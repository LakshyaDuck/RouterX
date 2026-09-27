"""baseline: core fleet schema

The first migration in this project, and the reason `alembic` works at all.

RouterX scaffolded Alembic (alembic.ini, migrations/env.py) but never committed
a single revision, while `database.init_db()` created the schema with
`SQLModel.metadata.create_all()` on startup. That combination is not a working
migration setup, it is two owners racing: whichever runs first creates the
tables, and a subsequent `alembic upgrade head` then fails with "relation
already exists". It also means the schema has no history, so a change to
models.py cannot be reviewed as a diff.

This baseline is generated with `--autogenerate` against an empty database, so
it is an explicit transcription of the seven tables in models.py rather than a
call to `metadata.create_all()` at migration time. That distinction matters:
a baseline that reads live metadata is not reproducible, because editing
models.py afterwards would silently change what this file "did" when replayed
against a fresh database.

Note on the enum types: `sa.Enum(...)` inline in create_table makes Postgres
create a real enum type per column (deliverystatus, eventtype, vehiclestatus).
SQLAlchemy's create_type default emits the CREATE TYPE alongside the table, and
checkfirst=True means re-running is safe. A later migration that ADDS a value to
one of these must use a separate `op.execute("ALTER TYPE ... ADD VALUE")` — it
cannot be a create_table, because Postgres will not let you add a value inside
a transaction block on older versions, which is exactly the case
`database.init_db()`'s best-effort ALTER TYPE was papering over.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — referenced via `sqlmodel.sql.sqltypes.AutoString`
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the seven fleet tables."""
    op.create_table(
        "delivery",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("demand", sa.Float(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("time_window_start", sa.Float(), nullable=False),
        sa.Column("time_window_end", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "IN_PROGRESS",
                "DELIVERED",
                "FAILED",
                "CANCELLED",
                name="deliverystatus",
            ),
            nullable=False,
        ),
        sa.Column(
            "assigned_vehicle", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "event",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "TRAFFIC_UPDATE",
                "VEHICLE_BREAKDOWN",
                "NEW_DELIVERY",
                "DELIVERY_CANCELLED",
                "ROAD_BLOCKED",
                "TIME_WINDOW_CHANGE",
                name="eventtype",
            ),
            nullable=False,
        ),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column(
            "affected_entity_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "node",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("is_depot", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
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
    op.create_table(
        "simulationmetadata",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("simulation_time", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vehicle",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("capacity", sa.Float(), nullable=False),
        sa.Column(
            "current_location", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("driver_hours_remaining", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "DELAYED",
                "BREAKDOWN",
                "NOTACTIVATED",
                name="vehiclestatus",
            ),
            nullable=False,
        ),
        sa.Column("current_load", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """
    Drop all seven tables.

    Deliberately not reversible-by-default in spirit: the Postgres enum types
    (deliverystatus, eventtype, vehiclestatus) are left behind, because dropping
    a type that other objects might reference fails mid-transaction. They are
    harmless residue and a `DROP TYPE` can be added once something actually
    depends on them not existing.
    """
    op.drop_table("vehicle")
    op.drop_table("simulationmetadata")
    op.drop_table("route")
    op.drop_table("road")
    op.drop_table("node")
    op.drop_table("event")
    op.drop_table("delivery")
