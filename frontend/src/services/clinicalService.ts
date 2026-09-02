import apiClient from './apiClient'
import type { Prescription, Invoice, Doctor, Department, Appointment, AppointmentSlot, CheckInResult } from '@/types/common'

export interface MedicineItemCreate {
  medicine?: string
  medicine_master_id?: string
  medicine_product_id?: string
  is_free_text?: boolean
  free_text_reason?: string
  strength?: string
  dosage_form?: string
  dose: string
  frequency: string
  food_instruction?: string
  duration: string
  route: string
  quantity?: string
  quantity_override_reason?: string
  timing_relative_to_food?: string
  notes?: string
}

export interface PrescriptionCreate {
  visit_id: string
  medicines?: MedicineItemCreate[]
  instructions?: string
  lab_tests?: { test_id: string; notes?: string }[]
}

export interface InvoiceCreate {
  visit_id: string
  line_items?: { description: string; amount: number }[]
  discount?: number
  tax?: number
}

export const prescriptionService = {
  create: (data: PrescriptionCreate) =>
    apiClient.post<Prescription>('/prescriptions', data).then(r => r.data),

  update: (visitId: string, data: Omit<PrescriptionCreate, 'visit_id'>) =>
    apiClient.patch<Prescription>(`/prescriptions/${visitId}`, data).then(r => r.data),

  get: (visitId: string) =>
    apiClient.get<Prescription>(`/prescriptions/${visitId}`).then(r => r.data),
}

export const billingService = {
  createInvoice: (data: InvoiceCreate) =>
    apiClient.post<Invoice>('/billing', data).then(r => r.data),

  listByVisit: (visitId: string) =>
    apiClient.get<Invoice[]>('/billing', { params: { visit_id: visitId } }).then(r => r.data),

  getByVisit: (visitId: string) =>
    apiClient.get<Invoice>(`/billing/visit/${visitId}`).then(r => r.data),

  pay: (invoiceId: string, payment_method: string) =>
    apiClient.post<Invoice>(`/billing/${invoiceId}/pay`, { payment_method }).then(r => r.data),

  recordPayment: (invoiceId: string, data: { payment_method: string; amount?: number; transaction_reference?: string }) =>
    apiClient.post(`/billing/${invoiceId}/payments`, data).then(r => r.data),

  getReceipt: (invoiceId: string) =>
    apiClient.get<Invoice>(`/billing/${invoiceId}/receipt`).then(r => r.data),

  refund: (invoiceId: string, data: { amount?: number; reason: string }) =>
    apiClient.post<Invoice>(`/billing/${invoiceId}/refund`, data).then(r => r.data),

  syncPayment: (invoiceId: string) =>
    apiClient.post<Invoice>(`/billing/${invoiceId}/sync-payment`).then(r => r.data),

  resendPos: (invoiceId: string) =>
    apiClient.post<Invoice>(`/billing/${invoiceId}/resend-pos`).then(r => r.data),

  admitPatient: (invoiceId: string) =>
    apiClient.post<Invoice>(`/billing/${invoiceId}/admit-patient`).then(r => r.data),

  publicConfig: () =>
    apiClient.get<{ razorpay_key_id: string }>('/billing/public-config').then(r => r.data),
}

export const doctorService = {
  list: (params?: { include_inactive?: boolean; department_id?: string }) =>
    apiClient.get<Doctor[]>('/doctors', { params }).then(r => r.data),

  get: (id: string) =>
    apiClient.get<Doctor>(`/doctors/${id}`).then(r => r.data),

  create: (data: {
    user_id: string
    full_name: string
    specialization: string
    department_id?: string
    consultation_fee?: number
    qualification?: string
    experience_years?: number
  }) => apiClient.post<Doctor>('/doctors', data).then(r => r.data),

  /** Creates login account (role=doctor) + doctor profile in one step. */
  onboard: (data: {
    email: string
    phone: string
    username?: string
    full_name: string
    specialization: string
    department_id?: string
    consultation_fee?: number
    qualification?: string
    experience_years?: number
    send_via?: string
    schedule_later?: boolean
    schedules?: Array<{
      doctor_id?: string
      department_id?: string
      weekday: number
      start_time: string
      end_time: string
      slot_duration_minutes: number
      capacity: number
      effective_from?: string | null
      effective_to?: string | null
      room?: string | null
      appointment_type?: string
      is_active?: boolean
      notes?: string | null
    }>
  }) => apiClient.post<Doctor & { temp_password: string }>('/doctors/onboard', data).then(r => r.data),

  update: (id: string, data: Partial<{
    full_name: string
    specialization: string
    department_id: string | null
    consultation_fee: number
    qualification: string
    experience_years: number
    is_active: boolean
  }>) => apiClient.patch<Doctor>(`/doctors/${id}`, data).then(r => r.data),

  resetPassword: (doctorId: string, reason: string, sendVia: 'sms' | 'whatsapp' | 'none') =>
    apiClient.post<{
      message: string
      doctor_id: string
      user_id: string
      username: string
      phone: string | null
      temporary_password: string
      must_change_password: boolean
      delivery_status: 'sent' | 'failed' | 'not_requested'
    }>(`/doctors/${doctorId}/reset-password`, { reason, send_via: sendVia }).then(r => r.data),
}

export const userService = {
  /** List non-doctor staff users, optionally filtered by role. */
  list: (params?: { role?: string; include_inactive?: boolean }) =>
    apiClient.get<import('@/types/common').StaffUser[]>('/users', { params }).then(r => r.data),

  create: (data: {
    email?: string
    phone: string
    username?: string
    full_name: string
    role: string
    gender: string
    send_via: string
  }) => apiClient.post<import('@/types/common').StaffUser & { temp_password: string }>('/users', data).then(r => r.data),

  update: (id: string, data: { full_name?: string; is_active?: boolean }) =>
    apiClient.patch<import('@/types/common').StaffUser>(`/users/${id}`, data).then(r => r.data),

  resetPassword: (id: string) =>
    apiClient.post<{ detail: string; phone: string }>(`/users/${id}/reset-password`).then(r => r.data),
}

export const departmentService = {
  list: (include_inactive = false) =>
    apiClient.get<Department[]>('/departments', { params: { include_inactive } }).then(r => r.data),

  get: (id: string) =>
    apiClient.get<Department>(`/departments/${id}`).then(r => r.data),

  create: (data: { name: string; description?: string }) =>
    apiClient.post<Department>('/departments', data).then(r => r.data),

  update: (id: string, data: Partial<{ name: string; description: string; is_active: boolean }>) =>
    apiClient.patch<Department>(`/departments/${id}`, data).then(r => r.data),
}

export const appointmentService = {
  list: (params?: {
    date?: string
    doctor_id?: string
    patient_id?: string
    status?: string
  }) => apiClient.get<Appointment[]>('/appointments', { params }).then(r => r.data),

  get: (id: string) =>
    apiClient.get<Appointment>(`/appointments/${id}`).then(r => r.data),

  book: (data: {
    patient_id: string
    doctor_id: string
    slot_time: string
    type?: 'walkin' | 'phone' | 'online'
    notes?: string
  }) => apiClient.post<Appointment>('/appointments', data).then(r => r.data),

  slots: (doctor_id: string, date: string) =>
    apiClient.get<AppointmentSlot[]>('/appointments/slots', { params: { doctor_id, date } }).then(r => r.data),

  reschedule: (id: string, slot_time: string, notes?: string) =>
    apiClient.patch<Appointment>(`/appointments/${id}/reschedule`, { slot_time, notes }).then(r => r.data),

  cancel: (id: string) =>
    apiClient.patch<Appointment>(`/appointments/${id}/cancel`, {}).then(r => r.data),

  checkin: (id: string, waive_fee = false) =>
    apiClient.post<CheckInResult>(`/appointments/${id}/checkin`, { waive_fee }).then(r => r.data),
}
