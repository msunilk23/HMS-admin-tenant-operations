import apiClient from './apiClient'
import type { PharmacyQueueItem } from '@/types/common'

export interface PharmacyLineItem {
  name: string
  mfr: string
  batch: string
  expiry: string
  qty: number
  mrp: number
  gst_pct: number
  dis_pct: number
  total: number
}

export interface PharmacyBillCreate {
  line_items: PharmacyLineItem[]
  discount: number
  payment_method: 'cash' | 'online'
}

export const pharmacyService = {
  list: (params?: { status?: string }) =>
    apiClient.get<PharmacyQueueItem[]>('/pharmacy', { params }).then(r => r.data),

  updateStatus: (id: string, status: string, notes?: string) =>
    apiClient.patch<PharmacyQueueItem>(`/pharmacy/${id}/status`, { status, notes }).then(r => r.data),

  bill: (pqId: string, data: PharmacyBillCreate) =>
    apiClient.post<{ id: string; status: string; razorpay_order_id?: string; total: number }>(`/pharmacy/${pqId}/bill`, data).then(r => r.data),
}
