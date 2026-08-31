"""P29.2 PostgreSQL linkage and concurrent invoice uniqueness tests."""

import os
import socket
import uuid
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PG_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital",
)


def _postgres_reachable() -> bool:
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="PostgreSQL is not reachable",
)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def linkage_schema():
    schema = f"test_p292_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET search_path TO "{schema}"'))
        await connection.execute(text("""
            CREATE TABLE pharmacy_dispenses (
                id UUID PRIMARY KEY,
                invoice_id UUID NULL
            )
        """))
        await connection.execute(text("""
            CREATE TABLE invoices (
                id UUID PRIMARY KEY,
                pharmacy_dispense_id UUID NULL,
                CONSTRAINT uq_invoices_pharmacy_dispense UNIQUE (pharmacy_dispense_id),
                CONSTRAINT fk_invoices_pharmacy_dispense_id
                    FOREIGN KEY (pharmacy_dispense_id) REFERENCES pharmacy_dispenses(id)
            )
        """))
        await connection.execute(text("""
            ALTER TABLE pharmacy_dispenses
            ADD CONSTRAINT fk_pharmacy_dispenses_invoice_id
            FOREIGN KEY (invoice_id) REFERENCES invoices(id)
        """))
        await connection.execute(text("""
            CREATE UNIQUE INDEX ix_pharmacy_dispenses_invoice_id
            ON pharmacy_dispenses (invoice_id)
        """))
    yield schema, engine
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_linkage_foreign_keys_and_one_invoice_per_dispense(linkage_schema):
    schema, engine = linkage_schema
    dispense_id = uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(text(f'SET search_path TO "{schema}"'))
        await connection.execute(
            text("INSERT INTO pharmacy_dispenses (id) VALUES (:id)"),
            {"id": dispense_id},
        )
        await connection.execute(
            text("INSERT INTO invoices (id, pharmacy_dispense_id) VALUES (:id, :dispense_id)"),
            {"id": uuid.uuid4(), "dispense_id": dispense_id},
        )
        with pytest.raises(Exception):
            await connection.execute(
                text("INSERT INTO invoices (id, pharmacy_dispense_id) VALUES (:id, :dispense_id)"),
                {"id": uuid.uuid4(), "dispense_id": dispense_id},
            )


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_same_dispense_insert_has_one_winner(linkage_schema):
    schema, engine = linkage_schema
    dispense_id = uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(text(f'SET search_path TO "{schema}"'))
        await connection.execute(
            text("INSERT INTO pharmacy_dispenses (id) VALUES (:id)"),
            {"id": dispense_id},
        )

    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def insert_invoice():
        session = maker()
        try:
            await session.execute(text(f'SET search_path TO "{schema}"'))
            await session.execute(
                text("INSERT INTO invoices (id, pharmacy_dispense_id) VALUES (:id, :dispense_id)"),
                {"id": uuid.uuid4(), "dispense_id": dispense_id},
            )
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False
        finally:
            await session.close()

    results = await __import__("asyncio").gather(insert_invoice(), insert_invoice())
    assert sum(results) == 1
    async with engine.connect() as connection:
        await connection.execute(text(f'SET search_path TO "{schema}"'))
        count = await connection.scalar(
            text("SELECT COUNT(*) FROM invoices WHERE pharmacy_dispense_id = :id"),
            {"id": dispense_id},
        )
    assert count == 1
