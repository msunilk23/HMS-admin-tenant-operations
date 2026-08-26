import apiClient from './apiClient'

export interface ICD10Code {
  id: string
  code: string
  description: string
  is_active: boolean
}

export interface MedicineMaster {
  id: string
  generic_name: string
  brand_name?: string
  strength?: string
  dosage_form?: string
  instructions?: string
  is_active: boolean
}

export interface FormularyMedicineSearchResult {
  medicine_product_id: string
  code: string
  brand_name?: string
  generic_name: string
  strength?: string
  unit?: string
  dosage_form_name: string
  default_route_name?: string
  composition?: string
  is_controlled_drug: boolean
  requires_prescription: boolean
  is_approved: boolean
  is_preferred: boolean
  is_prescribable: boolean
  effective_date?: string
  expiry_date?: string
}

export const masterDataService = {
  searchIcd10: (q: string) => apiClient.get<ICD10Code[]>('/master-data/icd10', { params: { q, limit: 20 } }).then(r => r.data),
  searchMedicines: (q: string) => apiClient.get<MedicineMaster[]>('/master-data/medicines', { params: { q, limit: 20 } }).then(r => r.data),
  searchFormularyMedicines: (q: string, departmentId?: string) => apiClient.get<FormularyMedicineSearchResult[]>('/pharmacy/medicines/search', { params: { q, department_id: departmentId, prescribable_only: true, limit: 20 } }).then(r => r.data),
}