"""
PostgreSQL database layer using SQLModel ORM.
Supports environment variable DATABASE_URL for deployment (e.g. Render, Railway, AWS, Docker).
"""

import os
import logging
from typing import Generator, Optional
from sqlmodel import SQLModel, create_engine, Session, select

from app.models import (
    Vehicle, Delivery, Node, Road, Route, Event,
    SimulationMetadata, FleetState, VehicleStatus, DeliveryStatus
)
from app.time_utils import get_current_local_iso, to_datetime
from app.config import (
    DATABASE_URL, DB_POOL_SIZE, DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE, DB_POOL_PRE_PING, LOG_LEVEL
)

logger = logging.getLogger("routerx.database")

# ---------------------------------------------------------------------------
# Database URL configuration
# ---------------------------------------------------------------------------

# Connection engine with pre-ping, connection pooling, and connection recycling
engine = create_engine(
    DATABASE_URL,
    echo=(LOG_LEVEL == "DEBUG"),
    pool_pre_ping=DB_POOL_PRE_PING,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_recycle=DB_POOL_RECYCLE,
)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions."""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create all SQLModel tables in PostgreSQL and sync enums and columns."""
    SQLModel.metadata.create_all(engine)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TYPE eventtype ADD VALUE IF NOT EXISTS 'TIME_WINDOW_CHANGE'"))
            conn.execute(text("ALTER TYPE vehiclestatus ADD VALUE IF NOT EXISTS 'NOTACTIVATED'"))
            conn.execute(text("ALTER TYPE deliverystatus ADD VALUE IF NOT EXISTS 'CANCELLED'"))
            conn.execute(text("ALTER TABLE simulationmetadata ADD COLUMN IF NOT EXISTS simulation_start_time VARCHAR DEFAULT '';"))
            conn.execute(text("ALTER TABLE simulationmetadata ADD COLUMN IF NOT EXISTS is_running BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE simulationmetadata ADD COLUMN IF NOT EXISTS speed_multiplier FLOAT DEFAULT 1.0;"))
            conn.commit()
    except Exception as e:
        logger.debug("Schema migration sync check completed: %s", e)



# ---------------------------------------------------------------------------
# State Query & Persistence Helpers
# ---------------------------------------------------------------------------

def has_fleet_data(session: Optional[Session] = None) -> bool:
    """Check if the network/fleet database is initialized."""
    def _check(s: Session) -> bool:
        stmt = select(Node).limit(1)
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
            s.add(SimulationMetadata(
                id="global",
                simulation_time=0.0,
                simulation_start_time=get_current_local_iso(),
                is_running=False,
                speed_multiplier=1.0,
            ))
        s.commit()

    if session is not None:
        _save(session)
    else:
        with Session(engine) as s:
            _save(s)


def get_fleet_state(session: Optional[Session] = None) -> FleetState:
    """Retrieve full fleet state from PostgreSQL, dynamically time-aware."""
    def _query(s: Session) -> FleetState:
        vehicles = list(s.exec(select(Vehicle)).all())
        deliveries = list(s.exec(select(Delivery)).all())
        nodes = list(s.exec(select(Node)).all())
        roads = list(s.exec(select(Road)).all())
        routes = list(s.exec(select(Route)).all())
        events = list(s.exec(select(Event).order_by(Event.timestamp.asc())).all())
        meta = s.get(SimulationMetadata, "global")
        sim_time = meta.simulation_time if meta else 0.0
        start_time_iso = (meta.simulation_start_time if meta and meta.simulation_start_time else "") or get_current_local_iso()
        is_running = meta.is_running if meta else False
        speed_mult = meta.speed_multiplier if meta else 1.0

        if meta and not meta.simulation_start_time:
            meta.simulation_start_time = start_time_iso
            s.add(meta)
            s.commit()

        # Dynamically determine time-dependent vehicle positions and delivery lifecycle
        if routes and vehicles and deliveries and nodes and roads:
            try:
                from app.optimizer import simulate_route_timeline
                from app.routing import build_graph

                graph = build_graph(nodes, roads)
                deliveries_dict = {d.id: d for d in deliveries}
                SERVICE_TIME = 5.0

                for r in routes:
                    v = next((veh for veh in vehicles if veh.id == r.vehicle_id), None)
                    if not v or getattr(v.status, "value", v.status) == "BREAKDOWN":
                        continue

                    sim = simulate_route_timeline(r.delivery_ids, v, deliveries_dict, graph, service_time=SERVICE_TIME, start_time=0.0)
                    arrival_times = sim.get("arrival_times", {})

                    curr_loc = "depot"
                    for did in r.delivery_ids:
                        d = deliveries_dict.get(did)
                        if not d:
                            continue
                        arr_t = arrival_times.get(did)
                        if arr_t is None:
                            continue
                        serv_start = max(arr_t, d.time_window_start)
                        serv_end = serv_start + SERVICE_TIME

                        # Time-aware delivery lifecycle
                        if getattr(d.status, "value", d.status) != "CANCELLED":
                            if sim_time < arr_t:
                                d.status = DeliveryStatus.PENDING
                            elif arr_t <= sim_time < serv_end:
                                d.status = DeliveryStatus.IN_PROGRESS
                                curr_loc = d.location
                            elif sim_time >= serv_end:
                                d.status = DeliveryStatus.DELIVERED
                                curr_loc = d.location

                    final_ret = sim.get("final_return_time", 0.0)
                    if sim_time >= final_ret and r.delivery_ids:
                        curr_loc = "depot"

                    v.current_location = curr_loc
            except Exception:
                pass

        from app.optimizer import compute_fleet_metrics
        fleet_metrics = compute_fleet_metrics(routes, vehicles, deliveries, nodes, roads)

        active_veh = sum(1 for v in vehicles if getattr(v.status, "value", v.status) == "ACTIVE")
        broken_veh = sum(1 for v in vehicles if getattr(v.status, "value", v.status) == "BREAKDOWN")
        pending_del = sum(1 for d in deliveries if getattr(d.status, "value", d.status) == "PENDING")
        delivered = sum(1 for d in deliveries if getattr(d.status, "value", d.status) == "DELIVERED")

        metrics = {
            "total_distance": fleet_metrics["total_distance"],
            "total_travel_time": fleet_metrics["total_travel_time"],
            "total_vehicles": len(vehicles),
            "active_vehicles": active_veh,
            "broken_vehicles": broken_veh,
            "total_deliveries": len(deliveries),
            "pending_deliveries": pending_del,
            "completed_deliveries": delivered,
            "total_violations": fleet_metrics["total_violations"],
            "capacity_violations": fleet_metrics["capacity_violations"],
            "time_window_violations": fleet_metrics["time_window_violations"],
            "driver_hour_violations": fleet_metrics["driver_hour_violations"],
            "assignment_violations": fleet_metrics["assignment_violations"],
            "unreachable_routes": fleet_metrics["unreachable_routes"],
            "failed_deliveries": fleet_metrics["failed_deliveries"],
            "unassigned_deliveries": fleet_metrics["unassigned_deliveries"],
            "infeasible_routes": fleet_metrics["infeasible_routes"],
            "route_violations": fleet_metrics["total_violations"],
            "violations": fleet_metrics["violations"],
        }

        return FleetState(
            vehicles=vehicles,
            deliveries=deliveries,
            nodes=nodes,
            roads=roads,
            routes=routes,
            events=events,
            simulation_time=sim_time,
            simulation_start_time=start_time_iso,
            current_simulation_time=to_datetime(start_time_iso, sim_time).isoformat(),
            is_running=is_running,
            speed_multiplier=speed_mult,
            metrics=metrics,
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


def reset_fleet_database(session: Optional[Session] = None, start_time: Optional[str] = None) -> FleetState:
    """
    Reset PostgreSQL database to the fixed deterministic demo scenario:
      - 8 vehicles
      - 40 deliveries
      - 25 nodes
      - 45 roads
      - Initial feasible routes computed deterministically
    """
    from simulation.demo_scenario import get_demo_scenario
    from app.optimizer import generate_initial_plan
    from sqlalchemy import text

    def _reset(s: Session) -> FleetState:
        # Delete existing records in dependency order
        s.execute(text("DELETE FROM event;"))
        s.execute(text("DELETE FROM route;"))
        s.execute(text("DELETE FROM delivery;"))
        s.execute(text("DELETE FROM vehicle;"))
        s.execute(text("DELETE FROM road;"))
        s.execute(text("DELETE FROM node;"))
        s.commit()

        sc = get_demo_scenario()
        nodes = sc["nodes"]
        roads = sc["roads"]
        vehicles = sc["vehicles"]
        deliveries = sc["deliveries"]

        # Generate deterministic initial fleet plan
        plan = generate_initial_plan(vehicles, deliveries, nodes, roads)

        # Merge all into database
        for n in nodes:
            s.merge(n)
        for r in roads:
            s.merge(r)
        for v in vehicles:
            s.merge(v)
        for d in deliveries:
            s.merge(d)
        for rt in plan.routes:
            s.merge(rt)

        meta = s.get(SimulationMetadata, "global")
        if not meta:
            s.add(SimulationMetadata(
                id="global",
                simulation_time=0.0,
                simulation_start_time=start_time or get_current_local_iso(),
                is_running=False,
                speed_multiplier=1.0,
            ))
        else:
            meta.simulation_time = 0.0
            meta.simulation_start_time = start_time or get_current_local_iso()
            meta.is_running = False
            meta.speed_multiplier = 1.0
            s.add(meta)
        s.commit()

        return get_fleet_state(s)

    if session is not None:
        return _reset(session)
    with Session(engine) as s:
        return _reset(s)


def fresh_fleet_database(session: Optional[Session] = None, start_time: Optional[str] = None) -> FleetState:
    """
    Clear the current operational scenario to an empty slate:
      - 0 vehicles
      - 0 deliveries
      - 0 routes
      - 0 events
      - Preserves underlying network infrastructure (nodes, depot, roads)
      - Resets roads to normal traffic (1.0) and unblocked (False)
      - Resets simulation start time to current/specified local time
    """
    from simulation.demo_scenario import get_demo_scenario
    from sqlalchemy import text

    def _fresh(s: Session) -> FleetState:
        s.execute(text("DELETE FROM event;"))
        s.execute(text("DELETE FROM route;"))
        s.execute(text("DELETE FROM delivery;"))
        s.execute(text("DELETE FROM vehicle;"))
        s.execute(text("UPDATE road SET traffic_multiplier = 1.0, blocked = false;"))

        # Ensure core network nodes and roads are present
        existing_nodes = list(s.exec(select(Node)).all())
        existing_roads = list(s.exec(select(Road)).all())
        if not existing_nodes or not existing_roads:
            sc = get_demo_scenario()
            for n in sc["nodes"]:
                s.merge(n)
            for r in sc["roads"]:
                s.merge(r)

        meta = s.get(SimulationMetadata, "global")
        if not meta:
            s.add(SimulationMetadata(
                id="global",
                simulation_time=0.0,
                simulation_start_time=start_time or get_current_local_iso(),
                is_running=False,
                speed_multiplier=1.0,
            ))
        else:
            meta.simulation_time = 0.0
            meta.simulation_start_time = start_time or get_current_local_iso()
            meta.is_running = False
            meta.speed_multiplier = 1.0
            s.add(meta)
        s.commit()

        return get_fleet_state(s)

    if session is not None:
        return _fresh(session)
    with Session(engine) as s:
        return _fresh(s)


def set_simulation_clock(
    sim_time: float,
    start_time: Optional[str] = None,
    session: Optional[Session] = None,
) -> FleetState:
    """Set the authoritative simulation clock to a specified elapsed minute or start time."""
    def _set(s: Session) -> FleetState:
        meta = s.get(SimulationMetadata, "global")
        target_mins = max(0.0, float(sim_time))
        if not meta:
            meta = SimulationMetadata(
                id="global",
                simulation_time=target_mins,
                simulation_start_time=start_time or get_current_local_iso(),
                is_running=False,
                speed_multiplier=1.0,
            )
            s.add(meta)
        else:
            meta.simulation_time = target_mins
            if start_time:
                meta.simulation_start_time = start_time
            s.add(meta)
        s.commit()
        return get_fleet_state(s)

    if session is not None:
        return _set(session)
    with Session(engine) as s:
        return _set(s)


def advance_simulation_clock(
    minutes: float,
    session: Optional[Session] = None,
) -> FleetState:
    """Advance or rewind the simulation clock by a delta number of minutes."""
    def _adv(s: Session) -> FleetState:
        meta = s.get(SimulationMetadata, "global")
        delta = float(minutes)
        if not meta:
            meta = SimulationMetadata(
                id="global",
                simulation_time=max(0.0, delta),
                simulation_start_time=get_current_local_iso(),
                is_running=False,
                speed_multiplier=1.0,
            )
            s.add(meta)
        else:
            meta.simulation_time = max(0.0, meta.simulation_time + delta)
            s.add(meta)
        s.commit()
        return get_fleet_state(s)

    if session is not None:
        return _adv(session)
    with Session(engine) as s:
        return _adv(s)


def control_simulation_clock(
    is_running: bool,
    speed_multiplier: Optional[float] = None,
    session: Optional[Session] = None,
) -> FleetState:
    """Pause, resume, or adjust the speed multiplier of the simulation clock."""
    def _ctrl(s: Session) -> FleetState:
        meta = s.get(SimulationMetadata, "global")
        if not meta:
            meta = SimulationMetadata(
                id="global",
                simulation_time=0.0,
                simulation_start_time=get_current_local_iso(),
                is_running=is_running,
                speed_multiplier=float(speed_multiplier or 1.0),
            )
            s.add(meta)
        else:
            meta.is_running = is_running
            if speed_multiplier is not None:
                meta.speed_multiplier = max(0.1, float(speed_multiplier))
            s.add(meta)
        s.commit()
        return get_fleet_state(s)

    if session is not None:
        return _ctrl(session)
    with Session(engine) as s:
        return _ctrl(s)


