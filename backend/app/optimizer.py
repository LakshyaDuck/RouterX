"""
Initial Fleet Route Optimizer for Delivery Control Tower.

Implements an explainable, deterministic insertion heuristic for Vehicle Routing
with Time Windows (VRPTW), Capacity constraints, and Driver Hours constraints.

Modular design:
  - simulate_route_timeline(): detailed step-by-step route simulation
  - is_route_feasible(): strict constraint checking (capacity, time-windows, driver hours)
  - calculate_route_cost(): multi-objective scoring function
  - calculate_plan_metrics(): KPI aggregation
  - validate_plan(): post-planning verification
  - generate_initial_plan(): priority-first insertion heuristic
"""

import math
from typing import Optional, Union
from sqlmodel import SQLModel, Field

from app.models import (
    Vehicle, Delivery, Node, Road, Route, Event,
    VehicleStatus, DeliveryStatus, EventType
)
from app.routing import CityGraph, build_graph


# ---------------------------------------------------------------------------
# Scoring / Penalty Weights
# ---------------------------------------------------------------------------

DEFAULT_COST_WEIGHTS = {
    "travel_time": 1.0,           # per minute of transit
    "distance": 0.5,              # per kilometer driven
    "lateness_penalty": 100.0,    # per minute delivered after time_window_end
    "capacity_penalty": 1000.0,   # per kg over capacity
    "driver_hours_penalty": 500.0,# per minute exceeding driver hours
    "missed_priority_penalty": 1000.0, # base penalty for unassigned delivery
}


# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------

class OptimizationPlan(SQLModel):
    """Result of fleet route optimization."""
    routes: list[Route]
    unassigned_deliveries: list[str]  # IDs of deliveries not assigned
    total_distance: float
    total_travel_time: float
    number_of_late_deliveries: int
    number_of_capacity_violations: int
    number_of_unassigned_deliveries: int
    before: Optional[dict] = None
    after: Optional[dict] = None
    before_metrics: Optional[dict] = None
    after_metrics: Optional[dict] = None
    routes_changed: list[str] = Field(default_factory=list)
    changed_routes: list[str] = Field(default_factory=list)
    deliveries_reassigned: list[str] = Field(default_factory=list)
    reassigned_deliveries: list[str] = Field(default_factory=list)
    optimization_time_ms: float = 0.0
    explanation: str = ""
    decision_explanation: str = ""
    title: str = "Global Fleet Optimization"
    event_type: str = "FLEET_OPTIMIZATION"
    reoptimization_scope: float = 0.0
    full_state: Optional[dict] = None


# ---------------------------------------------------------------------------
# Route Timeline Simulator
# ---------------------------------------------------------------------------

def simulate_route_timeline(
    route_delivery_ids: list[str],
    vehicle: Vehicle,
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> dict:
    """
    Simulate vehicle driving from its current location through each delivery
    stop and returning to the depot.

    Returns timeline metrics including:
      - arrival_times: dict[delivery_id, float]
      - lateness_per_stop: dict[delivery_id, float]
      - total_distance: float (km)
      - total_travel_time: float (minutes driving)
      - total_load: float (kg)
      - final_return_time: float (minutes from simulation start)
      - capacity_violation: float (kg over capacity)
      - driver_hours_violation: float (minutes over shift)
      - is_reachable: bool
      - is_feasible: bool
    """
    if vehicle.status != VehicleStatus.ACTIVE:
        has_deliveries = len(route_delivery_ids) > 0
        return {
            "is_reachable": not has_deliveries,
            "is_feasible": not has_deliveries,
            "reason": (
                f"Vehicle {vehicle.id} is {vehicle.status} but has {len(route_delivery_ids)} assigned deliveries"
                if has_deliveries
                else f"Vehicle {vehicle.id} is {vehicle.status} (parked/inactive, 0 deliveries)"
            ),
            "total_load": sum(deliveries_dict[did].demand for did in route_delivery_ids if did in deliveries_dict),
            "total_distance": 0.0,
            "total_travel_time": 0.0,
            "final_return_time": start_time,
            "arrival_times": {},
            "lateness_per_stop": {},
            "total_lateness": 0.0,
            "capacity_violation": 0.0,
            "driver_hours_violation": 0.0,
        }

    if not route_delivery_ids:
        return {
            "is_reachable": True,
            "is_feasible": True,
            "reason": "Empty route (idle vehicle)",
            "total_load": 0.0,
            "total_distance": 0.0,
            "total_travel_time": 0.0,
            "final_return_time": start_time,
            "arrival_times": {},
            "lateness_per_stop": {},
            "total_lateness": 0.0,
            "capacity_violation": 0.0,
            "driver_hours_violation": 0.0,
        }

    current_time = start_time
    current_location = vehicle.current_location
    total_distance = 0.0
    total_travel_time = 0.0
    total_load = 0.0
    lateness_per_stop: dict[str, float] = {}
    arrival_times: dict[str, float] = {}

    for delivery_id in route_delivery_ids:
        delivery = deliveries_dict.get(delivery_id)
        if not delivery:
            return {
                "is_reachable": False,
                "is_feasible": False,
                "reason": f"Delivery {delivery_id} not found in deliveries dictionary",
                "total_load": total_load,
                "total_distance": total_distance,
                "total_travel_time": total_travel_time,
                "final_return_time": current_time,
                "lateness_per_stop": lateness_per_stop,
                "total_lateness": 0.0,
                "capacity_violation": 0.0,
                "driver_hours_violation": 0.0,
            }

        total_load += delivery.demand

        # Transit to delivery location
        leg_time = graph.travel_time(current_location, delivery.location)
        if leg_time == math.inf:
            return {
                "is_reachable": False,
                "is_feasible": False,
                "reason": f"No path from {current_location} to {delivery.location}",
                "total_load": total_load,
                "total_distance": total_distance,
                "total_travel_time": total_travel_time,
                "final_return_time": current_time,
                "lateness_per_stop": lateness_per_stop,
                "total_lateness": 0.0,
                "capacity_violation": 0.0,
                "driver_hours_violation": 0.0,
            }

        total_travel_time += leg_time
        path = graph.shortest_path(current_location, delivery.location)
        total_distance += graph.route_distance(path)

        arrival_time = current_time + leg_time
        arrival_times[delivery_id] = arrival_time

        # Check time window
        lateness = max(0.0, arrival_time - delivery.time_window_end)
        lateness_per_stop[delivery_id] = lateness

        # Wait if arrived early, then perform service
        service_start = max(arrival_time, delivery.time_window_start)
        current_time = service_start + service_time
        current_location = delivery.location

    # Return to central depot
    return_leg_time = graph.travel_time(current_location, "depot")
    if return_leg_time == math.inf:
        return {
            "is_reachable": False,
            "is_feasible": False,
            "reason": f"No return path from {current_location} to depot",
            "total_load": total_load,
            "total_distance": total_distance,
            "total_travel_time": total_travel_time,
            "final_return_time": current_time,
            "lateness_per_stop": lateness_per_stop,
            "total_lateness": sum(lateness_per_stop.values()),
            "capacity_violation": 0.0,
            "driver_hours_violation": 0.0,
        }

    total_travel_time += return_leg_time
    ret_path = graph.shortest_path(current_location, "depot")
    total_distance += graph.route_distance(ret_path)
    final_return_time = current_time + return_leg_time

    # Constraint checks
    max_driver_minutes = vehicle.driver_hours_remaining * 60.0
    elapsed_duration = final_return_time - start_time
    driver_hours_violation = max(0.0, elapsed_duration - max_driver_minutes)
    capacity_violation = max(0.0, total_load - vehicle.capacity)
    total_lateness = sum(lateness_per_stop.values())

    is_feasible = (
        capacity_violation == 0.0
        and driver_hours_violation == 0.0
        and total_lateness == 0.0
    )

    reason = "Feasible" if is_feasible else ""
    if not is_feasible:
        reasons = []
        if capacity_violation > 0:
            reasons.append(f"Capacity exceeded by {capacity_violation:.1f} kg")
        if driver_hours_violation > 0:
            reasons.append(f"Driver hours exceeded by {driver_hours_violation:.1f} min")
        if total_lateness > 0:
            reasons.append(f"Time window missed by {total_lateness:.1f} min")
        reason = "; ".join(reasons)

    return {
        "is_reachable": True,
        "is_feasible": is_feasible,
        "reason": reason,
        "total_load": round(total_load, 2),
        "total_distance": round(total_distance, 2),
        "total_travel_time": round(total_travel_time, 2),
        "final_return_time": round(final_return_time, 2),
        "arrival_times": arrival_times,
        "lateness_per_stop": lateness_per_stop,
        "total_lateness": round(total_lateness, 2),
        "capacity_violation": round(capacity_violation, 2),
        "driver_hours_violation": round(driver_hours_violation, 2),
    }


# ---------------------------------------------------------------------------
# Feasibility & Cost Evaluation
# ---------------------------------------------------------------------------

def is_route_feasible(
    route_delivery_ids: list[str],
    vehicle: Vehicle,
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> tuple[bool, str]:
    """
    Check if a route satisfies all operational constraints:
      - Vehicle capacity (total load <= vehicle.capacity)
      - Delivery time windows (arrival <= time_window_end for each stop)
      - Driver shift limits (total route duration <= driver_hours_remaining * 60)
      - Road network connectivity (all legs reachable)

    Returns (is_feasible: bool, reason: str).
    """
    sim = simulate_route_timeline(
        route_delivery_ids=route_delivery_ids,
        vehicle=vehicle,
        deliveries_dict=deliveries_dict,
        graph=graph,
        service_time=service_time,
        start_time=start_time,
    )
    return sim["is_feasible"], sim["reason"]


def calculate_route_cost(
    route_delivery_ids: list[str],
    vehicle: Vehicle,
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
    weights: Optional[dict] = None,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> float:
    """
    Scoring function that computes the cost of a route.
    Considers:
      - Total travel time
      - Total distance
      - Lateness penalty
      - Capacity violation penalty
      - Driver overtime penalty

    Returns a scalar cost (lower is better).
    """
    w = {**DEFAULT_COST_WEIGHTS, **(weights or {})}
    sim = simulate_route_timeline(
        route_delivery_ids=route_delivery_ids,
        vehicle=vehicle,
        deliveries_dict=deliveries_dict,
        graph=graph,
        service_time=service_time,
        start_time=start_time,
    )

    if not sim["is_reachable"]:
        return 1e9  # Unreachable route has prohibitive cost

    cost = (
        (sim["total_travel_time"] * w["travel_time"])
        + (sim["total_distance"] * w["distance"])
        + (sim["total_lateness"] * w["lateness_penalty"])
        + (sim["capacity_violation"] * w["capacity_penalty"])
        + (sim["driver_hours_violation"] * w["driver_hours_penalty"])
    )
    return round(cost, 2)


# ---------------------------------------------------------------------------
# Metrics & Plan Validation
# ---------------------------------------------------------------------------

ACTIVE_DELIVERY_STATUSES = {DeliveryStatus.PENDING, DeliveryStatus.IN_PROGRESS}


def _status_value(entity) -> str:
    status = getattr(entity, "status", "")
    return str(getattr(status, "value", status))


def validate_fleet_state(
    routes: list[Route],
    vehicles: list[Vehicle],
    deliveries: list[Delivery],
    graph: CityGraph,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> dict:
    """Freshly validate one fleet snapshot and derive its authoritative metrics.

    Violation counts are counts of independently invalid constraints: one per
    overloaded route, late delivery, overtime route, unassigned active delivery,
    and assignment/reachability inconsistency. Terminal deliveries are excluded
    from assignment counts.
    """
    vehicles_dict = {v.id: v for v in vehicles}
    deliveries_dict = {d.id: d for d in deliveries}
    assignments: dict[str, list[str]] = {}
    violations: list[dict] = []
    infeasible_route_ids: set[str] = set()

    total_distance = 0.0
    total_travel_time = 0.0
    infeasible_routes = 0
    capacity_violations = 0
    time_window_violations = 0
    driver_hour_violations = 0
    unassigned_deliveries = 0
    assignment_violations = 0
    unreachable_routes = 0
    failed_deliveries = 0

    def add_violation(
        kind: str,
        *,
        vehicle_id: Optional[str] = None,
        delivery_id: Optional[str] = None,
        route_id: Optional[str] = None,
        current_value=None,
        allowed_limit=None,
        reason: str,
    ) -> None:
        violations.append({
            "type": kind,
            "vehicle_id": vehicle_id,
            "delivery_id": delivery_id,
            "route_id": route_id,
            "current_value": current_value,
            "allowed_limit": allowed_limit,
            "reason": reason,
        })

    for route in routes:
        vehicle = vehicles_dict.get(route.vehicle_id)
        for delivery_id in route.delivery_ids:
            assignments.setdefault(delivery_id, []).append(route.vehicle_id)

        if vehicle is None:
            infeasible_route_ids.add(route.vehicle_id)
            assignment_violations += 1
            add_violation(
                "unknown_vehicle", vehicle_id=route.vehicle_id,
                route_id=route.vehicle_id, current_value=route.vehicle_id,
                allowed_limit="vehicle in fleet", reason="Route references an unknown vehicle.",
            )
            continue

        sim = simulate_route_timeline(
            route_delivery_ids=route.delivery_ids,
            vehicle=vehicle,
            deliveries_dict=deliveries_dict,
            graph=graph,
            service_time=service_time,
            start_time=start_time,
        )
        total_distance += sim["total_distance"]
        total_travel_time += sim["total_travel_time"]

        for delivery_id in route.delivery_ids:
            if delivery_id not in deliveries_dict:
                assignment_violations += 1
                add_violation(
                    "unknown_delivery", vehicle_id=vehicle.id,
                    delivery_id=delivery_id, route_id=route.vehicle_id,
                    current_value=delivery_id, allowed_limit="delivery in fleet",
                    reason="Route references a delivery that does not exist.",
                )

        if route.delivery_ids and _status_value(vehicle) != VehicleStatus.ACTIVE.value:
            infeasible_route_ids.add(route.vehicle_id)
            assignment_violations += 1
            add_violation(
                "vehicle_unavailable", vehicle_id=vehicle.id,
                route_id=route.vehicle_id, current_value=_status_value(vehicle),
                allowed_limit=VehicleStatus.ACTIVE.value,
                reason="A non-active vehicle has deliveries assigned.",
            )
            continue

        if not sim["is_reachable"]:
            infeasible_route_ids.add(route.vehicle_id)
            unreachable_routes += 1
            add_violation(
                "unreachable_route", vehicle_id=vehicle.id,
                route_id=route.vehicle_id, current_value=sim.get("reason"),
                allowed_limit="all route legs reachable", reason=sim.get("reason", "Route is unreachable."),
            )

        if sim.get("capacity_violation", 0.0) > 0.0:
            capacity_violations += 1
            add_violation(
                "capacity", vehicle_id=vehicle.id, route_id=route.vehicle_id,
                current_value=sim["total_load"], allowed_limit=vehicle.capacity,
                reason=f"Route load exceeds vehicle capacity by {sim['capacity_violation']:.2f} kg.",
            )

        for delivery_id, lateness in sim.get("lateness_per_stop", {}).items():
            if lateness > 0.0:
                time_window_violations += 1
                delivery = deliveries_dict.get(delivery_id)
                arrival_time = sim.get("arrival_times", {}).get(delivery_id)
                add_violation(
                    "time_window", vehicle_id=vehicle.id,
                    delivery_id=delivery_id, route_id=route.vehicle_id,
                    current_value=arrival_time,
                    allowed_limit=delivery.time_window_end if delivery else None,
                    reason=f"Delivery arrived {lateness:.2f} minutes after its time window.",
                )

        if sim.get("driver_hours_violation", 0.0) > 0.0:
            driver_hour_violations += 1
            actual_minutes = sim["final_return_time"] - start_time
            allowed_minutes = vehicle.driver_hours_remaining * 60.0
            add_violation(
                "driver_hours", vehicle_id=vehicle.id,
                route_id=route.vehicle_id, current_value=round(actual_minutes, 2),
                allowed_limit=round(allowed_minutes, 2),
                reason=f"Route duration exceeds the driver's remaining shift by {sim['driver_hours_violation']:.2f} minutes.",
            )

        if not sim["is_feasible"] and _status_value(vehicle) == VehicleStatus.ACTIVE.value:
            infeasible_route_ids.add(route.vehicle_id)

    for delivery_id, vehicle_ids in assignments.items():
        if len(vehicle_ids) > 1:
            for duplicate_vehicle_id in vehicle_ids[1:]:
                assignment_violations += 1
                add_violation(
                    "duplicate_assignment", vehicle_id=duplicate_vehicle_id,
                    delivery_id=delivery_id, route_id=duplicate_vehicle_id,
                    current_value=len(vehicle_ids), allowed_limit=1,
                    reason="Delivery appears in more than one route position.",
                )

    for delivery in deliveries:
        status = _status_value(delivery)
        assigned_vehicles = assignments.get(delivery.id, [])

        if status in {DeliveryStatus.PENDING.value, DeliveryStatus.IN_PROGRESS.value}:
            if not assigned_vehicles:
                unassigned_deliveries += 1
                add_violation(
                    "unassigned_delivery", delivery_id=delivery.id,
                    current_value=None, allowed_limit="assigned to one active vehicle",
                    reason="Active delivery does not appear in a route.",
                )
            elif len(assigned_vehicles) == 1 and delivery.assigned_vehicle != assigned_vehicles[0]:
                assignment_violations += 1
                add_violation(
                    "assignment_mismatch", vehicle_id=assigned_vehicles[0],
                    delivery_id=delivery.id, route_id=assigned_vehicles[0],
                    current_value=delivery.assigned_vehicle,
                    allowed_limit=assigned_vehicles[0],
                    reason="Delivery assignment does not match its route.",
                )
        elif status == DeliveryStatus.FAILED.value:
            failed_deliveries += 1
            add_violation(
                "failed_delivery", delivery_id=delivery.id,
                current_value=status, allowed_limit="PENDING, IN_PROGRESS, or DELIVERED",
                reason="Delivery is marked failed and needs operational follow-up.",
            )
        elif status == DeliveryStatus.CANCELLED.value:
            if assigned_vehicles or delivery.assigned_vehicle is not None:
                assignment_violations += 1
                add_violation(
                    "terminal_delivery_assigned",
                    vehicle_id=assigned_vehicles[0] if assigned_vehicles else delivery.assigned_vehicle,
                    delivery_id=delivery.id,
                    route_id=assigned_vehicles[0] if assigned_vehicles else None,
                    current_value=status, allowed_limit="not present in an active route",
                    reason="Cancelled order remains assigned to a vehicle or route.",
                )

    total_violations = len(violations)
    infeasible_routes = len(infeasible_route_ids)
    return {
        "total_distance": round(total_distance, 2),
        "total_travel_time": round(total_travel_time, 2),
        "distance": round(total_distance, 2),
        "travel_time": round(total_travel_time, 2),
        "total_violations": total_violations,
        "capacity_violations": capacity_violations,
        "time_window_violations": time_window_violations,
        "late_deliveries": time_window_violations,
        "driver_hour_violations": driver_hour_violations,
        "unassigned_deliveries": unassigned_deliveries,
        "assignment_violations": assignment_violations,
        "unreachable_routes": unreachable_routes,
        "failed_deliveries": failed_deliveries,
        "infeasible_routes": infeasible_routes,
        "route_violations": total_violations,
        "number_of_late_deliveries": time_window_violations,
        "number_of_capacity_violations": capacity_violations,
        "number_of_unassigned_deliveries": unassigned_deliveries,
        "violations": violations,
    }


def calculate_plan_metrics(
    routes: list[Route],
    unassigned_deliveries: list[str],
    vehicles_dict: dict[str, Vehicle],
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> dict:
    # `unassigned_deliveries` remains in the public signature for compatibility.
    # The snapshot's delivery statuses and route assignments are authoritative.
    return validate_fleet_state(
        routes=routes,
        vehicles=list(vehicles_dict.values()),
        deliveries=list(deliveries_dict.values()),
        graph=graph,
        service_time=service_time,
        start_time=start_time,
    )


def compute_fleet_metrics(
    routes: list[Route],
    vehicles: list[Vehicle],
    deliveries: list[Delivery],
    nodes: list[Node],
    roads: list[Road],
    graph: Optional[CityGraph] = None,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> dict:
    """
    Authoritative calculation of fleet-wide metrics for any given snapshot.
    Works for both pre-optimization and post-optimization states.
    """
    if graph is None:
        graph = build_graph(nodes, roads)
    vehicles_dict = {v.id: v for v in vehicles}
    deliveries_dict = {d.id: d for d in deliveries}

    return validate_fleet_state(
        routes=routes,
        vehicles=vehicles,
        deliveries=deliveries,
        graph=graph,
        service_time=service_time,
        start_time=start_time,
    )


def recalculate_route_derived_state(
    routes: list[Route],
    vehicles: list[Vehicle],
    deliveries: list[Delivery],
    graph: CityGraph,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> None:
    """Refresh persisted route totals/feasibility and vehicle loads in place."""
    vehicles_dict = {v.id: v for v in vehicles}
    deliveries_dict = {d.id: d for d in deliveries}
    for route in routes:
        vehicle = vehicles_dict.get(route.vehicle_id)
        if vehicle is None:
            route.total_distance = 0.0
            route.total_travel_time = 0.0
            route.total_load = 0.0
            route.feasible = False
            continue
        sim = simulate_route_timeline(
            route_delivery_ids=route.delivery_ids,
            vehicle=vehicle,
            deliveries_dict=deliveries_dict,
            graph=graph,
            service_time=service_time,
            start_time=start_time,
        )
        route.total_distance = sim["total_distance"]
        route.total_travel_time = sim["total_travel_time"]
        route.total_load = sim["total_load"]
        route.feasible = sim["is_feasible"]
        vehicle.current_load = sim["total_load"]


def validate_plan(
    routes: list[Route],
    vehicles_dict: dict[str, Vehicle],
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> tuple[bool, list[str]]:
    """
    Validate every route in the plan.
    Returns (is_valid: bool, issues: list[str]).
    """
    issues = []
    for route in routes:
        vehicle = vehicles_dict.get(route.vehicle_id)
        if not vehicle:
            issues.append(f"Route references unknown vehicle '{route.vehicle_id}'")
            continue

        feasible, reason = is_route_feasible(
            route_delivery_ids=route.delivery_ids,
            vehicle=vehicle,
            deliveries_dict=deliveries_dict,
            graph=graph,
            service_time=service_time,
            start_time=start_time,
        )
        if not feasible:
            issues.append(f"Vehicle '{vehicle.id}' route infeasible: {reason}")

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Initial Plan Generation (Insertion Heuristic)
# ---------------------------------------------------------------------------

def generate_initial_plan(
    vehicles: list[Vehicle],
    deliveries: list[Delivery],
    nodes: list[Node],
    roads: list[Road],
    graph: Optional[CityGraph] = None,
    weights: Optional[dict] = None,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> OptimizationPlan:
    """
    Construct an initial feasible delivery plan.

    Algorithm:
      1. Filter active vehicles and pending deliveries.
      2. Sort deliveries primarily by priority (1=highest), then by time-window urgency.
      3. For each delivery:
         - Identify active candidate vehicles.
         - Test inserting the delivery at every position in each candidate route.
         - Reject candidate insertions violating capacity, time windows, or driver hours.
         - Score feasible insertions using calculate_route_cost().
         - Select the lowest-cost feasible insertion.
         - If no feasible vehicle can take the delivery, mark as unassigned.
      4. Validate every route and compute plan metrics.
      5. Return OptimizationPlan.
    """
    if graph is None:
        graph = build_graph(nodes, roads)

    deliveries_dict = {d.id: d for d in deliveries}
    vehicles_dict = {v.id: v for v in vehicles}

    for delivery in deliveries:
        if _status_value(delivery) not in {status.value for status in ACTIVE_DELIVERY_STATUSES}:
            delivery.assigned_vehicle = None

    # Step 1: Filter active vehicles
    # Database queries do not promise row order. A deterministic vehicle tie
    # break is necessary because equal-cost insertions keep the first candidate.
    active_vehicles = sorted(
        (v for v in vehicles if v.status == VehicleStatus.ACTIVE),
        key=lambda vehicle: vehicle.id,
    )
    v_routes: dict[str, list[str]] = {v.id: [] for v in active_vehicles}

    # Step 2: Sort deliveries primarily by priority, then by time window urgency
    pending_deliveries = [d for d in deliveries if _status_value(d) in {s.value for s in ACTIVE_DELIVERY_STATUSES}]
    sorted_deliveries = sorted(
        pending_deliveries,
        key=lambda d: (d.priority, d.time_window_end, d.time_window_start, d.id),
    )

    unassigned_deliveries: list[str] = []

    # Step 3: Sequential insertion heuristic
    for delivery in sorted_deliveries:
        best_vehicle_id: Optional[str] = None
        best_insert_index: Optional[int] = None
        best_cost: float = math.inf

        for vehicle in active_vehicles:
            current_route = v_routes[vehicle.id]

            # Fast capacity pre-check
            current_load = sum(deliveries_dict[did].demand for did in current_route)
            if current_load + delivery.demand > vehicle.capacity:
                continue  # Rejects candidate violating capacity

            # Test every insertion position in candidate vehicle route
            for idx in range(len(current_route) + 1):
                candidate_route = current_route[:idx] + [delivery.id] + current_route[idx:]

                # Check strict feasibility (capacity, time-windows, driver hours)
                feasible, _ = is_route_feasible(
                    route_delivery_ids=candidate_route,
                    vehicle=vehicle,
                    deliveries_dict=deliveries_dict,
                    graph=graph,
                    service_time=service_time,
                    start_time=start_time,
                )
                if not feasible:
                    continue  # Reject candidate violating constraints

                cost = calculate_route_cost(
                    route_delivery_ids=candidate_route,
                    vehicle=vehicle,
                    deliveries_dict=deliveries_dict,
                    graph=graph,
                    weights=weights,
                    service_time=service_time,
                    start_time=start_time,
                )

                if cost < best_cost:
                    best_cost = cost
                    best_vehicle_id = vehicle.id
                    best_insert_index = idx

        # Step 4: Choose lowest-cost feasible insertion
        if best_vehicle_id is not None and best_insert_index is not None:
            v_routes[best_vehicle_id].insert(best_insert_index, delivery.id)
            delivery.assigned_vehicle = best_vehicle_id
        else:
            unassigned_deliveries.append(delivery.id)
            delivery.assigned_vehicle = None

    # Step 5: Convert routes to Route models & update vehicle loads
    routes: list[Route] = []
    for vehicle in vehicles:
        route_ids = v_routes.get(vehicle.id, [])
        sim = simulate_route_timeline(
            route_delivery_ids=route_ids,
            vehicle=vehicle,
            deliveries_dict=deliveries_dict,
            graph=graph,
            service_time=service_time,
            start_time=start_time,
        )
        vehicle.current_load = sim["total_load"]
        routes.append(
            Route(
                vehicle_id=vehicle.id,
                delivery_ids=route_ids,
                total_distance=sim["total_distance"],
                total_travel_time=sim["total_travel_time"],
                total_load=sim["total_load"],
                feasible=sim["is_feasible"],
            )
        )

    # Step 6: Validate plan and compute summary metrics
    validate_plan(
        routes=routes,
        vehicles_dict=vehicles_dict,
        deliveries_dict=deliveries_dict,
        graph=graph,
        service_time=service_time,
        start_time=start_time,
    )

    metrics = calculate_plan_metrics(
        routes=routes,
        unassigned_deliveries=unassigned_deliveries,
        vehicles_dict=vehicles_dict,
        deliveries_dict=deliveries_dict,
        graph=graph,
        service_time=service_time,
        start_time=start_time,
    )

    return OptimizationPlan(
        routes=routes,
        unassigned_deliveries=unassigned_deliveries,
        total_distance=metrics["total_distance"],
        total_travel_time=metrics["total_travel_time"],
        number_of_late_deliveries=metrics["number_of_late_deliveries"],
        number_of_capacity_violations=metrics["number_of_capacity_violations"],
        number_of_unassigned_deliveries=metrics["number_of_unassigned_deliveries"],
        after=metrics,
        after_metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Incremental Re-Optimization Engine
# ---------------------------------------------------------------------------

class MetricDict(dict):
    """Dictionary supporting both item and attribute access for metrics."""
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'MetricDict' object has no attribute '{name}'")

    def __setattr__(self, name: str, value):
        self[name] = value


class ReoptimizationResult(dict):
    """
    Result returned by repair_affected_routes().

    Provides both dictionary access (result["before"]["distance"])
    and attribute access (result.before.distance) for convenience.
    """
    def __init__(
        self,
        before: MetricDict,
        after: MetricDict,
        reoptimization_scope: float,
        changed_route_percentage: float,
        routes: list[Route],
        unassigned_deliveries: list[str],
        affected_vehicles: list[str],
        affected_deliveries: list[str],
        changed_routes: list[str],
        reassigned_deliveries: list[str],
        explanation: str,
        decision_explanation: str = "",
        plan: Optional[OptimizationPlan] = None,
    ):
        data = {
            "before": before,
            "after": after,
            "reoptimization_scope": round(reoptimization_scope, 4),
            "changed_route_percentage": round(changed_route_percentage, 4),
            "routes": routes,
            "unassigned_deliveries": unassigned_deliveries,
            "affected_vehicles": affected_vehicles,
            "affected_deliveries": affected_deliveries,
            "changed_routes": changed_routes,
            "reassigned_deliveries": reassigned_deliveries,
            "explanation": explanation,
            "decision_explanation": decision_explanation or explanation,
            "plan": plan,
        }
        super().__init__(data)
        for k, v in data.items():
            setattr(self, k, v)


def _does_route_use_road(
    route_delivery_ids: list[str],
    road: Road,
    vehicle: Vehicle,
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
) -> bool:
    """
    Check if a route traverses a specific road along the shortest paths
    between consecutive stops (depot -> stop 1 -> stop 2 ... -> depot).
    """
    if not route_delivery_ids:
        return False

    u, v = road.from_node, road.to_node
    waypoints = [vehicle.current_location]
    for did in route_delivery_ids:
        d = deliveries_dict.get(did)
        if d:
            waypoints.append(d.location)
    waypoints.append("depot")

    for i in range(len(waypoints) - 1):
        src, dst = waypoints[i], waypoints[i + 1]
        path = graph.shortest_path(src, dst)
        for j in range(len(path) - 1):
            if (path[j] == u and path[j + 1] == v) or (path[j] == v and path[j + 1] == u):
                return True
    return False


def _find_best_insertion(
    delivery: Delivery,
    candidate_vehicles: list[Vehicle],
    routes_by_vehicle: dict[str, Route],
    deliveries_dict: dict[str, Delivery],
    graph: CityGraph,
    weights: Optional[dict] = None,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> tuple[Optional[str], Optional[int], float]:
    """
    Find the best feasible insertion slot for a delivery among candidate vehicles
    using greedy local insertion based on calculate_route_cost().
    Returns (best_vehicle_id, best_insert_index, best_cost).
    """
    best_v_id: Optional[str] = None
    best_idx: Optional[int] = None
    best_cost: float = math.inf

    for vehicle in candidate_vehicles:
        if vehicle.status != VehicleStatus.ACTIVE:
            continue

        r = routes_by_vehicle.get(vehicle.id)
        current_stops = list(r.delivery_ids) if r else []

        # Capacity pre-check
        current_load = sum(deliveries_dict[did].demand for did in current_stops if did in deliveries_dict)
        if current_load + delivery.demand > vehicle.capacity:
            continue

        # Test every insertion position
        for idx in range(len(current_stops) + 1):
            cand_route = current_stops[:idx] + [delivery.id] + current_stops[idx:]

            feasible, _ = is_route_feasible(
                route_delivery_ids=cand_route,
                vehicle=vehicle,
                deliveries_dict=deliveries_dict,
                graph=graph,
                service_time=service_time,
                start_time=start_time,
            )
            if not feasible:
                continue

            cost = calculate_route_cost(
                route_delivery_ids=cand_route,
                vehicle=vehicle,
                deliveries_dict=deliveries_dict,
                graph=graph,
                weights=weights,
                service_time=service_time,
                start_time=start_time,
            )

            if cost < best_cost:
                best_cost = cost
                best_v_id = vehicle.id
                best_idx = idx

    return best_v_id, best_idx, best_cost


def repair_affected_routes(
    plan: Union[OptimizationPlan, list[Route]],
    event: Union[Event, dict],
    vehicles: list[Vehicle],
    deliveries: list[Delivery],
    roads: list[Road],
    nodes: Optional[list[Node]] = None,
    graph: Optional[CityGraph] = None,
    weights: Optional[dict] = None,
    service_time: float = 5.0,
    start_time: float = 0.0,
) -> ReoptimizationResult:
    """
    Incrementally repair only the affected routes when an event occurs,
    preserving all unaffected vehicle routes and avoiding full re-optimization.

    ALGORITHM:
      1. Receive current fleet plan and event.
      2. Determine affected vehicles and deliveries.
      3. Preserve all unaffected vehicle routes.
      4. Release only affected deliveries that need reassignment.
      5. For VEHICLE_BREAKDOWN:
         - mark vehicle unavailable
         - remove all uncompleted deliveries from that vehicle
         - find feasible active vehicles
         - insert those deliveries into existing routes
      6. For NEW_DELIVERY:
         - test insertion into existing routes
         - respect capacity and time-window constraints
      7. For TRAFFIC_UPDATE:
         - identify routes using affected road
         - compare current route cost against alternative route options
         - only modify routes when a better feasible alternative exists
      8. For TIME_WINDOW_CHANGE:
         - re-evaluate affected delivery
         - move to another route if necessary

    Returns ReoptimizationResult with before/after metrics, scope,
    changed route percentage, and updated routes.
    """
    # 1. Setup Graph and lookup dictionaries
    if graph is None:
        if nodes is None:
            # Auto-infer minimal nodes from roads and vehicles
            node_ids = set()
            for r in roads:
                node_ids.add(r.from_node)
                node_ids.add(r.to_node)
            for v in vehicles:
                node_ids.add(v.current_location)
            for d in deliveries:
                node_ids.add(d.location)
            node_ids.add("depot")
            nodes = [Node(id=nid, label=nid, lat=0.0, lon=0.0, is_depot=(nid == "depot")) for nid in node_ids]
        graph = build_graph(nodes, roads)
    baseline_graph = graph

    vehicles_dict = {v.id: v for v in vehicles}
    deliveries_dict = {d.id: d for d in deliveries}
    roads_dict = {r.id: r for r in roads}

    # 2. Extract current plan routes and unassigned
    if isinstance(plan, OptimizationPlan):
        routes = [Route(**r.model_dump()) for r in plan.routes]
        unassigned_deliveries = list(plan.unassigned_deliveries)
    else:
        routes = [Route(**r.model_dump()) for r in plan]
        assigned_set = set(did for r in routes for did in r.delivery_ids)
        unassigned_deliveries = [
            d.id for d in deliveries
            if d.id not in assigned_set and d.status == DeliveryStatus.PENDING
        ]

    routes_by_vehicle: dict[str, Route] = {r.vehicle_id: r for r in routes}
    for v in vehicles:
        if v.id not in routes_by_vehicle:
            r = Route(
                vehicle_id=v.id,
                delivery_ids=[],
                total_distance=0.0,
                total_travel_time=0.0,
                total_load=0.0,
                feasible=True,
            )
            routes.append(r)
            routes_by_vehicle[v.id] = r

    # 3. Parse incoming event
    if isinstance(event, dict):
        ev_type = str(event.get("event_type", ""))
        entity_id = str(event.get("affected_entity_id", ""))
        parameters = dict(event.get("parameters") or {})
    else:
        ev_type = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        entity_id = str(event.affected_entity_id or "")
        parameters = dict(event.parameters or {})

    # 4. Compute baseline 'before' metrics
    before_distance = 0.0
    before_travel_time = 0.0
    before_late = 0

    for r in routes:
        v = vehicles_dict.get(r.vehicle_id)
        if v and r.delivery_ids:
            sim = simulate_route_timeline(
                route_delivery_ids=r.delivery_ids,
                vehicle=v,
                deliveries_dict=deliveries_dict,
                graph=graph,
                service_time=service_time,
                start_time=start_time,
            )
            r.total_distance = sim["total_distance"]
            r.total_travel_time = sim["total_travel_time"]
            r.total_load = sim["total_load"]
            r.feasible = sim["is_feasible"]
            before_distance += sim["total_distance"]
            before_travel_time += sim["total_travel_time"]
            for lateness in sim.get("lateness_per_stop", {}).values():
                if lateness > 0.0:
                    before_late += 1
        else:
            before_distance += r.total_distance
            before_travel_time += r.total_travel_time

    # 5. Tracking structures for incremental re-optimization
    affected_vehicles: list[str] = []
    affected_deliveries: list[str] = []
    affected_routes: list[str] = []
    changed_routes_set: set[str] = set()
    reassigned_deliveries: list[str] = []
    explanation: str = ""
    decision_explanation: str = ""

    # -------------------------------------------------------------------------
    # Scenario 1: VEHICLE_BREAKDOWN
    # -------------------------------------------------------------------------
    if ev_type in (EventType.VEHICLE_BREAKDOWN, "VEHICLE_BREAKDOWN"):
        v_id = entity_id or parameters.get("vehicle_id")
        target_v = vehicles_dict.get(v_id)
        if target_v:
            target_v.status = VehicleStatus.BREAKDOWN
            target_v.current_load = 0.0

        affected_vehicles.append(v_id)
        affected_routes.append(v_id)
        changed_routes_set.add(v_id)

        broken_route = routes_by_vehicle.get(v_id)
        if broken_route and broken_route.delivery_ids:
            orphaned = list(broken_route.delivery_ids)
            affected_deliveries.extend(orphaned)

            # Clear broken route stops and load; preserve baseline incurred distance and time
            broken_route.delivery_ids = []
            broken_route.total_load = 0.0
            broken_route.feasible = False

            # Sort released deliveries by priority first, then deadline
            sorted_orphaned = sorted(
                orphaned,
                key=lambda did: (
                    deliveries_dict[did].priority if did in deliveries_dict else 99,
                    deliveries_dict[did].time_window_end if did in deliveries_dict else 9999.0,
                ),
            )

            active_candidates = [
                v for v in vehicles
                if v.status == VehicleStatus.ACTIVE and v.id != v_id
            ]

            reassigned_count = 0
            for did in sorted_orphaned:
                deliv = deliveries_dict.get(did)
                if not deliv:
                    continue

                best_v, best_idx, _ = _find_best_insertion(
                    delivery=deliv,
                    candidate_vehicles=active_candidates,
                    routes_by_vehicle=routes_by_vehicle,
                    deliveries_dict=deliveries_dict,
                    graph=graph,
                    weights=weights,
                    service_time=service_time,
                    start_time=start_time,
                )

                if best_v is not None and best_idx is not None:
                    routes_by_vehicle[best_v].delivery_ids.insert(best_idx, did)
                    deliv.assigned_vehicle = best_v
                    reassigned_deliveries.append(did)
                    changed_routes_set.add(best_v)
                    if best_v not in affected_vehicles:
                        affected_vehicles.append(best_v)
                    reassigned_count += 1
                else:
                    deliv.assigned_vehicle = None
                    if did not in unassigned_deliveries:
                        unassigned_deliveries.append(did)

            unassigned_count = len(orphaned) - reassigned_count
            explanation = (
                f"Vehicle {v_id} marked BREAKDOWN. {reassigned_count} uncompleted orders reassigned "
                f"to active fleet; {unassigned_count} unassigned."
            )
            from app.explainability import explain_vehicle_breakdown
            decision_explanation = explain_vehicle_breakdown(
                broken_vehicle_id=v_id,
                orphaned_count=len(orphaned),
                reassigned_deliveries=reassigned_deliveries,
                target_vehicles=list(changed_routes_set - {v_id}),
                unassigned_count=unassigned_count,
            )
        else:
            explanation = f"Vehicle {v_id} marked BREAKDOWN (no active deliveries on route)."
            decision_explanation = f"Vehicle {v_id} became unavailable. The vehicle had no pending deliveries assigned, so no routes were disrupted."

    # -------------------------------------------------------------------------
    # Scenario 2: NEW_DELIVERY
    # -------------------------------------------------------------------------
    elif ev_type in (EventType.NEW_DELIVERY, "NEW_DELIVERY"):
        did = entity_id or parameters.get("delivery_id")
        if did not in deliveries_dict:
            loc = parameters.get("location", "n1")
            dem = float(parameters.get("demand", 10.0))
            prio = int(parameters.get("priority", 1))
            tw_start = float(parameters.get("time_window_start", 0.0))
            tw_end = float(parameters.get("time_window_end", 120.0))
            new_deliv = Delivery(
                id=did,
                location=loc,
                demand=dem,
                priority=prio,
                time_window_start=tw_start,
                time_window_end=tw_end,
                status=DeliveryStatus.PENDING,
            )
            deliveries.append(new_deliv)
            deliveries_dict[did] = new_deliv

        target_deliv = deliveries_dict[did]
        affected_deliveries.append(did)

        active_candidates = [v for v in vehicles if v.status == VehicleStatus.ACTIVE]
        best_v, best_idx, _ = _find_best_insertion(
            delivery=target_deliv,
            candidate_vehicles=active_candidates,
            routes_by_vehicle=routes_by_vehicle,
            deliveries_dict=deliveries_dict,
            graph=graph,
            weights=weights,
            service_time=service_time,
            start_time=start_time,
        )

        if best_v is not None and best_idx is not None:
            routes_by_vehicle[best_v].delivery_ids.insert(best_idx, did)
            target_deliv.assigned_vehicle = best_v
            changed_routes_set.add(best_v)
            affected_vehicles.append(best_v)
            explanation = (
                f"New priority order {did} (P{target_deliv.priority}, {target_deliv.demand}kg) "
                f"inserted into vehicle {best_v} at stop {best_idx}."
            )
            from app.explainability import explain_new_delivery
            decision_explanation = explain_new_delivery(
                delivery_id=did,
                location=target_deliv.location,
                demand=target_deliv.demand,
                priority=target_deliv.priority,
                time_window_start=target_deliv.time_window_start,
                time_window_end=target_deliv.time_window_end,
                assigned_vehicle=best_v,
                stop_index=best_idx,
            )
        else:
            target_deliv.assigned_vehicle = None
            if did not in unassigned_deliveries:
                unassigned_deliveries.append(did)
            explanation = (
                f"New delivery {did} could not be feasibly assigned to any vehicle "
                f"due to capacity/window constraints."
            )
            from app.explainability import explain_new_delivery
            decision_explanation = explain_new_delivery(
                delivery_id=did,
                location=target_deliv.location,
                demand=target_deliv.demand,
                priority=target_deliv.priority,
                time_window_start=target_deliv.time_window_start,
                time_window_end=target_deliv.time_window_end,
                assigned_vehicle=None,
            )

    # -------------------------------------------------------------------------
    # Scenario 3: TRAFFIC_UPDATE
    # -------------------------------------------------------------------------
    elif ev_type in (EventType.TRAFFIC_UPDATE, "TRAFFIC_UPDATE"):
        road_id = entity_id or parameters.get("road_id")
        mult = float(parameters.get("traffic_multiplier", 2.0))
        target_road = roads_dict.get(road_id)

        if target_road:
            # Identify routes using the affected road on baseline graph
            for r in routes:
                v = vehicles_dict.get(r.vehicle_id)
                if (
                    v
                    and v.status == VehicleStatus.ACTIVE
                    and _does_route_use_road(r.delivery_ids, target_road, v, deliveries_dict, baseline_graph)
                ):
                    affected_routes.append(r.vehicle_id)
                    affected_vehicles.append(r.vehicle_id)
                    affected_deliveries.extend(r.delivery_ids)

            target_road.traffic_multiplier = mult
            graph = build_graph(nodes, roads)

            # Local search: compare current route cost against alternative stop orderings
            for v_id in affected_routes:
                r = routes_by_vehicle[v_id]
                v = vehicles_dict[v_id]

                current_cost = calculate_route_cost(
                    r.delivery_ids, v, deliveries_dict, graph, weights, service_time, start_time
                )
                best_seq = list(r.delivery_ids)
                best_cost = current_cost

                # Test 2-opt reversals
                if len(r.delivery_ids) > 1:
                    for i in range(len(r.delivery_ids)):
                        for j in range(i + 1, len(r.delivery_ids)):
                            cand_seq = r.delivery_ids[:i] + r.delivery_ids[i:j+1][::-1] + r.delivery_ids[j+1:]
                            cand_feas, _ = is_route_feasible(
                                cand_seq, v, deliveries_dict, graph, service_time, start_time
                            )
                            if cand_feas:
                                cand_cost = calculate_route_cost(
                                    cand_seq, v, deliveries_dict, graph, weights, service_time, start_time
                                )
                                if cand_cost < best_cost:
                                    best_cost = cand_cost
                                    best_seq = cand_seq

                # Only modify route if a better feasible alternative exists
                if best_seq != r.delivery_ids:
                    r.delivery_ids = best_seq

                changed_routes_set.add(v_id)

            explanation = (
                f"Traffic on road {road_id} updated to {mult:.1f}x. "
                f"{len(affected_routes)} route(s) evaluated and updated."
            )
            from app.explainability import explain_traffic_update
            decision_explanation = explain_traffic_update(
                road_id=road_id,
                from_node=target_road.from_node,
                to_node=target_road.to_node,
                old_mult=1.0,
                new_mult=mult,
                base_time=target_road.base_time,
                affected_vehicles=affected_routes,
            )
        else:
            explanation = f"Road {road_id} not found."
            decision_explanation = f"Road {road_id} not found in road network."

    # -------------------------------------------------------------------------
    # Scenario 4: TIME_WINDOW_CHANGE
    # -------------------------------------------------------------------------
    elif ev_type in (EventType.TIME_WINDOW_CHANGE, "TIME_WINDOW_CHANGE"):
        did = entity_id or parameters.get("delivery_id")
        target_d = deliveries_dict.get(did)

        if target_d:
            affected_deliveries.append(did)
            if "new_window_start" in parameters:
                target_d.time_window_start = float(parameters["new_window_start"])
            elif "time_window_start" in parameters:
                target_d.time_window_start = float(parameters["time_window_start"])

            if "new_window_end" in parameters:
                target_d.time_window_end = float(parameters["new_window_end"])
            elif "time_window_end" in parameters:
                target_d.time_window_end = float(parameters["time_window_end"])

            # Find currently assigned vehicle
            assigned_v_id = target_d.assigned_vehicle
            if not assigned_v_id:
                for r in routes:
                    if did in r.delivery_ids:
                        assigned_v_id = r.vehicle_id
                        break

            if assigned_v_id and assigned_v_id in routes_by_vehicle:
                affected_routes.append(assigned_v_id)
                affected_vehicles.append(assigned_v_id)
                r = routes_by_vehicle[assigned_v_id]
                v = vehicles_dict[assigned_v_id]

                feasible, _ = is_route_feasible(
                    r.delivery_ids, v, deliveries_dict, graph, service_time, start_time
                )

                if feasible:
                    # Test if shifting stop order improves cost
                    best_seq = list(r.delivery_ids)
                    best_cost = calculate_route_cost(
                        r.delivery_ids, v, deliveries_dict, graph, weights, service_time, start_time
                    )
                    temp_stops = [x for x in r.delivery_ids if x != did]
                    for idx in range(len(temp_stops) + 1):
                        cand_seq = temp_stops[:idx] + [did] + temp_stops[idx:]
                        c_feas, _ = is_route_feasible(
                            cand_seq, v, deliveries_dict, graph, service_time, start_time
                        )
                        if c_feas:
                            c_cost = calculate_route_cost(
                                cand_seq, v, deliveries_dict, graph, weights, service_time, start_time
                            )
                            if c_cost < best_cost:
                                best_cost = c_cost
                                best_seq = cand_seq
                    r.delivery_ids = best_seq
                    changed_routes_set.add(assigned_v_id)
                    explanation = f"Time window updated for {did}. Maintained feasible on vehicle {assigned_v_id}."
                else:
                    # Current stop order infeasible; test local re-insertion
                    temp_stops = [x for x in r.delivery_ids if x != did]
                    found_local = False
                    for idx in range(len(temp_stops) + 1):
                        cand_seq = temp_stops[:idx] + [did] + temp_stops[idx:]
                        c_feas, _ = is_route_feasible(
                            cand_seq, v, deliveries_dict, graph, service_time, start_time
                        )
                        if c_feas:
                            r.delivery_ids = cand_seq
                            changed_routes_set.add(assigned_v_id)
                            found_local = True
                            explanation = (
                                f"Time window changed for {did}. Reordered stop sequence on "
                                f"{assigned_v_id} to satisfy new window."
                            )
                            break

                    if not found_local:
                        # Move to another route if necessary
                        r.delivery_ids.remove(did)
                        changed_routes_set.add(assigned_v_id)

                        other_active = [
                            ov for ov in vehicles
                            if ov.status == VehicleStatus.ACTIVE and ov.id != assigned_v_id
                        ]
                        best_ov, best_oidx, _ = _find_best_insertion(
                            delivery=target_d,
                            candidate_vehicles=other_active,
                            routes_by_vehicle=routes_by_vehicle,
                            deliveries_dict=deliveries_dict,
                            graph=graph,
                            weights=weights,
                            service_time=service_time,
                            start_time=start_time,
                        )

                        if best_ov is not None and best_oidx is not None:
                            routes_by_vehicle[best_ov].delivery_ids.insert(best_oidx, did)
                            target_d.assigned_vehicle = best_ov
                            changed_routes_set.add(best_ov)
                            reassigned_deliveries.append(did)
                            if best_ov not in affected_vehicles:
                                affected_vehicles.append(best_ov)
                            explanation = (
                                f"Time window changed for {did}. Infeasible on {assigned_v_id}; "
                                f"moved to vehicle {best_ov}."
                            )
                        else:
                            target_d.assigned_vehicle = None
                            if did not in unassigned_deliveries:
                                unassigned_deliveries.append(did)
                            explanation = (
                                f"Time window changed for {did}. Infeasible on {assigned_v_id} and "
                                f"cannot be accommodated by other vehicles (unassigned)."
                            )
        else:
            explanation = f"Delivery {did} not found."

    # -------------------------------------------------------------------------
    # Scenario 5: ROAD_BLOCKED
    # -------------------------------------------------------------------------
    elif ev_type in (EventType.ROAD_BLOCKED, "ROAD_BLOCKED"):
        road_id = entity_id or parameters.get("road_id")
        target_road = roads_dict.get(road_id)
        if target_road:
            # Check which routes traversed this road before the block
            for r in routes:
                v = vehicles_dict.get(r.vehicle_id)
                if (
                    v
                    and v.status == VehicleStatus.ACTIVE
                    and _does_route_use_road(r.delivery_ids, target_road, v, deliveries_dict, baseline_graph)
                ):
                    affected_routes.append(r.vehicle_id)
                    affected_vehicles.append(r.vehicle_id)
                    affected_deliveries.extend(r.delivery_ids)
                    changed_routes_set.add(r.vehicle_id)

            blocked_val = bool(parameters.get("blocked", not target_road.blocked))
            target_road.blocked = blocked_val
            graph = build_graph(nodes, roads)

            explanation = f"Road {road_id} blocked status set to {blocked_val}."
        else:
            explanation = f"Road {road_id} not found."

    else:
        explanation = f"Unhandled event type: {ev_type}"

    # 6. Recalculate metrics for changed routes
    for v_id in changed_routes_set:
        r = routes_by_vehicle[v_id]
        v = vehicles_dict.get(v_id)
        if v and r.delivery_ids and v.status == VehicleStatus.ACTIVE:
            sim = simulate_route_timeline(
                route_delivery_ids=r.delivery_ids,
                vehicle=v,
                deliveries_dict=deliveries_dict,
                graph=graph,
                service_time=service_time,
                start_time=start_time,
            )
            r.total_distance = sim["total_distance"]
            r.total_travel_time = sim["total_travel_time"]
            r.total_load = sim["total_load"]
            r.feasible = sim["is_feasible"]
            v.current_load = sim["total_load"]
        elif v and v.status == VehicleStatus.BREAKDOWN:
            r.delivery_ids = []
            r.total_load = 0.0
            r.feasible = False
            v.current_load = 0.0

    # 7. Compute after-metrics
    after_distance = 0.0
    after_travel_time = 0.0
    after_late = 0

    for r in routes:
        v = vehicles_dict.get(r.vehicle_id)
        if v and r.delivery_ids and v.status == VehicleStatus.ACTIVE:
            sim = simulate_route_timeline(
                route_delivery_ids=r.delivery_ids,
                vehicle=v,
                deliveries_dict=deliveries_dict,
                graph=graph,
                service_time=service_time,
                start_time=start_time,
            )
            after_distance += sim["total_distance"]
            after_travel_time += sim["total_travel_time"]
            for lateness in sim.get("lateness_per_stop", {}).values():
                if lateness > 0.0:
                    after_late += 1
        else:
            after_distance += r.total_distance
            after_travel_time += r.total_travel_time

    changed_routes_list = sorted(list(changed_routes_set))
    unique_affected_deliveries = sorted(list(set(affected_deliveries)))
    total_deliveries = max(1, len(deliveries))
    total_routes = max(1, len(routes))

    reoptimization_scope = len(unique_affected_deliveries) / total_deliveries
    changed_route_percentage = len(changed_routes_list) / total_routes

    before_metrics = MetricDict(
        distance=round(before_distance, 2),
        travel_time=round(before_travel_time, 2),
        late_deliveries=before_late,
        affected_routes=affected_routes,
    )

    after_metrics = MetricDict(
        distance=round(after_distance, 2),
        travel_time=round(after_travel_time, 2),
        late_deliveries=after_late,
        changed_routes=changed_routes_list,
        reassigned_deliveries=reassigned_deliveries,
    )

    updated_plan = OptimizationPlan(
        routes=routes,
        unassigned_deliveries=unassigned_deliveries,
        total_distance=round(after_distance, 2),
        total_travel_time=round(after_travel_time, 2),
        number_of_late_deliveries=after_late,
        number_of_capacity_violations=sum(1 for r in routes if not r.feasible),
        number_of_unassigned_deliveries=len(unassigned_deliveries),
    )

    return ReoptimizationResult(
        before=before_metrics,
        after=after_metrics,
        reoptimization_scope=reoptimization_scope,
        changed_route_percentage=changed_route_percentage,
        routes=routes,
        unassigned_deliveries=unassigned_deliveries,
        affected_vehicles=affected_vehicles,
        affected_deliveries=unique_affected_deliveries,
        changed_routes=changed_routes_list,
        reassigned_deliveries=reassigned_deliveries,
        explanation=explanation,
        decision_explanation=decision_explanation or explanation,
        plan=updated_plan,
    )
