import apiClient from './apiClient'

export interface GoodsReceiptItem {
  id: string
  goods_receipt_id: string
  purchase_order_item_id: string
  medicine_product_id: string
  batch_number: string
  manufacturing_date?: string
  expiry_date: string
  received_quantity: string
  free_quantity: string
  purchase_rate: string
  mrp?: string
  gst_percent: string
  taxable_amount: string
  tax_amount: string
  line_total: string
  receiving_notes?: string
}

export interface GoodsReceipt {
  id: string
  grn_number: string
  purchase_order_id: string
  supplier_id: string
  facility_id?: string
  pharmacy_location_id?: string
  supplier_invoice_number?: string
  supplier_invoice_date?: string
  received_date: string
  status: string
  subtotal: string
  tax_amount: string
  total_amount: string
  notes?: string
  items: GoodsReceiptItem[]
}

export const goodsReceiptService = {
  locations: () => apiClient.get<{ id: string; facility_id: string; location_code: string; location_name: string; active: boolean }[]>('/pharmacy/inventory/locations').then(r => r.data),
  list: (params?: { status?: string; purchase_order_id?: string }) => apiClient.get<GoodsReceipt[]>('/pharmacy/grn', { params }).then(r => r.data),
  get: (id: string) => apiClient.get<GoodsReceipt>(`/pharmacy/grn/${id}`).then(r => r.data),
  create: (data: { purchase_order_id: string; facility_id: string; pharmacy_location_id: string; received_date?: string; supplier_invoice_number?: string; supplier_invoice_date?: string; notes?: string }) => apiClient.post<GoodsReceipt>('/pharmacy/grn', data).then(r => r.data),
  receiveItem: (id: string, data: { purchase_order_item_id: string; received_quantity: number; free_quantity?: number; batch_number: string; manufacturing_date?: string; expiry_date: string; receiving_notes?: string }) => apiClient.post<GoodsReceiptItem>(`/pharmacy/grn/${id}/items`, data).then(r => r.data),
  finalize: (id: string) => apiClient.post<GoodsReceipt>(`/pharmacy/grn/${id}/finalize`).then(r => r.data),
  reject: (id: string, reason: string) => apiClient.post<GoodsReceipt>(`/pharmacy/grn/${id}/reject`, null, { params: { reason } }).then(r => r.data),
  cancel: (id: string, reason: string) => apiClient.post<GoodsReceipt>(`/pharmacy/grn/${id}/cancel`, null, { params: { reason } }).then(r => r.data),
}
