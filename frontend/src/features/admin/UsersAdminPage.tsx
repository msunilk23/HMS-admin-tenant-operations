/**
 * Admin — Manage Staff Users
 * hospital_admin can create / edit / deactivate non-doctor staff.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import type { StaffUser } from '@/types/common'
import { userService, departmentService } from '@/services/clinicalService'
import { nurseDeptService } from '@/services/nurseDeptService'

// ── Zod schemas ───────────────────────────────────────────────────────────────

const MANAGEABLE_ROLES = [
  'receptionist',
  'nurse',
  'billing_officer',
  'lab_technician',
  'pharmacist',
  'hospital_admin',
  'store_manager',
] as const

const ROLE_LABELS: Record<string, string> = {
  receptionist: 'Receptionist',
  nurse: 'Nurse',
  billing_officer: 'Billing Officer',
  lab_technician: 'Lab Technician',
  pharmacist: 'Pharmacist',
  hospital_admin: 'Hospital Admin',
  store_manager: 'Store Manager',
}

const createSchema = z.object({
  full_name: z.string().min(1, 'Name required'),
  role: z.enum(MANAGEABLE_ROLES, { required_error: 'Role required' }),
  phone: z
    .string()
    .length(10, 'Enter exactly 10 digits')
    .regex(/^[6-9]\d{9}$/, 'Enter a valid 10-digit Indian mobile number'),
  gender: z.enum(['male', 'female'], { required_error: 'Gender required' }),
  email: z.string().email('Valid email required').optional().or(z.literal('')),
  username: z
    .string()
    .min(3, 'Min 3 characters')
    .max(50)
    .regex(/^[a-z0-9_]+$/, 'Lowercase letters, digits, underscores only')
    .optional()
    .or(z.literal('')),
  send_via: z.enum(['sms', 'whatsapp']).default('sms'),
})
type CreateForm = z.infer<typeof createSchema>

const editSchema = z.object({
  full_name: z.string().min(1, 'Name required'),
})
type EditForm = z.infer<typeof editSchema>

// ── Small reusable UI ─────────────────────────────────────────────────────────

const StatusBadge = ({ active }: { active: boolean }) => (
  <span
    className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
      active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
    }`}
  >
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
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">
          ×
        </button>
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

const inputCls =
  'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary'

// ── Credentials modal (shown after creation) ──────────────────────────────────

interface CreatedCreds {
  full_name: string
  username: string
  password: string
  phone: string
}

function CredentialsModal({ creds, onClose }: { creds: CreatedCreds; onClose: () => void }) {
  return (
    <Modal title="User Created — Credentials Sent" onClose={onClose}>
      <p className="text-sm text-gray-600 mb-4">
        An SMS with login credentials has been sent to <strong>{creds.phone}</strong>.
      </p>
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-500">Full Name</span>
          <span className="font-medium text-gray-900">{creds.full_name}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Username</span>
          <span className="font-mono font-medium text-gray-900">{creds.username}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Password</span>
          <span className="font-mono font-medium text-gray-900">{creds.password}</span>
        </div>
      </div>
      <div className="flex justify-end pt-4">
        <button
          onClick={onClose}
          className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
        >
          Done
        </button>
      </div>
    </Modal>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function UsersAdminPage() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<StaffUser | null>(null)
  const [showInactive, setShowInactive] = useState(false)
  const [createdCreds, setCreatedCreds] = useState<CreatedCreds | null>(null)
  const [resetTarget, setResetTarget] = useState<StaffUser | null>(null)
  const [resetDone, setResetDone] = useState<{ phone: string; name: string } | null>(null)

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['staff-users', showInactive],
    queryFn: () => userService.list({ include_inactive: showInactive }),
  })

  const { data: departments = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['departments'],
    queryFn: () => departmentService.list(),
  })

  const { data: nurseAssignments = [] } = useQuery({
    queryKey: ['nurse-departments'],
    queryFn: () => nurseDeptService.list(),
  })

  const assignMut = useMutation({
    mutationFn: ({ userId, deptId }: { userId: string; deptId: string }) =>
      nurseDeptService.assign(userId, deptId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['nurse-departments'] }),
  })

  const unassignMut = useMutation({
    mutationFn: ({ userId, deptId }: { userId: string; deptId: string }) =>
      nurseDeptService.unassign(userId, deptId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['nurse-departments'] }),
  })

  const nurses = users.filter(u => u.role === 'nurse' && u.is_active)

  const createMut = useMutation({
    mutationFn: userService.create,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['staff-users'] })
      setShowCreate(false)
      setCreatedCreds({
        full_name: created.full_name,
        username: created.username,
        password: created.temp_password,
        phone: created.phone ?? '',
      })
    },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof userService.update>[1] }) =>
      userService.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['staff-users'] })
      setEditing(null)
    },
  })

  const resetPasswordMut = useMutation({
    mutationFn: (id: string) => userService.resetPassword(id),
    onSuccess: (data, id) => {
      const user = users.find(u => u.id === id)
      setResetTarget(null)
      setResetDone({ phone: data.phone, name: user?.full_name ?? '' })
    },
  })

  const createForm = useForm<CreateForm>({ resolver: zodResolver(createSchema), defaultValues: { send_via: 'whatsapp' } })
  const editForm = useForm<EditForm>({ resolver: zodResolver(editSchema) })

  const openEdit = (user: StaffUser) => {
    setEditing(user)
    editForm.reset({ full_name: user.full_name })
  }

  const onCreateSubmit = (data: CreateForm) => {
    createMut.mutate({ ...data, phone: `+91${data.phone}`, gender: data.gender, send_via: data.send_via, email: data.email || undefined })
  }

  const toggleActive = (user: StaffUser) =>
    updateMut.mutate({ id: user.id, data: { is_active: !user.is_active } })

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Manage Staff</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Create and manage hospital staff accounts
          </p>
        </div>
        <button
          onClick={() => { setShowCreate(true); createForm.reset() }}
          className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
        >
          + Add Staff
        </button>
      </div>

      {/* Toolbar */}
      <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer w-fit">
        <input
          type="checkbox"
          checked={showInactive}
          onChange={e => setShowInactive(e.target.checked)}
          className="rounded"
        />
        Show inactive users
      </label>

      {/* Table */}
      {isLoading ? (
        <p className="text-sm text-gray-500 py-8 text-center">Loading…</p>
      ) : users.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">No staff users found</p>
      ) : (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Full Name', 'Email', 'Username', 'Phone', 'Role', 'Status', 'Actions'].map(h => (
                  <th
                    key={h}
                    className={`px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide ${h === 'Actions' ? 'text-right w-48' : ''}`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {users.map(user => (
                <tr key={user.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{user.full_name}</td>
                  <td className="px-4 py-3 text-gray-500">{user.email}</td>
                  <td className="px-4 py-3 font-mono text-gray-600">{user.username}</td>
                  <td className="px-4 py-3 text-gray-500">{user.phone ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-600">
                    {ROLE_LABELS[user.role] ?? user.role}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge active={user.is_active} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5 justify-end">
                      <button
                        onClick={() => openEdit(user)}
                        title="Edit"
                        className="group p-1.5 rounded-lg border border-primary text-primary hover:bg-primary/10 relative"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                        <span className="absolute -top-7 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs rounded px-1.5 py-0.5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap">Edit</span>
                      </button>
                      <button
                        onClick={() => setResetTarget(user)}
                        title="Reset Password"
                        className="group p-1.5 rounded-lg border border-amber-400 text-amber-600 hover:bg-amber-50 relative"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                        </svg>
                        <span className="absolute -top-7 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs rounded px-1.5 py-0.5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap">Reset Password</span>
                      </button>
                      <button
                        onClick={() => toggleActive(user)}
                        title={user.is_active ? 'Deactivate' : 'Activate'}
                        className={`group p-1.5 rounded-lg border relative ${
                          user.is_active
                            ? 'border-red-300 text-red-600 hover:bg-red-50'
                            : 'border-green-400 text-green-600 hover:bg-green-50'
                        }`}
                      >
                        {user.is_active ? (
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                          </svg>
                        ) : (
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                        )}
                        <span className="absolute -top-7 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs rounded px-1.5 py-0.5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap">
                          {user.is_active ? 'Deactivate' : 'Activate'}
                        </span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Nurse Department Assignment */}
      {nurses.length > 0 && departments.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-800">Nurse — Department Assignment</h2>
            <p className="text-xs text-gray-400">Each nurse can manage multiple departments</p>
          </div>
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['Nurse', 'Assigned Departments', 'Add Department'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {nurses.map(nurse => {
                  const assigned: any[] = nurseAssignments.filter((a: any) => a.user_id === nurse.id)
                  const assignedIds = new Set(assigned.map((a: any) => a.department_id))
                  const unassigned = departments.filter((d: any) => !assignedIds.has(d.id))
                  return (
                    <tr key={nurse.id} className="hover:bg-gray-50 align-top">
                      <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">{nurse.full_name}</td>
                      <td className="px-4 py-3">
                        {assigned.length === 0 ? (
                          <span className="text-gray-400 italic text-xs">Unassigned</span>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            {assigned.map((a: any) => (
                              <span
                                key={a.department_id}
                                className="inline-flex items-center gap-1 bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-2 py-0.5 text-xs font-medium"
                              >
                                {departments.find((d: any) => d.id === a.department_id)?.name ?? a.department_id}
                                <button
                                  onClick={() => unassignMut.mutate({ userId: nurse.id, deptId: a.department_id })}
                                  className="hover:text-red-500 leading-none ml-0.5"
                                  title="Remove"
                                >
                                  ×
                                </button>
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {unassigned.length > 0 ? (
                          <select
                            value=""
                            onChange={e => {
                              if (e.target.value) assignMut.mutate({ userId: nurse.id, deptId: e.target.value })
                            }}
                            className="border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-primary/30"
                          >
                            <option value="">+ Add department…</option>
                            {unassigned.map((d: any) => (
                              <option key={d.id} value={d.id}>{d.name}</option>
                            ))}
                          </select>
                        ) : (
                          <span className="text-xs text-gray-400 italic">All departments assigned</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <Modal title="Add Staff Member" onClose={() => setShowCreate(false)}>
          <form onSubmit={createForm.handleSubmit(onCreateSubmit)} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <FormField
                label="Full Name"
                error={createForm.formState.errors.full_name?.message}
              >
                <input
                  {...createForm.register('full_name')}
                  className={inputCls}
                  placeholder="Priya Sharma"
                />
              </FormField>
              <FormField label="Role" error={createForm.formState.errors.role?.message}>
                <select {...createForm.register('role')} className={inputCls}>
                  <option value="">Select role…</option>
                  {MANAGEABLE_ROLES.map(r => (
                    <option key={r} value={r}>
                      {ROLE_LABELS[r]}
                    </option>
                  ))}
                </select>
              </FormField>
            </div>

            <div className="grid grid-cols-2 gap-4">
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
              <FormField label="Gender" error={createForm.formState.errors.gender?.message}>
                <select {...createForm.register('gender')} className={inputCls}>
                  <option value="">Select gender…</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                </select>
              </FormField>
            </div>

              <FormField label="Email (optional)" error={createForm.formState.errors.email?.message}>
              <input
                {...createForm.register('email')}
                type="email"
                className={inputCls}
                placeholder="priya@hospital.com"
              />
            </FormField>

            <FormField
              label="Username (optional — auto-generated if left blank)"
              error={createForm.formState.errors.username?.message}
            >
              <input
                {...createForm.register('username')}
                className={inputCls}
                placeholder="e.g. priya_sharma"
              />
            </FormField>

            <div>
              <p className="block text-sm font-medium text-gray-700 mb-1">Send credentials via</p>
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

            {createMut.isError && (
              <p className="text-xs text-red-500">
                {(createMut.error as { response?: { data?: { detail?: string } } })?.response?.data
                  ?.detail ?? 'Failed to create user. Please try again.'}
              </p>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createMut.isPending}
                className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {createMut.isPending ? 'Creating…' : 'Create Staff'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title="Edit Staff Member" onClose={() => setEditing(null)}>
          <form
            onSubmit={editForm.handleSubmit(data =>
              updateMut.mutate({ id: editing.id, data })
            )}
            className="space-y-4"
          >
            <FormField label="Full Name" error={editForm.formState.errors.full_name?.message}>
              <input {...editForm.register('full_name')} className={inputCls} />
            </FormField>
            <p className="text-xs text-gray-400">
              Role and email cannot be changed after creation.
            </p>

            {updateMut.isError && (
              <p className="text-xs text-red-500">
                {(updateMut.error as { response?: { data?: { detail?: string } } })?.response?.data
                  ?.detail ?? 'Failed to update user.'}
              </p>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
              >
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

      {/* Credentials modal */}
      {createdCreds && (
        <CredentialsModal creds={createdCreds} onClose={() => setCreatedCreds(null)} />
      )}

      {/* Reset Password — confirm modal */}
      {resetTarget && (
        <Modal title="Reset Password" onClose={() => setResetTarget(null)}>
          <p className="text-sm text-gray-600 mb-5">
            A new password will be generated and sent via SMS to{' '}
            <strong>{resetTarget.phone ?? 'the user\'s registered number'}</strong> for{' '}
            <strong>{resetTarget.full_name}</strong>.
          </p>
          {resetPasswordMut.isError && (
            <p className="text-xs text-red-500 mb-3">
              {(resetPasswordMut.error as { response?: { data?: { detail?: string } } })?.response
                ?.data?.detail ?? 'Failed to reset password. Please try again.'}
            </p>
          )}
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setResetTarget(null)}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
            >
              Cancel
            </button>
            <button
              disabled={resetPasswordMut.isPending}
              onClick={() => resetPasswordMut.mutate(resetTarget.id)}
              className="px-4 py-2 bg-amber-500 text-white rounded-lg text-sm font-medium hover:bg-amber-600 disabled:opacity-50"
            >
              {resetPasswordMut.isPending ? 'Resetting…' : 'Yes, Reset & Send SMS'}
            </button>
          </div>
        </Modal>
      )}

      {/* Reset Password — success modal */}
      {resetDone && (
        <Modal title="Password Reset" onClose={() => setResetDone(null)}>
          <p className="text-sm text-gray-600 mb-5">
            A new password has been sent via SMS to <strong>{resetDone.phone}</strong> for{' '}
            <strong>{resetDone.name}</strong>.
          </p>
          <div className="flex justify-end">
            <button
              onClick={() => setResetDone(null)}
              className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
            >
              Done
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
