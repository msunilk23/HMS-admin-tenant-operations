"""Real PostgreSQL tenant-schema concurrency regression tests for existing Lab workflows."""

import asyncio
import os
import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.public.user import Tenant
from app.models.tenant import Department, Doctor, Invoice, LabOrder, LabResult, Patient, Visit
from app.models.tenant.lab_order import can_transition_lab_order
from app.services.lab_billing_service import create_lab_invoice_if_needed

PG_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")
_PREFIX = "test_lab_concurrency_"


def _postgres_reachable() -> bool:
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable")


class RecordingPublisher:
    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []
        self._lock = asyncio.Lock()

    async def broadcast(self, tenant: str, channel: str, message: dict) -> None:
        async with self._lock:
            self.events.append((tenant, channel, message.copy()))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def lab_context():
    suffix = uuid.uuid4().hex[:12]
    schema = f"{_PREFIX}{suffix}"
    tenant_id = uuid.uuid4()
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text("""
                INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, plan, is_active, display_token, session_version, created_at, updated_at)
                VALUES (:id, :schema, 'Lab Concurrency', :email, 'enterprise', true, :token, 0, now(), now())
            """), {"id": tenant_id, "schema": schema, "email": f"{schema}@test.invalid", "token": f"display-{suffix}"})
            await connection.execute(text(f'SET search_path TO "{schema}", public'))
            await connection.run_sync(lambda sync_connection: Base.metadata.create_all(sync_connection, tables=tables))

        async def new_session() -> AsyncSession:
            session = maker()
            await session.execute(text(f'SET search_path TO "{schema}", public'))
            assert await session.scalar(text("SELECT current_schema()")) == schema
            assert schema in await session.scalar(text("SHOW search_path"))
            return session

        async with await new_session() as session:
            department = Department(id=uuid.uuid4(), name="Lab Concurrency")
            patient = Patient(id=uuid.uuid4(), uhid=f"LAB-{suffix[:6]}", first_name="Concurrent", last_name="Patient", gender="female", phone="9000000001")
            doctor = Doctor(id=uuid.uuid4(), user_id=uuid.uuid4(), full_name="Concurrency Doctor", specialization="General", department_id=department.id, is_active=True)
            visit = Visit(id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid, doctor_id=doctor.id, department_id=department.id, status="CONSULTATION_COMPLETED")
            session.add_all([department, patient, doctor])
            await session.flush()
            session.add(visit)
            await session.commit()

        yield {"schema": schema, "tenant_id": tenant_id, "engine": engine, "new_session": new_session, "patient_id": patient.id, "visit_id": visit.id, "uhid": patient.uhid}
    finally:
        async with engine.begin() as connection:
            assert schema.startswith(_PREFIX)
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
        await engine.dispose()


async def _create_order(context, status: str, tests: list[dict]) -> uuid.UUID:
    async with await context["new_session"]() as session:
        order = LabOrder(id=uuid.uuid4(), visit_id=context["visit_id"], uhid=context["uhid"], tests=tests, status=status)
        session.add(order)
        await session.commit()
        return order.id


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_lab_result_entry(lab_context):
    order_id = await _create_order(lab_context, "processing", [{"test": "CBC", "price": 200.0}])

    async def enter_result():
        async with await lab_context["new_session"]() as session:
            order = await session.scalar(select(LabOrder).where(LabOrder.id == order_id).with_for_update())
            if order.status != "processing":
                return "already_entered"
            if await session.scalar(select(LabResult.id).where(LabResult.lab_order_id == order_id)) is not None:
                return "already_entered"
            session.add(LabResult(id=uuid.uuid4(), lab_order_id=order_id, uhid=order.uhid, results={"CBC": "Normal"}, reported_by_user_id=uuid.uuid4()))
            order.status = "result_ready"
            await session.commit()
            return "entered"

    outcomes = await asyncio.wait_for(asyncio.gather(enter_result(), enter_result()), timeout=10)
    async with await lab_context["new_session"]() as verify:
        assert sorted(outcomes) == ["already_entered", "entered"]
        assert await verify.scalar(select(func.count()).select_from(LabResult).where(LabResult.lab_order_id == order_id)) == 1
        assert (await verify.get(LabOrder, order_id)).status == "result_ready"


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_lab_verification(lab_context):
    order_id = await _create_order(lab_context, "result_ready", [{"test": "TSH", "price": 300.0}])

    async def verify_order():
        async with await lab_context["new_session"]() as session:
            order = await session.scalar(select(LabOrder).where(LabOrder.id == order_id).with_for_update())
            if order.status == "verified":
                return "already_verified"
            assert can_transition_lab_order(order.status, "verified")
            order.status = "verified"
            order.verified_at = datetime.now(timezone.utc)
            await session.commit()
            return "verified"

    outcomes = await asyncio.wait_for(asyncio.gather(verify_order(), verify_order()), timeout=10)
    async with await lab_context["new_session"]() as verify:
        assert sorted(outcomes) == ["already_verified", "verified"]
        assert (await verify.get(LabOrder, order_id)).status == "verified"


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_lab_to_billing_trigger(lab_context):
    order_id = await _create_order(lab_context, "result_ready", [{"test": "CBC", "test_code": "CBC", "price": 200.0}, {"test": "TSH", "test_code": "TSH", "price": 300.0}])

    async def create_invoice():
        async with await lab_context["new_session"]() as session:
            try:
                invoice = await create_lab_invoice_if_needed(session, order_id, lab_context["visit_id"], [{"test": "CBC", "test_code": "CBC", "price": 200.0}, {"test": "TSH", "test_code": "TSH", "price": 300.0}], lab_context["patient_id"], {"sub": str(uuid.uuid4()), "role": "lab_technician", "tenant_schema": lab_context["schema"]})
                await session.commit()
                return invoice.id
            except IntegrityError:
                await session.rollback()
                async with await lab_context["new_session"]() as retry:
                    return (await retry.scalar(select(Invoice.id).where(Invoice.lab_order_id == order_id)))

    invoice_ids = await asyncio.wait_for(asyncio.gather(create_invoice(), create_invoice()), timeout=10)
    async with await lab_context["new_session"]() as verify:
        assert invoice_ids[0] == invoice_ids[1]
        assert await verify.scalar(select(func.count()).select_from(Invoice).where(Invoice.lab_order_id == order_id)) == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_invalid_lab_status_transition(lab_context):
    order_id = await _create_order(lab_context, "ordered", [{"test": "GLU", "price": 150.0}])
    async with await lab_context["new_session"]() as session:
        order = await session.scalar(select(LabOrder).where(LabOrder.id == order_id).with_for_update())
        assert not can_transition_lab_order(order.status, "completed")
        await session.rollback()
    async with await lab_context["new_session"]() as verify:
        assert (await verify.get(LabOrder, order_id)).status == "ordered"
