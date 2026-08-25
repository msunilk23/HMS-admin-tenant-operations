/**
 * Admin — Doctors & Departments Management
 * Two tabs: Departments (CRUD) + Doctors (CRUD with dept association)
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import type { Department, Doctor } from '@/types/common'
import { departmentService, doctorService } from '@/services/clinicalService'

// ── Zod schemas ───────────────────────────────────────────────────────────────

const deptSchema = z.object({
  name: z.string().min(1, 'Name required'),
  description: z.string().optional(),
})
type DeptForm = z.infer<typeof deptSchema>

// Used for the Create (onboard) form — includes login credentials
const doctorOnboardSchema = z.object({
  email: z.string().email('Valid email required'),
  phone: z.string()
    .length(10, 'Enter exactly 10 digits')
    .regex(/^[6-9]\d{9}$/, 'Enter a valid 10-digit Indian mobile number'),
  username: z.string()
    .min(3, 'Min 3 characters')
    .max(50)
    .regex(/^[a-z0-9_]+$/, 'Lowercase letters, digits, underscores only')
    .optional()
    .or(z.literal('')),
  full_name: z.string().min(1, 'Name required'),
  specialization: z.string().min(1, 'Specialization required'),
  department_id: z.string().uuid().optional().or(z.literal('')),
  consultation_fee: z.coerce.number().min(0),
  qualification: z.string().optional(),
  experience_years: z.coerce.number().min(0).max(60).optional(),
  send_via: z.enum(['sms', 'whatsapp']).default('sms'),
  schedule_later: z.boolean().default(true),
  schedule_weekday: z.coerce.number().min(0).max(6).default(0),
  schedule_start: z.string().default('09:00'),
  schedule_end: z.string().default('13:00'),
  schedule_duration: z.coerce.number().min(5).max(240).default(15),
  schedule_capacity: z.coerce.number().min(1).max(100).default(1),
})

type DoctorOnboardForm = z.infer<typeof doctorOnboardSchema>

// Used for the Edit form — no credentials
const doctorEditSchema = z.object({
  full_name: z.string().min(1, 'Name required'),
  specialization: z.string().min(1, 'Specialization required'),
  department_id: z.string().uuid().optional().or(z.literal('')),
  consultation_fee: z.coerce.number().min(0),
  qualification: z.string().optional(),
  experience_years: z.coerce.number().min(0).max(60).optional(),
})
type DoctorEditForm = z.infer<typeof doctorEditSchema>

const StatusBadge = ({ active }: { active: boolean }) => (
  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
    active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
  }`}>
    {active ? 'Active' : 'Inactive'}
  </span>
)

const Modal = ({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
    <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4">
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
        <h2 className="text-base font-semibold text-gray-900">{title}</h2>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
      </div>
      <div className="px-6 py-5">{children}</div>
    </div>
  </div>
)

const FormField = ({
  label,
  error,
  children,
}: {
  label: string
  error?: string
  children: React.ReactNode
}) => (
  <div className="space-y-1">
    <label className="block text-sm font-medium text-gray-700">{label}</label>
    {children}
    {error && <p className="text-xs text-red-500">{error}</p>}
  </div>
)

const inputCls = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary'

function DoctorResetModal({ doctor, onClose }: { doctor: Doctor; onClose: () => void }) {
  const [reason, setReason] = useState('')
  const [sendVia, setSendVia] = useState<'sms' | 'whatsapp' | 'none'>('none')
  const [result, setResult] = useState<Awaited<ReturnType<typeof doctorService.resetPassword>> | null>(null)
  const reset = useMutation({ mutationFn: () => doctorService.resetPassword(doctor.id, reason.trim(), sendVia), onSuccess: setResult })
  return (
    <Modal title="Reset Doctor Password" onClose={onClose}>
      {result ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-700">The old sessions were terminated. The doctor must change this password at next login.</p>
          <div className="flex gap-2"><code className="flex-1 bg-gray-100 rounded px-3 py-2 font-mono select-all">{result.temporary_password}</code><button type="button" onClick={() => void navigator.clipboard.writeText(result.temporary_password)} className="bg-gray-900 text-white rounded px-3 text-sm">Copy</button></div>
          <p className="text-xs text-gray-500">Delivery: {result.delivery_status}. Phone: {result.phone ?? 'not registered'}.</p>
          <button type="button" onClick={onClose} className="w-full bg-primary text-white rounded-lg py-2 text-sm">Done</button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-gray-700"><strong>{doctor.full_name}</strong> · {doctor.username ?? 'No username'} · {doctor.phone ? `******${doctor.phone.slice(-4)}` : 'No phone'}</p>
          <textarea value={reason} onChange={e => setReason(e.target.value)} maxLength={500} rows={3} placeholder="Reason for reset (required)" className={inputCls} />
          <select value={sendVia} onChange={e => setSendVia(e.target.value as typeof sendVia)} className={inputCls}><option value="none">Display once only</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option></select>
          {reset.isError && <p className="text-xs text-red-600">Reset failed.</p>}
          <p className="text-xs text-amber-700 bg-amber-50 rounded px-3 py-2">Existing doctor sessions will be terminated. The doctor must change the password at next login.</p>
          <div className="flex gap-3"><button type="button" onClick={onClose} className="flex-1 border rounded-lg py-2 text-sm">Cancel</button><button type="button" disabled={reason.trim().length < 5 || reset.isPending} onClick={() => reset.mutate()} className="flex-1 bg-red-600 text-white rounded-lg py-2 text-sm disabled:opacity-50">{reset.isPending ? 'Resetting…' : 'Confirm Reset'}</button></div>
        </div>
      )}
    </Modal>
  )
}

// ── Departments Tab ────────────────────────────────────────────────────────────

function DepartmentsTab() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<Department | null>(null)
  const [showInactive, setShowInactive] = useState(false)

  const { data: depts = [], isLoading } = useQuery({
    queryKey: ['departments', showInactive],
    queryFn: () => departmentService.list(showInactive),
  })

  const createMut = useMutation({
    mutationFn: departmentService.create,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['departments'] }); setShowCreate(false) },
  })
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof departmentService.update>[1] }) =>
      departmentService.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['departments'] }); setEditing(null) },
  })

  const createForm = useForm<DeptForm>({ resolver: zodResolver(deptSchema) })
  const editForm = useForm<DeptForm>({ resolver: zodResolver(deptSchema) })

  const openEdit = (dept: Department) => {
    setEditing(dept)
    editForm.reset({ name: dept.name, description: dept.description ?? '' })
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-4">
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={e => setShowInactive(e.target.checked)}
            className="rounded"
          />
          Show inactive
        </label>
        <button
          onClick={() => { setShowCreate(true); createForm.reset() }}
          className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
        >
          + New Department
        </button>
      </div>

      {/* Table */}
      {isLoading ? (
        <p className="text-sm text-gray-500 py-8 text-center">Loading…</p>
      ) : depts.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">No departments found</p>
      ) : (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Name', 'Description', 'Status', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {depts.map(dept => (
                <tr key={dept.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{dept.name}</td>
                  <td className="px-4 py-3 text-gray-500">{dept.description ?? '—'}</td>
                  <td className="px-4 py-3"><StatusBadge active={dept.is_active} /></td>
                  <td className="px-4 py-3 text-right space-x-2">
                    <button
                      onClick={() => openEdit(dept)}
                      className="text-primary hover:underline text-xs"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => updateMut.mutate({ id: dept.id, data: { is_active: !dept.is_active } })}
                      className="text-gray-400 hover:text-gray-600 text-xs"
                    >
                      {dept.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <Modal title="New Department" onClose={() => setShowCreate(false)}>
          <form
            onSubmit={createForm.handleSubmit(data => createMut.mutate(data))}
            className="space-y-4"
          >
            <FormField label="Name" error={createForm.formState.errors.name?.message}>
              <input {...createForm.register('name')} className={inputCls} placeholder="e.g. Cardiology" />
            </FormField>
            <FormField label="Description">
              <textarea {...createForm.register('description')} rows={2} className={inputCls} />
            </FormField>
            <div className="flex justify-end gap-3 pt-2">
              <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
                Cancel
              </button>
              <button
                type="submit"
                disabled={createMut.isPending}
                className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {createMut.isPending ? 'Saving…' : 'Create'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title="Edit Department" onClose={() => setEditing(null)}>
          <form
            onSubmit={editForm.handleSubmit(data => updateMut.mutate({ id: editing.id, data }))}
            className="space-y-4"
          >
            <FormField label="Name" error={editForm.formState.errors.name?.message}>
              <input {...editForm.register('name')} className={inputCls} />
            </FormField>
            <FormField label="Description">
              <textarea {...editForm.register('description')} rows={2} className={inputCls} />
            </FormField>
            <div className="flex justify-end gap-3 pt-2">
              <button type="button" onClick={() => setEditing(null)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
                Cancel
              </button>
              <button
                type="submit"
                disabled={updateMut.isPending}
                className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {updateMut.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}

// ── Doctors Tab ────────────────────────────────────────────────────────────────

function DoctorsTab({ departments }: { departments: Department[] }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<Doctor | null>(null)
  const [showInactive, setShowInactive] = useState(false)
  const [createdCreds, setCreatedCreds] = useState<{
    username: string; email: string; phone: string; password: string; full_name: string
  } | null>(null)
  const [resetTarget, setResetTarget] = useState<Doctor | null>(null)

  const { data: doctors = [], isLoading } = useQuery({
    queryKey: ['doctors-admin', showInactive],
    queryFn: () => doctorService.list({ include_inactive: showInactive }),
  })

  const onboardMut = useMutation({
    mutationFn: doctorService.onboard,
    onSuccess: (doctor, vars) => {
      qc.invalidateQueries({ queryKey: ['doctors-admin'] })
      setShowCreate(false)
      setCreatedCreds({
        username: doctor.username ?? vars.full_name,
        email: vars.email,
        phone: vars.phone,
        password: doctor.temp_password,
        full_name: vars.full_name,
      })
    },
  })
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof doctorService.update>[1] }) =>
      doctorService.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['doctors-admin'] }); setEditing(null) },
  })

  const createForm = useForm<DoctorOnboardForm>({ resolver: zodResolver(doctorOnboardSchema), mode: 'onChange', defaultValues: { send_via: 'whatsapp', schedule_later: true, schedule_weekday: 0, schedule_start: '09:00', schedule_end: '13:00', schedule_duration: 15, schedule_capacity: 1 } })
  const editForm = useForm<DoctorEditForm>({ resolver: zodResolver(doctorEditSchema) })

  const openEdit = (doc: Doctor) => {
    setEditing(doc)
    editForm.reset({
      full_name: doc.full_name,
      specialization: doc.specialization,
      department_id: doc.department_id ?? '',
      consultation_fee: doc.consultation_fee,
      qualification: doc.qualification ?? '',
      experience_years: doc.experience_years ?? undefined,
    })
  }

  const deptMap: Record<string, string> = {}
  departments.forEach(d => { deptMap[d.id] = d.name })

  // Fields shared between create and edit.
  // Typed as the superset (OnboardForm); edit form is cast at the call site.
  const DoctorProfileFields = ({ form }: { form: ReturnType<typeof useForm<DoctorOnboardForm>> }) => (
    <>
      <div className="grid grid-cols-2 gap-4">
        <FormField label="Full Name" error={form.formState.errors.full_name?.message}>
          <input {...form.register('full_name')} className={inputCls} />
        </FormField>
        <FormField label="Specialization" error={form.formState.errors.specialization?.message}>
          <input {...form.register('specialization')} className={inputCls} />
        </FormField>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <FormField label="Department">
          <select {...form.register('department_id')} className={inputCls}>
            <option value="">— None —</option>
            {departments.map(d => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Consultation Fee (₹)" error={form.formState.errors.consultation_fee?.message}>
          <input {...form.register('consultation_fee')} type="number" min={0} className={inputCls} />
        </FormField>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <FormField label="Qualification">
          <input {...form.register('qualification')} className={inputCls} placeholder="MBBS, MD…" />
        </FormField>
        <FormField label="Experience (years)">
          <input {...form.register('experience_years')} type="number" min={0} max={60} className={inputCls} />
        </FormField>
      </div>
    </>
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={e => setShowInactive(e.target.checked)}
            className="rounded"
          />
          Show inactive
        </label>
        <button
          onClick={() => { setShowCreate(true); createForm.reset() }}
          className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
        >
          + Add Doctor
        </button>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-500 py-8 text-center">Loading…</p>
      ) : doctors.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">No doctors found</p>
      ) : (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Name', 'Specialization', 'Department', 'Fee', 'Exp.', 'Status', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {doctors.map(doc => (
                <tr key={doc.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {doc.full_name}
                    {doc.qualification && (
                      <span className="ml-1 text-xs text-gray-400">({doc.qualification})</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{doc.specialization}</td>
                  <td className="px-4 py-3 text-gray-500">
                    {doc.department_id ? (deptMap[doc.department_id] ?? '—') : '—'}
                  </td>
                  <td className="px-4 py-3 text-gray-600">₹{doc.consultation_fee}</td>
                  <td className="px-4 py-3 text-gray-500">
                    {doc.experience_years != null ? `${doc.experience_years}y` : '—'}
                  </td>
                  <td className="px-4 py-3"><StatusBadge active={doc.is_active} /></td>
                  <td className="px-4 py-3 text-right space-x-2">
                    <button onClick={() => openEdit(doc)} className="text-primary hover:underline text-xs">
                      Edit
                    </button>
                    <button onClick={() => navigate(`/admin/doctors/schedules?doctor_id=${doc.id}`)} className="text-blue-600 hover:underline text-xs">
                      Schedule
                    </button>
                    <button onClick={() => navigate(`/admin/doctors/schedules?doctor_id=${doc.id}&exception=1`)} className="text-amber-600 hover:underline text-xs">
                      Leave/Block
                    </button>
                    <button onClick={() => setResetTarget(doc)} className="text-red-600 hover:underline text-xs">
                      Reset Password
                    </button>
                    <button
                      onClick={() => updateMut.mutate({ id: doc.id, data: { is_active: !doc.is_active } })}
                      className="text-gray-400 hover:text-gray-600 text-xs"
                    >
                      {doc.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resetTarget && (
        <DoctorResetModal doctor={resetTarget} onClose={() => setResetTarget(null)} />
      )}

      {/* Create modal */}
      {showCreate && (
        <Modal title="Add Doctor" onClose={() => setShowCreate(false)}>
          <form
            onSubmit={createForm.handleSubmit(data =>
              onboardMut.mutate({
                ...data,
                phone: `+91${data.phone}`,
                department_id: data.department_id || undefined,
                experience_years: data.experience_years || undefined,
                qualification: data.qualification || undefined,
                username: data.username || undefined,
                send_via: data.send_via,
                schedule_later: data.schedule_later,
                schedules: data.schedule_later ? [] : [{
                  doctor_id: undefined,
                  department_id: data.department_id || undefined,
                  weekday: data.schedule_weekday,
                  start_time: data.schedule_start,
                  end_time: data.schedule_end,
                  slot_duration_minutes: data.schedule_duration,
                  capacity: data.schedule_capacity,
                  effective_from: null,
                  effective_to: null,
                  room: null,
                  appointment_type: 'consultation',
                  is_active: true,
                  notes: null,
                }],
              })
            )}
            className="space-y-4"
          >
            {/* Login credentials — only on create */}
            <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 space-y-3">
              <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide">Login Account</p>
              <div className="grid grid-cols-2 gap-4">
                <FormField label="Email" error={createForm.formState.errors.email?.message}>
                  <input {...createForm.register('email')} type="email" className={inputCls} placeholder="doctor@hospital.in" />
                </FormField>
                <FormField label="Phone" error={createForm.formState.errors.phone?.message}>
                  <div className="flex">
                    <span className="inline-flex items-center px-3 rounded-l-lg border border-r-0 border-gray-300 bg-gray-50 text-gray-500 text-sm select-none">
                      +91
                    </span>
                    <input
                      {...createForm.register('phone')}
                      type="tel"
                      maxLength={10}
                      className="w-full px-3 py-2 border border-gray-300 rounded-r-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                      placeholder="9876543210"
                      onKeyDown={e => { if (!/[0-9]|Backspace|Delete|Tab|ArrowLeft|ArrowRight/.test(e.key)) e.preventDefault() }}
                    />
                  </div>
                </FormField>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <FormField
                  label="Username (auto-generated if blank)"
                  error={createForm.formState.errors.username?.message}
                >
                  <input
                    {...createForm.register('username')}
                    className={inputCls}
                    placeholder="e.g. skredd03"
                    onChange={e => {
                      // Force lowercase as user types
                      e.target.value = e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '')
                      createForm.register('username').onChange(e)
                    }}
                  />
                </FormField>
              </div>
              <div>
                <p className="block text-sm font-medium text-blue-700 mb-1">Send credentials via</p>
                <div className="flex gap-4">
                  {(['sms', 'whatsapp'] as const).map(option => (
                    <label key={option} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        value={option}
                        {...createForm.register('send_via')}
                        className="accent-primary"
                      />
                      <span className="text-sm text-gray-700">{option === 'sms' ? 'SMS' : 'WhatsApp'}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <DoctorProfileFields form={createForm} />
            <div className="border border-gray-200 rounded-lg p-4 space-y-3">
              <label className="flex items-center gap-2 text-sm font-medium text-gray-700"><input type="checkbox" {...createForm.register('schedule_later')} /> Schedule later</label>
              {!createForm.watch('schedule_later') && <div className="grid grid-cols-2 gap-3"><FormField label="Working day"><select {...createForm.register('schedule_weekday')} className={inputCls}>{['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map((day, index) => <option key={day} value={index}>{day}</option>)}</select></FormField><FormField label="Slot duration"><input type="number" {...createForm.register('schedule_duration')} min={5} max={240} className={inputCls} /></FormField><FormField label="Start"><input type="time" {...createForm.register('schedule_start')} className={inputCls} /></FormField><FormField label="End"><input type="time" {...createForm.register('schedule_end')} className={inputCls} /></FormField><FormField label="Capacity"><input type="number" {...createForm.register('schedule_capacity')} min={1} max={100} className={inputCls} /></FormField></div>}
            </div>
            {onboardMut.isError && (
              <p className="text-xs text-red-600">
                {(onboardMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create doctor'}
              </p>
            )}
            <div className="flex justify-end gap-3 pt-2">
              <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 text-sm text-gray-600">Cancel</button>
              <button
                type="submit"
                disabled={onboardMut.isPending || !createForm.formState.isValid}
                className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {onboardMut.isPending ? 'Saving…' : 'Add Doctor'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title="Edit Doctor" onClose={() => setEditing(null)}>
          <form
            onSubmit={editForm.handleSubmit(data =>
              updateMut.mutate({
                id: editing.id,
                data: {
                  ...data,
                  department_id: data.department_id || undefined,
                },
              })
            )}
            className="space-y-4"
          >
            <DoctorProfileFields form={editForm as unknown as ReturnType<typeof useForm<DoctorOnboardForm>>} />
            <div className="flex justify-end gap-3 pt-2">
              <button type="button" onClick={() => setEditing(null)} className="px-4 py-2 text-sm text-gray-600">Cancel</button>
              <button
                type="submit"
                disabled={updateMut.isPending}
                className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {updateMut.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Credentials reveal modal — shown after a doctor is created */}
      {createdCreds && (
        <Modal title="✅ Doctor Created — Save These Credentials" onClose={() => setCreatedCreds(null)}>
          <div className="space-y-4">
            <p className="text-sm text-gray-600">
              Credentials for <strong>{createdCreds.full_name}</strong> have been sent via SMS to <strong>{createdCreds.phone}</strong>.
              A copy is shown below for your records.
            </p>
            <div className="bg-gray-50 border border-gray-200 rounded-lg divide-y divide-gray-200 text-sm">
              {([
                ['Full Name', createdCreds.full_name],
                ['Username', createdCreds.username],
                ['Email', createdCreds.email],
                ['Phone', createdCreds.phone],
                ['Password', createdCreds.password],
              ] as [string, string][]).map(([label, value]) => (
                <div key={label} className="flex items-center px-4 py-2.5 gap-4">
                  <span className="w-24 text-gray-500 flex-shrink-0">{label}</span>
                  <span className="font-mono font-medium text-gray-900 select-all">{value}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-amber-600">
              ⚠️ Ask the doctor to change their password on first login.
            </p>
            <div className="flex justify-end pt-1">
              <button
                onClick={() => setCreatedCreds(null)}
                className="px-5 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
              >
                Done
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DoctorsAdminPage() {
  const [tab, setTab] = useState<'departments' | 'doctors'>('departments')

  const { data: departments = [] } = useQuery({
    queryKey: ['departments', false],
    queryFn: () => departmentService.list(false),
  })

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Doctors & Departments</h1>
        <p className="text-sm text-gray-500 mt-0.5">Manage hospital departments and doctor profiles</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 mb-6">
        {(['departments', 'doctors'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-5 py-2.5 text-sm font-medium capitalize border-b-2 -mb-px transition-colors ${
              tab === t
                ? 'border-primary text-primary'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'departments' ? (
        <DepartmentsTab />
      ) : (
        <DoctorsTab departments={departments} />
      )}
    </div>
  )
}
