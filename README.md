# RouterX — Dynamic Fleet Dispatch & Delivery Control Tower

RouterX is a real-time, event-driven vehicle routing, dispatching, and control tower platform. It combines dynamic routing with continuous re-optimization, explainable automated dispatch decisions, and a real-time interactive operations dashboard.

---

## Architecture Overview

- **Backend**: FastAPI + SQLModel ORM + PostgreSQL with connection pooling and pre-ping health checks. Pure-Python graph Dijkstra engine with incremental re-optimization and explainability auditing.
- **Frontend**: React 19 + Vite + Tailwind CSS + Leaflet (React-Leaflet) interactive operations map and control panels.
- **Reverse Proxy / Production Server**: Nginx with SPA routing fallback, gzip compression, asset caching, and backend API forwarding.
- **Containerization**: Production Dockerfiles for backend and frontend with Docker Compose orchestration.

---

## Quick Start with Docker (Production Ready)

The simplest way to run the entire stack in a production-equivalent environment:

```bash
# 1. Clone the repository and navigate to project root
cd RouterX

# 2. Configure environment variables (or copy example)
cp .env.example .env

# 3. Build and launch all services (PostgreSQL + Backend + Frontend/Nginx)
docker compose up --build -d

# 4. View service status
docker compose ps
```

- **Frontend Dashboard**: [http://localhost](http://localhost) (or port configured in `FRONTEND_PORT`)
- **Backend API**: [http://localhost:8000](http://localhost:8000)
- **API Documentation (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **API Health Check**: [http://localhost:8000/health](http://localhost:8000/health) or [http://localhost:8000/api/health](http://localhost:8000/api/health)

To stop the containers:
```bash
docker compose down
```

---

## Local Development (Without Docker)

### Prerequisites
- Python 3.11+
- Node.js 20+ or Bun 1.1+
- PostgreSQL 14+ (or run `docker compose up -d db` to run only Postgres)

### 1. Database Setup
Ensure PostgreSQL is running and create the database:
```sql
CREATE DATABASE fleet_db;
```

### 2. Backend Setup
```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure environment
cp .env.example .env
# Edit .env to set your DATABASE_URL

# Start backend server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# Or directly: python main.py
```

### 3. Frontend Setup
```bash
cd frontend

# Install dependencies (using bun or npm)
bun install
# or: npm install

# Start Vite development server
bun run dev
# or: npm run dev
```

Visit [http://localhost:5173](http://localhost:5173).

---

## Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | *(required in prod)* | PostgreSQL connection string (`postgresql://user:pass@host:port/dbname`) |
| `ENVIRONMENT` | `production` | Environment mode (`production`, `development`, `test`) |
| `HOST` | `0.0.0.0` | Backend bind host |
| `PORT` | `8000` | Backend bind port |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CORS_ORIGINS` | *(allowed localhost ports in dev)* | Comma-separated list of allowed origins (e.g. `https://app.mydomain.com`) |
| `AUTO_SEED_DEMO` | `true` | Auto-seed deterministic demo scenario on empty database |
| `DB_POOL_SIZE` | `10` | SQLAlchemy / SQLModel connection pool size |
| `DB_MAX_OVERFLOW` | `20` | Max overflow connections above pool size |
| `DB_POOL_RECYCLE` | `300` | Pool connection recycle time in seconds |
| `DB_POOL_PRE_PING` | `true` | Validate connections before checkout |
| `VITE_API_BASE_URL` | `/api` | Base API path used by frontend |
| `FRONTEND_PORT` | `80` (docker) / `5173` (dev) | Frontend public listening port |
| `POSTGRES_USER` | `postgres` | PostgreSQL username (for docker compose) |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL password (for docker compose) |
| `POSTGRES_DB` | `fleet_db` | PostgreSQL database name (for docker compose) |

---

## Running Automated Tests

To execute the full 136-test suite:
```bash
cd backend
pytest -v
```

All tests run against standard SQLModel schemas and pure algorithmic models.

---

## Health Checks & Monitoring

- **Container Health Check**: Built-in Docker `HEALTHCHECK` instructions for all services.
- **Top-Level Health Endpoint**: `GET /health` returns `{"status": "ok", "service": "Delivery Control Tower"}`.
- **API Health Endpoint**: `GET /api/health` returns status and service verification.
- **Nginx Health**: `GET /nginx-health` returns `healthy`.
