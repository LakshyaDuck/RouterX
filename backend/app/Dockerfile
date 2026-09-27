# uv's official image ships uv pre-installed on top of a slim Python base —
# avoids a separate `pip install uv` layer.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# OR-Tools' Python wheel is pure-wheel on most platforms, but a couple of
# transitive deps (and OSRM client libs if you compile anything) want these.
# Kept minimal on purpose — add to this list only if a build actually fails
# without it, since every added package is another thing to patch/update.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Dependency layer, cached separately from app code ────────────────────
# Copying ONLY the lock/manifest files first means Docker's layer cache is
# invalidated by a dependency change, not by every source-code edit.
# This is the single biggest iteration-speed win uv gives you in Docker:
# `uv sync` reads uv.lock and installs exact pinned versions, fast, without
# needing network access to a package index at all if the wheel cache
# already has them from a previous build.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── App code layer ────────────────────────────────────────────────────────
COPY . .

# Now install the project itself (fast — deps are already resolved above).
# --no-dev drops the pytest/httpx/ruff dependency group: a deployed web
# service has no use for a test runner, and the group is resolved in
# uv.lock either way, so --frozen stays satisfied.
RUN uv sync --frozen --no-dev

EXPOSE 8000

# uv run executes inside the project's locked virtualenv without needing
# to `source .venv/bin/activate` manually.
# ${PORT:-8000} keeps local docker compose on 8000 while honoring the port
# Render injects. --reload is deliberately gone: it is a dev file-watcher,
# and in production it masks real startup errors behind endless restarts.
CMD ["sh", "-c", "uv run uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
