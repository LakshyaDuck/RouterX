"""
Single source of truth for config, loaded once from environment variables.
Both main.py (API process) and worker.py (arq process) import this — so a
docker-compose env_file change propagates to both without duplication.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_dsn: str = "postgresql+psycopg://vrp:vrp_local_dev@db:5432/vrp"
    redis_url: str = "redis://redis:6379/0"

    # Seed the deterministic demo city into an empty database on startup.
    #
    # On by default because an empty fleet renders as an empty dashboard: five
    # blank panels, no vehicles, no routes, and no way to tell a working system
    # from a broken one. With it on, `docker compose up` produces something you
    # can actually look at.
    #
    # Set to false for a deployment that supplies its own data, where seeding
    # would be actively wrong — a wiped production database coming back full of
    # invented vehicles and deliveries is worse than coming back empty. Seeding
    # only ever runs against an EMPTY database (see database.seed_fleet_state),
    # so this flag can never overwrite real data; it only controls whether an
    # empty database is filled with the demo city or left empty.
    seed_demo_data: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
