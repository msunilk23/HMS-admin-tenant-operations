import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { masterDataService } from '@/services/masterDataService'
import { goodsReceiptService } from '@/services/goodsReceiptService'
import { supplierReturnService, type SupplierReturnCreateInput } from '@/services/returnsService'

const errorMessage = (error: unknown) => {
  const detail = typeof error === 'object' && error !== null && 'response' in error
    ? (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail : undefined
  if (typeof detail === 'string') return detail
  return error instanceof Error ? error.message : 'Unable to complete the request.'
}

export default function SupplierReturnsPage() {
  const queryClient = useQueryClient()
  const idempotencyKey = useRef<string | null>(null)
  const [pharmacyLocationId, setPharmacyLocationId] = useState('')
  const [supplierId, setSupplierId] = useState('')
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const locations = useQuery({ queryKey: ['return-locations'], queryFn: goodsReceiptService.locations })
  const suppliers = useQuery({ queryKey: ['return-suppliers'], queryFn: () => masterDataService.listSuppliers() })
  const eligibility = useQuery({
    queryKey: ['supplier-return-eligibility', supplierId, pharmacyLocationId],
    queryFn: () => supplierReturnService.eligibility({ supplier_id: supplierId, pharmacy_location_id: pharmacyLocationId }),
    enabled: Boolean(supplierId && pharmacyLocationId),
  })
  const records = useQuery({
    queryKey: ['supplier-returns', page, status],
    queryFn: () => supplierReturnService.list({ page, page_size: 20, status: status || undefined }),
  })
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['supplier-returns'] })
    queryClient.invalidateQueries({ queryKey: ['supplier-return-eligibility'] })
  }
  const create = useMutation({
    mutationFn: (payload: SupplierReturnCreateInput) => supplierReturnService.create(payload),
    onSuccess: (result) => { setMessage(`Supplier return ${result.reference_key} created.`); setError(''); idempotencyKey.current = null; setReason(''); setNotes(''); setQuantities({}); refresh() },
    onError: (mutationError) => setError(errorMessage(mutationError)),
  })
  const approve = useMutation({ mutationFn: supplierReturnService.approve, onSuccess: (result) => { setMessage(`Supplier return ${result.reference_key} approved.`); refresh() }, onError: (mutationError) => setError(errorMessage(mutationError)) })
  const dispatch = useMutation({ mutationFn: supplierReturnService.dispatch, onSuccess: (result) => { setMessage(`Supplier return ${result.reference_key} dispatched.`); refresh() }, onError: (mutationError) => setError(errorMessage(mutationError)) })
  const submit = () => {
    if (!pharmacyLocationId || !supplierId || reason.trim().length < 10) { setError('Select a pharmacy location and supplier, then provide a return reason of at least 10 characters.'); return }
    const items = eligibility.data?.items.map((batch) => ({ inventory_batch_id: batch.inventory_batch_id, returned_quantity: Number(quantities[batch.inventory_batch_id] || 0), unit_cost: Number(batch.unit_cost) })).filter((item) => item.returned_quantity > 0) || []
    if (!items.length) { setError('Enter a positive quantity for at least one eligible batch.'); return }
    for (const item of items) {
      const batch = eligibility.data?.items.find((candidate) => candidate.inventory_batch_id === item.inventory_batch_id)
      if (!batch || item.returned_quantity > Number(batch.eligible_return_quantity)) { setError('A selected batch exceeds its eligible return quantity.'); return }
    }
    idempotencyKey.current ??= crypto.randomUUID()
    setError('')
    create.mutate({
      supplier_id: supplierId,
      pharmacy_location_id: pharmacyLocationId,
      goods_receipt_id: eligibility.data?.items.find((batch) => batch.goods_receipt_id)?.goods_receipt_id,
      return_reason: reason.trim(), notes: notes.trim() || undefined, idempotency_key: idempotencyKey.current,
      items,
    })
  }
  return <div className="p-6 space-y-6">
    <div><h1 className="text-2xl font-bold text-gray-900">Supplier Returns</h1><p className="mt-1 text-sm text-gray-500">Create and dispatch returns from eligible pharmacy inventory.</p></div>
    <div className="grid gap-6 xl:grid-cols-[minmax(420px,0.9fr)_minmax(0,1.1fr)]">
      <section className="space-y-4 rounded-xl border border-gray-200 bg-white p-5"><h2 className="font-semibold text-gray-900">Create return</h2>
        <label className="block text-sm text-gray-700">Pharmacy location<select aria-label="Pharmacy location" value={pharmacyLocationId} onChange={(event) => { idempotencyKey.current = null; setPharmacyLocationId(event.target.value); setQuantities({}); setError('') }} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2"><option value="">Select pharmacy location</option>{locations.data?.filter((location) => location.active).map((location) => <option key={location.id} value={location.id}>{location.location_code} · {location.location_name}</option>)}</select></label>
        {locations.isError && <p role="alert" className="text-sm text-rose-700">{errorMessage(locations.error)}</p>}
        <label className="block text-sm text-gray-700">Active supplier<select aria-label="Active supplier" value={supplierId} onChange={(event) => { idempotencyKey.current = null; setSupplierId(event.target.value); setQuantities({}); setError('') }} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2"><option value="">Select supplier</option>{suppliers.data?.filter((supplier) => supplier.is_active).map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.supplier_name}</option>)}</select></label>
        {suppliers.isError && <p role="alert" className="text-sm text-rose-700">{errorMessage(suppliers.error)}</p>}
        {eligibility.isLoading && <p className="text-sm text-gray-500">Loading eligible inventory batches...</p>}
        {eligibility.data?.items.map((batch) => <label key={batch.inventory_batch_id} className="grid grid-cols-[1fr_110px] gap-3 rounded-lg border border-gray-200 p-3 text-sm"><span><b>{batch.medicine_name || 'Medicine'} - {batch.batch_number}</b><span className="block text-xs text-gray-500">Available {batch.available_quantity}; eligible {batch.eligible_return_quantity}; GRN {batch.goods_receipt_id || 'Not recorded'}</span></span><input aria-label={`Return quantity for ${batch.batch_number}`} type="number" min="0" max={batch.eligible_return_quantity} step="0.001" value={quantities[batch.inventory_batch_id] ?? ''} onChange={(event) => { idempotencyKey.current = null; setQuantities((current) => ({ ...current, [batch.inventory_batch_id]: event.target.value })) }} className="rounded-lg border border-gray-300 px-2 py-1" /></label>)}
        {eligibility.data?.items.length === 0 && <p className="text-sm text-gray-500">No eligible inventory batches for this supplier.</p>}
        <label className="block text-sm text-gray-700">Return reason<input value={reason} onChange={(event) => { idempotencyKey.current = null; setReason(event.target.value) }} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2" /></label><label className="block text-sm text-gray-700">Notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2" /></label>
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}{message && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{message}</p>}
        <button type="button" onClick={submit} disabled={create.isPending || !eligibility.data} className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60">{create.isPending ? 'Submitting...' : 'Submit return'}</button>
      </section>
      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white"><div className="flex justify-between gap-3 border-b border-gray-200 p-4"><h2 className="font-semibold text-gray-900">Return log</h2><select aria-label="Supplier return status filter" value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} className="rounded border px-2 py-1 text-sm"><option value="">All statuses</option><option value="REQUESTED">Requested</option><option value="APPROVED">Approved</option><option value="DISPATCHED">Dispatched</option></select></div>
        {records.isLoading ? <p className="p-5 text-sm text-gray-500">Loading supplier returns...</p> : records.isError ? <p role="alert" className="p-5 text-sm text-rose-700">{errorMessage(records.error)}</p> : records.data?.items.length === 0 ? <p className="p-5 text-sm text-gray-500">No supplier returns match these filters.</p> : <div className="divide-y divide-gray-100">{records.data?.items.map((record) => <article key={record.id} className="space-y-2 p-4"><div className="flex justify-between gap-3"><div><p className="font-semibold text-gray-900">{record.reference_key}</p><p className="text-xs text-gray-500">Supplier {record.supplier_id} | GRN {record.goods_receipt_id || 'Not recorded'}</p></div><span className="rounded-full bg-slate-100 px-2 py-1 text-xs">{record.status}</span></div><p className="text-sm text-gray-600">{record.return_reason}</p><p className="text-xs text-gray-500">{record.items.map((item) => `${item.returned_quantity} from ${item.inventory_batch_id}`).join(', ')}</p>{record.status === 'REQUESTED' && <button type="button" onClick={() => approve.mutate(record.id)} disabled={approve.isPending} className="rounded border px-3 py-1 text-xs">Approve</button>}{record.status === 'APPROVED' && <button type="button" onClick={() => dispatch.mutate(record.id)} disabled={dispatch.isPending} className="rounded border px-3 py-1 text-xs">Dispatch</button>}</article>)}</div>}
        {(records.data?.total_pages ?? 0) > 1 && <div className="flex justify-between border-t border-gray-200 p-3"><button type="button" disabled={page === 1} onClick={() => setPage((current) => current - 1)}>Previous</button><span>Page {page} of {records.data?.total_pages}</span><button type="button" disabled={page >= (records.data?.total_pages ?? 0)} onClick={() => setPage((current) => current + 1)}>Next</button></div>}</section>
    </div>
  </div>
}
