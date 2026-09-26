"""
Single source of truth for config, loaded once from environment variables.
Both main.py (API process) and worker.py (arq process) import this — so a
docker-compose env_file change propagates to both without duplication.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_dsn: str = "postgresql+psycopg://vrp:vrp_local_dev@db:5432/vrp"
    redis_url: str = "redis://redis:6379/0"

    class Config:
        env_file = ".env"


settings = Settings()
