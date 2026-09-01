/**
 * Lab Orders Page — Lab Technician
 *
 * Flow: ordered → sample_pending → sample_collected → processing → result_ready → verified → completed
 * Features: per-test critical flags, normal ranges, PDF/image upload, sample rejection,
 *           doctor notification via WebSocket on results ready.
 */
import { useRef, useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { labService } from '@/services/labService'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { LabOrder } from '@/types/common'

const STATUS_FLOW: Record<string, { next: string; label: string; color: string } | null> = {
  ordered:          { next: 'sample_pending',   label: 'Await Sample',     color: 'blue' },
  sample_pending:   { next: 'sample_collected', label: 'Collect Sample',   color: 'blue' },
  sample_collected: { next: 'processing',        label: 'Start Processing', color: 'purple' },
  processing:       { next: 'result_ready',      label: 'Enter Results',    color: 'green' },
  result_ready:     { next: 'verified',          label: 'Verify Results',   color: 'green' },
  verified:         { next: 'completed',         label: 'Complete Order',   color: 'green' },
  completed:        null,
  rejected:         null,
}

const STATUS_BADGE: Record<string, string> = {
  ordered:          'bg-gray-100 text-gray-600',
  sample_pending:   'bg-gray-100 text-gray-600',
  sample_collected: 'bg-blue-100 text-blue-700',
  processing:       'bg-purple-100 text-purple-700',
  resulted:         'bg-green-100 text-green-700',
  rejected:         'bg-red-100 text-red-600',
}

export default function LabPage() {
  const qc = useQueryClient()
  const [enterResultsFor, setEnterResultsFor] = useState<LabOrder | null>(null)
  const [testResults, setTestResults] = useState<Record<string, string>>({})
  const [labNotes, setLabNotes] = useState('')
  const [reportFile, setReportFile] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const { data: orders = [], refetch } = useQuery({
    queryKey: ['lab-orders'],
    queryFn: () => labService.listOrders(),
    refetchInterval: 30_000,
  })

  useWebSocket('lab:update', useCallback(() => refetch(), [refetch]))
  useWebSocket('visit:update', useCallback(() => refetch(), [refetch]))

  const openResultsModal = (order: LabOrder) => {
    const initial: Record<string, string> = {}
    order.tests.forEach(t => {
      const key = t.test_code || t.test
      if (key) initial[key] = ''
    })
    setTestResults(initial)
    setLabNotes('')
    setReportFile(null)
    setEnterResultsFor(order)
  }

  const { mutate: advance } = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => {
      if (status === 'result_ready') {
        const order = orders.find(o => o.id === id)
        if (order) openResultsModal(order)
        return Promise.resolve({} as any)
      }
      if (status === 'verified') return labService.verifyResults(id)
      return labService.updateStatus(id, status)
    },
    onSuccess: (_, vars) => {
      if (vars.status !== 'result_ready') qc.invalidateQueries({ queryKey: ['lab-orders'] })
    },
  })

  const { mutate: rejectOrder } = useMutation({
    mutationFn: (id: string) => labService.rejectOrder(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['lab-orders'] }),
  })

  const { mutate: submitResults, isPending: submitting } = useMutation({
    mutationFn: async () => {
      const results: Record<string, string> = {}
      Object.entries(testResults).forEach(([test, val]) => {
        if (val.trim()) results[test] = val
      })
      const labResult = await labService.enterResults(enterResultsFor!.id, {
        results: Object.keys(results).length ? results : undefined,
        notes: labNotes.trim() || undefined,
      })
      if (reportFile) {
        await labService.uploadReport(enterResultsFor!.id, reportFile)
      }
      return labResult
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['lab-orders'] })
      setEnterResultsFor(null)
    },
  })

  const active = orders.filter(o => !['resulted', 'rejected'].includes(o.status))
  const resulted = orders.filter(o => ['result_ready', 'verified', 'completed'].includes(o.status))
  const rejected = orders.filter(o => o.status === 'rejected')

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Laboratory Orders</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {active.length} active · {resulted.length} resulted · {rejected.length} rejected
        </p>
      </div>

      {active.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400">
          No pending lab orders
        </div>
      ) : (
        <div className="space-y-3">
          {active.map(order => (
            <LabOrderCard key={order.id} order={order} onAdvance={advance} onReject={rejectOrder} />
          ))}
        </div>
      )}

      {resulted.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-700 list-none flex items-center gap-1">
            <svg className="w-4 h-4 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            {resulted.length} resulted orders
          </summary>
          <div className="mt-2 space-y-2">
            {resulted.map(order => (
              <LabOrderCard key={order.id} order={order} onAdvance={advance} onReject={rejectOrder} />
            ))}
          </div>
        </details>
      )}

      {rejected.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-sm text-red-400 hover:text-red-600 list-none flex items-center gap-1">
            <svg className="w-4 h-4 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            {rejected.length} rejected samples
          </summary>
          <div className="mt-2 space-y-2">
            {rejected.map(order => (
              <LabOrderCard key={order.id} order={order} onAdvance={advance} onReject={rejectOrder} />
            ))}
          </div>
        </details>
      )}

      {/* Enter Results Modal */}
      {enterResultsFor && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEnterResultsFor(null)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
            {/* Header */}
            <div className="p-5 border-b border-gray-100 flex items-center justify-between shrink-0">
              <div>
                <h2 className="font-semibold text-gray-900">Enter Lab Results</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  {enterResultsFor.patient_name} · {enterResultsFor.doctor_name ? `Dr. ${enterResultsFor.doctor_name}` : ''}
                </p>
              </div>
              <button onClick={() => setEnterResultsFor(null)} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
            </div>

            {/* Body */}
            <div className="p-5 space-y-5 overflow-y-auto flex-1">
              {/* Lab Notes */}
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5 block">
                  Lab Notes <span className="normal-case font-normal text-gray-400">(optional)</span>
                </label>
                <textarea
                  value={labNotes}
                  onChange={e => setLabNotes(e.target.value)}
                  rows={3}
                  placeholder="Observations, sample quality, remarks…"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none"
                />
              </div>

              {/* Per-test results */}
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5 block">
                  Results <span className="normal-case font-normal text-gray-400">(optional)</span>
                </label>
                <div className="space-y-2">
                  {Object.keys(testResults).map(test => (
                    <div key={test} className="flex items-center gap-3">
                      <span className="text-sm text-gray-700 w-1/3 truncate">{test}</span>
                      <input
                        value={testResults[test]}
                        onChange={e => setTestResults(p => ({ ...p, [test]: e.target.value }))}
                        placeholder="Enter value…"
                        className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                      />
                    </div>
                  ))}
                </div>
              </div>

              {/* File upload */}
              <div className="border-2 border-dashed border-gray-200 rounded-xl p-4">
                <p className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">Upload Report (PDF / Image) — Optional</p>
                {reportFile ? (
                  <div className="flex items-center justify-between bg-blue-50 rounded-lg px-3 py-2">
                    <span className="text-sm text-blue-700 font-medium truncate">{reportFile.name}</span>
                    <button onClick={() => setReportFile(null)} className="text-red-400 hover:text-red-600 ml-2 shrink-0">Remove</button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => fileRef.current?.click()}
                    className="w-full text-sm text-gray-500 hover:text-primary flex items-center justify-center gap-2 py-2"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                    </svg>
                    Click to select file
                  </button>
                )}
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png"
                  className="hidden"
                  onChange={e => setReportFile(e.target.files?.[0] ?? null)}
                />
              </div>
            </div>

            {/* Footer */}
            <div className="p-5 border-t border-gray-100 flex gap-3 shrink-0">
              <button onClick={() => setEnterResultsFor(null)}
                className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-50">
                Cancel
              </button>
              <button
                disabled={submitting || (Object.values(testResults).every(v => !v.trim()) && !labNotes.trim() && !reportFile)}
                onClick={() => submitResults()}
                className="flex-1 bg-green-600 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
              >
                {submitting ? 'Saving…' : 'Save Results'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function LabOrderCard({
  order,
  onAdvance,
  onReject,
}: {
  order: LabOrder
  onAdvance: (args: { id: string; status: string }) => void
  onReject: (id: string) => void
}) {
  const next = STATUS_FLOW[order.status]
  const [reportLoading, setReportLoading] = useState(false)
  const btnColor: Record<string, string> = {
    blue:   'bg-blue-600 hover:bg-blue-700',
    purple: 'bg-purple-600 hover:bg-purple-700',
    green:  'bg-green-600 hover:bg-green-700',
  }
  const canReject = order.status === 'sample_collected' || order.status === 'processing'

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <p className="font-semibold text-gray-900">{order.patient_name || 'Patient'}</p>
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[order.status] || ''}`}>
              {order.status.replace(/_/g, ' ')}
            </span>
          </div>
          <p className="text-xs text-gray-400">
            {order.doctor_name ? `Dr. ${order.doctor_name}` : ''} · {new Date(order.ordered_at).toLocaleTimeString()}
          </p>
          {order.result?.report_url && (
            <button
              disabled={reportLoading}
              onClick={async () => {
                setReportLoading(true)
                try {
                  const url = await labService.getReportUrl(order.id)
                  window.open(url, '_blank', 'noreferrer')
                } finally {
                  setReportLoading(false)
                }
              }}
              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline mt-1.5 disabled:opacity-50"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {reportLoading ? 'Opening…' : 'View Report'}
            </button>
          )}
          <div className="mt-3">
            <p className="text-xs font-medium text-gray-500 mb-1.5">Tests ordered:</p>
            <div className="flex flex-wrap gap-1.5">
              {order.tests.map((t, i) => (
                <span key={i} className="bg-gray-100 text-gray-700 text-xs px-2 py-0.5 rounded-full">
                  {t.test_code ? `${t.test_code} — ${t.test_name}` : t.test}{t.notes ? ` (${t.notes})` : ''}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2 shrink-0">
          {next && (
            <button
              onClick={() => onAdvance({ id: order.id, status: next.next })}
              className={`px-4 py-2 text-white rounded-lg text-sm font-medium ${btnColor[next.color] || 'bg-gray-600'}`}
            >
              {next.label}
            </button>
          )}
          {canReject && (
            <button
              onClick={() => onReject(order.id)}
              className="px-4 py-2 border border-red-200 text-red-600 rounded-lg text-sm font-medium hover:bg-red-50"
            >
              Reject Sample
            </button>
          )}
        </div>
      </div>
    </div>
  )
}


