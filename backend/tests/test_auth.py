"""Authentication, roles and fab isolation."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import _verify_supabase
from app.config import Settings
from app.main import app
from tests.conftest import auth_headers

anon = TestClient(app)
viewer = TestClient(app, headers=auth_headers("viewer"))
dispatcher = TestClient(app, headers=auth_headers("dispatcher"))


def test_public_endpoints_need_no_token():
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/auth/config").json()["mode"] == "demo"


def test_everything_else_requires_sign_in():
    for method, path in [
        ("get", "/api/fabs"),
        ("post", "/api/scenario"),
        ("post", "/api/plan"),
        ("get", "/api/shifts?fab_id=fab1-300mm-logic"),
        ("post", "/api/repairs/similar"),
    ]:
        r = getattr(anon, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 401, path
        assert r.headers["www-authenticate"] == "Bearer"


def test_forged_and_expired_tokens_are_rejected():
    forged = jwt.encode(
        {
            "sub": "x",
            "role": "dispatcher",
            "email": "x@y",
            "aud": "fab-dispatch",
            "iss": "fab-dispatch-demo",
            "exp": time.time() + 60,
        },
        "wrong-secret-of-sufficient-length-1234",
    )
    assert anon.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    from app.config import get_settings

    expired = jwt.encode(
        {
            "sub": "x",
            "role": "dispatcher",
            "email": "x@y",
            "aud": "fab-dispatch",
            "iss": "fab-dispatch-demo",
            "exp": time.time() - 10,
        },
        get_settings().auth_secret,
    )
    r = anon.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"]


def test_demo_sign_in_issues_a_working_token():
    token = anon.post("/api/auth/demo", json={"role": "viewer"}).json()["access_token"]
    me = anon.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "viewer" and me["provider"] == "demo"


def test_viewers_cannot_change_live_shifts():
    sc = viewer.post("/api/scenario", json={"seed": 2, "n_engineers": 5, "n_jobs": 12}).json()
    assert viewer.post("/api/plan", json={"scenario": sc, "algorithm": "greedy"}).status_code == 200
    r = viewer.post("/api/shifts", json={"scenario": sc, "algorithm": "greedy"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    sid = dispatcher.post("/api/shifts", json={"scenario": sc, "algorithm": "greedy"}).json()["state"]["id"]
    assert viewer.get(f"/api/shifts/{sid}").status_code == 200
    assert viewer.post(f"/api/shifts/{sid}/advance", json={"minutes": 10}).status_code == 403


def test_users_only_see_their_fabs():
    from app.auth import User
    from app.validation import fab_for

    fab1_only = User(id="u", email="u@x", role="dispatcher", fabs=["fab1-300mm-logic"], provider="demo")
    assert fab_for(fab1_only, "fab1-300mm-logic").id == "fab1-300mm-logic"
    with pytest.raises(Exception) as e:
        fab_for(fab1_only, "fab2-200mm-analog")
    assert e.value.status_code == 404  # 404, not 403: don't reveal another customer's fab


def test_demo_mode_is_refused_in_production():
    with pytest.raises(ValueError, match="refused in production"):
        Settings(env="production", auth_mode="demo")
    with pytest.raises(ValueError, match="FAB_AUTH_SECRET"):
        Settings(env="production", auth_mode="demo", allow_demo_auth_in_production=True)


def test_supabase_tokens_map_roles_and_fabs():
    s = Settings(
        auth_mode="supabase",
        supabase_url="https://abc.supabase.co",
        supabase_jwt_secret="super-secret-jwt-key-for-tests-only-123456",
        dispatcher_emails=["Lead@Fab.com"],
        default_role="viewer",
    )

    def token(email, meta=None):
        return jwt.encode(
            {
                "sub": email,
                "email": email,
                "aud": "authenticated",
                "iss": "https://abc.supabase.co/auth/v1",
                "exp": time.time() + 60,
                "app_metadata": meta or {},
            },
            s.supabase_jwt_secret,
        )

    assert _verify_supabase(token("lead@fab.com"), s).role == "dispatcher"  # bootstrap allow-list
    assert _verify_supabase(token("op@fab.com"), s).role == "viewer"  # least privilege by default
    u = _verify_supabase(token("op@fab.com", {"role": "dispatcher", "fabs": ["fab2-200mm-analog"]}), s)
    assert u.role == "dispatcher" and u.fabs == ["fab2-200mm-analog"]  # admin-set metadata wins
    bad = jwt.encode(
        {"sub": "x", "aud": "authenticated", "iss": "https://evil.example/auth/v1", "exp": time.time() + 60},
        s.supabase_jwt_secret,
    )
    with pytest.raises(jwt.InvalidIssuerError):
        _verify_supabase(bad, s)


def _anonymous_token(s: Settings, extra: dict | None = None) -> str:
    claims = {
        "sub": "8f2c1e9a-0000-4000-8000-000000000001",
        "is_anonymous": True,
        "aud": "authenticated",
        "iss": "https://abc.supabase.co/auth/v1",
        "exp": time.time() + 60,
        **(extra or {}),
    }
    return jwt.encode(claims, s.supabase_jwt_secret)


@pytest.mark.parametrize("guest_role", ["viewer", "dispatcher"])
def test_guests_get_the_configured_role_and_a_label_not_an_email(guest_role):
    s = Settings(
        auth_mode="supabase",
        supabase_url="https://abc.supabase.co",
        supabase_jwt_secret="super-secret-jwt-key-for-tests-only-123456",
        guest_role=guest_role,
    )
    u = _verify_supabase(_anonymous_token(s), s)
    assert (u.role, u.provider, u.email) == (guest_role, "guest", "guest-8f2c1e")
    assert u.fabs == s.default_fabs


def test_guests_cannot_raise_their_own_role_and_can_be_refused():
    s = Settings(
        auth_mode="supabase",
        supabase_url="https://abc.supabase.co",
        supabase_jwt_secret="super-secret-jwt-key-for-tests-only-123456",
        guest_role="viewer",
        dispatcher_emails=["anyone@x.com"],
    )
    sneaky = _anonymous_token(s, {"email": "anyone@x.com", "app_metadata": {"role": "dispatcher"}})
    assert _verify_supabase(sneaky, s).role == "viewer"
    with pytest.raises(ValueError, match="guest access is disabled"):
        _verify_supabase(_anonymous_token(s), Settings(**{**s.model_dump(), "guest_role": "none"}))


def test_auth_config_tells_the_ui_whether_guests_are_welcome(monkeypatch):
    from app.routes import auth as auth_routes

    base = {"auth_mode": "supabase", "supabase_url": "https://abc.supabase.co", "supabase_publishable_key": "pk"}
    monkeypatch.setattr(auth_routes, "get_settings", lambda: Settings(**base, guest_role="dispatcher"))
    assert auth_routes.auth_config()["guest_role"] == "dispatcher"
    monkeypatch.setattr(auth_routes, "get_settings", lambda: Settings(**base, guest_role="none"))
    assert auth_routes.auth_config()["guest_role"] is None
