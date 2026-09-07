import apiClient from './apiClient'

export interface PatientRouteStep {
  id: string
  route_id: string
  visit_id: string
  destination: 'PHARMACY' | 'LAB' | 'BILLING' | 'EXIT'
  source_type?: string
  source_record_id?: string
  status: string
  presentation_deadline_at?: string
  presented_at?: string
  service_started_at?: string
  completed_at?: string
  not_presented_at?: string
  reopened_at?: string
  presentation_channel?: string
  outcome_reason?: string
  late_presentation: boolean
}

export interface PatientRoute {
  id: string
  visit_id: string
  consultation_id?: string
  patient_id: string
  uhid: string
  facility_id?: string
  status: string
  completed_at?: string
  steps: PatientRouteStep[]
}

export interface PrescriptionDocument {
  version: number
  created_at: string
  is_current: boolean
}

export const routingService = {
  getForVisit: (visitId: string) => apiClient.get<PatientRoute>(`/visits/${visitId}/routing`).then(r => r.data),
  listSteps: (params?: { destination?: string; status?: string }) => apiClient.get<PatientRouteStep[]>('/routing/steps', { params }).then(r => r.data),
  present: (stepId: string, channel = 'RECEPTION') => apiClient.post<PatientRouteStep>(`/routing/steps/${stepId}/present`, { channel }).then(r => r.data),
  start: (stepId: string) => apiClient.post<PatientRouteStep>(`/routing/steps/${stepId}/start`).then(r => r.data),
  complete: (stepId: string) => apiClient.post<PatientRouteStep>(`/routing/steps/${stepId}/complete`).then(r => r.data),
  expire: () => apiClient.post<{ expired: number }>('/routing/expire').then(r => r.data),
  listPrescriptionDocuments: (visitId: string) => apiClient.get<PrescriptionDocument[]>(`/prescriptions/${visitId}/documents`).then(r => r.data),
  downloadPrescription: (visitId: string, version: number) => apiClient.get<Blob>(`/prescriptions/${visitId}/documents/${version}/download`, { responseType: 'blob' }).then(r => r.data),
}