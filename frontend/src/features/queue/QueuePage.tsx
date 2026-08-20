import { useState, useCallback, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useWebSocket } from '@/hooks/useWebSocket'
import { queueService } from '@/services/queueService'
import { patientService } from '@/services/patientService'
import { departmentService, doctorService, billingService } from '@/services/clinicalService'
import { RegisterPatientModal } from '@/components/shared/RegisterPatientModal'
import type { Doctor, Patient, QueueToken, Invoice } from '@/types/common'

const PRIORITY_BADGE: Record<string, string> = {
  emergency: 'bg-red-100 text-red-700',
  urgent: 'bg-orange-100 text-orange-700',
  pregnant: 'bg-pink-100 text-pink-700',
  disabled: 'bg-indigo-100 text-indigo-700',
  senior_citizen: 'bg-yellow-100 text-yellow-700',
  normal: 'bg-gray-100 text-gray-600',
}

const STATUS_BADGE: Record<string, string> = {
  checked_in: 'bg-blue-50 text-blue-700',
  completed: 'bg-green-50 text-green-700',
  cancelled: 'bg-red-50 text-red-600',
}

export default function QueuePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [issueForm, setIssueForm] = useState(false)
  const [issueStep, setIssueStep] = useState<'form' | 'confirm'>('form')
  const [patientSearch, setPatientSearch] = useState('')
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null)
  const [priority, setPriority] = useState('normal')
  const [priorityReason, setPriorityReason] = useState('')
  const [selectedDeptId, setSelectedDeptId] = useState<string>('')
  const [selectedDoctorId, setSelectedDoctorId] = useState<string>('')
  const [filterDeptId, setFilterDeptId] = useState<string>('')
  const [waiveFee, setWaiveFee] = useState(false)
  const [payMode, setPayMode] = useState<'cash' | 'online'>('cash')
  const [showCompleted, setShowCompleted] = useState(false)
  const [showCancelled, setShowCancelled] = useState(false)

  // Edit modal
  const [editToken, setEditToken] = useState<QueueToken | null>(null)
  const [editDeptId, setEditDeptId] = useState<string>('')
  const [editDoctorId, setEditDoctorId] = useState<string>('')
  const [editPriority, setEditPriority] = useState<string>('')
  const [editPriorityReason, setEditPriorityReason] = useState('')

  const [showRegisterModal, setShowRegisterModal] = useState(false)

  // Cancel modal
  const [cancelToken, setCancelToken] = useState<QueueToken | null>(null)
  const [cancelStep, setCancelStep] = useState<'confirm' | 'notes'>('confirm')
  const [cancelNotes, setCancelNotes] = useState<string>('')

  const qc = useQueryClient()
  const navigate = useNavigate()

  const { data: departments = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['departments'],
    queryFn: () => departmentService.list(),
  })

  const { data: tokens = [], refetch } = useQuery<QueueToken[]>({
    queryKey: ['queue', filterDeptId],
    queryFn: () => queueService.list({ department_id: filterDeptId || undefined }),
    refetchInterval: 30_000,
  })

  const { data: queueSummary } = useQuery({
    queryKey: ['queue-summary'],
    queryFn: () => queueService.summary(),
    refetchInterval: 30_000,
  })

  const { data: patients = [] } = useQuery({
    queryKey: ['patients', patientSearch],
    queryFn: () => patientService.list(patientSearch || undefined),
    enabled: issueForm,
    staleTime: 10_000,
  })

  const { data: lastVisitHistory = [] } = useQuery({
    queryKey: ['patient-last-visit', selectedPatient?.id],
    queryFn: () => patientService.getHistory(selectedPatient!.id),
    enabled: !!selectedPatient && issueStep === 'confirm',
    staleTime: 60_000,
  })

  const { data: deptDoctors = [] } = useQuery<Doctor[]>({
    queryKey: ['doctors', 'by-dept', selectedDeptId],
    queryFn: () => doctorService.list({ department_id: selectedDeptId }),
    enabled: !!selectedDeptId,
    staleTime: 30_000,
  })

  const { data: editDeptDoctors = [] } = useQuery<Doctor[]>({
    queryKey: ['doctors', 'by-dept', editDeptId],
    queryFn: () => doctorService.list({ department_id: editDeptId }),
    enabled: !!editDeptId,
    staleTime: 30_000,
  })

  useWebSocket('queue:update', useCallback(() => { refetch() }, [refetch]))
  useWebSocket('pos:payment', useCallback(() => {
    refetch()
    qc.invalidateQueries({ queryKey: ['invoice-by-visit'] })
  }, [refetch, qc]))

  // Arriving from Register Visit → Walk-In opens the issue form directly.
  useEffect(() => {
    if (searchParams.get('action') === 'issue') {
      setIssueForm(true)
      const next = new URLSearchParams(searchParams)
      next.delete('action')
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const closeIssue = () => {
    setIssueForm(false)
    setIssueStep('form')
    setSelectedPatient(null)
    setPatientSearch('')
    setPriority('normal')
    setPriorityReason('')
    setSelectedDeptId('')
    setSelectedDoctorId('')
    setWaiveFee(false)
    setPayMode('cash')
  }

  const { mutate: issueToken, isPending: issuing } = useMutation({
    mutationFn: () => queueService.issue({
      patient_id: selectedPatient!.id,
      queue_type: 'consultation',
      department_id: selectedDeptId || undefined,
      doctor_id: selectedDoctorId || undefined,
      priority,
      priority_reason: priorityReason || undefined,
      waive_fee: waiveFee,
    }),
    onSuccess: (token) => {
      qc.invalidateQueries({ queryKey: ['queue'] })
      closeIssue()
      if (token.visit_id && !waiveFee) {
        if (payMode === 'cash') {
          navigate(`/billing?visitId=${token.visit_id}&returnTo=queue`)
        }
        // online: POS kiosk triggered by backend — stay on queue page
      }
    },
  })

  const { mutate: editMut, isPending: editing } = useMutation({
    mutationFn: () => queueService.edit(editToken!.id, {
      department_id: editDeptId || undefined,
      doctor_id: editDoctorId || undefined,
      priority: editPriority || undefined,
      priority_reason: editPriorityReason || undefined,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['queue'] }); setEditToken(null) },
  })

  const { mutate: cancelMut, isPending: cancelling } = useMutation({
    mutationFn: () => queueService.cancel(cancelToken!.id, cancelNotes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['queue'] })
      setCancelToken(null)
      setCancelStep('confirm')
      setCancelNotes('')
    },
  })

  // ── Payment recovery actions (receptionist) ────────────────────────────────
  const { mutate: resendPos } = useMutation({
    mutationFn: (invoiceId: string) => billingService.resendPos(invoiceId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['invoice-by-visit'] }),
  })

  const { mutate: admitPatient } = useMutation({
    mutationFn: (invoiceId: string) => billingService.admitPatient(invoiceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['queue'] })
      qc.invalidateQueries({ queryKey: ['invoice-by-visit'] })
    },
  })

  const { mutate: syncAndAdmit } = useMutation({
    mutationFn: (invoiceId: string) => billingService.syncPayment(invoiceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['queue'] })
      qc.invalidateQueries({ queryKey: ['invoice-by-visit'] })
    },
  })

  const checkedIn = tokens.filter(t => t.status === 'checked_in').length
  const completed = tokens.filter(t => t.status === 'completed').length
  const cancelled = tokens.filter(t => t.status === 'cancelled').length

  const activeTokens = tokens.filter(t => t.status !== 'completed' && t.status !== 'cancelled')
  const completedTokens = tokens.filter(t => t.status === 'completed')
  const cancelledTokens = tokens.filter(t => t.status === 'cancelled')

  const openEdit = (token: QueueToken) => {
    setEditToken(token)
    setEditDeptId(token.department_id ?? '')
    setEditDoctorId(token.doctor_id ?? '')
    setEditPriority(token.priority)
    setEditPriorityReason(token.priority_reason ?? '')
  }

  const openCancel = (token: QueueToken) => {
    setCancelToken(token)
    setCancelStep('confirm')
    setCancelNotes('')
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">OPD Queue Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">Real-time patient queue management</p>
        </div>
        <button
          onClick={() => setIssueForm(true)}
          className="flex items-center gap-2 bg-primary text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-primary/90"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Issue Token
        </button>
      </div>

      {/* Department filter */}
      {departments.length > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Filter by department:</span>
          <select
            value={filterDeptId}
            onChange={e => setFilterDeptId(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            <option value="">All departments</option>
            {departments.map(d => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard label="Checked In" value={checkedIn} color="blue" />
        <StatCard label="Completed" value={completed} color="green" />
        <StatCard label="Cancelled" value={cancelled} color="red" />
      </div>

      {queueSummary && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <QueueSlaCard label="Waiting for Nurse" summary={queueSummary.waiting_for_nurse} />
          <QueueSlaCard label="Waiting for Doctor" summary={queueSummary.waiting_for_doctor} />
        </div>
      )}

      {/* Token table — active only */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['Token', 'Priority', 'Patient', 'Phone', 'Department', 'Doctor', 'Status', 'Payment', 'Issued', 'Actions'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {activeTokens.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-4 py-10 text-center text-gray-400">No active tokens</td>
              </tr>
            ) : activeTokens.map((token) => (
              <tr
                key={token.id}
                className={`hover:bg-gray-50 ${token.status === 'cancelled' ? 'opacity-60' : ''}`}
              >
                <td className="px-4 py-3">
                  <span className="text-2xl font-bold text-primary tabular-nums">{token.token_no}</span>
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${PRIORITY_BADGE[token.priority] || ''}`}>
                    {token.priority.replace('_', ' ')}
                  </span>
                </td>
                <td className="px-4 py-3 font-medium text-gray-900">{token.patient_name || '—'}</td>
                <td className="px-4 py-3 text-gray-500">{token.patient_phone || '—'}</td>
                <td className="px-4 py-3 text-gray-500 text-xs">{token.department_name || '—'}</td>
                <td className="px-4 py-3 text-gray-500 text-xs">{token.doctor_name || '—'}</td>
                <td className="px-4 py-3">
                  <span
                    title={token.status === 'cancelled' && token.notes ? `Reason: ${token.notes}` : undefined}
                    className={`px-2 py-0.5 rounded-full text-xs font-medium cursor-default ${STATUS_BADGE[token.status] || 'bg-gray-100 text-gray-600'}`}
                  >
                    {token.status.replace('_', ' ')}
                    {token.status === 'cancelled' && token.notes && (
                      <span className="ml-1 text-red-400">ⓘ</span>
                    )}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {token.visit_id
                    ? <PaymentCell visitId={token.visit_id} />
                    : <span className="text-xs text-gray-400">—</span>
                  }
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {new Date(token.issued_at).toLocaleTimeString()}
                </td>
                <td className="px-4 py-3">
                  {token.status === 'checked_in' && (
                    <div className="flex items-center gap-2 flex-wrap">
                      {token.visit_id && (
                        <PaymentActions
                          visitId={token.visit_id}
                          onResendPos={resendPos}
                          onSyncAndAdmit={syncAndAdmit}
                          onAdmitManually={admitPatient}
                        />
                      )}
                      <button
                        onClick={() => openEdit(token)}
                        title="Edit token"
                        className="p-1 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                      <button
                        onClick={() => openCancel(token)}
                        title="Cancel visit"
                        className="p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Completed records — collapsible */}
      {completedTokens.length > 0 && (
        <div className="border border-gray-200 rounded-xl overflow-hidden">
          <button
            onClick={() => setShowCompleted(v => !v)}
            className="w-full flex items-center justify-between px-5 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-sm font-medium text-gray-700"
          >
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500"></span>
              Completed Today
              <span className="ml-1 px-2 py-0.5 rounded-full bg-green-100 text-green-700 text-xs font-semibold">{completedTokens.length}</span>
            </span>
            <svg
              className={`w-4 h-4 text-gray-400 transition-transform ${showCompleted ? 'rotate-180' : ''}`}
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showCompleted && (
            <div className="bg-white overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    {['Token', 'Patient', 'Phone', 'Department', 'Doctor', 'Payment', 'Completed'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {completedTokens.map(token => (
                    <tr key={token.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <span className="text-lg font-bold text-gray-400 tabular-nums">{token.token_no}</span>
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-700">{token.patient_name || '—'}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{token.patient_phone || '—'}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{token.department_name || '—'}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{token.doctor_name || '—'}</td>
                      <td className="px-4 py-3">
                        {token.visit_id
                          ? <PaymentCell visitId={token.visit_id} />
                          : <span className="text-xs text-gray-400">—</span>
                        }
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {new Date(token.issued_at).toLocaleTimeString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Cancelled records — collapsible */}
      {cancelledTokens.length > 0 && (
        <div className="border border-red-100 rounded-xl overflow-hidden">
          <button
            onClick={() => setShowCancelled(v => !v)}
            className="w-full flex items-center justify-between px-5 py-3 bg-red-50 hover:bg-red-100 transition-colors text-sm font-medium text-red-700"
          >
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-red-400"></span>
              Cancelled Today
              <span className="ml-1 px-2 py-0.5 rounded-full bg-red-100 text-red-600 text-xs font-semibold">{cancelledTokens.length}</span>
            </span>
            <svg
              className={`w-4 h-4 text-red-300 transition-transform ${showCancelled ? 'rotate-180' : ''}`}
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showCancelled && (
            <div className="bg-white overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    {['Token', 'Patient', 'Phone', 'Department', 'Doctor', 'Reason', 'Issued'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {cancelledTokens.map(token => (
                    <tr key={token.id} className="hover:bg-gray-50 opacity-75">
                      <td className="px-4 py-3">
                        <span className="text-lg font-bold text-red-300 tabular-nums">{token.token_no}</span>
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-600">{token.patient_name || '—'}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{token.patient_phone || '—'}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{token.department_name || '—'}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{token.doctor_name || '—'}</td>
                      <td className="px-4 py-3 text-xs text-red-500">{token.notes || '—'}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {new Date(token.issued_at).toLocaleTimeString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Issue Token Modal */}
      {issueForm && issueStep === 'form' && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4" onClick={closeIssue}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b border-gray-100 flex items-center justify-between">
              <h2 className="font-semibold text-gray-900">Issue Queue Token</h2>
              <button onClick={closeIssue} className="text-gray-400 hover:text-gray-700">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Search Patient</label>
                <input
                  value={patientSearch}
                  onChange={e => setPatientSearch(e.target.value)}
                  placeholder="Name, phone or UHID…"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                />
              </div>

              {patientSearch && patients.length > 0 && (
                <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-40 overflow-y-auto">
                  {patients.map((p: Patient) => (
                    <button
                      key={p.id}
                      onClick={() => { setSelectedPatient(p); setPatientSearch('') }}
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-blue-50 transition-colors ${selectedPatient?.id === p.id ? 'bg-blue-50' : ''}`}
                    >
                      <div className="font-medium">{p.first_name} {p.last_name}</div>
                      <div className="text-xs text-gray-400">{p.uhid} · {p.phone}</div>
                    </button>
                  ))}
                </div>
              )}

              {patientSearch.length >= 2 && patients.length === 0 && !selectedPatient && (
                <p className="text-xs text-gray-500">
                  No patients found.{' '}
                  <button
                    type="button"
                    onClick={() => setShowRegisterModal(true)}
                    className="text-primary font-medium underline hover:text-primary/80"
                  >
                    Click here to register a new patient
                  </button>
                </p>
              )}

              {selectedPatient && (
                <div className="bg-blue-50 rounded-lg px-3 py-2 text-sm flex items-center justify-between">
                  <span>
                    <span className="font-medium">{selectedPatient.first_name} {selectedPatient.last_name}</span>
                    <span className="text-xs text-blue-600 ml-2">{selectedPatient.uhid}</span>
                  </span>
                  <button onClick={() => setSelectedPatient(null)} className="text-blue-400 hover:text-blue-700 text-xs">✕</button>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Priority</label>
                <select value={priority} onChange={e => setPriority(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30">
                  <option value="normal">Normal</option>
                  <option value="senior_citizen">Senior Citizen</option>
                  <option value="pregnant">Pregnant</option>
                  <option value="disabled">Disabled</option>
                  <option value="urgent">Urgent</option>
                  <option value="emergency">Emergency</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Priority reason</label>
                <input value={priorityReason} onChange={e => setPriorityReason(e.target.value)}
                  placeholder="Reason for priority assignment"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
              </div>

              {departments.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Department</label>
                  <select value={selectedDeptId} onChange={e => { setSelectedDeptId(e.target.value); setSelectedDoctorId('') }}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30">
                    <option value="">— Select department —</option>
                    {departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                </div>
              )}

              {selectedDeptId && (
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Doctor</label>
                  {deptDoctors.length === 0 ? (
                    <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2">No doctors found for this department</p>
                  ) : (
                    <select value={selectedDoctorId} onChange={e => setSelectedDoctorId(e.target.value)}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30">
                      <option value="">— Select doctor —</option>
                      {deptDoctors.map((d: Doctor) => <option key={d.id} value={d.id}>{d.full_name}</option>)}
                    </select>
                  )}
                </div>
              )}

              <div className="flex gap-3 pt-1">
                <button onClick={closeIssue}
                  className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50">
                  Cancel
                </button>
                <button
                  disabled={!selectedPatient}
                  onClick={() => setIssueStep('confirm')}
                  className="flex-1 bg-primary text-white py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
                >
                  Review & Confirm
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Issue Token — Confirm Step */}
      {issueForm && issueStep === 'confirm' && (() => {
        const selDoctor = deptDoctors.find(d => d.id === selectedDoctorId) ?? null
        const selDept = departments.find(d => d.id === selectedDeptId) ?? null
        const fee = selDoctor?.consultation_fee ?? 0

        // Last visit calculation
        const today = new Date(); today.setHours(0, 0, 0, 0)
        const pastVisits = lastVisitHistory.filter(
          (h: any) => !['registered', 'vitals_recorded', 'vitals_done', 'in_consultation', 'pre_billing'].includes(h.status)
        )
        const lastVisit = pastVisits.length > 0 ? new Date(pastVisits[0].visit_date) : null
        const daysDiff = lastVisit ? Math.floor((today.getTime() - new Date(lastVisit).setHours(0,0,0,0)) / 86400000) : null
        const isFollowUp = daysDiff !== null && daysDiff <= 7
        const lastVisitLabel = lastVisit
          ? `${lastVisit.toLocaleDateString('en-GB')} (${daysDiff === 0 ? 'today' : daysDiff === 1 ? '1 day ago' : `${daysDiff} days ago`})`
          : null

        return (
          <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4">
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
              <div className="p-5 border-b border-gray-100 flex items-center justify-between">
                <h2 className="font-semibold text-gray-900">Confirm Token Issuance</h2>
                <button onClick={closeIssue} className="text-gray-400 hover:text-gray-700">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="p-5 space-y-4">
                {/* Summary card */}
                <div className="bg-gray-50 rounded-xl divide-y divide-gray-200 border border-gray-200">
                  <ConfirmRow label="Patient" value={`${selectedPatient!.first_name} ${selectedPatient!.last_name}`} sub={selectedPatient!.uhid} />
                  <ConfirmRow label="Department" value={selDept?.name ?? '—'} />
                  <ConfirmRow label="Doctor" value={selDoctor ? `Dr. ${selDoctor.full_name}` : '—'} sub={selDoctor?.specialization} />
                  <ConfirmRow label="Priority" value={priority.replace('_', ' ')} highlight={priority === 'emergency' ? 'red' : priority === 'senior_citizen' ? 'yellow' : undefined} />
                  {lastVisitLabel && (
                    <ConfirmRow
                      label="Last Visit"
                      value={lastVisitLabel}
                      highlight={isFollowUp ? 'green' : undefined}
                    />
                  )}
                  {fee > 0 && (
                    <ConfirmRow label="Consultation Fee" value={waiveFee ? 'Free (follow-up)' : `₹${fee}`} highlight={waiveFee ? 'green' : 'blue'} />
                  )}
                </div>

                {/* Follow-up waiver */}
                {fee > 0 && isFollowUp && (
                  <label className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-xl px-4 py-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={waiveFee}
                      onChange={e => setWaiveFee(e.target.checked)}
                      className="mt-0.5 accent-green-600 w-4 h-4"
                    />
                    <div>
                      <p className="text-sm font-medium text-green-800">Waive consultation fee</p>
                      <p className="text-xs text-green-700 mt-0.5">
                        Last visit was {daysDiff} {daysDiff === 1 ? 'day' : 'days'} ago — follow-up within 7 days is free.
                      </p>
                    </div>
                  </label>
                )}

                {/* Payment mode toggle */}
                {fee > 0 && !waiveFee && (
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-gray-700">Payment Method</p>
                    <div className="flex rounded-lg border border-gray-200 overflow-hidden">
                      <button
                        type="button"
                        onClick={() => setPayMode('cash')}
                        className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                          payMode === 'cash'
                            ? 'bg-green-600 text-white'
                            : 'bg-white text-gray-600 hover:bg-gray-50'
                        }`}
                      >
                        💵 Cash
                      </button>
                      <button
                        type="button"
                        onClick={() => setPayMode('online')}
                        className={`flex-1 py-2.5 text-sm font-medium border-l border-gray-200 transition-colors ${
                          payMode === 'online'
                            ? 'bg-blue-600 text-white'
                            : 'bg-white text-gray-600 hover:bg-gray-50'
                        }`}
                      >
                        📲 Online (Razorpay)
                      </button>
                    </div>
                    {payMode === 'cash' && (
                      <p className="text-xs text-green-700 bg-green-50 rounded-lg px-3 py-2">
                        Reception will collect <strong>₹{fee}</strong> cash and direct the patient to billing.
                      </p>
                    )}
                    {payMode === 'online' && (
                      <p className="text-xs text-blue-700 bg-blue-50 rounded-lg px-3 py-2">
                        Payment request will be sent to the POS kiosk for <strong>₹{fee}</strong>.
                      </p>
                    )}
                  </div>
                )}

                <div className="flex gap-3 pt-1">
                  <button onClick={() => setIssueStep('form')}
                    className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50">
                    Back
                  </button>
                  <button
                    disabled={issuing}
                    onClick={() => issueToken()}
                    className="flex-1 bg-primary text-white py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
                  >
                    {issuing
                      ? 'Issuing…'
                      : (fee > 0 && !waiveFee && payMode === 'cash')
                        ? 'Issue Token & Collect Cash'
                        : 'Confirm & Issue Token'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Edit Token Modal */}
      {editToken && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4" onClick={() => setEditToken(null)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b border-gray-100 flex items-center justify-between">
              <h2 className="font-semibold text-gray-900">Edit Token #{editToken.token_no}</h2>
              <button onClick={() => setEditToken(null)} className="text-gray-400 hover:text-gray-700">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Priority</label>
                <select value={editPriority} onChange={e => setEditPriority(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30">
                  <option value="normal">Normal</option>
                  <option value="senior_citizen">Senior Citizen</option>
                  <option value="pregnant">Pregnant</option>
                  <option value="disabled">Disabled</option>
                  <option value="urgent">Urgent</option>
                  <option value="emergency">Emergency</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Priority reason</label>
                <input value={editPriorityReason} onChange={e => setEditPriorityReason(e.target.value)}
                  placeholder="Reason for priority assignment"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Department</label>
                <select value={editDeptId} onChange={e => { setEditDeptId(e.target.value); setEditDoctorId('') }}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30">
                  <option value="">— No change —</option>
                  {departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
              {editDeptId && (
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Doctor</label>
                  {editDeptDoctors.length === 0 ? (
                    <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2">No doctors found for this department</p>
                  ) : (
                    <select value={editDoctorId} onChange={e => setEditDoctorId(e.target.value)}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30">
                      <option value="">— No change —</option>
                      {editDeptDoctors.map((d: Doctor) => <option key={d.id} value={d.id}>{d.full_name}</option>)}
                    </select>
                  )}
                </div>
              )}
              <div className="flex gap-3 pt-1">
                <button onClick={() => setEditToken(null)}
                  className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50">
                  Cancel
                </button>
                <button
                  disabled={editing}
                  onClick={() => editMut()}
                  className="flex-1 bg-primary text-white py-2.5 rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
                >
                  {editing ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cancel Confirmation Modal */}
      {cancelToken && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4" onClick={() => { setCancelToken(null); setCancelStep('confirm'); setCancelNotes('') }}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm" onClick={e => e.stopPropagation()}>
            {cancelStep === 'confirm' ? (
              <>
                <div className="p-5 space-y-3">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center flex-shrink-0">
                      <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-900">Cancel Visit?</h3>
                      <p className="text-sm text-gray-500">Token #{cancelToken.token_no} — {cancelToken.patient_name}</p>
                    </div>
                  </div>
                  <p className="text-sm text-gray-600">Do you want to cancel this visit? This action cannot be undone.</p>
                </div>
                <div className="px-5 pb-5 flex gap-3">
                  <button
                    onClick={() => { setCancelToken(null); setCancelStep('confirm'); setCancelNotes('') }}
                    className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50"
                  >
                    No, keep it
                  </button>
                  <button
                    onClick={() => setCancelStep('notes')}
                    className="flex-1 bg-red-600 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-red-700"
                  >
                    Yes, cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="p-5 border-b border-gray-100 flex items-center justify-between">
                  <h3 className="font-semibold text-gray-900">Reason for Cancellation</h3>
                  <button onClick={() => setCancelStep('confirm')} className="text-gray-400 hover:text-gray-700 text-xs">← Back</button>
                </div>
                <div className="p-5 space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Notes <span className="text-red-500">*</span>
                    </label>
                    <textarea
                      value={cancelNotes}
                      onChange={e => setCancelNotes(e.target.value)}
                      rows={3}
                      placeholder="Enter reason for cancellation…"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-300 focus:border-red-400 resize-none"
                    />
                    {cancelNotes.trim() === '' && (
                      <p className="text-xs text-red-500 mt-1">Notes are required to cancel a visit</p>
                    )}
                  </div>
                  <div className="flex gap-3">
                    <button
                      onClick={() => { setCancelToken(null); setCancelStep('confirm'); setCancelNotes('') }}
                      className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50"
                    >
                      Discard
                    </button>
                    <button
                      disabled={cancelNotes.trim() === '' || cancelling}
                      onClick={() => cancelMut()}
                      className="flex-1 bg-red-600 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
                    >
                      {cancelling ? 'Cancelling…' : 'Confirm Cancel'}
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {showRegisterModal && (
        <RegisterPatientModal
          onClose={() => setShowRegisterModal(false)}
          prefillPhone={/^\d/.test(patientSearch) ? patientSearch.replace(/\D/g, '').slice(0, 15) : undefined}
          onSuccess={patient => {
            setSelectedPatient(patient)
            setPatientSearch('')
            setShowRegisterModal(false)
          }}
        />
      )}
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: number | string; color: string }) {
  const colorMap: Record<string, string> = {
    blue: 'bg-blue-50 text-blue-700',
    green: 'bg-green-50 text-green-700',
    red: 'bg-red-50 text-red-700',
    gray: 'bg-gray-50 text-gray-700',
  }
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-3xl font-bold ${colorMap[color] || ''} rounded-lg px-2 py-0.5 inline-block`}>{value}</p>
    </div>
  )
}

function QueueSlaCard({
  label,
  summary,
}: {
  label: string
  summary: { waiting_count: number; breached_count: number; longest_wait_seconds?: number; sla_threshold_seconds: number }
}) {
  const longestMinutes = summary.longest_wait_seconds == null
    ? '—'
    : `${Math.floor(summary.longest_wait_seconds / 60)} min`
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-gray-800">{label}</p>
        {summary.breached_count > 0 && (
          <span className="text-xs font-semibold text-red-700 bg-red-50 border border-red-200 rounded-full px-2 py-0.5">
            {summary.breached_count} breached
          </span>
        )}
      </div>
      <div className="flex items-end gap-6 mt-3">
        <div><p className="text-xs text-gray-500">Waiting</p><p className="text-2xl font-bold text-gray-900">{summary.waiting_count}</p></div>
        <div><p className="text-xs text-gray-500">Longest</p><p className="text-lg font-semibold text-gray-700">{longestMinutes}</p></div>
        <div><p className="text-xs text-gray-500">SLA</p><p className="text-lg font-semibold text-gray-700">{Math.floor(summary.sla_threshold_seconds / 60)} min</p></div>
      </div>
    </div>
  )
}

function ConfirmRow({ label, value, sub, highlight }: { label: string; value: string; sub?: string; highlight?: 'red' | 'yellow' | 'blue' | 'green' }) {
  const highlightClass = highlight === 'red' ? 'text-red-700 font-semibold' : highlight === 'yellow' ? 'text-yellow-700 font-semibold' : highlight === 'blue' ? 'text-blue-700 font-semibold' : highlight === 'green' ? 'text-green-700 font-semibold' : 'text-gray-900 font-medium'
  return (
    <div className="flex items-center justify-between px-4 py-3">
      <span className="text-xs text-gray-500 uppercase tracking-wide">{label}</span>
      <div className="text-right">
        <span className={`text-sm ${highlightClass}`}>{value}</span>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

// ── Payment status chip shown in the Payment column ───────────────────────────
function PaymentCell({ visitId }: { visitId: string }) {
  const { data: invoice, isLoading } = useQuery<Invoice>({
    queryKey: ['invoice-by-visit', visitId],
    queryFn: () => billingService.getByVisit(visitId),
    refetchInterval: 12_000,
    retry: false,
  })

  if (isLoading) return <span className="text-xs text-gray-400">—</span>
  if (!invoice)  return <span className="text-xs text-gray-400">—</span>

  const isPaid = invoice.status === 'paid'
  return (
    <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded-full font-medium border ${
      isPaid
        ? 'bg-green-50 text-green-700 border-green-200'
        : 'bg-amber-50 text-amber-700 border-amber-200'
    }`}>
      {isPaid ? `✓ Paid ₹${Number(invoice.total).toFixed(0)}` : `⏳ ₹${Number(invoice.total).toFixed(0)} pending`}
    </span>
  )
}

// ── Payment recovery actions shown in the Actions column for pre_billing ──────
function PaymentActions({
  visitId,
  onResendPos,
  onSyncAndAdmit,
  onAdmitManually,
}: {
  visitId: string
  onResendPos: (id: string) => void
  onSyncAndAdmit: (id: string) => void
  onAdmitManually: (id: string) => void
}) {
  const { data: invoice } = useQuery<Invoice>({
    queryKey: ['invoice-by-visit', visitId],
    queryFn: () => billingService.getByVisit(visitId),
    refetchInterval: 12_000,
    retry: false,
  })

  if (!invoice || invoice.status === 'paid') return null

  const hasPosOrder = !!invoice.razorpay_order_id

  return (
    <>
      {hasPosOrder && (
        <button
          onClick={() => onResendPos(invoice.id)}
          title="Re-send payment request to POS kiosk"
          className="px-2 py-1 text-xs font-medium rounded-md bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 whitespace-nowrap"
        >
          Re-send POS
        </button>
      )}
      {hasPosOrder && (
        <button
          onClick={() => onSyncAndAdmit(invoice.id)}
          title="Check Razorpay and admit if paid"
          className="px-2 py-1 text-xs font-medium rounded-md bg-purple-50 text-purple-700 border border-purple-200 hover:bg-purple-100 whitespace-nowrap"
        >
          Verify
        </button>
      )}
      <button
        onClick={() => onAdmitManually(invoice.id)}
        title="Mark as cash paid and admit to queue"
        className="px-2 py-1 text-xs font-medium rounded-md bg-green-50 text-green-700 border border-green-200 hover:bg-green-100 whitespace-nowrap"
      >
        Admit (Cash)
      </button>
    </>
  )
}
