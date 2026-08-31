import { beforeEach, describe, expect, it, vi } from 'vitest'
import apiClient from './apiClient'
import { goodsReceiptService } from './goodsReceiptService'
import { purchaseOrderService } from './purchaseOrderService'

vi.mock('./apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

describe('procurement service contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiClient.get).mockResolvedValue({ data: [] })
    vi.mocked(apiClient.post).mockResolvedValue({ data: {} })
    vi.mocked(apiClient.put).mockResolvedValue({ data: {} })
  })

  it('lists and creates purchase orders through the pharmacy namespace', async () => {
    await purchaseOrderService.list({ status: 'DRAFT' })
    expect(apiClient.get).toHaveBeenCalledWith('/pharmacy/purchase-orders', { params: { status: 'DRAFT' } })

    const payload = {
      supplier_id: 'supplier-1',
      items: [{
        medicine_product_id: 'product-1',
        ordered_quantity: 10,
        unit_of_measure: 'tablet',
        unit_purchase_price: 12.5,
      }],
    }
    await purchaseOrderService.create(payload)
    expect(apiClient.post).toHaveBeenCalledWith('/pharmacy/purchase-orders', payload)
  })

  it('sends lifecycle actions to dedicated purchase-order endpoints', async () => {
    await purchaseOrderService.submit('po-1')
    await purchaseOrderService.approve('po-1')
    await purchaseOrderService.send('po-1')
    await purchaseOrderService.cancel('po-1', 'Supplier unavailable')
    expect(apiClient.post).toHaveBeenNthCalledWith(1, '/pharmacy/purchase-orders/po-1/submit')
    expect(apiClient.post).toHaveBeenNthCalledWith(2, '/pharmacy/purchase-orders/po-1/approve')
    expect(apiClient.post).toHaveBeenNthCalledWith(3, '/pharmacy/purchase-orders/po-1/send')
    expect(apiClient.post).toHaveBeenNthCalledWith(4, '/pharmacy/purchase-orders/po-1/cancel', null, { params: { reason: 'Supplier unavailable' } })
  })

  it('captures GRN batches and calls receiving lifecycle endpoints', async () => {
    await goodsReceiptService.list({ status: 'DRAFT' })
    expect(apiClient.get).toHaveBeenCalledWith('/pharmacy/grn', { params: { status: 'DRAFT' } })

    const payload = {
      purchase_order_item_id: 'po-item-1',
      received_quantity: 10,
      batch_number: 'B-2026-01',
      expiry_date: '2027-01-31',
    }
    await goodsReceiptService.receiveItem('grn-1', payload)
    expect(apiClient.post).toHaveBeenCalledWith('/pharmacy/grn/grn-1/items', payload)

    await goodsReceiptService.finalize('grn-1')
    expect(apiClient.post).toHaveBeenCalledWith('/pharmacy/grn/grn-1/finalize')
  })
})
