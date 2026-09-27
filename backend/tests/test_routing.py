"""
Automated test suite for the CityGraph routing engine.

Run with:
    cd backend
    python -m pytest tests/ -v

Tests cover:
  1. Shortest path — basic reachability and correct node order
  2. Blocked road — blocked edges are not traversed
  3. Traffic multiplier — higher multiplier increases effective travel time
  4. Invalid node — unknown node IDs return safe fallback values
  5. route_distance — km sum along a waypoint sequence
  6. route_travel_time — minute sum, detects infeasible routes
  7. Same-node query — start == end edge case
  8. All-pairs table — APSP consistency check
"""

import math
import pytest

from app.routing import CityGraph, build_graph
from app.models import Node, Road


# ---------------------------------------------------------------------------
# Fixtures: minimal deterministic test graphs
# ---------------------------------------------------------------------------

def _node(id_: str, lat: float = 0.0, lon: float = 0.0) -> Node:
    return Node(id=id_, label=id_, lat=lat, lon=lon, is_depot=(id_ == "depot"))


def _road(id_: str, frm: str, to: str, dist: float, base: float,
          mult: float = 1.0, blocked: bool = False) -> Road:
    return Road(
        id=id_,
        from_node=frm, to_node=to,
        distance=dist, base_time=base,
        traffic_multiplier=mult, blocked=blocked
    )


@pytest.fixture
def linear_graph() -> CityGraph:
    """
    Simple linear graph:
        A --5min,1km-- B --10min,2km-- C
    No traffic, no blocks.
    """
    nodes = [_node("A"), _node("B"), _node("C")]
    roads = [
        _road("r1", "A", "B", dist=1.0, base=5.0),
        _road("r2", "B", "C", dist=2.0, base=10.0),
    ]
    return build_graph(nodes, roads)


@pytest.fixture
def branched_graph() -> CityGraph:
    """
    Branched graph with two routes from A to C:
        A --5min-- B --5min-- C    (total 10 min, direct path)
        A --3min-- D --15min-- C   (total 18 min, longer path)
    Dijkstra should prefer A→B→C.
    """
    nodes = [_node("A"), _node("B"), _node("C"), _node("D")]
    roads = [
        _road("r1", "A", "B", dist=1.0, base=5.0),
        _road("r2", "B", "C", dist=1.0, base=5.0),
        _road("r3", "A", "D", dist=0.5, base=3.0),
        _road("r4", "D", "C", dist=3.0, base=15.0),
    ]
    return build_graph(nodes, roads)


@pytest.fixture
def traffic_graph() -> CityGraph:
    """
    Two parallel routes:
        A --base=10, mult=1.0-- B    (eff=10 min)
        A --base=6,  mult=3.0-- C --base=1, mult=1.0-- B   (eff=19 min)
    Direct A→B is faster even though base is 10.
    """
    nodes = [_node("A"), _node("B"), _node("C")]
    roads = [
        _road("r1", "A", "B", dist=2.0, base=10.0, mult=1.0),  # eff=10
        _road("r2", "A", "C", dist=1.0, base=6.0,  mult=3.0),  # eff=18
        _road("r3", "C", "B", dist=0.5, base=1.0,  mult=1.0),  # eff=1
    ]
    return build_graph(nodes, roads)


@pytest.fixture
def blocked_graph() -> CityGraph:
    """
    A --[BLOCKED]-- B --10min-- C
    A ---20min----- C          (alternative exists)
    """
    nodes = [_node("A"), _node("B"), _node("C")]
    roads = [
        _road("r1", "A", "B", dist=1.0, base=5.0,  blocked=True),   # blocked
        _road("r2", "B", "C", dist=2.0, base=10.0),
        _road("r3", "A", "C", dist=3.0, base=20.0),
    ]
    return build_graph(nodes, roads)


@pytest.fixture
def island_graph() -> CityGraph:
    """
    A --5min-- B     [disconnected]     C --5min-- D
    A and B cannot reach C or D.
    """
    nodes = [_node("A"), _node("B"), _node("C"), _node("D")]
    roads = [
        _road("r1", "A", "B", dist=1.0, base=5.0),
        _road("r2", "C", "D", dist=1.0, base=5.0),
    ]
    return build_graph(nodes, roads)


# ---------------------------------------------------------------------------
# 1. Shortest path — basic reachability and node order
# ---------------------------------------------------------------------------

class TestShortestPath:

    def test_direct_path(self, linear_graph):
        """A→B should return exactly [A, B]."""
        assert linear_graph.shortest_path("A", "B") == ["A", "B"]

    def test_two_hop_path(self, linear_graph):
        """A→C requires going through B."""
        assert linear_graph.shortest_path("A", "C") == ["A", "B", "C"]

    def test_reverse_path(self, linear_graph):
        """Roads are bidirectional; C→A must also work."""
        assert linear_graph.shortest_path("C", "A") == ["C", "B", "A"]

    def test_dijkstra_picks_fastest_route(self, branched_graph):
        """With two routes to C, Dijkstra must pick A→B→C (10 min) over A→D→C (18 min)."""
        path = branched_graph.shortest_path("A", "C")
        assert path == ["A", "B", "C"]

    def test_same_node_returns_singleton(self, linear_graph):
        """Start == end should return [node] immediately."""
        assert linear_graph.shortest_path("B", "B") == ["B"]

    def test_path_starts_and_ends_correctly(self, branched_graph):
        path = branched_graph.shortest_path("A", "C")
        assert path[0] == "A"
        assert path[-1] == "C"

    def test_disconnected_nodes_return_empty(self, island_graph):
        """A cannot reach C in an island graph."""
        assert island_graph.shortest_path("A", "C") == []

    def test_disconnected_nodes_return_empty_reverse(self, island_graph):
        """C cannot reach A either."""
        assert island_graph.shortest_path("C", "A") == []


# ---------------------------------------------------------------------------
# 2. Blocked road
# ---------------------------------------------------------------------------

class TestBlockedRoad:

    def test_blocked_road_uses_alternate(self, blocked_graph):
        """A→B is blocked; path A→C should go directly (r3)."""
        path = blocked_graph.shortest_path("A", "C")
        assert "B" not in path, "Should not route through blocked node B"
        assert path == ["A", "C"]

    def test_blocked_road_b_to_c_still_works(self, blocked_graph):
        """B→C is not blocked; B can still reach C."""
        path = blocked_graph.shortest_path("B", "C")
        assert path == ["B", "C"]

    def test_fully_blocked_path_returns_empty(self):
        """If the only road is blocked, nodes are unreachable."""
        nodes = [_node("X"), _node("Y")]
        roads = [_road("r1", "X", "Y", dist=1.0, base=5.0, blocked=True)]
        graph = build_graph(nodes, roads)
        assert graph.shortest_path("X", "Y") == []

    def test_travel_time_through_blocked_road_is_inf(self):
        """travel_time must return inf when no path exists after blocking."""
        nodes = [_node("X"), _node("Y")]
        roads = [_road("r1", "X", "Y", dist=1.0, base=5.0, blocked=True)]
        graph = build_graph(nodes, roads)
        assert graph.travel_time("X", "Y") == math.inf

    def test_blocked_road_not_in_adjacency(self):
        """Blocked road should never appear in any shortest path."""
        blocked_graph_local = build_graph(
            [_node("A"), _node("B"), _node("C")],
            [
                _road("rb", "A", "B", dist=0.5, base=1.0, blocked=True),
                _road("r2", "A", "C", dist=2.0, base=20.0),
                _road("r3", "C", "B", dist=1.0, base=5.0),
            ]
        )
        path = blocked_graph_local.shortest_path("A", "B")
        # Path must go A→C→B since A→B is blocked
        assert path == ["A", "C", "B"]


# ---------------------------------------------------------------------------
# 3. Traffic multiplier
# ---------------------------------------------------------------------------

class TestTrafficMultiplier:

    def test_effective_time_equals_base_times_multiplier(self):
        """
        Single road with base_time=10, mult=1.5 → eff_time=15.
        """
        nodes = [_node("P"), _node("Q")]
        roads = [_road("r1", "P", "Q", dist=1.0, base=10.0, mult=1.5)]
        graph = build_graph(nodes, roads)
        assert math.isclose(graph.travel_time("P", "Q"), 15.0, rel_tol=1e-6)

    def test_multiplier_of_one_equals_base(self):
        """mult=1.0 should not change base_time."""
        nodes = [_node("P"), _node("Q")]
        roads = [_road("r1", "P", "Q", dist=1.0, base=8.0, mult=1.0)]
        graph = build_graph(nodes, roads)
        assert math.isclose(graph.travel_time("P", "Q"), 8.0, rel_tol=1e-6)

    def test_high_multiplier_road_avoided(self, traffic_graph):
        """
        A→B (eff=10) vs A→C→B (eff=19).
        Dijkstra should always prefer the direct A→B edge.
        """
        assert traffic_graph.shortest_path("A", "B") == ["A", "B"]
        assert math.isclose(traffic_graph.travel_time("A", "B"), 10.0, rel_tol=1e-6)

    def test_high_traffic_slower_than_low_traffic(self):
        """Same distance, different multipliers — higher mult = slower."""
        nodes = [_node("S"), _node("T")]
        road_slow = _road("rs", "S", "T", dist=1.0, base=5.0, mult=2.0)  # eff=10
        road_fast = _road("rf", "S", "T", dist=1.0, base=5.0, mult=1.0)  # eff=5
        g_slow = build_graph(nodes, [road_slow])
        g_fast = build_graph(nodes, [road_fast])
        assert g_slow.travel_time("S", "T") > g_fast.travel_time("S", "T")

    def test_multiplier_zero_point_nine(self):
        """
        A fractional multiplier < 1.0 means lighter traffic (uncommon but valid).
        base=10, mult=0.9 → eff=9.
        """
        nodes = [_node("X"), _node("Y")]
        roads = [_road("r1", "X", "Y", dist=1.0, base=10.0, mult=0.9)]
        graph = build_graph(nodes, roads)
        assert math.isclose(graph.travel_time("X", "Y"), 9.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 4. Invalid node
# ---------------------------------------------------------------------------

class TestInvalidNode:

    def test_unknown_start_returns_empty_path(self, linear_graph):
        assert linear_graph.shortest_path("DOES_NOT_EXIST", "A") == []

    def test_unknown_end_returns_empty_path(self, linear_graph):
        assert linear_graph.shortest_path("A", "DOES_NOT_EXIST") == []

    def test_both_unknown_returns_empty_path(self, linear_graph):
        assert linear_graph.shortest_path("X99", "Y99") == []

    def test_unknown_start_travel_time_is_inf(self, linear_graph):
        assert linear_graph.travel_time("GHOST", "A") == math.inf

    def test_unknown_end_travel_time_is_inf(self, linear_graph):
        assert linear_graph.travel_time("A", "GHOST") == math.inf

    def test_has_node_false_for_unknown(self, linear_graph):
        assert not linear_graph.has_node("NOWHERE")

    def test_has_node_true_for_known(self, linear_graph):
        assert linear_graph.has_node("A")


# ---------------------------------------------------------------------------
# 5. route_distance
# ---------------------------------------------------------------------------

class TestRouteDistance:

    def test_two_node_route(self, linear_graph):
        """A→B has distance 1.0 km."""
        assert math.isclose(linear_graph.route_distance(["A", "B"]), 1.0, rel_tol=1e-6)

    def test_three_node_route(self, linear_graph):
        """A→B→C: 1.0 + 2.0 = 3.0 km."""
        assert math.isclose(linear_graph.route_distance(["A", "B", "C"]), 3.0, rel_tol=1e-6)

    def test_single_node_route_zero(self, linear_graph):
        """Single waypoint → 0 km."""
        assert linear_graph.route_distance(["A"]) == 0.0

    def test_empty_route_zero(self, linear_graph):
        assert linear_graph.route_distance([]) == 0.0


# ---------------------------------------------------------------------------
# 6. route_travel_time
# ---------------------------------------------------------------------------

class TestRouteTravelTime:

    def test_two_node_route(self, linear_graph):
        """A→B: 5 min effective."""
        assert math.isclose(linear_graph.route_travel_time(["A", "B"]), 5.0, rel_tol=1e-6)

    def test_three_node_route(self, linear_graph):
        """A→B→C: 5 + 10 = 15 min."""
        assert math.isclose(linear_graph.route_travel_time(["A", "B", "C"]), 15.0, rel_tol=1e-6)

    def test_infeasible_route_returns_inf(self, island_graph):
        """A→C is disconnected; route A→B→C→D must be infeasible."""
        t = island_graph.route_travel_time(["A", "B", "C", "D"])
        assert t == math.inf

    def test_single_node_is_zero(self, linear_graph):
        assert linear_graph.route_travel_time(["A"]) == 0.0


# ---------------------------------------------------------------------------
# 7. All-pairs shortest paths consistency
# ---------------------------------------------------------------------------

class TestAllPairs:

    def test_apsp_includes_all_nodes(self, linear_graph):
        apsp = linear_graph.all_pairs_travel_times()
        assert "A" in apsp
        assert "B" in apsp
        assert "C" in apsp

    def test_apsp_self_distance_zero(self, linear_graph):
        apsp = linear_graph.all_pairs_travel_times()
        for n in ["A", "B", "C"]:
            assert apsp[n].get(n, 0.0) == 0.0

    def test_apsp_matches_travel_time(self, branched_graph):
        """APSP table should agree with individual travel_time() calls."""
        apsp = branched_graph.all_pairs_travel_times()
        for src in ["A", "B", "C", "D"]:
            for dst in ["A", "B", "C", "D"]:
                expected = branched_graph.travel_time(src, dst)
                got = apsp.get(src, {}).get(dst, math.inf)
                assert math.isclose(expected, got, rel_tol=1e-6), \
                    f"APSP[{src}][{dst}]={got} but travel_time()={expected}"


# ---------------------------------------------------------------------------
# 8. Integration: city data smoke test
# ---------------------------------------------------------------------------

class TestCityDataIntegration:
    """
    Verify the routing engine works correctly with the actual city dataset
    (25 nodes, 45 roads, fixed seed=42).
    """

    @pytest.fixture(scope="class")
    @classmethod
    def city_graph(cls):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from simulation.city_data import generate_city_data
        # Build Node + Road objects from city data
        from app.models import Node as N, Road as R
        city = generate_city_data()
        nodes = [N(**n) for n in city["nodes"]]
        roads = [R(**r) for r in city["roads"]]
        return build_graph(nodes, roads)

    def test_all_nodes_reachable_from_depot(self, city_graph):
        """Every node in the city must be reachable from the depot."""
        apsp = city_graph.all_pairs_travel_times()
        depot_times = apsp.get("depot", {})
        assert len(depot_times) > 0, "Depot has no outgoing paths"
        unreachable = [nid for nid in city_graph._nodes
                       if nid != "depot" and depot_times.get(nid, math.inf) == math.inf]
        assert unreachable == [], f"Nodes unreachable from depot: {unreachable}"

    def test_depot_to_depot_zero(self, city_graph):
        assert city_graph.travel_time("depot", "depot") == 0.0

    def test_path_to_self_is_singleton(self, city_graph):
        for nid in list(city_graph._nodes)[:5]:
            assert city_graph.shortest_path(nid, nid) == [nid]

    def test_nonexistent_node_safe(self, city_graph):
        assert city_graph.shortest_path("depot", "PHANTOM") == []
        assert city_graph.travel_time("depot", "PHANTOM") == math.inf
