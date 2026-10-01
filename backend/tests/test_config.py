from app.config import Settings, libpq_url


def test_supabase_integration_url_is_cleaned_for_libpq():
    raw = "postgres://postgres.abc:pw@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require&supa=base-pooler.x"
    assert libpq_url(raw) == "postgres://postgres.abc:pw@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"


def test_supabase_gets_tls_even_without_sslmode():
    assert libpq_url("postgresql://u:p@db.x.supabase.co:5432/postgres").endswith("?sslmode=require")


def test_postgres_url_from_platform_integration_is_used(monkeypatch):
    monkeypatch.delenv("FAB_DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_URL", "postgres://u:p@h.pooler.supabase.com:6543/postgres?supa=x")
    s = Settings()
    assert s.is_postgres and s.database_url.endswith("?sslmode=require")


def test_explicit_setting_wins_over_platform_variable(monkeypatch):
    monkeypatch.setenv("FAB_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("POSTGRES_URL", "postgres://u:p@h/db")
    assert Settings().database_url == "sqlite:///:memory:"
