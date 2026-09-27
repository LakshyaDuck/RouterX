"""
The deterministic demo scenario.

A fixed, hand-authored city: 25 nodes (one depot + 24 delivery locations), 45
bidirectional roads, 8 vehicles, and 40 deliveries across three priority bands.
There is no random generator anywhere in this module, by design. Every number
below is a literal, so the scenario is byte-identical on every machine and every
restart. That is what makes the demo events reproducible and what lets a test
assert on specific routes and specific violations instead of on "some route,
some violation".

Ported from Routerpriv8's simulation/demo_scenario.py. Two deliberate changes
from the source:

  * It lives at backend/app/demo_scenario.py rather than a top-level
    simulation/ package. The source reached it with a `sys.path.insert` in
    main.py and its sibling city_data.py imported `app.models`, so the package
    could not be moved or imported on its own. Next to the models it describes
    is both the obvious location and one that needs no path manipulation.

  * city_data.py is NOT ported. It is a second, divergent scenario generator
    (seeded RNG, 6 vehicles, 30 deliveries, different node coordinates) that
    nothing in the API ever used — only two throwaway scripts referenced it.
    Carrying both forward would mean two sources of truth for "what is the
    demo city", differing in ways nothing would catch.

DEPOT_ID is load-bearing beyond this file. The routing graph treats roads as
bidirectional and the optimizer returns every vehicle to the literal string
"depot" at the end of a route. Renaming the depot id does not fail here — it
makes every route in the system unreachable, silently, one phase later.
"""

from typing import Any

from models import (
    Delivery,
    DeliveryStatus,
    Node,
    Road,
    Vehicle,
    VehicleStatus,
)

# The node every vehicle starts at and every route returns to.
DEPOT_ID = "depot"


# ---------------------------------------------------------------------------
# City Nodes (25 nodes)
# ---------------------------------------------------------------------------

# Offsets from a nominal city centre rather than absolute coordinates. The world
# is imaginary (see the project README), so anchoring to a real city's latitude
# and longitude would imply a geography that does not exist. The offsets are
# what actually matter: they set the relative layout the map draws.
_BASE_LAT = 40.7128
_BASE_LON = -74.0060


def _offset(lat_d: float, lon_d: float) -> tuple[float, float]:
    return round(_BASE_LAT + lat_d, 6), round(_BASE_LON + lon_d, 6)


DEMO_NODES_DATA: list[dict] = [
    {"id": "depot", "label": "Central Fleet Depot", "lat_d": 0.000, "lon_d": 0.000, "is_depot": True},
    {"id": "n01", "label": "City Hall & Civic Center", "lat_d": 0.006, "lon_d": 0.003},
    {"id": "n02", "label": "Main Street Market", "lat_d": 0.009, "lon_d": -0.006},
    {"id": "n03", "label": "Central Park North", "lat_d": 0.014, "lon_d": 0.002},
    {"id": "n04", "label": "Financial District", "lat_d": -0.004, "lon_d": 0.007},
    {"id": "n05", "label": "Union Square Commerce", "lat_d": 0.011, "lon_d": -0.003},
    {"id": "n06", "label": "West Harbor Terminal", "lat_d": 0.003, "lon_d": -0.016},
    {"id": "n07", "label": "Riverside Plaza", "lat_d": 0.008, "lon_d": -0.019},
    {"id": "n08", "label": "Westfield Mall", "lat_d": 0.016, "lon_d": -0.015},
    {"id": "n09", "label": "Sunset Industrial Park", "lat_d": -0.006, "lon_d": -0.013},
    {"id": "n10", "label": "East Gate Commercial Hub", "lat_d": 0.004, "lon_d": 0.017},
    {"id": "n11", "label": "Innovation Tech Campus", "lat_d": 0.010, "lon_d": 0.021},
    {"id": "n12", "label": "Metro Stadium District", "lat_d": 0.017, "lon_d": 0.015},
    {"id": "n13", "label": "East Suburbs Plaza", "lat_d": 0.021, "lon_d": 0.023},
    {"id": "n14", "label": "North Expressway Junction", "lat_d": 0.023, "lon_d": 0.006},
    {"id": "n15", "label": "University Medical Center", "lat_d": 0.026, "lon_d": -0.004},
    {"id": "n16", "label": "North Point Retail Center", "lat_d": 0.029, "lon_d": 0.010},
    {"id": "n17", "label": "Grand South Station", "lat_d": -0.011, "lon_d": 0.003},
    {"id": "n18", "label": "Airport Logistics Way", "lat_d": -0.019, "lon_d": 0.006},
    {"id": "n19", "label": "South Manufacturing Hub", "lat_d": -0.016, "lon_d": -0.009},
    {"id": "n20", "label": "Intermodal Freight Terminal", "lat_d": -0.021, "lon_d": 0.015},
    {"id": "n21", "label": "Ring Expressway North", "lat_d": 0.019, "lon_d": -0.008},
    {"id": "n22", "label": "Ring Expressway East", "lat_d": 0.013, "lon_d": 0.012},
    {"id": "n23", "label": "Ring Expressway South", "lat_d": -0.008, "lon_d": 0.011},
    {"id": "n24", "label": "Ring Expressway West", "lat_d": 0.002, "lon_d": -0.010},
]


# ---------------------------------------------------------------------------
# City Roads (45 edges)
# ---------------------------------------------------------------------------
#
# Each tuple is (id, from_node, to_node, distance_km, base_time_min). The two
# are stated independently rather than derived from each other, so the scenario
# can express "this road is short on distance but slow" — which is the normal
# shape of real congestion and is exactly what the traffic events in Phase 5
# manipulate. Deriving base_time from distance at a fixed speed would make the
# multiplier the only way to express slowness, and would quietly rule that out.
#
# Roads are stored once and treated as bidirectional by the graph. Storing both
# directions would double the rows and guarantee the two copies drift.

DEMO_ROADS_DATA: list[tuple[str, str, str, float, float]] = [
    # (id, from, to, distance_km, base_time_min)
    ("road_000", "depot", "n01", 1.8, 3.5),
    ("road_001", "depot", "n04", 1.9, 3.8),
    ("road_002", "depot", "n24", 2.2, 4.2),
    ("road_003", "depot", "n17", 2.5, 4.8),
    ("road_004", "n01", "n02", 1.5, 3.0),
    ("road_005", "n02", "n05", 1.2, 2.5),
    ("road_006", "n05", "n03", 1.4, 2.8),
    ("road_007", "n03", "n01", 1.7, 3.2),
    ("road_008", "n01", "n22", 2.0, 3.8),
    ("road_009", "n04", "n23", 1.6, 3.1),
    ("road_010", "n24", "n06", 1.4, 2.7),
    ("road_011", "n06", "n07", 1.3, 2.6),
    ("road_012", "n07", "n08", 2.1, 4.0),
    ("road_013", "n08", "n21", 1.8, 3.5),
    ("road_014", "n24", "n09", 1.7, 3.3),
    ("road_015", "n09", "n19", 2.3, 4.5),
    ("road_016", "n22", "n10", 1.9, 3.7),
    ("road_017", "n10", "n11", 1.6, 3.2),
    ("road_018", "n11", "n12", 2.0, 3.9),
    ("road_019", "n12", "n13", 2.2, 4.3),
    ("road_020", "n13", "n16", 2.1, 4.1),
    ("road_021", "n11", "n22", 1.8, 3.5),
    ("road_022", "n21", "n15", 1.9, 3.6),
    ("road_023", "n15", "n14", 1.7, 3.3),
    ("road_024", "n14", "n16", 2.4, 4.6),
    ("road_025", "n16", "n13", 2.1, 4.1),
    ("road_026", "n03", "n14", 2.3, 4.4),
    ("road_027", "n05", "n21", 1.6, 3.1),
    ("road_028", "n17", "n18", 2.2, 4.2),
    ("road_029", "n18", "n20", 2.5, 4.9),
    ("road_030", "n20", "n23", 2.4, 4.6),
    ("road_031", "n23", "n17", 1.9, 3.7),
    ("road_032", "n17", "n19", 2.0, 3.8),
    ("road_033", "n18", "n19", 2.1, 4.1),
    ("road_034", "n21", "n22", 2.8, 5.2),
    ("road_035", "n22", "n23", 2.7, 5.0),
    ("road_036", "n23", "n24", 2.9, 5.5),
    ("road_037", "n24", "n21", 2.6, 4.9),
    ("road_038", "n02", "n24", 1.5, 2.9),
    ("road_039", "n04", "n10", 2.2, 4.2),
    ("road_040", "n08", "n15", 2.5, 4.8),
    ("road_041", "n09", "n18", 2.7, 5.1),
    ("road_042", "n12", "n22", 1.7, 3.3),
    ("road_043", "n20", "n10", 3.2, 6.0),
    ("road_044", "n16", "n21", 2.8, 5.3),
]


# ---------------------------------------------------------------------------
# 8 Vehicles (varied capacities and driver hours)
# ---------------------------------------------------------------------------

DEMO_VEHICLES_DATA: list[dict] = [
    {"id": "v01", "name": "V01 - Urban Express", "capacity": 160.0, "driver_hours": 8.0},
    {"id": "v02", "name": "V02 - Metro Cargo", "capacity": 260.0, "driver_hours": 8.0},
    # v03 is the target of demo event 2 (mechanical breakdown). Its stops are
    # what that event has to offload, so the scenario is only a fair test of
    # breakdown handling if v03 actually carries work — which it does only once
    # the optimizer has run. See the Phase 3 note on seeding order.
    {"id": "v03", "name": "V03 - Fleet Courier", "capacity": 180.0, "driver_hours": 7.5},
    {"id": "v04", "name": "V04 - Heavy Hauler", "capacity": 450.0, "driver_hours": 8.0},
    {"id": "v05", "name": "V05 - City Sprinter", "capacity": 140.0, "driver_hours": 7.0},
    {"id": "v06", "name": "V06 - Regional Van", "capacity": 220.0, "driver_hours": 7.5},
    {"id": "v07", "name": "V07 - Transit Courier", "capacity": 170.0, "driver_hours": 8.0},
    {"id": "v08", "name": "V08 - Freight Prime", "capacity": 480.0, "driver_hours": 8.0},
]


# ---------------------------------------------------------------------------
# 40 Deliveries (three priority bands, varied time windows)
# ---------------------------------------------------------------------------
#
# The bands are ordered in the literal, and the split is deliberate:
#   P1  d01-d10  tight windows (15-160 min)  — must be served early
#   P2  d11-d26  moderate windows (60-300 min)
#   P3  d27-d40  wide windows (120-450 min)   — the slack the solver spends
#
# A single band would not exercise the thing the optimizer is for. The P1/P3
# contrast is what forces priority ordering to matter: with 10 urgent orders
# competing for 8 vehicles and windows that overlap, a solver that ignores
# priority produces a plan that is feasible on paper and useless in practice.

DEMO_DELIVERIES_DATA: list[dict] = [
    # Priority 1: urgent (10 orders)
    {"id": "d01", "location": "n01", "demand": 18.0, "priority": 1, "tw_start": 15.0, "tw_end": 90.0},
    {"id": "d02", "location": "n04", "demand": 24.0, "priority": 1, "tw_start": 20.0, "tw_end": 100.0},
    {"id": "d03", "location": "n11", "demand": 15.0, "priority": 1, "tw_start": 30.0, "tw_end": 110.0},
    {"id": "d04", "location": "n15", "demand": 22.0, "priority": 1, "tw_start": 25.0, "tw_end": 120.0},
    {"id": "d05", "location": "n18", "demand": 30.0, "priority": 1, "tw_start": 35.0, "tw_end": 130.0},
    {"id": "d06", "location": "n06", "demand": 14.0, "priority": 1, "tw_start": 40.0, "tw_end": 140.0},
    {"id": "d07", "location": "n10", "demand": 20.0, "priority": 1, "tw_start": 20.0, "tw_end": 105.0},
    {"id": "d08", "location": "n03", "demand": 16.0, "priority": 1, "tw_start": 45.0, "tw_end": 150.0},
    {"id": "d09", "location": "n17", "demand": 25.0, "priority": 1, "tw_start": 30.0, "tw_end": 125.0},
    {"id": "d10", "location": "n22", "demand": 19.0, "priority": 1, "tw_start": 50.0, "tw_end": 160.0},
    # Priority 2: standard (16 orders)
    {"id": "d11", "location": "n02", "demand": 28.0, "priority": 2, "tw_start": 60.0, "tw_end": 200.0},
    {"id": "d12", "location": "n05", "demand": 32.0, "priority": 2, "tw_start": 60.0, "tw_end": 220.0},
    {"id": "d13", "location": "n07", "demand": 21.0, "priority": 2, "tw_start": 75.0, "tw_end": 240.0},
    {"id": "d14", "location": "n08", "demand": 35.0, "priority": 2, "tw_start": 80.0, "tw_end": 250.0},
    {"id": "d15", "location": "n09", "demand": 18.0, "priority": 2, "tw_start": 90.0, "tw_end": 260.0},
    {"id": "d16", "location": "n12", "demand": 26.0, "priority": 2, "tw_start": 65.0, "tw_end": 230.0},
    {"id": "d17", "location": "n13", "demand": 34.0, "priority": 2, "tw_start": 85.0, "tw_end": 270.0},
    {"id": "d18", "location": "n14", "demand": 22.0, "priority": 2, "tw_start": 70.0, "tw_end": 240.0},
    {"id": "d19", "location": "n16", "demand": 29.0, "priority": 2, "tw_start": 95.0, "tw_end": 280.0},
    {"id": "d20", "location": "n19", "demand": 25.0, "priority": 2, "tw_start": 80.0, "tw_end": 250.0},
    {"id": "d21", "location": "n20", "demand": 38.0, "priority": 2, "tw_start": 100.0, "tw_end": 300.0},
    {"id": "d22", "location": "n21", "demand": 17.0, "priority": 2, "tw_start": 70.0, "tw_end": 240.0},
    {"id": "d23", "location": "n23", "demand": 23.0, "priority": 2, "tw_start": 90.0, "tw_end": 270.0},
    {"id": "d24", "location": "n24", "demand": 31.0, "priority": 2, "tw_start": 85.0, "tw_end": 260.0},
    {"id": "d25", "location": "n01", "demand": 19.0, "priority": 2, "tw_start": 110.0, "tw_end": 290.0},
    {"id": "d26", "location": "n04", "demand": 27.0, "priority": 2, "tw_start": 105.0, "tw_end": 280.0},
    # Priority 3: flexible (14 orders)
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
# Pre-configured demo events
# ---------------------------------------------------------------------------
#
# Consumed by the /api/simulation endpoints in Phase 6, not here — this phase
# only carries the definitions forward so the scenario and its demo share one
# source of truth. Each entry names a real entity from the data above; the
# referential check in validate_demo_scenario() enforces that now rather than
# letting a renamed road turn demo step 1 into a silent no-op later.

DEMO_EVENTS_SPEC: list[dict] = [
    {
        "step": 1,
        "title": "EVENT 1: Major Traffic Jam on Central Artery",
        "description": (
            "Severe traffic congestion (4.5x multiplier) on road_000 "
            "(Central Depot to City Hall) affects multiple vehicle routes."
        ),
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
        "description": (
            "Vehicle V03 suffers transmission failure. Its uncompleted "
            "deliveries must be offloaded and reassigned across the active fleet."
        ),
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
        "description": (
            "Urgent on-demand medical delivery received for Riverside Plaza "
            "(n07) with a tight 70-minute window deadline."
        ),
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
        "description": (
            "Corporate customer for delivery d12 (Union Square Commerce) demands "
            "express priority, shifting window deadline earlier from 220m to 25m."
        ),
        "event_type": "TIME_WINDOW_CHANGE",
        "affected_entity_id": "d12",
        "parameters": {
            "delivery_id": "d12",
            "new_window_start": 10.0,
            "new_window_end": 25.0,
        },
    },
]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_demo_nodes() -> list[Node]:
    return [
        Node(
            id=row["id"],
            label=row["label"],
            lat=_offset(row["lat_d"], row["lon_d"])[0],
            lon=_offset(row["lat_d"], row["lon_d"])[1],
            is_depot=row.get("is_depot", False),
        )
        for row in DEMO_NODES_DATA
    ]


def build_demo_roads() -> list[Road]:
    # traffic_multiplier 1.0 and blocked False on every road: the scenario is
    # the undisturbed baseline. Every congestion and closure in the demo is an
    # event applied on top, which is what makes "reset and replay" meaningful.
    return [
        Road(
            id=road_id,
            from_node=from_node,
            to_node=to_node,
            distance=distance,
            base_time=base_time,
            traffic_multiplier=1.0,
            blocked=False,
        )
        for road_id, from_node, to_node, distance, base_time in DEMO_ROADS_DATA
    ]


def build_demo_vehicles() -> list[Vehicle]:
    return [
        Vehicle(
            id=row["id"],
            name=row["name"],
            capacity=row["capacity"],
            current_location=DEPOT_ID,
            driver_hours_remaining=row["driver_hours"],
            status=VehicleStatus.ACTIVE,
            current_load=0.0,
        )
        for row in DEMO_VEHICLES_DATA
    ]


def build_demo_deliveries() -> list[Delivery]:
    return [
        Delivery(
            id=row["id"],
            location=row["location"],
            demand=row["demand"],
            priority=row["priority"],
            time_window_start=row["tw_start"],
            time_window_end=row["tw_end"],
            status=DeliveryStatus.PENDING,
            assigned_vehicle=None,
        )
        for row in DEMO_DELIVERIES_DATA
    ]


def get_demo_scenario() -> dict[str, Any]:
    """Return every scenario entity, as live SQLModel objects."""
    return {
        "nodes": build_demo_nodes(),
        "roads": build_demo_roads(),
        "vehicles": build_demo_vehicles(),
        "deliveries": build_demo_deliveries(),
        "events_spec": DEMO_EVENTS_SPEC,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Which entity type each demo event's affected_entity_id must resolve to. A
# traffic update names a road, a breakdown names a vehicle. Checking the type
# as well as the existence catches the more likely mistake: renaming a road to
# something that happens to collide with a node id.
_EVENT_TARGET_TABLE = {
    "TRAFFIC_UPDATE": ("roads", "road_id", "existing"),
    "ROAD_BLOCKED": ("roads", "road_id", "existing"),
    "VEHICLE_BREAKDOWN": ("vehicles", "vehicle_id", "existing"),
    "DELIVERY_CANCELLED": ("deliveries", "delivery_id", "existing"),
    "TIME_WINDOW_CHANGE": ("deliveries", "delivery_id", "existing"),
    # NEW_DELIVERY is the one event whose target does not exist yet: it names
    # the id the event will CREATE. So the check inverts — the id must be free,
    # not present.
    "NEW_DELIVERY": ("deliveries", "delivery_id", "to_create"),
}

_TABLE_SINGULAR = {"roads": "road", "vehicles": "vehicle", "deliveries": "delivery"}


def validate_demo_scenario() -> list[str]:
    """
    Check the scenario's internal consistency. Returns a list of problems.

    An empty list means the data is sound. This exists because the failure mode
    of hand-authored fixture data is not a crash — it is a scenario that seeds
    successfully and is subtly wrong. A delivery pointing at a misspelled node
    id, or a road whose endpoint is not in the node table, produces no error at
    insert time; it produces an unreachable delivery two phases later, once the
    graph is built, where the cause is no longer visible.

    Checks, in order of how badly they would hurt:
      1. exactly one depot, with the expected id
      2. no duplicate ids within any table
      3. every road endpoint is a real node
      4. every delivery location is a real node, and is not the depot
      5. every delivery window is non-empty and ordered
      6. every priority is 1-3
      7. every demo event names a real entity of the right type
    """
    problems: list[str] = []
    nodes = build_demo_nodes()
    roads = build_demo_roads()
    vehicles = build_demo_vehicles()
    deliveries = build_demo_deliveries()

    node_ids = {n.id for n in nodes}
    road_ids = {r.id for r in roads}
    vehicle_ids = {v.id for v in vehicles}
    delivery_ids = {d.id for d in deliveries}

    # 1. depot
    depots = [n.id for n in nodes if n.is_depot]
    if len(depots) != 1:
        problems.append(f"expected exactly 1 depot node, found {len(depots)}: {depots}")
    if DEPOT_ID not in node_ids:
        problems.append(f"DEPOT_ID {DEPOT_ID!r} is not present in the node table")

    # 2. duplicate ids
    for label, ids in (
        ("node", [n.id for n in nodes]),
        ("road", [r.id for r in roads]),
        ("vehicle", [v.id for v in vehicles]),
        ("delivery", [d.id for d in deliveries]),
    ):
        seen: set[str] = set()
        dupes = sorted({i for i in ids if i in seen or seen.add(i)})  # type: ignore[func-returns-value]
        if dupes:
            problems.append(f"duplicate {label} ids: {dupes}")

    # 3. road endpoints
    for road in roads:
        for endpoint in (road.from_node, road.to_node):
            if endpoint not in node_ids:
                problems.append(f"road {road.id} references unknown node {endpoint!r}")
        if road.from_node == road.to_node:
            problems.append(f"road {road.id} is a self-loop on {road.from_node!r}")
        if road.base_time <= 0:
            problems.append(f"road {road.id} has non-positive base_time {road.base_time}")
        if road.distance <= 0:
            problems.append(f"road {road.id} has non-positive distance {road.distance}")

    # 4-6. deliveries
    for delivery in deliveries:
        if delivery.location not in node_ids:
            problems.append(
                f"delivery {delivery.id} references unknown node {delivery.location!r}"
            )
        elif delivery.location == DEPOT_ID:
            # Not fatal — a depot delivery is legal — but it is never what the
            # author meant, since the depot is where vehicles start and return.
            problems.append(f"delivery {delivery.id} is located at the depot")
        if delivery.time_window_end <= delivery.time_window_start:
            problems.append(
                f"delivery {delivery.id} has an empty or inverted time window "
                f"[{delivery.time_window_start}, {delivery.time_window_end}]"
            )
        if delivery.priority not in (1, 2, 3):
            problems.append(f"delivery {delivery.id} has priority {delivery.priority}, expected 1-3")
        if delivery.demand < 0:
            problems.append(f"delivery {delivery.id} has negative demand {delivery.demand}")

    # 7. demo events resolve
    for spec in DEMO_EVENTS_SPEC:
        event_type = spec["event_type"]
        target = spec.get("affected_entity_id")
        if event_type not in _EVENT_TARGET_TABLE:
            problems.append(f"demo event {spec['step']} has unknown type {event_type!r}")
            continue
        table_name, _param_name, expectation = _EVENT_TARGET_TABLE[event_type]
        pool = {
            "roads": road_ids,
            "vehicles": vehicle_ids,
            "deliveries": delivery_ids,
        }[table_name]
        singular = _TABLE_SINGULAR[table_name]
        if expectation == "existing" and target not in pool:
            problems.append(
                f"demo event {spec['step']} ({event_type}) targets {target!r}, "
                f"which is not a known {singular}"
            )
        elif expectation == "to_create" and target in pool:
            # Not a crash on replay — merge() would overwrite the seeded delivery
            # and the "rush order" would silently become a different order with
            # the same id. Worth catching here rather than in the Phase 6 runner.
            problems.append(
                f"demo event {spec['step']} ({event_type}) creates {target!r}, "
                f"which collides with a seeded {singular}"
            )
        elif expectation == "to_create":
            # A NEW_DELIVERY also has to name a real place to go. Nothing else in
            # the event spec would catch a bad location until the optimizer could
            # not route the stop.
            location = spec["parameters"].get("location")
            if location not in node_ids:
                problems.append(
                    f"demo event {spec['step']} ({event_type}) targets unknown "
                    f"node {location!r}"
                )

    # 8. every node is reachable from the depot
    # Roads are bidirectional, so adjacency is built both ways. This is the check
    # that catches a road endpoint typo's real consequence: a node that is present
    # and well-formed but cut off from the network, which Phase 2's graph would
    # build without complaint and the optimizer would then report as a delivery it
    # cannot reach — far from the missing road that caused it.
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for road in roads:
        if road.from_node in adjacency and road.to_node in adjacency:
            adjacency[road.from_node].add(road.to_node)
            adjacency[road.to_node].add(road.from_node)

    if DEPOT_ID in adjacency:
        reached = {DEPOT_ID}
        frontier = [DEPOT_ID]
        while frontier:
            for neighbour in adjacency[frontier.pop()]:
                if neighbour not in reached:
                    reached.add(neighbour)
                    frontier.append(neighbour)
        orphans = sorted(node_ids - reached)
        if orphans:
            problems.append(
                f"nodes unreachable from the depot: {orphans} — no delivery there "
                f"can be routed"
            )

    return problems


def scenario_summary() -> dict[str, Any]:
    """
    Headline numbers for the scenario, for logs and for tests to assert on.

    Total demand and total capacity are included because their relationship is
    the first thing to check when a plan comes back with unassigned deliveries:
    if total demand exceeds total capacity, no plan can assign everything, and
    that is a property of the scenario rather than a solver defect.
    """
    vehicles = build_demo_vehicles()
    deliveries = build_demo_deliveries()
    nodes = build_demo_nodes()
    roads = build_demo_roads()
    return {
        "nodes": len(nodes),
        "roads": len(roads),
        "vehicles": len(vehicles),
        "deliveries": len(deliveries),
        "total_capacity_kg": round(sum(v.capacity for v in vehicles), 2),
        "total_demand_kg": round(sum(d.demand for d in deliveries), 2),
        "priorities": {
            str(p): sum(1 for d in deliveries if d.priority == p) for p in (1, 2, 3)
        },
    }
