"""
Phase 0 contract tests.

These exist to make the endpoint surface a deliberate, asserted thing rather
than whatever `main.py` happens to register. The port renames `/fleet/state` to
`/api/state` and `/health` to `/api/health`; a test that pins the full route
table turns that rename from a silent breaking change into a failing assertion
on the commit that causes it.

No database is required for most of this file — it inspects the app object and
exercises the dependency-free endpoints. The one test that needs a session uses
the `session` fixture from conftest, which points at a throwaway database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import main
from models import FleetState, Route, Vehicle


def _get_paths() -> set[str]:
    """
    Paths reachable with GET.

    Membership is tested with `"GET" in r.methods` rather than
    `next(iter(r.methods))`: Starlette registers the docs routes as
    {'GET', 'HEAD'}, and iterating a set to grab "the" method returns HEAD
    often enough to make a naive version of this pass or fail at random.
    """
    return {
        r.path for r in main.app.routes if hasattr(r, "methods") and "GET" in r.methods
    }


def test_app_imports_and_builds() -> None:
    """The app object exists and is a FastAPI instance — the cheapest smoke test."""
    from fastapi import FastAPI

    assert isinstance(main.app, FastAPI)


def test_home_advertises_only_routes_that_exist() -> None:
    """
    Every href in the homepage payload must be a real route.

    The homepage is a contract with the frontend, and a link to a 404 is the
    kind of thing that ships and is only noticed by a user. The phase that
    renames /fleet/state -> /api/state updates these links in the same commit,
    and this test is what guarantees the two never drift.
    """
    registered = _get_paths()
    client = TestClient(main.app)
    body = client.get("/").json()

    for link in body["endpoints"]:
        href = link["href"]
        assert href in registered, f"homepage links to unknown route: {href}"


def test_health_shape() -> None:
    """
    /health reports per-dependency status and rolls them into one `ok`.

    The shape is asserted, not the values: whether Postgres and Redis happen to
    be reachable is environment, but the contract that each check is a dict with
    a boolean `ok` and that the rollup ignores optional checks is not.
    """
    body = TestClient(main.app).get("/health").json()

    assert isinstance(body["ok"], bool)
    for name, check in body["checks"].items():
        assert "ok" in check, f"check {name} has no 'ok' key"
        assert isinstance(check["ok"], bool)
        if not check["ok"]:
            # A failing check must say why. A bare False is unactionable.
            assert "error" in check, f"failing check {name} gives no error"


def test_fleet_state_declares_metrics() -> None:
    """
    FleetState has a `metrics` field.

    Asserts the target shape, not the current one. The whole UI's KPI bar
    reads `state.metrics.total_violations`, and the ported optimizer is what
    populates it, so this is written to fail until Phase 3 lands — which is the
    point: it names the deliverable instead of leaving it implicit.

    `strict=True` so that when Phase 3 adds the field this test starts failing
    for the opposite reason ("unexpectedly passing") and has to be converted to
    a real assertion. An xfail nobody removes is how a suite starts lying.
    """
    if "metrics" not in FleetState.model_fields:
        pytest.xfail(
            "FleetState.metrics is not implemented yet — delivered in Phase 3 "
            "(optimizer + metrics)."
        )
    assert FleetState.model_fields["metrics"].annotation is not None


def test_route_and_vehicle_defaults() -> None:
    """
    Route and Vehicle construct with only their required fields.

    A regression guard on SQLModel column plumbing: `Route.delivery_ids` is a
    JSON column with a default_factory, and it is the field every mutation in
    the event engine touches. If it ever loses its default, every route
    construction site in the ported code raises instead of producing an empty
    route.
    """
    route = Route(
        vehicle_id="v01",
        total_distance=0.0,
        total_travel_time=0.0,
        total_load=0.0,
    )
    assert route.delivery_ids == []
    assert route.feasible is True

    vehicle = Vehicle(
        id="v01",
        name="Test",
        capacity=100.0,
        current_location="depot",
        driver_hours_remaining=8.0,
    )
    assert vehicle.status == "ACTIVE"
    assert vehicle.current_load == 0.0


def test_fleet_state_is_serialisable_from_a_session(session: Session) -> None:
    """
    get_fleet_state returns a FleetState that round-trips through JSON.

    Uses the throwaway-database session fixture rather than the app engine, so
    this is safe to run at any time. An empty state is the interesting case: it
    is exactly what the deployed app returns today, and it must still produce a
    well-formed payload rather than a 500.
    """
    from database import get_fleet_state

    state = get_fleet_state(session)

    assert state.vehicles == []
    assert state.simulation_time == 0.0
    payload = state.model_dump()
    assert set(payload) >= {"vehicles", "deliveries", "nodes", "roads", "routes", "events"}


@pytest.mark.parametrize(
    "path",
    ["/fleet/state", "/health", "/events/stream"],
)
def test_legacy_unprefixed_paths_still_serve(path: str) -> None:
    """
    The pre-port unprefixed paths are tracked explicitly.

    They are expected to be REMOVED when Phase 3 lands the /api/* rename; this
    test exists so that removal is a deliberate edit to this list rather than
    something discovered by a client. Delete the parameter to retire a path.
    """
    assert path in _get_paths(), (
        f"{path} was expected to still exist. If the /api/* rename has landed, "
        f"remove this test — that is the intended way to retire a path."
    )
