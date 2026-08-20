import apiClient from './apiClient'
import type { Patient, PatientHistoryItem } from '@/types/common'

export interface PatientCreate {
  first_name: string
  last_name: string
  dob?: string
  age?: number
  gender: string
  phone: string
  email?: string
  address?: string
  blood_group?: string
  insurance_provider?: string
  insurance_id?: string
  aadhar_number: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  /** Set true to proceed after a duplicate warning has been shown to the user. */
  override_duplicate?: boolean
}

export interface PatientDuplicateCandidate {
  id: string
  uhid: string
  first_name: string
  last_name: string
  phone: string
  dob?: string
  aadhar_number?: string
  matched_on: string[]
}

export interface PatientDuplicateError {
  message: string
  duplicates: PatientDuplicateCandidate[]
}

export const patientService = {
  list: (q?: string, options?: { includeInactive?: boolean }) =>
    apiClient.get<Patient[]>('/patients', {
      params: { ...(q ? { q } : {}), ...(options?.includeInactive ? { include_inactive: true } : {}) },
    }).then(r => r.data),

  get: (id: string) =>
    apiClient.get<Patient>(`/patients/${id}`).then(r => r.data),

  create: (data: PatientCreate) =>
    apiClient.post<Patient>('/patients', data).then(r => r.data),

  update: (id: string, data: Partial<PatientCreate>) =>
    apiClient.patch<Patient>(`/patients/${id}`, data).then(r => r.data),

  deactivate: (id: string) =>
    apiClient.post<Patient>(`/patients/${id}/deactivate`).then(r => r.data),

  reactivate: (id: string) =>
    apiClient.post<Patient>(`/patients/${id}/reactivate`).then(r => r.data),

  getHistory: (id: string) =>
    apiClient.get<PatientHistoryItem[]>(`/patients/${id}/history`).then(r => r.data),
}
