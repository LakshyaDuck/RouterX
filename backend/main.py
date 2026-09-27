"""
FastAPI application entry point for backend root.
Re-exports the application from app.main.
"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
for p in (str(BASE_DIR), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.main import app, lifespan

__all__ = ["app", "lifespan"]

if __name__ == "__main__":
    import uvicorn
    from app.config import HOST, PORT, IS_PRODUCTION
    uvicorn.run("main:app", host=HOST, port=PORT, reload=not IS_PRODUCTION)
