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

Compose requires `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_DB_URL_PASSWORD`,
`PGADMIN_DEFAULT_EMAIL`, and `PGADMIN_DEFAULT_PASSWORD` from the shell or root
`.env` file. Copy `.env.example`, replace every development/example credential,
and then start Compose. Compose intentionally has no embedded credential
fallbacks.

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

The GitHub stabilization workflow requires repository Actions secrets
`CI_POSTGRES_PASSWORD` and `CI_SECRET_KEY`. Use dedicated CI-only values; never
reuse development, UAT, or production credentials.

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

## Backup and restore validation

Run this exercise against a disposable restore database before approving a
release. It does not overwrite the source database.

```bash
export PGPASSWORD='<database-password>'
pg_dump -h localhost -p 5433 -U hospital_user -d hospital \
  -Fc -f hms-release-a.dump

createdb -h localhost -p 5433 -U hospital_user hms_release_a_restore
pg_restore -h localhost -p 5433 -U hospital_user \
  -d hms_release_a_restore --exit-on-error hms-release-a.dump

psql -h localhost -p 5433 -U hospital_user -d hms_release_a_restore \
  -c "SELECT * FROM public.alembic_version;"
```

Verify that `public.alembic_version` reports the approved head, all expected
tenant schemas exist, representative patient/visit/audit records have matching
counts, and application read-only smoke queries succeed. Drop only the named
disposable restore database after evidence has been retained:

```bash
dropdb -h localhost -p 5433 -U hospital_user hms_release_a_restore
```

Never run `pg_restore --clean` against the source, UAT, or production database.

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
