import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, ShieldAlert, Trash2, Undo2 } from 'lucide-react'
import { useAuthStore } from '@/features/auth/authStore'
import { quarantineService, type CreateQuarantineInput, type DisposeQuarantineInput, type QuarantineReason, type StockQuarantine } from '@/services/quarantineService'

const errorMessage = (error: unknown) => {
  const detail = typeof error === 'object' && error !== null && 'response' in error
    ? (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail : undefined
  return typeof detail === 'string' ? detail : error instanceof Error ? error.message : 'Unable to complete the request.'
}

const formatDate = (value?: string) => value ? new Date(value).toLocaleString() : 'Not recorded'

export default function QuarantinePage() {
  const queryClient = useQueryClient()
  const user = useAuthStore((state) => state.user)
  const idempotencyKey = useRef<string | null>(null)
  const [batchId, setBatchId] = useState('')
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState<QuarantineReason>('INVESTIGATION')
  const [notes, setNotes] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [releaseReason, setReleaseReason] = useState('')
  const [disposalReason, setDisposalReason] = useState('')
  const [disposalMethod, setDisposalMethod] = useState('')
  const [disposalDate, setDisposalDate] = useState(new Date().toISOString().slice(0, 10))
  const [witnessedBy, setWitnessedBy] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const canCreate = ['pharmacist', 'store_manager', 'hospital_admin'].includes(user?.role || '')
  const canApprove = ['store_manager', 'hospital_admin'].includes(user?.role || '')
  const batches = useQuery({ queryKey: ['quarantine-batches'], queryFn: () => quarantineService.batches() })
  const records = useQuery({ queryKey: ['quarantines', statusFilter], queryFn: () => quarantineService.list({ status: statusFilter || undefined }) })
  const selected = records.data?.items.find((record) => record.id === selectedId) || records.data?.items[0]
  const selectedBatch = batches.data?.find((batch) => batch.id === batchId)
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['quarantines'] })
    queryClient.invalidateQueries({ queryKey: ['quarantine-batches'] })
    queryClient.invalidateQueries({ queryKey: ['inventory-batches'] })
  }
  const create = useMutation({
    mutationFn: (payload: CreateQuarantineInput) => quarantineService.create(payload),
    onSuccess: (record) => { setSelectedId(record.id); setMessage(`${record.reference_key} quarantined.`); setError(''); setBatchId(''); setQuantity(''); setNotes(''); idempotencyKey.current = null; refresh() },
    onError: (mutationError) => setError(errorMessage(mutationError)),
  })
  const release = useMutation({ mutationFn: ({ id, reasonText }: { id: string; reasonText: string }) => quarantineService.release(id, reasonText), onSuccess: (record) => { setMessage(`${record.reference_key} released.`); setError(''); setReleaseReason(''); refresh() }, onError: (mutationError) => setError(errorMessage(mutationError)) })
  const dispose = useMutation({ mutationFn: ({ id, payload }: { id: string; payload: DisposeQuarantineInput }) => quarantineService.dispose(id, payload), onSuccess: (record) => { setMessage(`${record.reference_key} disposed.`); setError(''); setDisposalReason(''); setDisposalMethod(''); setWitnessedBy(''); refresh() }, onError: (mutationError) => setError(errorMessage(mutationError)) })
  const resetLogicalRequest = () => { idempotencyKey.current = null; setError('') }
  const submit = () => {
    const numericQuantity = Number(quantity)
    if (!selectedBatch) return setError('Select an eligible inventory batch.')
    if (!Number.isFinite(numericQuantity) || numericQuantity <= 0) return setError('Quantity must be greater than zero.')
    if (numericQuantity > Number(selectedBatch.available_quantity)) return setError('Quantity exceeds available saleable stock.')
    idempotencyKey.current ??= crypto.randomUUID()
    create.mutate({ inventory_batch_id: selectedBatch.id, quantity: numericQuantity, reason, notes: notes.trim() || undefined, idempotency_key: idempotencyKey.current })
  }
  const submitRelease = (record: StockQuarantine) => {
    if (releaseReason.trim().length < 10) return setError('Release evidence must be at least 10 characters.')
    release.mutate({ id: record.id, reasonText: releaseReason.trim() })
  }
  const submitDisposal = (record: StockQuarantine) => {
    if (disposalReason.trim().length < 10 || disposalMethod.trim().length < 3 || !disposalDate || !witnessedBy) return setError('Complete disposal reason, method, date, and witness.')
    dispose.mutate({ id: record.id, payload: { disposal_reason: disposalReason.trim(), disposal_method: disposalMethod.trim(), disposal_date: disposalDate, witnessed_by: witnessedBy.trim() } })
  }
  const pending = create.isPending || release.isPending || dispose.isPending
  const mayApproveSelected = selected?.status === 'QUARANTINED' && canApprove && selected.quarantined_by !== user?.id

  return <div className="space-y-6 p-6">
    <header><h1 className="text-2xl font-bold text-gray-900">Stock Quarantine</h1><p className="mt-1 text-sm text-gray-500">Isolate non-saleable stock and document release or final disposal.</p></header>
    {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
    {message && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</p>}
    <div className="grid gap-6 xl:grid-cols-[minmax(340px,0.8fr)_minmax(0,1.2fr)]">
      {canCreate && <section className="space-y-4 rounded-lg border border-gray-200 bg-white p-5"><h2 className="flex items-center gap-2 font-semibold"><ShieldAlert className="h-5 w-5 text-amber-600" />Create quarantine</h2>
        {batches.isLoading ? <p className="text-sm text-gray-500">Loading saleable batches...</p> : batches.isError ? <p role="alert" className="text-sm text-rose-700">{errorMessage(batches.error)}</p> : <label className="block text-sm">Batch and location<select aria-label="Batch and location" value={batchId} onChange={(event) => { setBatchId(event.target.value); resetLogicalRequest() }} className="mt-1 w-full rounded-lg border px-3 py-2"><option value="">Select batch</option>{batches.data?.map((batch) => <option key={batch.id} value={batch.id}>{batch.batch_number} | {batch.pharmacy_location_id} | available {batch.available_quantity}</option>)}</select></label>}
        {selectedBatch && <div className="rounded-lg bg-slate-50 p-3 text-sm"><b>{selectedBatch.batch_number}</b><p>Saleable quantity: {selectedBatch.available_quantity}</p><p>Expiry: {selectedBatch.expiry_date || 'Not recorded'}</p></div>}
        <label className="block text-sm">Quantity<input aria-label="Quarantine quantity" type="number" min="0.001" step="0.001" max={selectedBatch?.available_quantity} value={quantity} onChange={(event) => { setQuantity(event.target.value); resetLogicalRequest() }} className="mt-1 w-full rounded-lg border px-3 py-2" /></label>
        <label className="block text-sm">Reason<select aria-label="Quarantine reason" value={reason} onChange={(event) => { setReason(event.target.value as QuarantineReason); resetLogicalRequest() }} className="mt-1 w-full rounded-lg border px-3 py-2"><option value="INVESTIGATION">Investigation</option><option value="EXPIRED">Expired</option><option value="DAMAGED">Confirmed damaged</option></select></label>
        <label className="block text-sm">Notes<textarea aria-label="Quarantine notes" rows={3} value={notes} onChange={(event) => { setNotes(event.target.value); resetLogicalRequest() }} className="mt-1 w-full rounded-lg border px-3 py-2" /></label>
        <button type="button" onClick={submit} disabled={pending || !selectedBatch} className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60">{create.isPending ? 'Quarantining...' : 'Quarantine stock'}</button>
      </section>}
      <section className="overflow-hidden rounded-lg border border-gray-200 bg-white"><div className="flex items-center justify-between border-b p-4"><h2 className="font-semibold">Quarantine register</h2><select aria-label="Quarantine status filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded border px-2 py-1 text-sm"><option value="">All statuses</option><option value="QUARANTINED">Quarantined</option><option value="RELEASED">Released</option><option value="DISPOSED">Disposed</option></select></div>
        {records.isLoading ? <p className="p-5 text-sm text-gray-500">Loading quarantine records...</p> : records.isError ? <p role="alert" className="p-5 text-sm text-rose-700">{errorMessage(records.error)}</p> : records.data?.items.length === 0 ? <p className="p-5 text-sm text-gray-500">No quarantine records match this filter.</p> : <div className="divide-y">{records.data?.items.map((record) => <button type="button" key={record.id} onClick={() => setSelectedId(record.id)} className={`grid w-full grid-cols-[1fr_auto] gap-3 p-4 text-left ${selected?.id === record.id ? 'bg-amber-50' : 'hover:bg-gray-50'}`}><span><b>{record.reference_key}</b><span className="block text-xs text-gray-500">{record.reason} | batch {record.inventory_batch_id} | remaining {record.remaining_quantity}</span></span><span className="text-xs font-semibold">{record.status}</span></button>)}</div>}
      </section>
    </div>
    {selected && <section className="space-y-5 border-t border-gray-200 pt-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{selected.reference_key}</h2><p className="text-sm text-gray-600">{selected.reason} | quarantined {selected.total_quantity_quarantined} | remaining {selected.remaining_quantity}</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold">{selected.status}</span></div>
      <div className="grid gap-3 text-sm md:grid-cols-3"><div><b>Initiated by</b><p>{selected.quarantined_by || 'Unknown'}</p><p className="text-gray-500">{formatDate(selected.quarantined_at)}</p></div><div><b>Approved by</b><p>{selected.approved_by || 'Pending'}</p><p className="text-gray-500">{formatDate(selected.approved_at)}</p></div><div><b>Outcome</b><p>{selected.approved_action || 'Awaiting action'}</p><p className="text-gray-500">{selected.release_reason || selected.disposal_reason || selected.notes || 'No notes'}</p></div></div>
      {mayApproveSelected && <div className="grid gap-5 lg:grid-cols-2">
        {selected.reason === 'INVESTIGATION' && <div className="space-y-3 rounded-lg border border-emerald-200 p-4"><h3 className="flex items-center gap-2 font-semibold"><Undo2 className="h-4 w-4" />Release investigation stock</h3><textarea aria-label="Release evidence" value={releaseReason} onChange={(event) => setReleaseReason(event.target.value)} rows={3} className="w-full rounded-lg border px-3 py-2" /><button type="button" onClick={() => submitRelease(selected)} disabled={pending} className="rounded-lg border border-emerald-600 px-3 py-2 text-sm text-emerald-700 disabled:opacity-60">Release stock</button></div>}
        <div className="space-y-3 rounded-lg border border-rose-200 p-4"><h3 className="flex items-center gap-2 font-semibold"><Trash2 className="h-4 w-4" />Dispose quarantined stock</h3><textarea aria-label="Disposal reason" value={disposalReason} onChange={(event) => setDisposalReason(event.target.value)} rows={2} className="w-full rounded-lg border px-3 py-2" /><input aria-label="Disposal method" placeholder="Disposal method" value={disposalMethod} onChange={(event) => setDisposalMethod(event.target.value)} className="w-full rounded-lg border px-3 py-2" /><input aria-label="Disposal date" type="date" value={disposalDate} onChange={(event) => setDisposalDate(event.target.value)} className="w-full rounded-lg border px-3 py-2" /><input aria-label="Witness user ID" placeholder="Witness user ID" value={witnessedBy} onChange={(event) => setWitnessedBy(event.target.value)} className="w-full rounded-lg border px-3 py-2" /><button type="button" onClick={() => submitDisposal(selected)} disabled={pending} className="rounded-lg border border-rose-600 px-3 py-2 text-sm text-rose-700 disabled:opacity-60">Dispose stock</button></div>
      </div>}
      {selected.status === 'RELEASED' && <p className="flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4" />Released {formatDate(selected.released_at)}</p>}
      {selected.status === 'DISPOSED' && <p className="flex items-center gap-2 text-sm text-rose-700"><AlertTriangle className="h-4 w-4" />Disposed by {selected.disposed_by}; witnessed by {selected.witnessed_by}; {selected.disposal_method}; {selected.disposal_date}</p>}
      {selected.status === 'QUARANTINED' && canApprove && selected.quarantined_by === user?.id && <p className="text-sm text-amber-700">A different manager or administrator must approve release or disposal.</p>}
    </section>}
  </div>
}