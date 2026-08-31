import apiClient from './apiClient'

export interface PurchaseOrderItem {
  id: string
  purchase_order_id: string
  medicine_product_id: string
  ordered_quantity: string
  free_quantity: string
  unit_of_measure: string
  unit_purchase_price: string
  mrp?: string
  discount_percent: string
  gst_percent: string
  taxable_amount: string
  tax_amount: string
  line_total: string
  received_quantity: string
}

export interface PurchaseOrder {
  id: string
  po_number: string
  supplier_id: string
  po_date: string
  required_by_date?: string
  status: string
  subtotal: string
  discount_amount: string
  tax_amount: string
  total_amount: string
  notes?: string
  approved_at?: string
  sent_at?: string
  items: PurchaseOrderItem[]
}

export interface PurchaseOrderItemCreate {
  medicine_product_id: string
  ordered_quantity: number
  free_quantity?: number
  unit_of_measure: string
  unit_purchase_price: number
  mrp?: number
  discount_percent?: number
  gst_percent?: number
}

export interface PurchaseOrderCreate {
  supplier_id: string
  po_date?: string
  required_by_date?: string
  notes?: string
  items: PurchaseOrderItemCreate[]
}

export const purchaseOrderService = {
  list: (params?: { status?: string; supplier_id?: string }) => apiClient.get<PurchaseOrder[]>('/pharmacy/purchase-orders', { params }).then(r => r.data),
  get: (id: string) => apiClient.get<PurchaseOrder>(`/pharmacy/purchase-orders/${id}`).then(r => r.data),
  create: (data: PurchaseOrderCreate) => apiClient.post<PurchaseOrder>('/pharmacy/purchase-orders', data).then(r => r.data),
  update: (id: string, data: Partial<PurchaseOrderCreate>) => apiClient.put<PurchaseOrder>(`/pharmacy/purchase-orders/${id}`, data).then(r => r.data),
  submit: (id: string) => apiClient.post<PurchaseOrder>(`/pharmacy/purchase-orders/${id}/submit`).then(r => r.data),
  approve: (id: string) => apiClient.post<PurchaseOrder>(`/pharmacy/purchase-orders/${id}/approve`).then(r => r.data),
  send: (id: string) => apiClient.post<PurchaseOrder>(`/pharmacy/purchase-orders/${id}/send`).then(r => r.data),
  cancel: (id: string, reason: string) => apiClient.post<PurchaseOrder>(`/pharmacy/purchase-orders/${id}/cancel`, null, { params: { reason } }).then(r => r.data),
}
