from __future__ import annotations

from decimal import Decimal
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.stock_transaction import StockTransaction


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


async def create_inventory_from_grn_item(
    session: AsyncSession,
    *,
    tenant_id,
    facility_id,
    pharmacy_location_id,
    medicine_id,
    supplier_id,
    goods_receipt_id,
    goods_receipt_item_id,
    batch_number: str,
    received_quantity: Any,
    free_quantity: Any = 0,
    purchase_rate: Any,
    mrp: Any | None = None,
    manufacturing_date=None,
    expiry_date=None,
    created_by=None,
    status: str = "ACTIVE",
    commit: bool = True,
) -> InventoryBatch:
    """Create a batch and ledger entry from a posted GRN item exactly once."""
    existing = await session.scalar(
        select(InventoryBatch).where(InventoryBatch.goods_receipt_item_id == goods_receipt_item_id)
    )
    if existing is not None:
        return existing

    stock_received = _to_decimal(received_quantity) + _to_decimal(free_quantity)
    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
        medicine_id=medicine_id,
        batch_number=batch_number,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        purchase_rate=_to_decimal(purchase_rate),
        mrp=_to_decimal(mrp) if mrp is not None else None,
        received_quantity=_to_decimal(received_quantity),
        available_quantity=stock_received,
        reserved_quantity=Decimal("0"),
        supplier_id=supplier_id,
        goods_receipt_id=goods_receipt_id,
        goods_receipt_item_id=goods_receipt_item_id,
        status=status,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(batch)
    await session.flush()

    prior_balance = Decimal("0")
    ledger_entry = StockTransaction(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
        medicine_id=medicine_id,
        inventory_batch_id=batch.id,
        transaction_type="PURCHASE_RECEIPT",
        quantity=stock_received,
        previous_balance=prior_balance,
        new_balance=prior_balance + stock_received,
        reference_type="goods_receipt_item",
        reference_id=goods_receipt_item_id,
        reason="GRN receipt",
        performed_by=created_by,
    )
    session.add(ledger_entry)
    if commit:
        await session.commit()
    return batch


async def sync_inventory_batch_balance(
    session: AsyncSession,
    inventory_batch_id,
    *,
    tenant_id=None,
    facility_id=None,
) -> InventoryBatch:
    """Recompute the cached batch balance from the stock ledger."""
    return await _sync_inventory_batch_balance(
        session,
        inventory_batch_id,
        tenant_id=tenant_id,
        facility_id=facility_id,
    )


async def _sync_inventory_batch_balance(
    session: AsyncSession,
    inventory_batch_id,
    *,
    tenant_id=None,
    facility_id=None,
) -> InventoryBatch:
    filters = [InventoryBatch.id == inventory_batch_id]
    if tenant_id is not None:
        filters.append(InventoryBatch.tenant_id == tenant_id)
    if facility_id is not None:
        filters.append(InventoryBatch.facility_id == facility_id)

    batch = await session.scalar(select(InventoryBatch).where(*filters))
    if batch is None:
        raise ValueError("Inventory batch not found")

    result = await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), Decimal("0"))).where(
            StockTransaction.inventory_batch_id == inventory_batch_id,
            StockTransaction.tenant_id == batch.tenant_id,
            StockTransaction.facility_id == batch.facility_id,
        )
    )
    batch.available_quantity = _to_decimal(result or 0)
    await session.commit()
    return batch


async def reconcile_inventory_batch(
    session: AsyncSession,
    inventory_batch_id,
    *,
    tenant_id=None,
    facility_id=None,
) -> dict[str, Any]:
    """Compare the cached batch balance with its immutable ledger balance."""
    filters = [InventoryBatch.id == inventory_batch_id]
    if tenant_id is not None:
        filters.append(InventoryBatch.tenant_id == tenant_id)
    if facility_id is not None:
        filters.append(InventoryBatch.facility_id == facility_id)

    batch = await session.scalar(select(InventoryBatch).where(*filters))
    if batch is None:
        raise ValueError("Inventory batch not found")

    ledger_balance = await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), Decimal("0"))).where(
            StockTransaction.inventory_batch_id == inventory_batch_id,
            StockTransaction.tenant_id == batch.tenant_id,
            StockTransaction.facility_id == batch.facility_id,
        )
    )
    cached_balance = _to_decimal(batch.available_quantity or 0)
    ledger_balance = _to_decimal(ledger_balance or 0)
    return {
        "inventory_batch_id": str(batch.id),
        "cached_balance": cached_balance,
        "ledger_balance": ledger_balance,
        "difference": cached_balance - ledger_balance,
        "is_consistent": cached_balance == ledger_balance,
    }


async def record_stock_adjustment(
    session: AsyncSession,
    *,
    tenant_id,
    facility_id,
    inventory_batch_id,
    quantity: Any,
    reference_id,
    reason: str,
    performed_by=None,
    as_of_date: date | None = None,
    commit: bool = True,
) -> StockTransaction:
    """Append one idempotent signed adjustment and update the batch cache."""
    existing = await session.scalar(
        select(StockTransaction).where(
            StockTransaction.reference_type == "stock_adjustment",
            StockTransaction.reference_id == reference_id,
            StockTransaction.transaction_type == "STOCK_ADJUSTMENT",
        )
    )
    if existing is not None:
        return existing

    batch = await session.scalar(
        select(InventoryBatch).where(
            InventoryBatch.id == inventory_batch_id,
            InventoryBatch.tenant_id == tenant_id,
            InventoryBatch.facility_id == facility_id,
        )
    )
    if batch is None:
        raise ValueError("Inventory batch not found")
    if batch.status != "ACTIVE":
        raise ValueError("Inventory batch is not active")
    if batch.expiry_date is not None and batch.expiry_date < (as_of_date or date.today()):
        raise ValueError("Cannot adjust expired inventory batch")

    adjustment = _to_decimal(quantity)
    if adjustment == 0:
        raise ValueError("Adjustment quantity cannot be zero")
    previous_balance = _to_decimal(batch.available_quantity or 0)
    new_balance = previous_balance + adjustment
    if new_balance < 0:
        raise ValueError("Adjustment exceeds available stock")

    transaction = StockTransaction(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=batch.pharmacy_location_id,
        medicine_id=batch.medicine_id,
        inventory_batch_id=batch.id,
        transaction_type="STOCK_ADJUSTMENT",
        quantity=adjustment,
        previous_balance=previous_balance,
        new_balance=new_balance,
        reference_type="stock_adjustment",
        reference_id=reference_id,
        reason=reason,
        performed_by=performed_by,
    )
    batch.available_quantity = new_balance
    batch.updated_by = performed_by
    session.add(transaction)
    await session.flush()
    if commit:
        await session.commit()
    return transaction


async def get_location_medicine_balance(
    session: AsyncSession,
    *,
    tenant_id=None,
    facility_id=None,
    pharmacy_location_id,
    medicine_id,
) -> dict[str, Decimal | str]:
    filters = [
        StockTransaction.pharmacy_location_id == pharmacy_location_id,
        StockTransaction.medicine_id == medicine_id,
    ]
    if tenant_id is not None:
        filters.append(StockTransaction.tenant_id == tenant_id)
    if facility_id is not None:
        filters.append(StockTransaction.facility_id == facility_id)

    ledger_result = await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), Decimal("0"))).where(*filters)
    )

    batch_filters = [
        InventoryBatch.pharmacy_location_id == pharmacy_location_id,
        InventoryBatch.medicine_id == medicine_id,
        InventoryBatch.status == "ACTIVE",
    ]
    if tenant_id is not None:
        batch_filters.append(InventoryBatch.tenant_id == tenant_id)
    if facility_id is not None:
        batch_filters.append(InventoryBatch.facility_id == facility_id)

    batch_total = await session.scalar(
        select(func.coalesce(func.sum(InventoryBatch.available_quantity), Decimal("0"))).where(*batch_filters)
    )
    has_ledger = await session.scalar(
        select(func.count(StockTransaction.id)).where(*filters)
    )

    on_hand = _to_decimal(ledger_result or 0) if has_ledger and int(has_ledger) > 0 else _to_decimal(batch_total or 0)
    reserved_result = await session.scalar(
        select(func.coalesce(func.sum(InventoryBatch.reserved_quantity), Decimal("0"))).where(*batch_filters)
    )
    reserved = _to_decimal(reserved_result or 0)
    balance = on_hand - reserved
    return {
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "facility_id": str(facility_id) if facility_id is not None else None,
        "pharmacy_location_id": str(pharmacy_location_id),
        "medicine_id": str(medicine_id),
        "on_hand": on_hand,
        "reserved": reserved,
        "available": balance,
    }


async def get_fefo_batches_for_medicine(
    session: AsyncSession,
    *,
    tenant_id,
    facility_id,
    pharmacy_location_id,
    medicine_id,
    as_of_date: date | None = None,
    limit: int | None = None,
) -> list[InventoryBatch]:
    """Return stock batches for a medicine sorted by earliest expiry and active status."""
    reference_date = as_of_date or date.today()
    stmt = (
        select(InventoryBatch)
        .where(
            InventoryBatch.tenant_id == tenant_id,
            InventoryBatch.facility_id == facility_id,
            InventoryBatch.pharmacy_location_id == pharmacy_location_id,
            InventoryBatch.medicine_id == medicine_id,
            InventoryBatch.status == "ACTIVE",
            InventoryBatch.available_quantity > Decimal("0"),
        )
        .order_by(InventoryBatch.expiry_date.asc().nulls_last())
    )

    if reference_date is not None:
        stmt = stmt.where(InventoryBatch.expiry_date.is_(None) | (InventoryBatch.expiry_date >= reference_date))

    if limit is not None:
        stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())
