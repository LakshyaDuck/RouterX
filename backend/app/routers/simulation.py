"""
Simulation Router for Hackathon Demo.

Provides deterministic control over the demonstration scenario:
  - Reset simulation to baseline (8 vehicles, 40 deliveries, 25 nodes, 45 roads)
  - Execute pre-configured Demo Events (Steps 1 through 4)
  - Inspect current simulation state
"""

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlmodel import Session, SQLModel

from app.database import (
    get_session,
    get_fleet_state,
    reset_fleet_database,
    fresh_fleet_database,
    has_fleet_data,
    set_simulation_clock,
    advance_simulation_clock,
    control_simulation_clock,
)
from app.models import FleetState, Event, EventType
from app.event_engine import process_event
from app.time_utils import (
    get_current_local_iso,
    to_datetime,
    to_elapsed_minutes,
    format_clock_time,
    format_date,
    parse_clock_time,
)
from simulation.demo_scenario import DEMO_EVENTS_SPEC

router = APIRouter(tags=["simulation"])


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------

class ResetRequest(SQLModel):
    start_time: Optional[str] = None


class ResetResponse(SQLModel):
    status: str
    message: str
    state: FleetState


class SimulationTimeResponse(SQLModel):
    simulation_start_time: str
    simulation_time: float
    current_simulation_time: str
    is_running: bool
    speed_multiplier: float
    clock_display: str
    date_display: str


class SetSimulationTimeRequest(SQLModel):
    simulation_time: Optional[float] = None
    target_datetime: Optional[str] = None
    target_time_str: Optional[str] = None
    simulation_start_time: Optional[str] = None


class AdvanceSimulationTimeRequest(SQLModel):
    minutes: float


class ControlSimulationTimeRequest(SQLModel):
    is_running: bool
    speed_multiplier: Optional[float] = None


class DemoEventSummary(SQLModel):
    step: int
    title: str
    description: str
    event_type: str
    affected_entity_id: str
    parameters: dict[str, Any]


class DemoEventExecutionResponse(SQLModel):
    step: int
    title: str
    description: str
    state_before: dict[str, Any]
    event: dict[str, Any]
    state_after: dict[str, Any]
    changed_routes: list[str]
    reassigned_deliveries: list[str]
    metrics: dict[str, Any]
    reoptimization_scope: float
    changed_route_percentage: float
    explanation: str
    decision_explanation: str = ""
    full_state: FleetState


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/simulation/reset", response_model=ResetResponse)
@router.post("/api/simulation/reset", response_model=ResetResponse)
async def reset_simulation(req: Optional[ResetRequest] = None, session: Session = Depends(get_session)):
    """
    Reset simulation to the fixed, deterministic initial state:
      - 8 vehicles
      - 40 deliveries
      - 25 nodes
      - 45 roads
      - Initial feasible routes computed deterministically
      - Simulation clock reset to elapsed 0.0 with current local start time
    """
    start_time = req.start_time if req else None
    state = reset_fleet_database(session, start_time=start_time)
    return ResetResponse(
        status="reset",
        message="Simulation successfully reset to initial deterministic state (8 vehicles, 40 deliveries).",
        state=state,
    )


@router.post("/simulation/fresh", response_model=ResetResponse)
@router.post("/api/simulation/fresh", response_model=ResetResponse)
@router.post("/api/scenario/fresh", response_model=ResetResponse)
async def fresh_simulation(req: Optional[ResetRequest] = None, session: Session = Depends(get_session)):
    """
    Clear operational scenario to an empty slate:
      - 0 vehicles
      - 0 deliveries
      - 0 routes
      - 0 events
      - Preserves underlying network infrastructure (nodes, depot, roads)
      - Resets roads to normal traffic (1.0) and unblocked (False)
      - Starts fresh simulation clock with elapsed 0.0
    """
    start_time = req.start_time if req else None
    state = fresh_fleet_database(session, start_time=start_time)
    return ResetResponse(
        status="fresh",
        message="Scenario successfully cleared to blank slate (0 vehicles, 0 deliveries).",
        state=state,
    )


@router.get("/simulation/time", response_model=SimulationTimeResponse)
@router.get("/api/simulation/time", response_model=SimulationTimeResponse)
async def get_simulation_time(session: Session = Depends(get_session)):
    """Get the authoritative simulation clock state."""
    state = get_fleet_state(session)
    start_iso = state.simulation_start_time or get_current_local_iso()
    sim_time = state.simulation_time
    curr_iso = state.current_simulation_time or to_datetime(start_iso, sim_time).isoformat()
    return SimulationTimeResponse(
        simulation_start_time=start_iso,
        simulation_time=sim_time,
        current_simulation_time=curr_iso,
        is_running=state.is_running or False,
        speed_multiplier=state.speed_multiplier or 1.0,
        clock_display=format_clock_time(sim_time, start_iso),
        date_display=format_date(sim_time, start_iso),
    )


@router.post("/simulation/time", response_model=FleetState)
@router.post("/api/simulation/time", response_model=FleetState)
async def set_simulation_time(req: SetSimulationTimeRequest, session: Session = Depends(get_session)):
    """
    Set simulation clock time.
    Accepts:
      - simulation_time: float (elapsed minutes)
      - target_datetime: str (ISO datetime)
      - target_time_str: str ("2:30 PM", "14:30")
      - simulation_start_time: str (optional ISO datetime)
    """
    state = get_fleet_state(session)
    start_iso = req.simulation_start_time or state.simulation_start_time or get_current_local_iso()

    target_mins: float = 0.0
    if req.simulation_time is not None:
        target_mins = float(req.simulation_time)
    elif req.target_datetime is not None:
        target_mins = to_elapsed_minutes(start_iso, req.target_datetime)
    elif req.target_time_str is not None:
        target_mins = parse_clock_time(req.target_time_str, start_iso)
    else:
        target_mins = state.simulation_time

    return set_simulation_clock(target_mins, start_time=req.simulation_start_time, session=session)


@router.post("/simulation/time/advance", response_model=FleetState)
@router.post("/api/simulation/time/advance", response_model=FleetState)
async def advance_simulation_time(req: AdvanceSimulationTimeRequest, session: Session = Depends(get_session)):
    """Advance or rewind the simulation clock by minutes (+15, -15, etc.)."""
    return advance_simulation_clock(req.minutes, session=session)


@router.post("/simulation/time/control", response_model=FleetState)
@router.post("/api/simulation/time/control", response_model=FleetState)
async def control_simulation_time(req: ControlSimulationTimeRequest, session: Session = Depends(get_session)):
    """Pause, play, or change simulation speed multiplier."""
    return control_simulation_clock(req.is_running, speed_multiplier=req.speed_multiplier, session=session)


@router.get("/simulation/state", response_model=FleetState)
@router.get("/api/simulation/state", response_model=FleetState)
async def get_simulation_state(session: Session = Depends(get_session)):
    """Retrieve full current simulation state."""
    if not has_fleet_data(session):
        raise HTTPException(status_code=503, detail="Fleet state not initialized. Call /simulation/reset first.")
    return get_fleet_state(session)



@router.get("/simulation/demo-events", response_model=list[DemoEventSummary])
@router.get("/api/simulation/demo-events", response_model=list[DemoEventSummary])
async def list_demo_events():
    """List the 4 fixed demo events for the hackathon walkthrough."""
    return [
        DemoEventSummary(
            step=spec["step"],
            title=spec["title"],
            description=spec["description"],
            event_type=spec["event_type"],
            affected_entity_id=spec["affected_entity_id"],
            parameters=spec["parameters"],
        )
        for spec in DEMO_EVENTS_SPEC
    ]


@router.post("/simulation/event/{step_id}", response_model=DemoEventExecutionResponse)
@router.post("/api/simulation/event/{step_id}", response_model=DemoEventExecutionResponse)
@router.post("/simulation/step/{step_id}", response_model=DemoEventExecutionResponse)
@router.post("/api/simulation/step/{step_id}", response_model=DemoEventExecutionResponse)
async def execute_demo_event(
    step_id: int = Path(..., ge=1, le=4, description="Demo step number (1, 2, 3, or 4)"),
    session: Session = Depends(get_session),
):
    """
    Execute one of the 4 pre-configured demo events:
      - Step 1: Major Traffic Jam on Central Artery (road_000)
      - Step 2: Vehicle V03 Mechanical Breakdown
      - Step 3: Urgent Priority 1 Order (d_rush_p1)
      - Step 4: Customer Expedited Delivery Window (d11)

    Captures state before, event, state after, metrics, and explanation.
    """
    if not has_fleet_data(session):
        # Auto-initialize if database is empty
        reset_fleet_database(session)

    # Find the corresponding event specification
    spec = next((s for s in DEMO_EVENTS_SPEC if s["step"] == step_id), None)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Demo event step {step_id} not found.")

    # 1. Capture State Before
    state_before_obj = get_fleet_state(session)
    active_vehicles_before = [v.id for v in state_before_obj.vehicles if v.status.value == "ACTIVE"]
    total_dist_before = round(sum(r.total_distance for r in state_before_obj.routes), 2)
    total_time_before = round(sum(r.total_travel_time for r in state_before_obj.routes), 2)
    state_before_summary = {
        "active_vehicles": active_vehicles_before,
        "total_vehicles": len(state_before_obj.vehicles),
        "total_deliveries": len(state_before_obj.deliveries),
        "total_distance": total_dist_before,
        "total_travel_time": total_time_before,
    }

    # 2. Build Event entity
    event_id = f"demo_step_{step_id}_{uuid.uuid4().hex[:6]}"
    ev_type = EventType(spec["event_type"])
    event_model = Event(
        id=event_id,
        event_type=ev_type,
        timestamp=float(step_id * 15.0),
        affected_entity_id=spec["affected_entity_id"],
        parameters=spec["parameters"],
    )

    # 3. Incrementally process event through event engine
    event_response = process_event(event_model, session)

    # 4. Capture State After
    state_after_obj = get_fleet_state(session)
    active_vehicles_after = [v.id for v in state_after_obj.vehicles if v.status.value == "ACTIVE"]
    total_dist_after = round(sum(r.total_distance for r in state_after_obj.routes), 2)
    total_time_after = round(sum(r.total_travel_time for r in state_after_obj.routes), 2)
    state_after_summary = {
        "active_vehicles": active_vehicles_after,
        "total_vehicles": len(state_after_obj.vehicles),
        "total_deliveries": len(state_after_obj.deliveries),
        "total_distance": total_dist_after,
        "total_travel_time": total_time_after,
    }

    # Calculate metrics package
    metrics_package = {
        "before": {
            "distance": event_response.before_metrics.total_distance,
            "travel_time": event_response.before_metrics.total_travel_time,
            "late_deliveries": event_response.before_metrics.late_deliveries,
            "unassigned_deliveries": event_response.before_metrics.unassigned_deliveries,
            "affected_routes": event_response.affected_vehicles,
        },
        "after": {
            "distance": event_response.after_metrics.total_distance,
            "travel_time": event_response.after_metrics.total_travel_time,
            "late_deliveries": event_response.after_metrics.late_deliveries,
            "unassigned_deliveries": event_response.after_metrics.unassigned_deliveries,
            "changed_routes": event_response.changed_routes,
            "reassigned_deliveries": event_response.reassigned_deliveries,
        },
        "reoptimization_scope": event_response.reoptimization_scope,
        "changed_route_percentage": round(
            len(event_response.changed_routes) / max(1, len(state_after_obj.routes)), 4
        ),
    }

    return DemoEventExecutionResponse(
        step=step_id,
        title=spec["title"],
        description=spec["description"],
        state_before=state_before_summary,
        event={
            "id": event_model.id,
            "event_type": spec["event_type"],
            "affected_entity_id": spec["affected_entity_id"],
            "parameters": spec["parameters"],
        },
        state_after=state_after_summary,
        changed_routes=event_response.changed_routes,
        reassigned_deliveries=event_response.reassigned_deliveries,
        metrics=metrics_package,
        reoptimization_scope=event_response.reoptimization_scope,
        changed_route_percentage=metrics_package["changed_route_percentage"],
        explanation=event_response.explanation,
        decision_explanation=event_response.decision_explanation or event_response.explanation,
        full_state=state_after_obj,
    )
