import apiClient from './apiClient'

export interface PatientReturnBatchAllocationInput {
  inventory_batch_id: string
  returned_quantity: number
}

export interface PatientReturnItemInput {
  dispense_item_id: string
  returned_quantity: number
  restockable?: boolean
  non_restockable_reason?: string
  batch_allocations?: PatientReturnBatchAllocationInput[]
}

export interface PatientReturnCreateInput {
  dispense_id: string
  return_reason: string
  package_condition?: string
  notes?: string
  items: PatientReturnItemInput[]
  idempotency_key?: string
}

export interface PatientReturnItemRead {
  id: string
  return_id: string
  dispense_item_id: string
  medicine_product_id?: string
  inventory_batch_id?: string
  prescribed_quantity: string
  returned_quantity: string
  original_unit_price: string
  return_amount: string
  status: string
  restockable: boolean
  non_restockable_reason?: string
  validated_by?: string
  validated_at?: string
  created_at: string
  updated_at: string
}

export interface PatientReturnRead {
  id: string
  tenant_id: string
  facility_id: string
  pharmacy_location_id: string
  patient_id: string
  visit_id: string
  dispense_id: string
  invoice_id?: string
  status: string
  reference_key: string
  return_reason: string
  package_condition?: string
  total_return_quantity: string
  total_return_amount: string
  refunded_amount: string
  restockable_count: number
  non_restockable_count: number
  requested_by?: string
  requested_at: string
  validated_by?: string
  validated_at?: string
  accepted_by?: string
  accepted_at?: string
  rejection_reason?: string
  rejected_by?: string
  rejected_at?: string
  refunded_by?: string
  refunded_at?: string
  notes?: string
  created_at: string
  updated_at: string
  items: PatientReturnItemRead[]
}

export interface PatientReturnListResponse {
  items: PatientReturnRead[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface PatientReturnEligibilityAllocation {
  allocation_id: string
  inventory_batch_id: string
  batch_number: string
  expiry_date?: string
  originally_dispensed_quantity: string
  previously_returned_quantity: string
  remaining_returnable_quantity: string
}

export interface PatientReturnEligibilityItem {
  dispense_item_id: string
  medicine_name?: string
  prescribed_quantity: string
  originally_dispensed_quantity: string
  previously_returned_quantity: string
  remaining_returnable_quantity: string
  allocations: PatientReturnEligibilityAllocation[]
}

export interface PatientReturnEligibility {
  dispense_id: string
  patient_id: string
  patient_name?: string
  visit_id: string
  invoice_id?: string
  prescription_id?: string
  dispense_reference?: string
  facility_id: string
  pharmacy_location_id: string
  items: PatientReturnEligibilityItem[]
}

export interface PatientReturnEligibleDispense {
  dispense_id: string
  patient_id: string
  patient_name: string
  patient_uhid: string
  visit_id: string
  prescription_id: string
  invoice_id?: string
  dispense_reference: string
  completed_at?: string
}

export interface SupplierReturnItemInput {
  inventory_batch_id: string
  returned_quantity: number
  unit_cost: number
}

export interface SupplierReturnCreateInput {
  supplier_id: string
  goods_receipt_id?: string
  return_reason: string
  notes?: string
  items: SupplierReturnItemInput[]
  idempotency_key?: string
}

export interface SupplierReturnItemRead {
  id: string
  supplier_return_id: string
  inventory_batch_id: string
  goods_receipt_item_id?: string
  received_quantity: string
  returned_quantity: string
  unit_cost: string
  return_value: string
  stock_reduction_ledger_id?: string
  created_at: string
  updated_at: string
}

export interface SupplierReturnRead {
  id: string
  tenant_id: string
  facility_id: string
  pharmacy_location_id: string
  supplier_id: string
  purchase_order_id?: string
  goods_receipt_id?: string
  status: string
  reference_key: string
  return_reason: string
  total_return_quantity: string
  total_return_value: string
  requested_by?: string
  requested_at: string
  approved_by?: string
  approved_at?: string
  dispatched_by?: string
  dispatched_at?: string
  received_by?: string
  received_at?: string
  notes?: string
  created_at: string
  updated_at: string
  items: SupplierReturnItemRead[]
}

export interface SupplierReturnListResponse {
  items: SupplierReturnRead[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface SupplierReturnEligibilityItem {
  inventory_batch_id: string
  batch_number: string
  medicine_name?: string
  expiry_date?: string
  available_quantity: string
  original_received_quantity: string
  eligible_return_quantity: string
  unit_cost: string
  supplier_id: string
  goods_receipt_id?: string
  purchase_order_id?: string
}

export interface SupplierReturnEligibility {
  supplier_id: string
  supplier_name?: string
  goods_receipt_id?: string
  purchase_order_id?: string
  facility_id: string
  pharmacy_location_id: string
  items: SupplierReturnEligibilityItem[]
}

export interface ReturnListParams {
  page?: number
  page_size?: number
  status?: string
  patient_id?: string
  dispense_id?: string
  supplier_id?: string
  goods_receipt_id?: string
}

export interface InventoryBatchRead {
  id: string
  medicine_id: string
  medicine_name?: string
  batch_number: string
  expiry_date?: string
  available_quantity: string
  received_quantity: string
  status: string
  supplier_id?: string
  goods_receipt_id?: string
  purchase_rate: string
}

export const patientReturnService = {
  list: (params?: Pick<ReturnListParams, 'page' | 'page_size' | 'status' | 'patient_id' | 'dispense_id'>) =>
    apiClient.get<PatientReturnListResponse>('/returns/patient-returns', { params }).then(r => r.data),
  get: (id: string) => apiClient.get<PatientReturnRead>(`/returns/patient-returns/${id}`).then(r => r.data),
  eligibleDispenses: (params?: { q?: string; limit?: number }) =>
    apiClient.get<PatientReturnEligibleDispense[]>('/returns/patient-returns/eligible-dispenses', { params }).then(r => r.data),
  eligibility: (dispenseId: string) =>
    apiClient.get<PatientReturnEligibility>(`/returns/patient-returns/eligibility/${encodeURIComponent(dispenseId)}`).then(r => r.data),
  create: (payload: PatientReturnCreateInput) =>
    apiClient.post<PatientReturnRead>('/returns/patient-returns', payload).then(r => r.data),
  validate: (id: string) => apiClient.post<PatientReturnRead>(`/returns/patient-returns/${id}/validate`).then(r => r.data),
  accept: (id: string) => apiClient.post<PatientReturnRead>(`/returns/patient-returns/${id}/accept`).then(r => r.data),
  reject: (id: string, reason: string) =>
    apiClient.post<PatientReturnRead>(`/returns/patient-returns/${id}/reject`, { rejection_reason: reason }).then(r => r.data),
}

export const supplierReturnService = {
  list: (params?: Pick<ReturnListParams, 'page' | 'page_size' | 'status' | 'supplier_id' | 'goods_receipt_id'>) =>
    apiClient.get<SupplierReturnListResponse>('/returns/supplier-returns', { params }).then(r => r.data),
  get: (id: string) => apiClient.get<SupplierReturnRead>(`/returns/supplier-returns/${id}`).then(r => r.data),
  eligibility: (params: { supplier_id: string; pharmacy_location_id?: string }) =>
    apiClient.get<SupplierReturnEligibility>('/returns/supplier-returns/eligibility', { params }).then(r => r.data),
  create: (payload: SupplierReturnCreateInput) =>
    apiClient.post<SupplierReturnRead>('/returns/supplier-returns', payload).then(r => r.data),
  approve: (id: string) => apiClient.post<SupplierReturnRead>(`/returns/supplier-returns/${id}/approve`).then(r => r.data),
  dispatch: (id: string) => apiClient.post<SupplierReturnRead>(`/returns/supplier-returns/${id}/dispatch`).then(r => r.data),
  receive: (id: string) => apiClient.post<SupplierReturnRead>(`/returns/supplier-returns/${id}/receive`).then(r => r.data),
}

export const inventoryService = {
  listBatches: (params: { facility_id: string; pharmacy_location_id: string; medicine_id?: string; dispensable_only?: boolean }) =>
    apiClient.get<InventoryBatchRead[]>('/pharmacy/inventory/batches', { params }).then(r => r.data),
}
