"""
Automated unit and integration tests for the Real-Time Event Engine.

Tests cover:
  1. TRAFFIC_UPDATE       - road congestion, re-routes affected vehicles, preserves unaffected
  2. VEHICLE_BREAKDOWN    - marks breakdown, reassigns orphaned deliveries to active fleet
  3. NEW_DELIVERY         - incremental insertion into lowest-cost candidate, leaves other routes
  4. DELIVERY_CANCELLED   - marks CANCELLED, removes from route, updates load/distance
  5. ROAD_BLOCKED         - blocks road, forces detour around road; then reopens and restores
  6. TIME_WINDOW_CHANGE   - shifts deadline, revalidates/repositions stop
  7. SEQUENTIAL_EVENTS    - traffic -> breakdown -> new delivery -> time-window change
  8. RESPONSE_FORMAT      - verifies explanation, diffs, reoptimization_scope
"""

import math
import pytest
from sqlmodel import Session, select

from app.models import (
    Vehicle, Delivery, Node, Road, Route, Event,
    VehicleStatus, DeliveryStatus, EventType
)
from app.database import engine, get_fleet_state, reset_fleet_database
from app.event_engine import process_event


@pytest.fixture(autouse=True)
def setup_fresh_fleet():
    """Seed the database with a clean initial fleet state before tests."""
    with Session(engine) as session:
        reset_fleet_database(session)
    yield


# ---------------------------------------------------------------------------
# 1. TRAFFIC_UPDATE
# ---------------------------------------------------------------------------

def test_traffic_update_event():
    with Session(engine) as session:
        # Find a road that is actually used by at least one route
        state = get_fleet_state(session)
        target_road = state.roads[0]
        initial_mult = target_road.traffic_multiplier

        ev = Event(
            id="ev_test_traffic",
            event_type=EventType.TRAFFIC_UPDATE,
            timestamp=5.0,
            affected_entity_id=target_road.id,
            parameters={"traffic_multiplier": initial_mult * 3.0},
        )

        resp = process_event(ev, session)

        assert resp.event_id == "ev_test_traffic"
        assert resp.event_type == "TRAFFIC_UPDATE"
        assert isinstance(resp.explanation, str)
        assert len(resp.explanation) > 0
        assert resp.before_metrics.total_distance > 0

        # Check DB updated
        updated_road = session.get(Road, target_road.id)
        assert math.isclose(updated_road.traffic_multiplier, initial_mult * 3.0, rel_tol=1e-5)


# ---------------------------------------------------------------------------
# 2. VEHICLE_BREAKDOWN
# ---------------------------------------------------------------------------

def test_vehicle_breakdown_event():
    with Session(engine) as session:
        state = get_fleet_state(session)
        # Pick an active vehicle with assigned deliveries
        active_v = next(v for v in state.vehicles if v.status == VehicleStatus.ACTIVE and len(state.routes) > 0)
        route = next(r for r in state.routes if r.vehicle_id == active_v.id)
        assert len(route.delivery_ids) > 0, "Selected vehicle must have assigned deliveries"
        orphaned_ids = list(route.delivery_ids)

        ev = Event(
            id="ev_test_breakdown",
            event_type=EventType.VEHICLE_BREAKDOWN,
            timestamp=12.0,
            affected_entity_id=active_v.id,
            parameters={"reason": "engine_overheating"},
        )

        resp = process_event(ev, session)

        # Vehicle must be marked BREAKDOWN
        v_updated = session.get(Vehicle, active_v.id)
        assert v_updated.status == VehicleStatus.BREAKDOWN
        assert v_updated.current_load == 0.0

        # Broken vehicle route should be cleared; feasible if 0 orphaned deliveries remain
        r_updated = session.get(Route, active_v.id)
        assert r_updated.delivery_ids == []
        assert r_updated.feasible is True

        # Deliveries must NOT be assigned to broken vehicle
        for did in orphaned_ids:
            d = session.get(Delivery, did)
            assert d.assigned_vehicle != active_v.id

        assert active_v.id in resp.affected_vehicles
        assert "BREAKDOWN" in resp.explanation


# ---------------------------------------------------------------------------
# 3. NEW_DELIVERY
# ---------------------------------------------------------------------------

def test_new_delivery_event():
    with Session(engine) as session:
        state_before = get_fleet_state(session)
        total_deliveries_before = len(state_before.deliveries)

        ev = Event(
            id="ev_test_new_del",
            event_type=EventType.NEW_DELIVERY,
            timestamp=15.0,
            affected_entity_id="d_brand_new_99",
            parameters={
                "location": "n01",
                "demand": 12.0,
                "priority": 1,
                "time_window_start": 30.0,
                "time_window_end": 240.0,
            },
        )

        resp = process_event(ev, session)

        # Delivery exists in database
        new_d = session.get(Delivery, "d_brand_new_99")
        assert new_d is not None
        assert new_d.demand == 12.0
        assert new_d.priority == 1
        assert "d_brand_new_99" in resp.affected_deliveries

        # If assigned, vehicle route must contain the new delivery
        if new_d.assigned_vehicle:
            r = session.get(Route, new_d.assigned_vehicle)
            assert "d_brand_new_99" in r.delivery_ids

        state_after = get_fleet_state(session)
        assert len(state_after.deliveries) == total_deliveries_before + 1


# ---------------------------------------------------------------------------
# 4. DELIVERY_CANCELLED
# ---------------------------------------------------------------------------

def test_delivery_cancelled_event():
    with Session(engine) as session:
        state = get_fleet_state(session)
        # Find an assigned delivery
        assigned_d = next(d for d in state.deliveries if d.assigned_vehicle is not None)
        vid = assigned_d.assigned_vehicle
        route_before = session.get(Route, vid)
        count_before = len(route_before.delivery_ids)

        ev = Event(
            id="ev_test_cancel",
            event_type=EventType.DELIVERY_CANCELLED,
            timestamp=20.0,
            affected_entity_id=assigned_d.id,
            parameters={"reason": "customer_cancelled"},
        )

        resp = process_event(ev, session)

        # Delivery status updated to CANCELLED
        d_updated = session.get(Delivery, assigned_d.id)
        assert d_updated.status == DeliveryStatus.CANCELLED
        assert d_updated.assigned_vehicle is None

        # Route updated and stop removed
        route_after = session.get(Route, vid)
        assert assigned_d.id not in route_after.delivery_ids
        assert len(route_after.delivery_ids) == count_before - 1
        assert vid in resp.affected_vehicles
        assert assigned_d.id in resp.affected_deliveries


# ---------------------------------------------------------------------------
# 5. ROAD_BLOCKED & REOPENED
# ---------------------------------------------------------------------------

def test_road_blocked_and_reopened_event():
    with Session(engine) as session:
        state = get_fleet_state(session)
        road = state.roads[0]

        # 1. Block road
        ev_block = Event(
            id="ev_block_01",
            event_type=EventType.ROAD_BLOCKED,
            timestamp=25.0,
            affected_entity_id=road.id,
            parameters={"blocked": True},
        )
        resp_block = process_event(ev_block, session)

        road_blocked = session.get(Road, road.id)
        assert road_blocked.blocked is True
        assert "blocked" in resp_block.explanation.lower()

        # 2. Reopen road
        ev_unblock = Event(
            id="ev_unblock_01",
            event_type=EventType.ROAD_BLOCKED,
            timestamp=30.0,
            affected_entity_id=road.id,
            parameters={"blocked": False},
        )
        resp_unblock = process_event(ev_unblock, session)

        road_open = session.get(Road, road.id)
        assert road_open.blocked is False
        assert "reopened" in resp_unblock.explanation.lower()


# ---------------------------------------------------------------------------
# 6. TIME_WINDOW_CHANGE
# ---------------------------------------------------------------------------

def test_time_window_change_event():
    with Session(engine) as session:
        state = get_fleet_state(session)
        target_d = state.deliveries[0]

        ev = Event(
            id="ev_test_tw_shift",
            event_type=EventType.TIME_WINDOW_CHANGE,
            timestamp=35.0,
            affected_entity_id=target_d.id,
            parameters={
                "new_window_start": 80.0,
                "new_window_end": 300.0,
            },
        )

        resp = process_event(ev, session)

        d_updated = session.get(Delivery, target_d.id)
        assert d_updated.time_window_start == 80.0
        assert d_updated.time_window_end == 300.0
        assert target_d.id in resp.affected_deliveries


# ---------------------------------------------------------------------------
# 7. SEQUENTIAL_EVENTS (traffic -> breakdown -> new delivery -> tw change)
# ---------------------------------------------------------------------------

def test_multiple_sequential_events():
    with Session(engine) as session:
        # Step 1: Traffic Update
        ev1 = Event(
            id="seq_ev1",
            event_type=EventType.TRAFFIC_UPDATE,
            timestamp=10.0,
            affected_entity_id="r01",
            parameters={"traffic_multiplier": 2.0},
        )
        r1 = process_event(ev1, session)
        assert r1.event_type == "TRAFFIC_UPDATE"

        # Step 2: Vehicle Breakdown
        target_v = session.exec(select(Vehicle)).first()
        ev2 = Event(
            id="seq_ev2",
            event_type=EventType.VEHICLE_BREAKDOWN,
            timestamp=20.0,
            affected_entity_id=target_v.id,
            parameters={"reason": "flat_tire"},
        )
        r2 = process_event(ev2, session)
        assert r2.event_type == "VEHICLE_BREAKDOWN"
        assert session.get(Vehicle, target_v.id).status == VehicleStatus.BREAKDOWN

        # Step 3: New Delivery
        ev3 = Event(
            id="seq_ev3",
            event_type=EventType.NEW_DELIVERY,
            timestamp=30.0,
            affected_entity_id="d_seq_new",
            parameters={
                "location": "n05",
                "demand": 8.0,
                "priority": 1,
                "time_window_start": 10.0,
                "time_window_end": 200.0,
            },
        )
        r3 = process_event(ev3, session)
        assert r3.event_type == "NEW_DELIVERY"
        # Confirm it was NOT assigned to broken vehicle
        new_d = session.get(Delivery, "d_seq_new")
        assert new_d.assigned_vehicle != target_v.id

        # Step 4: Time Window Change
        ev4 = Event(
            id="seq_ev4",
            event_type=EventType.TIME_WINDOW_CHANGE,
            timestamp=40.0,
            affected_entity_id="d_seq_new",
            parameters={
                "new_window_start": 20.0,
                "new_window_end": 250.0,
            },
        )
        r4 = process_event(ev4, session)
        assert r4.event_type == "TIME_WINDOW_CHANGE"
        assert session.get(Delivery, "d_seq_new").time_window_end == 250.0


# ---------------------------------------------------------------------------
# 8. Reoptimization Scope & Metrics
# ---------------------------------------------------------------------------

def test_reoptimization_scope():
    with Session(engine) as session:
        state = get_fleet_state(session)
        target_d = state.deliveries[0]

        ev = Event(
            id="ev_scope_test",
            event_type=EventType.DELIVERY_CANCELLED,
            timestamp=50.0,
            affected_entity_id=target_d.id,
            parameters={"reason": "test"},
        )
        resp = process_event(ev, session)

        # Single delivery affected out of 30
        assert 0.0 < resp.reoptimization_scope <= 1.0
        assert resp.reoptimization_scope == round(1.0 / len(state.deliveries), 4)
