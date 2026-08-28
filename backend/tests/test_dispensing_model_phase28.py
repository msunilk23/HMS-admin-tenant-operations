from sqlalchemy import inspect

from app.models.tenant.invoice import Invoice
from app.models.tenant.pharmacy_dispense import (
    PharmacyDispense,
    PharmacyDispenseAllocation,
    PharmacyDispenseItem,
    PharmacyStockReservation,
)
from app.models.tenant.prescription import Prescription, PrescriptionItem


def test_p28_dispensing_tables_and_constraints():
    assert PharmacyDispense.__tablename__ == "pharmacy_dispenses"
    assert PharmacyDispenseItem.__tablename__ == "pharmacy_dispense_items"
    assert PharmacyDispenseAllocation.__tablename__ == "pharmacy_dispense_allocations"
    assert PharmacyStockReservation.__tablename__ == "pharmacy_stock_reservations"

    dispense_columns = set(PharmacyDispense.__table__.c.keys())
    assert {"tenant_id", "facility_id", "prescription_id", "prescription_version", "status", "idempotency_key"} <= dispense_columns

    item_columns = set(PharmacyDispenseItem.__table__.c.keys())
    assert {"prescription_item_id", "prescribed_quantity", "internal_confirmed_quantity", "outside_purchase_quantity", "no_substitution_applied"} <= item_columns

    allocation_columns = set(PharmacyDispenseAllocation.__table__.c.keys())
    assert {"dispense_item_id", "inventory_batch_id", "allocated_quantity", "confirmed_dispensed_quantity", "allocation_source"} <= allocation_columns

    reservation_columns = set(PharmacyStockReservation.__table__.c.keys())
    assert {"dispense_id", "dispense_item_id", "inventory_batch_id", "quantity", "status", "expires_at"} <= reservation_columns

    assert any(
        constraint.name == "uq_pharmacy_dispenses_tenant_idempotency"
        for constraint in PharmacyDispense.__table__.constraints
    )
    assert any(
        constraint.name == "uq_pharmacy_dispense_items_dispense_prescription"
        for constraint in PharmacyDispenseItem.__table__.constraints
    )
    assert any(
        constraint.name == "uq_pharmacy_allocations_item_batch"
        for constraint in PharmacyDispenseAllocation.__table__.constraints
    )
    assert any(
        constraint.name == "ck_pharmacy_dispense_items_fulfillment_limit"
        for constraint in PharmacyDispenseItem.__table__.constraints
    )

    assert "pharmacy_dispense_id" in Invoice.__table__.c
    assert "invoice_id" in PharmacyDispense.__table__.c
    assert any(
        constraint.name == "uq_invoices_pharmacy_dispense"
        for constraint in Invoice.__table__.constraints
    )


def test_prescription_has_version_and_no_substitution_policy():
    assert "version" in Prescription.__table__.c
    assert "no_substitution" in PrescriptionItem.__table__.c
    assert "no_substitution_reason" in PrescriptionItem.__table__.c
