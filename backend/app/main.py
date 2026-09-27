"""
Re-export main application from backend.main for compatibility with deployment commands
that run either `uvicorn main:app` or `uvicorn app.main:app`.
"""

import sys
from pathlib import Path

# Ensure backend root and project root are in sys.path
backend_dir = Path(__file__).resolve().parent.parent
project_root = backend_dir.parent

for p in (str(backend_dir), str(project_root)):
    if p not in sys.path:
        sys.path.insert(0, p)

from main import app, lifespan

__all__ = ["app", "lifespan"]
