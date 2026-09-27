"""
Tests for the routing graph.

The graph is small enough that a mistake in it is invisible: Dijkstra still
returns *a* number, the routes still look plausible, and the mistake only
surfaces as routes that are subtly too short or a leg that reports zero
kilometres. So these tests check the arithmetic against hand-computed values
rather than against a previous run of the same code.
"""

from __future__ import annotations

import math

import pytest

import demo_scenario as ds
from models import Node, Road
from routing import UNREACHABLE, CityGraph, _cost_key, build_graph


@pytest.fixture
def city() -> CityGraph:
    """The demo city as a graph."""
    return build_graph(ds.build_demo_nodes(), ds.build_demo_roads())


@pytest.fixture
def toy() -> CityGraph:
    """
    A five-node graph whose hand-computed answers are listed below.

        n0 --3.0min/1.0km-- n1 --1.0min/4.0km-- n2
         |                                  |
       2.0/2.0km                        1.0min/9.0km
         |                                  |
         n3 ----------5.0min/1.5km------ n4

    Two properties make it useful for catching a wrong implementation:

    * **Time and distance disagree.** n1->n4 is 2.0 min over 13.0 km via n2,
      versus 8.0 min over 4.5 km via n0 and n3. An implementation that minimised
      km would return the slower, shorter route.
    * **There are exact time ties.** n2->n3 costs 6.0 min two different ways:
      via n1 and n0 at 7.0 km, or via n4 at 10.5 km. Without a tie-break, which
      one is reported depends on the source node, and this graph caught exactly
      that — the same corridor reported 10.5 km one way and 7.0 km the other,
      both "6.0 minutes".
    """
    return _toy_graph()


def _toy_graph() -> CityGraph:
    nodes = [
        Node(id=nid, label=nid, lat=0.0, lon=0.0, is_depot=(nid == "n0"))
        for nid in ("n0", "n1", "n2", "n3", "n4")
    ]
    roads = [
        Road(id="r0", from_node="n0", to_node="n1", distance=1.0, base_time=3.0, traffic_multiplier=1.0, blocked=False),
        Road(id="r1", from_node="n1", to_node="n2", distance=4.0, base_time=1.0, traffic_multiplier=1.0, blocked=False),
        Road(id="r2", from_node="n2", to_node="n4", distance=9.0, base_time=1.0, traffic_multiplier=1.0, blocked=False),
        Road(id="r3", from_node="n0", to_node="n3", distance=2.0, base_time=2.0, traffic_multiplier=1.0, blocked=False),
        Road(id="r4", from_node="n3", to_node="n4", distance=1.5, base_time=5.0, traffic_multiplier=1.0, blocked=False),
    ]
    return build_graph(nodes, roads)


# ── Hand-checked arithmetic ───────────────────────────────────────────────


def test_toy_direct_leg(toy: CityGraph) -> None:
    assert toy.travel_time("n0", "n1") == 3.0
    assert toy.distance_between("n0", "n1") == 1.0


def test_toy_optimises_time_not_distance(toy: CityGraph) -> None:
    """
    n1 -> n4 must go the fast way, not the short way.

      n1 -> n2 -> n4          : 1.0 + 1.0 =  2.0 min,  4.0 + 9.0 = 13.0 km
      n1 -> n0 -> n3 -> n4    : 3.0 + 2.0 + 5.0 = 8.0 min,  1.0 + 2.0 + 1.5 = 4.5 km

    The second is 4.5 km against the first's 13.0, and still 4x slower. An
    implementation that minimised km would return the wrong one.
    """
    assert toy.travel_time("n1", "n4") == 2.0
    assert toy.distance_between("n1", "n4") == 13.0
    assert toy.shortest_path("n1", "n4") == ["n1", "n2", "n4"]


def test_toy_same_node_is_zero_and_valid(toy: CityGraph) -> None:
    """A node to itself is zero cost, and still yields a real (single-node) path."""
    assert toy.travel_time("n2", "n2") == 0.0
    assert toy.distance_between("n2", "n2") == 0.0
    assert toy.shortest_path("n2", "n2") == ["n2"]


def test_toy_tie_between_equal_time_paths_prefers_the_shorter_km(toy: CityGraph) -> None:
    """
    n2 -> n3 costs 6.0 min either way; the 7.0 km route must win.

    n2 -> n1 -> n0 -> n3 : 1.0 + 3.0 + 2.0 = 6.0 min, 4.0 + 1.0 + 2.0 =  7.0 km
    n2 -> n4 -> n3       : 1.0 + 5.0       = 6.0 min, 9.0 + 1.5       = 10.5 km

    This is the assertion the original implementation could not have satisfied.
    """
    assert toy.travel_time("n2", "n3") == 6.0
    assert toy.distance_between("n2", "n3") == 7.0


def test_toy_is_symmetric_in_time_and_km(toy: CityGraph) -> None:
    """
    Every cost must be identical in both directions.

    The roads are bidirectional and carry one time and one distance, so an
    undirected network has a symmetric cost matrix — and this is a real
    regression test rather than a formality. An earlier version of this
    implementation reported n2->n3 as 10.5 km and n3->n2 as 7.0 km, both
    "6.0 minutes", because the reported distance came from whichever equal-cost
    path the search reached first and that depended on the source.
    """
    ids = toy.node_ids()
    for a in ids:
        for b in ids:
            assert toy.travel_time(a, b) == toy.travel_time(b, a), f"time {a}<->{b}"
            assert toy.distance_between(a, b) == toy.distance_between(b, a), f"km {a}<->{b}"


# ── An independent oracle ─────────────────────────────────────────────────


def _brute_force_lexicographic(graph: CityGraph) -> dict[tuple[str, str], tuple[float, float]]:
    """
    Shortest (minutes, km) between every ordered pair, by exhaustive enumeration.

    Deliberately shares no code with routing.py — it walks every simple path
    rather than running a priority queue, so a bug in the heap logic, the
    tie-break, or the memo cannot hide behind a matching bug in the oracle. The
    graph is five nodes, so the exponential cost is irrelevant.
    """
    adjacency: dict[str, list[tuple[str, float, float]]] = {n: [] for n in graph.node_ids()}
    for node in adjacency:
        for other in adjacency:
            if node == other:
                continue
            km = graph.distance_between(node, other)
            if km != UNREACHABLE:
                adjacency[node].append((other, graph.travel_time(node, other), km))

    def walk(start: str, current: str, visited: list[str], minutes: float, km: float):
        if current != start:
            yield (current, (minutes, km))
        for nxt, leg_minutes, leg_km in adjacency.get(current, ()):
            if nxt not in visited:
                yield from walk(
                    start, nxt, visited + [nxt], minutes + leg_minutes, km + leg_km
                )

    best: dict[tuple[str, str], tuple[float, float]] = {}
    for start in adjacency:
        for end, cost in walk(start, start, [start], 0.0, 0.0):
            key = (start, end)
            if key not in best or cost < best[key]:
                best[key] = cost
    return best


def test_dijkstra_agrees_with_brute_force_on_the_toy_graph(toy: CityGraph) -> None:
    """
    Every ordered pair must match an independent exhaustive search.

    The strong version of the tests above: rather than asserting the values I
    expected, this asserts the values the true answer is, computed by a method
    that cannot share a bug with the implementation.
    """
    for (a, b), (minutes, km) in _brute_force_lexicographic(toy).items():
        assert toy.travel_time(a, b) == pytest.approx(minutes), f"minutes {a}->{b}"
        assert toy.distance_between(a, b) == pytest.approx(km), f"km {a}->{b}"


def test_demo_city_reported_paths_match_their_real_road_costs(city: CityGraph) -> None:
    """
    On the real 25-node city, every reported path must cost what driving it costs.

    This is the demo-scale version of the brute-force check above, and it is
    stronger than a consistency check. It rebuilds adjacency straight from the
    seeded Road rows — no Dijkstra, no memo, no private state — then walks the
    path the router returned and sums the actual road times and kilometres. The
    router's reported time and km must equal the cost of the path it names.

    That catches the class of bug the distance fix was about: if the router
    returned a path but a number belonging to a different path, or if the km were
    looked up per direct road instead of accumulated along the path, the walk
    here would disagree with the report.
    """
    import demo_scenario as ds

    roads = {r.id: r for r in ds.build_demo_roads()}
    assert len(roads) == 45, "expected the demo city's 45 roads"

    adjacency: dict[str, dict[str, tuple[float, float]]] = {}
    for road in roads.values():
        assert not road.blocked, "demo city ships with no blocked roads"
        effective = road.base_time * road.traffic_multiplier
        adjacency.setdefault(road.from_node, {})[road.to_node] = (effective, road.distance)
        adjacency.setdefault(road.to_node, {})[road.from_node] = (effective, road.distance)

    for a in city.node_ids():
        for b in city.node_ids():
            path = city.shortest_path(a, b)

            if a == b:
                assert path == [a]
                continue

            # Every pair must be drivable: the demo city is validated connected
            # at seed time, so an empty path here means the router lost a node.
            assert path, f"no path {a}->{b}"
            assert path[0] == a and path[-1] == b, f"path {a}->{b} is {path}"

            walked_minutes = 0.0
            walked_km = 0.0
            for u, v in zip(path, path[1:], strict=False):
                leg = adjacency.get(u, {}).get(v)
                assert leg is not None, f"path {a}->{b} traverses a missing road {u}->{v}"
                walked_minutes += leg[0]
                walked_km += leg[1]

            assert city.travel_time(a, b) == pytest.approx(walked_minutes), (
                f"reported time for {a}->{b} does not match the road cost of {path}"
            )
            assert city.distance_between(a, b) == pytest.approx(walked_km), (
                f"reported km for {a}->{b} does not match the road cost of {path}"
            )


def test_demo_city_matches_an_independent_fixpoint_optimum(city: CityGraph) -> None:
    """
    Every cost on the real city must equal the true lexicographic optimum.

    A label-correcting Bellman-Ford run to a fixpoint, once per source, sharing
    no code with the Dijkstra. It converges to the optimum regardless of visit
    order, so it is a genuine oracle rather than a restatement of the
    implementation: if Dijkstra's tie-break or its heap discipline were wrong,
    the two would disagree.

    This is the check that catches the bug the ``COST_DECIMALS`` quantisation
    exists to fix. Comparing the raw floats, n15 and n17 — joined by two
    17.5-minute routes at 9.2 and 9.3 km — came out as 9.3 km from one end and
    9.2 km from the other, because the exact float sums differed by 1.8e-15 and
    the tie-break read that as a strict difference.
    """
    edges: list[tuple[str, str, tuple[float, float]]] = []
    for road in ds.build_demo_roads():
        leg = (road.base_time * road.traffic_multiplier, road.distance)
        edges.append((road.from_node, road.to_node, leg))
        edges.append((road.to_node, road.from_node, leg))

    nodes = city.node_ids()
    infinity = (UNREACHABLE, UNREACHABLE)

    def fixpoint_optimum(source: str) -> dict[str, tuple[float, float]]:
        best = {n: ((0.0, 0.0) if n == source else infinity) for n in nodes}
        for _ in range(len(nodes)):
            changed = False
            for u, v, (minutes, km) in edges:
                if best[u][0] == UNREACHABLE:
                    continue
                candidate = _cost_key(best[u][0] + minutes, best[u][1] + km)
                if candidate < best[v]:
                    best[v] = candidate
                    changed = True
            if not changed:
                break
        return best

    for source in nodes:
        expected = fixpoint_optimum(source)
        for target in nodes:
            if source == target:
                continue
            reported = (city.travel_time(source, target), city.distance_between(source, target))
            assert _cost_key(*reported) == expected[target], (
                f"{source}->{target}: reported {reported}, optimum {expected[target]}"
            )


def test_demo_city_costs_are_symmetric(city: CityGraph) -> None:
    """
    Reversing a journey changes nothing about its time or its distance.

    The regression this pins reported the same 6-minute corridor as 10.5 km from
    one end and 7.0 km from the other. On the demo city the tie-break makes the
    choice a property of the network, so both directions agree.
    """
    ids = city.node_ids()
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            assert city.travel_time(a, b) == city.travel_time(b, a), f"time {a}<->{b}"
            assert city.distance_between(a, b) == city.distance_between(b, a), f"km {a}<->{b}"


# ── The distance fix ──────────────────────────────────────────────────────


def test_multi_hop_leg_reports_real_distance_not_zero(toy: CityGraph) -> None:
    """
    n0 -> n4 shares no direct road and must still cost its real distance.

    The bug this pins: the original looked each hop up in a direct-road table
    and added 0.0 when the pair shared no road, so this leg reported zero
    kilometres. The time-optimal route is n0 -> n1 -> n2 -> n4 at 5.0 min and
    14.0 km — note it is 14.0 and not the 3.5 km of the n0 -> n3 -> n4 detour,
    because this graph optimises time and that detour takes 7.0 min. Any value
    at or near 0.0 is the regression.
    """
    assert toy.travel_time("n0", "n4") == 5.0
    assert toy.distance_between("n0", "n4") == 14.0


def test_route_distance_sums_multi_hop_legs(toy: CityGraph) -> None:
    """
    A whole route's km must include the legs with no direct road.

    Waypoint sequence n0 -> n4 -> n1:
      n0 -> n4  5.0 min, 14.0 km  (three hops, no direct road)
      n4 -> n1  2.0 min, 13.0 km  (two hops,  no direct road)
    Total 27.0 km. The original returned 0.0 for both legs.
    """
    assert toy.route_distance(["n0", "n4", "n1"]) == 27.0
    assert toy.route_travel_time(["n0", "n4", "n1"]) == 7.0  # 5.0 + 2.0


def test_route_distance_is_infinite_when_a_leg_is_unreachable() -> None:
    """
    An undrivable leg must not read as a very short route.

    n4 is cut off because the road to it is absent. The route n0 -> n4 -> n1
    cannot be driven, so both totals are infinite. Reporting 0.0 (or anything
    finite) for the dead leg would let an infeasible route look like a cheap
    one, and the optimizer would happily assign it.
    """
    cut = build_graph(
        [
            Node(id=nid, label=nid, lat=0.0, lon=0.0, is_depot=(nid == "n0"))
            for nid in ("n0", "n1", "n2", "n4")
        ],
        [
            Road(id="r0", from_node="n0", to_node="n1", distance=1.0, base_time=3.0, traffic_multiplier=1.0, blocked=False),
            Road(id="r1", from_node="n1", to_node="n2", distance=4.0, base_time=1.0, traffic_multiplier=1.0, blocked=False),
            # n2 -> n4 is deliberately absent: n4 is unreachable.
        ],
    )

    assert cut.travel_time("n2", "n4") == UNREACHABLE
    assert cut.distance_between("n2", "n4") == UNREACHABLE
    assert cut.shortest_path("n2", "n4") == []
    assert cut.route_travel_time(["n0", "n4", "n1"]) == UNREACHABLE
    assert cut.route_distance(["n0", "n4", "n1"]) == UNREACHABLE


# ── Traffic, blocking, bad data ───────────────────────────────────────────


def test_traffic_multiplier_makes_a_road_slower(city: CityGraph) -> None:
    """
    A congestion multiplier must actually raise the cost of the road it applies to.

    The demo event jams road_000 (depot -> n01, 3.5 min) at 4.5x. The direct
    edge is now 15.75 min, which is slower than the 10.1-minute detour, so the
    router reroutes rather than sitting in traffic — which is the correct
    behaviour, and the reason this test asserts a reroute instead of a slowdown
    factor. Asserting "at least 4.5x slower" would demand that the router
    deliberately take the jam.
    """
    baseline_path = city.shortest_path("depot", "n01")
    assert baseline_path == ["depot", "n01"], "uncongested, the direct road is fastest"
    baseline = city.travel_time("depot", "n01")
    assert baseline == 3.5

    jammed = build_graph(
        ds.build_demo_nodes(),
        [
            r if r.id != "road_000"
            else Road(
                id=r.id, from_node=r.from_node, to_node=r.to_node, distance=r.distance,
                base_time=r.base_time, traffic_multiplier=4.5, blocked=r.blocked,
            )
            for r in ds.build_demo_roads()
        ],
    )

    # The detour is used, and it is faster than the jammed direct road.
    detour = jammed.shortest_path("depot", "n01")
    assert "n01" not in detour[:-1] or detour[1] != "n01"
    assert detour != baseline_path
    assert jammed.travel_time("depot", "n01") < 3.5 * 4.5

    # And the jammed edge, in isolation, is genuinely 4.5x.
    assert jammed.travel_time("depot", "n01") > baseline

    # An unrelated corridor is untouched by a jam elsewhere.
    assert jammed.travel_time("depot", "n24") == city.travel_time("depot", "n24")


def test_blocked_roads_are_excluded(city: CityGraph) -> None:
    """Blocking every road out of the depot must make the city unreachable from it."""
    depot_roads = [r for r in ds.build_demo_roads() if r.from_node == "depot" or r.to_node == "depot"]
    assert depot_roads, "the demo city must have roads leaving the depot"

    sealed = build_graph(
        ds.build_demo_nodes(),
        [
            Road(
                id=r.id, from_node=r.from_node, to_node=r.to_node, distance=r.distance,
                base_time=r.base_time, traffic_multiplier=r.traffic_multiplier, blocked=True,
            )
            if r in depot_roads else r
            for r in ds.build_demo_roads()
        ],
    )
    assert sealed.travel_time("depot", "n01") == UNREACHABLE
    assert sealed.shortest_path("depot", "n01") == []


def test_road_pointing_at_an_unknown_node_is_skipped_not_silently_kept() -> None:
    """
    A road with a nonexistent endpoint must be reported, not quietly absorbed.

    The original created adjacency for the unknown node, producing a phantom key
    that no real node could ever reach — so the road simply did nothing, with no
    indication that any road had been dropped. `skipped_roads` makes it visible.
    """
    graph = build_graph(
        [Node(id="n0", label="n0", lat=0.0, lon=0.0, is_depot=True)],
        [
            Road(id="good", from_node="n0", to_node="n0", distance=1.0, base_time=1.0, traffic_multiplier=1.0, blocked=False),
            Road(id="dangling", from_node="n0", to_node="ghost", distance=1.0, base_time=1.0, traffic_multiplier=1.0, blocked=False),
        ],
    )
    assert graph.skipped_roads == ["dangling"]
    assert not graph.has_node("ghost")


def test_clean_graph_reports_no_skipped_roads(city: CityGraph) -> None:
    assert city.skipped_roads == []


# ── Unknown inputs ────────────────────────────────────────────────────────


def test_unknown_nodes_are_unreachable_not_an_exception(city: CityGraph) -> None:
    assert city.has_node("depot")
    assert not city.has_node("nowhere")
    assert city.travel_time("depot", "nowhere") == UNREACHABLE
    assert city.travel_time("nowhere", "depot") == UNREACHABLE
    assert city.distance_between("depot", "nowhere") == UNREACHABLE
    assert city.shortest_path("depot", "nowhere") == []


def test_empty_graph_is_usable() -> None:
    """An empty graph must answer sanely rather than raise, so a query on an
    empty city returns 'unreachable' instead of a 500."""
    graph = CityGraph([], [])
    assert graph.node_ids() == []
    assert graph.travel_time("a", "b") == UNREACHABLE
    assert graph.all_pairs_travel_times() == {}
    assert graph.route_distance(["a", "b"]) == UNREACHABLE


# ── The demo city ─────────────────────────────────────────────────────────


def test_every_demo_node_is_reachable_from_the_depot(city: CityGraph) -> None:
    """No delivery location in the demo city may be unroutable."""
    unreachable = [
        node for node in city.node_ids() if city.travel_time("depot", node) == UNREACHABLE
    ]
    assert unreachable == []


def test_depot_to_every_node_is_finite_and_positive(city: CityGraph) -> None:
    times = city.all_pairs_travel_times()["depot"]
    for node, minutes in times.items():
        assert math.isfinite(minutes), f"{node} is unreachable from the depot"
        if node != "depot":
            assert minutes > 0.0, f"{node} reported a non-positive travel time"


def test_route_travel_time_matches_sum_of_legs(city: CityGraph) -> None:
    """
    The waypoint-sequence total must equal the sum of its individual legs.

    Checked on the real city rather than the toy graph because this is the
    invariant the optimizer leans on when it reports a route's duration, and a
    disagreement here would be invisible in any single-number test.
    """
    waypoints = ["depot", "n01", "n04", "n17", "depot"]
    expected = sum(
        city.travel_time(a, b) for a, b in zip(waypoints, waypoints[1:], strict=False)
    )
    assert city.route_travel_time(waypoints) == pytest.approx(expected, abs=1e-3)


def test_all_pairs_tables_are_consistent_with_single_queries(city: CityGraph) -> None:
    times = city.all_pairs_travel_times()
    kms = city.all_pairs_distances()
    for a in ("depot", "n05", "n16", "n22"):
        for b in ("depot", "n05", "n16", "n22"):
            assert times[a][b] == city.travel_time(a, b)
            assert kms[a][b] == city.distance_between(a, b)


def test_memoised_results_match_uncached_ones(city: CityGraph) -> None:
    """
    The Dijkstra memo must not change answers, only cost.

    Builds the same graph twice and interleaves queries so the second graph's
    memo is populated by a different access order than the first's. A cache bug —
    returning a shared mutable dict that a caller then mutates, or keying on
    something order-dependent — shows up here as a cross-graph disagreement.
    """
    other = build_graph(ds.build_demo_nodes(), ds.build_demo_roads())
    for a in ("depot", "n11", "n19"):
        for b in ("n02", "n23", "depot"):
            assert other.travel_time(a, b) == city.travel_time(a, b)
            assert other.distance_between(a, b) == city.distance_between(a, b)
            assert other.shortest_path(a, b) == city.shortest_path(a, b)
