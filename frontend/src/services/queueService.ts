import apiClient from './apiClient'
import type { QueueSummary, QueueToken } from '@/types/common'

export interface QueueTokenCreate {
  patient_id: string
  appointment_id?: string
  department_id?: string
  doctor_id?: string
  queue_type?: string
  priority?: string
  priority_reason?: string
  waive_fee?: boolean
}

export interface QueueTokenUpdate {
  department_id?: string
  doctor_id?: string
  priority?: string
  priority_reason?: string
}

export const queueService = {
  list: (params?: { queue_type?: string; department_id?: string; status?: string }) =>
    apiClient.get<QueueToken[]>('/queue', { params }).then(r => r.data),

  summary: () => apiClient.get<QueueSummary>('/queue/summary').then(r => r.data),

  issue: (data: QueueTokenCreate) =>
    apiClient.post<QueueToken>('/queue', data).then(r => r.data),

  edit: (tokenId: string, data: QueueTokenUpdate) =>
    apiClient.patch<QueueToken>(`/queue/${tokenId}`, data).then(r => r.data),

  cancel: (tokenId: string, notes: string) =>
    apiClient.post<QueueToken>(`/queue/${tokenId}/cancel`, { notes }).then(r => r.data),

  updateStatus: (tokenId: string, status: string) =>
    apiClient.patch<QueueToken>(`/queue/${tokenId}/status`, { status }).then(r => r.data),

  checkIn: (tokenId: string) =>
    apiClient.post<QueueToken>(`/queue/${tokenId}/checkin`).then(r => r.data),
}
