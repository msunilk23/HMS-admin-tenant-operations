import apiClient from './apiClient'
import type { PharmacyQueueItem } from '@/types/common'

export interface PharmacyLineItem {
  dispense_item_id?: string
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

export interface PharmacyDispense {
  id: string
  prescription_id: string
  pharmacy_queue_id?: string
  facility_id: string
  pharmacy_location_id: string
  prescription_version: number
  visit_id: string
  patient_id: string
  status: string
  billing_status: string
}

export interface PharmacyDispenseItem {
  id: string
  prescription_item_id: string
  prescribed_medicine_product_id?: string
  prescribed_name_snapshot: string
  prescribed_quantity: string
  internal_requested_quantity: string
  internal_confirmed_quantity: string
  outside_purchase_quantity: string
  no_substitution_applied: boolean
  status: string
}

export const pharmacyService = {
  list: (params?: { status?: string }) =>
    apiClient.get<PharmacyQueueItem[]>('/pharmacy', { params }).then(r => r.data),

  updateStatus: (id: string, status: string, notes?: string) =>
    apiClient.patch<PharmacyQueueItem>(`/pharmacy/${id}/status`, { status, notes }).then(r => r.data),

  bill: (pqId: string, data: PharmacyBillCreate) =>
    apiClient.post<{ id: string; status: string; razorpay_order_id?: string; total: number }>(`/pharmacy/${pqId}/bill`, data).then(r => r.data),

  startDispense: (queueId: string, data: { facility_id: string; pharmacy_location_id: string }) =>
    apiClient.post<PharmacyQueueItem>(`/pharmacy/${queueId}/start`, data).then(r => r.data),

  validateDispense: (dispenseId: string, facilityId: string) =>
    apiClient.post<PharmacyDispense>(`/pharmacy/dispenses/${dispenseId}/validate`, null, { params: { facility_id: facilityId } }).then(r => r.data),

  proposeAllocation: (dispenseId: string, facilityId: string, requested_quantities?: Record<string, string>) =>
    apiClient.post<PharmacyDispense>(`/pharmacy/dispenses/${dispenseId}/allocation-proposal`, { requested_quantities }, { params: { facility_id: facilityId } }).then(r => r.data),

  reserve: (dispenseId: string, facilityId: string) =>
    apiClient.post(`/pharmacy/dispenses/${dispenseId}/reserve`, null, { params: { facility_id: facilityId } }).then(r => r.data),

  fulfillInternally: (dispenseId: string, facilityId: string, partial: boolean) =>
    apiClient.post<PharmacyDispense>(`/pharmacy/dispenses/${dispenseId}/fulfill-internally`, null, { params: { facility_id: facilityId, partial } }).then(r => r.data),

  outsidePurchase: (dispenseId: string, facilityId: string, items: { dispense_item_id: string; quantity: string; reason: string }[]) =>
    apiClient.post<PharmacyDispense>(`/pharmacy/dispenses/${dispenseId}/outside-purchase`, { items }, { params: { facility_id: facilityId } }).then(r => r.data),

  confirmDispense: (dispenseId: string, facilityId: string, billing_authorized: boolean) =>
    apiClient.post<PharmacyDispense>(`/pharmacy/dispenses/${dispenseId}/confirm`, { billing_authorized }, { params: { facility_id: facilityId } }).then(r => r.data),

  listDispenseItems: (dispenseId: string, facilityId: string) =>
    apiClient.get<PharmacyDispenseItem[]>(`/pharmacy/dispenses/${dispenseId}/items`, { params: { facility_id: facilityId } }).then(r => r.data),

  cancelDispense: (dispenseId: string, facilityId: string, reason: string) =>
    apiClient.post<PharmacyDispense>(`/pharmacy/dispenses/${dispenseId}/cancel`, { reason }, { params: { facility_id: facilityId } }).then(r => r.data),
}
