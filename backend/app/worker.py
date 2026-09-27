"""
arq worker process. This is what runs the OR-Tools solver OFF the FastAPI
request thread — see the earlier reasoning: a warm-start repair can take
200ms-2s depending on fleet size, which is too slow to hold an HTTP worker
open for.

Flow: an event lands on a Redis Stream -> a consumer in main.py reads it ->
enqueues a job here via arq -> this worker picks it up -> runs the solver ->
writes the result back to Postgres -> publishes the update over SSE.
"""

from arq.connections import RedisSettings

from app_settings import settings


async def repair_route(ctx, event_payload: dict) -> dict:
    """
    Placeholder for the actual OR-Tools warm-start repair call.
    Receives one event (new_order / traffic_update / vehicle_breakdown)
    and the ID of the affected route-set, re-solves ONLY that subproblem
    seeded with the previous solution (see warm-start discussion).
    """
    # from solver import warm_start_repair
    # result = warm_start_repair(event_payload)
    # persist result, publish to SSE subscribers
    return {"status": "processed", "event": event_payload}


class WorkerSettings:
    functions = [repair_route]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Keep result data around briefly for debugging/inspection via arq's
    # own result-store; not a substitute for your Postgres event log.
    keep_result = 3600
