import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.invoice import Invoice
from app.models.tenant.pharmacy_dispense import PharmacyDispense, PharmacyDispenseAllocation, PharmacyDispenseItem, PharmacyStockReservation
from app.models.tenant.pharmacy_location import PharmacyLocation
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.stock_transaction import StockTransaction
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit
from app.services.pharmacy_dispensing import approve_pharmacy_substitution, confirm_dispense_stock_consumption, confirm_full_internal_fulfillment, confirm_outside_purchase_fulfillment, confirm_partial_internal_fulfillment, create_stock_reservations, expire_stock_reservations, prepare_billable_pharmacy_line_items, propose_pharmacy_allocations, release_dispense_reservations, release_stock_reservation, resolve_billable_pharmacy_line_items, start_pharmacy_dispense, validate_billable_dispense_quantities, validate_pharmacy_dispense


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


@pytest_asyncio.fixture
async def validation_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[
                Patient.__table__, Visit.__table__, Prescription.__table__, PrescriptionItem.__table__,
                PharmacyQueue.__table__, PharmacyLocation.__table__, PharmacyDispense.__table__,
                PharmacyDispenseItem.__table__, PharmacyStockReservation.__table__, InventoryBatch.__table__,
                Invoice.__table__, StockTransaction.__table__, PharmacyDispenseAllocation.__table__,
            ],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_start_and_validate_dispense_snapshots_prescription_without_stock_mutation(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    user_id = uuid.uuid4()
    medicine_id = uuid.uuid4()
    patient = Patient(uhid="P28-001", first_name="Test", last_name="Patient", gender="M", phone="9000000001")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription.items.append(PrescriptionItem(
        medicine="Dolo 650", strength="650 mg", final_quantity="10", quantity="10", medicine_product_id=medicine_id,
        no_substitution=True, no_substitution_reason="Doctor restriction",
    ))
    validation_session.add(prescription)
    location = PharmacyLocation(
        tenant_id=tenant_id, facility_id=facility_id, location_code="P28", location_name="P28 Pharmacy",
        location_type="PHARMACY", active=True,
    )
    validation_session.add(location)
    await validation_session.flush()
    for batch_number, expiry, quantity in (("FEFO-A", date(2026, 10, 1), Decimal("6")), ("FEFO-B", date(2027, 2, 1), Decimal("20"))):
        validation_session.add(InventoryBatch(
            tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
            medicine_id=medicine_id, batch_number=batch_number, expiry_date=expiry,
            purchase_rate=Decimal("5.00"), mrp=Decimal("6.00"), received_quantity=quantity,
            available_quantity=quantity, reserved_quantity=Decimal("0"), status="ACTIVE",
        ))
    await validation_session.flush()
    queue = PharmacyQueue(prescription_id=prescription.id, uhid=patient.uhid, status="pending")
    validation_session.add(queue)
    await validation_session.commit()

    dispense = await start_pharmacy_dispense(
        validation_session, queue_id=queue.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=location.id, started_by=user_id,
    )
    repeated = await start_pharmacy_dispense(
        validation_session, queue_id=queue.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=location.id, started_by=user_id,
    )
    assert dispense.id == repeated.id
    assert dispense.status == "DRAFT"

    validated = await validate_pharmacy_dispense(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, validated_by=user_id,
    )
    assert validated.status == "VALIDATED"
    item = await validation_session.scalar(select(PharmacyDispenseItem).where(PharmacyDispenseItem.dispense_id == dispense.id))
    assert item.prescribed_quantity == Decimal("10")
    assert item.no_substitution_applied is True
    assert await validation_session.scalar(select(func.sum(InventoryBatch.available_quantity))) == Decimal("26")
    assert await validation_session.scalar(select(func.sum(InventoryBatch.reserved_quantity))) == Decimal("0")
    assert await validation_session.scalar(select(func.count()).select_from(PharmacyStockReservation)) == 0
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0

    await propose_pharmacy_allocations(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, proposed_by=user_id, as_of_date=date(2026, 1, 1),
    )
    allocations = (await validation_session.execute(select(PharmacyDispenseAllocation))).scalars().all()
    allocated_by_batch = {
        (await validation_session.get(InventoryBatch, allocation.inventory_batch_id)).batch_number: allocation.allocated_quantity
        for allocation in allocations
    }
    assert allocated_by_batch == {"FEFO-A": Decimal("6"), "FEFO-B": Decimal("4")}
    reservations = await create_stock_reservations(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, reserved_by=user_id, now=datetime(2026, 1, 1, tzinfo=timezone.utc), ttl_minutes=15,
    )
    assert len(reservations) == 2
    first_batch = await validation_session.scalar(select(InventoryBatch).where(InventoryBatch.batch_number == "FEFO-A"))
    assert first_batch.reserved_quantity == Decimal("6")
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0
    ready = await confirm_full_internal_fulfillment(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, confirmed_by=user_id,
    )
    assert ready.status == "READY_FOR_BILLING"
    assert item.internal_confirmed_quantity == Decimal("10")
    assert item.outside_purchase_quantity == Decimal("0")
    assert all(reservation.status == "ACTIVE" for reservation in reservations)
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0
    await release_stock_reservation(
        validation_session, reservation_id=reservations[0].id, tenant_id=tenant_id,
        facility_id=facility_id, released_by=user_id,
    )
    await release_stock_reservation(
        validation_session, reservation_id=reservations[0].id, tenant_id=tenant_id,
        facility_id=facility_id, released_by=user_id,
    )


@pytest.mark.asyncio
async def test_validation_rejects_changed_prescription_version(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    patient = Patient(uhid="P28-002", first_name="Version", last_name="Patient", gender="F", phone="9000000002")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription.items.append(PrescriptionItem(medicine="Test", quantity="2", final_quantity="2"))
    validation_session.add(prescription)
    location = PharmacyLocation(
        tenant_id=tenant_id, facility_id=facility_id, location_code="P28-V", location_name="Version Pharmacy",
        location_type="PHARMACY", active=True,
    )
    validation_session.add(location)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, status="DRAFT",
    )
    validation_session.add(dispense)
    await validation_session.commit()
    prescription.version = 2
    await validation_session.commit()

    with pytest.raises(ValueError, match="version"):
        await validate_pharmacy_dispense(
            validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
            facility_id=facility_id, validated_by=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_partial_internal_fulfillment_preserves_shortage_and_reservation(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    user_id = uuid.uuid4()
    patient = Patient(uhid="P28-003", first_name="Partial", last_name="Patient", gender="M", phone="9000000003")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Partial Medicine", medicine_product_id=uuid.uuid4(), quantity="10", final_quantity="10")
    prescription.items.append(prescription_item)
    location = PharmacyLocation(tenant_id=tenant_id, facility_id=facility_id, location_code="P28-P", location_name="Partial Pharmacy", location_type="PHARMACY", active=True)
    validation_session.add_all([prescription, location])
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, status="RESERVED",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        medicine_id=prescription_item.medicine_product_id, batch_number="PARTIAL-BATCH",
        expiry_date=date(2027, 1, 1), purchase_rate=Decimal("5"), mrp=Decimal("6"),
        received_quantity=Decimal("6"), available_quantity=Decimal("6"), reserved_quantity=Decimal("6"), status="ACTIVE",
    )
    item = PharmacyDispenseItem(
        dispense_id=dispense.id, prescription_item_id=prescription_item.id,
        prescribed_medicine_product_id=prescription_item.medicine_product_id,
        prescribed_name_snapshot="Partial Medicine", prescribed_quantity=Decimal("10"),
        internal_requested_quantity=Decimal("10"), status="PENDING",
    )
    validation_session.add_all([batch, item])
    await validation_session.flush()
    allocation = PharmacyDispenseAllocation(
        dispense_item_id=item.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=location.id, inventory_batch_id=batch.id,
        allocated_quantity=Decimal("6"), confirmed_dispensed_quantity=Decimal("0"), status="RESERVED",
    )
    reservation = PharmacyStockReservation(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        dispense_id=dispense.id, dispense_item_id=item.id, inventory_batch_id=batch.id,
        quantity=Decimal("6"), status="ACTIVE", reserved_at=datetime.now(timezone.utc),
        reserved_by=user_id, expires_at=datetime.now(timezone.utc),
    )
    validation_session.add_all([allocation, reservation])
    await validation_session.commit()

    result = await confirm_partial_internal_fulfillment(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, confirmed_by=user_id,
    )

    assert result.status == "PARTIALLY_FULFILLED"
    assert item.internal_confirmed_quantity == Decimal("6")
    assert item.outside_purchase_quantity == Decimal("0")
    assert item.status == "PARTIAL"
    assert reservation.status == "ACTIVE"
    assert batch.available_quantity == Decimal("6")
    assert batch.reserved_quantity == Decimal("6")
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0


@pytest.mark.asyncio
async def test_outside_purchase_completes_fulfillment_without_stock_movement(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    patient = Patient(uhid="P28-004", first_name="Outside", last_name="Patient", gender="F", phone="9000000004")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Unavailable Medicine", quantity="10", final_quantity="10")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=uuid.uuid4(),
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, status="VALIDATED",
    )
    validation_session.add_all([prescription, dispense])
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id, prescription_item_id=prescription_item.id,
        prescribed_name_snapshot="Unavailable Medicine", prescribed_quantity=Decimal("10"), status="PENDING",
    )
    validation_session.add(item)
    await validation_session.commit()

    result = await confirm_outside_purchase_fulfillment(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, quantities={item.id: Decimal("10")}, confirmed_by=uuid.uuid4(),
    )

    assert result.status == "OUTSIDE_FULFILLED"
    assert item.outside_purchase_quantity == Decimal("10")
    assert item.internal_confirmed_quantity == Decimal("0")
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0
    assert prescription_item.quantity == "10"


@pytest.mark.asyncio
async def test_billable_quantity_rejects_outside_purchase_and_overbilling(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    patient = Patient(uhid="P28-005", first_name="Billable", last_name="Patient", gender="M", phone="9000000005")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    item = PrescriptionItem(medicine="Billable Medicine", quantity="10", final_quantity="10")
    prescription.items.append(item)
    validation_session.add(prescription)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=uuid.uuid4(),
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, status="READY_FOR_BILLING",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    bill_only_item = PharmacyDispenseItem(
        dispense_id=dispense.id, prescription_item_id=item.id,
        prescribed_name_snapshot="Billable Medicine", prescribed_quantity=Decimal("10"),
        internal_confirmed_quantity=Decimal("6"), outside_purchase_quantity=Decimal("0"), status="PARTIAL",
    )
    validation_session.add(bill_only_item)
    await validation_session.commit()

    with pytest.raises(ValueError, match="Billable quantity exceeds confirmed hospital-supplied quantity"):
        await validate_billable_dispense_quantities(
            validation_session,
            dispense_id=dispense.id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            requested_total_quantity=Decimal("7"),
        )

    outside_dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=uuid.uuid4(),
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, status="READY_FOR_BILLING",
    )
    validation_session.add(outside_dispense)
    await validation_session.flush()
    outside_item = PharmacyDispenseItem(
        dispense_id=outside_dispense.id, prescription_item_id=item.id,
        prescribed_name_snapshot="Outside Purchase Medicine", prescribed_quantity=Decimal("4"),
        internal_confirmed_quantity=Decimal("0"), outside_purchase_quantity=Decimal("4"), status="PARTIAL",
    )
    validation_session.add(outside_item)
    await validation_session.commit()

    with pytest.raises(ValueError, match="Outside-purchase quantities cannot be billed"):
        await validate_billable_dispense_quantities(
            validation_session,
            dispense_id=outside_dispense.id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            requested_total_quantity=Decimal("10"),
        )

    confirmed = await validate_billable_dispense_quantities(
        validation_session,
        dispense_id=dispense.id,
        tenant_id=tenant_id,
        facility_id=facility_id,
        requested_total_quantity=Decimal("6"),
    )
    assert confirmed == Decimal("6")


def test_prepare_billable_lines_excludes_outside_purchase_quantity():
    dispense_id = uuid.uuid4()
    item = PharmacyDispenseItem(
        id=uuid.uuid4(), dispense_id=dispense_id, prescription_item_id=uuid.uuid4(),
        prescribed_name_snapshot="Mixed Medicine", prescribed_quantity=Decimal("10"),
        internal_confirmed_quantity=Decimal("6"), outside_purchase_quantity=Decimal("4"),
    )
    outside_only = PharmacyDispenseItem(
        id=uuid.uuid4(), dispense_id=dispense_id, prescription_item_id=uuid.uuid4(),
        prescribed_name_snapshot="Outside Medicine", prescribed_quantity=Decimal("4"),
        internal_confirmed_quantity=Decimal("0"), outside_purchase_quantity=Decimal("4"),
    )

    lines = prepare_billable_pharmacy_line_items([
        {"name": "Mixed Medicine", "qty": 10, "mrp": 5, "gst_pct": 0, "dis_pct": 0, "total": 50},
        {"name": "Outside Medicine", "qty": 4, "mrp": 8, "gst_pct": 0, "dis_pct": 0, "total": 32},
    ], [item, outside_only])

    assert len(lines) == 1
    assert lines[0]["dispense_item_id"] == str(item.id)
    assert lines[0]["qty"] == 6.0
    assert lines[0]["total"] == 30.0


def test_prepare_billable_lines_excludes_quantity_billed_by_previous_dispense():
    item = PharmacyDispenseItem(
        id=uuid.uuid4(), dispense_id=uuid.uuid4(), prescription_item_id=uuid.uuid4(),
        prescribed_name_snapshot="Repeated Medicine", prescribed_quantity=Decimal("10"),
        internal_confirmed_quantity=Decimal("10"), outside_purchase_quantity=Decimal("0"),
    )

    lines = prepare_billable_pharmacy_line_items([
        {"name": "Repeated Medicine", "qty": 10, "mrp": 5, "gst_pct": 0, "dis_pct": 0, "total": 50},
    ], [item], {item.prescription_item_id: Decimal("6")})

    assert len(lines) == 1
    assert lines[0]["qty"] == 4.0
    assert lines[0]["prescription_item_id"] == str(item.prescription_item_id)


@pytest.mark.asyncio
async def test_resolve_billable_lines_uses_allocated_batch_mrp(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id, facility_id=facility_id, location_code="P29-PRICE",
        location_name="Price Pharmacy", location_type="PHARMACY", active=True,
    )
    patient = Patient(uhid="P29-PRICE", first_name="Price", last_name="Patient", gender="M", phone="9000000029")
    validation_session.add_all([location, patient])
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Server Priced Medicine", quantity="6", final_quantity="6")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, status="READY_FOR_BILLING",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id, prescription_item_id=prescription_item.id,
        prescribed_name_snapshot="Server Priced Medicine", prescribed_quantity=Decimal("6"),
        internal_confirmed_quantity=Decimal("6"), outside_purchase_quantity=Decimal("0"),
    )
    batch = InventoryBatch(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(), batch_number="PRICE-BATCH", expiry_date=date(2027, 1, 1),
        purchase_rate=Decimal("40"), mrp=Decimal("55"), received_quantity=Decimal("6"),
        available_quantity=Decimal("0"), reserved_quantity=Decimal("6"), status="ACTIVE",
    )
    validation_session.add_all([item, batch])
    await validation_session.flush()
    allocation = PharmacyDispenseAllocation(
        dispense_item_id=item.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=location.id, inventory_batch_id=batch.id,
        allocated_quantity=Decimal("6"), confirmed_dispensed_quantity=Decimal("6"), status="RESERVED",
    )
    validation_session.add(allocation)
    await validation_session.commit()

    lines = await resolve_billable_pharmacy_line_items(
        validation_session,
        line_items=[{"name": "Server Priced Medicine", "qty": 6, "mrp": 999, "gst_pct": 99, "dis_pct": 20, "total": 9999}],
        dispense_items=[item], tenant_id=tenant_id, facility_id=facility_id,
    )

    assert lines[0]["mrp"] == 55.0
    assert lines[0]["gst_pct"] == 0.0
    assert lines[0]["dis_pct"] == 0.0
    assert lines[0]["total"] == 330.0


@pytest.mark.asyncio
async def test_no_substitution_policy_rejects_replacement(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=uuid.uuid4(),
        prescription_id=uuid.uuid4(), prescription_version=1, visit_id=uuid.uuid4(),
        patient_id=uuid.uuid4(), status="VALIDATED",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id, prescription_item_id=uuid.uuid4(),
        prescribed_medicine_product_id=uuid.uuid4(), prescribed_name_snapshot="Restricted Medicine",
        prescribed_quantity=Decimal("1"), no_substitution_applied=True, status="PENDING",
    )
    validation_session.add(item)
    await validation_session.commit()

    with pytest.raises(ValueError, match="prohibited"):
        await approve_pharmacy_substitution(
            validation_session, dispense_id=dispense.id, dispense_item_id=item.id,
            tenant_id=tenant_id, facility_id=facility_id,
            dispensed_medicine_product_id=uuid.uuid4(), substitution_reason="Equivalent unavailable",
            approved_by=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_confirm_dispense_consumes_reservation_and_is_idempotent(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    user_id = uuid.uuid4()
    patient = Patient(uhid="P28-005", first_name="Confirm", last_name="Patient", gender="M", phone="9000000005")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    product_id = uuid.uuid4()
    prescription_item = PrescriptionItem(medicine="Confirmed Medicine", medicine_product_id=product_id, quantity="5", final_quantity="5")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    location = PharmacyLocation(tenant_id=tenant_id, facility_id=facility_id, location_code="P28-C", location_name="Confirm Pharmacy", location_type="PHARMACY", active=True)
    validation_session.add(location)
    await validation_session.flush()
    queue = PharmacyQueue(prescription_id=prescription.id, uhid=patient.uhid, status="dispensing")
    validation_session.add(queue)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, pharmacy_queue_id=queue.id, status="READY_FOR_BILLING",
    )
    batch = InventoryBatch(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        medicine_id=product_id, batch_number="CONFIRM-BATCH", expiry_date=date(2027, 1, 1),
        purchase_rate=Decimal("5"), mrp=Decimal("6"), received_quantity=Decimal("5"),
        available_quantity=Decimal("5"), reserved_quantity=Decimal("5"), status="ACTIVE",
    )
    validation_session.add_all([dispense, batch])
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id, prescription_item_id=prescription_item.id,
        prescribed_medicine_product_id=product_id, prescribed_name_snapshot="Confirmed Medicine",
        prescribed_quantity=Decimal("5"), internal_confirmed_quantity=Decimal("5"), status="FULFILLED",
    )
    validation_session.add(item)
    await validation_session.flush()
    allocation = PharmacyDispenseAllocation(
        dispense_item_id=item.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=location.id, inventory_batch_id=batch.id,
        allocated_quantity=Decimal("5"), confirmed_dispensed_quantity=Decimal("5"), status="RESERVED",
    )
    reservation = PharmacyStockReservation(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        dispense_id=dispense.id, dispense_item_id=item.id, inventory_batch_id=batch.id,
        quantity=Decimal("5"), status="ACTIVE", reserved_at=datetime.now(timezone.utc),
        reserved_by=user_id, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    validation_session.add_all([allocation, reservation])
    invoice = Invoice(
        visit_id=visit.id, uhid=patient.uhid, line_items=[], subtotal=30.0, tax=0.0, total=30.0,
        source="pharmacy_dispense", pharmacy_dispense_id=dispense.id, status="paid", paid_amount=30.0,
        paid_at=datetime.now(timezone.utc), payment_method="cash",
    )
    validation_session.add(invoice)
    dispense.invoice_id = invoice.id
    dispense.billing_status = "AUTHORIZED"
    await validation_session.commit()

    confirmed = await confirm_dispense_stock_consumption(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, confirmed_by=user_id, billing_authorized=True,
    )
    repeated = await confirm_dispense_stock_consumption(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, confirmed_by=user_id, billing_authorized=True,
    )

    assert confirmed.id == repeated.id
    assert confirmed.status == "CONFIRMED"
    assert confirmed.billing_status == "AUTHORIZED"
    assert batch.available_quantity == Decimal("0")
    assert batch.reserved_quantity == Decimal("0")
    assert reservation.status == "CONSUMED"
    assert allocation.status == "CONSUMED"
    assert allocation.stock_transaction_id is not None
    transactions = (await validation_session.execute(select(StockTransaction).where(StockTransaction.reference_id == allocation.id))).scalars().all()
    assert len(transactions) == 1
    assert transactions[0].quantity == Decimal("-5")
    assert transactions[0].previous_balance == Decimal("5")
    assert transactions[0].new_balance == Decimal("0")
    assert queue.status == "dispensed"


@pytest.mark.asyncio
async def test_paid_invoice_authorizes_billing_without_stock_deduction(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    user_id = uuid.uuid4()
    patient = Patient(uhid="P28-AUTH", first_name="Auth", last_name="Patient", gender="M", phone="9000000011")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Authorize Medicine", quantity="3", final_quantity="3")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    await validation_session.flush()
    location = PharmacyLocation(tenant_id=tenant_id, facility_id=facility_id, location_code="P28-A", location_name="Auth Pharmacy", location_type="PHARMACY", active=True)
    validation_session.add(location)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, status="READY_FOR_BILLING",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(), batch_number="AUTH-BATCH", expiry_date=date(2027, 1, 1),
        purchase_rate=Decimal("5"), mrp=Decimal("6"), received_quantity=Decimal("3"),
        available_quantity=Decimal("3"), reserved_quantity=Decimal("3"), status="ACTIVE",
    )
    validation_session.add(batch)
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id, prescription_item_id=prescription_item.id,
        prescribed_name_snapshot="Authorize Medicine", prescribed_quantity=Decimal("3"),
        internal_confirmed_quantity=Decimal("3"), status="FULFILLED",
    )
    validation_session.add(item)
    await validation_session.flush()
    allocation = PharmacyDispenseAllocation(
        dispense_item_id=item.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=location.id, inventory_batch_id=batch.id,
        allocated_quantity=Decimal("3"), confirmed_dispensed_quantity=Decimal("3"), status="RESERVED",
    )
    reservation = PharmacyStockReservation(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        dispense_id=dispense.id, dispense_item_id=item.id, inventory_batch_id=batch.id,
        quantity=Decimal("3"), status="ACTIVE", reserved_at=datetime.now(timezone.utc),
        reserved_by=user_id, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    validation_session.add_all([allocation, reservation])
    invoice = Invoice(
        visit_id=visit.id, uhid=patient.uhid, line_items=[], subtotal=18.0, tax=0.0, total=18.0,
        source="pharmacy_dispense", pharmacy_dispense_id=dispense.id, status="paid", paid_amount=18.0,
        paid_at=datetime.now(timezone.utc), payment_method="cash",
    )
    validation_session.add(invoice)
    dispense.invoice_id = invoice.id
    await validation_session.commit()

    authorized = await validation_session.run_sync(lambda s: None)
    from app.services.pharmacy_dispensing import authorize_pharmacy_billing
    authorized = await authorize_pharmacy_billing(
        validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
        facility_id=facility_id, confirmed_by=user_id, invoice_id=invoice.id,
    )

    assert authorized.billing_status == "AUTHORIZED"
    assert batch.available_quantity == Decimal("3")
    assert batch.reserved_quantity == Decimal("3")
    assert reservation.status == "ACTIVE"
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0


@pytest.mark.asyncio
async def test_unpaid_invoice_cannot_authorize_stock_consumption(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    user_id = uuid.uuid4()
    patient = Patient(uhid="P28-UNPAID", first_name="Unpaid", last_name="Patient", gender="M", phone="9000000012")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Unpaid Medicine", quantity="2", final_quantity="2")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    await validation_session.flush()
    location = PharmacyLocation(tenant_id=tenant_id, facility_id=facility_id, location_code="P28-U", location_name="Unpaid Pharmacy", location_type="PHARMACY", active=True)
    validation_session.add(location)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        prescription_id=prescription.id, prescription_version=1, visit_id=visit.id,
        patient_id=patient.id, status="READY_FOR_BILLING",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(), batch_number="UNPAID-BATCH", expiry_date=date(2027, 1, 1),
        purchase_rate=Decimal("5"), mrp=Decimal("6"), received_quantity=Decimal("2"),
        available_quantity=Decimal("2"), reserved_quantity=Decimal("2"), status="ACTIVE",
    )
    validation_session.add(batch)
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id, prescription_item_id=prescription_item.id,
        prescribed_name_snapshot="Unpaid Medicine", prescribed_quantity=Decimal("2"),
        internal_confirmed_quantity=Decimal("2"), status="FULFILLED",
    )
    validation_session.add(item)
    await validation_session.flush()
    allocation = PharmacyDispenseAllocation(
        dispense_item_id=item.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=location.id, inventory_batch_id=batch.id,
        allocated_quantity=Decimal("2"), confirmed_dispensed_quantity=Decimal("2"), status="RESERVED",
    )
    reservation = PharmacyStockReservation(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id,
        dispense_id=dispense.id, dispense_item_id=item.id, inventory_batch_id=batch.id,
        quantity=Decimal("2"), status="ACTIVE", reserved_at=datetime.now(timezone.utc),
        reserved_by=user_id, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    validation_session.add_all([allocation, reservation])
    invoice = Invoice(
        visit_id=visit.id, uhid=patient.uhid, line_items=[], subtotal=12.0, tax=0.0, total=12.0,
        source="pharmacy_dispense", pharmacy_dispense_id=dispense.id, status="draft", paid_amount=0.0,
    )
    validation_session.add(invoice)
    dispense.invoice_id = invoice.id
    await validation_session.commit()

    with pytest.raises(ValueError, match="paid|server-authorized|authorization"):
        await confirm_dispense_stock_consumption(
            validation_session, dispense_id=dispense.id, tenant_id=tenant_id,
            facility_id=facility_id, confirmed_by=user_id, billing_authorized=True,
        )

    assert batch.available_quantity == Decimal("2")
    assert batch.reserved_quantity == Decimal("2")
    assert reservation.status == "ACTIVE"
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0


@pytest.mark.asyncio
async def test_confirm_dispense_requires_billing_authorization(validation_session):
    with pytest.raises(ValueError, match="Billing authorization"):
        await confirm_dispense_stock_consumption(
            validation_session, dispense_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
            facility_id=uuid.uuid4(), confirmed_by=uuid.uuid4(), billing_authorized=False,
        )


@pytest.mark.asyncio
async def test_cancel_dispense_releases_reservations_without_stock_deduction(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    patient = Patient(uhid="P29-CANCEL", first_name="Cancel", last_name="Patient", gender="M", phone="9000000030")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Cancel Medicine", quantity="2", final_quantity="2")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    await validation_session.flush()
    location = PharmacyLocation(tenant_id=tenant_id, facility_id=facility_id, location_code="P29-C", location_name="Cancel Pharmacy", location_type="PHARMACY", active=True)
    validation_session.add(location)
    await validation_session.flush()
    dispense = PharmacyDispense(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, prescription_id=prescription.id, prescription_version=1, visit_id=visit.id, patient_id=patient.id, status="READY_FOR_BILLING")
    validation_session.add(dispense)
    await validation_session.flush()
    queue = PharmacyQueue(prescription_id=prescription.id, uhid=patient.uhid, status="dispensing")
    validation_session.add(queue)
    dispense.pharmacy_queue_id = queue.id
    await validation_session.flush()
    batch = InventoryBatch(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, medicine_id=uuid.uuid4(), batch_number="CANCEL-BATCH", expiry_date=date(2027, 1, 1), purchase_rate=Decimal("5"), mrp=Decimal("6"), received_quantity=Decimal("2"), available_quantity=Decimal("0"), reserved_quantity=Decimal("2"), status="ACTIVE")
    validation_session.add(batch)
    await validation_session.flush()
    item = PharmacyDispenseItem(dispense_id=dispense.id, prescription_item_id=prescription_item.id, prescribed_name_snapshot="Cancel Medicine", prescribed_quantity=Decimal("2"), internal_confirmed_quantity=Decimal("2"), status="FULFILLED")
    validation_session.add(item)
    await validation_session.flush()
    reservation = PharmacyStockReservation(tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=location.id, dispense_id=dispense.id, dispense_item_id=item.id, inventory_batch_id=batch.id, quantity=Decimal("2"), status="ACTIVE", reserved_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(minutes=15))
    validation_session.add(reservation)
    await validation_session.commit()

    result = await release_dispense_reservations(validation_session, dispense_id=dispense.id, tenant_id=tenant_id, facility_id=facility_id, reason="Payment abandoned")

    assert result.status == "CANCELLED"
    assert result.billing_status == "CANCELLED"
    assert reservation.status == "CANCELLED"
    assert batch.available_quantity == Decimal("0")
    assert batch.reserved_quantity == Decimal("0")
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0


@pytest.mark.asyncio
async def test_paid_authorized_reservation_is_protected_from_expiry(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    user_id = uuid.uuid4()
    patient = Patient(uhid="P29-PROTECTED", first_name="Protected", last_name="Patient", gender="M", phone="9000000032")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Protected Medicine", quantity="2", final_quantity="2")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    await validation_session.flush()
    location = PharmacyLocation(tenant_id=tenant_id, facility_id=facility_id, location_code="P29-P", location_name="Protected Pharmacy", location_type="PHARMACY", active=True)
    validation_session.add(location)
    await validation_session.flush()
    queue = PharmacyQueue(prescription_id=prescription.id, uhid=patient.uhid, status="dispensing")
    validation_session.add(queue)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        prescription_id=prescription.id,
        prescription_version=1,
        visit_id=visit.id,
        patient_id=patient.id,
        pharmacy_queue_id=queue.id,
        status="READY_FOR_BILLING",
        billing_status="AUTHORIZED",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        batch_number="PROTECTED-BATCH",
        expiry_date=date(2027, 1, 1),
        purchase_rate=Decimal("5"),
        mrp=Decimal("6"),
        received_quantity=Decimal("2"),
        available_quantity=Decimal("0"),
        reserved_quantity=Decimal("2"),
        status="ACTIVE",
    )
    validation_session.add(batch)
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id,
        prescription_item_id=prescription_item.id,
        prescribed_name_snapshot="Protected Medicine",
        prescribed_quantity=Decimal("2"),
        internal_confirmed_quantity=Decimal("2"),
        status="FULFILLED",
    )
    validation_session.add(item)
    await validation_session.flush()
    reservation = PharmacyStockReservation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        dispense_id=dispense.id,
        dispense_item_id=item.id,
        inventory_batch_id=batch.id,
        quantity=Decimal("2"),
        status="ACTIVE",
        reserved_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        reserved_by=user_id,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    validation_session.add(reservation)
    invoice = Invoice(
        visit_id=visit.id,
        uhid=patient.uhid,
        line_items=[],
        subtotal=12.0,
        tax=0.0,
        total=12.0,
        source="pharmacy_dispense",
        pharmacy_dispense_id=dispense.id,
        status="paid",
        paid_amount=12.0,
        paid_at=datetime.now(timezone.utc),
        payment_method="cash",
    )
    validation_session.add(invoice)
    dispense.invoice_id = invoice.id
    await validation_session.commit()

    expired = await expire_stock_reservations(
        validation_session,
        tenant_id=tenant_id,
        now=datetime.now(timezone.utc),
        released_by=user_id,
    )

    assert expired == 0
    assert reservation.status == "ACTIVE"
    assert batch.reserved_quantity == Decimal("2")
    assert dispense.status == "READY_FOR_BILLING"
    assert dispense.billing_status == "AUTHORIZED"
    assert queue.status == "dispensing"
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0


@pytest.mark.asyncio
async def test_paid_pre_dispense_refund_releases_reservation_without_stock_deduction(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    patient = Patient(uhid="P29-REFUND", first_name="Refund", last_name="Patient", gender="M", phone="9000000033")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Refund Medicine", quantity="2", final_quantity="2")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    await validation_session.flush()
    location = PharmacyLocation(tenant_id=tenant_id, facility_id=facility_id, location_code="P29-R", location_name="Refund Pharmacy", location_type="PHARMACY", active=True)
    validation_session.add(location)
    await validation_session.flush()
    queue = PharmacyQueue(prescription_id=prescription.id, uhid=patient.uhid, status="dispensing")
    validation_session.add(queue)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        prescription_id=prescription.id,
        prescription_version=1,
        visit_id=visit.id,
        patient_id=patient.id,
        pharmacy_queue_id=queue.id,
        status="READY_FOR_BILLING",
        billing_status="AUTHORIZED",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        batch_number="REFUND-BATCH",
        expiry_date=date(2027, 1, 1),
        purchase_rate=Decimal("5"),
        mrp=Decimal("6"),
        received_quantity=Decimal("2"),
        available_quantity=Decimal("0"),
        reserved_quantity=Decimal("2"),
        status="ACTIVE",
    )
    validation_session.add(batch)
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id,
        prescription_item_id=prescription_item.id,
        prescribed_name_snapshot="Refund Medicine",
        prescribed_quantity=Decimal("2"),
        internal_confirmed_quantity=Decimal("2"),
        status="FULFILLED",
    )
    validation_session.add(item)
    await validation_session.flush()
    reservation = PharmacyStockReservation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        dispense_id=dispense.id,
        dispense_item_id=item.id,
        inventory_batch_id=batch.id,
        quantity=Decimal("2"),
        status="ACTIVE",
        reserved_at=datetime.now(timezone.utc),
        reserved_by=patient.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    validation_session.add(reservation)
    invoice = Invoice(
        visit_id=visit.id,
        uhid=patient.uhid,
        line_items=[],
        subtotal=12.0,
        tax=0.0,
        total=12.0,
        source="pharmacy_dispense",
        pharmacy_dispense_id=dispense.id,
        status="paid",
        paid_amount=12.0,
        paid_at=datetime.now(timezone.utc),
        payment_method="cash",
    )
    validation_session.add(invoice)
    dispense.invoice_id = invoice.id
    await validation_session.commit()

    invoice.status = "refunded"
    result = await release_dispense_reservations(
        validation_session,
        dispense_id=dispense.id,
        tenant_id=tenant_id,
        facility_id=facility_id,
        released_by=patient.id,
        reason="Patient cancelled before dispense",
    )

    assert result.status == "CANCELLED"
    assert reservation.status == "CANCELLED"
    assert batch.reserved_quantity == Decimal("0")
    assert dispense.billing_status == "CANCELLED"
    assert queue.status == "cancelled"
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0


@pytest.mark.asyncio
async def test_expired_reservation_marks_dispense_and_queue_expired(validation_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    user_id = uuid.uuid4()
    patient = Patient(uhid="P29-EXPIRE", first_name="Expired", last_name="Patient", gender="M", phone="9000000031")
    validation_session.add(patient)
    await validation_session.flush()
    visit = Visit(patient_id=patient.id, uhid=patient.uhid, status="CONSULTATION_COMPLETED")
    validation_session.add(visit)
    await validation_session.flush()
    prescription = Prescription(visit_id=visit.id, uhid=patient.uhid, status="finalized", version=1)
    prescription_item = PrescriptionItem(medicine="Expired Medicine", quantity="2", final_quantity="2")
    prescription.items.append(prescription_item)
    validation_session.add(prescription)
    await validation_session.flush()
    location = PharmacyLocation(tenant_id=tenant_id, facility_id=facility_id, location_code="P29-E", location_name="Expire Pharmacy", location_type="PHARMACY", active=True)
    validation_session.add(location)
    await validation_session.flush()
    queue = PharmacyQueue(prescription_id=prescription.id, uhid=patient.uhid, status="dispensing")
    validation_session.add(queue)
    await validation_session.flush()
    dispense = PharmacyDispense(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        prescription_id=prescription.id,
        prescription_version=1,
        visit_id=visit.id,
        patient_id=patient.id,
        pharmacy_queue_id=queue.id,
        status="READY_FOR_BILLING",
        billing_status="PENDING",
    )
    validation_session.add(dispense)
    await validation_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        batch_number="EXPIRE-BATCH",
        expiry_date=date(2027, 1, 1),
        purchase_rate=Decimal("5"),
        mrp=Decimal("6"),
        received_quantity=Decimal("2"),
        available_quantity=Decimal("0"),
        reserved_quantity=Decimal("2"),
        status="ACTIVE",
    )
    validation_session.add(batch)
    await validation_session.flush()
    item = PharmacyDispenseItem(
        dispense_id=dispense.id,
        prescription_item_id=prescription_item.id,
        prescribed_name_snapshot="Expired Medicine",
        prescribed_quantity=Decimal("2"),
        internal_confirmed_quantity=Decimal("2"),
        status="FULFILLED",
    )
    validation_session.add(item)
    await validation_session.flush()
    reservation = PharmacyStockReservation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        dispense_id=dispense.id,
        dispense_item_id=item.id,
        inventory_batch_id=batch.id,
        quantity=Decimal("2"),
        status="ACTIVE",
        reserved_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        reserved_by=user_id,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    validation_session.add(reservation)
    await validation_session.commit()

    expired = await expire_stock_reservations(
        validation_session,
        tenant_id=tenant_id,
        now=datetime.now(timezone.utc),
        released_by=user_id,
    )

    assert expired == 1
    assert reservation.status == "EXPIRED"
    assert batch.reserved_quantity == Decimal("0")
    assert dispense.status == "EXPIRED"
    assert dispense.billing_status == "EXPIRED"
    assert queue.status == "cancelled"
    assert await validation_session.scalar(select(func.count()).select_from(StockTransaction)) == 0
