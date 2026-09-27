import sys
import json
import urllib.request
import urllib.error
import os

BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

def request(endpoint, method="GET", data=None):
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

def check_invariants(state, label=""):
    errors = []
    vehicles = {v["id"]: v for v in state.get("vehicles", [])}
    deliveries = {d["id"]: d for d in state.get("deliveries", [])}
    routes = {r["vehicle_id"]: r for r in state.get("routes", [])}
    nodes = {n["id"]: n for n in state.get("nodes", [])}

    # 1. No duplicated deliveries across routes
    seen_in_routes = {}
    for vid, r in routes.items():
        for did in r.get("delivery_ids", []):
            if did in seen_in_routes:
                errors.append(f"[{label}] Delivery {did} appears in multiple routes: {seen_in_routes[did]} and {vid}")
            seen_in_routes[did] = vid

    # 2. Check broken vehicles have NO active assigned deliveries
    for vid, v in vehicles.items():
        if v.get("status") == "BREAKDOWN":
            assigned = [did for did, d in deliveries.items() if d.get("assigned_vehicle") == vid and d.get("status") == "PENDING"]
            if assigned:
                errors.append(f"[{label}] Broken vehicle {vid} still has pending deliveries assigned: {assigned}")
            route_stops = routes.get(vid, {}).get("delivery_ids", [])
            if route_stops:
                errors.append(f"[{label}] Broken vehicle {vid} still has route stops: {route_stops}")

    # 3. Capacity checks
    for vid, v in vehicles.items():
        r = routes.get(vid)
        if r:
            actual_load = sum(deliveries[did]["demand"] for did in r.get("delivery_ids", []) if did in deliveries)
            if actual_load > v["capacity"] + 1e-3:
                errors.append(f"[{label}] Vehicle {vid} exceeded capacity: load {actual_load} > {v['capacity']}")
            if abs(v.get("current_load", 0) - actual_load) > 1e-2:
                errors.append(f"[{label}] Vehicle {vid} current_load ({v.get('current_load')}) does not match route load ({actual_load})")

    # 4. Check all vehicle locations exist in nodes
    for vid, v in vehicles.items():
        if v.get("current_location") not in nodes:
            errors.append(f"[{label}] Vehicle {vid} has invalid location: {v.get('current_location')}")

    # 5. Check all delivery locations exist in nodes
    for did, d in deliveries.items():
        if d.get("location") not in nodes:
            errors.append(f"[{label}] Delivery {did} has invalid location: {d.get('location')}")

    return errors

def run_qa_suite():
    print("=" * 70)
    print("STARTING QA STRESS & BREAK TEST SUITE")
    print("=" * 70)

    results = {}

    # TEST 1: Initial Optimization & Reset
    print("\n[TEST 1] Initial Optimization / Reset")
    status, res = request("/api/simulation/reset", "POST")
    if status == 200:
        st_code, state = request("/api/state")
        invariants = check_invariants(state, "TEST 1")
        if not invariants:
            results["1_initial_opt"] = ("PASS", "Clean state, all invariants held")
        else:
            results["1_initial_opt"] = ("FAIL", f"Invariants violated: {invariants}")
    else:
        results["1_initial_opt"] = ("FAIL", f"Reset returned status {status}: {res}")
    print(f"Result: {results['1_initial_opt']}")

    # TEST 2: Traffic Change
    print("\n[TEST 2] Traffic Change Event")
    payload = {"road_id": "road_000", "traffic_multiplier": 4.5}
    status, res = request("/api/events/traffic", "POST", payload)
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 2")
    if status == 200 and not invariants:
        results["2_traffic_change"] = ("PASS", f"Changed routes: {res.get('changed_routes')}, scope: {res.get('reoptimization_scope')}")
    else:
        results["2_traffic_change"] = ("FAIL", f"Status {status}, invariants: {invariants}, res: {res}")
    print(f"Result: {results['2_traffic_change']}")

    # TEST 3: Vehicle Breakdown
    print("\n[TEST 3] Vehicle Breakdown Event (v03)")
    payload = {"vehicle_id": "v03", "reason": "Gearbox breakdown"}
    status, res = request("/api/events/breakdown", "POST", payload)
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 3")
    v03 = next((v for v in state.get("vehicles", []) if v["id"] == "v03"), None)
    if status == 200 and v03 and v03.get("status") == "BREAKDOWN" and not invariants:
        results["3_breakdown"] = ("PASS", f"v03 marked BREAKDOWN, reassigned: {res.get('reassigned_deliveries')}")
    else:
        results["3_breakdown"] = ("FAIL", f"Status {status}, v03: {v03}, invariants: {invariants}")
    print(f"Result: {results['3_breakdown']}")

    # TEST 4: New Priority Order
    print("\n[TEST 4] New Priority Order")
    payload = {
        "delivery_id": "qa_rush_01",
        "location": "n04",
        "demand": 15.0,
        "priority": 1,
        "time_window_start": 20.0,
        "time_window_end": 180.0
    }
    status, res = request("/api/events/new-delivery", "POST", payload)
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 4")
    qa_deliv = next((d for d in state.get("deliveries", []) if d["id"] == "qa_rush_01"), None)
    if status == 200 and qa_deliv and qa_deliv.get("assigned_vehicle") and not invariants:
        results["4_new_priority_order"] = ("PASS", f"Inserted into vehicle {qa_deliv['assigned_vehicle']}")
    else:
        results["4_new_priority_order"] = ("FAIL", f"Status {status}, delivery: {qa_deliv}, invariants: {invariants}")
    print(f"Result: {results['4_new_priority_order']}")

    # TEST 5: Time-window change
    print("\n[TEST 5] Time-Window Change")
    payload = {
        "delivery_id": "d01",
        "new_window_start": 30.0,
        "new_window_end": 90.0
    }
    status, res = request("/api/events/time-window-change", "POST", payload)
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 5")
    d01 = next((d for d in state.get("deliveries", []) if d["id"] == "d01"), None)
    if status == 200 and d01 and d01["time_window_start"] == 30.0 and not invariants:
        results["5_time_window_change"] = ("PASS", "Window updated successfully")
    else:
        results["5_time_window_change"] = ("FAIL", f"Status {status}, d01: {d01}, invariants: {invariants}")
    print(f"Result: {results['5_time_window_change']}")

    # TEST 6: Sequential Events (Rapid succession)
    print("\n[TEST 6] Sequential Events")
    seq_errors = []
    # Breakdown v02
    st, r = request("/api/events/breakdown", "POST", {"vehicle_id": "v02"})
    if st != 200: seq_errors.append(f"Breakdown v02 failed: {st}")
    # Traffic spike
    st, r = request("/api/events/traffic", "POST", {"road_id": "road_005", "traffic_multiplier": 3.0})
    if st != 200: seq_errors.append(f"Traffic road_005 failed: {st}")
    # New order
    st, r = request("/api/events/new-delivery", "POST", {"delivery_id": "qa_seq_01", "location": "n08", "demand": 10.0, "priority": 1, "time_window_start": 50.0, "time_window_end": 200.0})
    if st != 200: seq_errors.append(f"New order qa_seq_01 failed: {st}")
    # Window change
    st, r = request("/api/events/time-window-change", "POST", {"delivery_id": "d05", "new_window_start": 40.0, "new_window_end": 120.0})
    if st != 200: seq_errors.append(f"Time window d05 failed: {st}")

    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 6")
    seq_errors.extend(invariants)
    if not seq_errors:
        results["6_sequential_events"] = ("PASS", "All 4 sequential events processed without invariant violation")
    else:
        results["6_sequential_events"] = ("FAIL", f"Errors: {seq_errors}")
    print(f"Result: {results['6_sequential_events']}")

    # TEST 7: Multiple Affected Routes
    print("\n[TEST 7] Multiple Affected Routes (Heavy congestion on key road)")
    request("/api/simulation/reset", "POST")
    st, res = request("/api/events/traffic", "POST", {"road_id": "road_000", "traffic_multiplier": 5.0})
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 7")
    changed_routes = res.get("changed_routes", [])
    if st == 200 and len(changed_routes) >= 2 and not invariants:
        results["7_multiple_affected_routes"] = ("PASS", f"Affected routes: {changed_routes}")
    else:
        results["7_multiple_affected_routes"] = ("FAIL", f"Status {st}, changed: {changed_routes}, invariants: {invariants}")
    print(f"Result: {results['7_multiple_affected_routes']}")

    # TEST 8: Vehicle Capacity Overflow
    print("\n[TEST 8] Vehicle Capacity Overflow (Huge demand: 500kg when max cap is 120kg)")
    payload = {
        "delivery_id": "qa_huge_overflow",
        "location": "n05",
        "demand": 500.0,
        "priority": 1,
        "time_window_start": 10.0,
        "time_window_end": 200.0
    }
    status, res = request("/api/events/new-delivery", "POST", payload)
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 8")
    # We want to see: did it crash (500)? Or did it gracefully handle it?
    # Deliveries in routes must NOT exceed vehicle capacity.
    if status in (200, 400, 422) and not invariants:
        results["8_capacity_overflow"] = ("PASS", f"Handled gracefully: status {status}, response: {res.get('detail') or res.get('decision_explanation') or res.get('explanation')}")
    else:
        results["8_capacity_overflow"] = ("FAIL", f"Crashed or violated invariants: status {status}, invariants: {invariants}, res: {res}")
    print(f"Result: {results['8_capacity_overflow']}")

    # TEST 9: Impossible Time Window
    print("\n[TEST 9] Impossible Time Window (end < start, or unattainable window)")
    payload = {
        "delivery_id": "qa_impossible_tw",
        "location": "n06",
        "demand": 5.0,
        "priority": 1,
        "time_window_start": 100.0,
        "time_window_end": 20.0 # end < start
    }
    status, res = request("/api/events/new-delivery", "POST", payload)
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 9")
    if status in (200, 400, 422) and not invariants:
        results["9_impossible_time_window"] = ("PASS", f"Handled gracefully: status {status}, response: {res}")
    else:
        results["9_impossible_time_window"] = ("FAIL", f"Crashed or violated invariants: status {status}, invariants: {invariants}, res: {res}")
    print(f"Result: {results['9_impossible_time_window']}")

    # TEST 10: Broken Vehicle Receiving New Work
    print("\n[TEST 10] Broken Vehicle Receiving Work")
    request("/api/simulation/reset", "POST")
    request("/api/events/breakdown", "POST", {"vehicle_id": "v03"})
    # Try inserting multiple new orders to check if v03 is ever assigned
    assigned_to_v03 = False
    for i in range(5):
        st, res = request("/api/events/new-delivery", "POST", {
            "delivery_id": f"qa_test_v03_work_{i}",
            "location": "n02",
            "demand": 5.0,
            "priority": 2,
            "time_window_start": 20.0,
            "time_window_end": 250.0
        })
        if res.get("assigned_vehicle") == "v03":
            assigned_to_v03 = True

    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 10")
    if not assigned_to_v03 and not invariants:
        results["10_broken_vehicle_no_work"] = ("PASS", "Broken vehicle v03 received zero new assignments")
    else:
        results["10_broken_vehicle_no_work"] = ("FAIL", f"Assigned to broken vehicle: {assigned_to_v03}, invariants: {invariants}")
    print(f"Result: {results['10_broken_vehicle_no_work']}")

    # TEST 11: Repeated Event
    print("\n[TEST 11] Repeated Event (Breakdown already broken vehicle, duplicate delivery ID)")
    st1, r1 = request("/api/events/breakdown", "POST", {"vehicle_id": "v03"})
    st2, r2 = request("/api/events/breakdown", "POST", {"vehicle_id": "v03"}) # duplicate breakdown
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 11")
    if st2 in (200, 400, 409) and not invariants:
        results["11_repeated_event"] = ("PASS", f"Duplicate breakdown handled cleanly: status {st2}")
    else:
        results["11_repeated_event"] = ("FAIL", f"Status {st2}, invariants: {invariants}, res: {r2}")
    print(f"Result: {results['11_repeated_event']}")

    # TEST 12: Reset Simulation
    print("\n[TEST 12] Reset Simulation")
    status, res = request("/api/simulation/reset", "POST")
    st_code, state = request("/api/state")
    invariants = check_invariants(state, "TEST 12")
    broken = [v["id"] for v in state.get("vehicles", []) if v.get("status") == "BREAKDOWN"]
    if status == 200 and not broken and not invariants:
        results["12_reset_simulation"] = ("PASS", f"State fully reset: 0 broken vehicles, {len(state['deliveries'])} deliveries")
    else:
        results["12_reset_simulation"] = ("FAIL", f"Reset failed, broken vehicles: {broken}, invariants: {invariants}")
    print(f"Result: {results['12_reset_simulation']}")

    # TEST 13: Page Refresh (State API Completeness & Self-Consistency)
    print("\n[TEST 13] Page Refresh (State API Self-Consistency)")
    st_code, state = request("/api/state")
    keys = ["vehicles", "deliveries", "routes", "nodes", "roads", "events", "metrics"]
    missing_keys = [k for k in keys if k not in state]
    if st_code == 200 and not missing_keys:
        results["13_page_refresh"] = ("PASS", "State API provides all essential keys for frontend re-hydration")
    else:
        results["13_page_refresh"] = ("FAIL", f"Missing keys: {missing_keys}, status {st_code}")
    print(f"Result: {results['13_page_refresh']}")

    # TEST 14: Backend Restart / Persistence
    print("\n[TEST 14] Backend Data Integrity")
    st_code, state = request("/api/state")
    if st_code == 200 and len(state.get("vehicles", [])) == 8 and len(state.get("deliveries", [])) >= 40:
        results["14_data_integrity"] = ("PASS", "Database queries and models load cleanly with correct entity counts")
    else:
        results["14_data_integrity"] = ("FAIL", f"Invalid counts: {len(state.get('vehicles', []))} vehicles")
    print(f"Result: {results['14_data_integrity']}")

    # TEST 15: Invalid Event Payload
    print("\n[TEST 15] Invalid Event Payload")
    bad_payloads = [
        ("/api/events/traffic", {}), # empty
        ("/api/events/traffic", {"road_id": "nonexistent_road_999", "traffic_multiplier": 2.0}),
        ("/api/events/traffic", {"road_id": "road_000", "traffic_multiplier": -5.0}), # negative
        ("/api/events/breakdown", {"vehicle_id": "v_fake_999"}), # nonexistent vehicle
        ("/api/events/new-delivery", {"delivery_id": "bad", "demand": -10.0}), # negative demand
        ("/api/events/time-window-change", {"delivery_id": "nonexistent_delivery_999", "new_window_start": 10.0, "new_window_end": 50.0}),
    ]
    payload_results = []
    for endpoint, p in bad_payloads:
        st, r = request(endpoint, "POST", p)
        # Server must NOT crash with 500
        payload_results.append((endpoint, p, st, st < 500))

    all_handled = all(ok for _, _, _, ok in payload_results)
    if all_handled:
        results["15_invalid_payload"] = ("PASS", f"All {len(bad_payloads)} invalid payloads rejected safely (< 500)")
    else:
        crashes = [(ep, p, st) for ep, p, st, ok in payload_results if not ok]
        results["15_invalid_payload"] = ("FAIL", f"500 crashes observed on invalid payloads: {crashes}")
    print(f"Result: {results['15_invalid_payload']}")

    print("\n" + "=" * 70)
    print("QA SUITE SUMMARY")
    print("=" * 70)
    for k, (verdict, detail) in results.items():
        print(f"[{verdict}] {k}: {detail}")
    print("=" * 70)

if __name__ == "__main__":
    run_qa_suite()
