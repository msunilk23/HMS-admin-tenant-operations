"""
Alembic env.py — custom multi-tenant setup.

Running `alembic upgrade head` will:
1. Run migrations on the `public` schema (tenants + users tables).
2. For every active tenant schema found in public.tenants, run the
   same migrations on that tenant's schema.

This means adding a new table migration will automatically deploy it
to ALL existing tenant schemas.
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ensure app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.base import Base  # noqa: E402
# Import all models so Alembic autogenerate can detect them
import app.models.public.user  # noqa: F401, E402
import app.models.public.tenant_feature  # noqa: F401, E402
import app.models.public.audit_log  # noqa: F401, E402
import app.models.public.platform_audit_log  # noqa: F401, E402
import app.models.tenant  # noqa: F401, E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use DATABASE_URL from environment if set (Docker / CI)
database_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
# Convert sync URL to async driver for alembic
if database_url and not database_url.startswith("postgresql+asyncpg"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Escape % for configparser interpolation (e.g. passwords containing special chars)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def do_run_migrations(connection: Connection, schema: str = "public") -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table="alembic_version",
        version_table_schema=schema,
        include_schemas=True,
        compare_type=True,
    )
    with context.begin_transaction():
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # 1. Migrate the public schema first (dedicated connection)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations, schema="public")
        await conn.commit()

    # 2. Collect tenant schemas (fresh connection)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT schema_name FROM public.tenants WHERE is_active = true")
        )
        tenant_schemas = [row[0] for row in result.fetchall()]

    # 3. Migrate each tenant schema — dedicated connection per schema
    for schema in tenant_schemas:
        async with engine.connect() as conn:
            await conn.run_sync(do_run_migrations, schema=schema)
            await conn.commit()

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


run_migrations_online()
