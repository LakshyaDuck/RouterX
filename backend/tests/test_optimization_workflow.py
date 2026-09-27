"""
Regression Test Suite: End-to-End Fleet Optimization Workflow & Violation State Consistency

Tests covered:
1. Two violations exist before optimization -> Optimize -> Real post-optimization count updated
2. Clean initial fleet optimization produces 0 violations
3. Optimization response contains valid before/after metrics with all required KPI fields
4. Tracking of routes_changed, deliveries_reassigned, and decision_explanation
5. Revalidation of final plan (all active routes feasible, loads accurate)
6. Broken vehicle with empty route is feasible; broken vehicle with deliveries is infeasible
7. Impossible constraint (demand > vehicle capacity) remains unassigned and counts as violation
8. Sequential optimizations are idempotent and stable
9. Full state returned in plan matches GET /api/state
10. Authoritative metrics consistency between database, optimizer, and event engine
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from sqlalchemy.orm.attributes import flag_modified

from main import app
from app.database import (
    engine,
    get_fleet_state,
    reset_fleet_database,
    get_vehicles,
    get_deliveries,
    get_routes,
    get_nodes,
    get_roads,
)
from app.models import Delivery, DeliveryStatus, Vehicle, VehicleStatus, Route, Node, Road
from app.optimizer import (
    compute_fleet_metrics,
    simulate_route_timeline,
    generate_initial_plan,
)
from app.routing import build_graph

client = TestClient(app)


def fresh_violation_count(routes, vehicles, deliveries, nodes, roads):
    """Independent test-side validation; does not use the metrics aggregator."""
    vehicles_by_id = {v.id: v for v in vehicles}
    deliveries_by_id = {d.id: d for d in deliveries}
    assigned = {}
    violations = 0

    for route in routes:
        for delivery_id in route.delivery_ids:
            assigned.setdefault(delivery_id, []).append(route.vehicle_id)
        vehicle = vehicles_by_id.get(route.vehicle_id)
        if vehicle is None:
            violations += 1
            continue
        if route.delivery_ids and vehicle.status != VehicleStatus.ACTIVE:
            violations += 1
            continue
        sim = simulate_route_timeline(
            route.delivery_ids, vehicle, deliveries_by_id, build_graph(nodes, roads)
        )
        violations += int(not sim["is_reachable"])
        violations += int(sim["capacity_violation"] > 0)
        violations += sum(lateness > 0 for lateness in sim["lateness_per_stop"].values())
        violations += int(sim["driver_hours_violation"] > 0)

    for delivery_id, route_vehicles in assigned.items():
        violations += max(0, len(route_vehicles) - 1)

    for delivery in deliveries:
        status = getattr(delivery.status, "value", delivery.status)
        assigned_vehicles = assigned.get(delivery.id, [])
        if status in ("PENDING", "IN_PROGRESS"):
            if not assigned_vehicles:
                violations += 1
            elif len(assigned_vehicles) == 1 and delivery.assigned_vehicle != assigned_vehicles[0]:
                violations += 1
        elif status == "FAILED":
            violations += 1
        elif status in ("CANCELLED", "DELIVERED"):
            if assigned_vehicles or delivery.assigned_vehicle is not None:
                violations += 1
    return violations


def assert_persisted_route_values_are_fresh(state):
    vehicles = {v.id: v for v in state.vehicles}
    deliveries = {d.id: d for d in state.deliveries}
    graph = build_graph(state.nodes, state.roads)
    for route in state.routes:
        sim = simulate_route_timeline(route.delivery_ids, vehicles[route.vehicle_id], deliveries, graph)
        assert route.total_distance == pytest.approx(sim["total_distance"], abs=0.01)
        assert route.total_travel_time == pytest.approx(sim["total_travel_time"], abs=0.01)
        assert route.total_load == pytest.approx(sim["total_load"], abs=0.01)
        assert route.feasible is sim["is_feasible"]
        assert vehicles[route.vehicle_id].current_load == pytest.approx(sim["total_load"], abs=0.01)


@pytest.fixture(autouse=True)
def reset_db():
    """Ensure every test starts with clean deterministic fleet state."""
    reset_fleet_database()
    yield


def test_1_two_violations_before_optimization_resets_and_updates_correctly():
    """
    Core bug regression test:
    Setup a fleet state with exactly 2 violations before optimization.
    Run /optimize.
    Verify:
      1. before_metrics reports exactly 2 violations
      2. after_metrics reports real post-optimization count (0 violations if fully resolved)
      3. Response contains before vs after metrics
      4. Database state and full_state reflect the new post-optimization count
    """
    with Session(engine) as s:
        # Add 2 pending deliveries that are NOT assigned to any vehicle
        d_extra1 = Delivery(
            id="del_extra_01",
            location="n02",
            demand=15.0,
            priority=1,
            time_window_start=0.0,
            time_window_end=300.0,
            status=DeliveryStatus.PENDING,
            assigned_vehicle=None,
        )
        d_extra2 = Delivery(
            id="del_extra_02",
            location="n04",
            demand=20.0,
            priority=2,
            time_window_start=0.0,
            time_window_end=300.0,
            status=DeliveryStatus.PENDING,
            assigned_vehicle=None,
        )
        s.add(d_extra1)
        s.add(d_extra2)
        s.commit()

        # Verify initial pre-optimization state has exactly 2 violations
        state_before = get_fleet_state(s)
        assert state_before.metrics["total_violations"] == 2
        assert state_before.metrics["unassigned_deliveries"] == 2

    # Call POST /api/optimize
    resp = client.post("/api/optimize")
    assert resp.status_code == 200
    data = resp.json()

    # Verify BEFORE metrics captured the 2 violations
    assert data["before_metrics"] is not None
    assert data["before_metrics"]["total_violations"] == 2
    assert data["before_metrics"]["unassigned_deliveries"] == 2

    # Verify AFTER metrics resolved the violations feasibly
    assert data["after_metrics"] is not None
    assert data["after_metrics"]["total_violations"] == 0
    assert data["after_metrics"]["unassigned_deliveries"] == 0
    assert data["after_metrics"]["capacity_violations"] == 0
    assert data["after_metrics"]["time_window_violations"] == 0

    # Verify routes changed and deliveries reassigned were tracked
    assert len(data["routes_changed"]) > 0
    assert "del_extra_01" in data["deliveries_reassigned"] or any(
        "del_extra_01" in r["delivery_ids"] for r in data["routes"]
    )
    assert data["decision_explanation"] != ""

    # Verify database state was updated
    with Session(engine) as s:
        state_after = get_fleet_state(s)
        assert state_after.metrics["total_violations"] == 0
        assert state_after.metrics["unassigned_deliveries"] == 0


def test_2_clean_initial_optimization():
    """Initial optimization on clean scenario produces 0 violations."""
    resp = client.post("/api/optimize")
    assert resp.status_code == 200
    data = resp.json()
    assert data["after_metrics"]["total_violations"] == 0
    assert data["number_of_unassigned_deliveries"] == 0
    assert data["number_of_capacity_violations"] == 0
    assert data["number_of_late_deliveries"] == 0


def test_3_before_and_after_metrics_structure():
    """Verify before_metrics and after_metrics contain all required KPI fields."""
    resp = client.post("/api/optimize")
    assert resp.status_code == 200
    data = resp.json()

    for key in ["before_metrics", "after_metrics"]:
        m = data[key]
        assert "total_distance" in m
        assert "total_travel_time" in m
        assert "total_violations" in m
        assert "capacity_violations" in m
        assert "time_window_violations" in m
        assert "driver_hour_violations" in m
        assert "unassigned_deliveries" in m


def test_4_optimize_tracks_changed_routes_and_explanation():
    """Verify optimization outputs explainability and scope details."""
    with Session(engine) as s:
        d = Delivery(
            id="del_reopt_99",
            location="n05",
            demand=10.0,
            priority=1,
            time_window_start=0.0,
            time_window_end=300.0,
            status=DeliveryStatus.PENDING,
            assigned_vehicle=None,
        )
        s.add(d)
        s.commit()

    resp = client.post("/api/optimize")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["routes_changed"]) >= 1
    assert "Global fleet optimization" in data["decision_explanation"]
    assert data["full_state"] is not None


def test_5_revalidation_all_active_routes_feasible():
    """Revalidate that every active route in the resulting plan is strictly feasible."""
    resp = client.post("/api/optimize")
    assert resp.status_code == 200
    data = resp.json()

    with Session(engine) as s:
        vehicles = {v.id: v for v in get_vehicles(s)}
        deliveries = {d.id: d for d in get_deliveries(s)}
        nodes = get_nodes(s)
        roads = get_roads(s)
        graph = build_graph(nodes, roads)

        for r in data["routes"]:
            v = vehicles[r["vehicle_id"]]
            if v.status == VehicleStatus.ACTIVE:
                sim = simulate_route_timeline(r["delivery_ids"], v, deliveries, graph)
                assert sim["is_feasible"] is True
                assert sim["capacity_violation"] == 0.0
                assert sim["driver_hours_violation"] == 0.0
                assert sim["total_lateness"] == 0.0


def test_6_broken_vehicle_empty_route_vs_assigned_route_feasibility():
    """
    Verify:
      - Broken vehicle with empty route (parked) is feasible (no constraint violations).
      - Broken vehicle with deliveries assigned is infeasible and counts as a violation.
    """
    with Session(engine) as s:
        v = s.get(Vehicle, "v01")
        v.status = VehicleStatus.BREAKDOWN
        s.add(v)

        deliveries = {d.id: d for d in get_deliveries(s)}
        nodes = get_nodes(s)
        roads = get_roads(s)
        graph = build_graph(nodes, roads)

        # Empty route for broken vehicle -> Feasible (parked/no violations)
        sim_empty = simulate_route_timeline([], v, deliveries, graph)
        assert sim_empty["is_feasible"] is True

        # Non-empty route for broken vehicle -> Infeasible (active violation)
        sim_loaded = simulate_route_timeline(["del_01"], v, deliveries, graph)
        assert sim_loaded["is_feasible"] is False


def test_7_impossible_delivery_remains_unassigned():
    """An impossible delivery (demand 5000kg > max capacity 400kg) must remain unassigned and flagged as violation."""
    with Session(engine) as s:
        d_impossible = Delivery(
            id="del_impossible_999",
            location="n03",
            demand=5000.0,
            priority=1,
            time_window_start=0.0,
            time_window_end=120.0,
            status=DeliveryStatus.PENDING,
            assigned_vehicle=None,
        )
        s.add(d_impossible)
        s.commit()

    resp = client.post("/api/optimize")
    assert resp.status_code == 200
    data = resp.json()

    assert "del_impossible_999" in data["unassigned_deliveries"]
    assert data["after_metrics"]["unassigned_deliveries"] >= 1
    assert data["after_metrics"]["total_violations"] >= 1


def test_8_optimization_idempotence():
    """Repeated /optimize calls keep the persisted schedule stable."""
    resp1 = client.post("/api/optimize")
    assert resp1.status_code == 200
    data1 = resp1.json()
    routes1 = {
        route["vehicle_id"]: route["delivery_ids"]
        for route in data1["full_state"]["routes"]
    }

    resp2 = client.post("/api/optimize")
    assert resp2.status_code == 200
    data2 = resp2.json()
    routes2 = {
        route["vehicle_id"]: route["delivery_ids"]
        for route in data2["full_state"]["routes"]
    }

    resp3 = client.post("/api/optimize")
    assert resp3.status_code == 200
    data3 = resp3.json()
    routes3 = {
        route["vehicle_id"]: route["delivery_ids"]
        for route in data3["full_state"]["routes"]
    }

    assert data1["after_metrics"]["total_violations"] == data2["after_metrics"]["total_violations"]
    assert data2["after_metrics"]["total_violations"] == data3["after_metrics"]["total_violations"]
    assert routes1 == routes2 == routes3
    assert data1["total_distance"] == data2["total_distance"] == data3["total_distance"]
    assert data2["routes_changed"] == []
    assert data3["routes_changed"] == []


def test_initial_plan_is_independent_of_database_row_order():
    """Equal priority/window records must not reshuffle routes across DB row orders."""
    vehicles = get_vehicles()
    deliveries = get_deliveries()
    nodes = get_nodes()
    roads = get_roads()

    def plan(vehicle_rows, delivery_rows):
        # Rebuild plain model instances because the planner updates assigned_vehicle.
        copied_vehicles = [Vehicle(**vehicle.model_dump()) for vehicle in vehicle_rows]
        copied_deliveries = [Delivery(**delivery.model_dump()) for delivery in delivery_rows]
        return generate_initial_plan(copied_vehicles, copied_deliveries, nodes, roads)

    plan_in_db_order = plan(vehicles, deliveries)
    plan_in_reverse_db_order = plan(list(reversed(vehicles)), list(reversed(deliveries)))

    routes_a = {route.vehicle_id: route.delivery_ids for route in plan_in_db_order.routes}
    routes_b = {route.vehicle_id: route.delivery_ids for route in plan_in_reverse_db_order.routes}
    assert routes_a == routes_b
    assert plan_in_db_order.total_distance == plan_in_reverse_db_order.total_distance
    assert plan_in_db_order.total_travel_time == plan_in_reverse_db_order.total_travel_time


def test_9_full_state_consistency():
    """Verify that full_state in response matches GET /api/state."""
    resp = client.post("/api/optimize")
    assert resp.status_code == 200
    full_state_from_opt = resp.json()["full_state"]

    resp_state = client.get("/api/state")
    assert resp_state.status_code == 200
    state_from_api = resp_state.json()

    assert full_state_from_opt["metrics"]["total_violations"] == state_from_api["metrics"]["total_violations"]
    assert len(full_state_from_opt["routes"]) == len(state_from_api["routes"])


def test_10_authoritative_metrics_consistency():
    """Verify compute_fleet_metrics and get_fleet_state metrics stay synchronized."""
    with Session(engine) as s:
        state = get_fleet_state(s)
        vehicles = get_vehicles(s)
        deliveries = get_deliveries(s)
        nodes = get_nodes(s)
        roads = get_roads(s)
        routes = get_routes(s)

        metrics = compute_fleet_metrics(routes, vehicles, deliveries, nodes, roads)
        assert state.metrics["total_violations"] == metrics["total_violations"]
        assert state.metrics["capacity_violations"] == metrics["capacity_violations"]
        assert state.metrics["time_window_violations"] == metrics["time_window_violations"]
        assert state.metrics["unassigned_deliveries"] == metrics["unassigned_deliveries"]


@pytest.mark.parametrize("violation_count", [0, 1, 2, 4])
def test_status_aware_before_after_metrics_match_fresh_validation(violation_count):
    """Canceled deliveries are terminal; feasible pending orphans are repaired."""
    with Session(engine) as s:
        # This formerly added one phantom violation because the fleet metric
        # counted every status except DELIVERED as an unassigned order.
        s.add(Delivery(
            id="workflow_cancelled_metric_check",
            location="n01",
            demand=1.0,
            priority=3,
            time_window_start=0.0,
            time_window_end=1000.0,
            status=DeliveryStatus.CANCELLED,
            assigned_vehicle=None,
        ))
        for index in range(violation_count):
            s.add(Delivery(
                id=f"workflow_orphan_{index}",
                location=f"n{index + 1:02d}",
                demand=1.0,
                priority=3,
                time_window_start=0.0,
                time_window_end=1000.0,
                status=DeliveryStatus.PENDING,
                assigned_vehicle=None,
            ))
        s.commit()

        before_state = get_fleet_state(s)
        before_fresh = fresh_violation_count(
            get_routes(s), get_vehicles(s), get_deliveries(s), get_nodes(s), get_roads(s)
        )
        assert before_fresh == violation_count
        assert before_state.metrics["total_violations"] == before_fresh
        assert before_state.metrics["unassigned_deliveries"] == violation_count

    response = client.post("/api/optimize")
    assert response.status_code == 200
    data = response.json()
    with Session(engine) as s:
        final_state = get_fleet_state(s)
        after_fresh = fresh_violation_count(
            get_routes(s), get_vehicles(s), get_deliveries(s), get_nodes(s), get_roads(s)
        )

    assert data["before_metrics"]["total_violations"] == before_fresh
    assert data["after_metrics"]["total_violations"] == after_fresh
    assert final_state.metrics["total_violations"] == after_fresh
    assert data["full_state"]["metrics"]["total_violations"] == after_fresh
    assert after_fresh == 0
    assert data["after_metrics"]["unassigned_deliveries"] == 0
    assert len(data["deliveries_reassigned"]) == violation_count
    assert_persisted_route_values_are_fresh(final_state)

    second_response = client.post("/api/optimize")
    assert second_response.status_code == 200
    second_data = second_response.json()
    second_state = client.get("/api/state").json()
    all_route_deliveries = [
        delivery_id for route in second_state["routes"] for delivery_id in route["delivery_ids"]
    ]
    active_delivery_ids = {
        delivery["id"] for delivery in second_state["deliveries"]
        if delivery["status"] in ("PENDING", "IN_PROGRESS")
    }
    assert len(all_route_deliveries) == len(set(all_route_deliveries))
    assert set(all_route_deliveries) == active_delivery_ids
    assert second_data["routes_changed"] == []
    assert second_data["after_metrics"]["total_violations"] == 0


@pytest.mark.parametrize("event_path,event_payload", [
    ("/api/events/traffic", {"road_id": "road_000", "traffic_multiplier": 3.5}),
    ("/api/events/breakdown", {"vehicle_id": "v03"}),
    ("/api/events/new-delivery", {
        "delivery_id": "workflow_event_new", "location": "n05", "demand": 2.0,
        "priority": 1, "time_window_start": 0.0, "time_window_end": 1000.0,
    }),
    ("/api/events/cancel", {"delivery_id": "d12"}),
    ("/api/events/road-blocked", {"road_id": "road_000", "blocked": True}),
    ("/api/events/time-window", {
        "delivery_id": "d12", "new_window_start": 0.0, "new_window_end": 1000.0,
    }),
])
def test_each_event_then_optimize_reports_final_persisted_validation(event_path, event_payload):
    event_response = client.post(event_path, json=event_payload)
    assert event_response.status_code == 200
    event_data = event_response.json()
    state_after_event = client.get("/api/state").json()
    assert event_data["after_metrics"]["total_violations"] == state_after_event["metrics"]["total_violations"]
    routes_after_event = {
        route["vehicle_id"]: route["delivery_ids"]
        for route in state_after_event["routes"]
    }

    violations_before_optimize = state_after_event["metrics"]["total_violations"]
    optimize_response = client.post("/api/optimize")
    assert optimize_response.status_code == 200
    optimize_data = optimize_response.json()
    state_after_optimize = client.get("/api/state").json()
    independent_after = fresh_violation_count(
        [Route(**r) for r in state_after_optimize["routes"]],
        [Vehicle(**v) for v in state_after_optimize["vehicles"]],
        [Delivery(**d) for d in state_after_optimize["deliveries"]],
        [Node(**n) for n in state_after_optimize["nodes"]],
        [Road(**r) for r in state_after_optimize["roads"]],
    )

    assert optimize_data["before_metrics"]["total_violations"] == violations_before_optimize
    assert optimize_data["after_metrics"]["total_violations"] == independent_after
    assert state_after_optimize["metrics"]["total_violations"] == independent_after
    assert optimize_data["full_state"]["metrics"]["total_violations"] == independent_after
    if violations_before_optimize == 0:
        assert optimize_data["routes_changed"] == []
        assert {
            route["vehicle_id"]: route["delivery_ids"]
            for route in state_after_optimize["routes"]
        } == routes_after_event
