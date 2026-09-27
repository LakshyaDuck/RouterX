"""
Automated test suite for the Incremental Re-Optimization Engine (repair_affected_routes).

Verifies the core project differentiator:
  1. We do NOT recompute all routes from scratch when an event occurs.
  2. Unaffected vehicle routes are strictly preserved.
  3. Incremental repair algorithms for:
     - Vehicle breakdown (offload & reassign to feasible active vehicles)
     - Traffic jam (re-evaluate routes traversing affected road)
     - New priority order (greedy insertion respecting capacity and time windows)
     - Time-window change (local reordering or move to another route)
     - Multiple events sequentially (cumulative incremental repairs)
     - Impossible reassignment (gracefully handled as unassigned without constraint violations)
  4. Accuracy of metrics:
     - before (distance, travel_time, late_deliveries, affected_routes)
     - after (distance, travel_time, late_deliveries, changed_routes, reassigned_deliveries)
     - reoptimization_scope = affected deliveries / total deliveries
     - changed_route_percentage = changed routes / total routes
"""

import pytest
from app.models import (
    Vehicle, Delivery, Node, Road, Route, Event,
    VehicleStatus, DeliveryStatus, EventType
)
from app.routing import build_graph
from app.optimizer import (
    generate_initial_plan,
    repair_affected_routes,
    ReoptimizationResult,
)


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

def _node(nid: str, is_depot: bool = False) -> Node:
    return Node(id=nid, label=nid, lat=40.7, lon=-74.0, is_depot=is_depot)


def _road(rid: str, u: str, v: str, dist: float = 2.0, base: float = 5.0) -> Road:
    return Road(id=rid, from_node=u, to_node=v, distance=dist, base_time=base, traffic_multiplier=1.0)


@pytest.fixture
def multi_vehicle_network():
    """
    Fleet network with central depot and multiple delivery clusters:
        depot ---5m,2km--- n1 ---3m,1km--- n2
        depot ---5m,2km--- n3 ---3m,1km--- n4
        depot ---6m,3km--- n5 ---4m,2km--- n6
        n2    ---4m,2km--- n3
    """
    nodes = [
        _node("depot", is_depot=True),
        _node("n1"), _node("n2"), _node("n3"),
        _node("n4"), _node("n5"), _node("n6"),
    ]
    roads = [
        _road("r_d_1", "depot", "n1", dist=2.0, base=5.0),
        _road("r_1_2", "n1", "n2", dist=1.0, base=3.0),
        _road("r_d_3", "depot", "n3", dist=2.0, base=5.0),
        _road("r_3_4", "n3", "n4", dist=1.0, base=3.0),
        _road("r_d_5", "depot", "n5", dist=3.0, base=6.0),
        _road("r_5_6", "n5", "n6", dist=2.0, base=4.0),
        _road("r_2_3", "n2", "n3", dist=2.0, base=4.0),
    ]
    graph = build_graph(nodes, roads)
    return nodes, roads, graph


# ---------------------------------------------------------------------------
# 1. Vehicle Breakdown Test
# ---------------------------------------------------------------------------

def test_repair_vehicle_breakdown(multi_vehicle_network):
    """
    When vehicle v1 breaks down:
      - v1 is marked BREAKDOWN
      - v1's deliveries are removed and reassigned to active vehicles (v2, v3)
      - Unaffected routes not receiving deliveries are preserved
      - Metrics, scope, and changed route percentage are accurate
    """
    nodes, roads, graph = multi_vehicle_network

    v1 = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v2 = Vehicle(id="v2", name="Van 2", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v3 = Vehicle(id="v3", name="Van 3", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    vehicles = [v1, v2, v3]

    d1 = Delivery(id="d1", location="n1", demand=20.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    d2 = Delivery(id="d2", location="n2", demand=20.0, priority=2, time_window_start=0.0, time_window_end=120.0)
    d3 = Delivery(id="d3", location="n3", demand=20.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    d4 = Delivery(id="d4", location="n4", demand=20.0, priority=2, time_window_start=0.0, time_window_end=120.0)
    d5 = Delivery(id="d5", location="n5", demand=20.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    deliveries = [d1, d2, d3, d4, d5]

    plan = generate_initial_plan(vehicles, deliveries, nodes, roads, graph=graph)
    assert plan.number_of_unassigned_deliveries == 0

    # Ensure v1 has deliveries
    v1_route = next(r for r in plan.routes if r.vehicle_id == "v1")
    assert len(v1_route.delivery_ids) > 0, "v1 should have assigned deliveries initially"
    initial_v1_stops = list(v1_route.delivery_ids)

    # Trigger vehicle breakdown event
    event = {
        "event_type": "VEHICLE_BREAKDOWN",
        "affected_entity_id": "v1",
        "parameters": {"reason": "transmission failure"},
    }

    result = repair_affected_routes(
        plan=plan,
        event=event,
        vehicles=vehicles,
        deliveries=deliveries,
        roads=roads,
        nodes=nodes,
        graph=graph,
    )

    assert isinstance(result, ReoptimizationResult)
    assert v1.status == VehicleStatus.BREAKDOWN

    # Broken vehicle's route is cleared
    rep_v1_route = next(r for r in result.routes if r.vehicle_id == "v1")
    assert rep_v1_route.delivery_ids == []
    assert not rep_v1_route.feasible

    # Reassigned deliveries include all of v1's initial stops
    for stop in initial_v1_stops:
        assert stop in result.reassigned_deliveries
        # Confirmed assigned to either v2 or v3
        assigned_route = next(r for r in result.routes if stop in r.delivery_ids)
        assert assigned_route.vehicle_id in ("v2", "v3")

    # Metrics check
    assert "distance" in result.before
    assert "travel_time" in result.before
    assert "affected_routes" in result.before
    assert "v1" in result.before.affected_routes

    assert "distance" in result.after
    assert "changed_routes" in result.after
    assert "v1" in result.after.changed_routes
    assert len(result.reassigned_deliveries) == len(initial_v1_stops)

    # Scope calculations
    expected_scope = len(initial_v1_stops) / len(deliveries)
    assert pytest.approx(result.reoptimization_scope, 0.01) == expected_scope
    assert 0.0 < result.changed_route_percentage <= 1.0


# ---------------------------------------------------------------------------
# 2. Traffic Jam Test
# ---------------------------------------------------------------------------

def test_repair_traffic_jam(multi_vehicle_network):
    """
    Traffic jam increases travel time on r_d_1 (depot to n1).
    Routes traversing r_d_1 are detected as affected and evaluated.
    Routes not using r_d_1 are preserved untouched.
    """
    nodes, roads, graph = multi_vehicle_network

    v1 = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v2 = Vehicle(id="v2", name="Van 2", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    vehicles = [v1, v2]

    # d1 is at n1 (uses r_d_1); d5 is at n5 (uses r_d_5, independent)
    d1 = Delivery(id="d1", location="n1", demand=20.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    d5 = Delivery(id="d5", location="n5", demand=20.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    deliveries = [d1, d5]

    plan = generate_initial_plan(vehicles, deliveries, nodes, roads, graph=graph)

    # Route using n1
    v_n1 = next(r.vehicle_id for r in plan.routes if "d1" in r.delivery_ids)
    v_n5 = next(r.vehicle_id for r in plan.routes if "d5" in r.delivery_ids)

    initial_n5_stops = list(next(r for r in plan.routes if r.vehicle_id == v_n5).delivery_ids)

    # Traffic jam on r_d_1
    event = {
        "event_type": "TRAFFIC_UPDATE",
        "affected_entity_id": "r_d_1",
        "parameters": {"traffic_multiplier": 4.0},
    }

    result = repair_affected_routes(
        plan=plan,
        event=event,
        vehicles=vehicles,
        deliveries=deliveries,
        roads=roads,
        nodes=nodes,
        graph=graph,
    )

    # r_d_1 road is updated
    road_obj = next(r for r in roads if r.id == "r_d_1")
    assert road_obj.traffic_multiplier == 4.0

    # Only v_n1 route was affected
    assert v_n1 in result.before.affected_routes
    assert v_n1 in result.after.changed_routes

    # If v_n5 is distinct from v_n1, v_n5 stops are identical (preserved)
    if v_n5 != v_n1:
        rep_n5 = next(r for r in result.routes if r.vehicle_id == v_n5)
        assert rep_n5.delivery_ids == initial_n5_stops


# ---------------------------------------------------------------------------
# 3. New Priority Order Test
# ---------------------------------------------------------------------------

def test_repair_new_priority_order(multi_vehicle_network):
    """
    A new high-priority order arrives and is inserted into existing active routes
    without modifying unaffected vehicle routes.
    """
    nodes, roads, graph = multi_vehicle_network

    v1 = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v2 = Vehicle(id="v2", name="Van 2", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    vehicles = [v1, v2]

    d1 = Delivery(id="d1", location="n1", demand=20.0, priority=2, time_window_start=0.0, time_window_end=120.0)
    deliveries = [d1]

    plan = generate_initial_plan(vehicles, deliveries, nodes, roads, graph=graph)

    # New rush delivery at n2
    event = {
        "event_type": "NEW_DELIVERY",
        "affected_entity_id": "d_rush_01",
        "parameters": {
            "location": "n2",
            "demand": 15.0,
            "priority": 1,
            "time_window_start": 5.0,
            "time_window_end": 60.0,
        },
    }

    result = repair_affected_routes(
        plan=plan,
        event=event,
        vehicles=vehicles,
        deliveries=deliveries,
        roads=roads,
        nodes=nodes,
        graph=graph,
    )

    # d_rush_01 was inserted into an active route
    assert "d_rush_01" in result.affected_deliveries
    assert any("d_rush_01" in r.delivery_ids for r in result.routes)
    assert len(result.after.changed_routes) == 1
    assert result.reoptimization_scope <= 0.5  # only 1 delivery out of 2 affected


# ---------------------------------------------------------------------------
# 4. Time-Window Change Test
# ---------------------------------------------------------------------------

def test_repair_time_window_change(multi_vehicle_network):
    """
    When a delivery's time window is tightened so that the current vehicle
    arrives late, the delivery is moved to another vehicle or reordered.
    """
    nodes, roads, graph = multi_vehicle_network

    v1 = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v2 = Vehicle(id="v2", name="Van 2", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    vehicles = [v1, v2]

    # d1 at n1 (5min away), d2 at n2 (8min away)
    d1 = Delivery(id="d1", location="n1", demand=10.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    d2 = Delivery(id="d2", location="n2", demand=10.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    deliveries = [d1, d2]

    plan = generate_initial_plan(vehicles, deliveries, nodes, roads, graph=graph)

    # Tighten window on d2 to [0, 15] min
    event = {
        "event_type": "TIME_WINDOW_CHANGE",
        "affected_entity_id": "d2",
        "parameters": {
            "new_window_start": 0.0,
            "new_window_end": 15.0,
        },
    }

    result = repair_affected_routes(
        plan=plan,
        event=event,
        vehicles=vehicles,
        deliveries=deliveries,
        roads=roads,
        nodes=nodes,
        graph=graph,
    )

    assert "d2" in result.affected_deliveries
    assert result.after.late_deliveries == 0, "Repaired plan must satisfy the new time window"
    # Scope is exactly 1 out of 2 deliveries (0.5)
    assert pytest.approx(result.reoptimization_scope, 0.01) == 0.5


# ---------------------------------------------------------------------------
# 5. Multiple Events Sequentially Test
# ---------------------------------------------------------------------------

def test_repair_multiple_events_sequentially(multi_vehicle_network):
    """
    Chain 3 events incrementally:
      1. New delivery
      2. Traffic spike
      3. Vehicle breakdown
    Each step re-optimizes only the affected portion from the previous state.
    """
    nodes, roads, graph = multi_vehicle_network

    v1 = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v2 = Vehicle(id="v2", name="Van 2", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v3 = Vehicle(id="v3", name="Van 3", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    vehicles = [v1, v2, v3]

    d1 = Delivery(id="d1", location="n1", demand=15.0, priority=2, time_window_start=0.0, time_window_end=120.0)
    d2 = Delivery(id="d2", location="n3", demand=15.0, priority=2, time_window_start=0.0, time_window_end=120.0)
    deliveries = [d1, d2]

    # Initial plan
    plan = generate_initial_plan(vehicles, deliveries, nodes, roads, graph=graph)

    # Step 1: New Delivery
    ev1 = {
        "event_type": "NEW_DELIVERY",
        "affected_entity_id": "d_seq_1",
        "parameters": {"location": "n5", "demand": 10.0, "priority": 1, "time_window_start": 0.0, "time_window_end": 120.0},
    }
    res1 = repair_affected_routes(plan, ev1, vehicles, deliveries, roads, nodes, graph)
    assert any("d_seq_1" in r.delivery_ids for r in res1.routes)
    assert res1.plan.number_of_unassigned_deliveries == 0

    # Step 2: Traffic Spike
    ev2 = {
        "event_type": "TRAFFIC_UPDATE",
        "affected_entity_id": "r_d_1",
        "parameters": {"traffic_multiplier": 3.0},
    }
    res2 = repair_affected_routes(res1.plan, ev2, vehicles, deliveries, roads, nodes, graph)
    assert res2.reoptimization_scope <= 1.0

    # Step 3: Vehicle Breakdown on v1
    ev3 = {
        "event_type": "VEHICLE_BREAKDOWN",
        "affected_entity_id": "v1",
        "parameters": {"reason": "flat tire"},
    }
    res3 = repair_affected_routes(res2.plan, ev3, vehicles, deliveries, roads, nodes, graph)
    assert v1.status == VehicleStatus.BREAKDOWN
    v1_final_route = next(r for r in res3.routes if r.vehicle_id == "v1")
    assert v1_final_route.delivery_ids == []


# ---------------------------------------------------------------------------
# 6. Impossible Reassignment Test
# ---------------------------------------------------------------------------

def test_repair_impossible_reassignment(multi_vehicle_network):
    """
    A vehicle with 80kg of demand breaks down.
    The only remaining active vehicle has only 10kg capacity remaining.
    The oversized delivery cannot fit and must be flagged as unassigned
    without violating capacity constraints on the remaining vehicle.
    """
    nodes, roads, graph = multi_vehicle_network

    # v1 has 100kg capacity, v2 has only 30kg capacity
    v1 = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v2 = Vehicle(id="v2", name="Van 2", capacity=30.0, current_location="depot", driver_hours_remaining=8.0)
    vehicles = [v1, v2]

    # d_heavy is 80kg (fits in v1, impossible in v2)
    d_heavy = Delivery(id="d_heavy", location="n1", demand=80.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    # d_small is 25kg (fits in v2)
    d_small = Delivery(id="d_small", location="n3", demand=25.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    deliveries = [d_heavy, d_small]

    plan = generate_initial_plan(vehicles, deliveries, nodes, roads, graph=graph)
    assert "d_heavy" in next(r for r in plan.routes if r.vehicle_id == "v1").delivery_ids

    # Breakdown on v1
    event = {
        "event_type": "VEHICLE_BREAKDOWN",
        "affected_entity_id": "v1",
        "parameters": {"reason": "engine blown"},
    }

    result = repair_affected_routes(
        plan=plan,
        event=event,
        vehicles=vehicles,
        deliveries=deliveries,
        roads=roads,
        nodes=nodes,
        graph=graph,
    )

    # d_heavy cannot fit in v2 (80kg + 25kg > 30kg); must be unassigned
    assert "d_heavy" in result.unassigned_deliveries
    assert "d_heavy" not in result.reassigned_deliveries

    # v2 capacity must NOT be violated
    v2_route = next(r for r in result.routes if r.vehicle_id == "v2")
    assert v2_route.total_load <= v2.capacity
    assert v2_route.feasible, "v2 route must remain strictly feasible"


# ---------------------------------------------------------------------------
# 7. Unaffected Routes Preserved Test
# ---------------------------------------------------------------------------

def test_repair_preserves_unaffected_routes(multi_vehicle_network):
    """
    Explicit verification that routes of vehicles not involved in an event
    remain byte-for-byte identical before and after repair.
    """
    nodes, roads, graph = multi_vehicle_network

    v1 = Vehicle(id="v1", name="Van 1", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v2 = Vehicle(id="v2", name="Van 2", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    v3 = Vehicle(id="v3", name="Van 3", capacity=100.0, current_location="depot", driver_hours_remaining=8.0)
    vehicles = [v1, v2, v3]

    d1 = Delivery(id="d1", location="n1", demand=10.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    d3 = Delivery(id="d3", location="n3", demand=10.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    d5 = Delivery(id="d5", location="n5", demand=10.0, priority=1, time_window_start=0.0, time_window_end=120.0)
    deliveries = [d1, d3, d5]

    plan = generate_initial_plan(vehicles, deliveries, nodes, roads, graph=graph)

    # Let's map which vehicle has which delivery
    route_map_before = {r.vehicle_id: list(r.delivery_ids) for r in plan.routes}

    # Add a new delivery specifically targeted to insert near n1 (v1)
    event = {
        "event_type": "NEW_DELIVERY",
        "affected_entity_id": "d_extra",
        "parameters": {"location": "n2", "demand": 5.0, "priority": 1, "time_window_start": 0.0, "time_window_end": 120.0},
    }

    result = repair_affected_routes(plan, event, vehicles, deliveries, roads, nodes, graph)

    # Changed routes should be at most 1 vehicle
    assert len(result.changed_routes) == 1
    modified_v = result.changed_routes[0]

    # All OTHER vehicles must retain the exact same stops
    for v_id, stops in route_map_before.items():
        if v_id != modified_v:
            after_stops = next(r for r in result.routes if r.vehicle_id == v_id).delivery_ids
            assert after_stops == stops, f"Vehicle {v_id} route was unnecessarily modified!"
