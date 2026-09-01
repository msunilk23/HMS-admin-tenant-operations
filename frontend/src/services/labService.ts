import apiClient from './apiClient'
import type { LabOrder, LabResult } from '@/types/common'

export interface LabResultPayload {
  results?: Record<string, string>
  notes?: string
}

export const labService = {
  listOrders: (params?: { status?: string; visit_id?: string }) =>
    apiClient.get<LabOrder[]>('/lab', { params }).then(r => r.data),

  updateStatus: (orderId: string, new_status: string) =>
    apiClient.patch<LabOrder>(`/lab/${orderId}/status`, null, { params: { new_status } }).then(r => r.data),

  rejectOrder: (orderId: string) =>
    apiClient.post<LabOrder>(`/lab/${orderId}/reject`).then(r => r.data),

  enterResults: (orderId: string, payload: LabResultPayload) =>
    apiClient.post<LabResult>(`/lab/${orderId}/results`, payload).then(r => r.data),

  verifyResults: (orderId: string) =>
    apiClient.post<LabOrder>(`/lab/${orderId}/verify`).then(r => r.data),

  uploadReport: (orderId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<LabResult>(`/lab/${orderId}/results/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },

  getResults: (orderId: string) =>
    apiClient.get<LabResult>(`/lab/${orderId}/results`).then(r => r.data),

  getReportUrl: async (orderId: string): Promise<string> => {
    const response = await apiClient.get(`/lab/${orderId}/results/report`)
    return response.data.url
  },
}
