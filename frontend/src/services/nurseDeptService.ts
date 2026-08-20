import apiClient from './apiClient'
import type { NurseDepartment } from '@/types/common'

export const nurseDeptService = {
  list: () =>
    apiClient.get<NurseDepartment[]>('/nurse-departments').then(r => r.data),

  assign: (user_id: string, department_id: string) =>
    apiClient.post<NurseDepartment>('/nurse-departments', { user_id, department_id }).then(r => r.data),

  /** Remove one specific nurse→dept assignment */
  unassign: (userId: string, deptId: string) =>
    apiClient.delete(`/nurse-departments/${userId}/${deptId}`),

  /** Remove ALL dept assignments for a nurse */
  unassignAll: (userId: string) =>
    apiClient.delete(`/nurse-departments/${userId}`),

  /** Returns all departments the logged-in nurse is assigned to */
  myDepartments: () =>
    apiClient.get<NurseDepartment[]>('/nurse-departments/my').then(r => r.data),
}
