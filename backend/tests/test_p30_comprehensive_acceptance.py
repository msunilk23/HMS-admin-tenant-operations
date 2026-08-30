"""Real PostgreSQL tenant-schema P30 batch-return acceptance tests."""

import asyncio
import os
import socket
import uuid
from decimal import Decimal
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.models.public.user import Tenant, User
from app.models.tenant import (
    InventoryBatch,
    Patient,
    PatientReturn,
    PatientReturnBatchAllocation,
    PatientReturnItem,
    PharmacyDispense,
    PharmacyDispenseAllocation,
    PharmacyDispenseItem,
    PharmacyLocation,
    Prescription,
    PrescriptionItem,
    PurchaseOrder,
    Supplier,
    SupplierReturn,
    SupplierReturnItem,
    StockTransaction,
    Visit,
)
from app.models.tenant.goods_receipt import GoodsReceipt
from app.schemas.returns import PatientReturnCreate, PatientReturnItemCreate, SupplierReturnCreate, SupplierReturnItemCreate
from app.services.returns_service import PatientReturnService, SupplierReturnService

PG_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")


def _postgres_reachable() -> bool:
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def p30_pg_context():
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    schema_a = f"p30_a_{uuid.uuid4().hex[:8]}"
    schema_b = f"p30_b_{uuid.uuid4().hex[:8]}"
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    pharmacist_id = uuid.uuid4()
    pharmacist_b_id = uuid.uuid4()
    nurse_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    visit_id = uuid.uuid4()
    prescription_id = uuid.uuid4()
    prescription_item_id = uuid.uuid4()
    dispense_id = uuid.uuid4()
    dispense_item_id = uuid.uuid4()
    medicine_id = uuid.uuid4()
    user_id = uuid.uuid4()
    batch_a_id = uuid.uuid4()
    batch_b_id = uuid.uuid4()
    allocation_a_id = uuid.uuid4()
    allocation_b_id = uuid.uuid4()
    supplier_id = uuid.uuid4()
    purchase_order_id = uuid.uuid4()
    goods_receipt_id = uuid.uuid4()
    supplier_batch_id = uuid.uuid4()

    tenant_tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
    async with engine.begin() as connection:
        await connection.execute(text("""
            INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, plan, is_active, display_token, session_version, created_at, updated_at)
            VALUES (:id, :schema, :name, :email, 'enterprise', true, :display_token, 0, now(), now())
        """), [
            {"id": tenant_a, "schema": schema_a, "name": "P30 A", "email": f"{schema_a}@test.invalid", "display_token": f"display-{schema_a}"},
            {"id": tenant_b, "schema": schema_b, "name": "P30 B", "email": f"{schema_b}@test.invalid", "display_token": f"display-{schema_b}"},
        ])
        await connection.execute(text("""
            INSERT INTO public.users (id, tenant_id, tenant_name, email, username, hashed_password, full_name, role, is_active, must_change_password, session_version, created_at, updated_at)
            VALUES (:id, :tenant_id, :tenant_name, :email, :username, :password, :full_name, :role, true, false, 0, now(), now())
        """), [
            {"id": pharmacist_id, "tenant_id": tenant_a, "tenant_name": schema_a, "email": f"pharmacist-{schema_a}@test.invalid", "username": f"pharm{schema_a[-6:]}", "password": hash_password("Passw0rd!"), "full_name": "P30 Pharmacist", "role": "pharmacist"},
            {"id": pharmacist_b_id, "tenant_id": tenant_b, "tenant_name": schema_b, "email": f"pharmacist-{schema_b}@test.invalid", "username": f"pharm{schema_b[-6:]}", "password": hash_password("Passw0rd!"), "full_name": "P30 Pharmacist B", "role": "pharmacist"},
            {"id": nurse_id, "tenant_id": tenant_a, "tenant_name": schema_a, "email": f"nurse-{schema_a}@test.invalid", "username": f"nurse{schema_a[-6:]}", "password": hash_password("Passw0rd!"), "full_name": "P30 Nurse", "role": "nurse"},
        ])
        for schema, tenant_id in ((schema_a, tenant_a), (schema_b, tenant_b)):
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET search_path TO "{schema}", public'))
            await connection.run_sync(lambda sync_connection: Base.metadata.create_all(sync_connection, tables=tenant_tables))

            if schema == schema_a:
                location = PharmacyLocation(id=location_id, tenant_id=tenant_id, facility_id=facility_id, location_code="P30", location_name="P30", location_type="PHARMACY", active=True)
                patient = Patient(id=patient_id, uhid="P30-001", first_name="P30", last_name="Patient", gender="M", phone="9000000001")
                visit = Visit(id=visit_id, patient_id=patient_id, uhid="P30-001", status="CONSULTATION_COMPLETED")
                prescription = Prescription(id=prescription_id, visit_id=visit_id, uhid="P30-001", status="finalized", version=1)
                prescription_item = PrescriptionItem(id=prescription_item_id, prescription_id=prescription_id, medicine="P30 Medicine", quantity="10", final_quantity="10")
                dispense = PharmacyDispense(id=dispense_id, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location_id, prescription_id=prescription_id, prescription_version=1, visit_id=visit_id, patient_id=patient_id, status="CONFIRMED")
                dispense_item = PharmacyDispenseItem(id=dispense_item_id, dispense_id=dispense_id, prescription_item_id=prescription_item_id, prescribed_name_snapshot="P30 Medicine", prescribed_quantity=Decimal("10"), internal_requested_quantity=Decimal("10"), internal_confirmed_quantity=Decimal("10"), outside_purchase_quantity=Decimal("0"), status="DISPENSED")
                batch_a = InventoryBatch(id=batch_a_id, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location_id, medicine_id=medicine_id, batch_number="P30-A", purchase_rate=Decimal("10"), received_quantity=Decimal("6"), available_quantity=Decimal("0"), reserved_quantity=Decimal("0"), status="ACTIVE")
                batch_b = InventoryBatch(id=batch_b_id, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location_id, medicine_id=medicine_id, batch_number="P30-B", purchase_rate=Decimal("12"), received_quantity=Decimal("4"), available_quantity=Decimal("0"), reserved_quantity=Decimal("0"), status="ACTIVE")
                allocations = [
                    PharmacyDispenseAllocation(id=allocation_a_id, dispense_item_id=dispense_item_id, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location_id, inventory_batch_id=batch_a_id, allocated_quantity=Decimal("6"), confirmed_dispensed_quantity=Decimal("6"), status="CONSUMED"),
                    PharmacyDispenseAllocation(id=allocation_b_id, dispense_item_id=dispense_item_id, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location_id, inventory_batch_id=batch_b_id, allocated_quantity=Decimal("4"), confirmed_dispensed_quantity=Decimal("4"), status="CONSUMED"),
                ]
                session = AsyncSession(bind=connection, expire_on_commit=False)
                session.add_all([location, patient])
                await session.flush()
                session.add(visit)
                await session.flush()
                session.add(prescription)
                await session.flush()
                session.add(prescription_item)
                await session.flush()
                session.add(dispense)
                await session.flush()
                session.add(dispense_item)
                await session.flush()
                session.add_all([batch_a, batch_b])
                await session.flush()
                session.add_all(allocations)
                await session.flush()
                supplier = Supplier(id=supplier_id, supplier_code="P30-SUP", supplier_name="P30 Supplier")
                session.add(supplier)
                await session.flush()
                purchase_order = PurchaseOrder(id=purchase_order_id, po_number="P30-PO", supplier_id=supplier_id, status="FULLY_RECEIVED", subtotal=Decimal("100"), total_amount=Decimal("100"))
                session.add(purchase_order)
                await session.flush()
                goods_receipt = GoodsReceipt(id=goods_receipt_id, grn_number="P30-GRN", purchase_order_id=purchase_order_id, supplier_id=supplier_id, facility_id=facility_id, pharmacy_location_id=location_id, status="FULLY_RECEIVED", subtotal=Decimal("100"), total_amount=Decimal("100"))
                session.add(goods_receipt)
                await session.flush()
                supplier_batch = InventoryBatch(id=supplier_batch_id, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location_id, medicine_id=medicine_id, batch_number="P30-SUP-BATCH", purchase_rate=Decimal("15"), received_quantity=Decimal("10"), available_quantity=Decimal("10"), reserved_quantity=Decimal("0"), supplier_id=supplier_id, goods_receipt_id=goods_receipt_id, status="ACTIVE")
                session.add(supplier_batch)
                await session.flush()
                await session.commit()
                await session.close()

    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield {
        "engine": engine, "maker": maker, "schema_a": schema_a, "schema_b": schema_b,
        "tenant_a": tenant_a, "tenant_b": tenant_b, "facility_id": facility_id,
        "location_id": location_id, "patient_id": patient_id, "visit_id": visit_id,
        "dispense_id": dispense_id, "dispense_item_id": dispense_item_id,
        "batch_a_id": batch_a_id, "batch_b_id": batch_b_id, "allocation_a_id": allocation_a_id,
        "allocation_b_id": allocation_b_id, "medicine_id": medicine_id, "user_id": user_id,
        "pharmacist_id": pharmacist_id, "pharmacist_b_id": pharmacist_b_id, "nurse_id": nurse_id,
        "supplier_id": supplier_id, "purchase_order_id": purchase_order_id,
        "goods_receipt_id": goods_receipt_id, "supplier_batch_id": supplier_batch_id,
    }
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_a}" CASCADE'))
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_b}" CASCADE'))
        await connection.execute(text("DELETE FROM public.users WHERE id = ANY(:ids)"), {"ids": [pharmacist_id, pharmacist_b_id, nurse_id]})
        await connection.execute(text("DELETE FROM public.tenants WHERE id = ANY(:ids)"), {"ids": [tenant_a, tenant_b]})
    await engine.dispose()


async def _session(context):
    session = context["maker"]()
    await session.execute(text(f'SET search_path TO "{context["schema_a"]}", public'))
    assert await session.scalar(text("SELECT current_schema()")) == context["schema_a"]
    assert context["schema_a"] in await session.scalar(text("SHOW search_path"))
    return session


def _request(context, quantities, *, idempotency_key=None):
    allocations = [
        {"inventory_batch_id": batch_id, "returned_quantity": quantity}
        for batch_id, quantity in quantities.items()
    ]
    return PatientReturnCreate(
        dispense_id=context["dispense_id"],
        return_reason="Sealed patient return",
        idempotency_key=idempotency_key,
        items=[PatientReturnItemCreate(dispense_item_id=context["dispense_item_id"], returned_quantity=sum(quantities.values(), Decimal("0")), restockable=True, batch_allocations=allocations)],
    )


def _supplier_request(context, quantity, *, idempotency_key=None):
    return SupplierReturnCreate(
        supplier_id=context["supplier_id"], goods_receipt_id=context["goods_receipt_id"],
        return_reason="Supplier batch return", idempotency_key=idempotency_key,
        items=[SupplierReturnItemCreate(inventory_batch_id=context["supplier_batch_id"], returned_quantity=quantity, unit_cost=Decimal("15"))],
    )


async def _create_validate_accept(session, context, quantities, *, idempotency_key=None):
    requested = await PatientReturnService.request_return(session, context["tenant_a"], context["facility_id"], context["location_id"], context["patient_id"], context["visit_id"], _request(context, quantities, idempotency_key=idempotency_key), context["user_id"])
    await PatientReturnService.validate_return(session, requested.id, context["user_id"], context["tenant_a"], context["facility_id"])
    return await PatientReturnService.accept_return(session, requested.id, context["user_id"], context["tenant_a"], context["facility_id"])


def _token(context, user_id, role, *, tenant_id=None, tenant_schema=None):
    return create_access_token(str(user_id), {
        "role": role,
        "tenant_id": str(tenant_id or context["tenant_a"]),
        "tenant_schema": tenant_schema or context["schema_a"],
        "facility_id": str(context["facility_id"]),
        "session_version": 0,
        "tenant_session_version": 0,
        "features": ["pharmacy"],
    })


@pytest.mark.asyncio(loop_scope="module")
async def test_multi_batch_patient_return_restores_each_original_batch_and_ledger(p30_pg_context):
    session = await _session(p30_pg_context)
    try:
        result = await _create_validate_accept(session, p30_pg_context, {p30_pg_context["batch_a_id"]: Decimal("3"), p30_pg_context["batch_b_id"]: Decimal("2")})
        await session.commit()
        allocations = (await session.scalars(select(PatientReturnBatchAllocation).where(PatientReturnBatchAllocation.patient_return_item_id.in_(select(PatientReturnItem.id).where(PatientReturnItem.return_id == result.id))))).all()
        ledger = (await session.scalars(select(StockTransaction).where(StockTransaction.reference_type == "PatientReturnBatchAllocation"))).all()
        batches = {batch.id: batch for batch in (await session.scalars(select(InventoryBatch))).all()}
        assert result.status == "REFUND_PENDING"
        assert {allocation.inventory_batch_id for allocation in allocations} == {p30_pg_context["batch_a_id"], p30_pg_context["batch_b_id"]}
        assert batches[p30_pg_context["batch_a_id"]].available_quantity == Decimal("3")
        assert batches[p30_pg_context["batch_b_id"]].available_quantity == Decimal("2")
        assert len(ledger) == 2
        assert {entry.quantity for entry in ledger} == {Decimal("2"), Decimal("3")}
        assert all(entry.tenant_id == p30_pg_context["tenant_a"] and entry.medicine_id == p30_pg_context["medicine_id"] for entry in ledger)
    finally:
        await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_invalid_batch_or_cumulative_overreturn_creates_no_committed_state(p30_pg_context):
    session = await _session(p30_pg_context)
    try:
        with pytest.raises(ValueError, match="original dispensing"):
            await PatientReturnService.request_return(session, p30_pg_context["tenant_a"], p30_pg_context["facility_id"], p30_pg_context["location_id"], p30_pg_context["patient_id"], p30_pg_context["visit_id"], _request(p30_pg_context, {uuid.uuid4(): Decimal("1")}), p30_pg_context["user_id"])
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(PatientReturn)) == 1
    finally:
        await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_idempotency_replay_returns_original_return_without_duplicate(p30_pg_context):
    session = await _session(p30_pg_context)
    try:
        key = "p30-replay"
        first = await PatientReturnService.request_return(session, p30_pg_context["tenant_a"], p30_pg_context["facility_id"], p30_pg_context["location_id"], p30_pg_context["patient_id"], p30_pg_context["visit_id"], _request(p30_pg_context, {p30_pg_context["batch_a_id"]: Decimal("1")}, idempotency_key=key), p30_pg_context["user_id"])
        await session.commit()
        replay = await PatientReturnService.request_return(session, p30_pg_context["tenant_a"], p30_pg_context["facility_id"], p30_pg_context["location_id"], p30_pg_context["patient_id"], p30_pg_context["visit_id"], _request(p30_pg_context, {p30_pg_context["batch_a_id"]: Decimal("1")}, idempotency_key=key), p30_pg_context["user_id"])
        assert replay.id == first.id
        assert await session.scalar(select(func.count()).select_from(PatientReturn).where(PatientReturn.idempotency_key == key)) == 1
    finally:
        await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_patient_return_api_enforces_auth_tenant_and_idempotency(p30_pg_context):
    from app.main import app

    payload = {
        "dispense_id": str(p30_pg_context["dispense_id"]),
        "return_reason": "Sealed patient return",
        "idempotency_key": "p30-api-replay",
        "items": [{
            "dispense_item_id": str(p30_pg_context["dispense_item_id"]),
            "returned_quantity": "1",
            "restockable": True,
            "batch_allocations": [{"inventory_batch_id": str(p30_pg_context["batch_b_id"]), "returned_quantity": "1"}],
        }],
    }
    pharmacist_token = _token(p30_pg_context, p30_pg_context["pharmacist_id"], "pharmacist")
    nurse_token = _token(p30_pg_context, p30_pg_context["nurse_id"], "nurse")
    tenant_b_token = _token(p30_pg_context, p30_pg_context["pharmacist_b_id"], "pharmacist", tenant_id=p30_pg_context["tenant_b"], tenant_schema=p30_pg_context["schema_b"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/v1/returns/patient-returns", json=payload)).status_code == 401
        assert (await client.post("/api/v1/returns/patient-returns", json=payload, headers={"Authorization": f"Bearer {nurse_token}"})).status_code == 403
        created = await client.post("/api/v1/returns/patient-returns", json=payload, headers={"Authorization": f"Bearer {pharmacist_token}"})
        assert created.status_code == 201, created.text
        replay = await client.post("/api/v1/returns/patient-returns", json=payload, headers={"Authorization": f"Bearer {pharmacist_token}"})
        assert replay.status_code == 201, replay.text
        assert replay.json()["id"] == created.json()["id"]
        conflicting = {**payload, "items": [{
            **payload["items"][0],
            "returned_quantity": "2",
            "batch_allocations": [{"inventory_batch_id": str(p30_pg_context["batch_b_id"]), "returned_quantity": "2"}],
        }]}
        assert (await client.post("/api/v1/returns/patient-returns", json=conflicting, headers={"Authorization": f"Bearer {pharmacist_token}"})).status_code == 400
        assert (await client.get(f"/api/v1/returns/patient-returns/{created.json()['id']}", headers={"Authorization": f"Bearer {tenant_b_token}"})).status_code == 404


@pytest.mark.asyncio(loop_scope="module")
async def test_supplier_return_dispatch_reduces_exact_batch_and_writes_ledger(p30_pg_context):
    session = await _session(p30_pg_context)
    try:
        requested = await SupplierReturnService.request_return(session, p30_pg_context["tenant_a"], p30_pg_context["facility_id"], p30_pg_context["location_id"], _supplier_request(p30_pg_context, Decimal("4")), p30_pg_context["user_id"])
        await SupplierReturnService.approve_return(session, requested.id, p30_pg_context["user_id"], p30_pg_context["tenant_a"], p30_pg_context["facility_id"])
        dispatched = await SupplierReturnService.dispatch_return(session, requested.id, p30_pg_context["user_id"], p30_pg_context["tenant_a"], p30_pg_context["facility_id"])
        await session.commit()
        batch = await session.get(InventoryBatch, p30_pg_context["supplier_batch_id"])
        item = await session.scalar(select(SupplierReturnItem).where(SupplierReturnItem.supplier_return_id == requested.id))
        ledger = await session.scalar(select(StockTransaction).where(StockTransaction.reference_id == item.id, StockTransaction.transaction_type == "SUPPLIER_RETURN"))
        assert dispatched.status == "DISPATCHED"
        assert batch.available_quantity == Decimal("6")
        assert item.received_quantity == Decimal("10")
        assert ledger.quantity == Decimal("-4")
        assert ledger.inventory_batch_id == batch.id
        assert ledger.tenant_id == p30_pg_context["tenant_a"]
        assert ledger.previous_balance == Decimal("10") and ledger.new_balance == Decimal("6")
    finally:
        await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_supplier_return_api_enforces_auth_replay_and_validation(p30_pg_context):
    from app.main import app

    payload = _supplier_request(p30_pg_context, Decimal("1"), idempotency_key="p30-supplier-replay").model_dump(mode="json")
    pharmacist_token = _token(p30_pg_context, p30_pg_context["pharmacist_id"], "pharmacist")
    nurse_token = _token(p30_pg_context, p30_pg_context["nurse_id"], "nurse")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/v1/returns/supplier-returns", json=payload)).status_code == 401
        assert (await client.post("/api/v1/returns/supplier-returns", json=payload, headers={"Authorization": f"Bearer {nurse_token}"})).status_code == 403
        created = await client.post("/api/v1/returns/supplier-returns", json=payload, headers={"Authorization": f"Bearer {pharmacist_token}"})
        assert created.status_code == 201, created.text
        replay = await client.post("/api/v1/returns/supplier-returns", json=payload, headers={"Authorization": f"Bearer {pharmacist_token}"})
        assert replay.status_code == 201 and replay.json()["id"] == created.json()["id"]
        excessive = {**payload, "idempotency_key": "p30-supplier-excess", "items": [{**payload["items"][0], "returned_quantity": "100"}]}
        assert (await client.post("/api/v1/returns/supplier-returns", json=excessive, headers={"Authorization": f"Bearer {pharmacist_token}"})).status_code == 400


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_patient_returns_cannot_exceed_source_allocation(p30_pg_context):
    async def request(quantity):
        async with await _session(p30_pg_context) as session:
            try:
                result = await PatientReturnService.request_return(
                    session, p30_pg_context["tenant_a"], p30_pg_context["facility_id"], p30_pg_context["location_id"],
                    p30_pg_context["patient_id"], p30_pg_context["visit_id"],
                    _request(p30_pg_context, {p30_pg_context["batch_a_id"]: quantity}), p30_pg_context["user_id"],
                )
                await session.commit()
                return result.id
            except ValueError as error:
                await session.rollback()
                return str(error)

    outcomes = await asyncio.wait_for(asyncio.gather(request(Decimal("2")), request(Decimal("2"))), timeout=10)
    async with await _session(p30_pg_context) as verify:
        allocations = await verify.scalar(
            select(func.coalesce(func.sum(PatientReturnBatchAllocation.returned_quantity), Decimal("0")))
            .where(PatientReturnBatchAllocation.dispense_allocation_id == p30_pg_context["allocation_a_id"])
        )
        assert sum(isinstance(value, uuid.UUID) for value in outcomes) == 1
        assert Decimal(str(allocations)) <= Decimal("6")


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_supplier_dispatch_cannot_overdraw_batch(p30_pg_context):
    async def request_approve_dispatch(key):
        async with await _session(p30_pg_context) as session:
            try:
                requested = await SupplierReturnService.request_return(
                    session, p30_pg_context["tenant_a"], p30_pg_context["facility_id"], p30_pg_context["location_id"],
                    _supplier_request(p30_pg_context, Decimal("4"), idempotency_key=key), p30_pg_context["user_id"],
                )
                await SupplierReturnService.approve_return(session, requested.id, p30_pg_context["user_id"], p30_pg_context["tenant_a"], p30_pg_context["facility_id"])
                await SupplierReturnService.dispatch_return(session, requested.id, p30_pg_context["user_id"], p30_pg_context["tenant_a"], p30_pg_context["facility_id"])
                await session.commit()
                return requested.id
            except ValueError as error:
                await session.rollback()
                return str(error)

    outcomes = await asyncio.wait_for(asyncio.gather(request_approve_dispatch("supplier-race-a"), request_approve_dispatch("supplier-race-b")), timeout=10)
    async with await _session(p30_pg_context) as verify:
        batch = await verify.get(InventoryBatch, p30_pg_context["supplier_batch_id"])
        assert sum(isinstance(value, uuid.UUID) for value in outcomes) == 1
        assert batch.available_quantity >= Decimal("0")


@pytest.mark.asyncio(loop_scope="module")
async def test_patient_return_preparation_rollback_leaves_no_idempotency_or_allocation(p30_pg_context):
    key = "p30-rollback"
    async with await _session(p30_pg_context) as session:
        try:
            await PatientReturnService.request_return(
                session, p30_pg_context["tenant_a"], p30_pg_context["facility_id"], p30_pg_context["location_id"],
                p30_pg_context["patient_id"], p30_pg_context["visit_id"],
                _request(p30_pg_context, {p30_pg_context["batch_b_id"]: Decimal("1")}, idempotency_key=key),
                p30_pg_context["user_id"],
            )
            raise RuntimeError("controlled post-preparation failure")
        except RuntimeError:
            await session.rollback()

    async with await _session(p30_pg_context) as verify:
        assert await verify.scalar(select(func.count()).select_from(PatientReturn).where(PatientReturn.idempotency_key == key)) == 0
        assert await verify.scalar(
            select(func.count())
            .select_from(PatientReturnBatchAllocation)
            .join(PatientReturnItem, PatientReturnBatchAllocation.patient_return_item_id == PatientReturnItem.id)
            .join(PatientReturn, PatientReturnItem.return_id == PatientReturn.id)
            .where(PatientReturn.idempotency_key == key)
        ) == 0
        batch = await verify.get(InventoryBatch, p30_pg_context["batch_b_id"])
        assert batch.available_quantity == Decimal("2")
