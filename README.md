# Hospital Management System — OPD

Production-ready multi-tenant OPD management system built with FastAPI, React, and PostgreSQL.

## Quick Start (Development)

### Prerequisites
- Docker & Docker Compose
- Node.js 22+ (for local frontend development)
- Python 3.12+ (for local backend development)

### 1. Clone and configure environment

```bash
cp .env.example .env
# Edit .env — set a strong SECRET_KEY
```

### 2. Start all services

```bash
cd infra
docker compose up -d
```

Services started:
| Service | URL |
|---------|-----|
| Frontend | http://localhost:80 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/api/docs |
| pgAdmin | http://localhost:5050 |

### 3. Run database migrations

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
```

### 4. Seed the first tenant

```bash
python -m app.scripts.seed
```

The seed command generates unique temporary passwords for the Hospital Admin
and Super Admin and prints them exactly once. Store them securely and change
them immediately after the first login; fixed seed passwords are not supported.

### 5. Install frontend dependencies (local dev)

```bash
cd frontend
npm install
npm run dev
```

### 6. Run Task 7 browser verification

The controlled ICD-10 and medicine workflow uses an isolated PostgreSQL
tenant fixture and the real backend master-data APIs. It does not depend on
development seed records.

```bash
cd frontend
npm ci
npx playwright install chromium
npm run e2e
```

The fixture is created by `backend/tests/e2e_seed_task7.py` and cleaned up by
Playwright global teardown. The focused CI workflow is
.github/workflows/task7-e2e.yml.
```

---

## Project Structure

```
hospital-management-system/
├── backend/          FastAPI application
├── frontend/         React + Vite application
├── infra/            Docker Compose + Nginx + K8s manifests
├── PLAN.md           Full implementation plan
└── .env.example      Environment variable template
```

See [PLAN.md](./PLAN.md) for the complete architecture, database schema design, WebSocket events, and implementation phase roadmap.

Release documentation:

- [API contract](./docs/API.md)
- [OPD workflow](./docs/OPD_WORKFLOW.md)
- [State diagrams](./docs/STATE_DIAGRAMS.md)
- [RBAC matrix](./docs/RBAC_MATRIX.md)
- [Tenant architecture](./docs/TENANT_ARCHITECTURE.md)
- [Deployment runbook](./docs/DEPLOYMENT.md)
- [Data model](./docs/DATA_MODEL.md)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic |
| Frontend | React 18, Vite, TypeScript, shadcn/ui, Tailwind CSS |
| Database | PostgreSQL 16 (schema-per-tenant) |
| Cache | Redis 7 (pub/sub for WebSocket scaling) |
| Containerisation | Docker Compose (dev) + Kubernetes (prod) |
