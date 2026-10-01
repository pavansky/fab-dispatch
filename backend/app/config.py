"""Runtime settings, read once from environment variables (prefix ``FAB_``) or ``.env``.

Local development needs none of them: the defaults give a SQLite store and an
in-memory Qdrant collection, so the brief's "no API keys, runs locally" rule holds.
Production sets ``FAB_DATABASE_URL`` (Supabase/any Postgres) and, optionally,
``FAB_QDRANT_URL``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAB_", env_file=".env", extra="ignore")

    env: str = Field("local", description="local | test | production")
    database_url: str = Field("sqlite:///./data/fab.db", description="sqlite:///path or postgresql://...")
    db_schema: str = Field(
        "public", pattern=r"^[a-z_][a-z0-9_]{0,62}$", description="Postgres schema; lets UAT share a database safely"
    )
    qdrant_url: str | None = Field(None, description="Qdrant server URL; unset = embedded local mode")
    qdrant_api_key: str | None = None
    qdrant_path: str | None = Field(
        None, description="optional on-disk path for embedded Qdrant; unset = in-memory per process"
    )
    ingest_tokens: dict[str, str] = Field(
        default_factory=dict,
        description="fab id -> SHA-256 hex of that fab's ingestion token, for equipment systems "
        "posting tool-downs (POST /api/ingest/tool-downs). Store hashes, never tokens.",
    )
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    solver_time_limit_s: float = Field(3.0, gt=0, le=20, description="safety cap for ALNS and PyVRP")
    alns_iterations: int = Field(300, ge=1, description="ALNS iteration budget (deterministic stop); see ANALYSIS §1")
    pyvrp_iterations: int = Field(
        1000, ge=1, description="PyVRP iteration budget (deterministic stop); see ANALYSIS §1"
    )
    live_time_limit_s: float = Field(0.6, gt=0, le=10, description="budget per live re-dispatch")
    sse_window_s: float = Field(25.0, gt=0, description="seconds an SSE response stays open (serverless-safe)")
    log_json: bool = False
    log_level: str = "INFO"
    profiles_dir: str | None = Field(None, description="directory of fab profile JSON files; unset = bundled")
    default_fab: str = Field("fab1-300mm-logic", description="fab used when a request doesn't name one")

    # ---- authentication ------------------------------------------------------------
    auth_mode: Literal["demo", "supabase"] = Field(
        "demo", description="demo = one-click local sign-in (refused in production); supabase = Supabase Auth"
    )
    auth_secret: str = Field("local-demo-signing-secret-not-for-production-use", description="signs demo-mode tokens")
    allow_demo_auth_in_production: bool = Field(False, description="explicit opt-in for a public demo deployment")
    supabase_url: str | None = Field(None, validation_alias=AliasChoices("FAB_SUPABASE_URL", "SUPABASE_URL"))
    supabase_publishable_key: str | None = Field(
        None,
        validation_alias=AliasChoices("FAB_SUPABASE_PUBLISHABLE_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"),
    )
    supabase_jwt_secret: str | None = Field(
        None, validation_alias=AliasChoices("FAB_SUPABASE_JWT_SECRET", "SUPABASE_JWT_SECRET")
    )
    dispatcher_emails: list[str] = Field(default_factory=list, description="bootstrap dispatchers by email")
    turnstile_site_key: str | None = Field(
        None, description="Cloudflare Turnstile site key (public); set when CAPTCHA is on in Supabase Auth"
    )
    guest_role: Literal["none", "viewer", "dispatcher"] = Field(
        "viewer", description="role for Supabase anonymous (guest) sign-ins; none = guests refused"
    )
    default_role: Literal["viewer", "dispatcher"] = "viewer"
    default_fabs: list[str] = Field(
        default_factory=lambda: ["*"], description="fabs a user can access unless their profile says otherwise"
    )
    cron_secret: str | None = Field(None, validation_alias=AliasChoices("FAB_CRON_SECRET", "CRON_SECRET"))

    # ---- assistant -----------------------------------------------------------------
    assistant_llm: Literal["none", "anthropic", "ollama"] = Field(
        "none", description="optional model that rewrites grounded answers; none = fully local, no key"
    )
    assistant_model: str | None = Field(None, description="model id; defaults per provider")
    anthropic_api_key: str | None = Field(
        None, validation_alias=AliasChoices("FAB_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"), repr=False
    )
    ollama_url: str = Field("http://127.0.0.1:11434", description="local Ollama server for assistant_llm=ollama")
    assistant_llm_timeout_s: float = Field(8.0, gt=0, le=30)

    @field_validator("database_url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        if not v.startswith(("sqlite:///", "postgresql://", "postgres://")):
            raise ValueError("FAB_DATABASE_URL must be sqlite:///... or postgresql://...")
        return v

    @model_validator(mode="after")
    def _platform_database(self) -> Settings:
        """Accept the variable that Vercel's Supabase/Postgres integrations inject
        (``POSTGRES_URL``, the pooled URL) when ``FAB_DATABASE_URL`` isn't set."""
        if "database_url" not in self.model_fields_set and os.environ.get("POSTGRES_URL"):
            self.database_url = os.environ["POSTGRES_URL"]
        if self.is_postgres:
            self.database_url = libpq_url(self.database_url)
        return self

    @model_validator(mode="after")
    def _serverless_defaults(self) -> Settings:
        """On Vercel only /tmp is writable. Without FAB_DATABASE_URL the app still boots
        (ephemeral SQLite per instance, fine for a demo); with it, state is durable and
        shared. Logs go out as JSON for the platform's log drain."""
        if os.environ.get("VERCEL"):
            if "database_url" not in self.model_fields_set:
                self.database_url = "sqlite:////tmp/fab.db"
            if "log_json" not in self.model_fields_set:
                self.log_json = True
            if self.env == "local":
                self.env = "production"
        return self

    @model_validator(mode="after")
    def _auth_safe(self) -> Settings:
        """Fail closed: demo sign-in must never be reachable in production by accident."""
        if self.env == "production" and self.auth_mode == "demo" and not self.allow_demo_auth_in_production:
            raise ValueError(
                "FAB_AUTH_MODE=demo is refused in production; use supabase "
                "(or set FAB_ALLOW_DEMO_AUTH_IN_PRODUCTION=true for a public demo)"
            )
        if self.auth_mode == "supabase" and not self.supabase_url:
            raise ValueError("FAB_AUTH_MODE=supabase needs SUPABASE_URL")
        if (
            self.env == "production"
            and self.auth_mode == "demo"
            and self.auth_secret == "local-demo-signing-secret-not-for-production-use"
        ):
            raise ValueError("set FAB_AUTH_SECRET when demo auth is allowed in production")
        return self

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql://", "postgres://"))


# Query parameters libpq understands; anything else (e.g. Supabase's ``supa=``) makes
# psycopg refuse the URL, so it is dropped.
_LIBPQ_PARAMS = {
    "sslmode",
    "sslrootcert",
    "sslcert",
    "sslkey",
    "connect_timeout",
    "application_name",
    "options",
    "target_session_attrs",
    "keepalives",
    "keepalives_idle",
    "gssencmode",
}


def libpq_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k in _LIBPQ_PARAMS]
    if "supabase" in parts.netloc and not any(k == "sslmode" for k, _ in query):
        query.append(("sslmode", "require"))
    return urlunsplit(parts._replace(query=urlencode(query)))


@lru_cache
def get_settings() -> Settings:
    return Settings()
