"""Authentication and authorisation.

Two modes behind one interface:

* ``supabase`` (UAT, production): users sign in with Supabase Auth in the browser,
  passwordless (an emailed one-time code or link) or as a guest. The API verifies the access token Supabase issued: asymmetric
  keys from the project's JWKS endpoint, or the legacy shared HS256 secret. No password
  ever reaches this service.
* ``demo`` (local development): a one-click sign-in issues a short-lived token signed
  with ``FAB_AUTH_SECRET``. Settings refuse this mode in any environment other than
  ``local`` or ``test`` (staging and production included) unless
  ``FAB_ALLOW_DEMO_AUTH_IN_PRODUCTION`` opts in, and then only with a non-default secret.
  A deployment that sets ``FAB_ENV=local`` on a public host still gets demo sign-in, so
  ``FAB_ENV`` must be set truthfully (on Vercel it defaults to ``production``).

Guests (Supabase anonymous sign-in, no email) get ``FAB_GUEST_ROLE``, or are refused when
it's ``none``; that lets a public demo open in one click without weakening named accounts.

**Stream tickets.** ``EventSource`` can't send headers, so the SSE stream authenticates with a
query parameter. Rather than the long-lived access token (which would land in request logs
and go stale on the next refresh), the client asks ``POST /shifts/{id}/stream-ticket`` for a
90-second HMAC-signed ticket bound to the user, role, fabs and that one shift, and opens the
stream with ``?ticket=``. The ticket is signed with ``FAB_STREAM_TICKET_SECRET``, else the
configured JWT/demo signing secret; with neither, a per-process random key (which a deployment
running several instances must not rely on: a ticket from one instance would be refused by
another). ``?access_token=`` still works for one release and logs a deprecation warning.

Roles are ordered: ``viewer`` < ``dispatcher``. Viewers can plan, explore and watch live
shifts; dispatchers can also drive the clock, report tool-downs and call engineers off.
Each user also has a list of fabs they may see ("*" = all), which scopes every
fab-specific request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from functools import lru_cache
from typing import Literal

import jwt
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from .config import DEFAULT_AUTH_SECRET, Settings, get_settings

Role = Literal["viewer", "dispatcher"]
ROLE_RANK: dict[str, int] = {"viewer": 1, "dispatcher": 2}
DEMO_ISSUER, DEMO_AUDIENCE = "fab-dispatch-demo", "fab-dispatch"
DEMO_TTL_S = 12 * 3600
STREAM_TICKET_TTL_S = 90
log = logging.getLogger("fab")


class User(BaseModel):
    id: str
    email: str
    role: Role
    fabs: list[str]
    provider: Literal["demo", "supabase", "guest", "integration"]

    def can_access(self, fab_id: str) -> bool:
        return "*" in self.fabs or fab_id in self.fabs

    def at_least(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


def _unauthorised(msg: str = "Sign in required") -> HTTPException:
    return HTTPException(401, msg, headers={"WWW-Authenticate": "Bearer"})


# ----------------------------------------------------------------------------- demo
def issue_demo_token(role: Role, settings: Settings) -> str:
    now = int(time.time())
    claims = {
        "sub": f"demo-{role}",
        "email": f"{role}@demo.local",
        "role": role,
        "fabs": ["*"],
        "iss": DEMO_ISSUER,
        "aud": DEMO_AUDIENCE,
        "iat": now,
        "exp": now + DEMO_TTL_S,
    }
    return jwt.encode(claims, settings.auth_secret, algorithm="HS256")


def _verify_demo(token: str, settings: Settings) -> User:
    claims = jwt.decode(token, settings.auth_secret, algorithms=["HS256"], audience=DEMO_AUDIENCE, issuer=DEMO_ISSUER)
    return User(
        id=claims["sub"], email=claims["email"], role=claims["role"], fabs=claims.get("fabs", ["*"]), provider="demo"
    )


# ----------------------------------------------------------------------------- supabase
@lru_cache
def _jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def _verify_supabase(token: str, settings: Settings) -> User:
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
    alg = jwt.get_unverified_header(token).get("alg", "")
    if alg.startswith("HS"):
        if not settings.supabase_jwt_secret:
            raise jwt.InvalidTokenError("HS-signed token but no SUPABASE_JWT_SECRET configured")
        claims = jwt.decode(
            token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated", issuer=issuer
        )
    else:
        key = _jwks(settings.supabase_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["ES256", "RS256"], audience="authenticated", issuer=issuer)
    if claims.get("is_anonymous"):
        # Guest sign-in (Supabase anonymous user): no email; the role comes from settings.
        if settings.guest_role == "none":
            raise ValueError("guest access is disabled")
        return User(
            id=claims["sub"],
            email=f"guest-{claims['sub'][:6]}",
            role=settings.guest_role,
            fabs=list(settings.default_fabs),
            provider="guest",
        )
    email = (claims.get("email") or "").lower()
    meta = claims.get("app_metadata") or {}  # set by admins, not editable by users
    role = meta.get("role")
    if role not in ROLE_RANK:
        role = "dispatcher" if email in {e.lower() for e in settings.dispatcher_emails} else settings.default_role
    # Presence, not truthiness: an admin setting ``fabs: []`` revokes access to every fab; only a
    # user without the key falls back to the default (["*"] on the public demo: synthetic fabs).
    fabs = meta.get("fabs", settings.default_fabs)
    if not isinstance(fabs, list) or not all(isinstance(f, str) for f in fabs):
        raise ValueError("app_metadata.fabs must be a list of fab ids")
    return User(id=claims["sub"], email=email or claims["sub"], role=role, fabs=list(fabs), provider="supabase")


# ----------------------------------------------------------------------------- stream tickets
class InvalidTicket(ValueError):
    pass


@lru_cache
def _process_secret() -> bytes:
    return secrets.token_bytes(32)


def stream_ticket_secret(settings: Settings) -> bytes:
    """The key that signs stream tickets: ``FAB_STREAM_TICKET_SECRET``, else the Supabase JWT
    secret, else a non-default demo signing secret (or the demo secret itself in demo mode, which
    already signs the sessions), else a random key for this process only (warned once)."""
    if settings.stream_ticket_secret:
        return settings.stream_ticket_secret.encode()
    if settings.supabase_jwt_secret:
        return settings.supabase_jwt_secret.encode()
    if settings.auth_mode == "demo" or settings.auth_secret != DEFAULT_AUTH_SECRET:
        return settings.auth_secret.encode()
    if not _process_secret.cache_info().currsize:
        log.warning(
            "no FAB_STREAM_TICKET_SECRET (or JWT secret) configured: stream tickets are signed with a "
            "per-process key, so a deployment with several instances must set one"
        )
    return _process_secret()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_stream_ticket(user: User, shift_id: str, settings: Settings, ttl_s: int = STREAM_TICKET_TTL_S) -> str:
    """``<base64url payload>.<base64url HMAC-SHA256>``, bound to this user and this shift."""
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "fabs": user.fabs,
        "provider": user.provider,
        "shift": shift_id,
        "exp": int(time.time()) + ttl_s,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_b64(hmac.new(stream_ticket_secret(settings), body.encode(), hashlib.sha256).digest())}"


def verify_stream_ticket(ticket: str, shift_id: str, settings: Settings) -> User:
    body, _, sig = ticket.partition(".")
    try:
        expected = hmac.new(stream_ticket_secret(settings), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(sig), expected):
            raise InvalidTicket("invalid stream ticket")
        claims = json.loads(_unb64(body))
        if claims["exp"] < time.time():
            raise InvalidTicket("stream ticket expired; request a new one")
        if claims["shift"] != shift_id:
            raise InvalidTicket("stream ticket is for another shift")
        return User(
            id=claims["sub"],
            email=claims["email"],
            role=claims["role"],
            fabs=claims["fabs"],
            provider=claims["provider"],
        )
    except (ValueError, KeyError, TypeError) as e:  # bad base64/JSON/UTF-8, missing field, pydantic
        raise InvalidTicket(str(e) if isinstance(e, InvalidTicket) else "invalid stream ticket") from None


# ----------------------------------------------------------------------------- dependencies
def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    # EventSource can't set headers. The SSE stream alone accepts the access token as a query
    # parameter, deprecated in favour of a short-lived stream ticket (see the module docstring).
    if request.url.path.endswith("/stream") and (token := request.query_params.get("access_token")):
        log.warning("deprecated: stream opened with ?access_token=; use POST .../stream-ticket and ?ticket=")
        return token
    return None


def current_user(request: Request) -> User:
    settings = get_settings()
    if request.url.path.endswith("/stream") and (ticket := request.query_params.get("ticket")):
        try:
            user = verify_stream_ticket(ticket, str(request.path_params.get("shift_id", "")), settings)
        except InvalidTicket as e:
            raise _unauthorised(str(e)) from None
        request.state.user = user
        return user
    token = _token_from(request)
    if not token:
        raise _unauthorised()
    try:
        user = _verify_demo(token, settings) if settings.auth_mode == "demo" else _verify_supabase(token, settings)
    except jwt.ExpiredSignatureError:
        raise _unauthorised("Session expired; sign in again") from None
    except (jwt.InvalidTokenError, jwt.PyJWKClientError, KeyError, ValueError):
        raise _unauthorised("Invalid credentials") from None
    request.state.user = user
    return user


def require(role: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if not user.at_least(role):
            raise HTTPException(403, f"This action needs the {role} role")
        return user

    return dep


def check_fab(user: User, fab_id: str) -> None:
    if not user.can_access(fab_id):
        # 404, not 403: don't confirm that another customer's fab exists.
        raise HTTPException(404, f"fab {fab_id} not found")
