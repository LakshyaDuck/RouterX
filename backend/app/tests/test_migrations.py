"""
Tests for how the app boots its database schema.

`database.init_db()` runs the Alembic migration chain in-process at startup,
which is a real design choice with real global side effects. These tests pin the
two that have already caused a bug, so a future change to the migration wiring
cannot silently reintroduce them.

The alternative to running migrations in-process is a separate deploy step,
which would need `alembic upgrade head` in the platform's start command and
would break `uvicorn main:app` as a standalone start command. The trade is
accepted; these tests are the cost of accepting it.
"""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, text

import app_settings
import database
from database import init_db


def _sentinel_logger(name: str) -> logging.Logger:
    """A logger that exists before init_db() runs, standing in for uvicorn.error."""
    logger = logging.getLogger(name)
    # `disabled` is what fileConfig flips; a logger with no handler and no
    # explicit level is exactly the shape uvicorn's loggers have at this point.
    logger.disabled = False
    return logger


def test_init_db_does_not_disable_existing_loggers(tmp_path: Path) -> None:
    """
    Running migrations must not silence loggers that already exist.

    This is the regression test for a bug that made the entire API invisible.
    migrations/env.py called `logging.config.fileConfig(config_file_name)`, and
    that function defaults to `disable_existing_loggers=True` — so applying
    migrations set `disabled = True` on every logger not named in alembic.ini,
    including `uvicorn.error` and `uvicorn.access`.

    The symptom was not a crash. The server booted, migrated, seeded, and served
    every request correctly, and then logged nothing at all: no access log, no
    "Application startup complete", no startup or error output. A working
    application with total silence, which is the version of this bug that
    reaches production.

    Runs against a throwaway SQLite file rather than the dev Postgres, because
    the mechanism under test is the logging side effect and not the DDL.
    """
    db_path = tmp_path / "migration_side_effects.db"
    engine = create_engine(f"sqlite:///{db_path}")
    # The migration chain has to see an empty database to run at all, which is
    # what causes fileConfig to be reached.
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE _probe (id INTEGER PRIMARY KEY)"))
        conn.commit()
    engine.dispose()

    sentinel = _sentinel_logger("uvicorn.error")
    app_logger = _sentinel_logger("main")
    original_dsn = database.DATABASE_URL
    database.DATABASE_URL = f"sqlite:///{db_path}"
    try:
        init_db()
    finally:
        database.DATABASE_URL = original_dsn

    assert sentinel.disabled is False, (
        "init_db() disabled the 'uvicorn.error' logger. migrations/env.py must "
        "pass disable_existing_loggers=False to logging.config.fileConfig, or "
        "the app boots, serves traffic, and logs nothing."
    )
    assert app_logger.disabled is False, (
        "init_db() disabled the app's own module logger; startup messages such "
        "as 'seeded demo scenario' would be silently dropped."
    )


def test_migrations_and_app_agree_on_the_database(tmp_path: Path) -> None:
    """
    Alembic must use the app's resolved DSN, not a second one derived separately.

    database.py resolves `DATABASE_URL = os.getenv("DATABASE_URL") or
    settings.postgres_dsn`. migrations/env.py used to read settings.postgres_dsn
    directly, so the two disagreed whenever DATABASE_URL was set and
    POSTGRES_DSN was not — exactly the configuration Render and Railway hand out.

    The failure is silent and severe: the app reads and writes one database
    while `alembic upgrade head` migrates a different one, so the schema the app
    sees never changes and every query fails against a schema that does not
    exist there.

    Asserts on the parsed AST rather than on the file text, because the
    explanation of this rule lives in a comment that necessarily names the
    forbidden expression — a substring check would fail on its own
    documentation.
    """
    env_path = Path(__file__).resolve().parents[1] / "migrations" / "env.py"
    tree = ast.parse(env_path.read_text())

    forbidden = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "postgres_dsn"
    ]
    assert not forbidden, (
        f"migrations/env.py still reads settings.postgres_dsn on line(s) "
        f"{forbidden}, which is a second and independent answer to "
        f"'which database?'"
    )

    # sqlalchemy.url must be set from the imported DATABASE_URL name.
    url_values = [
        arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_main_option"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "sqlalchemy.url"
        for arg in node.args[1:]
    ]
    assert url_values, "migrations/env.py never sets sqlalchemy.url"
    assert all(
        isinstance(value, ast.Name) and value.id == "DATABASE_URL"
        for value in url_values
    ), "sqlalchemy.url must be set from the imported DATABASE_URL"


def test_app_dsn_resolution_order() -> None:
    """
    DATABASE_URL wins over POSTGRES_DSN.

    Worth pinning because the precedence looks arbitrary until you know the
    host: managed platforms inject DATABASE_URL themselves, and a developer who
    set POSTGRES_DSN in .env would otherwise silently not be using it.
    """
    assert database.DATABASE_URL == (
        os.getenv("DATABASE_URL") or app_settings.settings.postgres_dsn
    )
