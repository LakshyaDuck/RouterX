"""
Simulated city data generator.
Produces deterministic data with a fixed random seed so the demo
looks the same every time you start fresh.

City layout: a fictional mid-size city with a downtown depot,
residential zones, commercial zones, and industrial areas.
"""

import math
import random
from typing import Any

from app.models import (
    Node, Road, Vehicle, Delivery, Route, Event,
    VehicleStatus, DeliveryStatus
)

SEED = 42
rng = random.Random(SEED)

# ---------------------------------------------------------------------------
# Node definitions (25 nodes: 1 depot + 24 delivery locations)
# ---------------------------------------------------------------------------

# Approximate city centered near a fictional location
# We'll place nodes on a lat/lon grid with small offsets
BASE_LAT = 40.7128   # New York-ish
BASE_LON = -74.0060

def _offset(lat_d: float, lon_d: float) -> tuple[float, float]:
    """Convert degree offsets to absolute lat/lon."""
    return round(BASE_LAT + lat_d, 6), round(BASE_LON + lon_d, 6)


RAW_NODES: list[dict] = [
    # Depot
    {"id": "depot",  "label": "Central Depot",        "lat_d":  0.000, "lon_d":  0.000, "is_depot": True},
    # Downtown
    {"id": "n01",    "label": "City Hall",             "lat_d":  0.005, "lon_d":  0.003},
    {"id": "n02",    "label": "Main Street Market",    "lat_d":  0.008, "lon_d": -0.005},
    {"id": "n03",    "label": "Central Park North",    "lat_d":  0.012, "lon_d":  0.001},
    {"id": "n04",    "label": "Financial District",    "lat_d": -0.003, "lon_d":  0.006},
    {"id": "n05",    "label": "Union Square",          "lat_d":  0.010, "lon_d": -0.002},
    # West side
    {"id": "n06",    "label": "West Harbor",           "lat_d":  0.002, "lon_d": -0.015},
    {"id": "n07",    "label": "Riverside Plaza",       "lat_d":  0.007, "lon_d": -0.018},
    {"id": "n08",    "label": "West Mall",             "lat_d":  0.015, "lon_d": -0.014},
    {"id": "n09",    "label": "Sunset Industrial",     "lat_d": -0.005, "lon_d": -0.012},
    # East side
    {"id": "n10",    "label": "East Gate",             "lat_d":  0.003, "lon_d":  0.016},
    {"id": "n11",    "label": "Tech Campus",           "lat_d":  0.009, "lon_d":  0.020},
    {"id": "n12",    "label": "Stadium District",      "lat_d":  0.016, "lon_d":  0.014},
    {"id": "n13",    "label": "East Suburb",           "lat_d":  0.020, "lon_d":  0.022},
    # North
    {"id": "n14",    "label": "North Junction",        "lat_d":  0.022, "lon_d":  0.005},
    {"id": "n15",    "label": "University Campus",     "lat_d":  0.025, "lon_d": -0.003},
    {"id": "n16",    "label": "North Mall",            "lat_d":  0.028, "lon_d":  0.009},
    # South
    {"id": "n17",    "label": "South Station",         "lat_d": -0.010, "lon_d":  0.002},
    {"id": "n18",    "label": "Airport Road",          "lat_d": -0.018, "lon_d":  0.005},
    {"id": "n19",    "label": "South Industrial Park", "lat_d": -0.015, "lon_d": -0.008},
    {"id": "n20",    "label": "Logistics Hub",         "lat_d": -0.020, "lon_d":  0.014},
    # Mid-ring connectors
    {"id": "n21",    "label": "Ring Road North",       "lat_d":  0.018, "lon_d": -0.007},
    {"id": "n22",    "label": "Ring Road East",        "lat_d":  0.012, "lon_d":  0.011},
    {"id": "n23",    "label": "Ring Road South",       "lat_d": -0.007, "lon_d":  0.010},
    {"id": "n24",    "label": "Ring Road West",        "lat_d":  0.001, "lon_d": -0.009},
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance in km between two lat/lon points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def build_nodes() -> list[Node]:
    nodes = []
    for r in RAW_NODES:
        lat, lon = _offset(r["lat_d"], r["lon_d"])
        nodes.append(Node(
            id=r["id"],
            label=r["label"],
            lat=lat,
            lon=lon,
            is_depot=r.get("is_depot", False),
        ))
    return nodes


# ---------------------------------------------------------------------------
# Road edge definitions (45 edges, bidirectional)
# ---------------------------------------------------------------------------

RAW_EDGES: list[tuple[str, str]] = [
    # Depot connections
    ("depot", "n01"), ("depot", "n04"), ("depot", "n24"), ("depot", "n17"),
    # Downtown ring
    ("n01", "n02"), ("n02", "n05"), ("n05", "n03"), ("n03", "n01"),
    ("n01", "n22"), ("n04", "n23"),
    # West side
    ("n24", "n06"), ("n06", "n07"), ("n07", "n08"), ("n08", "n21"),
    ("n24", "n09"), ("n09", "n19"),
    # East side
    ("n22", "n10"), ("n10", "n11"), ("n11", "n12"), ("n12", "n13"),
    ("n13", "n16"), ("n11", "n22"),
    # North
    ("n21", "n15"), ("n15", "n14"), ("n14", "n16"), ("n16", "n13"),
    ("n03", "n14"), ("n05", "n21"),
    # South
    ("n17", "n18"), ("n18", "n20"), ("n20", "n23"), ("n23", "n17"),
    ("n17", "n19"), ("n18", "n19"),
    # Ring connectors
    ("n21", "n22"), ("n22", "n23"), ("n23", "n24"), ("n24", "n21"),
    # Cross links
    ("n02", "n24"), ("n04", "n10"), ("n08", "n15"), ("n09", "n18"),
    ("n12", "n22"), ("n20", "n10"), ("n16", "n21"),
]


def build_roads(nodes: list[Node]) -> list[Road]:
    """Build roads with distances derived from haversine and random traffic."""
    node_map = {n.id: n for n in nodes}
    roads = []
    avg_speed_kph = 40.0  # city average

    for i, (a, b) in enumerate(RAW_EDGES):
        na, nb = node_map[a], node_map[b]
        dist = round(_haversine_km(na.lat, na.lon, nb.lat, nb.lon), 3)
        # Minimum distance of 0.3 km to avoid zero-time edges
        dist = max(dist, 0.3)
        base_time = round((dist / avg_speed_kph) * 60, 2)  # minutes
        traffic = round(rng.uniform(0.9, 1.4), 2)
        roads.append(Road(
            id=f"road_{i:03d}",
            from_node=a,
            to_node=b,
            distance=dist,
            base_time=base_time,
            traffic_multiplier=traffic,
            blocked=False,
        ))
    return roads


# ---------------------------------------------------------------------------
# Vehicles (6 vehicles with varied capacity)
# ---------------------------------------------------------------------------

VEHICLE_DEFS: list[dict] = [
    {"id": "v1", "name": "Truck Alpha",   "capacity": 500.0, "driver_hours": 8.0},
    {"id": "v2", "name": "Van Beta",      "capacity": 250.0, "driver_hours": 7.5},
    {"id": "v3", "name": "Van Gamma",     "capacity": 250.0, "driver_hours": 7.5},
    {"id": "v4", "name": "Truck Delta",   "capacity": 600.0, "driver_hours": 8.0},
    {"id": "v5", "name": "Courier Epsilon","capacity": 80.0, "driver_hours": 6.0},
    {"id": "v6", "name": "Van Zeta",      "capacity": 300.0, "driver_hours": 7.0},
]


def build_vehicles() -> list[Vehicle]:
    vehicles = []
    for vd in VEHICLE_DEFS:
        vehicles.append(Vehicle(
            id=vd["id"],
            name=vd["name"],
            capacity=vd["capacity"],
            current_location="depot",
            driver_hours_remaining=vd["driver_hours"],
            status=VehicleStatus.ACTIVE,
            current_load=0.0,
        ))
    return vehicles


# ---------------------------------------------------------------------------
# Deliveries (30 deliveries spread across non-depot nodes)
# ---------------------------------------------------------------------------

DELIVERY_NODES = [r["id"] for r in RAW_NODES if not r.get("is_depot")]

PRIORITY_WEIGHTS = [1, 1, 2, 2, 3, 3, 3]  # more low-priority deliveries

def build_deliveries() -> list[Delivery]:
    deliveries = []
    for i in range(30):
        node_id = rng.choice(DELIVERY_NODES)
        priority = rng.choice(PRIORITY_WEIGHTS)
        demand = round(rng.uniform(5.0, 80.0), 1)

        # Time windows: priority 1 = tight, 3 = wide
        window_center = rng.uniform(60, 420)   # 1h to 7h from sim start
        half_width = {1: 30, 2: 60, 3: 120}[priority]
        tw_start = max(0, round(window_center - half_width, 1))
        tw_end = round(window_center + half_width, 1)

        deliveries.append(Delivery(
            id=f"d{i+1:02d}",
            location=node_id,
            demand=demand,
            priority=priority,
            time_window_start=tw_start,
            time_window_end=tw_end,
            status=DeliveryStatus.PENDING,
        ))
    return deliveries


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_city_data() -> dict[str, Any]:
    """Return the full simulated city dataset as serializable dicts."""
    nodes = build_nodes()
    roads = build_roads(nodes)
    vehicles = build_vehicles()
    deliveries = build_deliveries()

    return {
        "nodes": [n.model_dump() for n in nodes],
        "roads": [r.model_dump() for r in roads],
        "vehicles": [v.model_dump() for v in vehicles],
        "deliveries": [d.model_dump() for d in deliveries],
    }
