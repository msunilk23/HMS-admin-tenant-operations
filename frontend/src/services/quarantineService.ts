import apiClient from './apiClient'

export type QuarantineReason = 'EXPIRED' | 'DAMAGED' | 'INVESTIGATION'

export interface QuarantineBatch {
  id: string
  pharmacy_location_id: string
  medicine_id: string
  batch_number: string
  expiry_date?: string
  available_quantity: string
  status: string
}

export interface StockQuarantine {
  id: string
  tenant_id: string
  facility_id: string
  pharmacy_location_id: string
  inventory_batch_id: string
  status: 'QUARANTINED' | 'RELEASED' | 'DISPOSED'
  reference_key: string
  reason: QuarantineReason
  total_quantity_quarantined: string
  remaining_quantity: string
  notes?: string
  quarantined_by?: string
  quarantined_at: string
  approved_by?: string
  approved_at?: string
  approved_action?: string
  release_reason?: string
  released_by?: string
  released_at?: string
  disposal_reason?: string
  disposal_method?: string
  disposal_date?: string
  witnessed_by?: string
  disposed_by?: string
  disposed_at?: string
  quarantine_ledger_transaction_id?: string
  release_ledger_transaction_id?: string
  disposal_ledger_transaction_id?: string
  created_at: string
  updated_at: string
}

export interface CreateQuarantineInput {
  inventory_batch_id: string
  quantity: number
  reason: QuarantineReason
  idempotency_key: string
  notes?: string
}

export interface DisposeQuarantineInput {
  disposal_reason: string
  disposal_method: string
  disposal_date: string
  witnessed_by: string
}

export const quarantineService = {
  batches: (pharmacyLocationId?: string) => apiClient.get<QuarantineBatch[]>('/pharmacy/quarantines/batches', { params: { pharmacy_location_id: pharmacyLocationId || undefined } }).then((response) => response.data),
  list: (params?: { status?: string; pharmacy_location_id?: string }) => apiClient.get<{ items: StockQuarantine[]; total: number }>('/pharmacy/quarantines', { params }).then((response) => response.data),
  create: (payload: CreateQuarantineInput) => apiClient.post<StockQuarantine>('/pharmacy/quarantines', payload).then((response) => response.data),
  release: (id: string, releaseReason: string) => apiClient.post<StockQuarantine>(`/pharmacy/quarantines/${id}/release`, { release_reason: releaseReason }).then((response) => response.data),
  dispose: (id: string, payload: DisposeQuarantineInput) => apiClient.post<StockQuarantine>(`/pharmacy/quarantines/${id}/dispose`, payload).then((response) => response.data),
}