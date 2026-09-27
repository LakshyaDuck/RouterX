"""
Application Configuration.
Loads settings from environment variables and .env files.
Provides environment-specific defaults and strict production validation.
"""

import os
import logging
from pathlib import Path
from typing import List

# Attempt to load .env file if python-dotenv is present
try:
    from dotenv import load_dotenv
    # Look for .env in current directory, backend dir, or project root
    current_file = Path(__file__).resolve()
    backend_dir = current_file.parent.parent
    root_dir = backend_dir.parent

    for candidate in (Path.cwd() / ".env", backend_dir / ".env", root_dir / ".env"):
        if candidate.is_file():
            load_dotenv(dotenv_path=candidate, override=False)
            break
except ImportError:
    pass

logger = logging.getLogger("routerx.config")

# Environment identification
ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()
IS_PRODUCTION = ENVIRONMENT in ("production", "prod")

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Database configuration
_raw_db_url = os.getenv("DATABASE_URL", "").strip()

if not _raw_db_url:
    # Try individual Postgres variables if provided
    pg_user = os.getenv("POSTGRES_USER")
    pg_password = os.getenv("POSTGRES_PASSWORD")
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB")

    if pg_user and pg_password and pg_host and pg_db:
        _raw_db_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
    elif IS_PRODUCTION:
        raise RuntimeError(
            "DATABASE_URL environment variable is required in production environment. "
            "Please configure DATABASE_URL (e.g. postgresql://user:password@host:5432/dbname)."
        )
    else:
        _raw_db_url = "postgresql://postgres:postgres@localhost:5432/fleet_db"
        logger.warning(
            "DATABASE_URL not set in %s environment; defaulting to local development URL.",
            ENVIRONMENT
        )

# Normalize legacy postgres:// prefix (common on Heroku, Render, AWS) to postgresql://
if _raw_db_url.startswith("postgres://"):
    _raw_db_url = _raw_db_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_db_url

# Connection pool settings
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "300"))
DB_POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "true").lower() in ("true", "1", "yes")

# Auto-seed deterministic demo scenario when starting with empty database
AUTO_SEED_DEMO = os.getenv("AUTO_SEED_DEMO", "true").lower() in ("true", "1", "yes")

# CORS Configuration
def get_cors_origins() -> List[str]:
    cors_str = os.getenv("CORS_ORIGINS", "").strip()
    if cors_str:
        return [orig.strip() for orig in cors_str.split(",") if orig.strip()]
    if IS_PRODUCTION:
        return []
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

CORS_ORIGINS = get_cors_origins()
