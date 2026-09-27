"""Quick end-to-end test of the live routing API endpoints."""
import json
import urllib.request
import os

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req).read())

def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read())

print("=" * 58)
print("Routing API End-to-End Tests")
print("=" * 58)

# 1. POST /api/routing/path — depot to a delivery node
res = post("/api/routing/path", {"start": "depot", "end": "n01"})
print(f"\n1. depot -> n01")
print(f"   reachable       : {res['reachable']}")
print(f"   path            : {res['path']}")
print(f"   travel_time_min : {res['travel_time_minutes']:.2f}")
print(f"   hops            : {res['hops']}")
assert res["reachable"], "depot must reach n01"

# 2. POST /api/routing/path — unknown node should 404
try:
    post("/api/routing/path", {"start": "depot", "end": "PHANTOM"})
    print("\n2. Unknown node: FAILED (should have 404'd)")
except urllib.error.HTTPError as e:
    print(f"\n2. Unknown node: OK (got HTTP {e.code} as expected)")

# 3. GET /api/routing/time/{start}/{end}
res = get("/api/routing/time/depot/n10")
print(f"\n3. Travel time depot -> n10")
print(f"   travel_time_min : {res['travel_time_minutes']:.2f}")
print(f"   reachable       : {res['reachable']}")
assert res["reachable"]

# 4. POST /api/routing/route-distance — a simple 3-node waypoint
res = post("/api/routing/route-distance", {"node_ids": ["depot", "n01", "n04"]})
print(f"\n4. Route distance [depot, n01, n04]")
print(f"   distance_km     : {res['total_distance_km']:.3f}")
print(f"   feasible        : {res['feasible']}")

# 5. POST /api/routing/route-time — full route with several stops
stops = ["depot", "n01", "n02", "n05", "n03", "depot"]
res = post("/api/routing/route-time", {"node_ids": stops})
print(f"\n5. Route time {stops}")
print(f"   travel_min      : {res['total_travel_time_minutes']:.2f}")
print(f"   feasible        : {res['feasible']}")
assert res["feasible"]

# 6. POST /api/routing/path — same node, should give singleton path
res = post("/api/routing/path", {"start": "depot", "end": "depot"})
print(f"\n6. depot -> depot (same-node)")
print(f"   path            : {res['path']}")
print(f"   travel_time_min : {res['travel_time_minutes']}")
assert res["path"] == ["depot"]
assert res["travel_time_minutes"] == 0.0

print("\n" + "=" * 58)
print("All live routing endpoint tests PASSED OK")
print("=" * 58)
