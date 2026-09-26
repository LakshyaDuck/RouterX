"""
Entrypoint. Deliberately minimal — proves the wiring (Postgres/PostGIS,
Redis, SSE push) works end-to-end. Solver logic, SQLModel schema, and
Alembic migrations are the next layer to build on top of this.

No OSRM here: this system runs against a synthetic/imaginary world, so
travel costs are computed directly (Euclidean distance — see
distance_matrix.py) rather than fetched from a real-road-network router.
"""

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlmodel import SQLModel, create_engine, Session, text

from app_settings import settings

app = FastAPI(title="VRP Real-Time System")

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

engine = create_engine(settings.postgres_dsn)
redis_client = redis.from_url(settings.redis_url, decode_responses=True)


@app.get("/health")
async def health():
    """
    Checks every local dependency this system needs — Postgres+PostGIS,
    Redis — so a docker compose misconfiguration surfaces here instead
    of as a confusing failure three layers deep later.
    """
    checks = {}

    # Postgres + PostGIS
    try:
        with Session(engine) as session:
            version = session.exec(text("SELECT PostGIS_Version()")).first()
            checks["postgis"] = {"ok": True, "version": version[0] if version else None}
    except Exception as e:
        checks["postgis"] = {"ok": False, "error": str(e)}

    # Redis
    try:
        pong = await redis_client.ping()
        checks["redis"] = {"ok": bool(pong)}
    except Exception as e:
        checks["redis"] = {"ok": False, "error": str(e)}

    all_ok = all(c.get("ok") for c in checks.values())
    return {"ok": all_ok, "checks": checks}


@app.get("/events/stream")
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
    # Creates tables from SQLModel metadata if they don't exist yet.
    # Once you have real models + Alembic migrations, this line goes away
    # entirely — Alembic becomes the only thing that touches schema.
    SQLModel.metadata.create_all(engine)

