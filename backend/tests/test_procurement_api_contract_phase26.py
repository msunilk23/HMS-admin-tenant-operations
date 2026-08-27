from decimal import Decimal

from app.api.v1 import pharmacy
from app.api.v1.pharmacy import _GRN_TRANSITIONS, _PO_TRANSITIONS, _calculate_grn_totals, _calculate_po_items
from app.models.tenant.goods_receipt import GoodsReceiptItem
from app.schemas.purchase_order import PurchaseOrderItemCreate


def route_dependencies(path: str, method: str):
    return [
        route
        for route in pharmacy.router.routes
        if route.path == path and method in route.methods
    ]


def test_procurement_routes_are_registered():
    assert route_dependencies('/purchase-orders', 'POST')
    assert route_dependencies('/purchase-orders/{po_id}/approve', 'POST')
    assert route_dependencies('/purchase-orders/{po_id}/cancel', 'POST')
    assert route_dependencies('/grn', 'POST')
    assert route_dependencies('/grn/{grn_id}/items', 'POST')
    assert route_dependencies('/grn/{grn_id}/finalize', 'POST')


def test_procurement_status_machines_have_no_arbitrary_transition():
    assert _PO_TRANSITIONS['DRAFT'] == {'SUBMITTED', 'CANCELLED'}
    assert _PO_TRANSITIONS['APPROVED'] == {'SENT', 'CANCELLED'}
    assert _GRN_TRANSITIONS['DRAFT'] == {'PARTIALLY_RECEIVED', 'FULLY_RECEIVED', 'REJECTED', 'CANCELLED'}
    assert not _GRN_TRANSITIONS['FULLY_RECEIVED']


def test_purchase_order_calculation_is_decimal_safe():
    items, subtotal, discount, tax, total = _calculate_po_items([
        PurchaseOrderItemCreate(
            medicine_product_id='00000000-0000-0000-0000-000000000001',
            ordered_quantity=Decimal('3'),
            unit_of_measure='tablet',
            unit_purchase_price=Decimal('10.00'),
            discount_percent=Decimal('10'),
            gst_percent=Decimal('18'),
        )
    ])
    assert subtotal == Decimal('30.00')
    assert discount == Decimal('3.00')
    assert tax == Decimal('4.86')
    assert total == Decimal('31.86')
    assert items[0]['taxable_amount'] == Decimal('27.00')
    assert items[0]['line_total'] == Decimal('31.86')


def test_grn_totals_use_taxable_and_tax_amounts():
    first = GoodsReceiptItem(
        taxable_amount=Decimal('100.00'), tax_amount=Decimal('18.00'), received_quantity=Decimal('10'),
        purchase_rate=Decimal('10'), free_quantity=Decimal('0'), gst_percent=Decimal('18'),
    )
    second = GoodsReceiptItem(
        taxable_amount=Decimal('50.00'), tax_amount=Decimal('6.00'), received_quantity=Decimal('5'),
        purchase_rate=Decimal('10'), free_quantity=Decimal('0'), gst_percent=Decimal('12'),
    )
    assert _calculate_grn_totals([first, second]) == (Decimal('150.00'), Decimal('24.00'), Decimal('174.00'))
