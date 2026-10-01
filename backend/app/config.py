"""Runtime settings, read once from environment variables (prefix ``FAB_``) or ``.env``.

Local development needs none of them: the defaults give an in-process SQLite store and
an embedded Qdrant collection, so the brief's "no API keys, runs locally" rule holds.
Production sets ``FAB_DATABASE_URL`` (Supabase/any Postgres) and, optionally,
``FAB_QDRANT_URL``.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAB_", env_file=".env", extra="ignore")

    env: str = Field("local", description="local | test | production")
    database_url: str = Field("sqlite:///./data/fab.db", description="sqlite:///path or postgresql://...")
    qdrant_url: str | None = Field(None, description="Qdrant server URL; unset = embedded local mode")
    qdrant_api_key: str | None = None
    qdrant_path: str = Field("./data/qdrant", description="on-disk path for embedded Qdrant")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    solver_time_limit_s: float = Field(3.0, gt=0, le=20, description="safety cap for ALNS and PyVRP")
    alns_iterations: int = Field(600, ge=1, description="ALNS iteration budget (deterministic stop)")
    pyvrp_iterations: int = Field(3000, ge=1, description="PyVRP iteration budget (deterministic stop)")
    live_time_limit_s: float = Field(0.6, gt=0, le=10, description="budget per live re-dispatch")
    sse_window_s: float = Field(25.0, gt=0, description="seconds an SSE response stays open (serverless-safe)")
    log_json: bool = False
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        if not v.startswith(("sqlite:///", "postgresql://", "postgres://")):
            raise ValueError("FAB_DATABASE_URL must be sqlite:///... or postgresql://...")
        return v

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql://", "postgres://"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
