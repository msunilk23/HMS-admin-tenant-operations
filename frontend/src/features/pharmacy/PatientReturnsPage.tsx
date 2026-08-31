import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { patientReturnService, type PatientReturnCreateInput } from '@/services/returnsService'

const PAGE_SIZE = 20
const errorMessage = (error: unknown) => {
  const detail = typeof error === 'object' && error !== null && 'response' in error
    ? (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail : undefined
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((entry) => typeof entry === 'object' && entry !== null && 'msg' in entry ? String(entry.msg) : String(entry)).join(', ')
  return error instanceof Error ? error.message : 'Unable to complete the request.'
}
const date = (value?: string) => value ? new Date(value).toLocaleDateString('en-IN') : 'Not recorded'

export default function PatientReturnsPage() {
  const queryClient = useQueryClient()
  const idempotencyKey = useRef<string | null>(null)
  const [search, setSearch] = useState('')
  const [dispenseId, setDispenseId] = useState('')
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const eligible = useQuery({ queryKey: ['patient-return-eligible', search], queryFn: () => patientReturnService.eligibleDispenses({ q: search || undefined }) })
  const eligibility = useQuery({ queryKey: ['patient-return-eligibility', dispenseId], queryFn: () => patientReturnService.eligibility(dispenseId), enabled: Boolean(dispenseId) })
  const records = useQuery({ queryKey: ['patient-returns', page, status], queryFn: () => patientReturnService.list({ page, page_size: PAGE_SIZE, status: status || undefined }) })
  const reset = () => { idempotencyKey.current = null; setDispenseId(''); setReason(''); setNotes(''); setQuantities({}) }
  const create = useMutation({
    mutationFn: (payload: PatientReturnCreateInput) => patientReturnService.create(payload),
    onSuccess: (result) => { setMessage(`Patient return ${result.reference_key} created.`); setError(''); reset(); queryClient.invalidateQueries({ queryKey: ['patient-returns'] }); queryClient.invalidateQueries({ queryKey: ['patient-return-eligible'] }); queryClient.invalidateQueries({ queryKey: ['patient-return-eligibility'] }) },
    onError: (mutationError) => setError(errorMessage(mutationError)),
  })
  const refreshReturns = () => {
    queryClient.invalidateQueries({ queryKey: ['patient-returns'] })
    queryClient.invalidateQueries({ queryKey: ['patient-return-eligible'] })
    queryClient.invalidateQueries({ queryKey: ['patient-return-eligibility'] })
  }
  const validateReturn = useMutation({
    mutationFn: patientReturnService.validate,
    onSuccess: (result) => { setError(''); setMessage(`Patient return ${result.reference_key} validated.`); refreshReturns() },
    onError: (mutationError) => setError(errorMessage(mutationError)),
  })
  const acceptReturn = useMutation({
    mutationFn: patientReturnService.accept,
    onSuccess: (result) => { setError(''); setMessage(`Patient return ${result.reference_key} accepted and restocked.`); refreshReturns() },
    onError: (mutationError) => setError(errorMessage(mutationError)),
  })
  const quantityKey = (itemId: string, batchId: string) => `${itemId}:${batchId}`
  const submit = () => {
    if (!eligibility.data || reason.trim().length < 10) { setError('Select an eligible dispense and provide a return reason of at least 10 characters.'); return }
    const items = eligibility.data.items.map((item) => {
      const batch_allocations = item.allocations.map((allocation) => ({ inventory_batch_id: allocation.inventory_batch_id, returned_quantity: Number(quantities[quantityKey(item.dispense_item_id, allocation.inventory_batch_id)] || 0) })).filter((allocation) => allocation.returned_quantity > 0)
      return { dispense_item_id: item.dispense_item_id, returned_quantity: batch_allocations.reduce((total, allocation) => total + allocation.returned_quantity, 0), restockable: true, batch_allocations }
    }).filter((item) => item.returned_quantity > 0)
    if (!items.length) { setError('Enter a positive quantity for at least one original batch.'); return }
    for (const item of eligibility.data.items) {
      const selected = items.find((candidate) => candidate.dispense_item_id === item.dispense_item_id)
      if (selected && selected.returned_quantity > Number(item.remaining_returnable_quantity)) { setError(`${item.medicine_name || 'Medicine'} exceeds its remaining returnable quantity.`); return }
      for (const allocation of selected?.batch_allocations || []) {
        const source = item.allocations.find((candidate) => candidate.inventory_batch_id === allocation.inventory_batch_id)
        if (!source || allocation.returned_quantity > Number(source.remaining_returnable_quantity)) { setError('A batch quantity exceeds its remaining returnable quantity.'); return }
      }
    }
    idempotencyKey.current ??= crypto.randomUUID()
    setError('')
    create.mutate({ dispense_id: eligibility.data.dispense_id, return_reason: reason.trim(), notes: notes.trim() || undefined, idempotency_key: idempotencyKey.current, items })
  }

  return <div className="p-6 space-y-6">
    <div><h1 className="text-2xl font-bold text-gray-900">Patient Returns</h1><p className="mt-1 text-sm text-gray-500">Return medicines to their original dispense batches.</p></div>
    <div className="grid gap-6 xl:grid-cols-[minmax(420px,0.9fr)_minmax(0,1.1fr)]">
      <section className="space-y-4 rounded-xl border border-gray-200 bg-white p-5"><h2 className="font-semibold text-gray-900">New return</h2>
        <label className="block text-sm text-gray-700">Search patient or UHID<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Patient name or UHID" className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2" /></label>
        <label className="block text-sm text-gray-700">Eligible dispensing record<select aria-label="Eligible dispensing record" value={dispenseId} onChange={(event) => { idempotencyKey.current = null; setDispenseId(event.target.value); setQuantities({}); setError('') }} disabled={eligible.isLoading} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2"><option value="">{eligible.isLoading ? 'Loading eligible dispenses...' : 'Select a dispense'}</option>{eligible.data?.map((dispense) => <option key={dispense.dispense_id} value={dispense.dispense_id}>{dispense.patient_name} ({dispense.patient_uhid}) - {dispense.dispense_reference}</option>)}</select></label>
        {eligible.isError && <p role="alert" className="text-sm text-rose-700">{errorMessage(eligible.error)}</p>}
        {eligibility.isLoading && <p className="text-sm text-gray-500">Loading original allocations...</p>}
        {eligibility.data && <><div className="rounded-lg bg-slate-50 p-3 text-sm text-gray-700"><p className="font-medium">{eligibility.data.patient_name || 'Patient'}</p><p>Prescription: {eligibility.data.prescription_id || 'Not recorded'}</p><p>Dispense: {eligibility.data.dispense_reference} | Invoice: {eligibility.data.invoice_id || 'Not recorded'}</p></div>{eligibility.data.items.map((item) => <div key={item.dispense_item_id} className="space-y-2 border-t border-gray-200 pt-3"><p className="font-medium text-gray-900">{item.medicine_name || 'Medicine'}</p><p className="text-xs text-gray-500">Originally dispensed {item.originally_dispensed_quantity}; previously returned {item.previously_returned_quantity}; remaining {item.remaining_returnable_quantity}</p>{item.allocations.map((allocation) => { const key = quantityKey(item.dispense_item_id, allocation.inventory_batch_id); return <label key={key} className="grid grid-cols-[1fr_110px] gap-3 rounded-lg border border-gray-200 p-3 text-sm"><span><b>Batch {allocation.batch_number}</b><span className="block text-xs text-gray-500">Expiry {date(allocation.expiry_date)}; dispensed {allocation.originally_dispensed_quantity}; returned {allocation.previously_returned_quantity}; remaining {allocation.remaining_returnable_quantity}</span></span><input aria-label={`Return quantity for ${allocation.batch_number}`} type="number" min="0" max={allocation.remaining_returnable_quantity} step="0.001" value={quantities[key] ?? ''} onChange={(event) => { idempotencyKey.current = null; setQuantities((current) => ({ ...current, [key]: event.target.value })) }} className="rounded-lg border border-gray-300 px-2 py-1" /></label>})}</div>)}</>}
        <label className="block text-sm text-gray-700">Return reason<input value={reason} onChange={(event) => { idempotencyKey.current = null; setReason(event.target.value) }} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2" /></label>
        <label className="block text-sm text-gray-700">Notes<textarea value={notes} onChange={(event) => { idempotencyKey.current = null; setNotes(event.target.value) }} rows={3} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2" /></label>
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}{message && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{message}</p>}
        <button type="button" onClick={submit} disabled={create.isPending || !eligibility.data} className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60">{create.isPending ? 'Submitting...' : 'Submit return'}</button>
      </section>
      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 p-4"><h2 className="font-semibold text-gray-900">Return log</h2><div className="flex gap-2"><select aria-label="Return status filter" value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} className="rounded-lg border border-gray-300 px-2 py-1 text-sm"><option value="">All statuses</option><option value="REQUESTED">Requested</option><option value="VALIDATED">Validated</option><option value="REFUND_PENDING">Refund pending</option><option value="REFUNDED">Refunded</option><option value="REJECTED">Rejected</option></select><button type="button" onClick={() => records.refetch()} className="rounded-lg border border-gray-300 px-3 py-1 text-sm">Refresh</button></div></div>
        {records.isLoading ? <p className="p-5 text-sm text-gray-500">Loading returns...</p> : records.isError ? <p role="alert" className="p-5 text-sm text-rose-700">{errorMessage(records.error)}</p> : records.data?.items.length === 0 ? <p className="p-5 text-sm text-gray-500">No patient returns match these filters.</p> : <div className="divide-y divide-gray-100">{records.data?.items.map((record) => <article key={record.id} className="space-y-2 p-4"><div className="flex justify-between gap-3"><div><p className="font-semibold text-gray-900">{record.reference_key}</p><p className="text-xs text-gray-500">Dispense {record.dispense_id} | Invoice {record.invoice_id || 'Not recorded'}</p></div><span className="rounded-full bg-slate-100 px-2 py-1 text-xs">{record.status}</span></div><p className="text-sm text-gray-600">{record.return_reason}</p><p className="text-xs text-gray-500">Requested {date(record.requested_at)} by {record.requested_by || 'Unknown'} | Validated {date(record.validated_at)} by {record.validated_by || 'Not recorded'} | Accepted {date(record.accepted_at)} by {record.accepted_by || 'Not recorded'}</p><p className="text-xs text-gray-500">{record.items.map((item) => `${item.returned_quantity} (${item.inventory_batch_id || 'allocated batch'})`).join(', ')}</p>{record.status === 'REQUESTED' && <button type="button" disabled={validateReturn.isPending || acceptReturn.isPending} onClick={() => validateReturn.mutate(record.id)} className="rounded border px-3 py-1 text-xs disabled:opacity-50">Validate</button>}{record.status === 'VALIDATED' && <button type="button" disabled={validateReturn.isPending || acceptReturn.isPending} onClick={() => acceptReturn.mutate(record.id)} className="rounded border px-3 py-1 text-xs disabled:opacity-50">Accept</button>}</article>)}</div>}
        {(records.data?.total_pages ?? 0) > 1 && <div className="flex justify-between border-t border-gray-200 p-3 text-sm"><button type="button" disabled={page === 1} onClick={() => setPage((current) => current - 1)} className="rounded border px-2 py-1 disabled:opacity-50">Previous</button><span>Page {page} of {records.data?.total_pages}</span><button type="button" disabled={page >= (records.data?.total_pages ?? 0)} onClick={() => setPage((current) => current + 1)} className="rounded border px-2 py-1 disabled:opacity-50">Next</button></div>}
      </section>
    </div>
  </div>
}