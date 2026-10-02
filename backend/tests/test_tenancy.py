"""Database per fab: each fab's operational data lives only in its own database.

The API runs against three databases at once (the default, fab 1's and fab 2's) and every
assertion about isolation reads the databases directly, not through the API that wrote them."""

import hashlib
import os
import sqlite3
import uuid
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.config import get_settings
from app.main import app
from app.store import NotFound
from tests.conftest import auth_headers

FAB1, FAB2 = "fab1-300mm-logic", "fab2-200mm-analog"
FAB_TABLES = ("shifts", "shift_events", "assignments", "idempotency_keys", "plan_cache")
client = TestClient(app, headers=auth_headers("dispatcher"))


@pytest.fixture
def two_fab_databases(tmp_path, monkeypatch):
    paths = {FAB1: tmp_path / "fab1.db", FAB2: tmp_path / "fab2.db"}
    monkeypatch.setattr(get_settings(), "tenant_databases", {f: f"sqlite:///{p}" for f, p in paths.items()})
    deps.reset_stores()
    deps.all_stores()  # open and migrate every fab's database, as startup health checks do
    yield paths
    deps.reset_stores()


def _rows(path, table: str, where: str = "1=1") -> int:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def _shift(fab: str, seed: int = 3) -> str:
    sc = client.post("/api/scenario", json={"fab_id": fab, "seed": seed, "n_engineers": 6, "n_jobs": 16}).json()
    return client.post("/api/shifts", json={"scenario": sc, "algorithm": "greedy"}).json()["state"]["id"]


def test_each_fabs_data_lands_only_in_its_own_database(two_fab_databases):
    one, two = _shift(FAB1), _shift(FAB2)
    assert one.startswith(f"{FAB1}.") and two.startswith(f"{FAB2}.")
    for sid in (one, two):
        client.post(f"/api/shifts/{sid}/advance", json={"minutes": 60}, headers={"Idempotency-Key": f"k-{sid}"})
    sc = client.post("/api/scenario", json={"fab_id": FAB2, "seed": 4, "n_engineers": 5, "n_jobs": 12}).json()
    client.post("/api/plan", json={"scenario": sc, "algorithm": "greedy"})

    db1, db2 = two_fab_databases[FAB1], two_fab_databases[FAB2]
    # Fab 1's database holds fab 1's shift and nothing of fab 2's, and the reverse.
    assert _rows(db1, "shifts", f"id = '{one}'") == 1 and _rows(db1, "shifts", f"id = '{two}'") == 0
    assert _rows(db2, "shifts", f"id = '{two}'") == 1 and _rows(db2, "shifts", f"id = '{one}'") == 0
    for table, column in (("shift_events", "shift_id"), ("assignments", "shift_id")):
        assert _rows(db1, table, f"{column} = '{one}'") > 0 and _rows(db1, table, f"{column} = '{two}'") == 0
        assert _rows(db2, table, f"{column} = '{two}'") > 0 and _rows(db2, table, f"{column} = '{one}'") == 0
    assert _rows(db1, "idempotency_keys", f"key LIKE '%{two}%'") == 0
    assert _rows(db2, "idempotency_keys", f"key LIKE '%{two}%'") == 1
    assert _rows(db2, "plan_cache") >= 1 and _rows(db1, "plan_cache") == 0  # fab 2's plan is fab 2's data
    # And none of it reached the default database.
    for sid in (one, two):
        with pytest.raises(NotFound):
            deps.get_store().get_shift(sid)
    listed = {s["id"] for f in (FAB1, FAB2) for s in deps.get_store().list_shifts(f, 100)}
    assert one not in listed and two not in listed


def test_the_api_reads_each_fab_from_its_own_database(two_fab_databases):
    one, two = _shift(FAB1, 5), _shift(FAB2, 6)
    assert client.get(f"/api/shifts/{one}").json()["state"]["id"] == one
    assert client.get(f"/api/shifts/{two}").json()["state"]["id"] == two
    assert [s["id"] for s in client.get(f"/api/shifts?fab_id={FAB1}").json()] == [one]
    assert [s["id"] for s in client.get(f"/api/shifts?fab_id={FAB2}").json()] == [two]
    # A fab 2 shift addressed as if it were fab 1's is looked up in fab 1's database: not found.
    forged = f"{FAB1}.{two.split('.', 1)[1]}"
    assert client.get(f"/api/shifts/{forged}").status_code == 404


def test_ingestion_writes_to_the_fabs_own_database(two_fab_databases, monkeypatch):
    token = "tenancy-token"
    monkeypatch.setitem(get_settings().ingest_tokens, FAB1, hashlib.sha256(token.encode()).hexdigest())
    one = _shift(FAB1, 7)
    job = {
        "id": "MES-T1",
        "x": 40,
        "y": 30,
        "skill": "etch",
        "priority": 3,
        "earliest": 0,
        "latest": 60,
        "duration": 45,
    }
    r = TestClient(app).post(
        "/api/ingest/tool-downs",
        json={"fab_id": FAB1, "job": job},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "t1"},
    )
    assert r.status_code == 202 and r.json()["shift_id"] == one
    assert _rows(two_fab_databases[FAB1], "assignments", "job_id = 'MES-T1'") == 1
    assert _rows(two_fab_databases[FAB2], "assignments", "job_id = 'MES-T1'") == 0


def test_health_covers_every_database_and_deletion_reaches_them_all(two_fab_databases):
    health = client.get("/api/health").json()
    assert health["databases"] == 3 and health["db_ok"] and health["schema_ok"]
    assert client.get("/api/meta").json()["fab_databases"] == [FAB1, FAB2]
    one, two = _shift(FAB1, 8), _shift(FAB2, 9)
    erased = client.delete("/api/auth/me").json()["erased"]
    assert erased["shifts"] >= 2  # the demo user's shifts in both fab databases
    for path, sid in ((two_fab_databases[FAB1], one), (two_fab_databases[FAB2], two)):
        assert _rows(path, "shifts", f"id = '{sid}' AND created_by = 'a deleted user'") == 1


def test_fab_databases_must_be_real_urls():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(tenant_databases={FAB1: "mysql://nope"})


PG_URL = os.environ.get("FAB_TEST_PG_URL")


@pytest.mark.skipif(not PG_URL, reason="FAB_TEST_PG_URL not set")
def test_separate_postgres_databases_per_fab(monkeypatch):
    """Real separate Postgres databases (not schemas): created here, dropped afterwards."""
    import psycopg

    names = {FAB1: f"fab1_{uuid.uuid4().hex[:6]}", FAB2: f"fab2_{uuid.uuid4().hex[:6]}"}
    with psycopg.connect(PG_URL, autocommit=True) as c:
        for name in names.values():
            c.execute(f'CREATE DATABASE "{name}"')
    base = PG_URL.rsplit("/", 1)[0]
    try:
        monkeypatch.setattr(get_settings(), "tenant_databases", {f: f"{base}/{n}" for f, n in names.items()})
        deps.reset_stores()
        one, two = _shift(FAB1, 10), _shift(FAB2, 11)
        for fab, mine, theirs in ((FAB1, one, two), (FAB2, two, one)):
            with psycopg.connect(f"{base}/{names[fab]}") as c:
                assert c.execute("SELECT COUNT(*) FROM shifts WHERE id = %s", (mine,)).fetchone()[0] == 1
                assert c.execute("SELECT COUNT(*) FROM shifts WHERE id = %s", (theirs,)).fetchone()[0] == 0
                assert c.execute("SELECT COUNT(*) FROM assignments WHERE shift_id = %s", (mine,)).fetchone()[0] > 0
    finally:
        deps.reset_stores()
        with psycopg.connect(PG_URL, autocommit=True) as c:
            for name in names.values():
                c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
