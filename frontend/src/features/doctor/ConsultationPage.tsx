/**
 * Doctor Consultation Page
 *
 * Shows: patient info, vitals summary, SOAP notes form, ICD-10 diagnosis
 * Handles visits with status "vitals_done" → moves to "in_consultation" when opened
 */
import { useState, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useLocation } from 'react-router-dom'
import { useForm, useFieldArray } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { visitService, vitalsService, consultationService } from '@/services/visitService'
import { patientService } from '@/services/patientService'
import { labService } from '@/services/labService'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { Visit, Vitals, PatientHistoryItem, Consultation } from '@/types/common'
import ClinicalAlertBanner from '@/components/shared/ClinicalAlertBanner'
import { masterDataService, type ICD10Code } from '@/services/masterDataService'

function PriorityBadge({ priority }: { priority?: string }) {
  if (!priority || priority === 'normal') return null
  if (priority === 'emergency')
    return <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold border border-red-200">🚨 Emergency</span>
  if (priority === 'senior_citizen')
    return <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold border border-amber-200">👴 Senior</span>
  return null
}

const COMPLETED_STATUSES = [
  'prescription_done',
  'dispatched_pharmacy',
  'dispatched_lab',
  'dispatched_both',
  'billing_pending',
  'closed',
] as const

const consultSchema = z.object({
  chief_complaint: z.string().min(1, 'Required'),
  history: z.string().optional(),
  examination: z.string().optional(),
  notes: z.string().optional(),
  follow_up_date: z.string().optional(),
  diagnoses: z.array(z.object({
    code: z.string(),
    description: z.string(),
    master_id: z.string().optional(),
    free_text: z.boolean().optional(),
  })).optional(),
  free_text_diagnosis_reason: z.string().optional(),
}).superRefine((data, ctx) => {
  if (data.diagnoses?.some(d => d.free_text) && !data.free_text_diagnosis_reason?.trim()) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['free_text_diagnosis_reason'], message: 'Reason is required for free-text diagnosis' })
  }
})

type ConsultForm = z.infer<typeof consultSchema>

function DiagnosisSelector({ index, value, setValue }: { index: number; value: string; setValue: (name: `diagnoses.${number}.${'code' | 'description' | 'master_id' | 'free_text'}`, value: string | boolean) => void }) {
  const [query, setQuery] = useState(value ?? '')
  const [freeText, setFreeText] = useState(false)
  const { data = [] } = useQuery({
    queryKey: ['icd10-search', query],
    queryFn: () => masterDataService.searchIcd10(query),
    enabled: query.trim().length >= 2 && !freeText,
    staleTime: 30_000,
  })
  return (
    <div className="flex-1 relative">
      <input
        value={query}
        onChange={e => { setQuery(e.target.value); setValue(`diagnoses.${index}.description`, e.target.value); setValue(`diagnoses.${index}.free_text`, freeText) }}
        placeholder={freeText ? 'Free-text diagnosis' : 'Search ICD-10 code or description'}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
      />
      <div className="flex gap-2 mt-1">
        <button type="button" className="text-xs text-primary hover:underline" onClick={() => { setFreeText(false); setValue(`diagnoses.${index}.free_text`, false) }}>Controlled ICD-10</button>
        <button type="button" className="text-xs text-amber-700 hover:underline" onClick={() => { setFreeText(true); setQuery(''); setValue(`diagnoses.${index}.code`, 'FREE_TEXT'); setValue(`diagnoses.${index}.description`, ''); setValue(`diagnoses.${index}.free_text`, true) }}>Free-text diagnosis</button>
      </div>
      {!freeText && data.length > 0 && (
        <div className="absolute z-10 left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-auto">
          {data.map((item: ICD10Code) => <button type="button" key={item.id} className="block w-full text-left px-3 py-2 hover:bg-blue-50 text-sm" onClick={() => { setQuery(`${item.code} — ${item.description}`); setValue(`diagnoses.${index}.code`, item.code); setValue(`diagnoses.${index}.description`, item.description); setValue(`diagnoses.${index}.master_id`, item.id); setValue(`diagnoses.${index}.free_text`, false) }}><strong>{item.code}</strong> — {item.description}</button>)}
        </div>
      )}
    </div>
  )
}

function ReportButton({ orderId }: { orderId: string }) {
  const [loading, setLoading] = useState(false)
  return (
    <button
      disabled={loading}
      onClick={async () => {
        setLoading(true)
        try {
          const url = await labService.getReportUrl(orderId)
          window.open(url, '_blank', 'noreferrer')
        } finally {
          setLoading(false)
        }
      }}
      className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline mt-2 disabled:opacity-50"
    >
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
      </svg>
      {loading ? 'Opening…' : 'View Report'}
    </button>
  )
}

export default function ConsultationPage() {
  const [selectedVisit, setSelectedVisit] = useState<Visit | null>(null)
  const [existingConsultation, setExistingConsultation] = useState<Consultation | null>(null)
  const [vitals, setVitals] = useState<Vitals | null>(null)
  const [completedOpen, setCompletedOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'consultation' | 'history'>('consultation')
  const qc = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()

  const { data: visits = [], refetch } = useQuery({
    queryKey: ['visits', 'vitals_done'],
    queryFn: () => visitService.list({ status: 'vitals_done' }),
    refetchInterval: 30_000,
  })

  // Visits where consultation is saved but prescription not yet written (doctor abandoned mid-flow)
  const { data: inConsultationVisits = [], refetch: refetchInConsultation } = useQuery({
    queryKey: ['visits', 'in_consultation'],
    queryFn: () => visitService.list({ status: 'in_consultation' }),
    refetchInterval: 30_000,
  })

  // Count of patients still being prepared by nurse
  const { data: preparingVisits = [] } = useQuery({
    queryKey: ['visits', 'vitals_recorded'],
    queryFn: () => visitService.list({ status: 'vitals_recorded' }),
    refetchInterval: 30_000,
  })

  // All statuses that come after consultation (completed for the day)
  const completedQueries = COMPLETED_STATUSES.map(status =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useQuery({
      queryKey: ['visits', status],
      queryFn: () => visitService.list({ status }),
      refetchInterval: 30_000,
    })
  )
  const todayStr = new Date().toLocaleDateString('en-CA')
  const completedVisits = completedQueries
    .flatMap(q => q.data ?? [])
    .filter(v => new Date(v.created_at).toLocaleDateString('en-CA') === todayStr)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  const { data: patientHistory = [], isFetching: historyLoading } = useQuery({
    queryKey: ['patient-history', selectedVisit?.patient_id],
    queryFn: () => patientService.getHistory(selectedVisit!.patient_id),
    enabled: !!selectedVisit && activeTab === 'history',
  })

  const onUpdate = useCallback(() => {
    refetch()
    refetchInConsultation()
    completedQueries.forEach(q => q.refetch())
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refetch, refetchInConsultation])

  useWebSocket('visit:update', onUpdate)

  const {
    register,
    handleSubmit,
    control,
    reset,
    setValue,
    watch,
    formState: { errors },
  } = useForm<ConsultForm>({ resolver: zodResolver(consultSchema) })

  const { fields: diagFields, append: appendDiag, remove: removeDiag } = useFieldArray({
    control,
    name: 'diagnoses',
  })

  const selectVisit = async (v: Visit) => {
    setSelectedVisit(v)
    setExistingConsultation(null)
    setActiveTab('consultation')
    reset()
    try {
      const vData = await vitalsService.get(v.id)
      setVitals(vData)
    } catch {
      setVitals(null)
    }
  }

  // Resume editing an already-saved consultation (coming back from PrescriptionPage)
  const resumeVisit = async (v: Visit) => {
    setSelectedVisit(v)
    setActiveTab('consultation')
    try {
      const [vData, consult] = await Promise.all([
        vitalsService.get(v.id).catch(() => null),
        consultationService.get(v.id).catch(() => null),
      ])
      setVitals(vData)
      setExistingConsultation(consult)
      reset({
        chief_complaint: consult?.chief_complaint ?? '',
        history: consult?.history ?? '',
        examination: consult?.examination ?? '',
        notes: consult?.notes ?? '',
        follow_up_date: consult?.follow_up_date ?? '',
        diagnoses: (consult?.diagnosis_icd10 as { code: string; description: string }[]) ?? [],
        free_text_diagnosis_reason: '',
      })
    } catch {
      setVitals(null)
      setExistingConsultation(null)
      reset()
    }
  }

  // Auto-resume when navigated back from PrescriptionPage
  useEffect(() => {
    const resumeId = (location.state as { resumeVisitId?: string } | null)?.resumeVisitId
    if (!resumeId) return
    // Find the visit in in_consultation list (already saved consultation, pending prescription)
    const match = inConsultationVisits.find(v => v.id === resumeId)
    if (!match) return
    // Clear navigation state so we don't retrigger on re-render
    window.history.replaceState({}, '')
    resumeVisit(match)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inConsultationVisits, location.state])

  const [callingIn, setCallingIn] = useState<string | null>(null)

  const callIn = async (v: Visit) => {
    setCallingIn(v.id)
    try {
      await visitService.updateStatus(v.id, 'in_consultation')
      qc.invalidateQueries({ queryKey: ['visits'] })
    } catch { /* ignore — form still opens */ }
    setCallingIn(null)
    await selectVisit(v)
  }

  const { mutate: saveConsultation, isPending, error: saveError } = useMutation({
    mutationFn: (data: ConsultForm) => {
      // If diagnoses is present but all entries are empty, treat as null
      let cleanedDiagnoses = data.diagnoses
      if (Array.isArray(cleanedDiagnoses)) {
        cleanedDiagnoses = cleanedDiagnoses.filter(d => d.code.trim() || d.description.trim())
        if (cleanedDiagnoses.length === 0) cleanedDiagnoses = undefined
      }
      const payload = {
        visit_id: selectedVisit!.id,
        chief_complaint: data.chief_complaint,
        history: data.history,
        examination: data.examination,
        notes: data.notes,
        follow_up_date: data.follow_up_date || undefined,
        diagnosis_icd10: cleanedDiagnoses,
        free_text_diagnosis_reason: data.free_text_diagnosis_reason,
      }
      // Use PATCH if consultation already exists (editing), POST if new
      return existingConsultation
        ? consultationService.update(selectedVisit!.id, payload)
        : consultationService.create(payload)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['visits'] })
      navigate(`/doctor/prescription/${selectedVisit!.id}`)
    },
  })

  return (
    <div className="p-6 space-y-6 flex gap-6">
      {/* Left: patient queue */}
      <div className="w-72 shrink-0 space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-700">
            Patients for Consultation
            {visits.length > 0 && (
              <span className="ml-1.5 text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded-full font-medium">
                {visits.length}
              </span>
            )}
          </h2>
          {preparingVisits.length > 0 && (
            <p className="text-xs text-amber-600 mt-0.5">
              ⏳ {preparingVisits.length} patient{preparingVisits.length > 1 ? 's' : ''} being prepared by nurse
            </p>
          )}
        </div>
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="divide-y divide-gray-100">
            {visits.length === 0 ? (
              <div className="p-6 text-center text-gray-400 text-sm">No patients waiting</div>
            ) : visits.map(v => (
              <div
                key={v.id}
                className={`px-4 py-3 text-sm border-l-2 transition-colors ${
                  selectedVisit?.id === v.id ? 'bg-blue-50 border-blue-500' : 'border-transparent hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2 flex-wrap">
                  {v.token_no && (
                    <span className="text-xs font-bold text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">#{v.token_no}</span>
                  )}
                  <span className="font-medium text-gray-900">{v.patient_name}</span>
                  <PriorityBadge priority={v.priority} />
                </div>
                <p className="text-xs text-gray-400 mt-0.5">{v.doctor_name ? `Dr. ${v.doctor_name}` : ''}
                  {v.department_name ? ` · ${v.department_name}` : ''}
                </p>
                <button
                  onClick={() => callIn(v)}
                  disabled={callingIn === v.id}
                  className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 bg-primary text-white rounded-lg text-xs font-medium hover:bg-primary/90 disabled:opacity-60"
                >
                  {callingIn === v.id ? (
                    'Calling…'
                  ) : (
                    <>
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                      </svg>
                      Call In
                    </>
                  )}
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Resume Prescription — consultation saved but prescription not yet written */}
        {inConsultationVisits.length > 0 && (
          <div className="bg-white rounded-xl border border-amber-200 overflow-hidden">
            <div className="px-4 py-2.5 bg-amber-50 border-b border-amber-200 flex items-center gap-2">
              <svg className="w-3.5 h-3.5 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
              <span className="text-xs font-semibold text-amber-700">Resume Prescription</span>
              <span className="ml-auto text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full font-medium">{inConsultationVisits.length}</span>
            </div>
            <div className="divide-y divide-amber-100">
              {inConsultationVisits.map(v => (
                <button
                  key={v.id}
                  onClick={() => resumeVisit(v)}
                  className={`w-full text-left px-4 py-3 hover:bg-amber-50 transition-colors text-sm ${
                    selectedVisit?.id === v.id ? 'bg-amber-50 border-l-2 border-amber-500' : ''
                  }`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    {v.token_no && (
                      <span className="text-xs font-bold text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">#{v.token_no}</span>
                    )}
                    <span className="font-medium text-gray-900">{v.patient_name}</span>
                    <PriorityBadge priority={v.priority} />
                  </div>
                  <p className="text-xs text-amber-600 mt-0.5">Consultation saved — click to edit &amp; write prescription</p>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Completed Today — expandable */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <button
            onClick={() => setCompletedOpen(o => !o)}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-700">Completed Today</span>
              <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">{completedVisits.length}</span>
            </div>
            <svg
              className={`w-4 h-4 text-gray-400 transition-transform ${completedOpen ? 'rotate-180' : ''}`}
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {completedOpen && (
            <div className="divide-y divide-gray-100 border-t border-gray-100">
              {completedVisits.length === 0 ? (
                <div className="p-4 text-center text-gray-400 text-xs">No completed consultations yet today</div>
              ) : completedVisits.map(v => (
                <div key={v.id} className="px-4 py-3">
                  <p className="font-medium text-gray-900 text-sm">{v.patient_name}</p>
                  <div className="flex items-center justify-between mt-0.5">
                    <p className="text-xs text-gray-400">{new Date(v.created_at).toLocaleTimeString()}</p>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${completedBadge(v.status)}`}>
                      {completedLabel(v.status)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right: consultation form */}
      <div className="flex-1 space-y-5">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-gray-900">
            {selectedVisit ? `Consultation — ${selectedVisit.patient_name}` : 'Doctor Consultation'}
          </h1>
          {selectedVisit && (
            <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm font-medium">
              <button
                onClick={() => setActiveTab('consultation')}
                className={`px-4 py-1.5 transition-colors ${activeTab === 'consultation' ? 'bg-primary text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              >
                Consultation
              </button>
              <button
                onClick={() => setActiveTab('history')}
                className={`px-4 py-1.5 transition-colors border-l border-gray-200 ${activeTab === 'history' ? 'bg-primary text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              >
                Patient History
              </button>
            </div>
          )}
        </div>

        {!selectedVisit ? (
          <div className="bg-white rounded-xl border border-gray-200 p-12 text-center text-gray-400">
            Select a patient from the list to begin consultation
          </div>
        ) : activeTab === 'history' ? (
          <PatientHistoryPanel history={patientHistory} loading={historyLoading} />
        ) : (
          <>
            <ClinicalAlertBanner patientId={selectedVisit.patient_id} />
            {/* Vitals summary */}
            {vitals && (
              <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-xl p-4">
                <h3 className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-3">Vitals</h3>
                <div className="grid grid-cols-4 gap-4">
                  <VitalChip label="BP" value={vitals.bp_systolic && vitals.bp_diastolic ? `${vitals.bp_systolic}/${vitals.bp_diastolic}` : '—'} unit="mmHg" />
                  <VitalChip label="Temp" value={vitals.temperature != null ? (Math.round((vitals.temperature * 9/5 + 32) * 10) / 10).toString() : '—'} unit="°F" />
                  <VitalChip label="SpO₂" value={vitals.spo2?.toString() ?? '—'} unit="%" />
                  <VitalChip label="Pulse" value={vitals.pulse?.toString() ?? '—'} unit="bpm" />
                  <VitalChip label="Weight" value={vitals.weight?.toString() ?? '—'} unit="kg" />
                  <VitalChip label="Height" value={vitals.height?.toString() ?? '—'} unit="cm" />
                </div>
              </div>
            )}

            {/* SOAP form */}
            <form onSubmit={handleSubmit(d => saveConsultation(d))} className="space-y-5 bg-white rounded-xl border border-gray-200 p-6">
              {saveError && <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">Unable to save consultation. Check the diagnosis selection and free-text reason.</p>}
              <SoapField label="Chief Complaint *" error={errors.chief_complaint?.message}>
                <textarea {...register('chief_complaint')} rows={2}
                  className={txtCls(!!errors.chief_complaint)}
                  placeholder="What brings the patient in today?" />
              </SoapField>

              <SoapField label="History of Present Illness">
                <textarea {...register('history')} rows={3}
                  className={txtCls(false)}
                  placeholder="Onset, duration, progression, associated symptoms…" />
              </SoapField>

              <SoapField label="Examination Findings">
                <textarea {...register('examination')} rows={3}
                  className={txtCls(false)}
                  placeholder="Physical examination observations…" />
              </SoapField>

              {/* ICD-10 Diagnoses */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm font-medium text-gray-700">ICD-10 Diagnosis</label>
                  <button type="button" onClick={() => appendDiag({ code: '', description: '' })}
                    className="text-xs text-primary hover:underline font-medium">
                    + Add Diagnosis
                  </button>
                </div>
                <div className="space-y-2">
                  {diagFields.map((field, i) => (
                    <div key={field.id} className="flex gap-2 items-start">
                      <input type="hidden" {...register(`diagnoses.${i}.code`)} />
                      <input type="hidden" {...register(`diagnoses.${i}.master_id`)} />
                      <input type="hidden" {...register(`diagnoses.${i}.free_text`)} />
                      <DiagnosisSelector index={i} value={[watch(`diagnoses.${i}.code`), watch(`diagnoses.${i}.description`)].filter(Boolean).join(' — ')} setValue={setValue} />
                      <button type="button" onClick={() => removeDiag(i)}
                        className="text-gray-400 hover:text-red-500 mt-2">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
                {diagFields.some((_, i) => watch(`diagnoses.${i}.free_text`)) && (
                  <textarea {...register('free_text_diagnosis_reason')} rows={2} placeholder="Reason for using free-text diagnosis (required)" className="mt-2 w-full border border-amber-300 rounded-lg px-3 py-2 text-sm bg-amber-50" />
                )}
              </div>

              <SoapField label="Clinical Notes / Instructions">
                <textarea {...register('notes')} rows={2}
                  className={txtCls(false)}
                  placeholder="Additional notes for the patient file…" />
              </SoapField>

              <SoapField label="Follow-up Date">
                <input {...register('follow_up_date')} type="date"
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 w-48" />
              </SoapField>

              <div className="flex gap-3 pt-2 border-t border-gray-100">
                <button type="button" onClick={() => setSelectedVisit(null)}
                  className="border border-gray-300 text-gray-700 px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50">
                  Cancel
                </button>
                <button type="submit" disabled={isPending}
                  className="bg-primary text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-60">
                  {isPending ? 'Saving…' : 'Save & Write Prescription →'}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  )
}

// ── Patient History Panel ────────────────────────────────────────────────────

function PatientHistoryPanel({ history, loading }: { history: PatientHistoryItem[]; loading: boolean }) {
  const [openVisit, setOpenVisit] = useState<string | null>(null)

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400 text-sm">
        Loading history…
      </div>
    )
  }

  // Filter out the current visit (today, active statuses)
  const pastVisits = history.filter(h => !['registered', 'vitals_recorded', 'vitals_done', 'in_consultation'].includes(h.status))

  if (pastVisits.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400 text-sm">
        No past visit records found for this patient.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {pastVisits.map(v => {
        const isOpen = openVisit === v.visit_id
        const date = new Date(v.visit_date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
        const diagnoses = v.consultation?.diagnosis_icd10 ?? []
        return (
          <div key={v.visit_id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {/* Visit header row */}
            <button
              onClick={() => setOpenVisit(isOpen ? null : v.visit_id)}
              className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center gap-4 text-left">
                <div>
                  <p className="text-sm font-semibold text-gray-800">{date}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {v.doctor_name ? `Dr. ${v.doctor_name}` : '—'}
                    {v.department_name ? ` · ${v.department_name}` : ''}
                  </p>
                </div>
                {v.consultation?.chief_complaint && (
                  <p className="text-sm text-gray-600 hidden sm:block truncate max-w-xs">
                    {v.consultation.chief_complaint}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${historyStatusBadge(v.status)}`}>
                  {historyStatusLabel(v.status)}
                </span>
                <svg className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                  fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </button>

            {isOpen && (
              <div className="border-t border-gray-100 px-5 py-4 space-y-4 text-sm">
                {/* Chief Complaint + Examination */}
                {(v.consultation?.chief_complaint || v.consultation?.examination) && (
                  <div className="grid grid-cols-2 gap-4">
                    {v.consultation.chief_complaint && (
                      <div>
                        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Chief Complaint</p>
                        <p className="text-gray-800">{v.consultation.chief_complaint}</p>
                      </div>
                    )}
                    {v.consultation.examination && (
                      <div>
                        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Examination</p>
                        <p className="text-gray-800">{v.consultation.examination}</p>
                      </div>
                    )}
                  </div>
                )}

                {/* Diagnoses */}
                {diagnoses.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Diagnoses</p>
                    <div className="flex flex-wrap gap-2">
                      {diagnoses.map((d, i) => (
                        <span key={i} className="bg-blue-50 text-blue-700 px-2.5 py-1 rounded-lg text-xs font-medium">
                          {d.code} — {d.description}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Medicines */}
                {v.medicines && v.medicines.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Prescription</p>
                    <table className="w-full text-xs border border-gray-100 rounded-lg overflow-hidden">
                      <thead className="bg-gray-50">
                        <tr>
                          {['Medicine', 'Dose', 'Frequency', 'Duration', 'Route'].map(h => (
                            <th key={h} className="px-3 py-2 text-left text-gray-500 font-medium">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {v.medicines.map((m, i) => (
                          <tr key={i} className="hover:bg-gray-50">
                            <td className="px-3 py-2 font-medium text-gray-800">{m.name}</td>
                            <td className="px-3 py-2 text-gray-600">{m.dose}</td>
                            <td className="px-3 py-2 text-gray-600">{m.frequency}</td>
                            <td className="px-3 py-2 text-gray-600">{m.duration}</td>
                            <td className="px-3 py-2 text-gray-600">{m.route}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {v.prescription_instructions && (
                      <p className="mt-1.5 text-xs text-gray-500 italic">Note: {v.prescription_instructions}</p>
                    )}
                  </div>
                )}

                {/* Lab Orders */}
                {v.lab_orders.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Lab</p>
                    <div className="space-y-2">
                      {v.lab_orders.map((lo, i) => (
                        <div key={i} className="border border-gray-100 rounded-lg p-3">
                          <div className="flex items-center justify-between mb-1.5">
                            <p className="text-xs font-medium text-gray-700">
                              {lo.tests?.map((t: { test: string }) => t.test).join(', ') || 'Lab tests'}
                            </p>
                            {lo.status === 'resulted'
                              ? <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-green-100 text-green-700">Results available</span>
                              : <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-gray-100 text-gray-500">Pending</span>
                            }
                          </div>
                          {lo.result?.results && (
                            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-2">
                              {Object.entries(lo.result.results).map(([k, val]) => (
                                <p key={k} className="text-xs text-gray-600">
                                  <span className="font-medium text-gray-700">{k}:</span> {String(val)}
                                </p>
                              ))}
                            </div>
                          )}
                          {lo.result?.report_url && lo.id && (
                            <ReportButton orderId={lo.id} />
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Notes */}
                {v.consultation?.notes && (
                  <div>
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Clinical Notes</p>
                    <p className="text-gray-700 bg-yellow-50 rounded-lg px-3 py-2">{v.consultation.notes}</p>
                  </div>
                )}

                {/* Follow-up */}
                {v.consultation?.follow_up_date && (
                  <p className="text-xs text-gray-500">
                    Follow-up: <span className="font-medium text-gray-700">{new Date(v.consultation.follow_up_date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</span>
                  </p>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function historyStatusLabel(status: string) {
  if (['dispatched_lab', 'dispatched_both'].includes(status)) return 'Lab Ordered'
  if (status === 'closed') return 'Closed'
  if (status === 'cancelled') return 'Cancelled'
  return 'Completed'
}

function historyStatusBadge(status: string) {
  if (['dispatched_lab', 'dispatched_both'].includes(status)) return 'bg-blue-100 text-blue-700'
  if (status === 'closed') return 'bg-green-100 text-green-700'
  if (status === 'cancelled') return 'bg-red-100 text-red-600'
  return 'bg-gray-100 text-gray-600'
}

function VitalChip({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="text-center">
      <p className="text-xs text-gray-500 mb-0.5">{label}</p>
      <p className="font-semibold text-gray-900">{value} <span className="text-xs text-gray-400 font-normal">{unit}</span></p>
    </div>
  )
}

function SoapField({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1.5">{label}</label>
      {children}
      {error && <p className="text-xs text-red-600 mt-0.5">{error}</p>}
    </div>
  )
}

function txtCls(hasError: boolean) {
  return `w-full border ${hasError ? 'border-red-400' : 'border-gray-300'} rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary resize-none`
}

function completedLabel(status: string) {
  const map: Record<string, string> = {
    prescription_done: 'Prescription Ready',
    dispatched_pharmacy: 'Pharmacy ✓',
    dispatched_lab: 'Lab ✓',
    dispatched_both: 'Pharmacy ✓ Lab ✓',
    billing_pending: 'Billing Pending',
    closed: 'Closed',
  }
  return map[status] ?? status
}

function completedBadge(status: string) {
  const map: Record<string, string> = {
    prescription_done: 'bg-purple-100 text-purple-700',
    dispatched_pharmacy: 'bg-orange-100 text-orange-700',
    dispatched_lab: 'bg-blue-100 text-blue-700',
    dispatched_both: 'bg-teal-100 text-teal-700',
    billing_pending: 'bg-yellow-100 text-yellow-700',
    closed: 'bg-green-100 text-green-700',
  }
  return map[status] ?? 'bg-gray-100 text-gray-600'
}
