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

export interface GenericMedicine { id: string; code: string; name: string; description?: string; therapeutic_class?: string; is_active: boolean }
export interface DosageForm { id: string; code: string; name: string; calculation_type: 'UNIT' | 'LIQUID' | 'PRN' | 'MANUAL'; description?: string; is_active: boolean }
export interface RouteMaster { id: string; code: string; name: string; description?: string; is_active: boolean }
export interface Manufacturer { id: string; code: string; name: string; gstin?: string; country?: string; is_active: boolean }
export interface MedicineProduct { id: string; code: string; generic_medicine_id: string; brand_name?: string; strength?: string; unit?: string; dosage_form_id: string; default_route_id?: string; manufacturer_id?: string; composition?: string; hsn_code?: string; gst_rate?: number; schedule_category?: string; is_controlled_drug: boolean; requires_prescription: boolean; is_active: boolean }
export interface HospitalFormulary { id: string; medicine_product_id: string; department_id: string; is_approved: boolean; is_preferred: boolean; is_prescribable: boolean; effective_date?: string; expiry_date?: string; is_active: boolean }

type Resource = 'generic-medicines' | 'dosage-forms' | 'routes' | 'manufacturers' | 'medicine-products' | 'formulary'
const search = <T>(resource: Resource, q = '') => apiClient.get<T[]>(`/master-data/${resource}`, { params: { q, limit: 100 } }).then(r => r.data)
const create = <T>(resource: Resource, data: unknown) => apiClient.post<T>(`/master-data/${resource}`, data).then(r => r.data)
const update = <T>(resource: Resource, id: string, data: unknown) => apiClient.put<T>(`/master-data/${resource}/${id}`, data).then(r => r.data)
const deactivate = <T>(resource: Resource, id: string) => apiClient.post<T>(`/master-data/${resource}/${id}/deactivate`).then(r => r.data)

export const masterDataService = {
  searchIcd10: (q: string) => apiClient.get<ICD10Code[]>('/master-data/icd10', { params: { q, limit: 20 } }).then(r => r.data),
  searchMedicines: (q: string) => apiClient.get<MedicineMaster[]>('/master-data/medicines', { params: { q, limit: 20 } }).then(r => r.data),
  searchFormularyMedicines: (q: string, departmentId?: string) => apiClient.get<FormularyMedicineSearchResult[]>('/pharmacy/medicines/search', { params: { q, department_id: departmentId, prescribable_only: true, limit: 20 } }).then(r => r.data),
  listGenericMedicines: (q?: string) => search<GenericMedicine>('generic-medicines', q),
  createGenericMedicine: (data: unknown) => create<GenericMedicine>('generic-medicines', data),
  updateGenericMedicine: (id: string, data: unknown) => update<GenericMedicine>('generic-medicines', id, data),
  deactivateGenericMedicine: (id: string) => deactivate<GenericMedicine>('generic-medicines', id),
  listDosageForms: (q?: string) => search<DosageForm>('dosage-forms', q),
  createDosageForm: (data: unknown) => create<DosageForm>('dosage-forms', data),
  updateDosageForm: (id: string, data: unknown) => update<DosageForm>('dosage-forms', id, data),
  deactivateDosageForm: (id: string) => deactivate<DosageForm>('dosage-forms', id),
  listRoutes: (q?: string) => search<RouteMaster>('routes', q),
  createRoute: (data: unknown) => create<RouteMaster>('routes', data),
  updateRoute: (id: string, data: unknown) => update<RouteMaster>('routes', id, data),
  deactivateRoute: (id: string) => deactivate<RouteMaster>('routes', id),
  listManufacturers: (q?: string) => search<Manufacturer>('manufacturers', q),
  createManufacturer: (data: unknown) => create<Manufacturer>('manufacturers', data),
  updateManufacturer: (id: string, data: unknown) => update<Manufacturer>('manufacturers', id, data),
  deactivateManufacturer: (id: string) => deactivate<Manufacturer>('manufacturers', id),
  listMedicineProducts: (q?: string) => search<MedicineProduct>('medicine-products', q),
  createMedicineProduct: (data: unknown) => create<MedicineProduct>('medicine-products', data),
  updateMedicineProduct: (id: string, data: unknown) => update<MedicineProduct>('medicine-products', id, data),
  deactivateMedicineProduct: (id: string) => deactivate<MedicineProduct>('medicine-products', id),
  listFormulary: (q?: string, departmentId?: string) => apiClient.get<HospitalFormulary[]>('/master-data/formulary', { params: { q, department_id: departmentId, limit: 100 } }).then(r => r.data),
  listSuppliers: (q?: string) => apiClient.get<{ id: string; supplier_code: string; supplier_name: string; is_active: boolean }[]>('/pharmacy/suppliers', { params: { q, limit: 100 } }).then(r => r.data),
  createFormulary: (data: unknown) => create<HospitalFormulary>('formulary', data),
  updateFormulary: (id: string, data: unknown) => update<HospitalFormulary>('formulary', id, data),
  deactivateFormulary: (id: string) => deactivate<HospitalFormulary>('formulary', id),
}