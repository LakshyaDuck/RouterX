"""
Route planner: builds an initial greedy fleet plan.

Algorithm:
  1. Sort deliveries by priority (1 = most urgent first), then by time-window end.
  2. For each delivery, assign to the vehicle that:
     - Has enough remaining capacity
     - Has enough driver hours to reach the location
     - Produces the shortest additional travel time (nearest neighbour)
  3. Return the resulting routes.

This is intentionally simple for hackathon speed and determinism.
"""

import math
from typing import Optional

from app.models import Vehicle, Delivery, Node, Road, Route
from app.routing import CityGraph, build_graph


# ---------------------------------------------------------------------------
# Graph utilities — delegate to the routing engine
# ---------------------------------------------------------------------------

def all_pairs_shortest_paths(
    nodes: list[Node], roads: list[Road]
) -> dict[str, dict[str, float]]:
    """Pre-compute travel times between every pair of nodes via CityGraph."""
    graph = build_graph(nodes, roads)
    return graph.all_pairs_travel_times()


def travel_time(
    apsp: dict[str, dict[str, float]], from_node: str, to_node: str
) -> float:
    """Return travel time from APSP table or infinity if unreachable."""
    return apsp.get(from_node, {}).get(to_node, math.inf)


def travel_distance(roads: list[Road], from_node: str, to_node: str) -> float:
    """
    Returns the direct edge distance between two connected nodes.
    Falls back to 0 if not directly connected (routes use sequences of edges).
    """
    for r in roads:
        if (r.from_node == from_node and r.to_node == to_node) or \
           (r.to_node == from_node and r.from_node == to_node):
            return r.distance
    return 0.0


# ---------------------------------------------------------------------------
# Route builder
# ---------------------------------------------------------------------------

class VehicleState:
    """Mutable planner state for one vehicle during route construction."""

    def __init__(self, vehicle: Vehicle):
        self.vehicle = vehicle
        self.current_node: str = vehicle.current_location
        self.load: float = 0.0
        self.time_elapsed: float = 0.0    # minutes since shift start
        self.delivery_ids: list[str] = []
        self.total_distance: float = 0.0
        self.total_time: float = 0.0

    @property
    def capacity_remaining(self) -> float:
        return self.vehicle.capacity - self.load

    @property
    def driver_minutes_remaining(self) -> float:
        return self.vehicle.driver_hours_remaining * 60 - self.time_elapsed


from app.optimizer import generate_initial_plan


def build_initial_routes(
    vehicles: list[Vehicle],
    deliveries: list[Delivery],
    nodes: list[Node],
    roads: list[Road],
) -> list[Route]:
    """
    Generate initial delivery plan using the optimizer's insertion heuristic.
    """
    plan = generate_initial_plan(vehicles, deliveries, nodes, roads)
    return plan.routes
