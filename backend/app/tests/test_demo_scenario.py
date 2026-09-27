"""
Tests for the deterministic demo scenario and the seeding path.

The scenario is fixture data, so the risk is not that it crashes — it is that it
seeds cleanly and is subtly wrong. A misspelled node id, an unreachable node, an
event pointing at a renamed road: all of these insert without complaint and
surface two phases later as a delivery nothing can route, with the cause no
longer visible. So most of this file is about referential integrity, and the
seeding tests are about the one thing seeding must never do: overwrite.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, delete, select, update

import demo_scenario as ds
from database import get_fleet_state, has_fleet_data, seed_fleet_state
from models import Delivery, EventType, Route, Vehicle, VehicleStatus

# ── The data itself ───────────────────────────────────────────────────────


def test_scenario_is_internally_consistent() -> None:
    """
    The single most important assertion in the file.

    validate_demo_scenario() is the guard for everything that would otherwise
    fail silently, so a clean run here is what makes the rest of the port
    trustworthy. If this fails, do not "fix the test" — fix the data.
    """
    assert ds.validate_demo_scenario() == []


def test_scenario_is_deterministic() -> None:
    """
    Two independent builds of the scenario are equal.

    The module claims to be 100% deterministic, and the claim is load-bearing:
    the demo events replay identically and a test can assert on a specific
    route rather than on "some route". A single stray `random` or an unordered
    set comprehension would break that invisibly, so it is asserted rather than
    assumed.
    """
    assert ds.build_demo_nodes() == ds.build_demo_nodes()
    assert ds.build_demo_roads() == ds.build_demo_roads()
    assert ds.build_demo_vehicles() == ds.build_demo_vehicles()
    assert ds.build_demo_deliveries() == ds.build_demo_deliveries()


def test_scenario_shape_is_what_the_docs_claim() -> None:
    """
    25 nodes, 45 roads, 8 vehicles, 40 deliveries.

    These counts are quoted in the module docstring, in the README and in the
    frontend, and they are what the demo is designed around. A test that pins
    them means a change to the data has to be a deliberate edit to this line,
    not a silent drift away from three other places that say 40.
    """
    summary = ds.scenario_summary()
    assert summary["nodes"] == 25
    assert summary["roads"] == 45
    assert summary["vehicles"] == 8
    assert summary["deliveries"] == 40
    assert summary["priorities"] == {"1": 10, "2": 16, "3": 14}


def test_total_demand_fits_in_total_capacity() -> None:
    """
    Aggregate demand must be under aggregate capacity.

    Otherwise no plan can ever assign every delivery, and a plan that leaves
    some unassigned is the expected outcome rather than a solver defect. Worth
    asserting separately: a solver bug and an over-subscribed scenario look
    identical from the API.
    """
    summary = ds.scenario_summary()
    assert summary["total_demand_kg"] < summary["total_capacity_kg"]


def test_no_single_delivery_exceeds_any_vehicle() -> None:
    """
    Every individual delivery must fit in at least one vehicle.

    A 480kg order against a fleet whose largest truck is 450kg is unservable by
    construction. The optimizer would report it unassigned, which is a correct
    report of an impossible input.
    """
    largest = max(v.capacity for v in ds.build_demo_vehicles())
    too_big = [d.id for d in ds.build_demo_deliveries() if d.demand > largest]
    assert too_big == []


def test_every_node_is_reachable_from_the_depot() -> None:
    """
    No node is cut off from the network.

    Uses a breadth-first walk over the raw road list, independent of the routing
    graph that Phase 2 introduces. Two implementations that agree is stronger
    evidence than one, and until Phase 2 lands this is the only reachability
    check that exists.
    """
    adjacency: dict[str, set[str]] = {n.id: set() for n in ds.build_demo_nodes()}
    for road in ds.build_demo_roads():
        adjacency[road.from_node].add(road.to_node)
        adjacency[road.to_node].add(road.from_node)

    reached = {ds.DEPOT_ID}
    frontier = [ds.DEPOT_ID]
    while frontier:
        for neighbour in adjacency[frontier.pop()]:
            if neighbour not in reached:
                reached.add(neighbour)
                frontier.append(neighbour)

    assert set(adjacency) - reached == set()


def test_exactly_one_node_is_the_depot() -> None:
    depots = [n for n in ds.build_demo_nodes() if n.is_depot]
    assert len(depots) == 1
    assert depots[0].id == ds.DEPOT_ID


def test_vehicles_start_at_the_depot_with_no_load() -> None:
    """
    Every vehicle starts idle at the depot.

    Both halves matter. A vehicle that starts elsewhere has a leg the route
    builder does not know about; a vehicle that starts with a non-zero
    `current_load` makes its first capacity check wrong, because the optimizer
    compares route load against capacity without adding the existing load.
    """
    for vehicle in ds.build_demo_vehicles():
        assert vehicle.current_location == ds.DEPOT_ID
        assert vehicle.current_load == 0.0
        assert vehicle.status == VehicleStatus.ACTIVE


def test_roads_are_pristine_before_any_event() -> None:
    """
    Every road starts unblocked with no traffic.

    The demo events are what introduce congestion and closures, so a road that
    already carries a multiplier means "reset and replay" does not actually
    reset. A road at 4.5x from the seed would make the traffic event a no-op
    that still looked like it worked.
    """
    for road in ds.build_demo_roads():
        assert road.traffic_multiplier == 1.0
        assert road.blocked is False


def test_deliveries_start_unassigned_and_pending() -> None:
    for delivery in ds.build_demo_deliveries():
        assert delivery.assigned_vehicle is None
        assert delivery.status == "PENDING"


def test_time_windows_are_ordered_and_non_empty() -> None:
    for delivery in ds.build_demo_deliveries():
        assert delivery.time_window_end > delivery.time_window_start


# ── The demo events ───────────────────────────────────────────────────────


def test_demo_events_target_entities_that_exist() -> None:
    """
    Every demo event names a real entity of the right type.

    Asserted directly rather than only through validate_demo_scenario(), so that
    a failure points at the specific event instead of at the aggregate check.
    """
    scenario = ds.get_demo_scenario()
    road_ids = {r.id for r in scenario["roads"]}
    vehicle_ids = {v.id for v in scenario["vehicles"]}
    delivery_ids = {d.id for d in scenario["deliveries"]}
    node_ids = {n.id for n in scenario["nodes"]}

    expected: dict[EventType, set[str]] = {
        EventType.TRAFFIC_UPDATE: road_ids,
        EventType.VEHICLE_BREAKDOWN: vehicle_ids,
        EventType.TIME_WINDOW_CHANGE: delivery_ids,
    }

    for spec in scenario["events_spec"]:
        event_type = EventType(spec["event_type"])
        if event_type is EventType.NEW_DELIVERY:
            # NEW_DELIVERY creates its target, so the id must NOT exist yet, and
            # the location it creates must.
            assert spec["affected_entity_id"] not in delivery_ids
            assert spec["parameters"]["location"] in node_ids
        else:
            assert spec["affected_entity_id"] in expected[event_type]


def test_event_parameters_use_the_enum_spelling() -> None:
    """
    Every spec's event_type is a real EventType.

    These strings are compared against enum values when the Phase 6 runner
    applies them. A typo like "TRAFFIC_JAM" would pass a string comparison
    against the wrong reference and fail only when the event is actually fired.
    """
    for spec in ds.DEMO_EVENTS_SPEC:
        EventType(spec["event_type"])


# ── Seeding ───────────────────────────────────────────────────────────────


def test_seed_populates_an_empty_database(session: Session) -> None:
    assert seed_fleet_state(session) is True
    assert has_fleet_data(session) is True

    state = get_fleet_state(session)
    assert len(state.nodes) == 25
    assert len(state.roads) == 45
    assert len(state.vehicles) == 8
    assert len(state.deliveries) == 40


def test_seed_creates_one_empty_route_per_vehicle(session: Session) -> None:
    """
    Seeded routes are placeholders, and there is exactly one per vehicle.

    Route.vehicle_id is the primary key, so the 1:1 vehicle↔route invariant is
    enforced by the schema. Asserting the count matches the vehicle count is
    how a route seeded for a vehicle that no longer exists would be caught.
    """
    seed_fleet_state(session)
    state = get_fleet_state(session)

    assert len(state.routes) == len(state.vehicles) == 8
    assert {r.vehicle_id for r in state.routes} == {v.id for v in state.vehicles}
    for route in state.routes:
        assert route.delivery_ids == []
        assert route.total_distance == 0.0
        assert route.feasible is True


def test_seed_is_idempotent(session: Session) -> None:
    """
    A second seed changes nothing.

    This is what makes it safe to call on every boot. Without it, restarting the
    API would duplicate the whole city.
    """
    assert seed_fleet_state(session) is True
    before = {d.id for d in session.exec(select(Delivery)).all()}

    assert seed_fleet_state(session) is False

    after = {d.id for d in session.exec(select(Delivery)).all()}
    assert after == before
    assert len(get_fleet_state(session).deliveries) == 40


def test_seed_never_overwrites_existing_data(session: Session) -> None:
    """
    Seeding refuses to touch a fleet that already exists.

    The important property. A user experimenting with the Phase 5 event endpoints
    restarts the API, and the demo city must not silently reappear over their
    edits. This is the assertion that would have caught a `merge()`-based seed
    with the `has_fleet_data` guard removed.
    """
    seed_fleet_state(session)
    # Simulate a user edit: retire a vehicle and mark a delivery delivered.
    session.exec(delete(Vehicle).where(Vehicle.id == "v08"))
    session.exec(delete(Route).where(Route.vehicle_id == "v08"))
    session.exec(
        update(Delivery).where(Delivery.id == "d01").values(status="DELIVERED")
    )
    session.commit()

    assert seed_fleet_state(session) is False

    state = get_fleet_state(session)
    assert "v08" not in {v.id for v in state.vehicles}
    assert len(state.vehicles) == 7
    d01 = next(d for d in state.deliveries if d.id == "d01")
    assert d01.status == "DELIVERED"


def test_seed_raises_rather_than_writing_invalid_scenario(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A scenario that fails validation is refused, not seeded.

    Simulated by patching the validator to report a problem. The point is the
    control flow: `seed_fleet_state` must not reach the write. An empty database
    left empty is a recoverable state; a half-valid city is not.
    """
    monkeypatch.setattr(
        ds, "validate_demo_scenario", lambda: ["synthetic failure for the test"]
    )
    with pytest.raises(ValueError, match="synthetic failure for the test"):
        seed_fleet_state(session)
    assert has_fleet_data(session) is False
