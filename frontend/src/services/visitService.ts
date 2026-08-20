import apiClient from './apiClient'
import type { Visit, Vitals, Consultation } from '@/types/common'

export interface VisitCreate {
  patient_id: string
  doctor_id: string
  appointment_id?: string
  department_id?: string
}

export interface VitalsCreate {
  visit_id: string
  bp_systolic?: number
  bp_diastolic?: number
  temperature?: number
  weight?: number
  height?: number
  spo2?: number
  pulse?: number
}

export interface ConsultationCreate {
  visit_id: string
  chief_complaint?: string
  history?: string
  examination?: string
  diagnosis_icd10?: { code: string; description: string }[]
  notes?: string
  follow_up_date?: string
}

export const visitService = {
  list: (params?: { patient_id?: string; status?: string; department_id?: string; open_only?: boolean }) =>
    apiClient.get<Visit[]>('/visits', { params }).then(r => r.data),

  get: (id: string) =>
    apiClient.get<Visit>(`/visits/${id}`).then(r => r.data),

  create: (data: VisitCreate) =>
    apiClient.post<Visit>('/visits', data).then(r => r.data),

  updateStatus: (id: string, status: string) =>
    apiClient.patch<Visit>(`/visits/${id}/status`, { status }).then(r => r.data),

  dispatch: (id: string, action: 'close' | 'billing' | 'pharmacy' | 'lab') =>
    apiClient.post<Visit>(`/visits/${id}/dispatch`, { action }).then(r => r.data),
}

export const vitalsService = {
  record: (data: VitalsCreate) =>
    apiClient.post<Vitals>('/vitals', data).then(r => r.data),

  get: (visitId: string) =>
    apiClient.get<Vitals>(`/vitals/${visitId}`).then(r => r.data),
}

export const consultationService = {
  create: (data: ConsultationCreate) =>
    apiClient.post<Consultation>('/consultations', data).then(r => r.data),

  update: (visitId: string, data: Partial<ConsultationCreate>) =>
    apiClient.patch<Consultation>(`/consultations/${visitId}`, data).then(r => r.data),

  get: (visitId: string) =>
    apiClient.get<Consultation>(`/consultations/${visitId}`).then(r => r.data),
}
