import apiClient from './apiClient'

export interface NurseRoster {
  id: string
  facility_id: string
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
  substitute_name?: string
  department_name?: string
  doctor_name?: string
}

export interface NurseRosterAudit {
  id: string
  user_id?: string
  action: string
  resource_id?: string
  old_value?: Record<string, unknown>
  new_value?: Record<string, unknown>
  reason?: string
  timestamp: string
}

export interface NurseRosterListParams {
  roster_date?: string
  date_from?: string
  date_to?: string
  department_id?: string
  shift?: string
  user_id?: string
  include_inactive?: boolean
}

export interface NurseRosterCreateInput {
  user_id: string
  roster_date: string
  shift: 'morning' | 'afternoon' | 'night'
  department_id: string
  room?: string
  assigned_doctor_id?: string
  is_present?: boolean
  substitute_user_id?: string
  substitution_reason?: string
}

export const nurseRosterService = {
  list: (params?: NurseRosterListParams) =>
    apiClient.get<NurseRoster[]>('/nurse-roster', { params }).then(r => r.data),
  create: (data: NurseRosterCreateInput) =>
    apiClient.post<NurseRoster>('/nurse-roster', data).then(r => r.data),
  update: (id: string, data: Partial<NurseRoster> & { reason?: string }) =>
    apiClient.patch<NurseRoster>(`/nurse-roster/${id}`, data).then(r => r.data),
  auditHistory: (rosterId?: string) =>
    apiClient.get<NurseRosterAudit[]>('/nurse-roster/audit/history', { params: { roster_id: rosterId } }).then(r => r.data),
}
