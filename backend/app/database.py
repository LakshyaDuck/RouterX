"""
PostgreSQL database layer using SQLModel ORM.
Supports environment variable DATABASE_URL for deployment (e.g. Render, Railway, AWS, Docker).
"""

import os
from typing import Generator, Optional

from sqlmodel import Session, SQLModel, create_engine, select

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

# Normalize legacy postgres:// prefix (common on Heroku/Render) to postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Connection engine with pre-ping to ensure active connection
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions."""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create all SQLModel tables in PostgreSQL and sync enums."""
    SQLModel.metadata.create_all(engine)
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(
                text(
                    "ALTER TYPE eventtype ADD VALUE IF NOT EXISTS 'TIME_WINDOW_CHANGE'"
                )
            )
            conn.execute(
                text("ALTER TYPE vehiclestatus ADD VALUE IF NOT EXISTS 'NOTACTIVATED'")
            )
            conn.commit()
    except Exception:
        pass


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
