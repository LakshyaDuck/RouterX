"""
Automated tests for events and delivery model.
Verifies TIME_WINDOW_CHANGE event processing and delivery demand attribute.
"""

import asyncio
from app.models import Delivery, Event, EventType, DeliveryStatus
from app.routers.fleet import post_event
from app.database import engine
from sqlmodel import Session


def test_delivery_demand_attribute():
    """Verify delivery uses demand (not weight)."""
    d = Delivery(
        id="test_d1",
        location="n01",
        demand=25.5,
        priority=1,
        time_window_start=30.0,
        time_window_end=90.0,
        status=DeliveryStatus.PENDING,
    )
    assert d.demand == 25.5
    assert not hasattr(d, "weight") or getattr(d, "weight", None) is None


def test_time_window_change_event():
    """Verify TIME_WINDOW_CHANGE updates delivery time windows."""
    with Session(engine) as session:
        # Clean any leftovers from previous runs
        existing_d = session.get(Delivery, "test_tw_d1")
        if existing_d:
            session.delete(existing_d)
        existing_ev = session.get(Event, "ev_tw_01")
        if existing_ev:
            session.delete(existing_ev)
        session.commit()

        try:
            # Create a test delivery
            d = Delivery(
                id="test_tw_d1",
                location="n02",
                demand=15.0,
                priority=2,
                time_window_start=60.0,
                time_window_end=120.0,
                status=DeliveryStatus.PENDING,
            )
            session.add(d)
            session.commit()

            # Create TIME_WINDOW_CHANGE event
            ev = Event(
                id="ev_tw_01",
                event_type=EventType.TIME_WINDOW_CHANGE,
                timestamp=10.0,
                affected_entity_id="test_tw_d1",
                parameters={"time_window_start": 80.0, "time_window_end": 140.0},
            )

            asyncio.run(post_event(ev, session))

            # Refresh delivery from DB
            updated = session.get(Delivery, "test_tw_d1")
            assert updated is not None
            assert updated.time_window_start == 80.0
            assert updated.time_window_end == 140.0

            # Verify event was recorded in DB
            saved_event = session.get(Event, "ev_tw_01")
            assert saved_event is not None
            assert saved_event.event_type == EventType.TIME_WINDOW_CHANGE
        finally:
            d_cleanup = session.get(Delivery, "test_tw_d1")
            if d_cleanup:
                session.delete(d_cleanup)
            ev_cleanup = session.get(Event, "ev_tw_01")
            if ev_cleanup:
                session.delete(ev_cleanup)
            session.commit()
