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

Default credentials after seed:
- **Hospital Admin**: `admin@shankar-hospital.in` / `ChangeMe@123`
- **Super Admin**: `superadmin@smarthosp.in` / `SuperAdmin@123`

> ⚠️ Change these passwords immediately after first login.

### 5. Install frontend dependencies (local dev)

```bash
cd frontend
npm install
npm run dev
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
