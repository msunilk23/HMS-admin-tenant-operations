import apiClient from './apiClient'

export interface DoctorSchedule {
  id: string
  doctor_id: string
  department_id: string | null
  weekday: number
  start_time: string
  end_time: string
  slot_duration_minutes: number
  capacity: number
  effective_from: string | null
  effective_to: string | null
  room: string | null
  appointment_type: string | null
  is_active: boolean
  notes: string | null
}

export interface ScheduleException {
  id: string
  doctor_id: string
  exception_type: 'leave' | 'holiday' | 'block'
  start_datetime: string
  end_datetime: string
  reason: string | null
  is_active: boolean
  created_by_user_id: string | null
}

export interface AvailableSlot {
  slot_time: string
  is_available: boolean
  booked_count: number
  remaining_capacity: number
  capacity: number
  room: string | null
  appointment_type: string | null
  blocked_reason: string | null
}

export const doctorScheduleService = {
  listDoctorSchedules: (params?: { doctor_id?: string; weekday?: number; date?: string; include_inactive?: boolean }) =>
    apiClient.get<DoctorSchedule[]>('/doctor-schedules', { params }).then(r => r.data),
  createDoctorSchedule: (data: Omit<DoctorSchedule, 'id'>) =>
    apiClient.post<DoctorSchedule>('/doctor-schedules', data).then(r => r.data),
  updateDoctorSchedule: (id: string, data: Partial<Omit<DoctorSchedule, 'id' | 'doctor_id'>>) =>
    apiClient.patch<DoctorSchedule>(`/doctor-schedules/${id}`, data).then(r => r.data),
  deactivateDoctorSchedule: (id: string) =>
    apiClient.delete<DoctorSchedule>(`/doctor-schedules/${id}`).then(r => r.data),
  listScheduleExceptions: (doctorId: string) =>
    apiClient.get<ScheduleException[]>(`/doctor-schedules/${doctorId}/exceptions`).then(r => r.data),
  createScheduleException: (doctorId: string, data: Omit<ScheduleException, 'id' | 'doctor_id' | 'created_by_user_id'>) =>
    apiClient.post<ScheduleException>(`/doctor-schedules/${doctorId}/exceptions`, data).then(r => r.data),
  updateScheduleException: (doctorId: string, id: string, data: Partial<Omit<ScheduleException, 'id' | 'doctor_id' | 'created_by_user_id'>>) =>
    apiClient.patch<ScheduleException>(`/doctor-schedules/${doctorId}/exceptions/${id}`, data).then(r => r.data),
  deactivateScheduleException: (doctorId: string, id: string) =>
    apiClient.delete<ScheduleException>(`/doctor-schedules/${doctorId}/exceptions/${id}`).then(r => r.data),
  getDoctorAvailability: (doctorId: string, fromDate: string, toDate?: string) =>
    apiClient.get<{ date: string; timezone: string; slots: AvailableSlot[] }[]>(`/doctor-schedules/${doctorId}/availability`, { params: { from_date: fromDate, to_date: toDate } }).then(r => r.data),
}
