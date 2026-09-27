"""
The database -> routing seam, tested against a real database.

``test_routing.py`` proves the router is correct by handing it in-memory Node
and Road objects. This file covers the one thing that cannot be proved that way:
that the graph the *application* builds is the graph the tests reasoned about.
Those diverge easily and silently — a column populated with something other than
a distance still yields a graph that answers queries, just wrongly.
"""

import pytest

from database import build_city_graph, get_fleet_state, seed_fleet_state
from models import Road


def test_seam_builds_a_fully_connected_graph_from_seeded_rows(session) -> None:
    """The graph built from seeded rows must be the demo city, fully connected."""
    seed_fleet_state(session)
    graph = build_city_graph(get_fleet_state(session))

    assert len(graph.node_ids()) == 25
    assert graph.has_node("depot")

    ids = graph.node_ids()
    for a in ids:
        for b in ids:
            if a != b:
                assert graph.travel_time(a, b) < float("inf"), f"{b} unreachable from {a}"


def test_seam_reads_real_column_values_not_just_presence(session) -> None:
    """
    The graph must carry the distances and times actually stored in the rows.

    A guard for the bug this seam invites: if ``distance`` or ``base_time`` were
    read from the wrong attribute, or scaled, every query would still return a
    finite plausible number and nothing would look wrong. So compare against the
    row values rather than a hand-written constant.
    """
    seed_fleet_state(session)
    state = get_fleet_state(session)
    graph = build_city_graph(state)

    direct = next(r for r in state.roads if r.id == "road_000")  # depot -> n01

    assert graph.travel_time("depot", "n01") == pytest.approx(
        direct.base_time * direct.traffic_multiplier
    )
    assert graph.distance_between("depot", "n01") == pytest.approx(direct.distance)
    # And the multiplier is actually part of the cost, not dropped on the floor.
    assert graph.travel_time("depot", "n01") == pytest.approx(3.5)


def test_seam_reflects_a_blocked_road_on_rebuild(session) -> None:
    """
    Blocking the depot's fastest road must force a slower detour.

    Confirms the graph is built from current row values, so a blocked road needs
    no cache-invalidation step — rebuilding the graph *is* the invalidation. This
    is the property the event engine will depend on, and it is also the sharpest
    available check that the graph is not silently ignoring the ``blocked``
    column.

    Worth being precise about what the correct answer is here. The obvious
    expectation, "the depot is cut off", is wrong: the depot has several roads,
    so blocking one only lengthens the trip. The depot -> n01 leg is a 3.5-minute
    direct road; blocked, the router takes a 10.1-minute detour and still gets
    there. A test asserting ``inf`` would be asserting that the city is
    disconnected, which it is not — and it would fail for the right reason while
    looking like the graph had a bug.
    """
    seed_fleet_state(session)
    state = get_fleet_state(session)
    open_graph = build_city_graph(state)
    assert open_graph.travel_time("depot", "n01") == pytest.approx(3.5)
    assert open_graph.shortest_path("depot", "n01") == ["depot", "n01"]

    state.roads = [
        Road(
            id=r.id,
            from_node=r.from_node,
            to_node=r.to_node,
            distance=r.distance,
            base_time=r.base_time,
            traffic_multiplier=r.traffic_multiplier,
            blocked=r.id == "road_000",
        )
        for r in state.roads
    ]

    blocked_graph = build_city_graph(state)
    detour = blocked_graph.shortest_path("depot", "n01")

    # Still reachable, but no longer by the direct road, and strictly slower.
    assert detour != ["depot", "n01"]
    assert blocked_graph.travel_time("depot", "n01") > 3.5
    assert blocked_graph.distance_between("depot", "n01") > open_graph.distance_between("depot", "n01")


def test_seam_reports_infinity_when_a_road_is_genuinely_cut(session) -> None:
    """
    Sealing the depot off from every road must yield ``inf``, not a cheap trip.

    The counterpart to the detour above, and the case that actually matters for
    correctness: an undrivable leg must be unmistakably infeasible. If it read as
    0.0 or a small finite number, the optimizer would rank an impossible route
    as the best one available.
    """
    seed_fleet_state(session)
    state = get_fleet_state(session)

    state.roads = [
        Road(
            id=r.id,
            from_node=r.from_node,
            to_node=r.to_node,
            distance=r.distance,
            base_time=r.base_time,
            traffic_multiplier=r.traffic_multiplier,
            blocked=(r.from_node == "depot" or r.to_node == "depot"),
        )
        for r in state.roads
    ]

    sealed = build_city_graph(state)
    assert sealed.travel_time("depot", "n01") == float("inf")
    assert sealed.distance_between("depot", "n01") == float("inf")
    assert sealed.shortest_path("depot", "n01") == []
    assert sealed.route_travel_time(["depot", "n01"]) == float("inf")
    assert sealed.route_distance(["depot", "n01"]) == float("inf")
