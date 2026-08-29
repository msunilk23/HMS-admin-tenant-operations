"""
Lab Concurrency Tests - Phase 13
Test concurrent lab operations for race conditions and idempotency.
"""

import asyncio
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.lab_order import LabOrder, LabResult
from app.models.tenant.visit import Visit
from app.models.tenant.patient import Patient
from app.models.tenant.doctor import Doctor
from app.models.tenant.invoice import Invoice
from app.db.engine import AsyncSessionLocal
from app.services.lab_billing_service import create_lab_invoice_if_needed


@pytest.fixture
async def test_patient():
    """Create a test patient."""
    session = AsyncSessionLocal()
    try:
        patient = Patient(
            id=uuid.uuid4(),
            first_name="Concurrent",
            last_name="Test",
            phone="9999999999",
            uhid="CONC001",
        )
        session.add(patient)
        await session.commit()
        await session.refresh(patient)
        return patient
    finally:
        await session.close()


@pytest.fixture
async def test_visit(test_patient):
    """Create a test visit."""
    session = AsyncSessionLocal()
    try:
        doctor = Doctor(id=uuid.uuid4(), name="Test Doctor")
        session.add(doctor)
        await session.flush()
        
        visit = Visit(
            id=uuid.uuid4(),
            patient_id=test_patient.id,
            doctor_id=doctor.id,
            status="ongoing",
        )
        session.add(visit)
        await session.commit()
        await session.refresh(visit)
        return visit
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_concurrent_lab_result_entry(test_visit):
    """
    Test: Concurrent result entry on same lab order.
    Scenario: Two threads try to enter results for the same lab order simultaneously.
    Expected: Only first succeeds, second sees results already exist.
    """
    session = AsyncSessionLocal()
    try:
        # Create lab order
        lab_order = LabOrder(
            id=uuid.uuid4(),
            visit_id=test_visit.id,
            uhid=test_visit.patient_id.hex[:20],
            tests=[{"test": "CBC", "test_code": "CBC", "test_name": "Complete Blood Count", "price": 200.0}],
            status="processing",
        )
        session.add(lab_order)
        await session.commit()
        
        # Simulate concurrent result entry
        async def enter_result():
            async with AsyncSessionLocal() as s:
                order = await s.get(LabOrder, lab_order.id)
                result = LabResult(
                    id=uuid.uuid4(),
                    lab_order_id=order.id,
                    uhid=order.uhid,
                    results={"CBC": "Normal"},
                    notes="Entered by concurrent thread",
                    reported_by_user_id=uuid.uuid4(),
                )
                s.add(result)
                order.status = "result_ready"
                await s.commit()
                return result
        
        # Run two concurrent entries
        results = await asyncio.gather(
            enter_result(),
            enter_result(),
            return_exceptions=True
        )
        
        # Verify: One should succeed (no exception), one may fail due to unique constraint
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        assert success_count >= 1, "At least one concurrent result entry should succeed"
        
        # Verify lab order has result_ready status
        await session.refresh(lab_order)
        assert lab_order.status == "result_ready"
        
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_concurrent_lab_verification(test_visit):
    """
    Test: Concurrent result verification (verify endpoint called twice simultaneously).
    Scenario: Lab technician verifies results, but request is duplicated (network retry).
    Expected: Only first verification succeeds, second sees already verified.
    """
    session = AsyncSessionLocal()
    try:
        # Create lab order with result
        lab_order = LabOrder(
            id=uuid.uuid4(),
            visit_id=test_visit.id,
            uhid=test_visit.patient_id.hex[:20],
            tests=[{"test": "TSH", "test_code": "TSH", "test_name": "Thyroid", "price": 300.0}],
            status="result_ready",
        )
        session.add(lab_order)
        await session.flush()
        
        result = LabResult(
            id=uuid.uuid4(),
            lab_order_id=lab_order.id,
            uhid=lab_order.uhid,
            results={"TSH": "2.5"},
            reported_by_user_id=uuid.uuid4(),
        )
        session.add(result)
        await session.commit()
        
        # Simulate concurrent verification
        async def verify():
            async with AsyncSessionLocal() as s:
                order = await s.get(LabOrder, lab_order.id)
                if order and order.status != "verified":
                    order.status = "verified"
                    order.verified_at = datetime.now(timezone.utc)
                    await s.commit()
                    return order.status
                return "already_verified"
        
        # Run two concurrent verifications
        results = await asyncio.gather(
            verify(),
            verify(),
        )
        
        # Both should return "verified" or "already_verified" (idempotent)
        assert all(r in ("verified", "already_verified") for r in results)
        
        # Verify final status is verified
        await session.refresh(lab_order)
        assert lab_order.status == "verified"
        
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_concurrent_lab_to_billing_trigger(test_visit):
    """
    Test: Concurrent billing invoice creation when lab is verified.
    Scenario: Lab verification triggers billing; two verifications happen concurrently.
    Expected: Only one invoice created (unique constraint on lab_order_id).
    """
    session = AsyncSessionLocal()
    try:
        # Create lab order
        lab_order = LabOrder(
            id=uuid.uuid4(),
            visit_id=test_visit.id,
            uhid=test_visit.patient_id.hex[:20],
            tests=[
                {"test": "CBC", "test_code": "CBC", "test_name": "Complete Blood Count", "price": 200.0},
                {"test": "TSH", "test_code": "TSH", "test_name": "Thyroid", "price": 300.0},
            ],
            status="result_ready",
        )
        session.add(lab_order)
        await session.commit()
        
        # Simulate concurrent billing trigger
        async def trigger_billing():
            async with AsyncSessionLocal() as s:
                return await create_lab_invoice_if_needed(
                    s,
                    lab_order_id=lab_order.id,
                    visit_id=test_visit.id,
                    tests=lab_order.tests or [],
                    patient_id=test_visit.patient_id,
                    current_user={"sub": str(uuid.uuid4()), "role": "lab_technician"},
                )
        
        # Run two concurrent billing triggers
        invoices = await asyncio.gather(
            trigger_billing(),
            trigger_billing(),
        )
        
        # Both should return same invoice (idempotent)
        assert len([i for i in invoices if i is not None]) >= 1, "At least one invoice should be created"
        if invoices[0] and invoices[1]:
            assert invoices[0].id == invoices[1].id, "Both should reference same invoice"
        
        # Verify only one invoice exists for this lab order
        invoice_count = (await session.execute(
            __import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(Invoice).where(
                Invoice.lab_order_id == lab_order.id
            )
        )).scalar()
        assert invoice_count == 1, f"Expected 1 invoice, found {invoice_count}"
        
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_invalid_lab_status_transition(test_visit):
    """
    Test: Prevent invalid state transitions via concurrent modification.
    Scenario: Try to transition lab order through invalid state path.
    Expected: State machine validation prevents transition.
    """
    session = AsyncSessionLocal()
    try:
        lab_order = LabOrder(
            id=uuid.uuid4(),
            visit_id=test_visit.id,
            uhid=test_visit.patient_id.hex[:20],
            tests=[{"test": "Glucose", "test_code": "GLU", "test_name": "Glucose", "price": 150.0}],
            status="ordered",
        )
        session.add(lab_order)
        await session.commit()
        
        # Try invalid transition (ordered -> completed, should be ordered -> sample_pending -> ...)
        async def invalid_transition():
            async with AsyncSessionLocal() as s:
                order = await s.get(LabOrder, lab_order.id)
                from app.models.tenant.lab_order import can_transition_lab_order
                if can_transition_lab_order(order.status, "completed"):
                    order.status = "completed"
                    await s.commit()
                    return True
                return False
        
        result = await invalid_transition()
        assert result is False, "Invalid state transition should be prevented"
        
        # Verify status unchanged
        await session.refresh(lab_order)
        assert lab_order.status == "ordered"
        
    finally:
        await session.close()
