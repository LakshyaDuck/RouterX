"""
Test harness.

Two things live here, and both exist because of a specific failure mode rather
than for tidiness.

1. The test DSN is resolved and pushed into os.environ BEFORE anything from the
   app is imported. `database.py` reads DATABASE_URL once at module import and
   calls create_engine() there, so a conftest that set the variable after
   importing the app would be too late — the engine would already be bound to
   the development database. pytest imports conftest.py before it collects test
   modules, which is what makes the ordering below reliable rather than lucky.

2. The default is a throwaway SQLite file, not the development Postgres. Most of
   the suite this harness will grow to hold calls reset_fleet_database() or
   issues raw `DELETE FROM` in setup, and a conftest that quietly pointed those
   at the dev database would destroy real fleet data on every run. SQLite also
   means `pytest` works with no server running, which is what makes it usable as
   a per-phase gate. Set TEST_DATABASE_URL when a test genuinely needs Postgres
   semantics (the Postgres-only `ALTER TYPE` enum sync in init_db() is the main
   one); the same env-var path serves as the "isolated DSN" override that keeps
   destructive tests pointed at a throwaway database instead of dev.

   The dev Postgres is not reachable from SQLite tests, so `docker compose up`
   is not a prerequisite for `pytest` — only for exercising the real deployment.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _resolve_test_dsn() -> str:
    """
    Return the DSN tests must use.

    Order matters: an explicit TEST_DATABASE_URL always wins, then a
    DATABASE_URL with its database name swapped for a `_test` sibling (so a
    developer who exports DATABASE_URL still cannot have their dev data
    deleted), and only then the SQLite fallback.
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit

    dev_url = os.environ.get("DATABASE_URL")
    if dev_url:
        # "postgresql+psycopg://u:p@host:5432/vrp" -> ".../vrp_test". Done with
        # rsplit on "/" so it cannot mangle a password that contains a slash.
        scheme, _, tail = dev_url.rpartition("://")
        if not scheme:
            return dev_url
        netloc, slash, dbname = tail.rpartition("/")
        if not slash:
            return dev_url
        return f"{scheme}://{netloc}/{dbname}_test"

    tmp_dir = Path(tempfile.gettempdir()) / "routerx-test-dbs"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{tmp_dir / 'routerx_test.db'}"


# Must precede every app import — see the module docstring.
os.environ["DATABASE_URL"] = _resolve_test_dsn()

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app_settings import settings  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    """
    A session-scoped engine against the test DSN, with the schema created once.

    Deliberately NOT database.engine: that is the application engine, bound to
    whatever DATABASE_URL was set at import time, and tests must never share a
    connection pool with a server that might be running against it.
    """
    test_engine = create_engine(
        os.environ["DATABASE_URL"],
        echo=False,
        pool_pre_ping=True,
        # SQLite rejects concurrent writers; a single shared connection keeps
        # parallel test execution from turning into "database is locked".
        connect_args={"check_same_thread": False}
        if os.environ["DATABASE_URL"].startswith("sqlite")
        else {},
    )
    SQLModel.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine):
    """
    A transactional session rolled back after each test.

    Every table is truncated up front rather than relying on the rollback alone.
    The ported suite's convention is to call reset_fleet_database() or delete
    rows directly, and both would leave committed state behind for the next
    test if a previous one committed mid-transaction. Truncating makes each test
    independent regardless of what the previous one did — the property that
    actually matters, and the one that stops "passes alone, fails in a suite"
    from ever happening here.
    """
    # One DELETE per table, not `DELETE FROM a, b, c`. The comma form is
    # Postgres-only; SQLite parses it as a syntax error, which would have made
    # this harness silently Postgres-only — the opposite of what it is for.
    # Children before parents (reversed(sorted_tables)) so a foreign-key check
    # cannot fail on ordering.
    statements = [
        text(f'DELETE FROM "{table.name}"')
        for table in reversed(SQLModel.metadata.sorted_tables)
    ]
    with Session(engine) as db:
        for statement in statements:
            db.exec(statement)
        db.commit()
        yield db
        db.rollback()


@pytest.fixture(scope="session")
def app_settings():
    """The resolved settings object, for tests that assert on configuration."""
    return settings
