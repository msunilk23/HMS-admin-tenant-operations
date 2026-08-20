import apiClient from './apiClient'
import type { ClinicalAlert } from '@/types/common'

export const clinicalAlertService = {
  listForPatient: (patientId: string) =>
    apiClient.get<ClinicalAlert[]>(`/clinical-alerts/patient/${patientId}`).then(r => r.data),
}