"""
API routers for fleet state retrieval using SQLModel and PostgreSQL.
All routes are read-only in Phase 1.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import (
    get_session,
    get_fleet_state,
    get_vehicles,
    get_deliveries,
    get_routes,
    get_nodes,
    get_roads,
    get_events,
    append_event,
    has_fleet_data,
)
from app.models import (
    FleetState, Vehicle, Delivery, Route, Node, Road, Event,
    EventType, VehicleStatus, DeliveryStatus, SimulationMetadata
)
from app.optimizer import OptimizationPlan, generate_initial_plan
from app.event_engine import EventResponse, process_event
from sqlmodel import SQLModel
from typing import Optional

router = APIRouter(prefix="/api", tags=["fleet"])


@router.get("/state", response_model=FleetState)
async def fetch_fleet_state(session: Session = Depends(get_session)):
    """Return the full current fleet state."""
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")
    return get_fleet_state(session)


@router.get("/vehicles", response_model=list[Vehicle])
async def fetch_vehicles(session: Session = Depends(get_session)):
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")
    return get_vehicles(session)


@router.get("/deliveries", response_model=list[Delivery])
async def fetch_deliveries(session: Session = Depends(get_session)):
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")
    return get_deliveries(session)


@router.get("/routes", response_model=list[Route])
async def fetch_routes(session: Session = Depends(get_session)):
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")
    return get_routes(session)


@router.get("/nodes", response_model=list[Node])
async def fetch_nodes(session: Session = Depends(get_session)):
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")
    return get_nodes(session)


@router.get("/roads", response_model=list[Road])
async def fetch_roads(session: Session = Depends(get_session)):
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")
    return get_roads(session)


@router.get("/events", response_model=list[Event])
async def fetch_events(session: Session = Depends(get_session)):
    """Return all events from the event log."""
    return get_events(session)


class CreateVehicleRequest(SQLModel):
    id: Optional[str] = None
    name: str
    capacity: float = 120.0
    driver_hours_remaining: float = 8.0
    current_location: str = "depot"
    status: VehicleStatus = VehicleStatus.ACTIVE


@router.post("/vehicles", response_model=FleetState)
async def create_vehicle(req: CreateVehicleRequest, session: Session = Depends(get_session)):
    """Scenario Builder: Add a new vehicle to the fleet and initialize its route."""
    import uuid
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")

    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="Vehicle name cannot be empty")
    if req.capacity <= 0:
        raise HTTPException(status_code=400, detail="Vehicle capacity must be greater than 0")
    if req.driver_hours_remaining < 0:
        raise HTTPException(status_code=400, detail="Driver hours remaining cannot be negative")

    vehicles = get_vehicles(session)
    if req.id and req.id.strip():
        vid = req.id.strip()
        if any(v.id == vid for v in vehicles):
            raise HTTPException(status_code=409, detail=f"Vehicle with ID '{vid}' already exists")
    else:
        existing_ids = {v.id for v in vehicles}
        idx = len(vehicles) + 1
        while f"v{idx:02d}" in existing_ids:
            idx += 1
        vid = f"v{idx:02d}"

    nodes = get_nodes(session)
    loc = req.current_location if any(n.id == req.current_location for n in nodes) else "depot"

    vehicle = Vehicle(
        id=vid,
        name=req.name.strip(),
        capacity=float(req.capacity),
        current_location=loc,
        driver_hours_remaining=float(req.driver_hours_remaining),
        status=req.status,
        current_load=0.0,
    )
    route = Route(
        vehicle_id=vid,
        delivery_ids=[],
        total_distance=0.0,
        total_travel_time=0.0,
        total_load=0.0,
        feasible=True,
    )
    session.add(vehicle)
    session.add(route)

    ev = Event(
        id=f"ev_veh_{uuid.uuid4().hex[:6]}",
        event_type=EventType.TRAFFIC_UPDATE,
        timestamp=0.0,
        affected_entity_id=vid,
        parameters={"action": "add_vehicle", "name": vehicle.name, "capacity": vehicle.capacity},
    )
    session.add(ev)
    session.commit()
    return get_fleet_state(session)


class CreateDeliveryRequest(SQLModel):
    id: Optional[str] = None
    location: str
    demand: float = 10.0
    priority: int = 2
    time_window_start: float = 0.0
    time_window_end: float = 300.0
    auto_assign: bool = False


@router.post("/deliveries", response_model=FleetState)
async def create_delivery(req: CreateDeliveryRequest, session: Session = Depends(get_session)):
    """Scenario Builder: Add a delivery to the scenario."""
    import uuid
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")

    deliveries = get_deliveries(session)
    did = req.id.strip() if req.id and req.id.strip() else f"d{len(deliveries) + 1:02d}"
    if any(d.id == did for d in deliveries):
        did = f"d_custom_{uuid.uuid4().hex[:4]}"

    nodes = get_nodes(session)
    loc = req.location if any(n.id == req.location for n in nodes) else (nodes[0].id if nodes else "n01")

    curr_time = _get_current_sim_time(session)
    if req.auto_assign:
        ev = Event(
            id=f"ev_new_{uuid.uuid4().hex[:6]}",
            event_type=EventType.NEW_DELIVERY,
            timestamp=curr_time,
            affected_entity_id=did,
            parameters={
                "location": loc,
                "demand": float(req.demand),
                "priority": int(req.priority),
                "time_window_start": float(req.time_window_start),
                "time_window_end": float(req.time_window_end),
            },
        )
        process_event(ev, session)
    else:
        delivery = Delivery(
            id=did,
            location=loc,
            demand=float(req.demand),
            priority=int(req.priority),
            time_window_start=float(req.time_window_start),
            time_window_end=float(req.time_window_end),
            status=DeliveryStatus.PENDING,
            assigned_vehicle=None,
        )
        session.add(delivery)
        ev = Event(
            id=f"ev_new_{uuid.uuid4().hex[:6]}",
            event_type=EventType.NEW_DELIVERY,
            timestamp=curr_time,
            affected_entity_id=did,
            parameters={
                "action": "add_unassigned_delivery",
                "location": loc,
                "demand": float(req.demand),
                "priority": int(req.priority),
            },
        )
        session.add(ev)
        session.commit()

    return get_fleet_state(session)


class CreateNodeRequest(SQLModel):
    id: Optional[str] = None
    label: str
    lat: float
    lon: float
    connect_to_node: Optional[str] = None


@router.post("/nodes", response_model=FleetState)
async def create_node(req: CreateNodeRequest, session: Session = Depends(get_session)):
    """Scenario Builder: Add a new routable stop/node to the city graph."""
    import math, uuid
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")

    nodes = get_nodes(session)
    nid = req.id.strip() if req.id and req.id.strip() else f"n{len(nodes) + 1:02d}"
    if any(n.id == nid for n in nodes):
        nid = f"n_custom_{uuid.uuid4().hex[:4]}"

    new_node = Node(
        id=nid,
        label=req.label.strip() or f"Stop {nid}",
        lat=float(req.lat),
        lon=float(req.lon),
        is_depot=False,
    )
    session.add(new_node)

    # Connect safely to target or closest node
    target_node = None
    if req.connect_to_node:
        target_node = next((n for n in nodes if n.id == req.connect_to_node), None)
    if not target_node and nodes:
        target_node = min(
            nodes,
            key=lambda n: (n.lat - req.lat) ** 2 + (n.lon - req.lon) ** 2,
        )

    if target_node:
        deg_dist = math.sqrt((req.lat - target_node.lat) ** 2 + (req.lon - target_node.lon) ** 2)
        dist_km = max(0.5, round(deg_dist * 111.0, 2))
        base_time = max(1.5, round(dist_km * 2.0, 1))

        new_road = Road(
            id=f"road_{nid}_{target_node.id}",
            from_node=nid,
            to_node=target_node.id,
            distance=dist_km,
            base_time=base_time,
            traffic_multiplier=1.0,
            blocked=False,
        )
        session.add(new_road)

    session.commit()
    return get_fleet_state(session)


@router.post("/events", response_model=EventResponse)
async def post_event(event: Event, session: Session = Depends(get_session)):
    """
    Canonical endpoint to ingest a real-time event.
    Triggers incremental fleet repair and returns detailed before/after metrics.
    """
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")
    return process_event(event, session)


class TrafficEventRequest(SQLModel):
    road_id: str
    traffic_multiplier: float
    timestamp: float = 0.0


class BreakdownEventRequest(SQLModel):
    vehicle_id: str
    reason: str = "engine_failure"
    timestamp: float = 0.0


class NewDeliveryEventRequest(SQLModel):
    delivery_id: Optional[str] = None
    location: str
    demand: float
    priority: int = 2
    time_window_start: float = 0.0
    time_window_end: float = 360.0
    timestamp: float = 0.0


class CancelDeliveryEventRequest(SQLModel):
    delivery_id: str
    reason: str = "customer_cancelled"
    timestamp: float = 0.0


class RoadBlockEventRequest(SQLModel):
    road_id: str
    blocked: bool = True
    timestamp: float = 0.0


class TimeWindowChangeEventRequest(SQLModel):
    delivery_id: str
    new_window_start: float
    new_window_end: float
    timestamp: float = 0.0


def _get_current_sim_time(session: Session) -> float:
    meta = session.get(SimulationMetadata, "global")
    return meta.simulation_time if meta else 0.0


@router.post("/events/traffic", response_model=EventResponse)
async def post_traffic_event(req: TrafficEventRequest, session: Session = Depends(get_session)):
    import uuid
    ts = req.timestamp if req.timestamp > 0.0 else _get_current_sim_time(session)
    ev = Event(
        id=f"ev_traffic_{uuid.uuid4().hex[:6]}",
        event_type=EventType.TRAFFIC_UPDATE,
        timestamp=ts,
        affected_entity_id=req.road_id,
        parameters={"traffic_multiplier": req.traffic_multiplier},
    )
    return process_event(ev, session)


@router.post("/events/breakdown", response_model=EventResponse)
async def post_breakdown_event(req: BreakdownEventRequest, session: Session = Depends(get_session)):
    import uuid
    ts = req.timestamp if req.timestamp > 0.0 else _get_current_sim_time(session)
    ev = Event(
        id=f"ev_bd_{uuid.uuid4().hex[:6]}",
        event_type=EventType.VEHICLE_BREAKDOWN,
        timestamp=ts,
        affected_entity_id=req.vehicle_id,
        parameters={"reason": req.reason},
    )
    return process_event(ev, session)


@router.post("/events/new-delivery", response_model=EventResponse)
async def post_new_delivery_event(req: NewDeliveryEventRequest, session: Session = Depends(get_session)):
    import uuid
    did = req.delivery_id or f"d_new_{uuid.uuid4().hex[:4]}"
    ts = req.timestamp if req.timestamp > 0.0 else _get_current_sim_time(session)
    ev = Event(
        id=f"ev_new_{uuid.uuid4().hex[:6]}",
        event_type=EventType.NEW_DELIVERY,
        timestamp=ts,
        affected_entity_id=did,
        parameters={
            "location": req.location,
            "demand": req.demand,
            "priority": req.priority,
            "time_window_start": req.time_window_start,
            "time_window_end": req.time_window_end,
        },
    )
    return process_event(ev, session)


@router.post("/events/cancel-delivery", response_model=EventResponse)
@router.post("/events/cancel", response_model=EventResponse)
async def post_cancel_delivery_event(req: CancelDeliveryEventRequest, session: Session = Depends(get_session)):
    import uuid
    ts = req.timestamp if req.timestamp > 0.0 else _get_current_sim_time(session)
    ev = Event(
        id=f"ev_cancel_{uuid.uuid4().hex[:6]}",
        event_type=EventType.DELIVERY_CANCELLED,
        timestamp=ts,
        affected_entity_id=req.delivery_id,
        parameters={"reason": req.reason},
    )
    return process_event(ev, session)


@router.post("/events/road-block", response_model=EventResponse)
@router.post("/events/road-blocked", response_model=EventResponse)
async def post_road_block_event(req: RoadBlockEventRequest, session: Session = Depends(get_session)):
    import uuid
    ts = req.timestamp if req.timestamp > 0.0 else _get_current_sim_time(session)
    ev = Event(
        id=f"ev_block_{uuid.uuid4().hex[:6]}",
        event_type=EventType.ROAD_BLOCKED,
        timestamp=ts,
        affected_entity_id=req.road_id,
        parameters={"blocked": req.blocked},
    )
    return process_event(ev, session)


@router.post("/events/time-window-change", response_model=EventResponse)
@router.post("/events/time-window", response_model=EventResponse)
async def post_time_window_change_event(req: TimeWindowChangeEventRequest, session: Session = Depends(get_session)):
    import uuid
    ts = req.timestamp if req.timestamp > 0.0 else _get_current_sim_time(session)
    ev = Event(
        id=f"ev_tw_{uuid.uuid4().hex[:6]}",
        event_type=EventType.TIME_WINDOW_CHANGE,
        timestamp=ts,
        affected_entity_id=req.delivery_id,
        parameters={
            "new_window_start": req.new_window_start,
            "new_window_end": req.new_window_end,
        },
    )
    return process_event(ev, session)


class OptimizeRequest(SQLModel):
    persist: bool = True
    service_time: float = 5.0
    start_time: float = 0.0


@router.post("/optimize", response_model=OptimizationPlan)
async def optimize_fleet(
    req: Optional[OptimizeRequest] = None,
    session: Session = Depends(get_session),
):
    """
    Run the fleet route optimizer on the current database fleet state.
    Returns the full optimization plan including before/after metrics, changed routes, and decision explanation.
    """
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized yet")

    if req is None:
        req = OptimizeRequest()

    vehicles = get_vehicles(session)
    deliveries = get_deliveries(session)
    nodes = get_nodes(session)
    roads = get_roads(session)
    routes = get_routes(session)

    # 1. Authoritative BEFORE metrics
    from app.optimizer import compute_fleet_metrics, recalculate_route_derived_state
    before_metrics = compute_fleet_metrics(
        routes=routes,
        vehicles=vehicles,
        deliveries=deliveries,
        nodes=nodes,
        roads=roads,
        service_time=req.service_time,
        start_time=req.start_time,
    )
    before_routes_map = {r.vehicle_id: list(r.delivery_ids) for r in routes}
    before_assignment = {
        did: route.vehicle_id
        for route in routes
        for did in route.delivery_ids
    }

    # 2. Repair only when the persisted snapshot contains a validated
    # violation. Rebuilding a feasible plan from scratch can reshuffle routes
    # without fixing anything and can even increase its total distance.
    if before_metrics["total_violations"]:
        plan = generate_initial_plan(
            vehicles=vehicles,
            deliveries=deliveries,
            nodes=nodes,
            roads=roads,
            service_time=req.service_time,
            start_time=req.start_time,
        )
    else:
        plan = OptimizationPlan(
            routes=routes,
            unassigned_deliveries=[],
            total_distance=before_metrics["total_distance"],
            total_travel_time=before_metrics["total_travel_time"],
            number_of_late_deliveries=before_metrics["time_window_violations"],
            number_of_capacity_violations=before_metrics["capacity_violations"],
            number_of_unassigned_deliveries=before_metrics["unassigned_deliveries"],
            before=before_metrics,
            after=before_metrics,
            before_metrics=before_metrics,
            after_metrics=before_metrics,
        )

    # 3. Persist new routes and vehicle/delivery assignments
    from sqlalchemy.orm.attributes import flag_modified
    if req.persist:
        for r in plan.routes:
            flag_modified(r, "delivery_ids")
            session.merge(r)
        for v in vehicles:
            session.merge(v)
        for d in deliveries:
            session.merge(d)
        session.commit()

    # 4. Validate the exact final snapshot, reading it back after persistence.
    if req.persist:
        final_routes = get_routes(session)
        final_vehicles = get_vehicles(session)
        final_deliveries = get_deliveries(session)
        from app.routing import build_graph
        recalculate_route_derived_state(
            routes=final_routes,
            vehicles=final_vehicles,
            deliveries=final_deliveries,
            graph=build_graph(nodes, roads),
            service_time=req.service_time,
            start_time=req.start_time,
        )
        for route in final_routes:
            session.add(route)
        for vehicle in final_vehicles:
            session.add(vehicle)
        session.commit()
        final_routes = get_routes(session)
        final_vehicles = get_vehicles(session)
        final_deliveries = get_deliveries(session)
    else:
        final_routes = plan.routes
        final_vehicles = vehicles
        final_deliveries = deliveries

    after_metrics = compute_fleet_metrics(
        routes=final_routes,
        vehicles=final_vehicles,
        deliveries=final_deliveries,
        nodes=nodes,
        roads=roads,
        service_time=req.service_time,
        start_time=req.start_time,
    )

    # 5. Track changed routes and reassigned deliveries
    routes_changed: list[str] = []
    for r in final_routes:
        old_ids = before_routes_map.get(r.vehicle_id, [])
        if old_ids != r.delivery_ids:
            routes_changed.append(r.vehicle_id)

    after_assignment = {
        did: route.vehicle_id
        for route in final_routes
        for did in route.delivery_ids
    }
    deliveries_reassigned = sorted(
        did for did in set(before_assignment) | set(after_assignment)
        if before_assignment.get(did) != after_assignment.get(did)
    )

    # 6. Deterministic explanation
    viol_diff = before_metrics["total_violations"] - after_metrics["total_violations"]
    if routes_changed:
        if viol_diff > 0:
            decision_explanation = (
                f"Global fleet optimization re-sequenced {len(routes_changed)} route(s) "
                f"({', '.join(routes_changed)}), resolving {viol_diff} violation(s) and reassigning "
                f"{len(deliveries_reassigned)} delivery stop(s) with 0 late arrivals."
            )
        else:
            decision_explanation = (
                f"Global fleet optimization rebalanced {len(routes_changed)} route(s) "
                f"({', '.join(routes_changed)}) with {after_metrics['total_violations']} remaining violation(s)."
            )
    else:
        if after_metrics["total_violations"] == 0:
            decision_explanation = (
                f"Current persisted plan is feasible; no route changes were needed across "
                f"{len(plan.routes)} routes."
            )
        else:
            decision_explanation = (
                f"Global fleet optimization evaluated the current plan without changing routes; "
                f"{after_metrics['total_violations']} total violations remain."
            )

    # 7. Populate the response from the final snapshot, never the optimizer's
    # pre-persistence objects.
    plan.routes = final_routes
    plan.unassigned_deliveries = sorted(
        violation["delivery_id"]
        for violation in after_metrics["violations"]
        if violation["type"] == "unassigned_delivery"
    )
    plan.total_distance = after_metrics["total_distance"]
    plan.total_travel_time = after_metrics["total_travel_time"]
    plan.number_of_late_deliveries = after_metrics["time_window_violations"]
    plan.number_of_capacity_violations = after_metrics["capacity_violations"]
    plan.number_of_unassigned_deliveries = after_metrics["unassigned_deliveries"]
    plan.before = before_metrics
    plan.after = after_metrics
    plan.before_metrics = before_metrics
    plan.after_metrics = after_metrics
    plan.routes_changed = routes_changed
    plan.changed_routes = routes_changed
    plan.deliveries_reassigned = deliveries_reassigned
    plan.reassigned_deliveries = deliveries_reassigned
    plan.decision_explanation = decision_explanation
    plan.explanation = decision_explanation
    plan.title = "Global Fleet Optimization"
    plan.event_type = "FLEET_OPTIMIZATION"
    plan.full_state = get_fleet_state(session).model_dump() if req.persist else None

    return plan


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "Delivery Control Tower"}
