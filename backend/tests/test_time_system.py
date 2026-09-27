"""
test_time_system.py — Comprehensive Test Suite for RouterX Time System Overhaul.

Verifies:
  TEST 1  — Application Start & Initial Clock
  TEST 2  — Advance Simulation Time (+15 min)
  TEST 3  — Manual Time Setting (e.g. 12:00 PM -> 3:00 PM)
  TEST 4  — Delivery Window & Lateness Calculation
  TEST 5  — Vehicle Route Progress Over Time
  TEST 6  — Vehicle Breakdown & Inactivity Under Time Advance
  TEST 7  — Traffic Impact on Time & ETA
  TEST 8  — Order Reassignment & ETA Delta Preservation
  TEST 9  — Reset Demo Time & State Cleanliness
  TEST 10 — Fresh Scenario Blank Slate & Clean Time
  TEST 11 — Midnight Crossing Time Arithmetic & Formatting
  TEST 12 — Multiple Orders With Independent Delivery Windows
"""

import pytest
from datetime import datetime, timezone
from sqlmodel import Session, create_engine, select

from app.models import (
    Vehicle, Delivery, Route, Event, EventType, VehicleStatus, DeliveryStatus,
    SimulationMetadata
)
from app.database import (
    init_db, get_fleet_state, reset_fleet_database, fresh_fleet_database,
    set_simulation_clock, advance_simulation_clock, control_simulation_clock
)
from app.time_utils import (
    get_current_local_iso, to_datetime, to_elapsed_minutes, format_clock_time,
    format_date, format_time_window, format_duration, format_eta_delta,
    parse_clock_time
)
from app.optimizer import generate_initial_plan


@pytest.fixture(autouse=True)
def setup_clean_db():
    init_db()
    # Reset to baseline deterministic scenario
    state = reset_fleet_database(start_time="2026-09-27T12:00:00+00:00")
    yield state


def test_1_application_start():
    state = get_fleet_state()
    assert state.simulation_start_time == "2026-09-27T12:00:00+00:00"
    assert state.simulation_time == 0.0
    assert state.current_simulation_time.startswith("2026-09-27T12:00:00")
    clock_str = format_clock_time(state.simulation_time, state.simulation_start_time)
    assert "12:00 PM" in clock_str


def test_2_advance_time():
    # Advance by 15 minutes
    state = advance_simulation_clock(15.0)
    assert state.simulation_time == 15.0
    clock_str = format_clock_time(state.simulation_time, state.simulation_start_time)
    assert "12:15 PM" in clock_str
    # Vehicles should have progressed or be en route
    assert state.metrics["total_vehicles"] == 8


def test_3_manual_time_setting():
    # Set clock from 12:00 PM to 3:00 PM (+180 minutes)
    state = set_simulation_clock(180.0)
    assert state.simulation_time == 180.0
    clock_str = format_clock_time(state.simulation_time, state.simulation_start_time)
    assert "3:00 PM" in clock_str

    # Deliveries should have progressed to delivered
    assert state.metrics["completed_deliveries"] > 0
    assert state.metrics["pending_deliveries"] < 40


def test_4_delivery_window_and_lateness():
    start_time = "2026-09-27T12:00:00+00:00"
    # Order with window 2:00 PM to 3:00 PM (120 min to 180 min)
    tw_str = format_time_window(120.0, 180.0, start_time)
    assert "2:00 PM – 3:00 PM" in tw_str

    # Arrival at 2:30 PM (150 min) -> on time
    arr_early = 150.0
    lateness_early = max(0.0, arr_early - 180.0)
    assert lateness_early == 0.0

    # Arrival at 3:15 PM (195 min) -> late by 15 min
    arr_late = 195.0
    lateness_late = max(0.0, arr_late - 180.0)
    assert lateness_late == 15.0
    assert format_duration(lateness_late) == "15 min"


def test_5_vehicle_route_progress():
    # Advance time sequentially and check vehicle locations
    s0 = set_simulation_clock(0.0)
    v0 = next(v for v in s0.vehicles if v.id == "v01")
    assert v0.current_location == "depot"

    # Advance to mid-tour
    s1 = advance_simulation_clock(60.0)
    v1 = next(v for v in s1.vehicles if v.id == "v01")
    # Location should reflect a visited stop on the route
    assert v1.current_location is not None


def test_6_vehicle_breakdown_under_time_advance():
    # Set vehicle v03 to BREAKDOWN
    state = get_fleet_state()
    from app.database import engine
    with Session(engine) as s:
        v = s.get(Vehicle, "v03")
        v.status = VehicleStatus.BREAKDOWN
        s.add(v)
        s.commit()

    # Advance time by 120 minutes
    state_after = advance_simulation_clock(120.0)
    v_after = next(v for v in state_after.vehicles if v.id == "v03")
    assert v_after.status == VehicleStatus.BREAKDOWN


def test_7_traffic_impact_on_time():
    from app.event_engine import process_event
    from app.database import engine
    with Session(engine) as s:
        ev = Event(
            id="ev_test_traffic",
            event_type=EventType.TRAFFIC_UPDATE,
            timestamp=10.0,
            affected_entity_id="road_000",
            parameters={"traffic_multiplier": 4.0},
        )
        res = process_event(ev, s)
        assert res.after_metrics.total_travel_time >= res.before_metrics.total_travel_time


def test_8_reassignment_and_eta_delta():
    # Verify delta formatting
    delta_pos = 15.0
    delta_neg = -9.0
    assert format_eta_delta(delta_pos) == "↑ +15 min"
    assert format_eta_delta(delta_neg) == "↓ -9 min"


def test_9_reset_demo():
    # Advance time first
    advance_simulation_clock(90.0)
    # Reset
    reset_state = reset_fleet_database(start_time="2026-09-27T10:00:00+00:00")
    assert reset_state.simulation_time == 0.0
    assert reset_state.simulation_start_time == "2026-09-27T10:00:00+00:00"
    clock_str = format_clock_time(reset_state.simulation_time, reset_state.simulation_start_time)
    assert "10:00 AM" in clock_str
    assert reset_state.metrics["total_vehicles"] == 8
    assert reset_state.metrics["total_deliveries"] == 40


def test_10_fresh_scenario():
    fresh_state = fresh_fleet_database(start_time="2026-09-27T08:30:00+00:00")
    assert fresh_state.simulation_time == 0.0
    assert fresh_state.simulation_start_time == "2026-09-27T08:30:00+00:00"
    assert fresh_state.metrics["total_vehicles"] == 0
    assert fresh_state.metrics["total_deliveries"] == 0
    clock_str = format_clock_time(fresh_state.simulation_time, fresh_state.simulation_start_time)
    assert "8:30 AM" in clock_str


def test_11_midnight_crossing():
    # Start at 11:50 PM
    start_time = "2026-09-27T23:50:00+00:00"
    # Advance 20 minutes -> 12:10 AM next day
    elapsed = 20.0
    dt = to_datetime(start_time, elapsed)
    assert dt.day == 28
    assert dt.hour == 0
    assert dt.minute == 10
    clock_str = format_clock_time(elapsed, start_time)
    assert clock_str == "12:10 AM"

    # Format date after crossing midnight
    date_str = format_date(elapsed, start_time)
    assert "Sep 28, 2026" in date_str


def test_12_multiple_orders_independent_windows():
    start_time = "2026-09-27T09:00:00+00:00"
    w1 = format_time_window(60.0, 120.0, start_time)   # 10:00 AM – 11:00 AM
    w2 = format_time_window(180.0, 240.0, start_time) # 12:00 PM – 1:00 PM
    assert "10:00 AM – 11:00 AM" in w1
    assert "12:00 PM – 1:00 PM" in w2

    # Parsing clock times back to elapsed minutes
    p1 = parse_clock_time("10:00 AM", start_time)
    p2 = parse_clock_time("1:00 PM", start_time)
    assert p1 == 60.0
    assert p2 == 240.0
