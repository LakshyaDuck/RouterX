"""
Deterministic Demo Scenario Generator for Hackathon.

Provides a fixed, realistic delivery network:
  - 25 nodes (1 central depot + 24 city locations)
  - 45 bidirectional roads with distance & travel times
  - 8 vehicles with realistic mixed capacities and driver hours
  - 40 deliveries with mixed priorities (P1, P2, P3) and varied time windows
  - 4 pre-configured demo events (traffic jam, V03 breakdown, rush order, window change)

All data is 100% deterministic (no unseeded random generator).
"""

from typing import Any
from app.models import (
    Node, Road, Vehicle, Delivery, Event,
    VehicleStatus, DeliveryStatus, EventType
)

# ---------------------------------------------------------------------------
# City Nodes (25 nodes)
# ---------------------------------------------------------------------------

BASE_LAT = 40.7128
BASE_LON = -74.0060

def _offset(lat_d: float, lon_d: float) -> tuple[float, float]:
    return round(BASE_LAT + lat_d, 6), round(BASE_LON + lon_d, 6)


DEMO_NODES_DATA: list[dict] = [
    {"id": "depot", "label": "Central Fleet Depot",      "lat_d":  0.000, "lon_d":  0.000, "is_depot": True},
    {"id": "n01",   "label": "City Hall & Civic Center", "lat_d":  0.006, "lon_d":  0.003},
    {"id": "n02",   "label": "Main Street Market",       "lat_d":  0.009, "lon_d": -0.006},
    {"id": "n03",   "label": "Central Park North",       "lat_d":  0.014, "lon_d":  0.002},
    {"id": "n04",   "label": "Financial District",       "lat_d": -0.004, "lon_d":  0.007},
    {"id": "n05",   "label": "Union Square Commerce",    "lat_d":  0.011, "lon_d": -0.003},
    {"id": "n06",   "label": "West Harbor Terminal",     "lat_d":  0.003, "lon_d": -0.016},
    {"id": "n07",   "label": "Riverside Plaza",          "lat_d":  0.008, "lon_d": -0.019},
    {"id": "n08",   "label": "Westfield Mall",           "lat_d":  0.016, "lon_d": -0.015},
    {"id": "n09",   "label": "Sunset Industrial Park",   "lat_d": -0.006, "lon_d": -0.013},
    {"id": "n10",   "label": "East Gate Commercial Hub", "lat_d":  0.004, "lon_d":  0.017},
    {"id": "n11",   "label": "Innovation Tech Campus",   "lat_d":  0.010, "lon_d":  0.021},
    {"id": "n12",   "label": "Metro Stadium District",   "lat_d":  0.017, "lon_d":  0.015},
    {"id": "n13",   "label": "East Suburbs Plaza",       "lat_d":  0.021, "lon_d":  0.023},
    {"id": "n14",   "label": "North Expressway Junction","lat_d":  0.023, "lon_d":  0.006},
    {"id": "n15",   "label": "University Medical Center","lat_d":  0.026, "lon_d": -0.004},
    {"id": "n16",   "label": "North Point Retail Center","lat_d":  0.029, "lon_d":  0.010},
    {"id": "n17",   "label": "Grand South Station",      "lat_d": -0.011, "lon_d":  0.003},
    {"id": "n18",   "label": "Airport Logistics Way",    "lat_d": -0.019, "lon_d":  0.006},
    {"id": "n19",   "label": "South Manufacturing Hub",  "lat_d": -0.016, "lon_d": -0.009},
    {"id": "n20",   "label": "Intermodal Freight Terminal","lat_d":-0.021, "lon_d":  0.015},
    {"id": "n21",   "label": "Ring Expressway North",    "lat_d":  0.019, "lon_d": -0.008},
    {"id": "n22",   "label": "Ring Expressway East",     "lat_d":  0.013, "lon_d":  0.012},
    {"id": "n23",   "label": "Ring Expressway South",    "lat_d": -0.008, "lon_d":  0.011},
    {"id": "n24",   "label": "Ring Expressway West",     "lat_d":  0.002, "lon_d": -0.010},
]

# ---------------------------------------------------------------------------
# City Roads (45 edges)
# ---------------------------------------------------------------------------

DEMO_ROADS_DATA: list[tuple[str, str, str, float, float]] = [
    # (id, from, to, distance_km, base_time_min)
    ("road_000", "depot", "n01", 1.8, 3.5),
    ("road_001", "depot", "n04", 1.9, 3.8),
    ("road_002", "depot", "n24", 2.2, 4.2),
    ("road_003", "depot", "n17", 2.5, 4.8),
    ("road_004", "n01",   "n02", 1.5, 3.0),
    ("road_005", "n02",   "n05", 1.2, 2.5),
    ("road_006", "n05",   "n03", 1.4, 2.8),
    ("road_007", "n03",   "n01", 1.7, 3.2),
    ("road_008", "n01",   "n22", 2.0, 3.8),
    ("road_009", "n04",   "n23", 1.6, 3.1),
    ("road_010", "n24",   "n06", 1.4, 2.7),
    ("road_011", "n06",   "n07", 1.3, 2.6),
    ("road_012", "n07",   "n08", 2.1, 4.0),
    ("road_013", "n08",   "n21", 1.8, 3.5),
    ("road_014", "n24",   "n09", 1.7, 3.3),
    ("road_015", "n09",   "n19", 2.3, 4.5),
    ("road_016", "n22",   "n10", 1.9, 3.7),
    ("road_017", "n10",   "n11", 1.6, 3.2),
    ("road_018", "n11",   "n12", 2.0, 3.9),
    ("road_019", "n12",   "n13", 2.2, 4.3),
    ("road_020", "n13",   "n16", 2.1, 4.1),
    ("road_021", "n11",   "n22", 1.8, 3.5),
    ("road_022", "n21",   "n15", 1.9, 3.6),
    ("road_023", "n15",   "n14", 1.7, 3.3),
    ("road_024", "n14",   "n16", 2.4, 4.6),
    ("road_025", "n16",   "n13", 2.1, 4.1),
    ("road_026", "n03",   "n14", 2.3, 4.4),
    ("road_027", "n05",   "n21", 1.6, 3.1),
    ("road_028", "n17",   "n18", 2.2, 4.2),
    ("road_029", "n18",   "n20", 2.5, 4.9),
    ("road_030", "n20",   "n23", 2.4, 4.6),
    ("road_031", "n23",   "n17", 1.9, 3.7),
    ("road_032", "n17",   "n19", 2.0, 3.8),
    ("road_033", "n18",   "n19", 2.1, 4.1),
    ("road_034", "n21",   "n22", 2.8, 5.2),
    ("road_035", "n22",   "n23", 2.7, 5.0),
    ("road_036", "n23",   "n24", 2.9, 5.5),
    ("road_037", "n24",   "n21", 2.6, 4.9),
    ("road_038", "n02",   "n24", 1.5, 2.9),
    ("road_039", "n04",   "n10", 2.2, 4.2),
    ("road_040", "n08",   "n15", 2.5, 4.8),
    ("road_041", "n09",   "n18", 2.7, 5.1),
    ("road_042", "n12",   "n22", 1.7, 3.3),
    ("road_043", "n20",   "n10", 3.2, 6.0),
    ("road_044", "n16",   "n21", 2.8, 5.3),
]

# ---------------------------------------------------------------------------
# 8 Vehicles (Varied capacities & specs)
# ---------------------------------------------------------------------------

DEMO_VEHICLES_DATA: list[dict] = [
    {"id": "v01", "name": "V01 - Urban Express",  "capacity": 160.0, "driver_hours": 8.0},
    {"id": "v02", "name": "V02 - Metro Cargo",     "capacity": 260.0, "driver_hours": 8.0},
    {"id": "v03", "name": "V03 - Fleet Courier",   "capacity": 180.0, "driver_hours": 7.5},  # Target for breakdown!
    {"id": "v04", "name": "V04 - Heavy Hauler",    "capacity": 450.0, "driver_hours": 8.0},
    {"id": "v05", "name": "V05 - City Sprinter",   "capacity": 140.0, "driver_hours": 7.0},
    {"id": "v06", "name": "V06 - Regional Van",    "capacity": 220.0, "driver_hours": 7.5},
    {"id": "v07", "name": "V07 - Transit Courier", "capacity": 170.0, "driver_hours": 8.0},
    {"id": "v08", "name": "V08 - Freight Prime",   "capacity": 480.0, "driver_hours": 8.0},
]

# ---------------------------------------------------------------------------
# 40 Deliveries (Mixed priorities & varied time windows)
# ---------------------------------------------------------------------------

DEMO_DELIVERIES_DATA: list[dict] = [
    # Priority 1: High / Urgent deliveries (10 orders)
    {"id": "d01", "location": "n01", "demand": 18.0, "priority": 1, "tw_start": 15.0,  "tw_end": 90.0},
    {"id": "d02", "location": "n04", "demand": 24.0, "priority": 1, "tw_start": 20.0,  "tw_end": 100.0},
    {"id": "d03", "location": "n11", "demand": 15.0, "priority": 1, "tw_start": 30.0,  "tw_end": 110.0},
    {"id": "d04", "location": "n15", "demand": 22.0, "priority": 1, "tw_start": 25.0,  "tw_end": 120.0},
    {"id": "d05", "location": "n18", "demand": 30.0, "priority": 1, "tw_start": 35.0,  "tw_end": 130.0},
    {"id": "d06", "location": "n06", "demand": 14.0, "priority": 1, "tw_start": 40.0,  "tw_end": 140.0},
    {"id": "d07", "location": "n10", "demand": 20.0, "priority": 1, "tw_start": 20.0,  "tw_end": 105.0},
    {"id": "d08", "location": "n03", "demand": 16.0, "priority": 1, "tw_start": 45.0,  "tw_end": 150.0},
    {"id": "d09", "location": "n17", "demand": 25.0, "priority": 1, "tw_start": 30.0,  "tw_end": 125.0},
    {"id": "d10", "location": "n22", "demand": 19.0, "priority": 1, "tw_start": 50.0,  "tw_end": 160.0},

    # Priority 2: Standard deliveries (16 orders)
    {"id": "d11", "location": "n02", "demand": 28.0, "priority": 2, "tw_start": 60.0,  "tw_end": 200.0},
    {"id": "d12", "location": "n05", "demand": 32.0, "priority": 2, "tw_start": 60.0,  "tw_end": 220.0},
    {"id": "d13", "location": "n07", "demand": 21.0, "priority": 2, "tw_start": 75.0,  "tw_end": 240.0},
    {"id": "d14", "location": "n08", "demand": 35.0, "priority": 2, "tw_start": 80.0,  "tw_end": 250.0},
    {"id": "d15", "location": "n09", "demand": 18.0, "priority": 2, "tw_start": 90.0,  "tw_end": 260.0},
    {"id": "d16", "location": "n12", "demand": 26.0, "priority": 2, "tw_start": 65.0,  "tw_end": 230.0},
    {"id": "d17", "location": "n13", "demand": 34.0, "priority": 2, "tw_start": 85.0,  "tw_end": 270.0},
    {"id": "d18", "location": "n14", "demand": 22.0, "priority": 2, "tw_start": 70.0,  "tw_end": 240.0},
    {"id": "d19", "location": "n16", "demand": 29.0, "priority": 2, "tw_start": 95.0,  "tw_end": 280.0},
    {"id": "d20", "location": "n19", "demand": 25.0, "priority": 2, "tw_start": 80.0,  "tw_end": 250.0},
    {"id": "d21", "location": "n20", "demand": 38.0, "priority": 2, "tw_start": 100.0, "tw_end": 300.0},
    {"id": "d22", "location": "n21", "demand": 17.0, "priority": 2, "tw_start": 70.0,  "tw_end": 240.0},
    {"id": "d23", "location": "n23", "demand": 23.0, "priority": 2, "tw_start": 90.0,  "tw_end": 270.0},
    {"id": "d24", "location": "n24", "demand": 31.0, "priority": 2, "tw_start": 85.0,  "tw_end": 260.0},
    {"id": "d25", "location": "n01", "demand": 19.0, "priority": 2, "tw_start": 110.0, "tw_end": 290.0},
    {"id": "d26", "location": "n04", "demand": 27.0, "priority": 2, "tw_start": 105.0, "tw_end": 280.0},

    # Priority 3: Flexible deliveries (14 orders)
    {"id": "d27", "location": "n03", "demand": 22.0, "priority": 3, "tw_start": 120.0, "tw_end": 360.0},
    {"id": "d28", "location": "n06", "demand": 16.0, "priority": 3, "tw_start": 130.0, "tw_end": 380.0},
    {"id": "d29", "location": "n07", "demand": 24.0, "priority": 3, "tw_start": 140.0, "tw_end": 400.0},
    {"id": "d30", "location": "n10", "demand": 33.0, "priority": 3, "tw_start": 120.0, "tw_end": 360.0},
    {"id": "d31", "location": "n11", "demand": 20.0, "priority": 3, "tw_start": 150.0, "tw_end": 420.0},
    {"id": "d32", "location": "n12", "demand": 18.0, "priority": 3, "tw_start": 135.0, "tw_end": 390.0},
    {"id": "d33", "location": "n15", "demand": 26.0, "priority": 3, "tw_start": 145.0, "tw_end": 410.0},
    {"id": "d34", "location": "n17", "demand": 31.0, "priority": 3, "tw_start": 160.0, "tw_end": 430.0},
    {"id": "d35", "location": "n18", "demand": 21.0, "priority": 3, "tw_start": 150.0, "tw_end": 420.0},
    {"id": "d36", "location": "n19", "demand": 29.0, "priority": 3, "tw_start": 165.0, "tw_end": 440.0},
    {"id": "d37", "location": "n20", "demand": 36.0, "priority": 3, "tw_start": 170.0, "tw_end": 450.0},
    {"id": "d38", "location": "n21", "demand": 19.0, "priority": 3, "tw_start": 140.0, "tw_end": 400.0},
    {"id": "d39", "location": "n23", "demand": 25.0, "priority": 3, "tw_start": 155.0, "tw_end": 430.0},
    {"id": "d40", "location": "n24", "demand": 22.0, "priority": 3, "tw_start": 160.0, "tw_end": 440.0},
]

# ---------------------------------------------------------------------------
# Pre-Configured Demo Events
# ---------------------------------------------------------------------------

DEMO_EVENTS_SPEC: list[dict] = [
    {
        "step": 1,
        "title": "EVENT 1: Major Traffic Jam on Central Artery",
        "description": "Severe traffic congestion (4.5x multiplier) on road_000 (Central Depot to City Hall) affects multiple vehicle routes.",
        "event_type": "TRAFFIC_UPDATE",
        "affected_entity_id": "road_000",
        "parameters": {
            "road_id": "road_000",
            "traffic_multiplier": 4.5,
            "reason": "Water main maintenance causing multi-lane corridor blockage",
        },
    },
    {
        "step": 2,
        "title": "EVENT 2: Vehicle V03 Mechanical Breakdown",
        "description": "Vehicle V03 suffers transmission failure. Its uncompleted deliveries must be offloaded and reassigned across the active fleet.",
        "event_type": "VEHICLE_BREAKDOWN",
        "affected_entity_id": "v03",
        "parameters": {
            "vehicle_id": "v03",
            "reason": "Transmission overheating on highway; towed to repair depot",
        },
    },
    {
        "step": 3,
        "title": "EVENT 3: Urgent Priority 1 Delivery",
        "description": "Urgent on-demand medical delivery received for Riverside Plaza (n07) with a tight 70-minute window deadline.",
        "event_type": "NEW_DELIVERY",
        "affected_entity_id": "d_rush_p1",
        "parameters": {
            "delivery_id": "d_rush_p1",
            "location": "n07",
            "demand": 22.0,
            "priority": 1,
            "time_window_start": 15.0,
            "time_window_end": 70.0,
        },
    },
    {
        "step": 4,
        "title": "EVENT 4: Expedited VIP Time Window",
        "description": "Corporate customer for delivery d12 (Union Square Commerce) demands express priority, shifting window deadline earlier from 220m to 25m.",
        "event_type": "TIME_WINDOW_CHANGE",
        "affected_entity_id": "d12",
        "parameters": {
            "delivery_id": "d12",
            "new_window_start": 10.0,
            "new_window_end": 25.0,
        },
    },
]


def build_demo_nodes() -> list[Node]:
    nodes = []
    for r in DEMO_NODES_DATA:
        lat, lon = _offset(r["lat_d"], r["lon_d"])
        nodes.append(Node(
            id=r["id"],
            label=r["label"],
            lat=lat,
            lon=lon,
            is_depot=r.get("is_depot", False),
        ))
    return nodes


def build_demo_roads() -> list[Road]:
    roads = []
    for rid, u, v, dist, base_t in DEMO_ROADS_DATA:
        roads.append(Road(
            id=rid,
            from_node=u,
            to_node=v,
            distance=dist,
            base_time=base_t,
            traffic_multiplier=1.0,
            blocked=False,
        ))
    return roads


def build_demo_vehicles() -> list[Vehicle]:
    vehicles = []
    for vd in DEMO_VEHICLES_DATA:
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


def build_demo_deliveries() -> list[Delivery]:
    deliveries = []
    for dd in DEMO_DELIVERIES_DATA:
        deliveries.append(Delivery(
            id=dd["id"],
            location=dd["location"],
            demand=dd["demand"],
            priority=dd["priority"],
            time_window_start=dd["tw_start"],
            time_window_end=dd["tw_end"],
            status=DeliveryStatus.PENDING,
            assigned_vehicle=None,
        ))
    return deliveries


def get_demo_scenario() -> dict[str, Any]:
    """Return the complete, deterministic raw scenario entities."""
    nodes = build_demo_nodes()
    roads = build_demo_roads()
    vehicles = build_demo_vehicles()
    deliveries = build_demo_deliveries()

    return {
        "nodes": nodes,
        "roads": roads,
        "vehicles": vehicles,
        "deliveries": deliveries,
        "events_spec": DEMO_EVENTS_SPEC,
    }
