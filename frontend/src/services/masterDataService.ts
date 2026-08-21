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

export const masterDataService = {
  searchIcd10: (q: string) => apiClient.get<ICD10Code[]>('/master-data/icd10', { params: { q, limit: 20 } }).then(r => r.data),
  searchMedicines: (q: string) => apiClient.get<MedicineMaster[]>('/master-data/medicines', { params: { q, limit: 20 } }).then(r => r.data),
}