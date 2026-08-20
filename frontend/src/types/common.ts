// Auth
export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

// Pagination
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// Common
export type UUID = string

export type Gender = 'male' | 'female' | 'other'

export type QueueType = 'registration' | 'vitals' | 'consultation' | 'pharmacy' | 'billing'

export type QueuePriority = 'emergency' | 'urgent' | 'pregnant' | 'disabled' | 'senior_citizen' | 'normal'

export type QueueStatus = 'waiting' | 'called' | 'in_progress' | 'completed' | 'skipped' | 'checked_in' | 'cancelled'

export type VisitStatus =
  | 'registered'
  | 'vitals_recorded'
  | 'vitals_done'
  | 'in_consultation'
  | 'prescription_done'
  | 'dispatched_pharmacy'
  | 'dispatched_lab'
  | 'dispatched_both'
  | 'billing_pending'
  | 'closed'

export type AppointmentStatus =
  | 'scheduled'
  | 'confirmed'
  | 'checked_in'
  | 'completed'
  | 'cancelled'
  | 'no_show'

export type InvoiceStatus = 'draft' | 'pending' | 'partially_paid' | 'paid' | 'cancelled' | 'refunded'

export type PaymentMethod = 'cash' | 'upi' | 'card' | 'insurance' | 'razorpay' | 'follow_up'

// Entities
export interface Patient {
  id: UUID
  uhid: string
  first_name: string
  last_name: string
  dob?: string
  age?: number
  gender: Gender
  phone: string
  email?: string
  address?: string
  blood_group?: string
  insurance_provider?: string
  insurance_id?: string
  aadhar_number?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  is_active: boolean
}

export interface Doctor {
  id: UUID
  user_id: UUID
  username?: string
  phone?: string
  full_name: string
  specialization: string
  department_id?: UUID
  department_name?: string
  consultation_fee: number
  qualification?: string
  experience_years?: number
  is_active: boolean
}

export interface StaffUser {
  id: UUID
  full_name: string
  email: string
  username: string
  phone?: string
  role: string
  is_active: boolean
  tenant_name: string
}

export interface Department {
  id: UUID
  name: string
  description?: string
  is_active: boolean
}

export interface QueueToken {
  id: UUID
  patient_id: UUID
  appointment_id?: UUID
  department_id?: UUID
  doctor_id?: UUID
  visit_id?: UUID
  token_no: number
  queue_type: QueueType
  priority: QueuePriority
  priority_reason?: string
  priority_assigned_by?: UUID
  priority_assigned_at?: string
  status: QueueStatus
  notes?: string
  issued_at: string
  called_at?: string
  completed_at?: string
  cancelled_at?: string
  patient?: Patient
  patient_name?: string
  patient_phone?: string
  department_name?: string
  doctor_name?: string
}

export interface QueueStageSummary {
  waiting_count: number
  breached_count: number
  longest_wait_seconds?: number
  sla_threshold_seconds: number
}

export interface QueueSummary {
  as_of: string
  waiting_for_nurse: QueueStageSummary
  waiting_for_doctor: QueueStageSummary
}

export interface Visit {
  id: UUID
  patient_id: UUID
  doctor_id: UUID
  appointment_id?: UUID
  department_id?: UUID
  status: VisitStatus
  created_at: string
  closed_at?: string
  patient?: Patient
  doctor?: Doctor
  patient_name?: string
  doctor_name?: string
  department_name?: string
  doctor_consultation_fee?: number
  priority?: 'emergency' | 'senior_citizen' | 'normal'
  token_no?: number
  has_lab_order?: boolean
}

export interface Vitals {
  id: UUID
  visit_id: UUID
  bp_systolic?: number
  bp_diastolic?: number
  temperature?: number
  weight?: number
  height?: number
  spo2?: number
  pulse?: number
  recorded_at: string
}

export interface MedicineItem {
  name: string
  dose: string
  frequency: string
  duration: string
  route: string
  instructions?: string
}

export interface Consultation {
  id: UUID
  visit_id: UUID
  chief_complaint?: string
  history?: string
  examination?: string
  diagnosis_icd10?: { code: string; description: string }[]
  notes?: string
  follow_up_date?: string
  created_at: string
}

export interface Prescription {
  id: UUID
  visit_id: UUID
  medicines: MedicineItem[]
  lab_tests?: { test_name: string; notes?: string }[]
  instructions?: string
  diagnosis?: string
  notes?: string
  created_at: string
}

export interface InvoiceLineItem {
  description: string
  quantity: number
  unit_price: number
  amount: number
}

export interface PatientHistoryLabOrder {
  id?: UUID
  tests?: { test: string; notes?: string }[]
  status: string
  result?: {
    results?: Record<string, string>
    reported_at: string
    report_url?: string
  }
}

export interface PatientHistoryItem {
  visit_id: UUID
  visit_date: string
  status: string
  doctor_name?: string
  department_name?: string
  consultation?: {
    chief_complaint?: string
    examination?: string
    diagnosis_icd10?: { code: string; description: string }[]
    notes?: string
    follow_up_date?: string
  }
  medicines?: MedicineItem[]
  prescription_instructions?: string
  lab_orders: PatientHistoryLabOrder[]
}

export interface Invoice {
  id: UUID
  visit_id: UUID
  uhid?: string
  line_items: InvoiceLineItem[]
  subtotal: number
  discount: number
  tax: number
  total: number
  paid_amount: number
  balance: number
  payment_method?: PaymentMethod
  status: InvoiceStatus
  paid_at?: string
  razorpay_order_id?: string
  razorpay_payment_id?: string
  receipt_number?: string
}

export interface Appointment {
  id: UUID
  patient_id: UUID
  doctor_id: UUID
  slot_time: string
  status: AppointmentStatus
  type: 'walkin' | 'phone' | 'online'
  notes?: string
  booked_by_user_id?: UUID
  created_at: string
  patient_name?: string
  patient_uhid?: string
  doctor_name?: string
}

export interface NurseDepartment {
  id: UUID
  user_id: UUID
  department_id: UUID
  assigned_at: string
  assigned_by: UUID
  nurse_name?: string
  department_name?: string
}

export interface LabOrder {
  id: UUID
  visit_id: UUID
  tests: { test: string; notes?: string }[]
  status: 'ordered' | 'sample_pending' | 'sample_collected' | 'processing' | 'result_ready' | 'verified' | 'completed' | 'rejected'
  ordered_at: string
  patient_name?: string
  doctor_name?: string
  result?: LabResult
}

export interface LabResult {
  id: UUID
  lab_order_id: UUID
  results: Record<string, string>
  notes?: string
  report_url?: string
  reported_by_user_id?: UUID
  reported_at: string
  verified_by_user_id?: UUID
  verified_at?: string
}

export interface PharmacyQueueItem {
  id: UUID
  prescription_id: UUID
  patient_id?: UUID
  visit_id?: UUID
  status: 'pending' | 'preparing' | 'ready' | 'partial' | 'dispensed' | 'cancelled'
  notes?: string
  updated_at: string
  patient_name?: string
  medicines?: { name: string; dose: string; frequency: string; duration: string; route: string }[]
}

export interface ClinicalAlert {
  id: UUID
  patient_id: UUID
  alert_type: 'allergy' | 'clinical' | string
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  description: string
  is_active: boolean
  created_at: string
  resolved_at?: string
}

export interface AppointmentSlot {
  slot_time: string
  is_available: boolean
}

export interface CheckInResult {
  appointment_id: UUID
  visit_id: UUID
  token_id: UUID
  token_no: number
  queue_type: string
  needs_payment: boolean
  invoice_id?: UUID
}
