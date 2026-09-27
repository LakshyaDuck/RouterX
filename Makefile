# RouterX — local development entry points.
#
# Why this file exists at all: the checked-in `backend/app/.venv` is root-owned
# on this machine, and `uv sync` cannot replace a venv it does not own. Every
# uv-backed target below therefore exports UV_PROJECT_ENVIRONMENT, so the
# working venv is `.venv-user/`. That is not a preference — without it, `uv
# sync` fails with "Permission denied: .venv/lib64" and `uv run` tries to write
# the same unwritable path. If the root-owned `.venv` is ever removed, drop the
# export and the rest of this file still works.
#
# Run `make help` for the target list.

COMPOSE     := docker compose -f backend/docker-compose.yml
BACKEND     := backend/app
FRONTEND    := frontend
VENV_ENV    := .venv-user

# Host-side DSNs. The committed backend/.env holds the Compose service names
# (`db`, `redis`) because that is what resolves *inside* the Compose network; a
# process running on the host cannot resolve those and needs localhost. The
# compose file overrides both with `environment:` for the same reason.
HOST_POSTGRES_DSN := postgresql+psycopg://vrp:vrp_local_dev@127.0.0.1:5432/vrp
HOST_REDIS_URL    := redis://127.0.0.1:6379/0

# The API port the host targets use. 8000 is frequently already taken by another
# stack on a shared machine; the committed compose maps the container to 8000
# regardless, so this only affects `make api` and `make smoke`.
API_PORT ?= 8010

.DEFAULT_GOAL := help
.PHONY: help install db-up db-down api worker seed web reset-db up down logs health \
        lint test check smoke psql redis-cli

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Sync backend (uv) and frontend (Bun) dependencies
	cd $(BACKEND) && UV_PROJECT_ENVIRONMENT=$(VENV_ENV) uv sync --frozen
	cd $(FRONTEND) && bun install

# ── Datastores ───────────────────────────────────────────────────────────
# `db` only, not `api`/`worker`: those are meant to run on the host with
# auto-reload while writing code. An nginx bundle or a non-reloading uvicorn has
# to be rebuilt to show one changed line, which defeats the point.

db-up: ## Start Postgres + Redis and wait until both are healthy
	$(COMPOSE) up -d --wait db redis

db-down: ## Stop Postgres + Redis (data volume is kept)
	$(COMPOSE) stop db redis

psql: ## Open a psql shell on the dev database
	docker exec -it vrp-backend-db-1 psql -U vrp -d vrp

redis-cli: ## Open a redis-cli shell
	docker exec -it vrp-backend-redis-1 redis-cli

reset-db: ## Destroy the database volume and start clean (DESTRUCTIVE)
	$(COMPOSE) down -v
	$(MAKE) db-up

# ── Application processes (on the host) ──────────────────────────────────

api: ## Run the FastAPI app on the host with auto-reload (API_PORT, default 8010)
	cd $(BACKEND) && \
		UV_PROJECT_ENVIRONMENT=$(VENV_ENV) \
		POSTGRES_DSN=$(HOST_POSTGRES_DSN) \
		REDIS_URL=$(HOST_REDIS_URL) \
		uv run --frozen uvicorn main:app --reload --port $(API_PORT)

worker: ## Run the arq worker on the host
	cd $(BACKEND) && \
		UV_PROJECT_ENVIRONMENT=$(VENV_ENV) \
		POSTGRES_DSN=$(HOST_POSTGRES_DSN) \
		REDIS_URL=$(HOST_REDIS_URL) \
		uv run --frozen arq worker.WorkerSettings

web: ## Run the Vite dev server on the host (port 5173)
	cd $(FRONTEND) && bun run dev

# ── Whole stack in Docker ────────────────────────────────────────────────
# For demos and for reproducing the deployed shape. The bind mounts and the
# baked venvs mean this is slower to iterate against than the host targets.

up: ## Start the whole stack in Docker (api + worker + db + redis)
	$(COMPOSE) up --build

down: ## Stop every container started by compose
	$(COMPOSE) down

logs: ## Tail the compose logs
	$(COMPOSE) logs -f

# ── Quality gates ────────────────────────────────────────────────────────
# `check` is the per-phase gate: lint and the full suite, in that order,
# because a lint failure is cheaper to read than a test failure caused by it.

lint: ## Lint the backend (ruff)
	cd $(BACKEND) && UV_PROJECT_ENVIRONMENT=$(VENV_ENV) uv run --frozen ruff check .

test: ## Run the backend test suite (throwaway DB; no Postgres needed)
	cd $(BACKEND) && UV_PROJECT_ENVIRONMENT=$(VENV_ENV) uv run --frozen pytest -q

check: lint test ## Lint and test the backend

health: ## Curl the health endpoint of a host-run API
	@curl -s http://127.0.0.1:$(API_PORT)/health | head -c 400; echo

smoke: ## Assert the API answers /health and /fleet/state (needs `make api` running)
	@curl -sf http://127.0.0.1:$(API_PORT)/health >/dev/null \
		&& echo "  /health        ok" \
		|| { echo "  /health        FAILED"; exit 1; }
	@curl -sf http://127.0.0.1:$(API_PORT)/fleet/state >/dev/null \
		&& echo "  /fleet/state   ok" \
		|| { echo "  /fleet/state   FAILED"; exit 1; }
