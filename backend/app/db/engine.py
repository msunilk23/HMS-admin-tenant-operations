from collections.abc import AsyncGenerator
from contextvars import ContextVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# ContextVar holding the current tenant's schema name (set by TenantMiddleware)
tenant_schema_var: ContextVar[str] = ContextVar("tenant_schema", default="public")


class _TenantSession(AsyncSession):
    """
    AsyncSession subclass that re-applies SET search_path after every commit.

    After session.commit(), asyncpg may start a new implicit transaction on a
    connection whose search_path has been reset (e.g. pool re-acquisition or
    asyncpg internals). Re-setting it here means every route handler gets a
    consistent search_path without any per-handler boilerplate.
    """

    async def commit(self) -> None:
        await super().commit()
        schema = tenant_schema_var.get()
        await self.execute(text(f'SET search_path TO "{schema}", public'))

engine_kwargs = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True,
}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update({
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    })
else:
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
    })

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=_TenantSession,
)


async def init_db() -> None:
    """Called at application startup; applies lightweight schema migrations."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        
        # Check if users table exists first
        table_exists = await conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'users'
            );
        """))
        table_exists_result = table_exists.scalar()
        
        # Only apply migrations if users table exists
        if table_exists_result:
            # Add username column if it doesn't exist yet (idempotent migration)
            await conn.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name   = 'users'
                          AND column_name  = 'username'
                    ) THEN
                        ALTER TABLE public.users ADD COLUMN username VARCHAR(50);
                        -- Back-fill existing rows with a unique placeholder derived from email
                        UPDATE public.users
                           SET username = LOWER(SPLIT_PART(email, '@', 1))
                                       || LPAD(CAST(EXTRACT(EPOCH FROM NOW())::BIGINT % 10000 AS TEXT), 4, '0')
                         WHERE username IS NULL;
                        ALTER TABLE public.users ALTER COLUMN username SET NOT NULL;
                        CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON public.users (username);
                    END IF;
                END $$;
            """))
            # Add phone column if it doesn't exist yet (idempotent migration)
            await conn.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name   = 'users'
                          AND column_name  = 'phone'
                    ) THEN
                        ALTER TABLE public.users ADD COLUMN phone VARCHAR(20);
                    END IF;
                END $$;
            """))
            # Add tenant_name column if it doesn't exist yet (idempotent migration)
            await conn.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name   = 'users'
                          AND column_name  = 'tenant_name'
                    ) THEN
                        ALTER TABLE public.users ADD COLUMN tenant_name VARCHAR(63);
                        -- Back-fill from the tenants table
                        UPDATE public.users u
                           SET tenant_name = t.schema_name
                          FROM public.tenants t
                         WHERE t.id = u.tenant_id;
                        ALTER TABLE public.users ALTER COLUMN tenant_name SET NOT NULL;
                    END IF;
                END $$;
            """))

            # Add password-change enforcement columns if they don't exist yet.
            # New users must be forced to change their password on first login. Existing
            # production users should be initialized to false to avoid locking everyone out
            # until an explicit admin reset or password-change event occurs.
            await conn.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name   = 'users'
                          AND column_name  = 'must_change_password'
                    ) THEN
                        ALTER TABLE public.users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT TRUE;
                        UPDATE public.users SET must_change_password = FALSE;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name   = 'users'
                          AND column_name  = 'password_changed_at'
                    ) THEN
                        ALTER TABLE public.users ADD COLUMN password_changed_at TIMESTAMP NULL;
                    END IF;
                END $$;
            """))


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a DB session with the correct
    tenant search_path already set.
    """
    schema = tenant_schema_var.get()
    async with AsyncSessionLocal() as session:
        # Set PostgreSQL search_path for this session so all queries
        # are scoped to the tenant schema without explicit schema prefixes.
        await session.execute(
            __import__("sqlalchemy").text(f'SET search_path TO "{schema}", public')
        )
        yield session
