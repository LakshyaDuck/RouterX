"""
FastAPI application entry point.
"""

from pathlib import Path
import sys
import os
import logging
from contextlib import asynccontextmanager

# Ensure project root and backend dir are in sys.path so simulation module is importable
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
for p in (str(BASE_DIR), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    CORS_ORIGINS,
    AUTO_SEED_DEMO,
    IS_PRODUCTION,
    LOG_LEVEL,
    HOST,
    PORT,
)
from app.database import init_db, has_fleet_data, reset_fleet_database
from app.routers import fleet
from app.routers import routing as routing_router
from app.routers import simulation as simulation_router

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("routerx.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup:
    1. Initialize the PostgreSQL database schema via SQLModel.
    2. If no state exists yet and AUTO_SEED_DEMO is True, seed deterministic demo scenario.
    3. Persist the state in PostgreSQL so subsequent restarts are fast.
    """
    logger.info("Initializing database schema...")
    init_db()

    if not has_fleet_data():
        if AUTO_SEED_DEMO:
            logger.info("No existing fleet data found — seeding deterministic demo scenario...")
            reset_fleet_database()
            logger.info("State saved to database with 8 vehicles, 40 deliveries.")
        else:
            logger.info("No existing fleet data found. Auto-seed disabled.")
    else:
        logger.info("Existing fleet state loaded from database.")

    yield


app = FastAPI(
    title="Delivery Control Tower",
    description="Real-time delivery fleet management API backed by SQLModel & PostgreSQL",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware configuration
# Specifically permits the production Vercel frontend (https://router-x.vercel.app),
# custom configured FRONTEND_URL / CORS_ORIGINS, and preview domains matching *.vercel.app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

app.include_router(fleet.router)
app.include_router(routing_router.router)
app.include_router(simulation_router.router)


@app.get("/")
async def root():
    return {
        "message": "Delivery Control Tower API",
        "docs": "/docs",
        "health": "/api/health",
        "database": "PostgreSQL (SQLModel ORM)",
    }


@app.get("/health", tags=["health"])
async def root_health():
    """Top-level health check endpoint for container orchestrators and load balancers."""
    return {"status": "ok", "service": "Delivery Control Tower"}


@app.post("/optimize", response_model=fleet.OptimizationPlan)
async def root_optimize(
    req: fleet.Optional[fleet.OptimizeRequest] = None,
    session: fleet.Session = fleet.Depends(fleet.get_session),
):
    """Alias for POST /api/optimize."""
    return await fleet.optimize_fleet(req, session)


@app.post("/events", response_model=fleet.EventResponse)
async def root_post_event(
    event: fleet.Event,
    session: fleet.Session = fleet.Depends(fleet.get_session),
):
    """Alias for POST /api/events."""
    return await fleet.post_event(event, session)


@app.post("/vehicles", response_model=fleet.FleetState)
async def root_create_vehicle(
    req: fleet.CreateVehicleRequest,
    session: fleet.Session = fleet.Depends(fleet.get_session),
):
    """Alias for POST /api/vehicles."""
    return await fleet.create_vehicle(req, session)


@app.post("/deliveries", response_model=fleet.FleetState)
async def root_create_delivery(
    req: fleet.CreateDeliveryRequest,
    session: fleet.Session = fleet.Depends(fleet.get_session),
):
    """Alias for POST /api/deliveries."""
    return await fleet.create_delivery(req, session)


@app.post("/nodes", response_model=fleet.FleetState)
async def root_create_node(
    req: fleet.CreateNodeRequest,
    session: fleet.Session = fleet.Depends(fleet.get_session),
):
    """Alias for POST /api/nodes."""
    return await fleet.create_node(req, session)


# Root GET aliases for clients querying without /api prefix
@app.get("/state", response_model=fleet.FleetState)
async def root_get_state(session: fleet.Session = fleet.Depends(fleet.get_session)):
    """Alias for GET /api/state."""
    return await fleet.fetch_fleet_state(session)


@app.get("/vehicles", response_model=list[fleet.Vehicle])
async def root_get_vehicles(session: fleet.Session = fleet.Depends(fleet.get_session)):
    """Alias for GET /api/vehicles."""
    return await fleet.fetch_vehicles(session)


@app.get("/deliveries", response_model=list[fleet.Delivery])
async def root_get_deliveries(session: fleet.Session = fleet.Depends(fleet.get_session)):
    """Alias for GET /api/deliveries."""
    return await fleet.fetch_deliveries(session)


@app.get("/routes", response_model=list[fleet.Route])
async def root_get_routes(session: fleet.Session = fleet.Depends(fleet.get_session)):
    """Alias for GET /api/routes."""
    return await fleet.fetch_routes(session)


@app.get("/nodes", response_model=list[fleet.Node])
async def root_get_nodes(session: fleet.Session = fleet.Depends(fleet.get_session)):
    """Alias for GET /api/nodes."""
    return await fleet.fetch_nodes(session)


@app.get("/roads", response_model=list[fleet.Road])
async def root_get_roads(session: fleet.Session = fleet.Depends(fleet.get_session)):
    """Alias for GET /api/roads."""
    return await fleet.fetch_roads(session)


@app.get("/events", response_model=list[fleet.Event])
async def root_get_events(session: fleet.Session = fleet.Depends(fleet.get_session)):
    """Alias for GET /api/events."""
    return await fleet.fetch_events(session)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=not IS_PRODUCTION)

