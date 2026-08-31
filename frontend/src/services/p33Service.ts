import apiClient from './apiClient'

export type CountType = 'FULL' | 'PARTIAL' | 'SAMPLE'
export type CountStatus = 'CREATED' | 'IN_PROGRESS' | 'SUBMITTED' | 'RECOUNT_REQUIRED' | 'RECOUNT_IN_PROGRESS' | 'RESUBMITTED' | 'APPROVED' | 'APPLIED' | 'CANCELLED'
export interface Location { id: string; location_name: string; location_code: string; active: boolean }
export interface Batch { id: string; pharmacy_location_id: string; medicine_id: string; batch_number: string; available_quantity: string; reserved_quantity: string; status: string }
export interface CountDetail { id: string; count_id: string; inventory_batch_id: string; medicine_id: string; batch_number: string; system_quantity: string; available_quantity: string; reserved_quantity: string; unit_cost?: string; physical_quantity?: string; variance_quantity?: string; variance_percent?: string; variance_value?: string; classifications: string[]; variance_reason?: string; is_unexpected: boolean; evidence?: string; counted_by?: string; version: number; adjustment_ledger_id?: string }
export interface RecountDetail { id: string; count_detail_id: string; physical_quantity?: string; variance_quantity?: string; variance_reason?: string; counted_by?: string; version: number }
export interface Recount { id: string; attempt_number: number; status: string; reason: string; assigned_to: string; requested_by: string; details: RecountDetail[] }
export interface HistoryEntry { action: string; resource_type: string; resource_id: string; user_id?: string; timestamp: string; reason?: string; old_value?: unknown; new_value?: unknown }
export interface StockCount { id: string; pharmacy_location_id: string; status: CountStatus; count_type: CountType; reference_key: string; selected_batch_ids: string[]; notes?: string; quantity_tolerance_percent: string; expected_total_quantity: string; physical_total_quantity: string; variance_quantity: string; total_items_counted: number; total_variance_items: number; recount_count: number; initiated_by: string; completed_by?: string; approved_by?: string; created_at: string; details?: CountDetail[]; recounts?: Recount[]; history?: HistoryEntry[] }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

const config = (key: string) => ({ headers: { 'Idempotency-Key': key } })
const action = (path: string, key: string, body: object = {}) => apiClient.post<StockCount>(path, body, config(key)).then(response => response.data)

export const p33Service = {
  locations: () => apiClient.get<Location[]>('/pharmacy/inventory/locations').then(response => response.data),
  batches: (locationId: string, dispensableOnly = true) => apiClient.get<Batch[]>('/pharmacy/inventory/batches', { params: { pharmacy_location_id: locationId, dispensable_only: dispensableOnly } }).then(response => response.data),
  counts: (params: { status?: string; count_type?: string; page?: number }) => apiClient.get<Page<StockCount>>('/pharmacy/inventory-counts', { params }).then(response => response.data),
  count: (id: string) => apiClient.get<StockCount>(`/pharmacy/inventory-counts/${id}`).then(response => response.data),
  create: (payload: { pharmacy_location_id: string; count_type: CountType; selected_batch_ids: string[]; notes?: string }, key: string) => apiClient.post<StockCount>('/pharmacy/inventory-counts', payload, config(key)).then(response => response.data),
  start: (id: string, key: string) => action(`/pharmacy/inventory-counts/${id}/start`, key),
  record: (countId: string, detailId: string, payload: { physical_quantity: number; version: number; variance_reason?: string; evidence?: string }, key: string) => apiClient.patch<CountDetail>(`/pharmacy/inventory-counts/${countId}/details/${detailId}`, payload, config(key)).then(response => response.data),
  addUnexpected: (countId: string, payload: { inventory_batch_id: string; physical_quantity: number; evidence: string; variance_reason?: string }, key: string) => apiClient.post<CountDetail>(`/pharmacy/inventory-counts/${countId}/details/unexpected`, payload, config(key)).then(response => response.data),
  submit: (id: string, key: string) => action(`/pharmacy/inventory-counts/${id}/submit`, key),
  requestRecount: (id: string, payload: { assigned_to: string; reason: string }, key: string) => action(`/pharmacy/inventory-counts/${id}/recounts`, key, payload),
  startRecount: (id: string, key: string) => action(`/pharmacy/inventory-counts/${id}/recounts/start`, key),
  recordRecount: (countId: string, detailId: string, payload: { physical_quantity: number; version: number; variance_reason?: string }, key: string) => apiClient.patch<RecountDetail>(`/pharmacy/inventory-counts/${countId}/recounts/details/${detailId}`, payload, config(key)).then(response => response.data),
  resubmit: (id: string, key: string) => action(`/pharmacy/inventory-counts/${id}/recounts/resubmit`, key),
  approve: (id: string, reason: string, key: string) => action(`/pharmacy/inventory-counts/${id}/approve`, key, { reason }),
  apply: (id: string, reason: string, key: string) => action(`/pharmacy/inventory-counts/${id}/apply`, key, { reason }),
  cancel: (id: string, reason: string, key: string) => action(`/pharmacy/inventory-counts/${id}/cancel`, key, { reason }),
}