import { useState } from 'react'
import { useQueryClient, useMutation } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { patientService, type PatientCreate, type PatientDuplicateCandidate } from '@/services/patientService'
import type { Patient } from '@/types/common'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatAadhar(raw: string): string {
  const digits = raw.replace(/\D/g, '').slice(0, 12)
  return digits.replace(/(\d{4})(?=\d)/g, '$1-')
}

function calcAge(dob: string): number | null {
  if (!dob) return null
  const birth = new Date(dob)
  if (isNaN(birth.getTime())) return null
  const today = new Date()
  let age = today.getFullYear() - birth.getFullYear()
  const m = today.getMonth() - birth.getMonth()
  if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--
  return age < 0 ? 0 : age
}

const patientSchema = z.object({
  first_name: z.string().min(1, 'Required'),
  last_name: z.string().min(1, 'Required'),
  phone: z.string().min(10, 'Enter valid phone').max(15),
  gender: z.enum(['male', 'female', 'other']),
  dob: z.string().optional().refine(
    v => !v || new Date(v) <= new Date(),
    'Date of birth cannot be a future date'
  ),
  email: z.string().email('Invalid email').optional().or(z.literal('')),
  blood_group: z.string().optional(),
  address: z.string().optional(),
  insurance_provider: z.string().optional(),
  insurance_id: z.string().optional(),
  aadhar_number: z.string()
    .transform(v => v.replace(/-/g, ''))
    .pipe(z.string().length(12, 'Aadhar must be exactly 12 digits').regex(/^\d{12}$/, 'Only digits are allowed')),
  emergency_contact_name: z.string().optional(),
  emergency_contact_phone: z.string().optional(),
  emergency_contact_relation: z.string().optional(),
})

type FormValues = z.infer<typeof patientSchema>

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      {children}
      {error && <p className="text-xs text-red-600 mt-0.5">{error}</p>}
    </div>
  )
}

function inputCls(hasError: boolean) {
  return `w-full border ${hasError ? 'border-red-400' : 'border-gray-300'} rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 ${hasError ? 'focus:ring-red-200' : 'focus:ring-primary/30'} focus:border-primary`
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RegisterPatientModal({
  onClose,
  onSuccess,
  prefillPhone,
}: {
  onClose: () => void
  /** Called with the newly created patient after successful registration */
  onSuccess: (patient: Patient) => void
  /** Optionally pre-fill the phone field (e.g. from appointment search) */
  prefillPhone?: string
}) {
  const qc = useQueryClient()
  const [duplicates, setDuplicates] = useState<PatientDuplicateCandidate[] | null>(null)
  const [pendingValues, setPendingValues] = useState<PatientCreate | null>(null)

  const { mutate, isPending, error: createError } = useMutation({
    mutationFn: (data: PatientCreate) => patientService.create(data),
    onSuccess: (patient) => {
      qc.invalidateQueries({ queryKey: ['patients'] })
      onSuccess(patient)
    },
    onError: (err) => {
      const detail = (err as { response?: { status?: number; data?: { detail?: { duplicates?: PatientDuplicateCandidate[] } } } })?.response
      if (detail?.status === 409 && detail.data?.detail?.duplicates) {
        setDuplicates(detail.data.detail.duplicates)
      }
    },
  })

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(patientSchema),
    defaultValues: { phone: prefillPhone ?? '' },
  })

  const dobValue = watch('dob')
  const calculatedAge = dobValue ? calcAge(dobValue) : null
  const todayStr = new Date().toISOString().split('T')[0]

  const onSubmit = (values: FormValues) => {
    const data: PatientCreate = {
      ...values,
      email: values.email || undefined,
      dob: values.dob || undefined,
      age: calculatedAge ?? undefined,
    }
    setPendingValues(data)
    setDuplicates(null)
    mutate(data)
  }

  const confirmOverride = () => {
    if (!pendingValues) return
    setDuplicates(null)
    mutate({ ...pendingValues, override_duplicate: true })
  }

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-2xl overflow-y-auto max-h-[90vh]"
        onClick={e => e.stopPropagation()}
      >
        <div className="p-6 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Register New Patient</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {createError && !duplicates && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
              Registration failed. Please try again.
            </div>
          )}

          {duplicates && duplicates.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 space-y-3">
              <p className="text-sm font-medium text-amber-800">
                Possible duplicate patient{duplicates.length > 1 ? 's' : ''} found
              </p>
              <ul className="space-y-1.5">
                {duplicates.map(d => (
                  <li key={d.id} className="text-xs text-amber-800 bg-white rounded-lg border border-amber-100 px-3 py-2">
                    <span className="font-medium">{d.first_name} {d.last_name}</span>
                    <span className="ml-2 font-mono text-amber-600">{d.uhid}</span>
                    <span className="block text-amber-500 mt-0.5">
                      Matched on: {d.matched_on.join(', ')} · {d.phone}
                    </span>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setDuplicates(null)}
                  className="flex-1 border border-amber-300 text-amber-700 py-2 rounded-lg text-xs font-medium hover:bg-amber-100"
                >
                  Cancel — I'll search instead
                </button>
                <button
                  type="button"
                  disabled={isPending}
                  onClick={confirmOverride}
                  className="flex-1 bg-amber-600 text-white py-2 rounded-lg text-xs font-medium hover:bg-amber-700 disabled:opacity-60"
                >
                  {isPending ? 'Registering…' : 'Register anyway'}
                </button>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field label="First Name *" error={errors.first_name?.message}>
              <input {...register('first_name')} className={inputCls(!!errors.first_name)} placeholder="First name" />
            </Field>
            <Field label="Last Name *" error={errors.last_name?.message}>
              <input {...register('last_name')} className={inputCls(!!errors.last_name)} placeholder="Last name" />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Phone *" error={errors.phone?.message}>
              <input {...register('phone')} type="tel" className={inputCls(!!errors.phone)} placeholder="10-digit mobile" />
            </Field>
            <Field label="Gender *" error={errors.gender?.message}>
              <select {...register('gender')} className={inputCls(!!errors.gender)}>
                <option value="">Select gender</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
              </select>
            </Field>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <Field label="Date of Birth" error={errors.dob?.message}>
              <input
                {...register('dob')}
                type="date"
                max={todayStr}
                className={inputCls(!!errors.dob)}
              />
            </Field>
            <Field label="Age">
              <input
                type="text"
                readOnly
                value={calculatedAge !== null ? `${calculatedAge} yrs` : ''}
                placeholder="Auto-calculated"
                className={inputCls(false) + ' bg-gray-50 cursor-default text-gray-500'}
              />
            </Field>
            <Field label="Blood Group" error={errors.blood_group?.message}>
              <select {...register('blood_group')} className={inputCls(false)}>
                <option value="">Unknown</option>
                {['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'].map(bg => (
                  <option key={bg} value={bg}>{bg}</option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Aadhar Number *" error={errors.aadhar_number?.message}>
            <input
              {...register('aadhar_number')}
              className={inputCls(!!errors.aadhar_number)}
              placeholder="XXXX-XXXX-XXXX"
              maxLength={14}
              inputMode="numeric"
              onChange={e => {
                const formatted = formatAadhar(e.target.value)
                e.target.value = formatted
                setValue('aadhar_number', formatted, { shouldValidate: true })
              }}
            />
          </Field>

          <Field label="Email" error={errors.email?.message}>
            <input {...register('email')} type="email" className={inputCls(!!errors.email)} placeholder="patient@email.com" />
          </Field>

          <Field label="Address" error={errors.address?.message}>
            <textarea {...register('address')} rows={2} className={inputCls(false) + ' resize-none'} placeholder="Full address" />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Insurance Provider" error={errors.insurance_provider?.message}>
              <input {...register('insurance_provider')} className={inputCls(false)} placeholder="e.g. Star Health" />
            </Field>
            <Field label="Insurance ID" error={errors.insurance_id?.message}>
              <input {...register('insurance_id')} className={inputCls(false)} placeholder="Policy number" />
            </Field>
          </div>

          <div className="pt-1">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Emergency Contact</p>
            <div className="grid grid-cols-3 gap-4">
              <Field label="Name" error={errors.emergency_contact_name?.message}>
                <input {...register('emergency_contact_name')} className={inputCls(false)} placeholder="Contact name" />
              </Field>
              <Field label="Phone" error={errors.emergency_contact_phone?.message}>
                <input {...register('emergency_contact_phone')} type="tel" className={inputCls(false)} placeholder="10-digit mobile" />
              </Field>
              <Field label="Relation" error={errors.emergency_contact_relation?.message}>
                <input {...register('emergency_contact_relation')} className={inputCls(false)} placeholder="e.g. Spouse" />
              </Field>
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="flex-1 bg-primary text-white py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-60"
            >
              {isPending ? 'Registering…' : 'Register Patient'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
