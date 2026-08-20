/**
 * Nurse Station
 *
 * Two-column layout — always visible:
 * Left  – Awaiting Vitals: registered patients (click row to expand accordion vitals form)
 *          + vitals_recorded patients ready to send to doctor
 * Right – Dispatch Queue: prescription_done / dispatched_pharmacy (active)
 *          Completed Today (expandable): dispatched_lab / dispatched_both / billing_pending / closed
 */
import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { visitService, vitalsService, consultationService, type VitalsCreate } from '@/services/visitService'
import { nurseDeptService } from '@/services/nurseDeptService'
import { prescriptionService } from '@/services/clinicalService'
import { pharmacyService } from '@/services/pharmacyService'
import { useAuthStore } from '@/features/auth/authStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { printPrescription } from '@/utils/printPrescription'
import type { Visit } from '@/types/common'
import ClinicalAlertBanner from '@/components/shared/ClinicalAlertBanner'

function PriorityBadge({ priority }: { priority?: string }) {
  if (!priority || priority === 'normal') return null
  if (priority === 'emergency')
    return <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold border border-red-200">🚨 Emergency</span>
  if (priority === 'senior_citizen')
    return <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold border border-amber-200">👴 Senior</span>
  return null
}

const vitalsSchema = z.object({
  bp_systolic: z.coerce.number().int().min(40).max(300).optional().or(z.literal('')),
  bp_diastolic: z.coerce.number().int().min(20).max(200).optional().or(z.literal('')),
  temperature: z.coerce.number().min(86).max(113.9).optional().or(z.literal('')),
  weight: z.coerce.number().min(1).max(500).optional().or(z.literal('')),
  height: z.coerce.number().min(30).max(250).optional().or(z.literal('')),
  spo2: z.coerce.number().int().min(1).max(100).optional().or(z.literal('')),
  pulse: z.coerce.number().int().min(20).max(300).optional().or(z.literal('')),
})

type VitalsForm = z.infer<typeof vitalsSchema>

export default function NurseVitalsPage() {
  const [selectedVisit, setSelectedVisit] = useState<Visit | null>(null)
  const [prescriptionVisitId, setPrescriptionVisitId] = useState<string | null>(null)
  const [activeDeptId, setActiveDeptId] = useState<string | undefined>(undefined)
  const [dispatchConfirm, setDispatchConfirm] = useState<{
    visitId: string; action: 'pharmacy' | 'lab'; patientName: string
  } | null>(null)
  const [closingVisit, setClosingVisit] = useState<Visit | null>(null)
  const [additionalBilling, setAdditionalBilling] = useState(false)
  const [completedOpen, setCompletedOpen] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const hospitalName = useAuthStore(s => s.user?.hospitalName ?? s.user?.tenantSchema ?? 'Hospital')

  // Pre-fetch prescription + consultation when close modal opens
  const { data: closingPrescription } = useQuery({
    queryKey: ['prescription', closingVisit?.id],
    queryFn: () => prescriptionService.get(closingVisit!.id),
    enabled: !!closingVisit?.id,
  })
  const { data: closingConsultation } = useQuery({
    queryKey: ['consultation', closingVisit?.id],
    queryFn: () => consultationService.get(closingVisit!.id),
    enabled: !!closingVisit?.id,
  })

  // Fetch all departments this nurse is assigned to
  const { data: myDepts = [] } = useQuery<import('@/types/common').NurseDepartment[]>({
    queryKey: ['my-departments'],
    queryFn: () => nurseDeptService.myDepartments(),
    retry: false,
  })

  const deptId = myDepts.length === 1 ? myDepts[0].department_id : activeDeptId

  const { data: registeredVisits = [], refetch: refetchRegistered } = useQuery({
    queryKey: ['visits', 'registered', deptId],
    queryFn: () => visitService.list({ status: 'registered', department_id: deptId }),
    refetchInterval: 30_000,
  })

  // ── Dispatch tab queries ─────────────────────────────────────────────────────
  const { data: prescriptionDoneVisits = [], refetch: refetchPrescription } = useQuery({
    queryKey: ['visits', 'prescription_done', deptId],
    queryFn: () => visitService.list({ status: 'prescription_done', department_id: deptId }),
    refetchInterval: 30_000,
  })

  const { data: dispatchedPharmacyVisits = [], refetch: refetchPharmacy } = useQuery({
    queryKey: ['visits', 'dispatched_pharmacy', deptId],
    queryFn: () => visitService.list({ status: 'dispatched_pharmacy', department_id: deptId }),
    refetchInterval: 30_000,
  })

  const { data: dispatchedLabVisits = [], refetch: refetchLab } = useQuery({
    queryKey: ['visits', 'dispatched_lab', deptId],
    queryFn: () => visitService.list({ status: 'dispatched_lab', department_id: deptId }),
    refetchInterval: 30_000,
  })

  const { data: dispatchedBothVisits = [], refetch: refetchBoth } = useQuery({
    queryKey: ['visits', 'dispatched_both', deptId],
    queryFn: () => visitService.list({ status: 'dispatched_both', department_id: deptId }),
    refetchInterval: 30_000,
  })

  const { data: billingPendingVisits = [], refetch: refetchBillingPending } = useQuery({
    queryKey: ['visits', 'billing_pending', deptId],
    queryFn: () => visitService.list({ status: 'billing_pending', department_id: deptId }),
    refetchInterval: 30_000,
  })

  const { data: closedVisits = [], refetch: refetchClosed } = useQuery({
    queryKey: ['visits', 'closed', deptId],
    queryFn: () => visitService.list({ status: 'closed', department_id: deptId }),
    refetchInterval: 30_000,
  })

  // Pharmacy queue — fetch active items to show status in dispatch cards
  const { data: pharmacyQueue = [], refetch: refetchPharmacyQueue } = useQuery({
    queryKey: ['pharmacy-queue', 'active'],
    queryFn: () => pharmacyService.list(),
    refetchInterval: 20_000,
  })
  // Map visitId → pharmacy status for quick lookup
  const pharmacyStatusByVisit = Object.fromEntries(
    pharmacyQueue
      .filter(pq => pq.visit_id)
      .map(pq => [String(pq.visit_id), pq.status])
  )

  // Prescription for the selected dispatch visit
  const { data: prescription } = useQuery({
    queryKey: ['prescription', prescriptionVisitId],
    queryFn: () => prescriptionService.get(prescriptionVisitId!),
    enabled: !!prescriptionVisitId,
  })

  // Active dispatch queue: prescription ready or pharmacy dispatched (lab not yet done)
  const dispatchVisits = [...prescriptionDoneVisits, ...dispatchedPharmacyVisits]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())

  const todayStr = new Date().toLocaleDateString('en-CA') // YYYY-MM-DD in local time

  // Completed: lab dispatched, both dispatched, closed, or sent to billing — today only
  const completedVisits = [...dispatchedLabVisits, ...dispatchedBothVisits, ...billingPendingVisits, ...closedVisits]
    .filter(v => new Date(v.created_at).toLocaleDateString('en-CA') === todayStr)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  const onUpdate = useCallback(() => {
    refetchRegistered()
    refetchPrescription()
    refetchPharmacy()
    refetchLab()
    refetchBoth()
    refetchBillingPending()
    refetchClosed()
    refetchPharmacyQueue()
  }, [refetchRegistered, refetchPrescription, refetchPharmacy, refetchLab, refetchBoth, refetchBillingPending, refetchClosed, refetchPharmacyQueue])

  useWebSocket('visit:update', onUpdate)
  useWebSocket('queue:update', onUpdate)
  useWebSocket('pharmacy:update', onUpdate)

  const { register, handleSubmit, reset, control, formState: { errors } } = useForm<VitalsForm>({
    resolver: zodResolver(vitalsSchema),
  })

  // Live BMI computation
  const watchWeight = useWatch({ control, name: 'weight' })
  const watchHeight = useWatch({ control, name: 'height' })
  const liveBmi = (() => {
    const w = Number(watchWeight)
    const h = Number(watchHeight)
    if (!w || !h || h <= 0) return null
    return Math.round((w / Math.pow(h / 100, 2)) * 10) / 10
  })()
  const bmiCategory = (bmi: number) => {
    if (bmi < 18.5) return { label: 'Underweight', cls: 'bg-blue-100 text-blue-700 border-blue-200' }
    if (bmi < 25)   return { label: 'Normal',      cls: 'bg-green-100 text-green-700 border-green-200' }
    if (bmi < 30)   return { label: 'Overweight',  cls: 'bg-yellow-100 text-yellow-700 border-yellow-200' }
    return              { label: 'Obese',          cls: 'bg-red-100 text-red-700 border-red-200' }
  }

  // Save vitals → automatically sends patient to doctor queue (vitals_done)
  const { mutate: submitVitals, isPending, error: vitalsError } = useMutation({
    mutationFn: (data: VitalsCreate) => vitalsService.record(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['visits'] })
      setSelectedVisit(null)
      reset()
    },
  })

  // Dispatch to pharmacy or lab (confirmed via modal)
  const { mutate: dispatch, isPending: dispatching } = useMutation({
    mutationFn: ({ visitId, action }: { visitId: string; action: 'pharmacy' | 'lab' }) =>
      visitService.dispatch(visitId, action),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['visits'] })
      setDispatchConfirm(null)
      setPrescriptionVisitId(null)
    },
  })

  // Close visit or send to billing (optional additional billing checkbox)
  const { mutate: closeVisit, isPending: closing } = useMutation({
    mutationFn: ({ visitId, billing }: { visitId: string; billing: boolean }) =>
      visitService.dispatch(visitId, billing ? 'billing' : 'close'),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['visits'] })
      setClosingVisit(null)
      setAdditionalBilling(false)
      if (vars.billing) navigate(`/billing?visitId=${vars.visitId}&returnTo=nurse`)
    },
  })

  const handleCloseAndPrint = () => {
    if (!closingVisit) return
    printPrescription(closingVisit, closingPrescription ?? null, closingConsultation ?? null, hospitalName)
    closeVisit({ visitId: closingVisit.id, billing: false })
  }

  const onSubmit = (values: VitalsForm) => {
    if (!selectedVisit) return
    const clean = (v: number | string | undefined) =>
      v === '' || v === undefined ? undefined : Number(v)
    submitVitals({
      visit_id: selectedVisit.id,
      bp_systolic: clean(values.bp_systolic),
      bp_diastolic: clean(values.bp_diastolic),
      temperature: clean(values.temperature) !== undefined
        ? Math.round(((clean(values.temperature)! - 32) * 5 / 9) * 10) / 10
        : undefined,
      weight: clean(values.weight),
      height: clean(values.height),
      spo2: clean(values.spo2),
      pulse: clean(values.pulse),
    })
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Nurse Station</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {myDepts.length === 0
              ? 'No department assigned'
              : myDepts.length === 1
              ? `Department: ${myDepts[0].department_name}`
              : `${myDepts.length} departments assigned`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {myDepts.length > 1 && (
            <select
              value={activeDeptId ?? ''}
              onChange={e => { setActiveDeptId(e.target.value || undefined); setSelectedVisit(null) }}
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            >
              <option value="">All departments</option>
              {myDepts.map(d => (
                <option key={d.department_id} value={d.department_id}>{d.department_name}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* LEFT: Vitals */}
        <div className="space-y-4">
          {/* Awaiting Vitals — inline accordion form */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
              <h2 className="text-sm font-semibold text-gray-700">Awaiting Vitals ({registeredVisits.length})</h2>
            </div>
            <div className="divide-y divide-gray-100">
              {registeredVisits.length === 0 ? (
                <div className="p-8 text-center text-gray-400">
                  <svg className="w-10 h-10 mx-auto mb-2 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  All caught up!
                </div>
              ) : registeredVisits.map(v => (
                <div key={v.id}>
                  <button
                    onClick={() => { setSelectedVisit(selectedVisit?.id === v.id ? null : v); reset() }}
                    className={`w-full text-left px-4 py-3 hover:bg-blue-50 transition-colors ${
                      selectedVisit?.id === v.id ? 'bg-blue-50 border-l-2 border-blue-500' : ''
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          {v.token_no && (
                            <span className="text-xs font-bold text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                              #{v.token_no}
                            </span>
                          )}
                          <p className="font-medium text-gray-900 text-sm">{v.patient_name || 'Patient'}</p>
                          <PriorityBadge priority={v.priority} />
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {v.department_name || ''}{v.department_name ? ' · ' : ''}{v.doctor_name ? `Dr. ${v.doctor_name}` : 'Unassigned'} · {new Date(v.created_at).toLocaleTimeString()}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">Waiting</span>
                        <svg
                          className={`w-4 h-4 text-gray-400 transition-transform ${selectedVisit?.id === v.id ? 'rotate-180' : ''}`}
                          fill="none" stroke="currentColor" viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>
                    </div>
                  </button>
                  {selectedVisit?.id === v.id && (
                    <form onSubmit={handleSubmit(onSubmit)} className="px-5 pb-5 pt-3 bg-blue-50 border-t border-blue-100 space-y-4">
                      <ClinicalAlertBanner patientId={v.patient_id} />
                      {vitalsError && (
                        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
                          Failed to save vitals. Please try again.
                        </div>
                      )}
                      <div className="grid grid-cols-2 gap-3">
                        <VitalField label="Systolic BP (mmHg)" error={errors.bp_systolic?.message}>
                          <input {...register('bp_systolic')} type="number" placeholder="120" className={inputCls(false)} />
                        </VitalField>
                        <VitalField label="Diastolic BP (mmHg)" error={errors.bp_diastolic?.message}>
                          <input {...register('bp_diastolic')} type="number" placeholder="80" className={inputCls(false)} />
                        </VitalField>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <VitalField label="Temperature (°F)" error={errors.temperature?.message}>
                          <input {...register('temperature')} type="number" step="0.1" placeholder="98.6" className={inputCls(false)} />
                        </VitalField>
                        <VitalField label="SpO₂ (%)" error={errors.spo2?.message}>
                          <input {...register('spo2')} type="number" placeholder="98" className={inputCls(false)} />
                        </VitalField>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <VitalField label="Pulse (bpm)" error={errors.pulse?.message}>
                          <input {...register('pulse')} type="number" placeholder="72" className={inputCls(false)} />
                        </VitalField>
                        <VitalField label="Weight (kg)" error={errors.weight?.message}>
                          <input {...register('weight')} type="number" step="0.1" placeholder="70" className={inputCls(!!errors.weight)} />
                        </VitalField>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <VitalField label="Height (cm)" error={errors.height?.message}>
                          <input {...register('height')} type="number" step="0.1" placeholder="170" className={inputCls(!!errors.height)} />
                        </VitalField>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1">BMI (auto-calculated)</label>
                          {liveBmi !== null ? (
                            <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm font-semibold ${bmiCategory(liveBmi).cls}`}>
                              <span className="text-base">{liveBmi}</span>
                              <span className="text-xs font-medium">{bmiCategory(liveBmi).label}</span>
                            </div>
                          ) : (
                            <div className="px-3 py-2 rounded-lg border border-dashed border-gray-300 text-xs text-gray-400">
                              Enter weight &amp; height
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-3 pt-1">
                        <button type="button" onClick={() => { setSelectedVisit(null); reset() }}
                          className="flex-1 border border-gray-300 text-gray-700 py-2 rounded-lg text-sm font-medium hover:bg-white">
                          Cancel
                        </button>
                        <button type="submit" disabled={isPending}
                          className="flex-1 bg-primary text-white py-2 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-60">
                          {isPending ? 'Saving…' : 'Save Vitals'}
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              ))}
            </div>
          </div>

        </div>

        {/* RIGHT: Dispatch Queue + Completed */}
        <div className="space-y-4">
          <div className="px-1 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">Dispatch Queue ({dispatchVisits.length})</h2>
          </div>
          {dispatchVisits.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400">
              No patients awaiting dispatch
            </div>
          ) : dispatchVisits.map(v => {
            const canPharmacy = v.status === 'prescription_done' || v.status === 'dispatched_lab'
            const canLab = (v.status === 'prescription_done' || v.status === 'dispatched_pharmacy') && v.has_lab_order === true
            const badge = statusBadge(v.status)
            return (
              <div key={v.id} className="bg-white rounded-xl border border-gray-200 p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="font-semibold text-gray-900">{v.patient_name || 'Patient'}</p>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${badge.color}`}>
                        {badge.label}
                      </span>
                      {v.status === 'dispatched_pharmacy' && pharmacyStatusByVisit[v.id] && (
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${pharmacyStatusChip(pharmacyStatusByVisit[v.id])}`}>
                          💊 {pharmacyStatusLabel(pharmacyStatusByVisit[v.id])}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {v.doctor_name ? `Dr. ${v.doctor_name}` : ''} · {v.department_name || ''} · {new Date(v.created_at).toLocaleTimeString()}
                    </p>
                  </div>
                  <button
                    onClick={() => setPrescriptionVisitId(prescriptionVisitId === v.id ? null : v.id)}
                    className="text-xs text-blue-600 hover:underline shrink-0"
                  >
                    {prescriptionVisitId === v.id ? 'Hide Prescription' : 'View Prescription'}
                  </button>
                </div>

                {prescriptionVisitId === v.id && prescription && (
                  <div className="mt-3 bg-gray-50 rounded-lg p-3 text-sm space-y-2">
                    {(prescription.instructions || prescription.notes) && (
                      <p><span className="font-medium text-gray-700">Notes:</span> {prescription.instructions || prescription.notes}</p>
                    )}
                    {prescription.medicines?.length > 0 && (
                      <div>
                        <p className="font-medium text-gray-700 mb-1">Medicines ({prescription.medicines.length}):</p>
                        <ul className="space-y-0.5 text-gray-600">
                          {prescription.medicines.map((m: any, i: number) => (
                            <li key={i} className="text-xs">• {m.name} {m.dosage || m.dose} — {m.frequency} × {m.duration}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {(prescription.lab_tests ?? []).length > 0 && (
                      <div>
                        <p className="font-medium text-gray-700 mb-1">Lab Tests ({(prescription.lab_tests ?? []).length}):</p>
                        <ul className="space-y-0.5 text-gray-600">
                          {(prescription.lab_tests ?? []).map((t: any, i: number) => (
                            <li key={i} className="text-xs">• {t.test_name}{t.notes ? ` (${t.notes})` : ''}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex flex-wrap gap-2 mt-4 pt-3 border-t border-gray-100 items-center">
                  <span className="text-xs text-gray-500 mr-1">Dispatch to:</span>
                  {canPharmacy && (
                    <button
                      onClick={() => setDispatchConfirm({ visitId: v.id, action: 'pharmacy', patientName: v.patient_name || 'Patient' })}
                      className="px-3 py-1.5 rounded-lg bg-orange-50 text-orange-700 text-xs font-medium hover:bg-orange-100 border border-orange-200"
                    >
                      → Pharmacy
                    </button>
                  )}
                  {canLab && (
                    <button
                      onClick={() => setDispatchConfirm({ visitId: v.id, action: 'lab', patientName: v.patient_name || 'Patient' })}
                      className="px-3 py-1.5 rounded-lg bg-purple-50 text-purple-700 text-xs font-medium hover:bg-purple-100 border border-purple-200"
                    >
                      → Lab
                    </button>
                  )}
                  <div className="flex-1" />
                  <button
                    onClick={() => { setClosingVisit(v); setAdditionalBilling(false) }}
                    className="px-3 py-1.5 rounded-lg bg-green-50 text-green-700 text-xs font-medium hover:bg-green-100 border border-green-200"
                  >
                    Close Visit ✓
                  </button>
                </div>
              </div>
            )
          })}
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
                  <div className="p-6 text-center text-gray-400 text-sm">No completed visits yet today</div>
                ) : completedVisits.map(v => {
                  const badge = statusBadge(v.status)
                  return (
                    <div key={v.id} className="flex items-center justify-between px-4 py-3">
                      <div>
                        <p className="font-medium text-gray-900 text-sm">{v.patient_name || 'Patient'}</p>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {v.doctor_name ? `Dr. ${v.doctor_name}` : ''}{v.doctor_name && v.department_name ? ' · ' : ''}{v.department_name || ''} · {new Date(v.created_at).toLocaleTimeString()}
                        </p>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ml-3 ${badge.color}`}>
                        {badge.label}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Dispatch Confirmation Modal (pharmacy / lab) */}
      {dispatchConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">
              Send to {dispatchConfirm.action === 'pharmacy' ? 'Pharmacy' : 'Lab'}?
            </h3>
            <p className="text-sm text-gray-600 mb-5">
              Patient <span className="font-medium">{dispatchConfirm.patientName}</span> will be{' '}
              {dispatchConfirm.action === 'pharmacy'
                ? 'routed to the hospital pharmacy to collect medicines.'
                : 'sent to the lab for the ordered tests.'}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setDispatchConfirm(null)}
                className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                disabled={dispatching}
                onClick={() => dispatch({ visitId: dispatchConfirm.visitId, action: dispatchConfirm.action })}
                className={`flex-1 py-2.5 rounded-lg text-sm font-medium text-white disabled:opacity-60 ${
                  dispatchConfirm.action === 'pharmacy' ? 'bg-orange-500 hover:bg-orange-600' : 'bg-purple-500 hover:bg-purple-600'
                }`}
              >
                {dispatching ? 'Sending…' : `Yes, Send to ${dispatchConfirm.action === 'pharmacy' ? 'Pharmacy' : 'Lab'}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Close Visit Modal */}
      {closingVisit && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-1">Close Visit</h3>
            <p className="text-sm text-gray-500 mb-4">
              {closingVisit.patient_name || 'Patient'} — hand prescription to patient and complete the visit.
            </p>
            <label className="flex items-start gap-3 p-3 rounded-lg border border-gray-200 hover:bg-gray-50 cursor-pointer mb-5">
              <input
                type="checkbox"
                checked={additionalBilling}
                onChange={e => setAdditionalBilling(e.target.checked)}
                className="mt-0.5 rounded"
              />
              <div>
                <p className="text-sm font-medium text-gray-800">Add additional billing charges</p>
                <p className="text-xs text-gray-500">Check if there are extra charges to bill (injections, dressings, procedures, etc.)</p>
              </div>
            </label>
            <div className="flex gap-3">
              <button
                onClick={() => { setClosingVisit(null); setAdditionalBilling(false) }}
                className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                disabled={closing}
                onClick={() => additionalBilling
                  ? closeVisit({ visitId: closingVisit.id, billing: true })
                  : handleCloseAndPrint()
                }
                className="flex-1 bg-green-600 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-60"
              >
                {closing ? 'Processing…' : additionalBilling ? 'Send to Billing →' : 'Close & Print'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function pharmacyStatusLabel(status: string) {
  if (status === 'pending')   return 'Pharmacy: Pending'
  if (status === 'preparing') return 'Pharmacy: Preparing'
  if (status === 'ready')     return 'Pharmacy: Ready'
  if (status === 'partial')   return 'Pharmacy: Partial'
  if (status === 'dispensed') return 'Pharmacy: Dispensed'
  return `Pharmacy: ${status}`
}

function pharmacyStatusChip(status: string) {
  if (status === 'pending')   return 'bg-gray-50 text-gray-500 border-gray-200'
  if (status === 'preparing') return 'bg-amber-50 text-amber-600 border-amber-200'
  if (status === 'ready')     return 'bg-green-50 text-green-700 border-green-200'
  if (status === 'partial')   return 'bg-yellow-50 text-yellow-600 border-yellow-200'
  if (status === 'dispensed') return 'bg-teal-50 text-teal-700 border-teal-200'
  return 'bg-gray-50 text-gray-500 border-gray-200'
}

function statusBadge(status: string) {
  if (status === 'prescription_done') return { color: 'bg-purple-100 text-purple-700', label: 'Prescription Ready' }
  if (status === 'dispatched_pharmacy') return { color: 'bg-orange-100 text-orange-700', label: 'Pharmacy ✓' }
  if (status === 'dispatched_lab') return { color: 'bg-blue-100 text-blue-700', label: 'Lab ✓' }
  if (status === 'dispatched_both') return { color: 'bg-teal-100 text-teal-700', label: 'Pharmacy ✓  Lab ✓' }
  if (status === 'billing_pending') return { color: 'bg-yellow-100 text-yellow-700', label: 'Billing Pending' }
  if (status === 'closed') return { color: 'bg-green-100 text-green-700', label: 'Closed' }
  return { color: 'bg-gray-100 text-gray-700', label: status }
}

function VitalField({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
      {error && <p className="text-xs text-red-600 mt-0.5">{error}</p>}
    </div>
  )
}

function inputCls(hasError: boolean) {
  return `w-full border ${hasError ? 'border-red-400' : 'border-gray-300'} rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary`
}
