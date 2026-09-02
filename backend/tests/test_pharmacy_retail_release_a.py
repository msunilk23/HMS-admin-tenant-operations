import asyncio
import os
import socket
import uuid
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.tenant import (
    DosageForm,
    GenericMedicine,
    InventoryBatch,
    MedicineProduct,
    Patient,
    PharmacistLocationAuthorization,
    PharmacyLocation,
    PharmacyRetailInvoice,
    PharmacyRetailPayment,
    PharmacyRetailReturn,
    PharmacyRetailReturnAllocation,
    PharmacyRetailSale,
    PharmacyRetailSaleAllocation,
    PharmacyRetailSaleItem,
    StockTransaction,
)
from app.schemas.pharmacy_retail import RetailReturnCreate, RetailSaleCreate, RetailSaleDispense
from app.services.pharmacy_retail_service import create_retail_sale, dispense_retail_sale, return_retail_sale, verify_external_sale

PG_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")
SCHEMA = f"test_retail_ra4_{uuid.uuid4().hex[:10]}"


def _postgres_reachable() -> bool:
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable")


def _user(context, key: str) -> dict:
    return {
        "sub": str(context[key]), "role": "pharmacist", "tenant_id": str(context["tenant_id"]),
        "tenant_schema": SCHEMA, "facility_id": str(context["facility_id"]),
    }


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def retail_context():
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    tenant_id, facility_id = uuid.uuid4(), uuid.uuid4()
    pharmacist_a, pharmacist_b, unauthorized = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await connection.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        await connection.execute(text("""
            INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, plan, is_active, display_token, created_at, updated_at)
            VALUES (:id, :schema, 'Retail RA4', :email, 'enterprise', true, :token, now(), now())
        """), {"id": tenant_id, "schema": SCHEMA, "email": f"{SCHEMA}@test.invalid", "token": SCHEMA})
        users = []
        for user_id, name in ((pharmacist_a, "Retail Pharmacist A"), (pharmacist_b, "Retail Pharmacist B"), (unauthorized, "Unauthorized Pharmacist")):
            users.append({
                "id": user_id, "tenant_id": tenant_id, "tenant_name": SCHEMA,
                "email": f"{user_id}@test.invalid", "username": f"retail{user_id.hex[:12]}",
                "password": "not-used", "name": name, "role": "pharmacist",
            })
        await connection.execute(text("""
            INSERT INTO public.users (id, tenant_id, tenant_name, email, username, hashed_password, full_name, role, is_active, must_change_password, created_at, updated_at)
            VALUES (:id, :tenant_id, :tenant_name, :email, :username, :password, :name, :role, true, false, now(), now())
        """), users)
        await connection.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        tenant_tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
        await connection.run_sync(lambda sync_connection: Base.metadata.create_all(sync_connection, tables=tenant_tables))

    async def new_session() -> AsyncSession:
        session = maker()
        await session.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        return session

    session = await new_session()
    generic = GenericMedicine(code="RA4-GEN", name="Release A Medicine", is_active=True)
    dosage = DosageForm(code="RA4-TAB", name="Tablet", calculation_type="UNIT", is_active=True)
    location = PharmacyLocation(
        tenant_id=tenant_id, facility_id=facility_id, location_code="RA4", location_name="Retail Counter",
        location_type="PHARMACY", active=True,
    )
    patient = Patient(id=uuid.uuid4(), uhid="RA4-PATIENT", first_name="Retail", last_name="Patient", gender="female", phone="9000000001")
    session.add_all([generic, dosage, location, patient])
    await session.flush()
    otc = MedicineProduct(code="RA4-OTC", generic_medicine_id=generic.id, brand_name="RA4 OTC", dosage_form_id=dosage.id, gst_rate=Decimal("5"), requires_prescription=False, is_controlled_drug=False, is_active=True)
    prescription = MedicineProduct(code="RA4-RX", generic_medicine_id=generic.id, brand_name="RA4 RX", dosage_form_id=dosage.id, gst_rate=Decimal("5"), requires_prescription=True, is_controlled_drug=False, is_active=True)
    controlled = MedicineProduct(code="RA4-CTRL", generic_medicine_id=generic.id, brand_name="RA4 Controlled", dosage_form_id=dosage.id, gst_rate=Decimal("5"), requires_prescription=True, is_controlled_drug=True, is_active=True)
    concurrency = MedicineProduct(code="RA4-RACE", generic_medicine_id=generic.id, brand_name="RA4 Race", dosage_form_id=dosage.id, gst_rate=Decimal("0"), requires_prescription=False, is_controlled_drug=False, is_active=True)
    session.add_all([otc, prescription, controlled, concurrency])
    await session.flush()
    expiry_early, expiry_late = date.today() + timedelta(days=60), date.today() + timedelta(days=120)
    session.add_all([
        InventoryBatch(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, medicine_id=otc.id, batch_number="OTC-EARLY", expiry_date=expiry_early, purchase_rate=Decimal("5"), mrp=Decimal("10"), received_quantity=Decimal("2"), available_quantity=Decimal("2"), reserved_quantity=Decimal("0"), status="ACTIVE"),
        InventoryBatch(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, medicine_id=otc.id, batch_number="OTC-LATE", expiry_date=expiry_late, purchase_rate=Decimal("6"), mrp=Decimal("12"), received_quantity=Decimal("10"), available_quantity=Decimal("10"), reserved_quantity=Decimal("0"), status="ACTIVE"),
        InventoryBatch(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, medicine_id=prescription.id, batch_number="RX", expiry_date=expiry_late, purchase_rate=Decimal("10"), mrp=Decimal("20"), received_quantity=Decimal("10"), available_quantity=Decimal("10"), reserved_quantity=Decimal("0"), status="ACTIVE"),
        InventoryBatch(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, medicine_id=controlled.id, batch_number="CTRL", expiry_date=expiry_late, purchase_rate=Decimal("20"), mrp=Decimal("30"), received_quantity=Decimal("10"), available_quantity=Decimal("10"), reserved_quantity=Decimal("0"), status="ACTIVE"),
        InventoryBatch(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, medicine_id=concurrency.id, batch_number="RACE", expiry_date=expiry_late, purchase_rate=Decimal("2"), mrp=Decimal("4"), received_quantity=Decimal("5"), available_quantity=Decimal("5"), reserved_quantity=Decimal("0"), status="ACTIVE"),
        PharmacistLocationAuthorization(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, user_id=pharmacist_a, authorized_by=pharmacist_a),
        PharmacistLocationAuthorization(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, user_id=pharmacist_b, authorized_by=pharmacist_a),
    ])
    await session.commit()
    await session.close()

    context = {
        "engine": engine, "new_session": new_session, "tenant_id": tenant_id, "facility_id": facility_id,
        "pharmacist_a": pharmacist_a, "pharmacist_b": pharmacist_b, "unauthorized": unauthorized,
        "location_id": location.id, "patient_id": patient.id, "otc_id": otc.id, "rx_id": prescription.id,
        "controlled_id": controlled.id, "concurrency_id": concurrency.id,
    }
    yield context

    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await connection.execute(text("DELETE FROM public.users WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        await connection.execute(text("DELETE FROM public.tenants WHERE id = :tenant_id"), {"tenant_id": tenant_id})
    await engine.dispose()


def _otc_payload(context, product_key: str = "otc_id", quantity: str = "3") -> RetailSaleCreate:
    return RetailSaleCreate(
        classification="OTC", pharmacy_location_id=context["location_id"],
        items=[{"medicine_product_id": context[product_key], "quantity": quantity}],
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_otc_rejects_prescription_only_and_unauthorized_pharmacists(retail_context):
    session = await retail_context["new_session"]()
    with pytest.raises(ValueError, match="cannot use the OTC path"):
        await create_retail_sale(
            session, payload=_otc_payload(retail_context, "rx_id"), idempotency_key="ra4-rx-denial",
            tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
            actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
        )
    await session.rollback()
    with pytest.raises(ValueError, match="not active and authorized"):
        await create_retail_sale(
            session, payload=_otc_payload(retail_context), idempotency_key="ra4-auth-denial",
            tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
            actor_id=retail_context["unauthorized"], current_user=_user(retail_context, "unauthorized"),
        )
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_otc_fefo_server_pricing_and_idempotent_replay(retail_context):
    session = await retail_context["new_session"]()
    sale = await create_retail_sale(
        session, payload=_otc_payload(retail_context), idempotency_key="ra4-otc-success",
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    replay = await create_retail_sale(
        session, payload=_otc_payload(retail_context), idempotency_key="ra4-otc-success",
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    assert replay.id == sale.id
    completed = await dispense_retail_sale(
        session, sale_id=sale.id, payload=RetailSaleDispense(payment_method="CASH"),
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    assert completed.status == "FULLY_DISPENSED"
    assert completed.subtotal == Decimal("32.00")
    assert completed.tax == Decimal("1.60")
    sale_allocations = list((await session.execute(text("""
        SELECT b.batch_number, a.quantity FROM pharmacy_retail_sale_allocations a
        JOIN pharmacy_retail_sale_items i ON i.id = a.sale_item_id
        JOIN inventory_batches b ON b.id = a.inventory_batch_id
        WHERE i.sale_id = :sale_id ORDER BY b.expiry_date
    """), {"sale_id": sale.id})).all())
    assert sale_allocations == [("OTC-EARLY", Decimal("2.000")), ("OTC-LATE", Decimal("1.000"))]
    ledger_count = await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.correlation_reference == sale.customer_reference))
    invoice = await session.scalar(select(PharmacyRetailInvoice).where(PharmacyRetailInvoice.sale_id == sale.id))
    assert invoice is not None
    assert invoice.classification == "OTC"
    assert invoice.total == completed.total
    payment = await session.scalar(select(PharmacyRetailPayment).where(PharmacyRetailPayment.invoice_id == invoice.id))
    assert payment is not None
    assert payment.amount == completed.total
    assert payment.status == "CAPTURED"
    await dispense_retail_sale(
        session, sale_id=sale.id, payload=RetailSaleDispense(payment_method="CASH"),
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    assert await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.correlation_reference == sale.customer_reference)) == ledger_count
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_controlled_external_requires_maker_checker_and_full_identity(retail_context):
    session = await retail_context["new_session"]()
    payload = RetailSaleCreate(
        classification="EXTERNAL_PRESCRIPTION", pharmacy_location_id=retail_context["location_id"],
        patient_id=retail_context["patient_id"], patient_name="Retail Patient", patient_age=35, patient_gender="female",
        patient_mobile="9000000001", patient_address="1 Test Street", government_id_type="Passport",
        government_id_last_four="1234", prescriber_name="External Doctor", prescriber_registration_number="REG-123",
        prescription_date=date.today(), issuing_facility="External Clinic", prescription_reference="RX-RA4-1",
        prescription_attachment_reference="document://rx-ra4-1", original_prescription_inspected=True,
        items=[{"medicine_product_id": retail_context["controlled_id"], "quantity": "2", "prescribed_quantity": "2", "duration_days": 7}],
    )
    sale = await create_retail_sale(
        session, payload=payload, idempotency_key="ra4-controlled", tenant_id=retail_context["tenant_id"],
        facility_id=retail_context["facility_id"], actor_id=retail_context["pharmacist_a"],
        current_user=_user(retail_context, "pharmacist_a"),
    )
    sale_id = sale.id
    await verify_external_sale(
        session, sale_id=sale_id, tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    with pytest.raises(ValueError, match="different dispensing Pharmacist"):
        await dispense_retail_sale(
            session, sale_id=sale_id, payload=RetailSaleDispense(payment_method="CASH"),
            tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
            actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
        )
    await session.rollback()
    completed = await dispense_retail_sale(
        session, sale_id=sale_id, payload=RetailSaleDispense(payment_method="CARD", payment_reference="CARD-RA4"),
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_b"], current_user=_user(retail_context, "pharmacist_b"),
    )
    assert completed.verified_by == retail_context["pharmacist_a"]
    assert completed.dispensed_by == retail_context["pharmacist_b"]
    assert completed.status == "FULLY_DISPENSED"
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_retail_return_restores_original_batch_once_and_retains_classification(retail_context):
    session = await retail_context["new_session"]()
    sale = await create_retail_sale(
        session, payload=_otc_payload(retail_context, quantity="2"), idempotency_key="ra4-return-source",
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    sale = await dispense_retail_sale(
        session, sale_id=sale.id, payload=RetailSaleDispense(payment_method="CASH"),
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    allocation, source_batch = (await session.execute(
        select(PharmacyRetailSaleAllocation, InventoryBatch)
        .join(InventoryBatch, InventoryBatch.id == PharmacyRetailSaleAllocation.inventory_batch_id)
        .join(PharmacyRetailSaleItem, PharmacyRetailSaleItem.id == PharmacyRetailSaleAllocation.sale_item_id)
        .where(PharmacyRetailSaleItem.sale_id == sale.id)
        .order_by(InventoryBatch.expiry_date)
    )).first()
    balance_after_sale = source_batch.available_quantity
    payload = RetailReturnCreate(
        reason="Sealed medicine returned by walk-in customer",
        allocations=[{"sale_allocation_id": allocation.id, "quantity": "1"}],
    )
    retail_return = await return_retail_sale(
        session, sale_id=sale.id, payload=payload, idempotency_key="ra4-return-once",
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    replay = await return_retail_sale(
        session, sale_id=sale.id, payload=payload, idempotency_key="ra4-return-once",
        tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
        actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
    )
    assert replay.id == retail_return.id
    assert retail_return.classification == sale.classification == "OTC"
    await session.refresh(source_batch)
    assert source_batch.available_quantity == balance_after_sale + Decimal("1")
    assert await session.scalar(select(func.count()).select_from(PharmacyRetailReturn).where(PharmacyRetailReturn.sale_id == sale.id)) == 1
    return_allocation = await session.scalar(select(PharmacyRetailReturnAllocation).where(PharmacyRetailReturnAllocation.return_id == retail_return.id))
    assert return_allocation.sale_allocation_id == allocation.id
    ledger = await session.scalar(select(StockTransaction).where(StockTransaction.id == return_allocation.stock_transaction_id))
    assert ledger.transaction_type == "PATIENT_RETURN_RESTOCK"
    assert ledger.quantity == Decimal("1.000")
    invoice = await session.scalar(select(PharmacyRetailInvoice).where(PharmacyRetailInvoice.sale_id == sale.id))
    payment = await session.scalar(select(PharmacyRetailPayment).where(PharmacyRetailPayment.invoice_id == invoice.id))
    assert invoice.status == "PARTIALLY_REFUNDED"
    assert payment.status == "PARTIALLY_REFUNDED"
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_otc_sales_cannot_oversell(retail_context):
    created_ids = []
    for suffix in ("a", "b"):
        session = await retail_context["new_session"]()
        sale = await create_retail_sale(
            session, payload=_otc_payload(retail_context, "concurrency_id", "4"), idempotency_key=f"ra4-race-{suffix}",
            tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
            actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
        )
        created_ids.append(sale.id)
        await session.close()

    async def attempt(sale_id):
        session = await retail_context["new_session"]()
        try:
            await dispense_retail_sale(
                session, sale_id=sale_id, payload=RetailSaleDispense(payment_method="CASH"),
                tenant_id=retail_context["tenant_id"], facility_id=retail_context["facility_id"],
                actor_id=retail_context["pharmacist_a"], current_user=_user(retail_context, "pharmacist_a"),
            )
            return "dispensed"
        except ValueError:
            await session.rollback()
            return "rejected"
        finally:
            await session.close()

    outcomes = await asyncio.wait_for(asyncio.gather(*(attempt(sale_id) for sale_id in created_ids)), timeout=10)
    assert sorted(outcomes) == ["dispensed", "rejected"]
    verify = await retail_context["new_session"]()
    batch_quantity = await verify.scalar(select(InventoryBatch.available_quantity).where(InventoryBatch.medicine_id == retail_context["concurrency_id"]))
    assert batch_quantity == Decimal("1.000")
    assert await verify.scalar(select(func.count()).select_from(PharmacyRetailSale).where(PharmacyRetailSale.id.in_(created_ids), PharmacyRetailSale.status == "FULLY_DISPENSED")) == 1
    await verify.close()