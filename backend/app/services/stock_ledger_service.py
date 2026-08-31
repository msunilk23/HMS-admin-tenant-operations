from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.stock_transaction import StockTransaction


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def assert_inventory_batch_not_frozen(
    batch: InventoryBatch,
    *,
    allowed_count_id: Optional[uuid.UUID] = None,
) -> None:
    if batch.frozen_by_count_id is not None and batch.frozen_by_count_id != allowed_count_id:
        raise ValueError("Inventory batch is frozen by an active stock count")


async def create_stock_ledger_transaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    pharmacy_location_id: uuid.UUID,
    medicine_id: Optional[uuid.UUID],
    inventory_batch_id: Optional[uuid.UUID],
    transaction_type: str,
    quantity: Any,
    reference_type: str,
    reference_id: Any,
    correlation_reference: str | None = None,
    reason: str,
    user_id: Optional[uuid.UUID] = None,
    affects_available_balance: bool = True,
    allowed_count_id: Optional[uuid.UUID] = None,
) -> StockTransaction:
    """Append a signed stock ledger row and keep the batch cache consistent."""
    if inventory_batch_id is not None:
        batch = await session.scalar(
            select(InventoryBatch).where(
                InventoryBatch.id == inventory_batch_id,
                InventoryBatch.tenant_id == tenant_id,
                InventoryBatch.facility_id == facility_id,
            ).with_for_update()
        )
        if batch is None:
            raise ValueError(f"Inventory batch {inventory_batch_id} not found")
        assert_inventory_batch_not_frozen(batch, allowed_count_id=allowed_count_id)
        if medicine_id is None:
            medicine_id = batch.medicine_id
        pharmacy_location_id = batch.pharmacy_location_id
    elif medicine_id is None:
        raise ValueError("Either medicine_id or inventory_batch_id must be provided")

    existing = await session.scalar(
        select(StockTransaction).where(
            StockTransaction.reference_type == reference_type,
            StockTransaction.reference_id == reference_id,
            StockTransaction.transaction_type == transaction_type,
        )
    )
    if existing is not None:
        return existing

    if inventory_batch_id is not None:
        prior_balance = _to_decimal((await session.scalar(
            select(InventoryBatch.available_quantity)
            .where(InventoryBatch.id == inventory_batch_id)
            .with_for_update()
        )) or Decimal("0"))
    else:
        prior_balance = Decimal("0")

    adjustment = _to_decimal(quantity)
    new_balance = prior_balance + adjustment if affects_available_balance else prior_balance
    if inventory_batch_id is not None and affects_available_balance:
        batch = await session.scalar(
            select(InventoryBatch).where(InventoryBatch.id == inventory_batch_id).with_for_update()
        )
        if batch is not None:
            if new_balance < Decimal("0"):
                raise ValueError("Stock ledger would create a negative quantity for the batch")
            batch.available_quantity = new_balance
            batch.updated_by = user_id

    transaction = StockTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
        medicine_id=medicine_id,
        inventory_batch_id=inventory_batch_id,
        transaction_type=transaction_type,
        quantity=adjustment,
        previous_balance=prior_balance,
        new_balance=new_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        correlation_reference=correlation_reference,
        reason=reason,
        performed_by=user_id,
    )
    session.add(transaction)
    await session.flush()
    return transaction
