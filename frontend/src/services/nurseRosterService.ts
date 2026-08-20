import apiClient from './apiClient'

export interface NurseRoster {
  id: string
  user_id: string
  roster_date: string
  shift: 'morning' | 'afternoon' | 'night'
  department_id: string
  room?: string
  assigned_doctor_id?: string
  is_present: boolean
  substitute_user_id?: string
  substitution_reason?: string
  is_active: boolean
  nurse_name?: string
  department_name?: string
  doctor_name?: string
}

export const nurseRosterService = {
  list: (params?: { roster_date?: string; include_inactive?: boolean }) =>
    apiClient.get<NurseRoster[]>('/nurse-roster', { params }).then(r => r.data),
  create: (data: Omit<NurseRoster, 'id' | 'nurse_name' | 'department_name' | 'doctor_name' | 'is_active'>) =>
    apiClient.post<NurseRoster>('/nurse-roster', data).then(r => r.data),
  update: (id: string, data: Partial<NurseRoster>) =>
    apiClient.patch<NurseRoster>(`/nurse-roster/${id}`, data).then(r => r.data),
}
