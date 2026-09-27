"""baseline: core fleet schema

The first migration in this project, and the reason `alembic` works at all.

RouterX scaffolded Alembic (alembic.ini, migrations/env.py) but never committed
a single revision, while `database.init_db()` created the schema with
`SQLModel.metadata.create_all()` on startup. That combination is not a working
migration setup, it is two owners racing: whichever runs first creates the
tables, and a subsequent `alembic upgrade head` then fails with "relation
already exists". It also means the schema has no history, so a change to
models.py cannot be reviewed as a diff.

This baseline is an explicit transcription of the seven tables in models.py
rather than a call to `metadata.create_all()` at migration time. That
distinction matters: a baseline that reads live metadata is not reproducible,
because editing models.py afterwards would silently change what this file "did"
when replayed against a fresh database.

Every statement is guarded on the existence of the object it creates, which is
unusual for a baseline and deliberate. See "Why this revision is guarded" below.

Note on the enum types — this is the part that is easy to get wrong, twice.
`sa.Enum(...)` inline in create_table makes Postgres create a real enum type per
column (deliverystatus, eventtype, vehiclestatus), and SQLAlchemy wires that up
as a table-level "before_create" hook. Alembic invokes that hook with
**checkfirst=False** — `alembic/ddl/impl.py:432` passes it explicitly, because
"create a table" is not a checkfirst operation. So an inline enum issues an
unconditional, un-deduplicated `CREATE TYPE`, with no existence check anywhere in
the path. An earlier version of this file carried a comment claiming the
opposite ("checkfirst=True means re-running is safe"); that was wrong, and it is
what made this revision fail on a real database with
`psycopg.errors.DuplicateObject: type "deliverystatus" already exists`.

Two objects per enum, one owner, is the fix: `*_OWNER` has create_type=True and
is created explicitly below; `*_COL` has create_type=False and goes into the
column definition, so the table-create hook stays quiet.

Why this revision is guarded
----------------------------
Because of the create_all history above, a database that ran the app before
Phase 0 already has all seven tables and all three enum types, and has NO
`alembic_version` row. That is not a hypothetical state — it is what the
production Postgres on Render is in right now, and an unguarded baseline
collides with it on the very first CREATE TYPE.

The guards are on the existence of tables and types, never on values, so they
cannot paper over a partial or corrupt schema: an object that already exists is
left exactly as it is, and one that is missing is created. What they buy is that
this revision is a no-op on an already-populated unversioned database and a
full build on a virgin one, and 0002 still adds the columns it needs either way.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — referenced via `sqlmodel.sql.sqltypes.AutoString`
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_VALUES = ("ACTIVE", "DELAYED", "BREAKDOWN", "NOTACTIVATED")
_DELIVERY_VALUES = ("PENDING", "IN_PROGRESS", "DELIVERED", "FAILED", "CANCELLED")
_EVENT_VALUES = (
    "TRAFFIC_UPDATE",
    "VEHICLE_BREAKDOWN",
    "NEW_DELIVERY",
    "DELIVERY_CANCELLED",
    "ROAD_BLOCKED",
    "TIME_WINDOW_CHANGE",
)

# The owners. These are the objects that issue CREATE TYPE, exactly once each,
# from `_create_enum` below.
VEHICLE_STATUS = sa.Enum(*_STATUS_VALUES, name="vehiclestatus")
DELIVERY_STATUS = sa.Enum(*_DELIVERY_VALUES, name="deliverystatus")
EVENT_TYPE = sa.Enum(*_EVENT_VALUES, name="eventtype")

# The column types, which must not. `create_type=False` is a postgresql.ENUM
# keyword — generic sa.Enum rejects it, because SchemaType.__init__ does not
# accept it and only the PG dialect defines the flag.
VEHICLE_STATUS_COL = postgresql.ENUM(
    *_STATUS_VALUES, name="vehiclestatus", create_type=False
)
DELIVERY_STATUS_COL = postgresql.ENUM(
    *_DELIVERY_VALUES, name="deliverystatus", create_type=False
)
EVENT_TYPE_COL = postgresql.ENUM(
    *_EVENT_VALUES, name="eventtype", create_type=False
)


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_enum(name: str) -> bool:
    """True if the Postgres type already exists. Only Postgres has named types."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    return bool(bind.dialect.has_type(bind, name))


def _create_enum(enum: sa.Enum) -> None:
    """
    Create the type, tolerating one that is already there.

    A second CREATE TYPE of the same name is an error, not a no-op, so the
    existence check is the whole point of this function.

    On a non-Postgres dialect this is a no-op rather than an error: sa.Enum is a
    SchemaType, so .create() dispatches to the dialect's implementation, which
    is sa.Enum itself on SQLite and therefore does nothing. That is what lets
    this revision run unchanged under the SQLite-backed migration tests.
    """
    if not _has_enum(enum.name):
        enum.create(op.get_bind(), checkfirst=True)


def upgrade() -> None:
    """Create the three enum types and the seven fleet tables."""
    for enum in (VEHICLE_STATUS, DELIVERY_STATUS, EVENT_TYPE):
        _create_enum(enum)

    if not _has_table("delivery"):
        op.create_table(
            "delivery",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("demand", sa.Float(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("time_window_start", sa.Float(), nullable=False),
            sa.Column("time_window_end", sa.Float(), nullable=False),
            sa.Column("status", DELIVERY_STATUS_COL, nullable=False),
            sa.Column(
                "assigned_vehicle", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("event"):
        op.create_table(
            "event",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("event_type", EVENT_TYPE_COL, nullable=False),
            sa.Column("timestamp", sa.Float(), nullable=False),
            sa.Column(
                "affected_entity_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("parameters", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("node"):
        op.create_table(
            "node",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("lat", sa.Float(), nullable=False),
            sa.Column("lon", sa.Float(), nullable=False),
            sa.Column("is_depot", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("road"):
        op.create_table(
            "road",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("from_node", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("to_node", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("distance", sa.Float(), nullable=False),
            sa.Column("base_time", sa.Float(), nullable=False),
            sa.Column("traffic_multiplier", sa.Float(), nullable=False),
            sa.Column("blocked", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("route"):
        op.create_table(
            "route",
            sa.Column("vehicle_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            # JSON, not a join table. The route is an ORDERED list of delivery ids
            # and the order is the route; a relational child table would make every
            # read a second query and every re-order a delete-and-reinsert.
            sa.Column("delivery_ids", sa.JSON(), nullable=True),
            sa.Column("total_distance", sa.Float(), nullable=False),
            sa.Column("total_travel_time", sa.Float(), nullable=False),
            sa.Column("total_load", sa.Float(), nullable=False),
            sa.Column("feasible", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("vehicle_id"),
        )

    if not _has_table("simulationmetadata"):
        op.create_table(
            "simulationmetadata",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("simulation_time", sa.Float(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("vehicle"):
        op.create_table(
            "vehicle",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("capacity", sa.Float(), nullable=False),
            sa.Column(
                "current_location", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("driver_hours_remaining", sa.Float(), nullable=False),
            sa.Column("status", VEHICLE_STATUS_COL, nullable=False),
            sa.Column("current_load", sa.Float(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    """
    Drop all seven tables and the three enum types.

    Dropped unconditionally, deliberately not mirroring the upgrade guards. A
    downgrade that respected "only drop what I created" would refuse to remove
    the tables on exactly the legacy unversioned databases where a downgrade is
    the thing you actually want — the inverse of the upgrade's situation.

    The enum types are dropped after the tables that depend on them, and
    guarded on existence, because on a legacy database the types predate this
    revision and are not ours to reason about.
    """
    for table in (
        "vehicle",
        "simulationmetadata",
        "route",
        "road",
        "node",
        "event",
        "delivery",
    ):
        if _has_table(table):
            op.drop_table(table)

    for enum in (EVENT_TYPE, DELIVERY_STATUS, VEHICLE_STATUS):
        if _has_enum(enum.name):
            enum.drop(op.get_bind(), checkfirst=True)
