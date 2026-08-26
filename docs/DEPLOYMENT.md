# Deployment and Release Runbook

## Services

`infra/docker-compose.yml` runs PostgreSQL 16, Redis 7, backend, frontend, nginx, and optional pgAdmin.

| Service | Local endpoint |
| --- | --- |
| Nginx | `http://localhost:80` |
| Frontend container | `http://localhost:5173` |
| Backend | `http://localhost:8000` |
| Swagger | `http://localhost:8000/api/docs` |
| pgAdmin | `http://localhost:5050` |
| PostgreSQL host port | `5433` |
| Redis host port | `6379` |

## Required configuration

Set a strong `SECRET_KEY`, PostgreSQL credentials, `DATABASE_URL`, and `REDIS_URL`. Configure `RAZORPAY_WEBHOOK_SECRET` before enabling online payments. Optional Cloudinary and Twilio credentials enable report storage and messaging. Never commit `.env` or payment secrets.

## Development startup

```bash
cd infra
docker compose up -d

docker compose ps
curl http://localhost:8000/health
```

The backend entrypoint runs schema initialization. For an explicit migration run from the backend environment:

```bash
cd backend
alembic upgrade head
```

The custom Alembic environment migrates `public` and every active tenant schema. New tenant schemas must be provisioned through the tenant service before tenant-scoped migrations are expected.

## Release checks

```bash
cd backend
pytest -q
python -m compileall -q app alembic/versions

cd ../frontend
npm ci
npm run type-check
npm run build

cd ../infra
docker compose config
docker compose build
```

Run migration and deployment checks against disposable PostgreSQL/Redis services. Do not use production data for migration experiments. Verify `/health`, `/api/docs`, login, tenant feature enforcement, WebSocket connectivity, and a complete OPD encounter before release.

## Operational safety

PostgreSQL is authoritative. Back up PostgreSQL before migrations, retain Redis as disposable supporting infrastructure, monitor backend logs, and verify that tenant-scoped audit, billing, lab, feedback, and roster records remain in the correct schema.

---

## Pharmacy release checks

For Pharmacy phases that add schema or seed data:

1. Run Alembic against a fresh database.
2. Run Alembic against an existing development database.
3. Verify tenant schemas receive the migration.
4. Load deterministic Pharmacy development/E2E seed data where configured.
5. Verify Medicine Master and formulary search.
6. Verify Doctor Prescription medicine selection/save/reload.
7. Verify zero stock never blocks prescribing once inventory exists.
8. For later phases verify GRN → batch stock → dispense → billing → stock ledger reconciliation.
9. Run the existing OPD regression suite.

Do not use production data for migration experiments.
