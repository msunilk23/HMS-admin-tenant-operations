/**
 * Super Admin — Tenant Management Page.
 * Lists all tenant hospitals; super_admin can toggle features, change plans, and suspend/reactivate.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '@/services/apiClient'

// ── Types ─────────────────────────────────────────────────────────────────────

interface TenantListItem {
  id: string
  hospital_name: string
  schema_name: string
  contact_email: string
  contact_phone: string | null
  logo_url: string | null
  primary_color: string | null
  secondary_color: string | null
  plan: string
  is_active: boolean
  enabled_features: string[]
  feature_count: number
}

interface TenantDetail extends Omit<TenantListItem, 'enabled_features' | 'feature_count'> {
  features: Record<string, boolean>
  admin_username: string | null
  admin_email: string | null
}

// ── Constants ─────────────────────────────────────────────────────────────────

const PLAN_LABELS: Record<string, string> = {
  starter: 'Starter',
  standard: 'Standard',
  enterprise: 'Enterprise',
}

const PLAN_COLORS: Record<string, string> = {
  starter: 'bg-gray-100 text-gray-700',
  standard: 'bg-blue-100 text-blue-700',
  enterprise: 'bg-purple-100 text-purple-700',
}

const FEATURE_LABELS: Record<string, string> = {
  opd_queue: 'OPD Queue',
  appointments: 'Appointments',
  vitals: 'Vitals',
  nurse_roster: 'Nurse Roster',
  lab: 'Lab',
  pharmacy: 'Pharmacy',
  billing: 'Billing',
  razorpay: 'Razorpay Payments',
  whatsapp_sms: 'WhatsApp / SMS',
  cloudinary_reports: 'Cloud Lab Reports',
}

const PLAN_FEATURES: Record<string, string[]> = {
  starter: ['opd_queue', 'vitals', 'appointments'],
  standard: ['opd_queue', 'vitals', 'appointments', 'lab', 'pharmacy', 'billing'],
  enterprise: [
    'opd_queue', 'vitals', 'appointments', 'lab', 'pharmacy', 'billing',
    'razorpay', 'whatsapp_sms', 'cloudinary_reports', 'nurse_roster',
  ],
}

// ── API helpers ───────────────────────────────────────────────────────────────

interface CreateTenantRequest {
  hospital_name: string
  schema_name: string
  contact_email: string
  contact_phone?: string
  plan: string
}

interface CreateTenantResponse {
  id: string
  hospital_name: string
  schema_name: string
  contact_email: string
  contact_phone: string | null
  plan: string
  username: string
  default_password: string
}

interface TenantAdminPasswordResetResponse {
  message: string
  tenant_id: string
  user_id: string
  username: string
  email: string | null
  temporary_password: string
  must_change_password: boolean
}

interface TenantLogoUploadResponse {
  logo_url: string
  primary_color: string
  secondary_color: string
}

const superApi = {
  listTenants: () => apiClient.get<TenantListItem[]>('/super/hospitals').then((r) => r.data),
  getTenant: (id: string) => apiClient.get<TenantDetail>(`/super/hospitals/${id}`).then((r) => r.data),
  updateTenant: (id: string, body: { hospital_name?: string; contact_email?: string; contact_phone?: string; plan?: string; is_active?: boolean; logo_url?: string; primary_color?: string; secondary_color?: string }) =>
    apiClient.patch<TenantDetail>(`/super/hospitals/${id}`, body).then((r) => r.data),
  uploadLogo: (id: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    // Let the browser set the multipart boundary — override apiClient's default JSON content type.
    return apiClient
      .post<TenantLogoUploadResponse>(`/super/hospitals/${id}/logo`, formData, { headers: { 'Content-Type': undefined } })
      .then((r) => r.data)
  },
  bulkSetFeatures: (id: string, enabledFeatures: string[]) =>
    apiClient.put<TenantDetail>(`/super/hospitals/${id}/features`, { enabled_features: enabledFeatures }).then((r) => r.data),
  toggleFeature: (id: string, feature: string, enabled: boolean) =>
    apiClient.patch<TenantDetail>(`/super/hospitals/${id}/features/${feature}`, { enabled }).then((r) => r.data),
  createTenant: (body: CreateTenantRequest) =>
    apiClient.post<CreateTenantResponse>('/super/hospitals', body).then((r) => r.data),
  deleteTenant: (id: string) =>
    apiClient.delete(`/super/hospitals/${id}`),
  resetTenantAdminPassword: (id: string, reason: string) =>
    apiClient.post<TenantAdminPasswordResetResponse>(`/super/tenants/${id}/admin/reset-password`, { reason }).then((r) => r.data),
}

// ── Toast ─────────────────────────────────────────────────────────────────────

type ToastType = 'success' | 'error'

function useToast() {
  const [toast, setToast] = useState<{ message: string; type: ToastType } | null>(null)

  const show = (message: string, type: ToastType = 'success') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  return { toast, show }
}

function ToastBanner({ toast }: { toast: { message: string; type: ToastType } | null }) {
  if (!toast) return null
  return (
    <div
      className={`fixed bottom-6 right-6 z-[100] flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg text-sm font-medium transition-all
        ${toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`}
    >
      {toast.type === 'success' ? (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      )}
      {toast.message}
    </div>
  )
}

// ── Edit Tenant Modal ─────────────────────────────────────────────────────────

function EditTenantModal({
  tenant,
  onClose,
  onToast,
}: {
  tenant: TenantListItem
  onClose: () => void
  onToast: (msg: string, type?: ToastType) => void
}) {
  const qc = useQueryClient()
  const [hospitalName, setHospitalName] = useState(tenant.hospital_name)
  const [contactEmail, setContactEmail] = useState(tenant.contact_email)
  const [contactPhone, setContactPhone] = useState(tenant.contact_phone ?? '')
  const [isActive, setIsActive] = useState(tenant.is_active)
  const [logoUrl, setLogoUrl] = useState(tenant.logo_url ?? '')
  const [primaryColor, setPrimaryColor] = useState(tenant.primary_color ?? '#2563eb')
  const [secondaryColor, setSecondaryColor] = useState(tenant.secondary_color ?? '#eff6ff')

  const save = useMutation({
    mutationFn: () =>
      superApi.updateTenant(tenant.id, {
        hospital_name: hospitalName.trim(),
        contact_email: contactEmail.trim(),
        contact_phone: contactPhone.trim() || undefined,
        is_active: isActive,
        logo_url: logoUrl.trim() || undefined,
        primary_color: primaryColor,
        secondary_color: secondaryColor,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['super-tenants'] })
      qc.invalidateQueries({ queryKey: ['super-tenant', tenant.id] })
      onToast('Hospital updated')
      onClose()
    },
    onError: (err: any) => {
      onToast(err?.response?.data?.detail ?? 'Failed to update hospital', 'error')
    },
  })

  const changed =
    hospitalName.trim() !== tenant.hospital_name ||
    contactEmail.trim() !== tenant.contact_email ||
    (contactPhone.trim() || null) !== tenant.contact_phone ||
    isActive !== tenant.is_active
    || logoUrl.trim() !== (tenant.logo_url ?? '')
    || primaryColor !== (tenant.primary_color ?? '')
    || secondaryColor !== (tenant.secondary_color ?? '')
  const canSave = changed && hospitalName.trim().length > 0 && contactEmail.trim().length > 0 && !save.isPending

  const uploadLogo = useMutation({
    mutationFn: (file: File) => superApi.uploadLogo(tenant.id, file),
    onSuccess: (result) => {
      setLogoUrl(result.logo_url)
      setPrimaryColor(result.primary_color)
      setSecondaryColor(result.secondary_color)
      qc.invalidateQueries({ queryKey: ['super-tenants'] })
      qc.invalidateQueries({ queryKey: ['super-tenant', tenant.id] })
      onToast('Logo uploaded — brand colors updated automatically')
    },
    onError: (err: any) => {
      onToast(err?.response?.data?.detail ?? 'Failed to upload logo', 'error')
    },
  })

  const handleLogoFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) uploadLogo.mutate(file)
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Edit Hospital</h2>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100">
              <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="px-6 py-5 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Hospital Name</label>
              <input
                type="text"
                value={hospitalName}
                onChange={(e) => setHospitalName(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Contact Email</label>
              <input
                type="email"
                value={contactEmail}
                onChange={(e) => setContactEmail(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Phone Number <span className="text-gray-400 font-normal">(optional)</span></label>
              <input
                type="tel"
                value={contactPhone}
                onChange={(e) => setContactPhone(e.target.value)}
                placeholder="+91 98765 43210"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
              />
            </div>

            <div className="border-t border-gray-100 pt-4 space-y-4">
              <h3 className="text-sm font-semibold text-gray-800">Hospital Branding</h3>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Logo image</label>
                <div className="flex items-center gap-3">
                  {logoUrl && (
                    <img src={logoUrl} alt="Hospital logo preview" className="h-10 w-10 flex-shrink-0 rounded-full border border-gray-200 object-cover" />
                  )}
                  <label className="flex-1 cursor-pointer rounded-lg border border-dashed border-gray-300 px-3 py-2 text-center text-sm text-gray-600 hover:bg-gray-50">
                    {uploadLogo.isPending ? 'Uploading…' : 'Upload PNG, JPEG, or WEBP'}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      onChange={handleLogoFileChange}
                      disabled={uploadLogo.isPending}
                      className="hidden"
                    />
                  </label>
                </div>
                <p className="mt-1 text-xs text-gray-400">Brand colors below are picked from the uploaded logo automatically — adjust if needed.</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Logo URL <span className="text-gray-400 font-normal">(optional — used only if no image is uploaded)</span></label>
                <input type="url" value={logoUrl} onChange={e => setLogoUrl(e.target.value)} placeholder="https://cdn.example.com/logo.png" className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-sm font-medium text-gray-700">Primary color<input type="color" value={primaryColor} onChange={e => setPrimaryColor(e.target.value)} className="mt-1 block h-10 w-full cursor-pointer rounded border border-gray-300 p-1" /></label>
                <label className="text-sm font-medium text-gray-700">Secondary color<input type="color" value={secondaryColor} onChange={e => setSecondaryColor(e.target.value)} className="mt-1 block h-10 w-full cursor-pointer rounded border border-gray-300 p-1" /></label>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Status</label>
              <div className="flex gap-3">
                <button
                  onClick={() => setIsActive(true)}
                  className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg border text-sm font-medium transition-colors
                    ${isActive ? 'bg-green-50 border-green-400 text-green-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}
                >
                  <span className={`w-2 h-2 rounded-full ${isActive ? 'bg-green-500' : 'bg-gray-400'}`} />
                  Active
                </button>
                <button
                  onClick={() => setIsActive(false)}
                  className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg border text-sm font-medium transition-colors
                    ${!isActive ? 'bg-red-50 border-red-400 text-red-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}
                >
                  <span className={`w-2 h-2 rounded-full ${!isActive ? 'bg-red-500' : 'bg-gray-400'}`} />
                  Inactive
                </button>
              </div>
            </div>

            <div className="flex gap-3 pt-1">
              <button
                onClick={onClose}
                className="flex-1 border border-gray-300 text-gray-700 text-sm py-2.5 rounded-lg font-medium hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => save.mutate()}
                disabled={!canSave}
                className="flex-1 bg-primary text-white text-sm py-2.5 rounded-lg font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {save.isPending ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

// ── Create Tenant Modal ───────────────────────────────────────────────────────

const toSchemaName = (name: string) =>
  name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 63)

function CreateTenantModal({
  onClose,
  onToast,
}: {
  onClose: () => void
  onToast: (msg: string, type?: ToastType) => void
}) {
  const qc = useQueryClient()
  const [hospitalName, setHospitalName] = useState('')
  const [schemaName, setSchemaName] = useState('')
  const [schemaTouched, setSchemaTouched] = useState(false)
  const [contactEmail, setContactEmail] = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [plan, setPlan] = useState('starter')
  const [createdTenant, setCreatedTenant] = useState<CreateTenantResponse | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  const handleNameChange = (v: string) => {
    setHospitalName(v)
    if (!schemaTouched) setSchemaName(toSchemaName(v))
  }

  const copy = (text: string, label: string) => {
    navigator.clipboard.writeText(text)
    setCopied(label)
    setTimeout(() => setCopied(null), 2000)
  }

  const create = useMutation({
    mutationFn: () => superApi.createTenant({ hospital_name: hospitalName.trim(), schema_name: schemaName.trim(), contact_email: contactEmail.trim(), contact_phone: contactPhone.trim() || undefined, plan }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['super-tenants'] })
      setCreatedTenant(data)
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail ?? 'Failed to create tenant'
      onToast(detail, 'error')
    },
  })

  const schemaValid = /^[a-z][a-z0-9_]{1,62}$/.test(schemaName)
  const canSubmit = hospitalName.trim() && schemaValid && contactEmail.trim() && !create.isPending

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={!createdTenant ? onClose : undefined} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">
              {createdTenant ? 'Tenant Created' : 'Add New Hospital'}
            </h2>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100">
              <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {createdTenant ? (
            /* ── Success / Credentials state ── */
            <div className="px-6 py-5 space-y-4">
              <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-sm text-green-800">
                <p className="font-semibold mb-1">✓ {createdTenant.hospital_name} is live</p>
                <p className="text-green-700 text-xs">Schema <span className="font-mono font-medium">{createdTenant.schema_name}</span> provisioned and all tables migrated.</p>
              </div>

              <p className="text-sm text-gray-600 font-medium">Share these default credentials with the hospital admin:</p>

              <div className="space-y-2">
                {[
                  { label: 'Username', value: createdTenant.username },
                  { label: 'Password', value: createdTenant.default_password },
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
                    <div>
                      <p className="text-xs text-gray-400">{label}</p>
                      <p className="font-mono text-sm font-medium text-gray-900">{value}</p>
                    </div>
                    <button
                      onClick={() => copy(value, label)}
                      className="text-xs text-primary hover:underline font-medium"
                    >
                      {copied === label ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                ))}
              </div>

              <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                ⚠️ Ask the admin to change their password immediately after first login.
              </p>

              <button
                onClick={onClose}
                className="w-full bg-primary text-white py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
              >
                Done
              </button>
            </div>
          ) : (
            /* ── Form state ── */
            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Hospital Name</label>
                <input
                  type="text"
                  value={hospitalName}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="Apollo Multi-Speciality Hospital"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Schema Name</label>
                <input
                  type="text"
                  value={schemaName}
                  onChange={(e) => { setSchemaTouched(true); setSchemaName(e.target.value) }}
                  placeholder="apollo"
                  className={`w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary
                    ${schemaName && !schemaValid ? 'border-red-400 bg-red-50' : 'border-gray-300'}`}
                />
                <p className="text-xs text-gray-400 mt-0.5">Lowercase letters, digits, underscore. This cannot be changed later.</p>
                {schemaName && !schemaValid && (
                  <p className="text-xs text-red-600 mt-0.5">Must start with a letter and be 2–63 chars (lowercase, digits, _).</p>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Contact Email</label>
                <input
                  type="email"
                  value={contactEmail}
                  onChange={(e) => setContactEmail(e.target.value)}
                  placeholder="admin@apollo-hospital.in"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Phone Number <span className="text-gray-400 font-normal">(optional)</span></label>
                <input
                  type="tel"
                  value={contactPhone}
                  onChange={(e) => setContactPhone(e.target.value)}
                  placeholder="+91 98765 43210"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Subscription Plan</label>
                <select
                  value={plan}
                  onChange={(e) => setPlan(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                >
                  {Object.entries(PLAN_LABELS).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>

              <div className="flex gap-3 pt-1">
                <button
                  onClick={onClose}
                  className="flex-1 border border-gray-300 text-gray-700 text-sm py-2.5 rounded-lg font-medium hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={() => create.mutate()}
                  disabled={!canSubmit}
                  className="flex-1 bg-primary text-white text-sm py-2.5 rounded-lg font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  {create.isPending ? 'Creating…' : 'Create Hospital'}
                </button>
              </div>

              {create.isPending && (
                <p className="text-xs text-center text-gray-400">
                  Provisioning schema and running migrations — this may take a few seconds…
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ── Detail Panel ──────────────────────────────────────────────────────────────

function TenantDetailPanel({
  tenantId,
  onClose,
  onToast,
}: {
  tenantId: string
  onClose: () => void
  onToast: (msg: string, type?: ToastType) => void
}) {
  const qc = useQueryClient()
  const [confirmSuspend, setConfirmSuspend] = useState(false)
  const [showReset, setShowReset] = useState(false)
  const [resetReason, setResetReason] = useState('')
  const [resetResult, setResetResult] = useState<TenantAdminPasswordResetResponse | null>(null)

  const { data: tenant, isLoading } = useQuery({
    queryKey: ['super-tenant', tenantId],
    queryFn: () => superApi.getTenant(tenantId),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['super-tenant', tenantId] })
    qc.invalidateQueries({ queryKey: ['super-tenants'] })
  }

  const changePlan = useMutation({
    mutationFn: (plan: string) => {
      const enabledFeatures = PLAN_FEATURES[plan] ?? []
      return Promise.all([
        superApi.updateTenant(tenantId, { plan }),
        superApi.bulkSetFeatures(tenantId, enabledFeatures),
      ])
    },
    onSuccess: () => { invalidate(); onToast('Plan updated and features synced') },
    onError: () => onToast('Failed to update plan', 'error'),
  })

  const toggleFeature = useMutation({
    mutationFn: ({ feature, enabled }: { feature: string; enabled: boolean }) =>
      superApi.toggleFeature(tenantId, feature, enabled),
    onSuccess: (_, { feature, enabled }) => {
      invalidate()
      onToast(`${FEATURE_LABELS[feature] ?? feature} ${enabled ? 'enabled' : 'disabled'}`)
    },
    onError: () => onToast('Failed to toggle feature', 'error'),
  })

  const toggleActive = useMutation({
    mutationFn: (is_active: boolean) => superApi.updateTenant(tenantId, { is_active }),
    onSuccess: (data) => {
      invalidate()
      setConfirmSuspend(false)
      onToast(data.is_active ? 'Hospital reactivated' : 'Hospital suspended')
    },
    onError: () => { setConfirmSuspend(false); onToast('Action failed', 'error') },
  })

  const resetAdmin = useMutation({
    mutationFn: () => superApi.resetTenantAdminPassword(tenantId, resetReason.trim()),
    onSuccess: (data) => {
      setResetResult(data)
      setShowReset(false)
      setResetReason('')
    },
  })

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />

      {/* Slide-in panel */}
      <div className="fixed right-0 top-0 bottom-0 z-50 w-full max-w-lg bg-white shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            {isLoading ? 'Loading…' : tenant?.hospital_name}
          </h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors">
            <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">Loading…</div>
        ) : tenant ? (
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">

            {/* Info */}
            <div className="text-sm text-gray-600 space-y-1">
              <p><span className="font-medium text-gray-800">Schema:</span> {tenant.schema_name}</p>
              <p><span className="font-medium text-gray-800">Email:</span> {tenant.contact_email}</p>
            </div>

            <div className="border border-amber-200 bg-amber-50 rounded-lg p-4 space-y-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-900">Tenant Administrator</h3>
                {tenant.admin_username ? (
                  <p className="text-sm text-gray-700 mt-1">
                    {tenant.admin_username} · {tenant.admin_email ?? 'No email registered'}
                  </p>
                ) : (
                  <p className="text-sm text-amber-800 mt-1">No single active hospital administrator found.</p>
                )}
              </div>
              {resetResult ? (
                <div className="bg-white border border-amber-200 rounded-lg p-3 space-y-3">
                  <p className="text-sm font-medium text-gray-900">Temporary password generated</p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 bg-gray-100 rounded px-2 py-1.5 text-sm font-mono select-all">{resetResult.temporary_password}</code>
                    <button
                      type="button"
                      onClick={() => void navigator.clipboard.writeText(resetResult.temporary_password)}
                      className="px-3 py-1.5 bg-gray-900 text-white rounded text-xs font-medium hover:bg-gray-700"
                    >
                      Copy
                    </button>
                  </div>
                  <p className="text-xs text-amber-800">Existing sessions were terminated. The administrator must change this password at next login.</p>
                  <button
                    type="button"
                    onClick={() => setResetResult(null)}
                    className="text-xs text-gray-600 hover:text-gray-900"
                  >
                    Clear temporary password
                  </button>
                </div>
              ) : showReset ? (
                <div className="bg-white border border-amber-200 rounded-lg p-3 space-y-3">
                  <p className="text-xs text-gray-700">Existing sessions will be terminated and the tenant administrator must change the password at next login.</p>
                  <textarea
                    value={resetReason}
                    onChange={(e) => setResetReason(e.target.value)}
                    maxLength={500}
                    rows={3}
                    placeholder="Reason for this reset (required)"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                  />
                  {resetAdmin.isError && (
                    <p className="text-xs text-red-600">{(resetAdmin.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Password reset failed.'}</p>
                  )}
                  <div className="flex gap-2">
                    <button type="button" onClick={() => { setShowReset(false); setResetReason(''); resetAdmin.reset() }} className="flex-1 border border-gray-300 text-gray-700 text-sm py-2 rounded-lg">Cancel</button>
                    <button
                      type="button"
                      onClick={() => resetAdmin.mutate()}
                      disabled={resetReason.trim().length < 5 || resetAdmin.isPending}
                      className="flex-1 bg-amber-600 text-white text-sm py-2 rounded-lg font-medium hover:bg-amber-700 disabled:opacity-50"
                    >
                      {resetAdmin.isPending ? 'Resetting…' : 'Confirm Reset'}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowReset(true)}
                  disabled={!tenant.is_active || !tenant.admin_username}
                  className="w-full border border-amber-500 text-amber-800 text-sm py-2 rounded-lg font-medium hover:bg-amber-100 disabled:opacity-50"
                >
                  Reset Tenant Admin Password
                </button>
              )}
            </div>

            {/* Plan selector */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Subscription Plan</label>
              <select
                value={tenant.plan}
                disabled={changePlan.isPending}
                onChange={(e) => changePlan.mutate(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary disabled:opacity-60"
              >
                {Object.entries(PLAN_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
              {changePlan.isPending && (
                <p className="text-xs text-gray-400 mt-1">Updating plan and syncing features…</p>
              )}
            </div>

            {/* Feature toggles */}
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-3">Feature Entitlements</h3>
              <div className="space-y-2">
                {Object.entries(FEATURE_LABELS).map(([key, label]) => {
                  const enabled = tenant.features[key] ?? false
                  const pending = toggleFeature.isPending && toggleFeature.variables?.feature === key
                  return (
                    <div
                      key={key}
                      className="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors"
                    >
                      <span className="text-sm text-gray-800">{label}</span>
                      <button
                        disabled={pending || changePlan.isPending}
                        onClick={() => toggleFeature.mutate({ feature: key, enabled: !enabled })}
                        className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none disabled:opacity-50
                          ${enabled ? 'bg-primary' : 'bg-gray-300'}`}
                        role="switch"
                        aria-checked={enabled}
                      >
                        <span
                          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200
                            ${enabled ? 'translate-x-4' : 'translate-x-0'}`}
                        />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Suspend / Reactivate */}
            <div className="border-t border-gray-200 pt-5">
              {tenant.is_active ? (
                <>
                  {confirmSuspend ? (
                    <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-3">
                      <p className="text-sm text-red-700 font-medium">
                        Suspend "{tenant.hospital_name}"? All users will be blocked on next login.
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => toggleActive.mutate(false)}
                          disabled={toggleActive.isPending}
                          className="flex-1 bg-red-600 text-white text-sm py-2 rounded-lg font-medium hover:bg-red-700 disabled:opacity-60"
                        >
                          {toggleActive.isPending ? 'Suspending…' : 'Confirm Suspend'}
                        </button>
                        <button
                          onClick={() => setConfirmSuspend(false)}
                          className="flex-1 bg-white border border-gray-300 text-gray-700 text-sm py-2 rounded-lg font-medium hover:bg-gray-50"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => setConfirmSuspend(true)}
                      className="w-full border border-red-300 text-red-600 text-sm py-2 rounded-lg font-medium hover:bg-red-50 transition-colors"
                    >
                      Suspend Hospital
                    </button>
                  )}
                </>
              ) : (
                <button
                  onClick={() => toggleActive.mutate(true)}
                  disabled={toggleActive.isPending}
                  className="w-full bg-green-600 text-white text-sm py-2 rounded-lg font-medium hover:bg-green-700 disabled:opacity-60 transition-colors"
                >
                  {toggleActive.isPending ? 'Reactivating…' : 'Reactivate Hospital'}
                </button>
              )}
            </div>
          </div>
        ) : null}
      </div>

      {/* Confirm suspend dialog already inside panel — no extra modal needed */}
    </>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function TenantsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [editTenant, setEditTenant] = useState<TenantListItem | null>(null)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const { toast, show: showToast } = useToast()
  const qc = useQueryClient()

  const { data: tenants = [], isLoading } = useQuery({
    queryKey: ['super-tenants'],
    queryFn: superApi.listTenants,
  })

  const deleteTenant = useMutation({
    mutationFn: (id: string) => superApi.deleteTenant(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['super-tenants'] })
      setDeleteId(null)
      showToast('Tenant deleted')
    },
    onError: () => { setDeleteId(null); showToast('Failed to delete tenant', 'error') },
  })

  const tenantToDelete = tenants.find((t) => t.id === deleteId)

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tenant Hospitals</h1>
          <p className="text-sm text-gray-500 mt-1">Manage plans, feature entitlements, and hospital accounts.</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 bg-primary text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add Hospital
        </button>
      </div>

      {isLoading ? (
        <div className="text-center py-16 text-gray-400 text-sm">Loading tenants…</div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Hospital</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Plan</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Features</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {tenants.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 cursor-pointer" onClick={() => setSelectedId(t.id)}>
                    <p className="font-medium text-gray-900">{t.hospital_name}</p>
                    <p className="text-xs text-gray-400">{t.contact_email}</p>
                  </td>
                  <td className="px-4 py-3 cursor-pointer" onClick={() => setSelectedId(t.id)}>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${PLAN_COLORS[t.plan] ?? 'bg-gray-100 text-gray-700'}`}>
                      {PLAN_LABELS[t.plan] ?? t.plan}
                    </span>
                  </td>
                  <td className="px-4 py-3 cursor-pointer" onClick={() => setSelectedId(t.id)}>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${t.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}>
                      {t.is_active ? 'Active' : 'Suspended'}
                    </span>
                  </td>
                  <td className="px-4 py-3 cursor-pointer" onClick={() => setSelectedId(t.id)}>
                    <span className="text-gray-700 font-medium">{t.feature_count}</span>
                    <span className="text-gray-400"> / 10</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <span
                        onClick={() => setSelectedId(t.id)}
                        className="text-primary text-xs font-medium hover:underline cursor-pointer"
                      >
                        Configure →
                      </span>
                      <button                        onClick={(e) => { e.stopPropagation(); setEditTenant(t) }}
                        className="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                        title="Edit tenant"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                      <button                        onClick={(e) => { e.stopPropagation(); setDeleteId(t.id) }}
                        className="p-1.5 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                        title="Delete tenant"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {tenants.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">No tenants found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteId && tenantToDelete && (
        <>
          <div className="fixed inset-0 z-40 bg-black/40" onClick={() => setDeleteId(null)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center flex-shrink-0">
                  <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                  </svg>
                </div>
                <div>
                  <h3 className="text-base font-semibold text-gray-900">Delete Tenant</h3>
                  <p className="text-sm text-gray-500 mt-0.5">This action cannot be undone.</p>
                </div>
              </div>
              <p className="text-sm text-gray-700">
                You are about to permanently delete <span className="font-semibold">{tenantToDelete.hospital_name}</span>.
                This will drop all patient data, tables, and users for schema <span className="font-mono text-xs bg-gray-100 px-1 rounded">{tenantToDelete.schema_name}</span>.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setDeleteId(null)}
                  className="flex-1 border border-gray-300 text-gray-700 text-sm py-2.5 rounded-lg font-medium hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={() => deleteTenant.mutate(deleteId)}
                  disabled={deleteTenant.isPending}
                  className="flex-1 bg-red-600 text-white text-sm py-2.5 rounded-lg font-medium hover:bg-red-700 disabled:opacity-60"
                >
                  {deleteTenant.isPending ? 'Deleting…' : 'Delete Permanently'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {selectedId && (
        <TenantDetailPanel
          tenantId={selectedId}
          onClose={() => setSelectedId(null)}
          onToast={showToast}
        />
      )}

      {editTenant && (
        <EditTenantModal
          tenant={editTenant}
          onClose={() => setEditTenant(null)}
          onToast={showToast}
        />
      )}

      {showCreate && (
        <CreateTenantModal
          onClose={() => setShowCreate(false)}
          onToast={showToast}
        />
      )}

      <ToastBanner toast={toast} />
    </div>
  )
}
