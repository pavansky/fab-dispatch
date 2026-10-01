"""Sign-in endpoints. The browser asks /config which mode is active, then either signs in
with Supabase directly (supabase mode) or calls /demo (local development only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import Role, User, current_user, issue_demo_token
from ..config import get_settings
from ..deps import get_store

router = APIRouter(prefix="/api/auth", tags=["auth"])


class DemoSignIn(BaseModel):
    role: Role = "dispatcher"


@router.get("/config")
def auth_config() -> dict:
    """Public: tells the UI how to sign in. The publishable key is designed to be public."""
    s = get_settings()
    out: dict = {"mode": s.auth_mode}
    if s.auth_mode == "supabase":
        out |= {
            "supabase_url": s.supabase_url,
            "supabase_publishable_key": s.supabase_publishable_key,
            "guest_role": None if s.guest_role == "none" else s.guest_role,
            # Supabase Auth verifies the token; the UI only needs the public site key.
            "captcha_site_key": s.turnstile_site_key,
        }
    else:
        out["demo_roles"] = ["dispatcher", "viewer"]
    return out


@router.post("/demo")
def demo_sign_in(req: DemoSignIn) -> dict:
    s = get_settings()
    if s.auth_mode != "demo":
        raise HTTPException(404, "demo sign-in is disabled")
    token = issue_demo_token(req.role, s)
    return {"access_token": token, "token_type": "bearer", "expires_in": 12 * 3600}


@router.get("/me", response_model=User)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.delete("/me")
def delete_me(user: User = Depends(current_user)) -> dict:
    """Delete your account and personal data (GDPR Art. 17). Feedback, presence and pending
    replays are deleted; your email in shared shift history becomes "a deleted user", so the
    audit trail keeps its shape without identifying you. On Supabase the sign-in account
    itself is removed too. Demo accounts are shared, so only their data is erased."""
    store = get_store()
    erased = store.delete_user_data(user.id, user.email)
    account = user.provider in ("supabase", "guest") and store.delete_auth_user(user.id)
    return {"erased": erased, "account_deleted": account}
