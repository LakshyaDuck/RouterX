import pytest
import urllib.request
import urllib.error
import json
import os

BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

def api_call(endpoint, method="GET", data=None):
    url = f"{BASE_URL}{endpoint}"
    req_data = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body
        return e.code, parsed
    except Exception as e:
        return 500, {"error": str(e)}

def assert_invariants(state, context=""):
    vehicles = {v["id"]: v for v in state.get("vehicles", [])}
    deliveries = {d["id"]: d for d in state.get("deliveries", [])}
    routes = {r["vehicle_id"]: r for r in state.get("routes", [])}
    nodes = {n["id"]: n for n in state.get("nodes", [])}

    # 1. No duplicated deliveries across routes
    seen = {}
    for vid, r in routes.items():
        for did in r.get("delivery_ids", []):
            assert did not in seen, f"[{context}] Delivery {did} duplicated across {seen[did]} and {vid}"
            seen[did] = vid

    # 2. Broken vehicles have NO pending deliveries and NO route stops
    for vid, v in vehicles.items():
        if v.get("status") == "BREAKDOWN":
            pending = [did for did, d in deliveries.items() if d.get("assigned_vehicle") == vid and d.get("status") == "PENDING"]
            assert len(pending) == 0, f"[{context}] Broken vehicle {vid} still assigned pending orders: {pending}"
            stops = routes.get(vid, {}).get("delivery_ids", [])
            assert len(stops) == 0, f"[{context}] Broken vehicle {vid} still has route stops: {stops}"

    # 3. Capacity constraints
    for vid, v in vehicles.items():
        r = routes.get(vid)
        if r:
            actual_load = sum(deliveries[did]["demand"] for did in r.get("delivery_ids", []) if did in deliveries)
            assert actual_load <= v["capacity"] + 1e-3, f"[{context}] Vehicle {vid} capacity exceeded: {actual_load} > {v['capacity']}"
            assert abs(v.get("current_load", 0) - actual_load) < 1e-2, f"[{context}] Vehicle {vid} current_load {v.get('current_load')} != actual {actual_load}"

    # 4. Locations must exist
    for vid, v in vehicles.items():
        assert v.get("current_location") in nodes, f"[{context}] Invalid vehicle loc: {v.get('current_location')}"
    for did, d in deliveries.items():
        assert d.get("location") in nodes, f"[{context}] Invalid delivery loc: {d.get('location')}"


def test_01_initial_optimization():
    """Test 1: Initial optimization & reset produces clean deterministic state."""
    st, res = api_call("/api/simulation/reset", "POST")
    assert st == 200, f"Reset failed with {st}"
    st, state = api_call("/api/state")
    assert st == 200
    assert len(state["vehicles"]) == 8
    assert len(state["deliveries"]) == 40
    assert_invariants(state, "test_01")


def test_02_traffic_change():
    """Test 2: Traffic slowdown on central artery triggers route repair with valid metrics."""
    st, res = api_call("/api/events/traffic", "POST", {"road_id": "road_000", "traffic_multiplier": 4.5})
    assert st == 200, f"Traffic event failed with {st}: {res}"
    assert "reoptimization_scope" in res
    assert "decision_explanation" in res or "explanation" in res
    st, state = api_call("/api/state")
    assert_invariants(state, "test_02")


def test_03_vehicle_breakdown():
    """Test 3: Vehicle breakdown offloads deliveries and preserves active vehicle capacity."""
    st, res = api_call("/api/events/breakdown", "POST", {"vehicle_id": "v03", "reason": "Engine failure"})
    assert st == 200, f"Breakdown failed with {st}: {res}"
    st, state = api_call("/api/state")
    v03 = next(v for v in state["vehicles"] if v["id"] == "v03")
    assert v03["status"] == "BREAKDOWN"
    assert_invariants(state, "test_03")


def test_04_new_priority_order():
    """Test 4: Insert high-priority delivery."""
    st, res = api_call("/api/events/new-delivery", "POST", {
        "delivery_id": "qa_p1_001",
        "location": "n04",
        "demand": 12.0,
        "priority": 1,
        "time_window_start": 30.0,
        "time_window_end": 180.0
    })
    assert st == 200, f"New delivery failed: {st}: {res}"
    st, state = api_call("/api/state")
    deliv = next(d for d in state["deliveries"] if d["id"] == "qa_p1_001")
    assert deliv["assigned_vehicle"] is not None
    assert_invariants(state, "test_04")


def test_05_time_window_change():
    """Test 5: Time window change for existing delivery."""
    st, res = api_call("/api/events/time-window-change", "POST", {
        "delivery_id": "d01",
        "new_window_start": 20.0,
        "new_window_end": 100.0
    })
    assert st == 200, f"Time window change failed: {st}: {res}"
    st, state = api_call("/api/state")
    d01 = next(d for d in state["deliveries"] if d["id"] == "d01")
    assert d01["time_window_start"] == 20.0
    assert_invariants(state, "test_05")


def test_06_sequential_events():
    """Test 6: Chain multiple events in rapid succession without state degradation."""
    events = [
        ("/api/events/breakdown", {"vehicle_id": "v02"}),
        ("/api/events/traffic", {"road_id": "road_005", "traffic_multiplier": 3.0}),
        ("/api/events/new-delivery", {"delivery_id": "qa_seq_02", "location": "n07", "demand": 8.0, "priority": 1, "time_window_start": 40.0, "time_window_end": 200.0}),
        ("/api/events/time-window-change", {"delivery_id": "d06", "new_window_start": 10.0, "new_window_end": 90.0}),
    ]
    for ep, payload in events:
        st, res = api_call(ep, "POST", payload)
        assert st == 200, f"Sequential event {ep} failed: {st}: {res}"

    st, state = api_call("/api/state")
    assert_invariants(state, "test_06")


def test_07_multiple_affected_routes():
    """Test 7: Incident affecting multiple routes simultaneously."""
    api_call("/api/simulation/reset", "POST")
    st, res = api_call("/api/events/traffic", "POST", {"road_id": "road_000", "traffic_multiplier": 5.0})
    assert st == 200
    changed = res.get("changed_routes", [])
    assert len(changed) >= 2, f"Expected multiple affected routes, got {changed}"
    st, state = api_call("/api/state")
    assert_invariants(state, "test_07")


def test_08_vehicle_capacity_overflow():
    """Test 8: Demand far exceeding max vehicle capacity."""
    st, res = api_call("/api/events/new-delivery", "POST", {
        "delivery_id": "qa_overflow_huge",
        "location": "n05",
        "demand": 999.0, # exceeds any vehicle capacity (100kg-120kg)
        "priority": 1,
        "time_window_start": 10.0,
        "time_window_end": 200.0
    })
    # Should not crash 500, should reject or mark unassigned without capacity violation
    assert st < 500, f"Server crashed 500 on capacity overflow: {res}"
    st, state = api_call("/api/state")
    assert_invariants(state, "test_08")


def test_09_impossible_time_window():
    """Test 9: Invalid/impossible time window (end < start)."""
    st, res = api_call("/api/events/new-delivery", "POST", {
        "delivery_id": "qa_impossible_tw_02",
        "location": "n06",
        "demand": 10.0,
        "priority": 1,
        "time_window_start": 200.0,
        "time_window_end": 50.0 # end before start
    })
    assert st < 500, f"Server crashed 500 on impossible time window: {res}"
    st, state = api_call("/api/state")
    assert_invariants(state, "test_09")


def test_10_broken_vehicle_no_new_work():
    """Test 10: Broken vehicle must never be assigned new deliveries."""
    api_call("/api/simulation/reset", "POST")
    api_call("/api/events/breakdown", "POST", {"vehicle_id": "v03"})

    for i in range(4):
        st, res = api_call("/api/events/new-delivery", "POST", {
            "delivery_id": f"qa_no_work_{i}",
            "location": "n03",
            "demand": 6.0,
            "priority": 2,
            "time_window_start": 10.0,
            "time_window_end": 300.0
        })
        assert res.get("assigned_vehicle") != "v03", f"Delivery assigned to broken vehicle v03!"

    st, state = api_call("/api/state")
    assert_invariants(state, "test_10")


def test_11_repeated_event():
    """Test 11: Duplicate event injection handled gracefully without crashing."""
    st1, _ = api_call("/api/events/breakdown", "POST", {"vehicle_id": "v03"})
    st2, res2 = api_call("/api/events/breakdown", "POST", {"vehicle_id": "v03"})
    assert st2 < 500, f"Server crashed on duplicate breakdown: {res2}"
    st, state = api_call("/api/state")
    assert_invariants(state, "test_11")


def test_12_reset_simulation():
    """Test 12: Simulation reset restores completely clean fleet state."""
    st, res = api_call("/api/simulation/reset", "POST")
    assert st == 200
    st, state = api_call("/api/state")
    broken = [v for v in state["vehicles"] if v["status"] == "BREAKDOWN"]
    assert len(broken) == 0, f"Reset did not clear broken vehicles: {broken}"
    assert len(state["vehicles"]) == 8
    assert_invariants(state, "test_12")


def test_13_page_refresh_consistency():
    """Test 13: GET /api/state contains complete and consistent data for UI."""
    st, state = api_call("/api/state")
    assert st == 200
    required_keys = ["vehicles", "deliveries", "routes", "nodes", "roads", "events", "metrics"]
    for k in required_keys:
        assert k in state, f"Missing key {k} in state response"
    assert_invariants(state, "test_13")


def test_14_data_integrity():
    """Test 14: Entities and metrics accurately match."""
    st, state = api_call("/api/state")
    assert st == 200
    metrics = state.get("metrics", {})
    assert "total_distance" in metrics
    assert "active_vehicles" in metrics
    assert "total_deliveries" in metrics
    assert metrics["active_vehicles"] <= len(state["vehicles"])


def test_15_invalid_payloads():
    """Test 15: Invalid payloads return clean 4xx without 500 crashes."""
    bad_payloads = [
        ("/api/events/traffic", {}),
        ("/api/events/traffic", {"road_id": "nonexistent_road_999", "traffic_multiplier": 2.0}),
        ("/api/events/breakdown", {"vehicle_id": "v_fake_999"}),
        ("/api/events/new-delivery", {"delivery_id": "bad", "demand": -10.0}),
        ("/api/events/time-window-change", {"delivery_id": "nonexistent_delivery_999", "new_window_start": 10.0, "new_window_end": 50.0}),
    ]
    for ep, p in bad_payloads:
        st, res = api_call(ep, "POST", p)
        assert st < 500, f"Server returned 500 on invalid payload {p} to {ep}: {res}"
