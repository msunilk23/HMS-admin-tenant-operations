import apiClient from './apiClient'

export const P34_PERMISSIONS = {
  dashboard: 'PHARMACY_DASHBOARD_VIEW',
  reports: 'PHARMACY_REPORT_VIEW',
  export: 'PHARMACY_REPORT_EXPORT',
  alerts: 'PHARMACY_ALERT_VIEW',
  acknowledge: 'PHARMACY_ALERT_ACKNOWLEDGE',
  configure: 'PHARMACY_ALERT_CONFIGURE',
  audit: 'PHARMACY_AUDIT_VIEW',
} as const

export interface PharmacyDashboardMetadata {
  business_date: string
  timezone: string
  facility_id: string
  pharmacy_location_id?: string
  generated_at: string
  currencies: string[]
}

export interface PharmacyDashboardData {
  metadata: PharmacyDashboardMetadata
  financial_data_visible: boolean
  cards: {
    sales: { currency: string; gross: string; discount: string; tax: string; invoice_net: string; refunds: string; net_paid: string }
    prescriptions_pending: number
    dispensed_today: { count: number; quantity: string }
    purchases_today: { count: number; value: string; currency: string }
    patient_returns_today: { count: number; refund_value: string; currency: string }
    supplier_returns_today: { count: number; value: string; currency: string }
    stock_adjustments_today: { count: number; quantity: string; value: string | null }
    low_stock_items: number
    out_of_stock_items: number
    expiring_stock: { '0_30': number; '31_60': number; '61_90': number }
    inventory_valuation: { available: string | null; reserved: string | null; quarantined: string | null; total_physical: string | null; unvalued_quantity: string; currency: string }
    outside_purchases: { item_count: number; quantity: string }
  }
}

export interface PharmacyAlert {
  id: string
  pharmacy_location_id?: string
  alert_type: string
  severity: string
  status: string
  subject_type: string
  subject_key: string
  subject_data: Record<string, unknown>
  title: string
  message: string
  condition_data: Record<string, unknown>
  first_detected_at: string
  last_evaluated_at: string
  resolved_at?: string
}

export interface PharmacyReport {
  report: string
  metadata: PharmacyDashboardMetadata
  filters: Record<string, unknown>
  items: Record<string, unknown>[]
  total: number
  page: number
  page_size: number
}

export interface PharmacyReportFilters {
  start_date?: string
  end_date?: string
  pharmacy_location_id?: string
  medicine_id?: string
  batch_number?: string
  supplier_id?: string
  status?: string
  alert_type?: string
  page?: number
  page_size?: number
}

export const pharmacyDashboardService = {
  capabilities: () => apiClient.get<{ permissions: string[] }>('/pharmacy-dashboard/capabilities').then(response => response.data),
  dashboard: (pharmacy_location_id?: string) => apiClient.get<PharmacyDashboardData>('/pharmacy-dashboard', { params: { pharmacy_location_id } }).then(response => response.data),
  reportCatalogue: () => apiClient.get<string[]>('/pharmacy-dashboard/reports').then(response => response.data),
  report: (report: string, params: PharmacyReportFilters) => apiClient.get<PharmacyReport>(`/pharmacy-dashboard/reports/${report}`, { params }).then(response => response.data),
  exportReport: (report: string, params: PharmacyReportFilters) => apiClient.get<Blob>(`/pharmacy-dashboard/reports/${report}/export`, { params, responseType: 'blob' }).then(response => response.data),
  alerts: (params?: { status?: string; pharmacy_location_id?: string; page?: number; page_size?: number }) => apiClient.get<{ items: PharmacyAlert[]; total: number; page: number; page_size: number }>('/pharmacy-dashboard/alerts', { params }).then(response => response.data),
  acknowledge: (id: string, note: string, idempotencyKey: string) => apiClient.post<PharmacyAlert>(`/pharmacy-dashboard/alerts/${id}/acknowledge`, { note }, { headers: { 'Idempotency-Key': idempotencyKey } }).then(response => response.data),
  configuration: (pharmacy_location_id?: string) => apiClient.get('/pharmacy-dashboard/alert-configuration', { params: { pharmacy_location_id } }).then(response => response.data),
  updateConfiguration: (payload: Record<string, unknown>, idempotencyKey: string) => apiClient.put('/pharmacy-dashboard/alert-configuration', payload, { headers: { 'Idempotency-Key': idempotencyKey } }).then(response => response.data),
}
