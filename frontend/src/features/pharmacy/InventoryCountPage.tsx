import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, ClipboardCheck, History, Play, RefreshCw, Scale } from 'lucide-react'
import { useAuthStore } from '@/features/auth/authStore'
import { p33Service, type CountDetail, type CountType, type StockCount } from '@/services/p33Service'

const messageOf = (error: unknown) => typeof error === 'object' && error && 'response' in error
  ? String((error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Request failed')
  : error instanceof Error ? error.message : 'Request failed'

export default function InventoryCountPage() {
  const user = useAuthStore(state => state.user)
  const client = useQueryClient()
  const keys = useRef<Record<string, string>>({})
  const key = (name: string) => keys.current[name] ??= crypto.randomUUID()
  const [selectedId, setSelectedId] = useState('')
  const [locationId, setLocationId] = useState('')
  const [countType, setCountType] = useState<CountType>('FULL')
  const [selectedBatches, setSelectedBatches] = useState<string[]>([])
  const [notes, setNotes] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [actionReason, setActionReason] = useState('')
  const [assignee, setAssignee] = useState('')
  const [applyConfirm, setApplyConfirm] = useState(false)

  const locations = useQuery({ queryKey: ['p33', 'locations'], queryFn: p33Service.locations })
  const batches = useQuery({ queryKey: ['p33', 'batches', locationId], queryFn: () => p33Service.batches(locationId), enabled: Boolean(locationId) })
  const counts = useQuery({ queryKey: ['p33', 'counts', statusFilter], queryFn: () => p33Service.counts({ status: statusFilter || undefined }) })
  const detail = useQuery({ queryKey: ['p33', 'count', selectedId], queryFn: () => p33Service.count(selectedId), enabled: Boolean(selectedId) })
  const current = detail.data
  const manager = user?.role === 'store_manager'
  const counter = ['pharmacist', 'store_manager'].includes(user?.role || '')

  const done = (message: string, count?: StockCount) => {
    setError(''); setSuccess(message); keys.current = {}; setApplyConfirm(false)
    if (count) setSelectedId(count.id)
    client.invalidateQueries({ queryKey: ['p33'] })
  }
  const failed = (reason: unknown) => { setSuccess(''); setError(messageOf(reason)) }
  const create = useMutation({ mutationFn: () => p33Service.create({ pharmacy_location_id: locationId, count_type: countType, selected_batch_ids: countType === 'FULL' ? [] : selectedBatches, notes: notes || undefined }, key('create')), onSuccess: count => done(`${count.reference_key} created`, count), onError: failed })
  const transition = useMutation({ mutationFn: ({ count, action }: { count: StockCount; action: 'start' | 'submit' | 'startRecount' | 'resubmit' }) => ({ start: p33Service.start, submit: p33Service.submit, startRecount: p33Service.startRecount, resubmit: p33Service.resubmit }[action])(count.id, key(`${action}-${count.id}`)), onSuccess: count => done(`${count.reference_key} updated`, count), onError: failed })
  const approve = useMutation({ mutationFn: (count: StockCount) => p33Service.approve(count.id, actionReason, key(`approve-${count.id}`)), onSuccess: count => done(`${count.reference_key} approved`, count), onError: failed })
  const apply = useMutation({ mutationFn: (count: StockCount) => p33Service.apply(count.id, actionReason, key(`apply-${count.id}`)), onSuccess: count => done(`${count.reference_key} adjustments applied`, count), onError: failed })
  const recount = useMutation({ mutationFn: (count: StockCount) => p33Service.requestRecount(count.id, { assigned_to: assignee, reason: actionReason }, key(`recount-${count.id}`)), onSuccess: count => done(`${count.reference_key} assigned for recount`, count), onError: failed })
  const cancel = useMutation({ mutationFn: (count: StockCount) => p33Service.cancel(count.id, actionReason, key(`cancel-${count.id}`)), onSuccess: count => done(`${count.reference_key} cancelled`, count), onError: failed })
  const pending = create.isPending || transition.isPending || approve.isPending || apply.isPending || recount.isPending || cancel.isPending

  return <div className="space-y-5 p-6">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="flex items-center gap-2 text-2xl font-bold text-gray-900"><ClipboardCheck className="h-6 w-6 text-emerald-700" />Inventory Counts</h1><p className="mt-1 text-sm text-gray-500">Physical count, variance review, recount, and controlled stock adjustment.</p></div>
      <select aria-label="Filter counts by status" value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className="rounded border bg-white p-2 text-sm"><option value="">All statuses</option>{['CREATED', 'IN_PROGRESS', 'SUBMITTED', 'RECOUNT_REQUIRED', 'RECOUNT_IN_PROGRESS', 'RESUBMITTED', 'APPROVED', 'APPLIED', 'CANCELLED'].map(value => <option key={value}>{value}</option>)}</select>
    </header>
    {error && <p role="alert" className="border-l-4 border-rose-600 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    {success && <p role="status" className="border-l-4 border-emerald-600 bg-emerald-50 p-3 text-sm text-emerald-800">{success}</p>}

    <div className="grid gap-5 xl:grid-cols-[minmax(300px,.75fr)_minmax(0,1.4fr)]">
      <div className="space-y-5">
        {counter && <section className="space-y-3 border bg-white p-4">
          <h2 className="font-semibold">Create count</h2>
          <select aria-label="Pharmacy location" value={locationId} onChange={event => { setLocationId(event.target.value); setSelectedBatches([]) }} className="w-full rounded border p-2"><option value="">Select location</option>{locations.data?.map(location => <option key={location.id} value={location.id}>{location.location_name}</option>)}</select>
          <div className="grid grid-cols-3 gap-1" role="group" aria-label="Count type">{(['FULL', 'PARTIAL', 'SAMPLE'] as CountType[]).map(value => <button key={value} type="button" aria-pressed={countType === value} onClick={() => { setCountType(value); setSelectedBatches([]) }} className={`border px-2 py-2 text-xs font-semibold ${countType === value ? 'border-emerald-700 bg-emerald-700 text-white' : 'bg-white'}`}>{value}</button>)}</div>
          {countType !== 'FULL' && <fieldset className="max-h-44 space-y-1 overflow-y-auto border p-2"><legend className="px-1 text-xs font-semibold">Count scope</legend>{batches.isLoading ? <p className="text-sm">Loading batches...</p> : batches.data?.length ? batches.data.map(batch => <label key={batch.id} className="flex items-center gap-2 py-1 text-sm"><input type="checkbox" checked={selectedBatches.includes(batch.id)} onChange={event => setSelectedBatches(values => event.target.checked ? [...values, batch.id] : values.filter(id => id !== batch.id))} />{batch.batch_number} <span className="text-gray-500">({Number(batch.available_quantity) + Number(batch.reserved_quantity)})</span></label>) : <p className="text-sm text-gray-500">No batches at this location.</p>}</fieldset>}
          <textarea aria-label="Count notes" value={notes} onChange={event => setNotes(event.target.value)} placeholder="Optional count notes" className="w-full rounded border p-2 text-sm" />
          <button disabled={pending || !locationId || (countType !== 'FULL' && selectedBatches.length === 0)} onClick={() => create.mutate()} className="w-full rounded bg-emerald-700 p-2 text-sm font-semibold text-white disabled:opacity-50">{create.isPending ? 'Creating...' : 'Create count'}</button>
        </section>}

        <section className="border bg-white"><h2 className="border-b p-4 font-semibold">Count register</h2>{counts.isLoading ? <p className="p-4">Loading counts...</p> : counts.isError ? <p role="alert" className="p-4 text-rose-700">{messageOf(counts.error)}</p> : counts.data?.items.length ? counts.data.items.map(count => <button key={count.id} onClick={() => setSelectedId(count.id)} className={`flex w-full justify-between gap-3 border-b p-4 text-left ${selectedId === count.id ? 'bg-emerald-50' : 'bg-white'}`}><span><b className="block">{count.reference_key}</b><small>{count.count_type} | {new Date(count.created_at).toLocaleDateString()}</small></span><b className="text-xs">{count.status}</b></button>) : <p className="p-4 text-sm text-gray-500">No inventory counts found.</p>}</section>
      </div>

      <section className="min-w-0 border bg-white">
        {!selectedId ? <div className="grid min-h-72 place-items-center p-8 text-center text-gray-500"><div><Scale className="mx-auto mb-3 h-8 w-8" /><p>Select a count to inspect its snapshot and workflow.</p></div></div> : detail.isLoading ? <p className="p-6">Loading count...</p> : detail.isError ? <p role="alert" className="p-6 text-rose-700">{messageOf(detail.error)}</p> : current && <CountWorkspace count={current} userId={user?.id || ''} manager={manager} counter={counter} pending={pending} actionReason={actionReason} setActionReason={setActionReason} assignee={assignee} setAssignee={setAssignee} applyConfirm={applyConfirm} setApplyConfirm={setApplyConfirm} actionKey={key} done={done} failed={failed} transition={transition.mutate} approve={() => approve.mutate(current)} apply={() => apply.mutate(current)} recount={() => recount.mutate(current)} cancel={() => cancel.mutate(current)} />}
      </section>
    </div>
  </div>
}

type WorkspaceProps = { count: StockCount; userId: string; manager: boolean; counter: boolean; pending: boolean; actionReason: string; setActionReason: (value: string) => void; assignee: string; setAssignee: (value: string) => void; applyConfirm: boolean; setApplyConfirm: (value: boolean) => void; actionKey: (name: string) => string; done: (message: string) => void; failed: (error: unknown) => void; transition: (input: { count: StockCount; action: 'start' | 'submit' | 'startRecount' | 'resubmit' }) => void; approve: () => void; apply: () => void; recount: () => void; cancel: () => void }

function CountWorkspace({ count, userId, manager, counter, pending, actionReason, setActionReason, assignee, setAssignee, applyConfirm, setApplyConfirm, actionKey, done, failed, transition, approve, apply, recount, cancel }: WorkspaceProps) {
  const client = useQueryClient()
  const submitting = useRef(new Set<string>())
  const [values, setValues] = useState<Record<string, string>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [unexpectedBatch, setUnexpectedBatch] = useState('')
  const [unexpectedQuantity, setUnexpectedQuantity] = useState('')
  const [unexpectedEvidence, setUnexpectedEvidence] = useState('')
  const locationBatches = useQuery({ queryKey: ['p33', 'all-batches', count.pharmacy_location_id], queryFn: () => p33Service.batches(count.pharmacy_location_id, false), enabled: count.status === 'IN_PROGRESS' && counter })
  const record = useMutation({ mutationFn: (detail: CountDetail) => p33Service.record(count.id, detail.id, { physical_quantity: Number(values[detail.id]), version: detail.version, variance_reason: reasons[detail.id] || undefined }, actionKey(`record-${detail.id}-${detail.version}`)), onSuccess: () => { done('Physical quantity recorded'); client.invalidateQueries({ queryKey: ['p33', 'count', count.id] }) }, onError: failed })
  const addUnexpected = useMutation({ mutationFn: () => p33Service.addUnexpected(count.id, { inventory_batch_id: unexpectedBatch, physical_quantity: Number(unexpectedQuantity), evidence: unexpectedEvidence }, actionKey(`unexpected-${unexpectedBatch}`)), onSuccess: () => { setUnexpectedBatch(''); setUnexpectedQuantity(''); setUnexpectedEvidence(''); done('Unexpected stock recorded'); client.invalidateQueries({ queryKey: ['p33', 'count', count.id] }) }, onError: failed })
  const latestRecount = count.recounts?.at(-1)
  const recountRecord = useMutation({ mutationFn: (detail: CountDetail) => { const recountValue = latestRecount?.details.find(value => value.count_detail_id === detail.id); return p33Service.recordRecount(count.id, detail.id, { physical_quantity: Number(values[detail.id]), version: recountValue?.version || 1, variance_reason: reasons[detail.id] || undefined }, actionKey(`recount-value-${detail.id}-${recountValue?.version || 1}`)) }, onSuccess: () => { done('Recount quantity recorded'); client.invalidateQueries({ queryKey: ['p33', 'count', count.id] }) }, onError: failed })
  const canRecord = count.status === 'IN_PROGRESS' && counter
  const assignedRecount = count.status === 'RECOUNT_IN_PROGRESS' && latestRecount?.assigned_to === userId
  const allEntered = count.details?.every(detail => detail.physical_quantity !== undefined && detail.physical_quantity !== null)
  const allRecounted = latestRecount?.details.every(detail => detail.physical_quantity !== undefined && detail.physical_quantity !== null)
  const makerCheckerBlocked = count.initiated_by === userId || count.completed_by === userId || count.details?.some(detail => detail.counted_by === userId) || count.recounts?.some(recount => recount.assigned_to === userId || recount.details.some(detail => detail.counted_by === userId))
  const canCancel = manager || ['CREATED', 'IN_PROGRESS'].includes(count.status)
  const save = (detail: CountDetail, kind: 'count' | 'recount') => {
    const lock = `${kind}:${detail.id}`
    if (submitting.current.has(lock)) return
    submitting.current.add(lock)
    const release = () => submitting.current.delete(lock)
    if (kind === 'count') record.mutate(detail, { onSettled: release })
    else recountRecord.mutate(detail, { onSettled: release })
  }
  return <div>
    <div className="flex flex-wrap items-start justify-between gap-3 border-b p-5"><div><h2 className="text-lg font-bold">{count.reference_key}</h2><p className="text-sm text-gray-500">{count.count_type} count | tolerance {count.quantity_tolerance_percent}%</p></div><span className="border border-gray-300 bg-gray-50 px-2 py-1 text-xs font-bold">{count.status}</span></div>
    <div className="grid grid-cols-3 border-b bg-gray-50 text-center text-sm"><div className="p-3"><b className="block text-lg">{count.expected_total_quantity}</b>System</div><div className="border-x p-3"><b className="block text-lg">{count.physical_total_quantity}</b>Physical</div><div className="p-3"><b className={`block text-lg ${Number(count.variance_quantity) ? 'text-rose-700' : 'text-emerald-700'}`}>{count.variance_quantity}</b>Variance</div></div>
    <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b text-left"><th className="p-3">Batch</th><th>System</th><th>Physical</th><th>Variance</th><th>Flags</th><th className="p-3">Action</th></tr></thead><tbody>{count.details?.map(detail => <tr key={detail.id} className="border-b align-top"><td className="p-3"><b>{detail.batch_number}</b><small className="block text-gray-500">Available {detail.available_quantity} + reserved {detail.reserved_quantity}</small></td><td className="py-3">{detail.system_quantity}</td><td className="py-3"><input aria-label={`Physical quantity ${detail.batch_number}`} type="number" min="0" value={values[detail.id] ?? (assignedRecount ? latestRecount?.details.find(value => value.count_detail_id === detail.id)?.physical_quantity || '' : detail.physical_quantity || '')} onChange={event => setValues(current => ({ ...current, [detail.id]: event.target.value }))} disabled={!canRecord && !assignedRecount} className="w-24 rounded border p-2 disabled:bg-gray-100" /><input aria-label={`Variance reason ${detail.batch_number}`} value={reasons[detail.id] ?? detail.variance_reason ?? ''} onChange={event => setReasons(current => ({ ...current, [detail.id]: event.target.value }))} disabled={!canRecord && !assignedRecount} placeholder="Reason" className="mt-1 block w-36 rounded border p-1 disabled:bg-gray-100" /></td><td className="py-3 font-semibold">{detail.variance_quantity ?? '-'}</td><td className="py-3">{detail.classifications.map(flag => <span key={flag} className="mr-1 inline-block border bg-amber-50 px-1 py-0.5 text-xs">{flag}</span>)}</td><td className="p-3">{canRecord && <button disabled={record.isPending || values[detail.id] === ''} onClick={() => save(detail, 'count')} className="rounded bg-gray-900 px-3 py-2 text-white disabled:opacity-50">Save</button>}{assignedRecount && <button disabled={recountRecord.isPending || values[detail.id] === ''} onClick={() => save(detail, 'recount')} className="rounded bg-gray-900 px-3 py-2 text-white disabled:opacity-50">Save recount</button>}</td></tr>)}</tbody></table>{!count.details?.length && <p className="p-5 text-gray-500">Start the count to capture its inventory snapshot.</p>}</div>
    {count.status === 'IN_PROGRESS' && counter && <div className="grid gap-2 border-b p-4 md:grid-cols-[1fr_8rem_1.5fr_auto]"><select aria-label="Unexpected stock batch" value={unexpectedBatch} onChange={event => setUnexpectedBatch(event.target.value)} className="rounded border p-2"><option value="">Unexpected zero-system batch</option>{locationBatches.data?.filter(batch => Number(batch.available_quantity) + Number(batch.reserved_quantity) === 0 && !count.details?.some(detail => detail.inventory_batch_id === batch.id)).map(batch => <option key={batch.id} value={batch.id}>{batch.batch_number}</option>)}</select><input aria-label="Unexpected physical quantity" type="number" min="0.001" value={unexpectedQuantity} onChange={event => setUnexpectedQuantity(event.target.value)} placeholder="Quantity" className="rounded border p-2" /><input aria-label="Unexpected stock evidence" value={unexpectedEvidence} onChange={event => setUnexpectedEvidence(event.target.value)} placeholder="Supporting evidence" className="rounded border p-2" /><button disabled={addUnexpected.isPending || !unexpectedBatch || Number(unexpectedQuantity) <= 0 || unexpectedEvidence.trim().length < 3} onClick={() => addUnexpected.mutate()} className="rounded border border-amber-700 px-3 py-2 text-amber-800 disabled:opacity-50">Add unexpected stock</button></div>}
    {counter && <div className="flex flex-wrap gap-2 border-b p-4">{count.status === 'CREATED' && <button disabled={pending} onClick={() => transition({ count, action: 'start' })} className="flex items-center gap-2 rounded bg-emerald-700 px-4 py-2 text-white"><Play className="h-4 w-4" />Start counting</button>}{count.status === 'IN_PROGRESS' && <button disabled={pending || !allEntered} onClick={() => transition({ count, action: 'submit' })} className="flex items-center gap-2 rounded bg-emerald-700 px-4 py-2 text-white"><Check className="h-4 w-4" />Submit count</button>}{count.status === 'RECOUNT_REQUIRED' && latestRecount?.assigned_to === userId && <button disabled={pending} onClick={() => transition({ count, action: 'startRecount' })} className="flex items-center gap-2 rounded bg-amber-700 px-4 py-2 text-white"><RefreshCw className="h-4 w-4" />Start recount</button>}{assignedRecount && <button disabled={pending || !allRecounted} onClick={() => transition({ count, action: 'resubmit' })} className="rounded bg-amber-700 px-4 py-2 text-white">Resubmit recount</button>}</div>}
    {manager && ['SUBMITTED', 'RESUBMITTED', 'APPROVED'].includes(count.status) && <div className="space-y-3 border-b p-4"><h3 className="font-semibold">Manager review</h3><textarea aria-label="Decision reason" value={actionReason} onChange={event => setActionReason(event.target.value)} placeholder="Decision or adjustment reason" className="w-full rounded border p-2" />{['SUBMITTED', 'RESUBMITTED'].includes(count.status) && <div className="flex flex-wrap gap-2"><button disabled={pending || makerCheckerBlocked} onClick={approve} className="rounded bg-emerald-700 px-4 py-2 text-white disabled:opacity-50">Approve count</button><input aria-label="Recount assignee user ID" value={assignee} onChange={event => setAssignee(event.target.value)} placeholder="Recount assignee UUID" className="min-w-64 rounded border p-2" /><button disabled={pending || !assignee || actionReason.length < 3 || count.recount_count >= 2} onClick={recount} className="rounded border border-amber-700 px-4 py-2 text-amber-800 disabled:opacity-50">Request recount</button></div>}{count.status === 'APPROVED' && (!applyConfirm ? <button onClick={() => setApplyConfirm(true)} className="rounded bg-gray-900 px-4 py-2 text-white">Review adjustment application</button> : <div role="alert" className="flex flex-wrap items-center gap-3 border border-amber-300 bg-amber-50 p-3"><AlertTriangle className="h-5 w-5 text-amber-700" /><span className="flex-1">Apply every nonzero approved variance and release the inventory freeze?</span><button disabled={pending} onClick={apply} className="rounded bg-rose-700 px-4 py-2 text-white">Apply adjustments</button><button onClick={() => setApplyConfirm(false)} className="rounded border px-3 py-2">Back</button></div>)}</div>}
    {counter && canCancel && ['CREATED', 'IN_PROGRESS', 'SUBMITTED', 'RECOUNT_REQUIRED', 'RECOUNT_IN_PROGRESS', 'RESUBMITTED'].includes(count.status) && <div className="flex gap-2 border-b p-4"><input aria-label="Cancellation reason" value={actionReason} onChange={event => setActionReason(event.target.value)} placeholder="Cancellation reason" className="min-w-64 flex-1 rounded border p-2" /><button disabled={pending || actionReason.length < 3} onClick={cancel} className="rounded border border-rose-700 px-4 py-2 text-rose-800 disabled:opacity-50">Cancel count</button></div>}
    <div className="p-4"><h3 className="mb-3 flex items-center gap-2 font-semibold"><History className="h-4 w-4" />History</h3>{count.history?.length ? <ol className="space-y-2">{count.history.map((entry, index) => <li key={`${entry.timestamp}-${index}`} className="border-l-2 border-gray-300 pl-3 text-sm"><b>{entry.action}</b> <span className="text-gray-500">{new Date(entry.timestamp).toLocaleString()}</span>{entry.reason && <p>{entry.reason}</p>}</li>)}</ol> : <p className="text-sm text-gray-500">No history entries.</p>}</div>
  </div>
}