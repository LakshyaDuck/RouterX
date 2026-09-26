"""
Replaces OSRM's job for a synthetic/imaginary world: turns a set of
(x, y) locations into a travel-time cost matrix for OR-Tools.

Why Euclidean and not a real router: OSRM's whole value was making travel
time reflect a REAL road network (turns, one-ways, congestion) instead of
straight-line distance. In an imaginary world there is no real network to
be more accurate than — you're the one defining what "a road" means here,
so straight-line distance, scaled by an assumed average speed, IS the
ground truth for this world. This is also exactly what OR-Tools' own
VRPTW reference examples use for synthetic benchmarks — not a shortcut,
the standard approach when geography is invented rather than real.

If you later want your imaginary world to have non-trivial structure
(obstacles, zones that are slower to cross, one-way constraints) — that's
the point where this stops being enough and becomes a small custom graph
you author yourself (nodes + weighted edges), with shortest paths via
networkx instead of straight lines. Nothing else in the stack needs to
change for that upgrade — this module is the only seam that would.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    id: str
    x: float
    y: float


def euclidean_distance(a: Location, b: Location) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def build_distance_matrix(locations: list[Location]) -> list[list[float]]:
    """
    Returns an N x N matrix of distances (matrix[i][j] = distance from
    locations[i] to locations[j]). This is the direct input to OR-Tools'
    RoutingModel — it never needs to know these came from math.hypot
    instead of a road-network query; the solver only cares about the
    matrix shape and values.
    """
    n = len(locations)
    return [
        [euclidean_distance(locations[i], locations[j]) for j in range(n)]
        for i in range(n)
    ]


def build_time_matrix(
    locations: list[Location], speed_units_per_second: float = 1.0
) -> list[list[float]]:
    """
    Same as build_distance_matrix, scaled into a travel-TIME matrix — what
    OR-Tools' time-window constraints actually need (VRPTW is defined in
    terms of arrival times, not raw distance). Pick speed_units_per_second
    to match whatever scale your imaginary world's coordinates use (e.g.
    if 1 unit = 1 km and vehicles average 40 km/h, that's 40/3600 km/s).
    """
    dist = build_distance_matrix(locations)
    return [[d / speed_units_per_second for d in row] for row in dist]
