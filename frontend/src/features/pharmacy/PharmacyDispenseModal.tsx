import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, ClipboardList, CreditCard, X } from 'lucide-react'
import { pharmacyService, type PharmacyDispense } from '@/services/pharmacyService'
import type { PharmacyQueueItem } from '@/types/common'

interface Props {
  item: PharmacyQueueItem
  onClose: () => void
  onDone: () => void
}

export default function PharmacyDispenseModal({ item, onClose, onDone }: Props) {
  const qc = useQueryClient()
  const [facilityId, setFacilityId] = useState('')
  const [locationId, setLocationId] = useState('')
  const [dispense, setDispense] = useState<PharmacyDispense | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [paymentMethod, setPaymentMethod] = useState<'cash' | 'online'>('cash')
  const [invoice, setInvoice] = useState<{ id: string; status: string; total: number; razorpay_order_id?: string } | null>(null)
  const itemsQuery = useQuery({
    queryKey: ['pharmacy-dispense-items', dispense?.id, facilityId],
    queryFn: () => pharmacyService.listDispenseItems(dispense?.id ?? '', facilityId),
    enabled: Boolean(dispense?.id && facilityId),
  })

  const startMutation = useMutation({
    mutationFn: () => pharmacyService.startDispense(item.id, { facility_id: facilityId, pharmacy_location_id: locationId }),
    onSuccess: result => {
      setError(null)
      setDispense({
        id: result.dispense_id ?? '',
        prescription_id: result.prescription_id,
        facility_id: facilityId,
        pharmacy_location_id: locationId,
        prescription_version: 0,
        visit_id: result.visit_id ?? '',
        patient_id: result.patient_id ?? '',
        status: 'DRAFT',
        billing_status: 'NOT_REQUIRED',
      })
      qc.invalidateQueries({ queryKey: ['pharmacy'] })
    },
    onError: value => setError(value instanceof Error ? value.message : 'Unable to start dispensing'),
  })

  const validateMutation = useMutation({
    mutationFn: () => pharmacyService.validateDispense(dispense?.id ?? '', facilityId),
    onSuccess: result => {
      setDispense(result)
      setError(null)
    },
    onError: value => setError(value instanceof Error ? value.message : 'Prescription validation failed'),
  })

  const prepareMutation = useMutation({
    mutationFn: async () => {
      if (!dispense?.id) throw new Error('Start the dispense first')
      const validated = dispense.status === 'DRAFT' ? await pharmacyService.validateDispense(dispense.id, facilityId) : dispense
      await pharmacyService.proposeAllocation(validated.id, facilityId)
      await pharmacyService.reserve(validated.id, facilityId)
      return pharmacyService.fulfillInternally(validated.id, facilityId, false)
    },
    onSuccess: result => {
      setDispense(result)
      setError(null)
      void itemsQuery.refetch()
    },
    onError: value => setError(value instanceof Error ? value.message : 'Unable to prepare fulfillment'),
  })

  const billMutation = useMutation({
    mutationFn: () => {
      if (!dispense?.id) throw new Error('Start the dispense first')
      const lineItems = (itemsQuery.data ?? []).map(item => ({
        dispense_item_id: item.id,
        name: item.prescribed_name_snapshot,
        mfr: '',
        batch: '',
        expiry: '',
        qty: Number(item.internal_confirmed_quantity),
        mrp: 0,
        gst_pct: 0,
        dis_pct: 0,
        total: 0,
      }))
      return pharmacyService.bill(item.id, { line_items: lineItems, discount: 0, payment_method: paymentMethod })
    },
    onSuccess: result => {
      setInvoice(result)
      setError(null)
      if (result.status === 'paid') {
        setDispense(current => current ? { ...current, status: 'CONFIRMED', billing_status: 'AUTHORIZED' } : current)
      }
      qc.invalidateQueries({ queryKey: ['pharmacy'] })
    },
    onError: value => setError(value instanceof Error ? value.message : 'Unable to create pharmacy invoice'),
  })

  const verifyMutation = useMutation({
    mutationFn: () => pharmacyService.verifyPayment(item.id),
    onSuccess: result => {
      if (result.success) {
        setInvoice(current => current ? { ...current, status: 'paid' } : current)
        setDispense(current => current ? { ...current, status: 'CONFIRMED', billing_status: 'AUTHORIZED' } : current)
        qc.invalidateQueries({ queryKey: ['pharmacy'] })
      } else {
        setError(result.reason ?? 'Payment is not captured yet')
      }
    },
    onError: value => setError(value instanceof Error ? value.message : 'Unable to verify payment'),
  })

  const cancelMutation = useMutation({
    mutationFn: () => pharmacyService.cancelDispense(dispense?.id ?? '', facilityId, 'Billing cancelled by pharmacy'),
    onSuccess: result => { setDispense(result); setError(null); qc.invalidateQueries({ queryKey: ['pharmacy'] }) },
    onError: value => setError(value instanceof Error ? value.message : 'Unable to cancel billing'),
  })

  const close = () => {
    if (!startMutation.isPending && !validateMutation.isPending) onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" role="dialog" aria-modal="true" aria-labelledby="dispense-title">
      <section className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">
              <ClipboardList className="h-4 w-4" aria-hidden="true" /> Prescription fulfillment
            </div>
            <h2 id="dispense-title" className="mt-1 text-xl font-semibold text-slate-950">{item.patient_name ?? 'Patient'}</h2>
            <p className="mt-1 text-sm text-slate-500">Review the doctor-prescribed items before pharmacy fulfillment.</p>
          </div>

          {dispense && <div className="overflow-hidden rounded-lg border border-slate-200">
            <div className="grid grid-cols-[1fr_auto_auto] gap-4 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500"><span>Medicine</span><span>Hospital</span><span>Outside</span></div>
            {(itemsQuery.data ?? []).map(item => <div key={item.id} className="grid grid-cols-[1fr_auto_auto] gap-4 border-b border-slate-100 px-4 py-3 text-sm last:border-0"><span className="font-medium text-slate-800">{item.prescribed_name_snapshot}</span><span className="font-mono text-teal-700">{item.internal_confirmed_quantity}</span><span className="font-mono text-amber-700">{item.outside_purchase_quantity}</span></div>)}
          </div>}
          <button onClick={close} className="rounded-md p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close dispensing workspace" title="Close">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 space-y-6 overflow-auto px-6 py-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-sm font-medium text-slate-700">Facility ID
              <input value={facilityId} onChange={event => setFacilityId(event.target.value)} placeholder="Facility UUID" className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100" />
            </label>
            <label className="text-sm font-medium text-slate-700">Pharmacy location ID
              <input value={locationId} onChange={event => setLocationId(event.target.value)} placeholder="Location UUID" className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100" />
            </label>
          </div>

          <div className="overflow-hidden rounded-lg border border-slate-200">
            <div className="grid grid-cols-[1fr_auto] gap-4 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <span>Prescribed medicine</span><span>Clinical quantity</span>
            </div>
            {(item.medicines ?? []).length > 0 ? item.medicines?.map((medicine, index) => (
              <div key={`${medicine.name}-${index}`} className="grid grid-cols-[1fr_auto] gap-4 border-b border-slate-100 px-4 py-4 last:border-0">
                <div><p className="font-medium text-slate-900">{medicine.name}</p><p className="mt-1 text-xs text-slate-500">{medicine.dose} · {medicine.route} · {medicine.frequency} · {medicine.duration}</p></div>
                <span className="self-center font-mono text-sm text-slate-700">From prescription</span>
              </div>
            )) : <p className="px-4 py-8 text-center text-sm text-slate-500">Prescription items will appear after intake validation.</p>}
          </div>

          {dispense && <div className="flex items-center gap-3 rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900"><CheckCircle2 className="h-5 w-5 shrink-0" aria-hidden="true" /> Dispense {dispense.status.toLowerCase().replaceAll('_', ' ')}. {dispense.status === 'CONFIRMED' ? 'Stock and ledger updated.' : 'Stock is unchanged until confirmed payment.'}</div>}
          {dispense && (dispense.status === 'READY_FOR_BILLING' || dispense.status === 'PARTIALLY_FULFILLED') && !invoice && <div className="flex items-center justify-between gap-4 rounded-lg border border-slate-200 bg-white px-4 py-3"><div><p className="text-sm font-semibold text-slate-900">Pharmacy payment</p><p className="text-xs text-slate-500">Only hospital-supplied quantities will be invoiced.</p></div><label className="flex items-center gap-2 text-sm text-slate-700"><CreditCard className="h-4 w-4" aria-hidden="true" /><select value={paymentMethod} onChange={event => setPaymentMethod(event.target.value as 'cash' | 'online')} className="rounded-md border border-slate-300 px-2 py-1.5"><option value="cash">Cash</option><option value="online">Online</option></select></label></div>}
          {invoice && <div className="flex items-center justify-between gap-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"><span>Invoice {invoice.status === 'paid' ? 'paid' : 'awaiting payment'}: ₹{Number(invoice.total).toFixed(2)}</span>{invoice.status !== 'paid' && <button onClick={() => verifyMutation.mutate()} disabled={verifyMutation.isPending} className="rounded-md border border-amber-400 px-3 py-1.5 font-semibold hover:bg-amber-100 disabled:opacity-50">{verifyMutation.isPending ? 'Checking…' : 'Verify payment'}</button>}</div>}
          {error && <div className="flex items-center gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"><AlertCircle className="h-5 w-5 shrink-0" aria-hidden="true" /> {error}</div>}
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
          <button onClick={close} className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          {!dispense ? <button onClick={() => startMutation.mutate()} disabled={!facilityId || !locationId || startMutation.isPending} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50">{startMutation.isPending ? 'Starting…' : 'Start review'}</button> : dispense.status === 'DRAFT' || dispense.status === 'VALIDATED' ? <button onClick={() => prepareMutation.mutate()} disabled={prepareMutation.isPending || validateMutation.isPending} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50">{prepareMutation.isPending ? 'Preparing stock…' : 'Validate and reserve FEFO stock'}</button> : dispense.status === 'READY_FOR_BILLING' || dispense.status === 'PARTIALLY_FULFILLED' ? <><button onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending || billMutation.isPending} className="rounded-md border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50">Cancel billing</button>{!invoice ? <button onClick={() => billMutation.mutate()} disabled={billMutation.isPending || itemsQuery.isLoading} className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50">{billMutation.isPending ? 'Creating invoice…' : 'Create invoice'}</button> : invoice.status === 'paid' ? <button onClick={onDone} className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800">Close workspace</button> : <button onClick={() => verifyMutation.mutate()} disabled={verifyMutation.isPending} className="rounded-md bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700 disabled:opacity-50">{verifyMutation.isPending ? 'Checking…' : 'Check payment'}</button>}</> : <button onClick={onDone} className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800">Close workspace</button>}
        </footer>
      </section>
    </div>
  )
}
