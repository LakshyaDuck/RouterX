"""
Routing engine for the Delivery Control Tower.

A deterministic, in-memory weighted graph over the city road network. All
routing is pure Python — no external APIs, no network calls.

Core design
-----------
  * ``CityGraph`` wraps the city's Node + Road rows into an adjacency structure.
  * Effective travel time = ``base_time * traffic_multiplier``; blocked roads
    are excluded from the graph entirely.
  * Roads are bidirectional. They are stored once and traversed both ways, so
    there is no way for the two directions to drift apart.
  * Dijkstra over a binary heap gives O((V + E) log V) per source node.
  * Predecessor tracking recovers the actual path, not just its cost.
  * Results are memoised per source node, so the twenty-odd Dijkstra runs an
    optimization needs cost twenty-odd runs in total rather than one per query.

This module replaces ``distance_matrix.py``, which computed straight-line
Euclidean costs. That module's own docstring named the moment it would stop
being the right answer: "if you later want your imaginary world to have
non-trivial structure (obstacles, zones that are slower to cross, one-way
constraints) — that's the point where this stops being enough and becomes a
small custom graph you author yourself." The demo scenario is that graph: 25
explicitly placed nodes and 45 explicitly timed roads, including roads that are
short in km but slow in minutes. Straight lines cannot express a detour, and a
world where the shortest path is not the fastest one is most of what makes
routing interesting.

Ported from Routerpriv8's backend/app/routing.py. Three deliberate changes,
each because the original was wrong in a way that produced plausible numbers
rather than an error:

1. **Distance is accumulated along the time-optimal path, not looked up as a
   direct road.** The original's ``route_distance`` added
   ``self._dist_adj.get(a, {}).get(b, 0.0)`` per hop — a direct-road lookup
   that contributed **0.0 km** when the two nodes shared no road. The original
   justified this with "the planner always picks adjacent nodes so this is
   safe", and that assumption does not hold: consecutive delivery stops are
   wherever the deliveries are, and a stop at n01 followed by one at n20 shares
   no direct road. Every such leg silently reported zero, so a route's
   kilometres came out far too low — and a wrong distance is harder to notice
   than a missing one, because it still looks like a number. Distance is now
   carried through the same Dijkstra that decides the path, which also removes
   the second adjacency structure the original kept for it: the km reported are
   necessarily the km of the path the vehicle will actually drive.

2. **An unreachable leg reports ``inf``, not 0.0.** Related to the above, and
   the same reasoning as ``route_travel_time``: a route that cannot be driven
   has no meaningful kilometre count, and reporting 0.0 let an infeasible route
   look like a very short one. Callers use this to mark the route infeasible.

3. **Dijkstra results are memoised per source node.** The original re-ran a
   full Dijkstra inside ``travel_time`` on every call, and
   ``route_travel_time`` calls it once per hop — so one route cost
   O(stops x E log V) and the optimizer, which asks the same question
   thousands of times over the same graph, paid that repeatedly. It also
   computed ``all_pairs_travel_times()`` and then did not use it for this.

Public API
----------
  ``CityGraph(nodes, roads)``            construct the graph
  ``.shortest_path(start, end)``         node IDs along the fastest path, [] if unreachable
  ``.travel_time(start, end)``           effective minutes, ``inf`` if unreachable
  ``.route_distance(waypoints)``         total km driven along the chosen paths, ``inf`` if any leg is unreachable
  ``.route_travel_time(waypoints)``      total effective minutes, ``inf`` if any leg is unreachable
  ``.all_pairs_travel_times()``          ``{from: {to: minutes}}``
  ``.all_pairs_distances()``             ``{from: {to: km}}``
  ``.has_node(node_id)``                 membership test
"""

import heapq
import math
from dataclasses import dataclass

from models import Node, Road

# Sentinel for "there is no path". A large finite float rather than None so it
# survives arithmetic and comparisons; inf is clearer at every use site and the
# values here are minutes and kilometres in the hundreds.
UNREACHABLE = math.inf

# Decimal places that cost comparisons are quantised to before being compared.
#
# This is load-bearing, not tidiness. Accumulating road times as floats is not
# associative, so two routes that are *mathematically* the same duration differ
# in the last bits: 13.9 arrived at as 13.899999999999999 one way and 13.9 the
# other. Comparing those exactly makes a tie look like a 1.8e-15 win for
# whichever path happened to accumulate in the unlucky order, and that silently
# disarms the km tie-break below — in the demo city, n15 and n17 are connected
# by two 17.5-minute routes, and float noise made the 9.3 km one win from one
# end and the 9.2 km one from the other.
#
# Nine places is far below the 0.1-minute granularity of the road data and far
# above double-precision noise at these magnitudes, so it can only ever merge
# costs that are genuinely equal. It is applied to the comparison key rather
# than to the stored value's derivation, so it cannot make a slower route win.
COST_DECIMALS = 9


def _cost_key(minutes: float, km: float) -> tuple[float, float]:
    """
    The lexicographic comparison key: quantised ``(minutes, km)``.

    Time first, and among routes of exactly equal duration, the shorter in km.
    Both components are quantised so that float accumulation order cannot
    masquerade as a real difference.
    """
    return (round(minutes, COST_DECIMALS), round(km, COST_DECIMALS))


@dataclass(frozen=True)
class _Edge:
    """One directed edge."""

    to: str
    time: float  # effective travel time in minutes (base_time * traffic_multiplier)
    km: float  # distance in km


class CityGraph:
    """
    Weighted directed graph over city nodes and roads.

    Treat as immutable after construction — the Dijkstra memo assumes the edge
    set does not change underneath it. Rebuild the graph when roads change
    rather than mutating one; the event engine in Phase 5 does exactly that, and
    rebuilding 25 nodes is free.
    """

    def __init__(self, nodes: list[Node], roads: list[Road]) -> None:
        self._nodes: set[str] = {n.id for n in nodes}
        self._adj: dict[str, list[_Edge]] = {n.id: [] for n in nodes}
        # node id -> (times, kms, prev) for the time-optimal tree rooted there.
        # The kms are those of the time-optimal path, not of a
        # distance-optimal path — see the module docstring.
        self._memo: dict[str, tuple[dict[str, float], dict[str, float], dict[str, str | None]]] = {}

        dangling: list[str] = []
        for road in roads:
            if road.blocked:
                continue  # Blocked roads are not traversable.
            if road.from_node not in self._nodes or road.to_node not in self._nodes:
                # A road pointing at a node that does not exist is bad data, and
                # silently inventing adjacency for the unknown endpoint would
                # hide it: the phantom key is unreachable from any real node, so
                # the road would just quietly do nothing. demo_scenario's
                # validator rejects this before seeding, so reaching here means
                # the data changed by another route.
                dangling.append(road.id)
                continue

            effective_time = road.base_time * road.traffic_multiplier
            # Roads are bidirectional — add both directions from one stored row.
            self._adj[road.from_node].append(_Edge(road.to_node, effective_time, road.distance))
            self._adj[road.to_node].append(_Edge(road.from_node, effective_time, road.distance))

        if dangling:
            # Not fatal: the graph is still usable for every valid road, and
            # failing the whole boot over one bad row would be worse. Surfaced
            # because a silently-ignored road is exactly the kind of thing that
            # becomes a mystery an hour later.
            self.skipped_roads = sorted(dangling)
        else:
            self.skipped_roads = []

    # ------------------------------------------------------------------
    # Dijkstra
    # ------------------------------------------------------------------

    def _dijkstra(
        self, start: str
    ) -> tuple[dict[str, float], dict[str, float], dict[str, str | None]]:
        """
        Single-source min-heap Dijkstra from ``start``, memoised.

        Returns ``(times, kms, prev)``:

          * ``times[node]`` — minimum effective minutes to reach the node
          * ``kms[node]``   — km along that time-optimal path
          * ``prev[node]``  — predecessor, for path reconstruction

        The objective is lexicographic: minimise **time first**, and among paths
        that are exactly equal in time, take the shortest in km.

        The tie-break is not decoration. A road network with symmetric
        alternatives routinely has several paths of identical duration — around
        a block, in either direction of a ring road. Without a tie-break, the km
        reported depends on which equal-cost path the search happened to relax
        first, which depends on the source node. Comparing ``(time, km)`` pairs
        makes the choice a property of the network rather than of the traversal.

        Comparisons run on ``_cost_key``, which quantises both components. Doing
        it any other way does not work: the exact floats of two equal-duration
        routes differ in their last bits, so a raw ``<`` treats a float artefact
        as a strict win and the tie-break never gets a chance to run. That is
        not hypothetical — it is what made n15 and n17 report different
        distances depending on which end you started from. See ``COST_DECIMALS``.

        Precondition: every edge must have strictly positive time. The argument
        above needs every path reaching time T to have all proper prefixes at
        time < T, so each equal-time candidate is in the heap before anything at
        time T is settled. A zero-time edge breaks that and the tie-break becomes
        traversal-order dependent again. demo_scenario.validate_demo_scenario
        rejects non-positive base_time, so the seeded city satisfies this; a
        road arriving by any other path is the exposure.

        ``times`` is still the true minimum-travel-time table — the km component
        only decides between paths that tie on time, so it cannot make a slower
        route win.
        """
        cached = self._memo.get(start)
        if cached is not None:
            return cached

        if start not in self._nodes:
            empty: tuple[dict[str, float], dict[str, float], dict[str, str | None]] = (
                {},
                {},
                {},
            )
            self._memo[start] = empty
            return empty

        # best[node] = quantised (minutes, km) of the best route found so far.
        # Quantised, because that is the value the comparisons below use.
        best: dict[str, tuple[float, float]] = {start: (0.0, 0.0)}
        # Accumulated, unrounded cost kept alongside, so the value handed back to
        # callers is the real sum of the real roads rather than a comparison key.
        actual: dict[str, tuple[float, float]] = {start: (0.0, 0.0)}
        prev: dict[str, str | None] = {start: None}
        unreachable_cost = (UNREACHABLE, UNREACHABLE)

        # Heap entries are (key_minutes, key_km, node_id). Carrying the node id
        # keeps the ordering total, so equal-cost entries never depend on
        # insertion order.
        heap: list[tuple[float, float, str]] = [(0.0, 0.0, start)]

        while heap:
            key_minutes, key_km, node = heapq.heappop(heap)
            if (key_minutes, key_km) > best.get(node, unreachable_cost):
                continue  # Stale entry superseded by a cheaper route.

            for edge in self._adj.get(node, ()):
                raw = actual[node]
                candidate = _cost_key(raw[0] + edge.time, raw[1] + edge.km)
                if candidate < best.get(edge.to, unreachable_cost):
                    best[edge.to] = candidate
                    actual[edge.to] = (raw[0] + edge.time, raw[1] + edge.km)
                    prev[edge.to] = node
                    heapq.heappush(heap, (candidate[0], candidate[1], edge.to))

        times = {node: cost[0] for node, cost in actual.items()}
        kms = {node: cost[1] for node, cost in actual.items()}
        result = (times, kms, prev)
        self._memo[start] = result
        return result

    def _reconstruct_path(self, prev: dict[str, str | None], end: str) -> list[str]:
        """Walk the predecessor map backward from ``end``."""
        if end not in prev:
            return []  # Unreachable.
        path: list[str] = []
        current: str | None = end
        while current is not None:
            path.append(current)
            current = prev.get(current)
        path.reverse()
        return path

    # ------------------------------------------------------------------
    # Public routing functions
    # ------------------------------------------------------------------

    def shortest_path(self, start: str, end: str) -> list[str]:
        """
        Ordered node IDs of the fastest path from ``start`` to ``end``.

        Returns ``[]`` if either node is unknown or no path exists (a
        disconnected graph, or every road out of the region is blocked).
        """
        if start not in self._nodes or end not in self._nodes:
            return []
        if start == end:
            return [start]
        return self._reconstruct_path(self._dijkstra(start)[2], end)

    def travel_time(self, start: str, end: str) -> float:
        """
        Effective minutes from ``start`` to ``end``; ``inf`` if unreachable.

        Rounded to 3 decimals so the answer is symmetric. Without it, the same
        journey reported 12.700000000000001 minutes from the depot and 12.7 from
        the other end, because float addition is not associative and the two
        searches accumulate the same path's legs in opposite order. The path
        was the same one; only the last bit of the mantissa moved. Rounding is
        applied here at the reporting boundary rather than inside the search,
        so it cannot alter which path is chosen or make two genuinely different
        routes compare equal.
        """
        if start not in self._nodes or end not in self._nodes:
            return UNREACHABLE
        if start == end:
            return 0.0
        return round(self._dijkstra(start)[0].get(end, UNREACHABLE), 3)

    def distance_between(self, start: str, end: str) -> float:
        """
        Km along the fastest path from ``start`` to ``end``; ``inf`` if unreachable.

        Named distinctly from ``route_distance`` because this is a single leg
        and that is a whole waypoint sequence — the two are easy to confuse at a
        call site and the mistake would not raise.

        Rounded for the same reason as ``travel_time``: the reverse direction
        accumulates the same legs in reverse order, and unrounded that showed up
        as 6.7 against 6.699999999999999.
        """
        if start not in self._nodes or end not in self._nodes:
            return UNREACHABLE
        if start == end:
            return 0.0
        return round(self._dijkstra(start)[1].get(end, UNREACHABLE), 3)

    def route_distance(self, ordered_node_ids: list[str]) -> float:
        """
        Total km for a waypoint sequence, traversed in order.

        Each hop is measured along the fastest path between that pair, so a hop
        with no direct road still costs the real distance to get there.

        Returns ``inf`` if any single hop is unreachable, because a route with
        an undrivable leg is not a short route — it is not a route.
        """
        total = 0.0
        for a, b in zip(ordered_node_ids, ordered_node_ids[1:], strict=False):
            leg = self.distance_between(a, b)
            if leg == UNREACHABLE:
                return UNREACHABLE
            total += leg
        return round(total, 3)

    def route_travel_time(self, ordered_node_ids: list[str]) -> float:
        """
        Total effective minutes for a waypoint sequence.

        Each hop is routed as a full shortest path, so multi-hop legs between
        stops that share no direct road are accounted for. Returns ``inf`` if
        any leg is unreachable.
        """
        total = 0.0
        for a, b in zip(ordered_node_ids, ordered_node_ids[1:], strict=False):
            leg = self.travel_time(a, b)
            if leg == UNREACHABLE:
                return UNREACHABLE
            total += leg
        return round(total, 3)

    def all_pairs_travel_times(self) -> dict[str, dict[str, float]]:
        """
        The all-pairs shortest-time table: ``{from: {to: minutes}}``.

        Reaches the memo, so calling this first makes every later single query
        free. Unreachable pairs are omitted rather than included as ``inf``, so
        iterate with ``.get(to, UNREACHABLE)``.

        Rounded to match ``travel_time`` exactly. These tables are what the
        optimizer will read thousands of times, and a caller comparing a table
        entry against the single-query answer must not have to care that one is
        rounded and the other is not.
        """
        return {
            node: {other: round(minutes, 3) for other, minutes in self._dijkstra(node)[0].items()}
            for node in self._nodes
        }

    def all_pairs_distances(self) -> dict[str, dict[str, float]]:
        """
        The all-pairs distance table: ``{from: {to: km}}``, along fastest paths.

        Same omission rule and same rounding as ``all_pairs_travel_times``.
        """
        return {
            node: {other: round(km, 3) for other, km in self._dijkstra(node)[1].items()}
            for node in self._nodes
        }

    def has_node(self, node_id: str) -> bool:
        """True if ``node_id`` exists in the graph."""
        return node_id in self._nodes

    def node_ids(self) -> list[str]:
        """All node ids, sorted, so callers get a stable iteration order."""
        return sorted(self._nodes)


def build_graph(nodes: list[Node], roads: list[Road]) -> CityGraph:
    """Construct a ``CityGraph`` from SQLModel Node and Road objects."""
    return CityGraph(nodes, roads)
