"""
Automated unit tests for the Initial Fleet Route Optimizer.

Tests cover:
  1. capacity constraint — rejects routes exceeding vehicle capacity
  2. time-window constraint — rejects routes that miss delivery windows
  3. priority order — high-priority deliveries (P1) assigned before lower priority
  4. driver-hours constraint — rejects routes exceeding available driver shift
  5. successful assignment — feasible deliveries are all planned
  6. impossible delivery — over-capacity or unreachable delivery marked unassigned
  7. scoring & metrics — calculate_route_cost and calculate_plan_metrics accuracy
  8. plan validation — validate_plan detects infeasible routes
"""

import math
import pytest

from app.models import Vehicle, Delivery, Node, Road, Route, VehicleStatus, DeliveryStatus
from app.routing import build_graph
from app.optimizer import (
    generate_initial_plan,
    is_route_feasible,
    calculate_route_cost,
    calculate_plan_metrics,
    validate_plan,
)


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

def _node(nid: str, is_depot: bool = False) -> Node:
    return Node(id=nid, label=nid, lat=40.7, lon=-74.0, is_depot=is_depot)


def _road(rid: str, u: str, v: str, dist: float = 2.0, base: float = 5.0) -> Road:
    return Road(id=rid, from_node=u, to_node=v, distance=dist, base_time=base, traffic_multiplier=1.0)


@pytest.fixture
def simple_network():
    """
    Depot connected to 3 delivery nodes:
        depot ---5min,2km--- n1
        depot ---5min,2km--- n2
        depot ---5min,2km--- n3
        n1    ---3min,1km--- n2
    """
    nodes = [_node("depot", is_depot=True), _node("n1"), _node("n2"), _node("n3")]
    roads = [
        _road("r1", "depot", "n1", dist=2.0, base=5.0),
        _road("r2", "depot", "n2", dist=2.0, base=5.0),
        _road("r3", "depot", "n3", dist=2.0, base=5.0),
        _road("r4", "n1", "n2", dist=1.0, base=3.0),
    ]
    graph = build_graph(nodes, roads)
    return nodes, roads, graph


# ---------------------------------------------------------------------------
# 1. Capacity Constraint
# ---------------------------------------------------------------------------

def test_capacity_constraint(simple_network):
    """
    Vehicle with capacity 50 kg cannot take two 30 kg deliveries.
    The second delivery must be rejected from this vehicle.
    """
    nodes, roads, graph = simple_network

    v = Vehicle(id="v1", name="Van 1", capacity=50.0, current_location="depot", driver_hours_remaining=8.0)
    d1 = Delivery(id="d1", location="n1", demand=30.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    d2 = Delivery(id="d2", location="n2", demand=30.0, priority=1, time_window_start=0.0, time_window_end=120.0)

    deliveries_dict = {"d1": d1, "d2": d2}

    # Single delivery is feasible
    feasible, _ = is_route_feasible(["d1"], v, deliveries_dict, graph)
    assert feasible, "Single 30kg delivery should fit in 50kg vehicle"

    # Both deliveries together exceed capacity (60 > 50)
    feasible_both, reason = is_route_feasible(["d1", "d2"], v, deliveries_dict, graph)
    assert not feasible_both, "Combined 60kg load must violate 50kg capacity"
    assert "Capacity exceeded" in reason

    # Optimizer should assign one and leave the other unassigned
    plan = generate_initial_plan([v], [d1, d2], nodes, roads, graph=graph)
    assert plan.number_of_capacity_violations == 0
    assert len(plan.routes[0].delivery_ids) == 1
    assert plan.number_of_unassigned_deliveries == 1


# ---------------------------------------------------------------------------
# 2. Time-Window Constraint
# ---------------------------------------------------------------------------

def test_time_window_constraint(simple_network):
    """
    Delivery has an impossible time window (deadline is at 2 min, but travel time is 5 min).
    Must be rejected for missing the time window.
    """
    nodes, roads, graph = simple_network

    v = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    # Travel from depot to n1 takes 5.0 minutes, but window ends at 2.0 minutes
    d_tight = Delivery(id="dt", location="n1", demand=10.0, priority=1, time_window_start=0.0, time_window_end=2.0)

    deliveries_dict = {"dt": d_tight}
    feasible, reason = is_route_feasible(["dt"], v, deliveries_dict, graph)
    assert not feasible, "Should reject delivery that cannot be reached before window ends"
    assert "Time window missed" in reason

    # Feasible delivery with ample time window
    d_ok = Delivery(id="dok", location="n1", demand=10.0, priority=1, time_window_start=0.0, time_window_end=60.0)
    deliveries_dict_ok = {"dok": d_ok}
    feasible_ok, _ = is_route_feasible(["dok"], v, deliveries_dict_ok, graph)
    assert feasible_ok, "Delivery within window should be feasible"


# ---------------------------------------------------------------------------
# 3. Priority Order
# ---------------------------------------------------------------------------

def test_priority_order(simple_network):
    """
    Two competing deliveries for a vehicle with capacity for only one:
    d_low:  priority=3, demand=40 kg, earlier time window [0, 50]
    d_high: priority=1, demand=40 kg, later time window [0, 100]
    Because priority is primary sort, d_high must be assigned and d_low unassigned.
    """
    nodes, roads, graph = simple_network

    v = Vehicle(id="v1", name="Van 1", capacity=50.0, current_location="depot", driver_hours_remaining=8.0)
    d_low = Delivery(id="d_low", location="n1", demand=40.0, priority=3, time_window_start=0.0, time_window_end=50.0)
    d_high = Delivery(id="d_high", location="n2", demand=40.0, priority=1, time_window_start=0.0, time_window_end=100.0)

    # Deliveries input in reverse order to ensure sorting handles it
    plan = generate_initial_plan([v], [d_low, d_high], nodes, roads, graph=graph)

    assigned = plan.routes[0].delivery_ids
    assert "d_high" in assigned, "Higher priority delivery (P1) must be assigned first"
    assert "d_low" not in assigned, "Lower priority delivery (P3) should remain unassigned due to capacity"
    assert "d_low" in plan.unassigned_deliveries


# ---------------------------------------------------------------------------
# 4. Driver-Hours Constraint
# ---------------------------------------------------------------------------

def test_driver_hours_constraint(simple_network):
    """
    Vehicle driver has only 0.15 hours remaining (9 minutes).
    Trip depot -> n1 (5 min) + service (5 min) + return (5 min) = 15 min > 9 min.
    Route must be rejected for exceeding driver hours.
    """
    nodes, roads, graph = simple_network

    v_tired = Vehicle(id="vt", name="Tired Van", capacity=100.0, current_location="depot", driver_hours_remaining=0.15)
    d = Delivery(id="d1", location="n1", demand=10.0, priority=1, time_window_start=0.0, time_window_end=100.0)

    feasible, reason = is_route_feasible(["d1"], v_tired, {"d1": d}, graph, service_time=5.0)
    assert not feasible, "Should reject route exceeding driver hours"
    assert "Driver hours exceeded" in reason

    # Same delivery with full shift driver is feasible
    v_fresh = Vehicle(id="vf", name="Fresh Van", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    feasible_fresh, _ = is_route_feasible(["d1"], v_fresh, {"d1": d}, graph, service_time=5.0)
    assert feasible_fresh, "Fresh driver should be feasible"


# ---------------------------------------------------------------------------
# 5. Successful Assignment
# ---------------------------------------------------------------------------

def test_successful_assignment(simple_network):
    """
    2 vehicles, 3 feasible deliveries: all should be assigned successfully.
    """
    nodes, roads, graph = simple_network

    v1 = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v2 = Vehicle(id="v2", name="Van 2", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)

    d1 = Delivery(id="d1", location="n1", demand=20.0, priority=1, time_window_start=0.0, time_window_end=100.0)
    d2 = Delivery(id="d2", location="n2", demand=20.0, priority=2, time_window_start=0.0, time_window_end=100.0)
    d3 = Delivery(id="d3", location="n3", demand=20.0, priority=3, time_window_start=0.0, time_window_end=100.0)

    plan = generate_initial_plan([v1, v2], [d1, d2, d3], nodes, roads, graph=graph)

    assert plan.number_of_unassigned_deliveries == 0
    assert plan.number_of_capacity_violations == 0
    assert plan.number_of_late_deliveries == 0
    assert len(plan.unassigned_deliveries) == 0

    assigned_total = sum(len(r.delivery_ids) for r in plan.routes)
    assert assigned_total == 3
    assert plan.total_distance > 0.0
    assert plan.total_travel_time > 0.0


# ---------------------------------------------------------------------------
# 6. Impossible Delivery
# ---------------------------------------------------------------------------

def test_impossible_delivery_over_capacity(simple_network):
    """
    Delivery with demand 500 kg when vehicle capacity is only 100 kg.
    Must be marked as unassigned without crashing the optimizer.
    """
    nodes, roads, graph = simple_network

    v = Vehicle(id="v1", name="Small Van", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    d_huge = Delivery(id="dhuge", location="n1", demand=500.0, priority=1, time_window_start=0.0, time_window_end=100.0)
    d_normal = Delivery(id="dnorm", location="n2", demand=30.0, priority=2, time_window_start=0.0, time_window_end=100.0)

    plan = generate_initial_plan([v], [d_huge, d_normal], nodes, roads, graph=graph)

    assert "dhuge" in plan.unassigned_deliveries
    assert plan.number_of_unassigned_deliveries == 1
    assert "dnorm" in plan.routes[0].delivery_ids
    assert plan.routes[0].feasible is True


def test_impossible_delivery_unreachable():
    """
    Delivery located on an island node with no road to depot.
    Must be marked as unassigned.
    """
    nodes = [_node("depot", is_depot=True), _node("island")]
    roads = []  # No roads!
    graph = build_graph(nodes, roads)

    v = Vehicle(id="v1", name="Van", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    d_isolated = Delivery(id="diso", location="island", demand=10.0, priority=1, time_window_start=0.0, time_window_end=100.0)

    plan = generate_initial_plan([v], [d_isolated], nodes, roads, graph=graph)
    assert "diso" in plan.unassigned_deliveries
    assert plan.number_of_unassigned_deliveries == 1


# ---------------------------------------------------------------------------
# 7. Route Cost & Metrics Functions
# ---------------------------------------------------------------------------

def test_calculate_route_cost_and_metrics(simple_network):
    """Verify calculate_route_cost and calculate_plan_metrics compute expected values."""
    nodes, roads, graph = simple_network

    v = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    d1 = Delivery(id="d1", location="n1", demand=20.0, priority=1, time_window_start=0.0, time_window_end=100.0)
    deliveries_dict = {"d1": d1}

    cost = calculate_route_cost(["d1"], v, deliveries_dict, graph)
    assert cost > 0.0
    assert not math.isinf(cost)

    route = Route(vehicle_id="v1", delivery_ids=["d1"], total_distance=4.0, total_travel_time=10.0, total_load=20.0, feasible=True)
    metrics = calculate_plan_metrics([route], [], {"v1": v}, deliveries_dict, graph)
    assert metrics["total_distance"] == 4.0
    assert metrics["total_travel_time"] == 10.0
    assert metrics["number_of_late_deliveries"] == 0
    assert metrics["number_of_capacity_violations"] == 0
    assert metrics["number_of_unassigned_deliveries"] == 0


# ---------------------------------------------------------------------------
# 8. Plan Validation
# ---------------------------------------------------------------------------

def test_validate_plan(simple_network):
    """validate_plan should return (True, []) for a valid plan and flag violations."""
    nodes, roads, graph = simple_network

    v = Vehicle(id="v1", name="Van 1", capacity=50.0, current_location="depot", driver_hours_remaining=8.0)
    d1 = Delivery(id="d1", location="n1", demand=20.0, priority=1, time_window_start=0.0, time_window_end=100.0)
    d2 = Delivery(id="d2", location="n2", demand=40.0, priority=1, time_window_start=0.0, time_window_end=100.0)
    deliveries_dict = {"d1": d1, "d2": d2}

    # Feasible route with just d1 (20kg <= 50kg)
    valid_route = Route(vehicle_id="v1", delivery_ids=["d1"], total_distance=4.0, total_travel_time=10.0, total_load=20.0, feasible=True)
    is_valid, issues = validate_plan([valid_route], {"v1": v}, deliveries_dict, graph)
    assert is_valid is True
    assert issues == []

    # Infeasible route with d1 + d2 (60kg > 50kg capacity)
    invalid_route = Route(vehicle_id="v1", delivery_ids=["d1", "d2"], total_distance=7.0, total_travel_time=15.0, total_load=60.0, feasible=False)
    is_valid_bad, issues_bad = validate_plan([invalid_route], {"v1": v}, deliveries_dict, graph)
    assert is_valid_bad is False
    assert len(issues_bad) == 1
    assert "infeasible" in issues_bad[0]
