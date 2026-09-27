import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from main import app
from app.database import engine, get_fleet_state, reset_fleet_database
from app.models import VehicleStatus, DeliveryStatus

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_db():
    reset_fleet_database()
    yield

def test_scenario_builder_add_vehicle():
    """Verify adding a vehicle dynamically via Scenario Builder."""
    resp = client.post("/api/vehicles", json={
        "name": "Heavy Hauler 9",
        "capacity": 300.0,
        "driver_hours_remaining": 9.0,
        "current_location": "depot",
    })
    assert resp.status_code == 200
    state = resp.json()
    new_v = next((v for v in state["vehicles"] if v["name"] == "Heavy Hauler 9"), None)
    assert new_v is not None
    assert new_v["capacity"] == 300.0
    assert any(r["vehicle_id"] == new_v["id"] for r in state["routes"])

def test_scenario_builder_add_multiple_vehicles():
    """Verify adding multiple vehicles sequentially."""
    resp1 = client.post("/api/vehicles", json={"name": "Van Alpha", "capacity": 150.0})
    assert resp1.status_code == 200
    resp2 = client.post("/api/vehicles", json={"name": "Van Beta", "capacity": 180.0})
    assert resp2.status_code == 200
    resp3 = client.post("/api/vehicles", json={"name": "Van Gamma", "capacity": 220.0})
    assert resp3.status_code == 200

    state = client.get("/api/state").json()
    assert len(state["vehicles"]) == 11  # 8 initial + 3 new
    assert any(v["name"] == "Van Alpha" for v in state["vehicles"])
    assert any(v["name"] == "Van Beta" for v in state["vehicles"])
    assert any(v["name"] == "Van Gamma" for v in state["vehicles"])

def test_scenario_builder_duplicate_vehicle_id_rejected():
    """Verify explicit duplicate vehicle ID is rejected with 409 Conflict."""
    resp = client.post("/api/vehicles", json={
        "id": "v01",
        "name": "Conflict Van",
        "capacity": 150.0,
    })
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]

def test_scenario_builder_invalid_vehicle_rejected():
    """Verify invalid vehicle parameters (empty name, negative capacity) are rejected gracefully with 400."""
    # Blank name
    resp1 = client.post("/api/vehicles", json={"name": "   ", "capacity": 100.0})
    assert resp1.status_code == 400

    # Non-positive capacity
    resp2 = client.post("/api/vehicles", json={"name": "Bad Capacity Van", "capacity": -10.0})
    assert resp2.status_code == 400

    # Negative driver hours
    resp3 = client.post("/api/vehicles", json={"name": "Overworked Van", "capacity": 100.0, "driver_hours_remaining": -2.0})
    assert resp3.status_code == 400

def test_scenario_builder_add_unassigned_delivery():
    """Verify adding an unassigned delivery dynamically via Scenario Builder."""
    resp = client.post("/api/deliveries", json={
        "location": "n04",
        "demand": 25.0,
        "priority": 1,
        "time_window_start": 30.0,
        "time_window_end": 180.0,
        "auto_assign": False,
    })
    assert resp.status_code == 200
    state = resp.json()
    new_d = next((d for d in state["deliveries"] if d["location"] == "n04" and d["demand"] == 25.0), None)
    assert new_d is not None
    assert new_d["assigned_vehicle"] is None
    assert state["metrics"]["unassigned_deliveries"] >= 1
    assert state["metrics"]["total_violations"] >= 1

    # Optimize scenario should assign it and clear violations
    opt_resp = client.post("/api/optimize")
    assert opt_resp.status_code == 200
    opt_data = opt_resp.json()
    assert opt_data["after_metrics"]["total_violations"] == 0

def test_scenario_builder_add_node_reachability():
    """Verify adding a routable node/stop dynamically and that Dijkstra routing can reach it."""
    resp = client.post("/api/nodes", json={
        "label": "Westside Hub",
        "lat": 37.77,
        "lon": -122.43,
        "connect_to_node": "n01",
    })
    assert resp.status_code == 200
    state = resp.json()
    new_n = next((n for n in state["nodes"] if n["label"] == "Westside Hub"), None)
    assert new_n is not None

    # Verify road exists connecting it
    assert any(
        (r["from_node"] == new_n["id"] and r["to_node"] == "n01") or
        (r["to_node"] == new_n["id"] and r["from_node"] == "n01")
        for r in state["roads"]
    )

    # Query routing API: verify shortest path between depot and new stop is reachable
    route_resp = client.post("/api/routing/path", json={
        "start": "depot",
        "end": new_n["id"],
    })
    assert route_resp.status_code == 200
    route_data = route_resp.json()
    assert route_data["reachable"] is True
    assert route_data["path"][-1] == new_n["id"]
    assert route_data["travel_time_minutes"] > 0

def test_scenario_builder_traffic_update():
    """Verify traffic multiplier update on road."""
    resp = client.post("/api/events/traffic", json={
        "road_id": "road_001",
        "traffic_multiplier": 3.5,
    })
    assert resp.status_code == 200
    state = client.get("/api/state").json()
    r1 = next(r for r in state["roads"] if r["id"] == "road_001")
    assert r1["traffic_multiplier"] == 3.5

def test_scenario_builder_road_block_and_reopen():
    """Verify blocking and reopening roads through the scenario interface."""
    # Block
    resp1 = client.post("/api/events/road-block", json={
        "road_id": "road_000",
        "blocked": True,
    })
    assert resp1.status_code == 200
    state1 = client.get("/api/state").json()
    r0 = next(r for r in state1["roads"] if r["id"] == "road_000")
    assert r0["blocked"] is True

    # Reopen
    resp2 = client.post("/api/events/road-block", json={
        "road_id": "road_000",
        "blocked": False,
    })
    assert resp2.status_code == 200
    state2 = client.get("/api/state").json()
    r0_reopened = next(r for r in state2["roads"] if r["id"] == "road_000")
    assert r0_reopened["blocked"] is False

def test_scenario_builder_cancel_and_optimize():
    """Verify cancelling an order and optimizing."""
    resp = client.post("/api/events/cancel-delivery", json={
        "delivery_id": "d01",
        "reason": "Customer cancellation",
    })
    assert resp.status_code == 200
    state = client.get("/api/state").json()
    d1 = next(d for d in state["deliveries"] if d["id"] == "d01")
    assert d1["status"] == "CANCELLED"
    assert d1["assigned_vehicle"] is None

    # Optimize scenario
    opt_resp = client.post("/api/optimize")
    assert opt_resp.status_code == 200
    assert opt_resp.json()["after_metrics"]["total_violations"] == 0

def test_scenario_builder_complete_workflow():
    """
    End-to-End test of the Scenario Builder workflow:
    1. Add a vehicle
    2. Add 2 unassigned deliveries
    3. Induce a traffic jam
    4. Optimize scenario
    5. Verify 0 violations and feasible routes
    6. Reset scenario
    """
    # 1. Add vehicle
    client.post("/api/vehicles", json={"name": "Rescue Van", "capacity": 200.0})

    # 2. Add 2 unassigned orders
    client.post("/api/deliveries", json={"location": "n02", "demand": 12.0, "priority": 1, "auto_assign": False})
    client.post("/api/deliveries", json={"location": "n03", "demand": 14.0, "priority": 2, "auto_assign": False})

    # 3. Traffic jam
    client.post("/api/events/traffic", json={"road_id": "road_000", "traffic_multiplier": 4.0})

    state_before = client.get("/api/state").json()
    assert state_before["metrics"]["total_violations"] >= 2

    # 4. Optimize Scenario
    opt_resp = client.post("/api/optimize")
    assert opt_resp.status_code == 200
    opt_data = opt_resp.json()

    # 5. Verify resolution
    assert opt_data["after_metrics"]["total_violations"] == 0
    assert opt_data["after_metrics"]["unassigned_deliveries"] == 0

    # 6. Reset
    reset_resp = client.post("/api/simulation/reset")
    assert reset_resp.status_code == 200
    state_after_reset = client.get("/api/state").json()
    assert len(state_after_reset["vehicles"]) == 8
    assert len(state_after_reset["deliveries"]) == 40
    assert state_after_reset["metrics"]["total_violations"] == 0
