"""
Real-Time Event Engine for Delivery Control Tower.

Implements incremental fleet repair responding dynamically to real-time events
WITHOUT rebuilding the entire fleet plan from scratch.

Supported Event Types:
  1. TRAFFIC_UPDATE       - Road congestion update; re-routes affected vehicles
  2. VEHICLE_BREAKDOWN    - Reassigns orphaned deliveries to other active vehicles
  3. NEW_DELIVERY         - Incrementally inserts a new order into the best feasible route
  4. DELIVERY_CANCELLED   - Cancels delivery and updates affected route metrics
  5. ROAD_BLOCKED         - Blocks/unblocks roads; finds detours or flags infeasible stops
  6. TIME_WINDOW_CHANGE   - Updates delivery deadline; locally repairs affected route
"""

import math
import uuid
from typing import Optional
from sqlmodel import Session, SQLModel, Field
from sqlalchemy.orm.attributes import flag_modified

from app.models import (
    Vehicle, Delivery, Node, Road, Route, Event,
    VehicleStatus, DeliveryStatus, EventType
)
from app.routing import CityGraph, build_graph
from app.optimizer import (
    simulate_route_timeline,
    is_route_feasible,
    calculate_route_cost,
    validate_fleet_state,
    recalculate_route_derived_state,
)


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class EventMetrics(SQLModel):
    total_distance: float
    total_travel_time: float
    late_deliveries: int
    unassigned_deliveries: int
    total_violations: int = 0
    capacity_violations: int = 0
    time_window_violations: int = 0
    driver_hour_violations: int = 0
    assignment_violations: int = 0
    unreachable_routes: int = 0
    infeasible_routes: int = 0
    failed_deliveries: int = 0
    violations: list[dict] = Field(default_factory=list)


class EventResponse(SQLModel):
    event_id: str
    event_type: str
    affected_vehicles: list[str]
    affected_deliveries: list[str]
    changed_routes: list[str]
    reassigned_deliveries: list[str]
    before_metrics: EventMetrics
    after_metrics: EventMetrics
    reoptimization_scope: float
    explanation: str
    decision_explanation: str = ""
    full_state: Optional[dict] = None


# ---------------------------------------------------------------------------
# Route Analysis Helpers
# ---------------------------------------------------------------------------

def does_route_use_road(
    route: Route,
    road: Road,
    vehicle: Vehicle,
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
) -> bool:
    """
    Check if a vehicle route traverses a specific road edge (either direction)
    along its shortest paths between consecutive stops.
    """
    if not route.delivery_ids:
        return False

    u, v = road.from_node, road.to_node
    current = vehicle.current_location

    waypoints = [current] + [deliveries_dict[did].location for did in route.delivery_ids if did in deliveries_dict] + ["depot"]

    for i in range(len(waypoints) - 1):
        src, dst = waypoints[i], waypoints[i + 1]
        path = graph.shortest_path(src, dst)
        for j in range(len(path) - 1):
            if (path[j] == u and path[j + 1] == v) or (path[j] == v and path[j + 1] == u):
                return True
    return False


def get_fleet_kpis(
    routes: list[Route],
    deliveries: list[Delivery],
    vehicles_dict: dict[str, Vehicle],
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> EventMetrics:
    """Use the same fresh validator used by GET /api/state and /api/optimize."""
    metrics = validate_fleet_state(
        routes=routes,
        vehicles=list(vehicles_dict.values()),
        deliveries=deliveries,
        graph=graph,
        service_time=service_time,
        start_time=start_time,
    )
    return EventMetrics(
        total_distance=metrics["total_distance"],
        total_travel_time=metrics["total_travel_time"],
        late_deliveries=metrics["time_window_violations"],
        unassigned_deliveries=metrics["unassigned_deliveries"],
        total_violations=metrics["total_violations"],
        capacity_violations=metrics["capacity_violations"],
        time_window_violations=metrics["time_window_violations"],
        driver_hour_violations=metrics["driver_hour_violations"],
        assignment_violations=metrics["assignment_violations"],
        unreachable_routes=metrics["unreachable_routes"],
        infeasible_routes=metrics["infeasible_routes"],
        failed_deliveries=metrics["failed_deliveries"],
        violations=metrics["violations"],
    )


# ---------------------------------------------------------------------------
# Incremental Repair Handler
# ---------------------------------------------------------------------------

def process_event(event: Event, session: Session) -> EventResponse:
    """
    Process any incoming fleet event incrementally without global replanning.
    Updates the database and returns detailed before/after diffs.
    """
    from app.database import get_vehicles, get_deliveries, get_routes, get_nodes, get_roads

    vehicles = get_vehicles(session)
    deliveries = get_deliveries(session)
    routes = get_routes(session)
    nodes = get_nodes(session)
    roads = get_roads(session)

    vehicles_dict = {v.id: v for v in vehicles}
    deliveries_dict = {d.id: d for d in deliveries}
    routes_dict = {r.vehicle_id: r for r in routes}
    roads_dict = {r.id: r for r in roads}

    # Build current graph
    current_graph = build_graph(nodes, roads)

    # Compute baseline metrics before event
    before_metrics = get_fleet_kpis(routes, deliveries, vehicles_dict, deliveries_dict, current_graph)

    affected_vehicles: list[str] = []
    affected_deliveries: list[str] = []
    changed_routes: list[str] = []
    reassigned_deliveries: list[str] = []
    explanation: str = ""
    decision_explanation: str = ""

    # Dispatch to specific event handler
    if event.event_type == EventType.TRAFFIC_UPDATE:
        explanation, decision_explanation = _handle_traffic_update(
            event, roads_dict, routes_dict, vehicles_dict, deliveries_dict,
            nodes, roads, affected_vehicles, affected_deliveries, changed_routes, session
        )

    elif event.event_type == EventType.VEHICLE_BREAKDOWN:
        explanation, decision_explanation = _handle_vehicle_breakdown(
            event, vehicles_dict, routes_dict, deliveries_dict, current_graph,
            affected_vehicles, affected_deliveries, changed_routes, reassigned_deliveries, session
        )

    elif event.event_type == EventType.NEW_DELIVERY:
        explanation, decision_explanation = _handle_new_delivery(
            event, deliveries_dict, vehicles_dict, routes_dict, current_graph,
            affected_vehicles, affected_deliveries, changed_routes, session
        )

    elif event.event_type == EventType.DELIVERY_CANCELLED:
        explanation, decision_explanation = _handle_delivery_cancelled(
            event, deliveries_dict, vehicles_dict, routes_dict, current_graph,
            affected_vehicles, affected_deliveries, changed_routes, session
        )

    elif event.event_type == EventType.ROAD_BLOCKED:
        explanation, decision_explanation = _handle_road_blocked(
            event, roads_dict, routes_dict, vehicles_dict, deliveries_dict,
            nodes, roads, affected_vehicles, affected_deliveries, changed_routes, session
        )

    elif event.event_type == EventType.TIME_WINDOW_CHANGE:
        explanation, decision_explanation = _handle_time_window_change(
            event, deliveries_dict, vehicles_dict, routes_dict, current_graph,
            affected_vehicles, affected_deliveries, changed_routes, reassigned_deliveries, session
        )

    else:
        explanation = f"Unknown event type {event.event_type}"
        decision_explanation = explanation

    # Rebuild updated graph for after-metrics
    updated_roads = get_roads(session)
    updated_graph = build_graph(nodes, updated_roads)
    updated_deliveries = get_deliveries(session)
    updated_routes = get_routes(session)
    updated_vehicles = get_vehicles(session)

    # Road, delivery, and assignment events can change route-derived fields even
    # when a stop sequence stays fixed. Persist one fresh snapshot before KPIs.
    recalculate_route_derived_state(
        routes=updated_routes,
        vehicles=updated_vehicles,
        deliveries=updated_deliveries,
        graph=updated_graph,
    )
    for route in updated_routes:
        session.add(route)
    for vehicle in updated_vehicles:
        session.add(vehicle)
    session.commit()

    updated_routes = get_routes(session)
    updated_vehicles = get_vehicles(session)

    after_metrics = get_fleet_kpis(
        updated_routes, updated_deliveries, {v.id: v for v in updated_vehicles},
        {d.id: d for d in updated_deliveries}, updated_graph
    )

    total_deliveries_count = max(1, len(updated_deliveries))
    reopt_scope = round(len(affected_deliveries) / total_deliveries_count, 4)

    # Record event in event log
    session.add(event)
    session.commit()

    from app.database import get_fleet_state
    full_state_dict = get_fleet_state(session).model_dump()

    return EventResponse(
        event_id=event.id,
        event_type=event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
        affected_vehicles=sorted(list(set(affected_vehicles))),
        affected_deliveries=sorted(list(set(affected_deliveries))),
        changed_routes=sorted(list(set(changed_routes))),
        reassigned_deliveries=sorted(list(set(reassigned_deliveries))),
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        reoptimization_scope=reopt_scope,
        explanation=explanation,
        decision_explanation=decision_explanation or explanation,
        full_state=full_state_dict,
    )


# ---------------------------------------------------------------------------
# Individual Event Handlers
# ---------------------------------------------------------------------------

def _handle_traffic_update(
    event: Event,
    roads_dict: dict[str, Road],
    routes_dict: dict[str, Route],
    vehicles_dict: dict[str, Vehicle],
    deliveries_dict: dict[str, Delivery],
    nodes: list[Node],
    roads: list[Road],
    affected_vehicles: list[str],
    affected_deliveries: list[str],
    changed_routes: list[str],
    session: Session,
) -> tuple[str, str]:
    road_id = event.affected_entity_id
    road = roads_dict.get(road_id)
    if not road:
        return f"Road '{road_id}' not found.", f"Road '{road_id}' not found in network."

    # Build graph BEFORE mutating traffic multiplier to identify who was using this road
    old_graph = build_graph(nodes, roads)

    old_mult = road.traffic_multiplier
    new_mult = float(event.parameters.get("traffic_multiplier", road.traffic_multiplier))
    road.traffic_multiplier = new_mult
    session.add(road)

    new_roads = [r if r.id != road.id else road for r in roads]
    new_graph = build_graph(nodes, new_roads)

    for vid, route in routes_dict.items():
        v = vehicles_dict.get(vid)
        if not v or not route.delivery_ids:
            continue

        if does_route_use_road(route, road, v, deliveries_dict, old_graph):
            affected_vehicles.append(vid)
            changed_routes.append(vid)
            affected_deliveries.extend(route.delivery_ids)

            # Re-evaluate route with new graph
            sim = simulate_route_timeline(route.delivery_ids, v, deliveries_dict, new_graph)
            route.total_distance = sim["total_distance"]
            route.total_travel_time = sim["total_travel_time"]
            route.feasible = sim["is_feasible"]
            session.add(route)

    session.commit()
    from app.explainability import explain_traffic_update
    decision_exp = explain_traffic_update(
        road_id=road.id,
        from_node=road.from_node,
        to_node=road.to_node,
        old_mult=old_mult,
        new_mult=new_mult,
        base_time=road.base_time,
        affected_vehicles=affected_vehicles,
    )
    short_exp = (
        f"Traffic updated on road {road_id} (multiplier {new_mult:.1f}x). "
        f"{len(affected_vehicles)} vehicle route(s) traversed this road and were recalculated."
    )
    return short_exp, decision_exp


def _handle_vehicle_breakdown(
    event: Event,
    vehicles_dict: dict[str, Vehicle],
    routes_dict: dict[str, Route],
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
    affected_vehicles: list[str],
    affected_deliveries: list[str],
    changed_routes: list[str],
    reassigned_deliveries: list[str],
    session: Session,
) -> tuple[str, str]:
    vid = event.affected_entity_id
    broken_vehicle = vehicles_dict.get(vid)
    if not broken_vehicle:
        return f"Vehicle '{vid}' not found.", f"Vehicle '{vid}' not found in active fleet."

    broken_vehicle.status = VehicleStatus.BREAKDOWN
    broken_vehicle.current_load = 0.0
    session.add(broken_vehicle)

    broken_route = routes_dict.get(vid)
    orphaned_deliveries = list(broken_route.delivery_ids) if broken_route else []

    affected_vehicles.append(vid)
    affected_deliveries.extend(orphaned_deliveries)
    changed_routes.append(vid)

    if broken_route:
        # Clear stops and load; preserve baseline incurred/dispatched distance and time
        # so total fleet operational distance accurately reflects emergency detour increases
        broken_route.delivery_ids = []
        flag_modified(broken_route, "delivery_ids")
        broken_route.total_load = 0.0
        broken_route.feasible = len(broken_route.delivery_ids) == 0  # Empty parked route has no constraint violations
        session.add(broken_route)

    # Sort orphaned deliveries: high priority (1) first, then urgency
    pending_orphans = [
        deliveries_dict[did] for did in orphaned_deliveries
        if did in deliveries_dict and deliveries_dict[did].status == DeliveryStatus.PENDING
    ]
    pending_orphans.sort(key=lambda d: (d.priority, d.time_window_end))

    # Candidate active vehicles
    active_vehicles = [
        v for v in vehicles_dict.values()
        if v.status == VehicleStatus.ACTIVE and v.id != vid
    ]

    reassigned_count = 0
    for d in pending_orphans:
        best_v_id: Optional[str] = None
        best_pos: Optional[int] = None
        best_cost = math.inf

        for candidate_v in active_vehicles:
            c_route = routes_dict.get(candidate_v.id)
            c_ids = list(c_route.delivery_ids) if c_route else []

            # Check capacity
            current_load = sum(deliveries_dict[did].demand for did in c_ids if did in deliveries_dict)
            if current_load + d.demand > candidate_v.capacity:
                continue

            for idx in range(len(c_ids) + 1):
                test_route = c_ids[:idx] + [d.id] + c_ids[idx:]
                feasible, _ = is_route_feasible(test_route, candidate_v, deliveries_dict, graph)
                if not feasible:
                    continue

                cost = calculate_route_cost(test_route, candidate_v, deliveries_dict, graph)
                if cost < best_cost:
                    best_cost = cost
                    best_v_id = candidate_v.id
                    best_pos = idx

        if best_v_id and best_pos is not None:
            target_route = routes_dict[best_v_id]
            new_ids = list(target_route.delivery_ids)
            new_ids.insert(best_pos, d.id)
            target_route.delivery_ids = new_ids
            flag_modified(target_route, "delivery_ids")
            d.assigned_vehicle = best_v_id
            session.add(d)

            # Update target vehicle route metrics
            sim = simulate_route_timeline(target_route.delivery_ids, vehicles_dict[best_v_id], deliveries_dict, graph)
            target_route.total_distance = sim["total_distance"]
            target_route.total_travel_time = sim["total_travel_time"]
            target_route.total_load = sim["total_load"]
            target_route.feasible = sim["is_feasible"]
            session.add(target_route)

            vehicles_dict[best_v_id].current_load = sim["total_load"]
            session.add(vehicles_dict[best_v_id])

            reassigned_deliveries.append(d.id)
            changed_routes.append(best_v_id)
            affected_vehicles.append(best_v_id)
            reassigned_count += 1
        else:
            d.assigned_vehicle = None
            session.add(d)

    session.commit()
    target_vehicles = [d.assigned_vehicle for d in pending_orphans if d.assigned_vehicle]
    from app.explainability import explain_vehicle_breakdown
    decision_exp = explain_vehicle_breakdown(
        broken_vehicle_id=vid,
        orphaned_count=len(pending_orphans),
        reassigned_deliveries=reassigned_deliveries,
        target_vehicles=target_vehicles,
        unassigned_count=len(pending_orphans) - reassigned_count,
    )
    short_exp = (
        f"Vehicle {vid} marked as BREAKDOWN. {len(orphaned_deliveries)} deliveries offloaded; "
        f"{reassigned_count} successfully reassigned to active fleet. "
        f"{len(orphaned_deliveries) - reassigned_count} unassigned."
    )
    return short_exp, decision_exp


def _handle_new_delivery(
    event: Event,
    deliveries_dict: dict[str, Delivery],
    vehicles_dict: dict[str, Vehicle],
    routes_dict: dict[str, Route],
    graph: CityGraph,
    affected_vehicles: list[str],
    affected_deliveries: list[str],
    changed_routes: list[str],
    session: Session,
) -> tuple[str, str]:
    did = event.affected_entity_id
    params = event.parameters or {}

    location = params.get("location", "n01")
    demand = float(params.get("demand", 10.0))
    priority = int(params.get("priority", 2))
    tw_start = float(params.get("time_window_start", 0.0))
    tw_end = float(params.get("time_window_end", 360.0))

    new_delivery = Delivery(
        id=did,
        location=location,
        demand=demand,
        priority=priority,
        time_window_start=tw_start,
        time_window_end=tw_end,
        status=DeliveryStatus.PENDING,
        assigned_vehicle=None,
    )
    deliveries_dict[did] = new_delivery
    affected_deliveries.append(did)

    active_vehicles = [v for v in vehicles_dict.values() if v.status == VehicleStatus.ACTIVE]
    best_v_id: Optional[str] = None
    best_pos: Optional[int] = None
    best_cost = math.inf

    for v in active_vehicles:
        r = routes_dict.get(v.id)
        r_ids = list(r.delivery_ids) if r else []

        current_load = sum(deliveries_dict[item_id].demand for item_id in r_ids if item_id in deliveries_dict)
        if current_load + demand > v.capacity:
            continue

        for idx in range(len(r_ids) + 1):
            test_ids = r_ids[:idx] + [did] + r_ids[idx:]
            feasible, _ = is_route_feasible(test_ids, v, deliveries_dict, graph)
            if not feasible:
                continue

            cost = calculate_route_cost(test_ids, v, deliveries_dict, graph)
            if cost < best_cost:
                best_cost = cost
                best_v_id = v.id
                best_pos = idx

    from app.explainability import explain_new_delivery
    if best_v_id and best_pos is not None:
        target_route = routes_dict[best_v_id]
        new_ids = list(target_route.delivery_ids)
        new_ids.insert(best_pos, did)
        target_route.delivery_ids = new_ids
        flag_modified(target_route, "delivery_ids")
        new_delivery.assigned_vehicle = best_v_id
        session.merge(new_delivery)

        sim = simulate_route_timeline(target_route.delivery_ids, vehicles_dict[best_v_id], deliveries_dict, graph)
        target_route.total_distance = sim["total_distance"]
        target_route.total_travel_time = sim["total_travel_time"]
        target_route.total_load = sim["total_load"]
        target_route.feasible = sim["is_feasible"]
        session.add(target_route)

        vehicles_dict[best_v_id].current_load = sim["total_load"]
        session.add(vehicles_dict[best_v_id])

        affected_vehicles.append(best_v_id)
        changed_routes.append(best_v_id)
        session.commit()
        decision_exp = explain_new_delivery(
            delivery_id=did,
            location=location,
            demand=demand,
            priority=priority,
            time_window_start=tw_start,
            time_window_end=tw_end,
            assigned_vehicle=best_v_id,
            stop_index=best_pos,
        )
        short_exp = (
            f"New delivery {did} (P{priority}, {demand}kg) inserted into {best_v_id} "
            f"at stop index {best_pos} without modifying other routes."
        )
        return short_exp, decision_exp
    else:
        session.merge(new_delivery)
        session.commit()
        decision_exp = explain_new_delivery(
            delivery_id=did,
            location=location,
            demand=demand,
            priority=priority,
            time_window_start=tw_start,
            time_window_end=tw_end,
            assigned_vehicle=None,
        )
        short_exp = (
            f"New delivery {did} created, but could not be feasibly assigned "
            f"due to capacity/window constraints. Marked unassigned."
        )
        return short_exp, decision_exp


def _handle_delivery_cancelled(
    event: Event,
    deliveries_dict: dict[str, Delivery],
    vehicles_dict: dict[str, Vehicle],
    routes_dict: dict[str, Route],
    graph: CityGraph,
    affected_vehicles: list[str],
    affected_deliveries: list[str],
    changed_routes: list[str],
    session: Session,
) -> tuple[str, str]:
    did = event.affected_entity_id
    delivery = deliveries_dict.get(did)
    if not delivery:
        return f"Delivery '{did}' not found.", f"Delivery '{did}' not found in active deliveries."

    delivery.status = DeliveryStatus.CANCELLED
    assigned_v = delivery.assigned_vehicle
    delivery.assigned_vehicle = None
    session.add(delivery)

    affected_deliveries.append(did)

    if assigned_v and assigned_v in routes_dict:
        route = routes_dict[assigned_v]
        if did in route.delivery_ids:
            route.delivery_ids = [x for x in route.delivery_ids if x != did]
            flag_modified(route, "delivery_ids")
            affected_vehicles.append(assigned_v)
            changed_routes.append(assigned_v)

            v = vehicles_dict.get(assigned_v)
            if v:
                sim = simulate_route_timeline(route.delivery_ids, v, deliveries_dict, graph)
                route.total_distance = sim["total_distance"]
                route.total_travel_time = sim["total_travel_time"]
                route.total_load = sim["total_load"]
                route.feasible = sim["is_feasible"]
                session.add(route)

                v.current_load = sim["total_load"]
                session.add(v)

    session.commit()
    from app.explainability import explain_delivery_cancelled
    decision_exp = explain_delivery_cancelled(
        delivery_id=did,
        vehicle_id=assigned_v,
        demand=delivery.demand,
    )
    short_exp = f"Delivery {did} cancelled and removed from route {assigned_v or 'none'}."
    return short_exp, decision_exp


def _handle_road_blocked(
    event: Event,
    roads_dict: dict[str, Road],
    routes_dict: dict[str, Route],
    vehicles_dict: dict[str, Vehicle],
    deliveries_dict: dict[str, Delivery],
    nodes: list[Node],
    roads: list[Road],
    affected_vehicles: list[str],
    affected_deliveries: list[str],
    changed_routes: list[str],
    session: Session,
) -> tuple[str, str]:
    road_id = event.affected_entity_id
    road = roads_dict.get(road_id)
    if not road:
        return f"Road '{road_id}' not found.", f"Road '{road_id}' not found in network."

    # Build graph BEFORE mutating road.blocked to identify who was using this road
    old_graph = build_graph(nodes, roads)

    is_blocked = bool(event.parameters.get("blocked", True))
    road.blocked = is_blocked
    session.add(road)

    new_roads = [r if r.id != road.id else road for r in roads]
    new_graph = build_graph(nodes, new_roads)

    for vid, route in routes_dict.items():
        v = vehicles_dict.get(vid)
        if not v or not route.delivery_ids:
            continue

        was_using = does_route_use_road(route, road, v, deliveries_dict, old_graph)
        will_use = does_route_use_road(route, road, v, deliveries_dict, new_graph) if not is_blocked else False

        if was_using or will_use:
            affected_vehicles.append(vid)
            changed_routes.append(vid)
            affected_deliveries.extend(route.delivery_ids)

            sim = simulate_route_timeline(route.delivery_ids, v, deliveries_dict, new_graph)
            route.total_distance = sim["total_distance"]
            route.total_travel_time = sim["total_travel_time"]
            route.feasible = sim["is_feasible"]
            session.add(route)

    session.commit()
    from app.explainability import explain_road_blocked
    decision_exp = explain_road_blocked(
        road_id=road.id,
        from_node=road.from_node,
        to_node=road.to_node,
        blocked=is_blocked,
        affected_vehicles=affected_vehicles,
    )
    status_str = "blocked" if is_blocked else "reopened"
    short_exp = (
        f"Road {road_id} {status_str}. "
        f"{len(affected_vehicles)} affected route(s) rerouted around the obstacle."
    )
    return short_exp, decision_exp


def _handle_time_window_change(
    event: Event,
    deliveries_dict: dict[str, Delivery],
    vehicles_dict: dict[str, Vehicle],
    routes_dict: dict[str, Route],
    graph: CityGraph,
    affected_vehicles: list[str],
    affected_deliveries: list[str],
    changed_routes: list[str],
    reassigned_deliveries: list[str],
    session: Session,
) -> tuple[str, str]:
    did = event.affected_entity_id
    delivery = deliveries_dict.get(did)
    if not delivery:
        return f"Delivery '{did}' not found.", f"Delivery '{did}' not found in active deliveries."

    from app.explainability import explain_time_window_change
    orig_start = float(delivery.time_window_start)
    orig_end = float(delivery.time_window_end)

    params = event.parameters or {}
    new_start = float(params.get("new_window_start", params.get("time_window_start", delivery.time_window_start)))
    new_end = float(params.get("new_window_end", params.get("time_window_end", delivery.time_window_end)))

    delivery.time_window_start = new_start
    delivery.time_window_end = new_end
    session.add(delivery)
    affected_deliveries.append(did)

    assigned_v = delivery.assigned_vehicle
    if not assigned_v or assigned_v not in routes_dict:
        session.commit()
        decision_exp = explain_time_window_change(did, orig_start, orig_end, new_start, new_end, None)
        return f"Delivery {did} time window updated to [{new_start}, {new_end}]. (Unassigned)", decision_exp

    v = vehicles_dict[assigned_v]
    r = routes_dict[assigned_v]
    affected_vehicles.append(assigned_v)

    # 1. Check if current route is still feasible with new window
    feasible, _ = is_route_feasible(r.delivery_ids, v, deliveries_dict, graph)
    if feasible:
        sim = simulate_route_timeline(r.delivery_ids, v, deliveries_dict, graph)
        r.total_travel_time = sim["total_travel_time"]
        r.total_distance = sim["total_distance"]
        r.feasible = True
        session.add(r)
        changed_routes.append(assigned_v)
        session.commit()
        decision_exp = explain_time_window_change(did, orig_start, orig_end, new_start, new_end, assigned_v, stop_reordered=False)
        return f"Delivery {did} time window updated. Existing route for {assigned_v} remains feasible.", decision_exp

    # 2. Local repair: test reordering stops within the same vehicle
    other_stops = [x for x in r.delivery_ids if x != did]
    best_pos: Optional[int] = None
    best_cost = math.inf

    for idx in range(len(other_stops) + 1):
        test_route = other_stops[:idx] + [did] + other_stops[idx:]
        fe, _ = is_route_feasible(test_route, v, deliveries_dict, graph)
        if fe:
            cost = calculate_route_cost(test_route, v, deliveries_dict, graph)
            if cost < best_cost:
                best_cost = cost
                best_pos = idx

    if best_pos is not None:
        r.delivery_ids = other_stops[:best_pos] + [did] + other_stops[best_pos:]
        flag_modified(r, "delivery_ids")
        sim = simulate_route_timeline(r.delivery_ids, v, deliveries_dict, graph)
        r.total_distance = sim["total_distance"]
        r.total_travel_time = sim["total_travel_time"]
        r.feasible = True
        session.add(r)
        changed_routes.append(assigned_v)
        session.commit()
        decision_exp = explain_time_window_change(did, orig_start, orig_end, new_start, new_end, assigned_v, stop_reordered=True, new_stop_index=best_pos)
        return f"Delivery {did} time window changed. Repositioned stop within {assigned_v} to maintain feasibility.", decision_exp

    # 3. Reassign to another active vehicle
    r.delivery_ids = [x for x in r.delivery_ids if x != did]
    flag_modified(r, "delivery_ids")
    sim_original = simulate_route_timeline(r.delivery_ids, v, deliveries_dict, graph)
    r.total_distance = sim_original["total_distance"]
    r.total_travel_time = sim_original["total_travel_time"]
    r.total_load = sim_original["total_load"]
    r.feasible = sim_original["is_feasible"]
    session.add(r)
    v.current_load = sim_original["total_load"]
    session.add(v)
    changed_routes.append(assigned_v)

    alt_v_id: Optional[str] = None
    alt_pos: Optional[int] = None
    alt_cost = math.inf

    for alt_v in vehicles_dict.values():
        if alt_v.status != VehicleStatus.ACTIVE or alt_v.id == assigned_v:
            continue
        alt_r = routes_dict.get(alt_v.id)
        alt_ids = list(alt_r.delivery_ids) if alt_r else []
        curr_load = sum(deliveries_dict[item_id].demand for item_id in alt_ids if item_id in deliveries_dict)
        if curr_load + delivery.demand > alt_v.capacity:
            continue

        for idx in range(len(alt_ids) + 1):
            test_ids = alt_ids[:idx] + [did] + alt_ids[idx:]
            fe, _ = is_route_feasible(test_ids, alt_v, deliveries_dict, graph)
            if fe:
                cost = calculate_route_cost(test_ids, alt_v, deliveries_dict, graph)
                if cost < alt_cost:
                    alt_cost = cost
                    alt_v_id = alt_v.id
                    alt_pos = idx

    if alt_v_id and alt_pos is not None:
        target_route = routes_dict[alt_v_id]
        new_ids = list(target_route.delivery_ids)
        new_ids.insert(alt_pos, did)
        target_route.delivery_ids = new_ids
        flag_modified(target_route, "delivery_ids")
        delivery.assigned_vehicle = alt_v_id
        session.add(delivery)

        sim_target = simulate_route_timeline(target_route.delivery_ids, vehicles_dict[alt_v_id], deliveries_dict, graph)
        target_route.total_distance = sim_target["total_distance"]
        target_route.total_travel_time = sim_target["total_travel_time"]
        target_route.total_load = sim_target["total_load"]
        target_route.feasible = sim_target["is_feasible"]
        session.add(target_route)

        vehicles_dict[alt_v_id].current_load = sim_target["total_load"]
        session.add(vehicles_dict[alt_v_id])

        reassigned_deliveries.append(did)
        affected_vehicles.append(alt_v_id)
        changed_routes.append(alt_v_id)
        session.commit()
        decision_exp = explain_time_window_change(did, orig_start, orig_end, new_start, new_end, assigned_v, reassigned_to=alt_v_id)
        return f"Delivery {did} time window changed. Reassigned from {assigned_v} to {alt_v_id}.", decision_exp
    else:
        delivery.assigned_vehicle = None
        session.add(delivery)
        session.commit()
        decision_exp = f"Delivery {did} time window changed to {new_start:.0f}–{new_end:.0f}m but could not fit feasibly into any vehicle schedule."
        return f"Delivery {did} time window changed. Could not be served feasibly and was unassigned.", decision_exp
