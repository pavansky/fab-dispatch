"""Authentication and authorisation.

Two modes behind one interface:

* ``supabase`` (UAT, production): users sign in with Supabase Auth in the browser,
  passwordless (an emailed one-time code or link) or as a guest. The API verifies the access token Supabase issued: asymmetric
  keys from the project's JWKS endpoint, or the legacy shared HS256 secret. No password
  ever reaches this service.
* ``demo`` (local development): a one-click sign-in issues a short-lived token signed
  with ``FAB_AUTH_SECRET``. Settings refuse this mode in production unless explicitly
  allowed, so it cannot leak into a real deployment.

Guests (Supabase anonymous sign-in, no email) get ``FAB_GUEST_ROLE``, or are refused when
it's ``none``; that lets a public demo open in one click without weakening named accounts.

Roles are ordered: ``viewer`` < ``dispatcher``. Viewers can plan, explore and watch live
shifts; dispatchers can also drive the clock, report tool-downs and call engineers off.
Each user also has a list of fabs they may see ("*" = all), which scopes every
fab-specific request.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Literal

import jwt
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from .config import Settings, get_settings

Role = Literal["viewer", "dispatcher"]
ROLE_RANK: dict[str, int] = {"viewer": 1, "dispatcher": 2}
DEMO_ISSUER, DEMO_AUDIENCE = "fab-dispatch-demo", "fab-dispatch"
DEMO_TTL_S = 12 * 3600


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
    fabs = meta.get("fabs") or settings.default_fabs
    return User(id=claims["sub"], email=email or claims["sub"], role=role, fabs=list(fabs), provider="supabase")


# ----------------------------------------------------------------------------- dependencies
def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    # EventSource can't set headers, so the SSE stream alone accepts the token as a query parameter.
    if request.url.path.endswith("/stream"):
        return request.query_params.get("access_token")
    return None


def current_user(request: Request) -> User:
    token = _token_from(request)
    if not token:
        raise _unauthorised()
    settings = get_settings()
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
