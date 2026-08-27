from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio

from app.api.v1.pharmacy import create_goods_receipt, finalize_goods_receipt, receive_goods_receipt_item
from app.schemas.goods_receipt import GoodsReceiptCreate, GoodsReceiptItemCreate

from test_goods_receipt_workflow_phase26 import grn_context as _grn_context
from test_goods_receipt_workflow_phase26 import sent_order

@pytest_asyncio.fixture(name="grn_context")
async def _local_grn_context():
    async for value in _grn_context.__pytest_wrapped__.obj():
        yield value


@pytest.mark.asyncio
async def test_batch_and_expiry_are_required_by_schema():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GoodsReceiptItemCreate(purchase_order_item_id="00000000-0000-0000-0000-000000000001", received_quantity=Decimal("1"))


@pytest.mark.asyncio
async def test_expiry_and_manufacturing_dates_are_validated(grn_context):
    session, supplier, product = grn_context
    order = await sent_order(session, supplier, product)
    receipt = await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id, received_date=date.today()), session, {"sub": "00000000-0000-0000-0000-000000000001", "role": "store_manager"})
    po_item = order.items[0]
    with pytest.raises(Exception) as expired:
        await receive_goods_receipt_item(receipt.id, GoodsReceiptItemCreate(purchase_order_item_id=po_item.id, received_quantity=Decimal("1"), batch_number="B-EXPIRED", expiry_date=date.today()), session, {"sub": "00000000-0000-0000-0000-000000000001", "role": "store_manager"})
    assert "Expiry date" in str(expired.value)
    with pytest.raises(Exception) as manufacture:
        await receive_goods_receipt_item(receipt.id, GoodsReceiptItemCreate(purchase_order_item_id=po_item.id, received_quantity=Decimal("1"), batch_number="B-MANUFACTURE", manufacturing_date=date.today() + timedelta(days=1), expiry_date=date.today() + timedelta(days=30)), session, {"sub": "00000000-0000-0000-0000-000000000001", "role": "store_manager"})
    assert "Manufacturing date" in str(manufacture.value)


@pytest.mark.asyncio
async def test_duplicate_batch_and_expiry_are_rejected(grn_context):
    session, supplier, product = grn_context
    order = await sent_order(session, supplier, product)
    user = {"sub": "00000000-0000-0000-0000-000000000001", "role": "store_manager"}
    first = await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id), session, user)
    po_item = order.items[0]
    payload = GoodsReceiptItemCreate(purchase_order_item_id=po_item.id, received_quantity=Decimal("1"), batch_number="B-DUP", expiry_date=date.today() + timedelta(days=30))
    await receive_goods_receipt_item(first.id, payload, session, user)
    await finalize_goods_receipt(first.id, session, user)
    second = await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id), session, user)
    with pytest.raises(Exception) as duplicate:
        await receive_goods_receipt_item(second.id, payload.model_copy(update={"received_quantity": Decimal("1")}), session, user)
    assert "batch and expiry already exists" in str(duplicate.value)
