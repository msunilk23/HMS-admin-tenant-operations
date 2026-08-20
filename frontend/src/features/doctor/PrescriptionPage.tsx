/**
 * Prescription Builder Page
 *
 * Route: /doctor/prescription/:visitId
 * Doctor adds medicines (name, dose, frequency, duration, route) + instructions
 * then saves → visit moves to prescription_done → billing queue
 */
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm, useFieldArray, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { visitService } from '@/services/visitService'
import { prescriptionService } from '@/services/clinicalService'

const PRESET_FREQUENCIES: { value: string; label: string }[] = [
  { value: 'OD',  label: 'OD — Once Daily' },
  { value: 'BD',  label: 'BD — Twice Daily' },
  { value: 'TID', label: 'TID — Three Times a Day' },
  { value: 'QID', label: 'QID — Four Times a Day' },
  { value: 'SOS', label: 'SOS — As Needed' },
  { value: 'QHS', label: 'QHS — Every Night at Bedtime' },
  { value: 'Q4H', label: 'Q4H — Every 4 Hours' },
  { value: 'Q6H', label: 'Q6H — Every 6 Hours' },
  { value: 'Q8H', label: 'Q8H — Every 8 Hours' },
]

const DOSE_OPTIONS = ['0', '½', '1', '2']
const SLOTS = ['M', 'A', 'E', 'N'] as const

/** Parses "1-0-1-0" → ['1','0','1','0']. Returns null if not in M-A-E-N format. */
function parseMaen(value: string): string[] | null {
  const parts = value.split('-')
  if (parts.length === 4 && parts.every(p => DOSE_OPTIONS.includes(p))) return parts
  return null
}

/**
 * M-A-E-N dosage picker. Renders four slot buttons (M / A / E / N)
 * each cycling through 0 → ½ → 1 → 2. The combined value is stored
 * as e.g. "1-0-1-0" in the form field.
 */
function DosagePicker({
  value,
  onChange,
}: {
  value: string
  onChange: (v: string) => void
}) {
  const parts = parseMaen(value) ?? ['1', '0', '1', '0']

  const cycle = (idx: number) => {
    const next = [...parts]
    const cur = DOSE_OPTIONS.indexOf(next[idx])
    next[idx] = DOSE_OPTIONS[(cur + 1) % DOSE_OPTIONS.length]
    onChange(next.join('-'))
  }

  return (
    <div className="flex items-center gap-1">
      {SLOTS.map((slot, idx) => (
        <button
          key={slot}
          type="button"
          onClick={() => cycle(idx)}
          className="flex flex-col items-center w-10 rounded-lg border border-gray-300 bg-gray-50 hover:bg-primary/10 hover:border-primary transition-colors py-1 select-none"
          title={`${slot}: click to change`}
        >
          <span className="text-[10px] font-semibold text-gray-400 leading-none">{slot}</span>
          <span className="text-sm font-bold text-gray-800 leading-tight mt-0.5">{parts[idx]}</span>
        </button>
      ))}
      <span className="text-xs text-gray-400 ml-1">{value}</span>
    </div>
  )
}
const ROUTES = ['oral', 'topical', 'IV', 'IM', 'SC', 'sublingual', 'inhaled', 'rectal']
const DURATIONS = ['1 day', '3 days', '5 days', '7 days', '10 days', '14 days', '1 month', 'Ongoing']

const FOOD_INSTRUCTIONS = ['Before Food', 'After Food', 'With Food', 'N/A'] as const

const medicineSchema = z.object({
  name: z.string().min(1, 'Drug name required'),
  dose: z.string().min(1, 'Dose required'),
  frequency: z.string().min(1, 'Frequency required'),
  food_instruction: z.enum(FOOD_INSTRUCTIONS).default('N/A'),
  duration: z.string().min(1, 'Duration required'),
  route: z.string().default('oral'),
  notes: z.string().optional(),
})

const labTestSchema = z.object({
  test_name: z.string().min(1, 'Test name required'),
  notes: z.string().optional(),
})

const rxSchema = z.object({
  medicines: z.array(medicineSchema),
  instructions: z.string().optional(),
  lab_tests: z.array(labTestSchema),
}).superRefine((data, ctx) => {
  if (data.medicines.length === 0 && data.lab_tests.length === 0) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: 'Add at least one medicine or one lab test',
      path: ['_form'],
    })
  }
})

type RxForm = z.infer<typeof rxSchema>

export default function PrescriptionPage() {
  const { visitId } = useParams<{ visitId: string }>()
  const navigate = useNavigate()
  // When the doctor comes back from here, we want to resume editing that consultation
  const backToConsultation = () => navigate('/doctor/consultation', { state: { resumeVisitId: visitId } })
  const qc = useQueryClient()

  const { data: visit } = useQuery({
    queryKey: ['visit', visitId],
    queryFn: () => visitService.get(visitId!),
    enabled: !!visitId,
  })

  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<RxForm>({
    resolver: zodResolver(rxSchema),
    defaultValues: { medicines: [], lab_tests: [] },
  })

  const { fields, append, remove } = useFieldArray({ control, name: 'medicines' })
  const { fields: labFields, append: appendLab, remove: removeLab } = useFieldArray({ control, name: 'lab_tests' })

  const { mutate: savePrescription, isPending } = useMutation({
    mutationFn: (data: RxForm) => prescriptionService.create({
      visit_id: visitId!,
      medicines: data.medicines,
      instructions: data.instructions,
      lab_tests: data.lab_tests?.length ? data.lab_tests : undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['visits'] })
      navigate('/doctor/consultation')
    },
  })

  return (
    <div className="p-6 max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Prescription Builder</h1>
          {visit && (
            <p className="text-sm text-gray-500 mt-0.5">
              Patient: <span className="font-medium text-gray-700">{visit.patient_name}</span>
            </p>
          )}
        </div>
        <button onClick={backToConsultation} className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </button>
      </div>

      <form onSubmit={handleSubmit(d => savePrescription(d))} className="space-y-5">
        {(errors as any)._form && (
          <p className="text-sm text-red-600 font-medium">{(errors as any)._form.message}</p>
        )}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">Medicines</h2>
            <button
              type="button"
              onClick={() => append({ name: '', dose: '', frequency: '1-0-1-0', food_instruction: 'N/A', duration: '5 days', route: 'oral' })}
              className="text-xs text-primary hover:underline font-medium flex items-center gap-1"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Medicine
            </button>
          </div>

          {errors.medicines?.root && (
            <p className="text-xs text-red-600 px-5 pt-2">{errors.medicines.root.message}</p>
          )}

          <div className="divide-y divide-gray-100">
            {fields.length === 0 ? (
              <p className="px-5 py-4 text-xs text-gray-400">No medicines added. Click "Add Medicine" to add.</p>
            ) : fields.map((field, i) => (
              <div key={field.id} className="px-5 py-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-400 uppercase">Medicine {i + 1}</span>
                  {fields.length > 1 && (
                    <button type="button" onClick={() => remove(i)} className="text-gray-400 hover:text-red-500">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Drug Name *</label>
                    <input
                      {...register(`medicines.${i}.name`)}
                      placeholder="e.g. Paracetamol 500mg"
                      className={rx_input(!!errors.medicines?.[i]?.name)}
                    />
                    {errors.medicines?.[i]?.name && (
                      <p className="text-xs text-red-600 mt-0.5">{errors.medicines[i]?.name?.message}</p>
                    )}
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Dose *</label>
                    <input {...register(`medicines.${i}.dose`)} placeholder="e.g. 500mg" className={rx_input(!!errors.medicines?.[i]?.dose)} />
                  </div>

                  <div className="col-span-2">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Frequency *</label>
                    <Controller
                      control={control}
                      name={`medicines.${i}.frequency`}
                      render={({ field }) => (
                        <FrequencyField value={field.value} onChange={field.onChange} />
                      )}
                    />
                  </div>

                  <div className="col-span-2">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Food Instruction</label>
                    <div className="flex flex-wrap gap-3">
                      {FOOD_INSTRUCTIONS.map(opt => (
                        <label key={opt} className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="radio"
                            value={opt}
                            {...register(`medicines.${i}.food_instruction`)}
                            className="accent-primary"
                          />
                          <span className="text-sm text-gray-700">{opt}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Duration *</label>
                    <select {...register(`medicines.${i}.duration`)} className={rx_input(false)}>
                      {DURATIONS.map(d => <option key={d} value={d}>{d}</option>)}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Route</label>
                    <select {...register(`medicines.${i}.route`)} className={rx_input(false)}>
                      {ROUTES.map(r => <option key={r} value={r} className="capitalize">{r}</option>)}
                    </select>
                  </div>

                  <div className="col-span-2">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Notes</label>
                    <input {...register(`medicines.${i}.notes`)} placeholder="e.g. Take after food" className={rx_input(false)} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Lab Tests */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">Lab Tests</h2>
            <button
              type="button"
              onClick={() => appendLab({ test_name: '', notes: '' })}
              className="text-xs text-primary hover:underline font-medium flex items-center gap-1"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Test
            </button>
          </div>

          {labFields.length === 0 ? (
            <p className="px-5 py-4 text-xs text-gray-400">No lab tests added. Click "Add Test" to add.</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {labFields.map((field, i) => (
                <div key={field.id} className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <input
                        {...register(`lab_tests.${i}.test_name`)}
                        placeholder="e.g. CBC, Blood Sugar, Urine Routine…"
                        className={rx_input(!!errors.lab_tests?.[i]?.test_name)}
                      />
                      {errors.lab_tests?.[i]?.test_name && (
                        <p className="text-xs text-red-600 mt-0.5">{errors.lab_tests[i]?.test_name?.message}</p>
                      )}
                    </div>
                    <div className="flex-1">
                      <input
                        {...register(`lab_tests.${i}.notes`)}
                        placeholder="Instructions / notes (optional)"
                        className={rx_input(false)}
                      />
                    </div>
                    <button type="button" onClick={() => removeLab(i)} className="text-gray-400 hover:text-red-500 shrink-0">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Instructions */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <label className="block text-sm font-semibold text-gray-700 mb-2">General Instructions</label>
          <textarea
            {...register('instructions')}
            rows={3}
            placeholder="Diet, rest, follow-up instructions for the patient…"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none"
          />
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button type="button" onClick={backToConsultation}
            className="border border-gray-300 text-gray-700 px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50">
            Back
          </button>
          <button type="submit" disabled={isPending}
            className="bg-primary text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-60">
            {isPending ? 'Saving…' : 'Save Prescription'}
          </button>
        </div>
      </form>
    </div>
  )
}

function rx_input(hasError: boolean) {
  return `w-full border ${hasError ? 'border-red-400' : 'border-gray-300'} rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary`
}

/**
 * Combined frequency field: preset dropdown OR M-A-E-N picker.
 * If the current value looks like M-A-E-N (e.g. "1-0-1-0"), shows the picker.
 * Otherwise shows a preset dropdown with an option to switch to M-A-E-N mode.
 */
function FrequencyField({
  value,
  onChange,
}: {
  value: string
  onChange: (v: string) => void
}) {
  const isMaen = parseMaen(value) !== null

  return (
    <div className="space-y-1.5">
      {isMaen ? (
        <div className="space-y-1">
          <DosagePicker value={value} onChange={onChange} />
          <button
            type="button"
            onClick={() => onChange('OD')}
            className="text-xs text-primary hover:underline"
          >
            Switch to preset
          </button>
        </div>
      ) : (
        <div className="space-y-1">
          <select value={value} onChange={e => onChange(e.target.value)} className={rx_input(false)}>
            {PRESET_FREQUENCIES.map(f => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => onChange('1-0-1-0')}
            className="text-xs text-primary hover:underline"
          >
            Use M-A-E-N dosage
          </button>
        </div>
      )}
    </div>
  )
}
