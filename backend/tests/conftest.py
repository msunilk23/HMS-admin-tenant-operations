"""
Pytest configuration for tests.

Provides fixtures for database, settings, and async session management.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Set required environment variables before importing settings
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5432/hospital")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

# Now safe to import app config
from app.core.config import settings


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def async_engine():
    """Create async engine for test database."""
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def async_session_maker(async_engine):
    """Create async session factory."""
    return async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
async def async_session(async_session_maker):
    """Provide a test async session."""
    async with async_session_maker() as session:
        yield session


@pytest.fixture
def settings_fixture():
    """Provide application settings."""
    return settings


@pytest.fixture
def mock_session():
    """Provide a mock async session for unit tests."""
    from unittest.mock import AsyncMock
    return AsyncMock(spec=AsyncSession)
