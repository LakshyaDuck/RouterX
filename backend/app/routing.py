"""
Routing engine for the Delivery Control Tower.

Provides a deterministic, in-memory weighted-graph over the city road network.
All routing is pure Python — no external APIs.

Core design:
  - CityGraph wraps the city's Node + Road data into an adjacency structure.
  - Effective travel time = base_time * traffic_multiplier  (blocked roads excluded).
  - Dijkstra with a binary heap (heapq) gives O((V+E) log V) performance.
  - Predecessor tracking lets us reconstruct the actual path, not just the cost.
  - A "distance graph" is also maintained separately so we can sum km along a path.

Public API
----------
  CityGraph(nodes, roads)                  – construct the graph
  .shortest_path(start, end)               – list of node IDs, or [] if unreachable
  .travel_time(start, end)                 – effective minutes, or inf
  .route_distance(ordered_node_ids)        – total km along a waypoint sequence
  .route_travel_time(ordered_node_ids)     – total effective minutes along a waypoint sequence
  .all_pairs_travel_times()               – {from: {to: minutes}} pre-computed APSP table
"""

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

from app.models import Node, Road


# ---------------------------------------------------------------------------
# Internal graph types
# ---------------------------------------------------------------------------

@dataclass
class _Edge:
    """One directed edge in the graph."""
    to: str
    time: float      # effective travel time in minutes  (base_time * multiplier)
    distance: float  # km


# ---------------------------------------------------------------------------
# CityGraph
# ---------------------------------------------------------------------------

class CityGraph:
    """
    Weighted directed graph over city nodes and roads.

    Both the time graph (for routing decisions) and the distance graph
    (for reporting km) are stored as adjacency dicts so we can compute
    shortest paths and distances independently.
    """

    def __init__(self, nodes: list[Node], roads: list[Road]) -> None:
        # Keep a set of all known node IDs for fast validation
        self._nodes: set[str] = {n.id for n in nodes}

        # Adjacency dict for time: {from_node: list[_Edge]}
        self._time_adj: dict[str, list[_Edge]] = {n.id: [] for n in nodes}

        # Adjacency dict for distance: {from_node: {to_node: km}}
        # (only needed for route_distance; keyed the same way as _time_adj)
        self._dist_adj: dict[str, dict[str, float]] = {n.id: {} for n in nodes}

        for road in roads:
            if road.blocked:
                continue  # Blocked roads are not traversable

            # Effective travel time: base_time * traffic_multiplier
            eff_time = road.base_time * road.traffic_multiplier

            # Roads are bidirectional — add both directions
            for src, dst in [(road.from_node, road.to_node),
                             (road.to_node, road.from_node)]:
                if src in self._time_adj:
                    self._time_adj[src].append(_Edge(to=dst, time=eff_time, distance=road.distance))
                else:
                    self._time_adj[src] = [_Edge(to=dst, time=eff_time, distance=road.distance)]

                if src in self._dist_adj:
                    self._dist_adj[src][dst] = road.distance
                else:
                    self._dist_adj[src] = {dst: road.distance}

    # ------------------------------------------------------------------
    # Dijkstra (single-source, returns costs + predecessors)
    # ------------------------------------------------------------------

    def _dijkstra(self, start: str) -> tuple[dict[str, float], dict[str, Optional[str]]]:
        """
        Min-heap Dijkstra from `start`.

        Returns
        -------
        dist : dict[node_id, float]
            Minimum effective travel time to each reachable node (minutes).
        prev : dict[node_id, Optional[str]]
            Predecessor map for path reconstruction.
        """
        if start not in self._nodes:
            return {}, {}

        dist: dict[str, float] = {start: 0.0}
        prev: dict[str, Optional[str]] = {start: None}

        # heap entries: (cost, node_id)
        heap: list[tuple[float, str]] = [(0.0, start)]

        while heap:
            cost, u = heapq.heappop(heap)

            # Skip stale heap entries
            if cost > dist.get(u, math.inf):
                continue

            for edge in self._time_adj.get(u, []):
                new_cost = cost + edge.time
                if new_cost < dist.get(edge.to, math.inf):
                    dist[edge.to] = new_cost
                    prev[edge.to] = u
                    heapq.heappush(heap, (new_cost, edge.to))

        return dist, prev

    def _reconstruct_path(self, prev: dict[str, Optional[str]], end: str) -> list[str]:
        """Walk the predecessor map backward from `end` to reconstruct the path."""
        if end not in prev:
            return []  # unreachable
        path: list[str] = []
        current: Optional[str] = end
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
        Return the ordered list of node IDs forming the shortest (time-optimal)
        path from `start` to `end`.

        Returns [] if:
          - Either node is unknown.
          - No path exists (disconnected or all roads blocked).
        """
        if start not in self._nodes or end not in self._nodes:
            return []
        if start == end:
            return [start]
        _, prev = self._dijkstra(start)
        return self._reconstruct_path(prev, end)

    def travel_time(self, start: str, end: str) -> float:
        """
        Return the effective travel time (minutes) from `start` to `end`
        along the shortest path.

        Returns math.inf if unreachable or either node is unknown.
        """
        if start not in self._nodes or end not in self._nodes:
            return math.inf
        if start == end:
            return 0.0
        dist, _ = self._dijkstra(start)
        return dist.get(end, math.inf)

    def route_distance(self, ordered_node_ids: list[str]) -> float:
        """
        Return the total distance in km for a sequence of waypoints
        (traversed in order: ordered_node_ids[0] → [1] → … → [-1]).

        Each hop uses the direct road distance between consecutive nodes.
        If any consecutive pair has no direct road, that hop contributes 0.0 km.
        (The planner always picks adjacent nodes so this is safe.)
        """
        total = 0.0
        for i in range(len(ordered_node_ids) - 1):
            a, b = ordered_node_ids[i], ordered_node_ids[i + 1]
            total += self._dist_adj.get(a, {}).get(b, 0.0)
        return round(total, 3)

    def route_travel_time(self, ordered_node_ids: list[str]) -> float:
        """
        Return the total effective travel time in minutes for a waypoint sequence.
        Each hop is routed via shortest_path so multi-hop intermediate legs
        are properly accounted for.
        """
        total = 0.0
        for i in range(len(ordered_node_ids) - 1):
            t = self.travel_time(ordered_node_ids[i], ordered_node_ids[i + 1])
            if t == math.inf:
                return math.inf  # whole route is infeasible
            total += t
        return round(total, 3)

    def all_pairs_travel_times(self) -> dict[str, dict[str, float]]:
        """
        Pre-compute the all-pairs shortest path time table.
        Returns {from_node: {to_node: minutes}}.
        """
        return {n: self._dijkstra(n)[0] for n in self._nodes}

    def has_node(self, node_id: str) -> bool:
        """Return True if node_id exists in the graph."""
        return node_id in self._nodes


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

def build_graph(nodes: list[Node], roads: list[Road]) -> CityGraph:
    """Construct a CityGraph from SQLModel Node and Road objects."""
    return CityGraph(nodes, roads)
