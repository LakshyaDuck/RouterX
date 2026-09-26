"""
Entrypoint. Deliberately minimal — proves the wiring (Postgres/PostGIS,
Redis, SSE push) works end-to-end. Solver logic, SQLModel schema, and
Alembic migrations are the next layer to build on top of this.

No OSRM here: this system runs against a synthetic/imaginary world, so
travel costs are computed directly (Euclidean distance — see
distance_matrix.py) rather than fetched from a real-road-network router.
"""

from datetime import datetime, timezone

import redis.asyncio as redis
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, text

from app_settings import settings
from database import engine, get_fleet_state, get_session, init_db
from models import FleetState

app = FastAPI(
    title="VRP Real-Time System",
    version="0.1.0",
    openapi_tags=[
        {"name": "general", "description": "Service metadata and home page data."},
        {"name": "fleet", "description": "Live fleet state read from Postgres."},
        {"name": "health", "description": "Dependency reachability checks."},
        {"name": "events", "description": "Real-time push streams."},
    ],
)

# Frontend is a separate app/origin (its own dev server port, its own
# deploy). Without this, the browser blocks its requests to this API by
# default — CORS is enforced by the BROWSER, not something a missing
# config silently degrades; it fails outright on the first fetch.
# Replace allow_origins with your actual frontend origin(s) once that
# stack exists — "*" is fine for local dev, wrong for anything deployed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# engine comes from database.py — one engine shared by the API process, the
# arq worker, and Alembic. Defining a second engine here meant /health could
# report on a different database than the routes actually used.
redis_client = redis.from_url(settings.redis_url, decode_responses=True)


# ── Home page contract ──────────────────────────────────────────────────
# The frontend is a separate app with its own build and deploy, so it renders
# this payload itself rather than the API shipping markup. Treat it as a
# contract: adding a field is safe, renaming or removing one is breaking.


class HomeLink(BaseModel):
    """One link the home page can render — nav, cards, or a button row."""

    label: str
    href: str
    description: str


class HomeResponse(BaseModel):
    title: str
    tagline: str
    description: str
    status: str
    version: str
    generated_at: datetime
    endpoints: list[HomeLink]
    features: list[str]


@app.get("/", response_model=HomeResponse, tags=["general"], summary="Home page data")
async def home() -> HomeResponse:
    """
    Data for the frontend home page.

    `status` is a static "ok" on purpose: it reports that this API process is
    alive and serving. It deliberately does NOT reflect Postgres/Redis
    reachability — /health is the single place that does, and duplicating the
    check here would give you two answers that could disagree.
    """
    return HomeResponse(
        title="VRP Real-Time System",
        tagline="Incremental vehicle routing with warm-start repair",
        description=(
            "Real-time vehicle routing and dispatch. Events such as new "
            "orders, traffic updates, and vehicle breakdowns are ingested "
            "through Redis Streams and trigger a warm-started re-solve of "
            "only the affected routes, then push the patch to subscribers "
            "over server-sent events."
        ),
        status="ok",
        version="0.1.0",
        generated_at=datetime.now(timezone.utc),
        endpoints=[
            HomeLink(
                label="API Reference",
                href="/docs",
                description="Interactive OpenAPI docs for every endpoint.",
            ),
            HomeLink(
                label="Health",
                href="/health",
                description="Live Postgres/PostGIS and Redis reachability.",
            ),
            HomeLink(
                label="Live Events (SSE)",
                href="/events/stream",
                description="Streaming route-change notifications.",
            ),
            HomeLink(
                label="Fleet State",
                href="/fleet/state",
                description="Current vehicles, deliveries, routes, and events.",
            ),
        ],
        features=[
            "Real-time order and disruption ingestion",
            "Warm-start route repair (OR-Tools)",
            "PostGIS spatial queries",
            "Server-sent event push",
        ],
    )


@app.get(
    "/fleet/state",
    response_model=FleetState,
    tags=["fleet"],
    summary="Full fleet state from Postgres",
)
def fleet_state(session: Session = Depends(get_session)) -> FleetState:
    """
    Everything the control tower needs to draw the map, the vehicle list, and
    the event log. The DB-backed counterpart to GET / — the home page is
    static, this is what renders once there's data worth showing.

    Deliberately `def`, not `async def`: get_fleet_state is a blocking DB call,
    and FastAPI runs sync handlers in a threadpool. Declaring it async would
    block the event loop for every other in-flight request.
    """
    return get_fleet_state(session)


@app.get("/health", tags=["health"])
async def health():
    """
    Checks every dependency this system needs — Postgres, Redis — so a bad
    connection string surfaces here instead of as a confusing failure three
    layers deep later.

    PostGIS is reported separately and does NOT affect `ok`. It is an optional
    capability, not a liveness requirement: managed Postgres (Render, RDS,
    most hosted offerings) ships without the extension, and nothing in the
    code requires it — models.py stores coordinates as plain lat/lon floats.
    Folding it into `ok` would report a perfectly healthy deployment as broken.
    """
    checks = {}

    # Postgres
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1")).first()
            checks["postgres"] = {"ok": True}
    except Exception as e:
        checks["postgres"] = {"ok": False, "error": str(e)}

    # PostGIS — optional capability, excluded from the `ok` rollup below.
    try:
        with Session(engine) as session:
            version = session.exec(text("SELECT PostGIS_Version()")).first()
            checks["postgis"] = {
                "ok": True,
                "required": False,
                "version": version[0] if version else None,
            }
    except Exception as e:
        checks["postgis"] = {"ok": False, "required": False, "error": str(e)}

    # Redis
    try:
        pong = await redis_client.ping()
        checks["redis"] = {"ok": bool(pong)}
    except Exception as e:
        checks["redis"] = {"ok": False, "error": str(e)}

    all_ok = all(c.get("ok") for c in checks.values() if c.get("required", True))
    return {"ok": all_ok, "checks": checks}


@app.get("/events/stream", tags=["events"])
async def stream_events():
    """
    SSE endpoint — the "push, not poll" mechanism discussed earlier.
    Frontend (handled separately, per your note) subscribes here to get
    route-change notifications the instant the solver commits a patch,
    rather than polling GET /routes on an interval.
    """

    async def event_generator():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("route-updates")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe("route-updates")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.on_event("startup")
async def on_startup():
    # Delegates to database.init_db(), which creates tables from SQLModel
    # metadata and syncs the Postgres enum types. Once Alembic owns the
    # schema, this goes away entirely — Alembic becomes the only thing that
    # touches it.
    init_db()
