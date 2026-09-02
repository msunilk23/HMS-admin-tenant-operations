import { useDeferredValue, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, Minus, Pill, Plus, ReceiptText, Search, ShoppingBasket, ShieldCheck, Trash2 } from 'lucide-react'
import { pharmacyRetailService, type RetailClassification, type RetailMedicine, type RetailSaleInput } from '@/services/pharmacyRetailService'

type CartLine = { medicine: RetailMedicine; quantity: number; durationDays: number }

const money = (value: string | number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(Number(value))
const messageOf = (error: unknown) => typeof error === 'object' && error && 'response' in error
  ? String((error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Request failed')
  : error instanceof Error ? error.message : 'Request failed'

export default function RetailSalePage() {
  const idempotencyKey = useRef('')
  const [classification, setClassification] = useState<RetailClassification>('OTC')
  const [locationId, setLocationId] = useState('')
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [cart, setCart] = useState<CartLine[]>([])
  const [sale, setSale] = useState<Awaited<ReturnType<typeof pharmacyRetailService.create>> | null>(null)
  const [resumeSaleId, setResumeSaleId] = useState('')
  const [error, setError] = useState('')
  const [paymentMethod, setPaymentMethod] = useState<'CASH' | 'CARD' | 'UPI'>('CASH')
  const [paymentReference, setPaymentReference] = useState('')
  const [fields, setFields] = useState<Record<string, string>>({ prescription_date: new Date().toISOString().slice(0, 10) })

  const locations = useQuery({ queryKey: ['retail-locations'], queryFn: pharmacyRetailService.locations })
  const medicines = useQuery({
    queryKey: ['retail-medicines', locationId, deferredSearch],
    queryFn: () => pharmacyRetailService.search(locationId, deferredSearch.trim()),
    enabled: Boolean(locationId),
  })
  const resetRequest = () => { idempotencyKey.current = ''; setSale(null); setError('') }
  const setField = (name: string, value: string) => { resetRequest(); setFields(current => ({ ...current, [name]: value })) }
  const updateQuantity = (id: string, quantity: number) => {
    resetRequest()
    setCart(lines => lines.map(line => line.medicine.id === id ? { ...line, quantity: Math.max(1, Math.min(quantity, Number(line.medicine.available_quantity))) } : line))
  }
  const add = (medicine: RetailMedicine) => {
    resetRequest()
    setCart(lines => lines.some(line => line.medicine.id === medicine.id) ? lines : [...lines, { medicine, quantity: 1, durationDays: 1 }])
  }
  const changeMode = (value: RetailClassification) => { setClassification(value); setCart([]); resetRequest() }

  const create = useMutation({
    mutationFn: () => {
      if (!locationId || !cart.length) throw new Error('Select a location and add at least one medicine.')
      const external = classification === 'EXTERNAL_PRESCRIPTION'
      const required = external ? ['patient_name', 'patient_age', 'patient_gender', 'patient_mobile', 'patient_address', 'prescriber_name', 'prescriber_registration_number', 'prescription_date', 'issuing_facility', 'prescription_reference'] : []
      if (required.some(name => !fields[name]?.trim())) throw new Error('Complete every required patient and prescription field.')
      if (external && cart.some(line => line.medicine.is_controlled_drug) && (!fields.patient_id || !fields.government_id_type || fields.government_id_last_four?.length !== 4)) throw new Error('Controlled sales require a registered patient, ID type, and the last four characters.')
      idempotencyKey.current ||= crypto.randomUUID()
      const payload: RetailSaleInput = {
        classification, pharmacy_location_id: locationId, original_prescription_inspected: external,
        patient_id: fields.patient_id || undefined,
        patient_name: fields.patient_name || undefined, patient_age: fields.patient_age ? Number(fields.patient_age) : undefined,
        patient_gender: fields.patient_gender || undefined, patient_mobile: fields.patient_mobile || undefined,
        patient_address: fields.patient_address || undefined, government_id_type: fields.government_id_type || undefined,
        government_id_last_four: fields.government_id_last_four || undefined, prescriber_name: fields.prescriber_name || undefined,
        prescriber_registration_number: fields.prescriber_registration_number || undefined, prescription_date: fields.prescription_date || undefined,
        issuing_facility: fields.issuing_facility || undefined, prescription_reference: fields.prescription_reference || undefined,
        prescription_attachment_reference: fields.prescription_attachment_reference || undefined,
        items: cart.map(line => ({ medicine_product_id: line.medicine.id, quantity: line.quantity, prescribed_quantity: external ? line.quantity : undefined, duration_days: external ? line.durationDays : undefined })),
      }
      return pharmacyRetailService.create(payload, idempotencyKey.current)
    },
    onSuccess: result => { setSale(result); setError('') },
    onError: value => setError(messageOf(value)),
  })
  const verify = useMutation({ mutationFn: () => pharmacyRetailService.verify(sale?.id || ''), onSuccess: result => { setSale(result); setError('') }, onError: value => setError(messageOf(value)) })
  const resume = useMutation({
    mutationFn: () => pharmacyRetailService.get(resumeSaleId.trim()),
    onSuccess: result => { setSale(result); setClassification(result.classification); setLocationId(result.pharmacy_location_id); setCart([]); setError('') },
    onError: value => setError(messageOf(value)),
  })
  const dispense = useMutation({
    mutationFn: () => {
      if (paymentMethod !== 'CASH' && !paymentReference.trim()) throw new Error('Enter the card or UPI payment reference.')
      return pharmacyRetailService.dispense(sale?.id || '', paymentMethod, paymentReference.trim())
    },
    onSuccess: result => { setSale(result); setError('') }, onError: value => setError(messageOf(value)),
  })
  const subtotal = cart.reduce((total, line) => total + Number(line.medicine.unit_price) * line.quantity, 0)

  return <div className="min-h-full bg-[#f4f6f2] p-4 sm:p-6">
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-emerald-950/15 pb-5">
      <div><p className="text-xs font-semibold uppercase text-emerald-800">Pharmacy counter</p><h1 className="mt-1 flex items-center gap-2 text-2xl font-bold text-gray-950"><ShoppingBasket className="h-6 w-6 text-emerald-700" />Retail Dispensing</h1><p className="mt-1 text-sm text-gray-600">Walk-in OTC and verified external prescriptions.</p></div>
      <div className="flex flex-wrap items-end gap-3"><label className="text-sm font-medium text-gray-700">Resume sale<input aria-label="Retail sale ID" value={resumeSaleId} onChange={event => setResumeSaleId(event.target.value)} placeholder="Sale ID" className="mt-1 block w-72 rounded-md border border-gray-300 bg-white px-3 py-2" /></label><button type="button" onClick={() => resume.mutate()} disabled={!resumeSaleId.trim() || resume.isPending} className="rounded-md bg-gray-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{resume.isPending ? 'Loading...' : 'Resume'}</button><label className="text-sm font-medium text-gray-700">Pharmacy location<select aria-label="Retail pharmacy location" value={locationId} onChange={event => { setLocationId(event.target.value); setCart([]); resetRequest() }} className="mt-1 block min-w-64 rounded-md border border-gray-300 bg-white px-3 py-2"><option value="">Select authorized location</option>{locations.data?.map(location => <option key={location.id} value={location.id}>{location.location_name} ({location.location_code})</option>)}</select></label></div>
    </header>
    {error && <p role="alert" className="my-4 border-l-4 border-rose-600 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    <div className="my-5 grid grid-cols-2 border border-gray-300 bg-white p-1 sm:w-[430px]" role="group" aria-label="Retail sale classification">
      <button type="button" aria-pressed={classification === 'OTC'} onClick={() => changeMode('OTC')} className={`px-3 py-2 text-sm font-semibold ${classification === 'OTC' ? 'bg-emerald-800 text-white' : 'text-gray-600'}`}>OTC walk-in</button>
      <button type="button" aria-pressed={classification === 'EXTERNAL_PRESCRIPTION'} onClick={() => changeMode('EXTERNAL_PRESCRIPTION')} className={`px-3 py-2 text-sm font-semibold ${classification === 'EXTERNAL_PRESCRIPTION' ? 'bg-emerald-800 text-white' : 'text-gray-600'}`}>External prescription</button>
    </div>

    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(350px,.75fr)]">
      <main className="space-y-5">
        {classification === 'EXTERNAL_PRESCRIPTION' && <ExternalFields fields={fields} setField={setField} controlled={cart.some(line => line.medicine.is_controlled_drug)} />}
        <section className="border border-gray-200 bg-white">
          <div className="flex items-center gap-2 border-b border-gray-200 p-4"><Search className="h-4 w-4 text-gray-500" /><input aria-label="Search retail medicines" value={search} onChange={event => setSearch(event.target.value)} disabled={!locationId || Boolean(sale)} placeholder="Search medicine name or code" className="min-w-0 flex-1 border-0 text-sm outline-none" /></div>
          {!locationId ? <p className="p-8 text-center text-sm text-gray-500">Select an authorized pharmacy location.</p> : medicines.isLoading ? <p role="status" className="p-8 text-center text-sm text-gray-500">Loading eligible stock...</p> : medicines.isError ? <p role="alert" className="p-4 text-rose-700">{messageOf(medicines.error)}</p> : medicines.data?.length ? <div className="divide-y">{medicines.data.map(medicine => {
            const blocked = classification === 'OTC' && (medicine.requires_prescription || medicine.is_controlled_drug)
            return <article key={medicine.id} className="grid gap-3 p-4 sm:grid-cols-[1fr_auto_auto] sm:items-center"><div><div className="flex flex-wrap items-center gap-2"><b>{medicine.name}</b>{medicine.strength && <span className="text-sm text-gray-500">{medicine.strength}</span>}{medicine.is_controlled_drug && <span className="bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-800">Controlled</span>}{medicine.requires_prescription && !medicine.is_controlled_drug && <span className="bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">Prescription</span>}</div><p className="text-xs text-gray-500">{medicine.code} | available {medicine.available_quantity} | GST {medicine.gst_rate}%</p>{blocked && <p className="mt-1 text-xs text-rose-700">Use External prescription mode.</p>}</div><b>{money(medicine.unit_price)}</b><button type="button" onClick={() => add(medicine)} disabled={blocked || Boolean(sale) || cart.some(line => line.medicine.id === medicine.id)} aria-label={`Add ${medicine.name}`} className="flex items-center justify-center gap-1 bg-emerald-800 px-3 py-2 text-sm font-semibold text-white disabled:bg-gray-300"><Plus className="h-4 w-4" />Add</button></article>
          })}</div> : <p className="p-8 text-center text-sm text-gray-500">No saleable stock matches this search.</p>}
        </section>
      </main>

      <aside className="h-fit border border-gray-200 bg-white xl:sticky xl:top-5">
        <div className="flex items-center gap-2 border-b bg-gray-50 p-4"><ReceiptText className="h-5 w-5 text-emerald-700" /><h2 className="font-semibold">Sale summary</h2></div>
        {!cart.length ? <div className="p-8 text-center text-sm text-gray-500"><Pill className="mx-auto mb-2 h-7 w-7" />No medicines added.</div> : <div className="divide-y">{cart.map(line => <div key={line.medicine.id} className="space-y-3 p-4"><div className="flex justify-between gap-3"><div><b className="text-sm">{line.medicine.name}</b><p className="text-xs text-gray-500">{money(line.medicine.unit_price)} each</p></div><button type="button" title="Remove medicine" aria-label={`Remove ${line.medicine.name}`} disabled={Boolean(sale)} onClick={() => { setCart(lines => lines.filter(item => item.medicine.id !== line.medicine.id)); resetRequest() }}><Trash2 className="h-4 w-4 text-rose-700" /></button></div><div className="flex items-center justify-between"><div className="flex items-center border"><button type="button" title="Decrease quantity" aria-label={`Decrease ${line.medicine.name} quantity`} disabled={Boolean(sale) || line.quantity <= 1} onClick={() => updateQuantity(line.medicine.id, line.quantity - 1)} className="p-2"><Minus className="h-3 w-3" /></button><input aria-label={`${line.medicine.name} quantity`} type="number" min="1" max={line.medicine.available_quantity} value={line.quantity} disabled={Boolean(sale)} onChange={event => updateQuantity(line.medicine.id, Number(event.target.value))} className="w-14 border-x px-2 py-1 text-center" /><button type="button" title="Increase quantity" aria-label={`Increase ${line.medicine.name} quantity`} disabled={Boolean(sale) || line.quantity >= Number(line.medicine.available_quantity)} onClick={() => updateQuantity(line.medicine.id, line.quantity + 1)} className="p-2"><Plus className="h-3 w-3" /></button></div><b>{money(Number(line.medicine.unit_price) * line.quantity)}</b></div>{classification === 'EXTERNAL_PRESCRIPTION' && <label className="block text-xs">Prescribed duration (days)<input aria-label={`${line.medicine.name} duration days`} type="number" min="1" max="30" value={line.durationDays} disabled={Boolean(sale)} onChange={event => { resetRequest(); setCart(lines => lines.map(item => item.medicine.id === line.medicine.id ? { ...item, durationDays: Number(event.target.value) } : item)) }} className="mt-1 w-full border px-2 py-1" /></label>}</div>)}</div>}
        <div className="space-y-3 border-t p-4"><div className="flex justify-between text-sm"><span>Estimated subtotal</span><b>{money(subtotal)}</b></div>{!sale && <button type="button" onClick={() => create.mutate()} disabled={create.isPending || !cart.length || !locationId} className="w-full bg-gray-950 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">{create.isPending ? 'Creating sale...' : classification === 'OTC' ? 'Review payment' : 'Submit for verification'}</button>}{sale && <SaleActions sale={sale} paymentMethod={paymentMethod} setPaymentMethod={setPaymentMethod} paymentReference={paymentReference} setPaymentReference={setPaymentReference} verify={() => verify.mutate()} dispense={() => dispense.mutate()} pending={verify.isPending || dispense.isPending} />}</div>
      </aside>
    </div>
  </div>
}

function ExternalFields({ fields, setField, controlled }: { fields: Record<string, string>; setField: (name: string, value: string) => void; controlled: boolean }) {
  const inputs = [['patient_name', 'Patient name'], ['patient_age', 'Patient age'], ['patient_gender', 'Patient gender'], ['patient_mobile', 'Patient mobile'], ['patient_address', 'Patient address'], ['prescriber_name', 'Prescriber name'], ['prescriber_registration_number', 'Registration number'], ['prescription_date', 'Prescription date'], ['issuing_facility', 'Issuing facility / clinic'], ['prescription_reference', 'Prescription reference']] as const
  return <section className="border border-gray-200 bg-white p-5"><div className="mb-4 flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-emerald-700" /><div><h2 className="font-semibold">External prescription record</h2><p className="text-xs text-gray-500">Patient identity and original prescription inspection are mandatory.</p></div></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{inputs.map(([name, label]) => <label key={name} className="text-sm">{label}<input aria-label={label} type={name === 'patient_age' ? 'number' : name === 'prescription_date' ? 'date' : 'text'} value={fields[name] || ''} onChange={event => setField(name, event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2" /></label>)}<label className="text-sm">Prescription document reference<input aria-label="Prescription document reference" value={fields.prescription_attachment_reference || ''} onChange={event => setField('prescription_attachment_reference', event.target.value)} placeholder="Optional upload/document reference" className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2" /></label>{controlled && <><label className="text-sm">Registered patient ID<input aria-label="Registered patient ID" value={fields.patient_id || ''} onChange={event => setField('patient_id', event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2" /></label><label className="text-sm">Government ID type<input aria-label="Government ID type" value={fields.government_id_type || ''} onChange={event => setField('government_id_type', event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2" /></label><label className="text-sm">Government ID last four<input aria-label="Government ID last four" maxLength={4} value={fields.government_id_last_four || ''} onChange={event => setField('government_id_last_four', event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2" /></label></>}</div></section>
}

function SaleActions({ sale, paymentMethod, setPaymentMethod, paymentReference, setPaymentReference, verify, dispense, pending }: { sale: Awaited<ReturnType<typeof pharmacyRetailService.create>>; paymentMethod: 'CASH' | 'CARD' | 'UPI'; setPaymentMethod: (value: 'CASH' | 'CARD' | 'UPI') => void; paymentReference: string; setPaymentReference: (value: string) => void; verify: () => void; dispense: () => void; pending: boolean }) {
  if (sale.status === 'FULLY_DISPENSED') return <div role="status" className="space-y-2 border-l-4 border-emerald-600 bg-emerald-50 p-3 text-sm text-emerald-900"><p className="flex items-center gap-2 font-semibold"><CheckCircle2 className="h-4 w-4" />Payment captured and stock dispensed</p><p>Receipt {sale.receipt_number}</p><p>{sale.classification.replace('_', ' ')} | {sale.customer_reference}</p><p className="text-lg font-bold">{money(sale.total)}</p></div>
  if (sale.status === 'PENDING_VERIFICATION') return <button type="button" onClick={verify} disabled={pending} className="w-full bg-amber-700 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">{pending ? 'Verifying...' : 'Verify original prescription'}</button>
  return <div className="space-y-3"><div className="grid grid-cols-3 border" role="group" aria-label="Payment method">{(['CASH', 'CARD', 'UPI'] as const).map(value => <button type="button" key={value} aria-pressed={paymentMethod === value} onClick={() => setPaymentMethod(value)} className={`p-2 text-xs font-semibold ${paymentMethod === value ? 'bg-emerald-800 text-white' : ''}`}>{value}</button>)}</div>{paymentMethod !== 'CASH' && <input aria-label="Payment reference" value={paymentReference} onChange={event => setPaymentReference(event.target.value)} placeholder="Payment reference" className="w-full rounded-md border px-3 py-2 text-sm" />}{sale.controlled_sale && sale.status === 'VERIFIED' && <p className="bg-amber-50 p-2 text-xs text-amber-900">A different authorized Pharmacist must dispense this controlled sale.</p>}<div className="flex justify-between border-t pt-3"><span className="text-sm">Amount due</span><b>{money(sale.total)}</b></div><button type="button" onClick={dispense} disabled={pending} className="w-full bg-emerald-800 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">{pending ? 'Capturing...' : 'Capture payment and dispense'}</button></div>
}