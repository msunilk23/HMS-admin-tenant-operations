#!/bin/sh
set -eu

echo "→ Running Alembic migrations..."
alembic upgrade head

echo "→ Ensuring schema columns and indexes..."
python -m app.scripts.ensure_schema

echo "→ Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
