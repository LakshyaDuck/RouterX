"""add simulation clock columns to simulationmetadata

models.py gained `simulation_start_time`, `is_running` and `speed_multiplier`
on SimulationMetadata without a migration, so the ORM asked for three columns
the schema did not have. Every read of the row failed with
`no such column: simulationmetadata.simulation_start_time` — which is what
`database.get_fleet_state()` does on its way to building FleetState, so this
reached essentially every endpoint, not just the simulation ones.

A second migration rather than an edit to 0001, on purpose. 0001 has already
been applied: the dev Postgres volume is stamped `0001_baseline`, and Render's
Postgres is a managed database that outlives a deploy. Rewriting the body of an
applied revision changes nothing for those databases — Alembic skips it by
revision id, so the columns would appear on a freshly created database and
silently not appear anywhere that already ran 0001. That is the worst shape for
a schema fix: it works in the one place nobody tests and fails in the one place
that matters. Adding a revision makes the change apply uniformly to new and
existing databases alike, and it is what `database.init_db()`'s docstring
already prescribes — "the schema changes by adding a migration".

The `server_default` on each column is required, not decorative. These are NOT
NULL columns being added to a table that already holds the `global` row on any
database that has ever booted the app, and Postgres rejects a NOT NULL column
with no default against a non-empty table. The defaults match the Python-side
defaults in models.py (`""`, `False`, `1.0`), so the existing row backfills to
exactly the state a fresh `SimulationMetadata(id="global")` would have produced.
They are deliberately left in place afterwards rather than dropped: they cost
nothing, they make the column safe to insert without naming it, and dropping a
default is a table rewrite on SQLite for no benefit.

Revision ID: 0002_simulation_clock
Revises: 0001_baseline
Create Date: 2026-09-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — referenced via `sqlmodel.sql.sqltypes.AutoString`
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_simulation_clock"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the three simulation clock columns to simulationmetadata."""
    op.add_column(
        "simulationmetadata",
        sa.Column(
            "simulation_start_time",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "simulationmetadata",
        sa.Column(
            "is_running",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "simulationmetadata",
        sa.Column(
            "speed_multiplier",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
    )


def downgrade() -> None:
    """
    Drop the three simulation clock columns.

    This is genuinely destructive of data and the round trip is not clean: a
    row that existed before 0002 keeps its id, and going back down leaves
    `simulation_start_time`/clock state permanently gone rather than
    reconstructed. It exists because a downgrade that fails halfway is worse
    than one that completes, not because anyone should run it in production.
    """
    op.drop_column("simulationmetadata", "speed_multiplier")
    op.drop_column("simulationmetadata", "is_running")
    op.drop_column("simulationmetadata", "simulation_start_time")
