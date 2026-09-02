import apiClient from './apiClient'

export type RetailClassification = 'OTC' | 'EXTERNAL_PRESCRIPTION'

export interface RetailMedicine {
  id: string
  code: string
  name: string
  strength?: string
  requires_prescription: boolean
  is_controlled_drug: boolean
  available_quantity: string
  unit_price: string
  gst_rate: string
}

export interface RetailSaleItemInput {
  medicine_product_id: string
  quantity: number
  prescribed_quantity?: number
  duration_days?: number
}

export interface RetailSaleInput {
  classification: RetailClassification
  pharmacy_location_id: string
  patient_id?: string
  patient_name?: string
  patient_age?: number
  patient_gender?: string
  patient_mobile?: string
  patient_address?: string
  government_id_type?: string
  government_id_last_four?: string
  prescriber_name?: string
  prescriber_registration_number?: string
  prescription_date?: string
  issuing_facility?: string
  prescription_reference?: string
  prescription_attachment_reference?: string
  original_prescription_inspected: boolean
  items: RetailSaleItemInput[]
}

export interface RetailSale {
  id: string
  pharmacy_location_id: string
  classification: RetailClassification
  status: string
  controlled_sale: boolean
  customer_reference: string
  subtotal: string
  tax: string
  discount: string
  total: string
  payment_method?: string
  payment_status: string
  payment_reference?: string
  receipt_number?: string
}

export interface PharmacyLocation {
  id: string
  location_name: string
  location_code: string
}

export const pharmacyRetailService = {
  locations: () => apiClient.get<PharmacyLocation[]>('/pharmacy/inventory/locations').then(response => response.data),
  search: (pharmacyLocationId: string, query: string) => apiClient.get<RetailMedicine[]>('/pharmacy/retail/medicines', { params: { pharmacy_location_id: pharmacyLocationId, q: query } }).then(response => response.data),
  create: (payload: RetailSaleInput, idempotencyKey: string) => apiClient.post<RetailSale>('/pharmacy/retail/sales', payload, { headers: { 'Idempotency-Key': idempotencyKey } }).then(response => response.data),
  get: (saleId: string) => apiClient.get<RetailSale>(`/pharmacy/retail/sales/${saleId}`).then(response => response.data),
  verify: (saleId: string) => apiClient.post<RetailSale>(`/pharmacy/retail/sales/${saleId}/verify`).then(response => response.data),
  dispense: (saleId: string, paymentMethod: 'CASH' | 'CARD' | 'UPI', paymentReference?: string) => apiClient.post<RetailSale>(`/pharmacy/retail/sales/${saleId}/dispense`, { payment_method: paymentMethod, payment_reference: paymentReference || undefined }).then(response => response.data),
}