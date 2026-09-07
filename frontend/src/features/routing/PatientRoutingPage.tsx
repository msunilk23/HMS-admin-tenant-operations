import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { routingService, type PatientRouteStep } from '@/services/routingService'

const destinationLabel: Record<string, string> = {
  PHARMACY: 'Pharmacy', LAB: 'Laboratory', BILLING: 'Billing', EXIT: 'Exit',
}

function deadlineLabel(value?: string) {
  if (!value) return 'No deadline'
  const delta = new Date(value).getTime() - Date.now()
  if (delta <= 0) return 'Overdue'
  const minutes = Math.ceil(delta / 60_000)
  return `${minutes} min remaining`
}

export default function PatientRoutingPage() {
  const [visitId, setVisitId] = useState('')
  const [lookupId, setLookupId] = useState('')
  const qc = useQueryClient()
  const routeQuery = useQuery({
    queryKey: ['patient-route', lookupId],
    queryFn: () => routingService.getForVisit(lookupId),
    enabled: !!lookupId,
  })
  const documentsQuery = useQuery({
    queryKey: ['prescription-documents', lookupId],
    queryFn: () => routingService.listPrescriptionDocuments(lookupId),
    enabled: !!lookupId,
  })
  const awaitingQuery = useQuery({
    queryKey: ['routing-steps', 'AWAITING_PATIENT'],
    queryFn: () => routingService.listSteps({ status: 'AWAITING_PATIENT' }),
    refetchInterval: 30_000,
  })
  const action = useMutation({
    mutationFn: ({ step, operation }: { step: PatientRouteStep; operation: 'present' | 'start' | 'complete' }) =>
      operation === 'present' ? routingService.present(step.id) : operation === 'start' ? routingService.start(step.id) : routingService.complete(step.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['patient-route'] })
      qc.invalidateQueries({ queryKey: ['routing-steps'] })
    },
  })

  const findVisit = (event: React.FormEvent) => {
    event.preventDefault()
    setLookupId(visitId.trim())
  }
  const printPrescription = async () => {
    const document = documentsQuery.data?.find(item => item.is_current) ?? documentsQuery.data?.at(-1)
    if (!document) return
    const blob = await routingService.downloadPrescription(lookupId, document.version)
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
  const route = routeQuery.data
  const visibleSteps = route?.steps ?? awaitingQuery.data ?? []

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <header>
        <p className="text-xs uppercase tracking-wider text-primary font-semibold">PF-1</p>
        <h1 className="text-2xl font-semibold text-gray-900">Patient Routing</h1>
        <p className="text-sm text-gray-500 mt-1">Find a completed encounter and confirm where the patient presents.</p>
      </header>

      <form onSubmit={findVisit} className="flex flex-col sm:flex-row gap-3">
        <label className="sr-only" htmlFor="routing-visit-id">Visit ID</label>
        <input id="routing-visit-id" value={visitId} onChange={e => setVisitId(e.target.value)} placeholder="Enter Visit ID" className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        <button type="submit" className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium">Find route</button>
      </form>

      {routeQuery.isError && <p className="text-sm text-red-600">Routing journey not found for this Visit.</p>}
      {route && <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
        <div className="flex flex-wrap justify-between gap-2">
          <div><h2 className="font-semibold text-gray-900">Visit {route.visit_id}</h2><p className="text-xs text-gray-500">UHID {route.uhid} · Journey {route.status}</p></div>
          <div className="flex items-center gap-2"><span className="text-xs px-2 py-1 rounded-full bg-green-50 text-green-700">OPD closed</span>{documentsQuery.data?.length ? <button onClick={printPrescription} className="px-3 py-1.5 rounded-lg border border-gray-300 text-xs font-medium text-gray-700">Print finalized prescription</button> : null}</div>
        </div>
      </section>}

      <section className="space-y-3">
        <div className="flex items-center justify-between"><h2 className="font-semibold text-gray-900">Awaiting patient presentation</h2><span className="text-xs text-gray-500">{visibleSteps.filter(step => step.status === 'AWAITING_PATIENT').length} steps</span></div>
        {visibleSteps.length === 0 ? <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-sm text-gray-400">No awaiting routes.</div> : visibleSteps.map(step => (
          <div key={step.id} className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col md:flex-row md:items-center gap-4">
            <div className="flex-1"><div className="flex items-center gap-2"><h3 className="font-medium text-gray-900">{destinationLabel[step.destination] ?? step.destination}</h3><span className="text-xs px-2 py-1 rounded-full bg-amber-50 text-amber-700">{step.status}</span></div><p className="text-xs text-gray-500 mt-1">Visit {step.visit_id} · {deadlineLabel(step.presentation_deadline_at)}{step.late_presentation ? ' · late presentation' : ''}</p></div>
            <div className="flex flex-wrap gap-2">
              {(step.status === 'AWAITING_PATIENT' || step.status === 'NOT_PRESENTED') && <button onClick={() => action.mutate({ step, operation: 'present' })} disabled={action.isPending} className="px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-medium">{step.status === 'NOT_PRESENTED' ? 'Reopen late' : 'Confirm arrival'}</button>}
              {(step.status === 'PRESENTED' || step.status === 'PRESENTED_LATE') && <button onClick={() => action.mutate({ step, operation: 'start' })} disabled={action.isPending} className="px-3 py-1.5 rounded-lg border border-primary text-primary text-xs font-medium">Start service</button>}
              {step.status === 'IN_SERVICE' && <button onClick={() => action.mutate({ step, operation: 'complete' })} disabled={action.isPending} className="px-3 py-1.5 rounded-lg bg-green-600 text-white text-xs font-medium">Complete service</button>}
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}