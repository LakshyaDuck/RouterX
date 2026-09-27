"""
Test Fresh Scenario endpoint and edge cases.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import get_session, get_fleet_state, Node, Vehicle, Delivery, Route
from main import app

client = TestClient(app)


def test_fresh_scenario_and_custom_build_workflow():
    # 1. Reset to baseline first
    res = client.post("/api/simulation/reset")
    assert res.status_code == 200

    # 2. Trigger Fresh Scenario
    res_fresh = client.post("/api/simulation/fresh")
    assert res_fresh.status_code == 200
    data = res_fresh.json()
    assert data["status"] == "fresh"

    state = data["state"]
    assert len(state["vehicles"]) == 0
    assert len(state["deliveries"]) == 0
    assert len(state["routes"]) == 0
    assert len(state["events"]) == 0
    assert len(state["nodes"]) >= 25  # Core network intact
    assert len(state["roads"]) >= 45  # Core roads intact

    # 3. Optimize on empty scenario should not crash
    res_opt_empty = client.post("/api/optimize")
    assert res_opt_empty.status_code == 200
    plan_empty = res_opt_empty.json()
    assert len(plan_empty["routes"]) == 0
    assert plan_empty["number_of_unassigned_deliveries"] == 0

    # 4. Add 1 vehicle
    res_v = client.post("/api/vehicles", json={
        "name": "Custom Explorer Van",
        "capacity": 120.0,
        "driver_hours_remaining": 8.0,
        "current_location": "depot",
    })
    assert res_v.status_code == 200
    assert len(res_v.json()["vehicles"]) == 1
    vid = res_v.json()["vehicles"][0]["id"]

    # 5. Add 1 delivery
    res_d = client.post("/api/deliveries", json={
        "location": "n01",
        "demand": 25.0,
        "priority": 1,
        "time_window_start": 0.0,
        "time_window_end": 180.0,
        "auto_assign": False,
    })
    assert res_d.status_code == 200
    assert len(res_d.json()["deliveries"]) == 1
    did = res_d.json()["deliveries"][0]["id"]

    # 6. Optimize scenario: vehicle should be assigned to delivery
    res_opt = client.post("/api/optimize")
    assert res_opt.status_code == 200
    plan = res_opt.json()
    assert len(plan["routes"]) == 1
    assert did in plan["routes"][0]["delivery_ids"]
    assert plan["number_of_unassigned_deliveries"] == 0

    # 7. Reset back to demo baseline
    res_reset = client.post("/api/simulation/reset")
    assert res_reset.status_code == 200
    assert len(res_reset.json()["state"]["vehicles"]) == 8
    assert len(res_reset.json()["state"]["deliveries"]) == 40
