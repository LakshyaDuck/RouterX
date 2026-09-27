"""
Routing API router.

Endpoints expose the CityGraph routing engine over HTTP so the
frontend and external tools can query paths and travel times.

All endpoints read road + node data from PostgreSQL on each request,
then run pure-Python Dijkstra in memory — fast enough for 25 nodes.
"""

import math
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel

from app.database import get_session, get_nodes, get_roads, has_fleet_data
from app.routing import build_graph

router = APIRouter(prefix="/api/routing", tags=["routing"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class PathRequest(SQLModel):
    start: str
    end: str


class PathResponse(SQLModel):
    start: str
    end: str
    path: list[str]           # ordered node IDs, empty if unreachable
    reachable: bool
    travel_time_minutes: float
    hops: int


class RouteMetricsRequest(SQLModel):
    node_ids: list[str]       # ordered waypoints (e.g. depot → d1 → d2 → depot)


class RouteMetricsResponse(SQLModel):
    node_ids: list[str]
    total_distance_km: float
    total_travel_time_minutes: float
    feasible: bool            # False if any leg is unreachable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_graph(session: Session):
    """Load nodes and roads from DB, build and return a CityGraph."""
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet data not yet initialized")
    nodes = get_nodes(session)
    roads = get_roads(session)
    return build_graph(nodes, roads)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/path", response_model=PathResponse)
async def compute_shortest_path(
    req: PathRequest,
    session: Session = Depends(get_session),
):
    """
    Compute the shortest (time-optimal) path between two city nodes.

    Returns the ordered list of node IDs and the effective travel time.
    If either node does not exist, or no path exists, `reachable` is False.
    """
    graph = _get_graph(session)

    if not graph.has_node(req.start):
        raise HTTPException(status_code=404, detail=f"Node '{req.start}' not found in city graph")
    if not graph.has_node(req.end):
        raise HTTPException(status_code=404, detail=f"Node '{req.end}' not found in city graph")

    path = graph.shortest_path(req.start, req.end)
    t = graph.travel_time(req.start, req.end)
    reachable = len(path) > 0 and t != math.inf

    return PathResponse(
        start=req.start,
        end=req.end,
        path=path,
        reachable=reachable,
        travel_time_minutes=t if reachable else -1.0,
        hops=len(path) - 1 if reachable else 0,
    )


@router.get("/time/{start}/{end}")
async def get_travel_time(
    start: str,
    end: str,
    session: Session = Depends(get_session),
):
    """
    Return the effective travel time in minutes between two nodes.
    Returns -1 if either node is unknown or unreachable.
    """
    graph = _get_graph(session)

    if not graph.has_node(start):
        raise HTTPException(status_code=404, detail=f"Node '{start}' not found")
    if not graph.has_node(end):
        raise HTTPException(status_code=404, detail=f"Node '{end}' not found")

    t = graph.travel_time(start, end)
    return {
        "start": start,
        "end": end,
        "travel_time_minutes": t if t != math.inf else -1.0,
        "reachable": t != math.inf,
    }


@router.post("/route-distance", response_model=RouteMetricsResponse)
async def compute_route_distance(
    req: RouteMetricsRequest,
    session: Session = Depends(get_session),
):
    """
    Compute the total road distance (km) for an ordered list of waypoints.
    Each consecutive pair of nodes must be directly connected by a road;
    the engine sums direct edge distances along the sequence.
    """
    if len(req.node_ids) < 2:
        raise HTTPException(status_code=422, detail="Provide at least 2 node IDs")

    graph = _get_graph(session)
    dist = graph.route_distance(req.node_ids)
    t = graph.route_travel_time(req.node_ids)
    feasible = t != math.inf

    return RouteMetricsResponse(
        node_ids=req.node_ids,
        total_distance_km=dist,
        total_travel_time_minutes=t if feasible else -1.0,
        feasible=feasible,
    )


@router.post("/route-time", response_model=RouteMetricsResponse)
async def compute_route_travel_time(
    req: RouteMetricsRequest,
    session: Session = Depends(get_session),
):
    """
    Compute the total effective travel time (minutes) for an ordered list of
    waypoints. Each hop is routed via Dijkstra so non-adjacent nodes are OK.
    """
    if len(req.node_ids) < 2:
        raise HTTPException(status_code=422, detail="Provide at least 2 node IDs")

    graph = _get_graph(session)
    t = graph.route_travel_time(req.node_ids)
    dist = graph.route_distance(req.node_ids)
    feasible = t != math.inf

    return RouteMetricsResponse(
        node_ids=req.node_ids,
        total_distance_km=dist,
        total_travel_time_minutes=t if feasible else -1.0,
        feasible=feasible,
    )
