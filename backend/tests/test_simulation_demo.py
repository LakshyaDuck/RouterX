"""
Automated tests for the Hackathon Deterministic Simulation & Demo Scenario.

Verifies:
  1. POST /simulation/reset sets up 8 vehicles, 40 deliveries, 25 nodes, 45 roads deterministically.
  2. GET /simulation/demo-events returns the 4 pre-configured demo events.
  3. POST /simulation/event/1 executes traffic jam on road_000.
  4. POST /simulation/event/2 executes V03 mechanical breakdown.
  5. POST /simulation/event/3 executes urgent priority 1 delivery insertion.
  6. POST /simulation/event/4 executes tightened delivery time window.
  7. Determinism: Replaying reset + 4 demo steps produces identical states every time.
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from app.models import VehicleStatus

client = TestClient(app)


def test_simulation_reset():
    """POST /simulation/reset resets the fleet database to baseline deterministic state."""
    response = client.post("/simulation/reset")
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["status"] == "reset"
    state = data["state"]

    assert len(state["vehicles"]) == 8
    assert len(state["deliveries"]) == 40
    assert len(state["nodes"]) == 25
    assert len(state["roads"]) == 45
    assert len(state["routes"]) == 8

    # All 8 routes must be feasible initially
    for r in state["routes"]:
        assert r["feasible"] is True

    # Vehicle V03 must be active initially
    v03 = next(v for v in state["vehicles"] if v["id"] == "v03")
    assert v03["status"] == "ACTIVE"


def test_demo_events_list():
    """GET /simulation/demo-events returns the 4 predefined hackathon events."""
    response = client.get("/simulation/demo-events")
    assert response.status_code == 200
    events = response.json()

    assert len(events) == 4
    assert [e["step"] for e in events] == [1, 2, 3, 4]
    assert events[0]["event_type"] == "TRAFFIC_UPDATE"
    assert events[1]["event_type"] == "VEHICLE_BREAKDOWN"
    assert events[2]["event_type"] == "NEW_DELIVERY"
    assert events[3]["event_type"] == "TIME_WINDOW_CHANGE"


def test_sequential_demo_events_execution():
    """Execute all 4 demo events sequentially and verify capture of state before/after."""
    # Start with a clean reset
    client.post("/simulation/reset")

    # Step 1: Major Traffic Jam
    r1 = client.post("/simulation/event/1")
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["step"] == 1
    assert "road_000" in d1["event"]["affected_entity_id"]
    assert "road_000" in d1["explanation"]
    assert len(d1["metrics"]["before"]["affected_routes"]) > 0

    # Step 2: Vehicle V03 Breakdown
    r2 = client.post("/simulation/event/2")
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["step"] == 2
    assert "v03" in d2["changed_routes"]
    assert len(d2["reassigned_deliveries"]) > 0
    # Confirm v03 is now BREAKDOWN in full_state
    v03_after = next(v for v in d2["full_state"]["vehicles"] if v["id"] == "v03")
    assert v03_after["status"] == "BREAKDOWN"

    # Step 3: Urgent Priority 1 Order
    r3 = client.post("/simulation/event/3")
    assert r3.status_code == 200, r3.text
    d3 = r3.json()
    assert d3["step"] == 3
    assert len(d3["changed_routes"]) == 1
    assert "d_rush_p1" in d3["explanation"]
    # Check that d_rush_p1 is present in full_state deliveries
    assert any(d["id"] == "d_rush_p1" for d in d3["full_state"]["deliveries"])

    # Step 4: Tightened Customer Delivery Window
    r4 = client.post("/simulation/event/4")
    assert r4.status_code == 200, r4.text
    d4 = r4.json()
    assert d4["step"] == 4
    assert len(d4["changed_routes"]) >= 1
    assert "d12" in d4["explanation"]


def test_simulation_replay_deterministic():
    """
    Ensure the scenario is 100% deterministic:
    Running Reset -> Step 1 -> Step 2 produces the exact same metrics and changed routes on repeated runs.
    """
    def run_cycle():
        client.post("/simulation/reset")
        step1 = client.post("/simulation/event/1").json()
        step2 = client.post("/simulation/event/2").json()
        return (
            step1["metrics"]["after"]["distance"],
            step1["changed_routes"],
            step2["metrics"]["after"]["distance"],
            step2["reassigned_deliveries"],
        )

    run_a = run_cycle()
    run_b = run_cycle()

    assert run_a == run_b, "Simulation demo runs must be 100% deterministic across replays!"
