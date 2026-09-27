from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import the app's RESOLVED database URL, not settings.postgres_dsn directly.
#
# database.py computes DATABASE_URL as `os.getenv("DATABASE_URL") or
# settings.postgres_dsn` and then normalises the driver. Reading settings here
# instead created two independent answers to "which database?", which disagree
# the moment DATABASE_URL is set and POSTGRES_DSN is not — a configuration
# Render and Railway both hand out. The result is the worst version of this
# class of bug: the app connects to database A while `alembic upgrade head`
# quietly migrates database B, and the schema the app sees never changes.
#
# One resolver, one answer, and the tests' DSN override reaches migrations too.
from database import DATABASE_URL

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
#
# disable_existing_loggers=False is load-bearing, and omitting it is a silent,
# app-wide failure that is very hard to see from the symptom.
#
# logging.config.fileConfig defaults to disable_existing_loggers=True: every
# logger that already exists and is NOT named in alembic.ini gets
# `disabled = True`. Because database.init_db() runs the migration chain
# in-process at startup, that reaches loggers this file has never heard of —
# uvicorn.error, uvicorn.access, and the app's own module logger.
#
# What it looks like: the server boots, applies migrations, seeds correctly, and
# serves every request — and then logs nothing more. Not one access log, no
# "Application startup complete", no startup or error output. The application is
# working perfectly and is completely invisible. The only reason this is caught
# at all is that a missing access log is noticeable; had the last line uvicorn
# emits been something nobody would look for, it would have shipped.
#
# Passing False keeps alembic.ini's own logger configuration (so `alembic
# upgrade` from a terminal still logs as it always did) without silencing
# anyone else.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Import the model modules so their tables are registered in `metadata` before
# `context.configure` diffs against it.
#
# `import models` is the load-bearing part, and it looks like a no-op because it
# binds no name — that is exactly why it is easy to drop. SQLModel registers
# table metadata as an import side effect, so without this line
# `SQLModel.metadata` is EMPTY: `alembic revision --autogenerate` then sees a
# database full of tables and an empty target and helpfully proposes dropping
# all of them.
#
# Both imports sit below `config.set_main_option`, which must run against the
# DSN this same Settings object provides. E402 and I001 are disabled for this
# file in pyproject.toml rather than inline: the ordering here is dictated by
# Alembic's template, so it should read as one explained exception rather than
# three scattered suppressions.
import models  # noqa: F401
from sqlmodel import SQLModel

target_metadata = SQLModel.metadata


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """
    Only ever consider tables SQLModel knows about.

    The database image is postgis/postgis, and its `postgis_tiger_geocoder`
    extension installs roughly a hundred tables of its own (tiger, topology,
    spatial_ref_sys, ...). Alembic compares "everything in the database"
    against "everything in target_metadata", so a table present in one and
    absent from the other is a difference — and since the geocoder tables are
    absent from our models, autogenerate helpfully emits a DROP for every one
    of them. Applying that would uninstall the extension.

    `compare_to is None` is the signal for "the database has this, the models
    do not". Returning False for those means Alembic will not propose dropping
    a table just because no model maps to it.

    The tradeoff, stated plainly: as a result, deleting a SQLModel class no
    longer auto-generates a DROP TABLE for it. That is the safer direction to
    err — a migration that silently drops a table because someone deleted a
    class is unrecoverable, while one that leaves an orphan behind is a line of
    SQL you write on purpose. Reintroduce drops by hand when you mean them.
    """
    if type_ == "table" and reflected and compare_to is None:
        return False
    return True


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
