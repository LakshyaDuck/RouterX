"""
PostgreSQL database layer using SQLModel ORM.
Supports environment variable DATABASE_URL for deployment (e.g. Render, Railway, AWS, Docker).
"""

import os
from typing import Generator, Optional

from sqlmodel import Session, create_engine, select

from app_settings import settings
from models import (
    Delivery,
    Event,
    FleetState,
    Node,
    Road,
    Route,
    SimulationMetadata,
    Vehicle,
)

# ---------------------------------------------------------------------------
# Database URL configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL") or settings.postgres_dsn

# Normalize the scheme so this works with whatever URL format the host
# injects. Render/Heroku/AWS hand out `postgres://` or a bare `postgresql://`
# with no driver suffix, and SQLAlchemy then defaults to psycopg2 — which is
# NOT installed here. This project is on psycopg3. Pinning the driver
# explicitly is what keeps that from becoming a ModuleNotFoundError at
# startup rather than a connection error.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://") :]

# Connection engine with pre-ping to ensure active connection
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions."""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """
    Bring the schema to head by running the Alembic migration chain.

    This used to be `SQLModel.metadata.create_all(engine)` plus a best-effort
    `ALTER TYPE ... ADD VALUE` block wrapped in a bare `except: pass`. Both were
    wrong, in ways that only showed up later:

      * create_all and Alembic are two owners of the same schema. Whichever ran
        first created the tables, and the other then failed — create_all with
        "relation already exists" the moment anyone ran `alembic upgrade head`
        against a database an app had already booted against.
      * The bare `except: pass` swallowed every failure, including a wrong DSN
        and a missing `eventtype`. An enum value that silently failed to be
        added is an insert error waiting to happen, reported from wherever it
        eventually surfaces rather than from the migration that should have
        added it.

    The 0001_baseline migration creates the enum types complete, so there is
    nothing left to patch up here. From this point on the rule is: the schema
    changes by adding a migration, and this function is the only thing that
    applies one.

    Runs in-process at startup rather than as a separate deploy step, which
    keeps `uvicorn main:app` a sufficient start command. The cost is that two
    processes booting against an empty database at the same instant can both
    decide to apply 0001 and the loser fails on "relation already exists".
    Postgres DDL is transactional, so this only bites when the api and worker
    containers start simultaneously against a brand-new volume; if that becomes
    a real failure rather than a theoretical one, the fix is a Postgres advisory
    lock around the upgrade, not a removal of this call.
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    # alembic.ini is the single source of truth for the migrations location: it
    # uses `%(here)s/migrations`, which resolves relative to the ini file itself,
    # so the app works regardless of the process's working directory.
    ini_path = Path(__file__).resolve().parent / "alembic.ini"
    command.upgrade(Config(str(ini_path)), "head")


# ---------------------------------------------------------------------------
# State Query & Persistence Helpers
# ---------------------------------------------------------------------------


def has_fleet_data(session: Optional[Session] = None) -> bool:
    """Check if vehicles/deliveries are already seeded in the database."""

    def _check(s: Session) -> bool:
        stmt = select(Vehicle).limit(1)
        return s.exec(stmt).first() is not None

    if session is not None:
        return _check(session)
    with Session(engine) as s:
        return _check(s)


def save_initial_fleet_state(
    vehicles: list[Vehicle],
    deliveries: list[Delivery],
    nodes: list[Node],
    roads: list[Road],
    routes: list[Route],
    session: Optional[Session] = None,
) -> None:
    """Seed initial fleet state into PostgreSQL."""

    def _save(s: Session) -> None:
        for n in nodes:
            s.merge(n)
        for r in roads:
            s.merge(r)
        for v in vehicles:
            s.merge(v)
        for d in deliveries:
            s.merge(d)
        for rt in routes:
            s.merge(rt)
        # Initialize simulation metadata if not present
        if not s.get(SimulationMetadata, "global"):
            s.add(SimulationMetadata(id="global", simulation_time=0.0))
        s.commit()

    if session is not None:
        _save(session)
    else:
        with Session(engine) as s:
            _save(s)


def seed_fleet_state(session: Optional[Session] = None) -> bool:
    """
    Insert the deterministic demo scenario if — and only if — the fleet is empty.

    Returns True if data was written, False if the database already had a fleet.

    Two properties this is careful about:

      * It never overwrites. `has_fleet_data()` is checked first, and the whole
        write goes through `save_initial_fleet_state`, which merges by primary
        key. Seeding is a bootstrap step, not a reset — restarting the API
        against a database that a user has been experimenting on must not
        silently restore the demo city over their changes. That is what
        `make reset-db` and the Phase 5/6 simulation endpoints are for.

      * It validates before it writes. `validate_demo_scenario()` returning
        non-empty raises rather than seeding. A half-valid scenario is worse
        than an unseeded one: the check exists precisely because the failure
        mode of hand-authored fixture data is a database that seeds cleanly and
        is subtly wrong, and a raise at bootstrap is the last cheap moment to
        notice.

    One empty Route per vehicle is seeded alongside, rather than waiting for the
    optimizer in Phase 3 to create them. Route.vehicle_id is the primary key, so
    "one route per vehicle" is a 1:1 invariant that holds from the first commit
    rather than from whenever the optimizer happened to land. The rows are
    zeroed placeholders — no stops, no distance — and Phase 3 overwrites them
    with a real plan. Seeding none would leave `/fleet/state` reporting
    `routes: []` for a phase, which reads as "the optimizer found nothing"
    rather than "the optimizer does not exist yet".
    """
    from demo_scenario import (
        build_demo_deliveries,
        build_demo_nodes,
        build_demo_roads,
        build_demo_vehicles,
        validate_demo_scenario,
    )

    problems = validate_demo_scenario()
    if problems:
        raise ValueError(
            "demo scenario failed validation, refusing to seed:\n  - "
            + "\n  - ".join(problems)
        )

    def _seed(s: Session) -> bool:
        if has_fleet_data(s):
            return False
        vehicles = build_demo_vehicles()
        save_initial_fleet_state(
            vehicles=vehicles,
            deliveries=build_demo_deliveries(),
            nodes=build_demo_nodes(),
            roads=build_demo_roads(),
            routes=[
                Route(
                    vehicle_id=vehicle.id,
                    delivery_ids=[],
                    total_distance=0.0,
                    total_travel_time=0.0,
                    total_load=0.0,
                    feasible=True,
                )
                for vehicle in vehicles
            ],
            session=s,
        )
        return True

    if session is not None:
        return _seed(session)
    with Session(engine) as s:
        return _seed(s)


def get_fleet_state(session: Optional[Session] = None) -> FleetState:
    """Retrieve full fleet state from PostgreSQL."""

    def _query(s: Session) -> FleetState:
        vehicles = list(s.exec(select(Vehicle)).all())
        deliveries = list(s.exec(select(Delivery)).all())
        nodes = list(s.exec(select(Node)).all())
        roads = list(s.exec(select(Road)).all())
        routes = list(s.exec(select(Route)).all())
        events = list(s.exec(select(Event).order_by(Event.timestamp.asc())).all())
        meta = s.get(SimulationMetadata, "global")
        sim_time = meta.simulation_time if meta else 0.0

        return FleetState(
            vehicles=vehicles,
            deliveries=deliveries,
            nodes=nodes,
            roads=roads,
            routes=routes,
            events=events,
            simulation_time=sim_time,
        )

    if session is not None:
        return _query(session)
    with Session(engine) as s:
        return _query(s)


def get_vehicles(session: Optional[Session] = None) -> list[Vehicle]:
    if session is not None:
        return list(session.exec(select(Vehicle)).all())
    with Session(engine) as s:
        return list(s.exec(select(Vehicle)).all())


def get_deliveries(session: Optional[Session] = None) -> list[Delivery]:
    if session is not None:
        return list(session.exec(select(Delivery)).all())
    with Session(engine) as s:
        return list(s.exec(select(Delivery)).all())


def get_routes(session: Optional[Session] = None) -> list[Route]:
    if session is not None:
        return list(session.exec(select(Route)).all())
    with Session(engine) as s:
        return list(s.exec(select(Route)).all())


def get_nodes(session: Optional[Session] = None) -> list[Node]:
    if session is not None:
        return list(session.exec(select(Node)).all())
    with Session(engine) as s:
        return list(s.exec(select(Node)).all())


def get_roads(session: Optional[Session] = None) -> list[Road]:
    if session is not None:
        return list(session.exec(select(Road)).all())
    with Session(engine) as s:
        return list(s.exec(select(Road)).all())


def get_events(session: Optional[Session] = None) -> list[Event]:
    if session is not None:
        return list(session.exec(select(Event).order_by(Event.timestamp.asc())).all())
    with Session(engine) as s:
        return list(s.exec(select(Event).order_by(Event.timestamp.asc())).all())


def append_event(event: Event, session: Optional[Session] = None) -> None:
    def _add(s: Session) -> None:
        s.add(event)
        s.commit()
        s.refresh(event)

    if session is not None:
        _add(session)
    else:
        with Session(engine) as s:
            _add(s)
