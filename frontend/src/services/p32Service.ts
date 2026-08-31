import apiClient from './apiClient'

export interface Location { id: string; location_name: string; location_code: string; active: boolean }
export interface EligibleBatch { id: string; pharmacy_location_id: string; medicine_id: string; batch_number: string; expiry_date?: string; available_quantity: string; reserved_quantity: string; status: string }
export interface Recall { id: string; medicine_id: string; batch_number: string; status: 'DRAFT' | 'ACTIVE' | 'RESOLVED'; reference_key: string; recall_reason: string; regulatory_reference?: string; notification_status: string; initiated_by: string; approved_by?: string; resolution_action?: string; created_at: string }
export interface AffectedPatient { dispense_id: string; patient_id: string; uhid: string; patient_name: string; phone: string; dispensed_quantity: string; dispensed_at?: string; notification_status: string }
export interface TransferItem { id: string; inventory_batch_id: string; transfer_quantity: string; received_quantity?: string; destination_batch_id?: string }
export interface Discrepancy { id: string; transfer_item_id: string; discrepancy_type: string; quantity: string; notes: string; status: 'OPEN' | 'RECONCILED' }
export interface Transfer { id: string; from_location_id: string; to_location_id: string; status: 'DRAFT' | 'APPROVED' | 'IN_TRANSIT' | 'RECEIVED' | 'CANCELLED'; reference_key: string; total_quantity: string; requested_by: string; received_quantity?: string; items?: TransferItem[]; discrepancies?: Discrepancy[]; created_at: string }

const action = (path: string, idempotencyKey: string) => apiClient.post(path, { idempotency_key: idempotencyKey }).then((response) => response.data)
export const p32Service = {
  locations: () => apiClient.get<Location[]>('/pharmacy/inventory/locations').then((response) => response.data),
  recalls: () => apiClient.get<Recall[]>('/pharmacy/recalls').then((response) => response.data),
  recall: (id: string) => apiClient.get<Recall & { affected_stock: unknown[] }>(`/pharmacy/recalls/${id}`).then((response) => response.data),
  affectedPatients: (id: string) => apiClient.get<AffectedPatient[]>(`/pharmacy/recalls/${id}/affected-dispensings`).then((response) => response.data),
  createRecall: (payload: { medicine_id: string; batch_number: string; recall_reason: string; regulatory_reference?: string; idempotency_key: string }) => apiClient.post<Recall>('/pharmacy/recalls', payload).then((response) => response.data),
  approveRecall: (id: string, key: string) => action(`/pharmacy/recalls/${id}/approve`, key) as Promise<Recall>,
  resolveRecall: (id: string, payload: { action: string; reason: string; idempotency_key: string }) => apiClient.post<Recall>(`/pharmacy/recalls/${id}/resolve`, payload).then((response) => response.data),
  eligibleBatches: (source: string) => apiClient.get<EligibleBatch[]>('/pharmacy/transfers/eligible-batches', { params: { source_location_id: source } }).then((response) => response.data),
  transfers: () => apiClient.get<Transfer[]>('/pharmacy/transfers').then((response) => response.data),
  transfer: (id: string) => apiClient.get<Transfer>(`/pharmacy/transfers/${id}`).then((response) => response.data),
  createTransfer: (payload: { source_location_id: string; destination_location_id: string; items: { inventory_batch_id: string; quantity: number }[]; idempotency_key: string }) => apiClient.post<Transfer>('/pharmacy/transfers', payload).then((response) => response.data),
  approveTransfer: (id: string, key: string) => action(`/pharmacy/transfers/${id}/approve`, key) as Promise<Transfer>,
  dispatchTransfer: (id: string, key: string) => action(`/pharmacy/transfers/${id}/dispatch`, key) as Promise<Transfer>,
  receiveTransfer: (id: string, payload: { items: { transfer_item_id: string; quantity_received: number; discrepancy_type?: string; discrepancy_quantity?: number; discrepancy_notes?: string }[]; complete_receipt: boolean; idempotency_key: string }) => apiClient.post<Transfer>(`/pharmacy/transfers/${id}/receive`, payload).then((response) => response.data),
  reconcile: (id: string, payload: { action: string; notes: string; idempotency_key: string }) => apiClient.post<Discrepancy>(`/pharmacy/transfers/discrepancies/${id}/reconcile`, payload).then((response) => response.data),
}
