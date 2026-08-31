import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { masterDataService } from '@/services/masterDataService'

type Tab = 'generic-medicines' | 'dosage-forms' | 'routes' | 'manufacturers' | 'medicine-products' | 'formulary'
type FormValue = string | boolean

const TABS: { id: Tab; label: string }[] = [
  { id: 'generic-medicines', label: 'Generic Medicines' },
  { id: 'dosage-forms', label: 'Dosage Forms' },
  { id: 'routes', label: 'Routes' },
  { id: 'manufacturers', label: 'Manufacturers' },
  { id: 'medicine-products', label: 'Products' },
  { id: 'formulary', label: 'Formulary' },
]

const fields: Record<Tab, { key: string; label: string; type?: 'boolean' | 'date' }[]> = {
  'generic-medicines': [
    { key: 'code', label: 'Code' }, { key: 'name', label: 'Name' }, { key: 'therapeutic_class', label: 'Therapeutic class' }, { key: 'description', label: 'Description' },
  ],
  'dosage-forms': [
    { key: 'code', label: 'Code' }, { key: 'name', label: 'Name' }, { key: 'calculation_type', label: 'Calculation type' }, { key: 'description', label: 'Description' },
  ],
  routes: [{ key: 'code', label: 'Code' }, { key: 'name', label: 'Name' }, { key: 'description', label: 'Description' }],
  manufacturers: [{ key: 'code', label: 'Code' }, { key: 'name', label: 'Name' }, { key: 'gstin', label: 'GSTIN' }, { key: 'country', label: 'Country' }],
  'medicine-products': [
    { key: 'code', label: 'Product code' }, { key: 'generic_medicine_id', label: 'Generic medicine ID' }, { key: 'brand_name', label: 'Brand name' }, { key: 'strength', label: 'Strength' }, { key: 'unit', label: 'Unit' }, { key: 'dosage_form_id', label: 'Dosage form ID' }, { key: 'default_route_id', label: 'Default route ID' }, { key: 'manufacturer_id', label: 'Manufacturer ID' }, { key: 'composition', label: 'Composition' }, { key: 'hsn_code', label: 'HSN code' }, { key: 'gst_rate', label: 'GST rate' }, { key: 'schedule_category', label: 'Schedule category' }, { key: 'is_controlled_drug', label: 'Controlled drug', type: 'boolean' }, { key: 'requires_prescription', label: 'Prescription required', type: 'boolean' },
  ],
  formulary: [
    { key: 'medicine_product_id', label: 'Medicine product ID' }, { key: 'department_id', label: 'Department ID' }, { key: 'is_approved', label: 'Approved', type: 'boolean' }, { key: 'is_preferred', label: 'Preferred', type: 'boolean' }, { key: 'is_prescribable', label: 'Prescribable', type: 'boolean' }, { key: 'effective_date', label: 'Effective date', type: 'date' }, { key: 'expiry_date', label: 'Expiry date', type: 'date' },
  ],
}

const api = {
  list: (tab: Tab, q: string) => {
    if (tab === 'generic-medicines') return masterDataService.listGenericMedicines(q)
    if (tab === 'dosage-forms') return masterDataService.listDosageForms(q)
    if (tab === 'routes') return masterDataService.listRoutes(q)
    if (tab === 'manufacturers') return masterDataService.listManufacturers(q)
    if (tab === 'medicine-products') return masterDataService.listMedicineProducts(q)
    return masterDataService.listFormulary(q)
  },
  create: (tab: Tab, data: Record<string, FormValue>) => {
    if (tab === 'generic-medicines') return masterDataService.createGenericMedicine(data)
    if (tab === 'dosage-forms') return masterDataService.createDosageForm(data)
    if (tab === 'routes') return masterDataService.createRoute(data)
    if (tab === 'manufacturers') return masterDataService.createManufacturer(data)
    if (tab === 'medicine-products') return masterDataService.createMedicineProduct(data)
    return masterDataService.createFormulary(data)
  },
  update: (tab: Tab, id: string, data: Record<string, FormValue>) => {
    if (tab === 'generic-medicines') return masterDataService.updateGenericMedicine(id, data)
    if (tab === 'dosage-forms') return masterDataService.updateDosageForm(id, data)
    if (tab === 'routes') return masterDataService.updateRoute(id, data)
    if (tab === 'manufacturers') return masterDataService.updateManufacturer(id, data)
    if (tab === 'medicine-products') return masterDataService.updateMedicineProduct(id, data)
    return masterDataService.updateFormulary(id, data)
  },
  deactivate: (tab: Tab, id: string) => {
    if (tab === 'generic-medicines') return masterDataService.deactivateGenericMedicine(id)
    if (tab === 'dosage-forms') return masterDataService.deactivateDosageForm(id)
    if (tab === 'routes') return masterDataService.deactivateRoute(id)
    if (tab === 'manufacturers') return masterDataService.deactivateManufacturer(id)
    if (tab === 'medicine-products') return masterDataService.deactivateMedicineProduct(id)
    return masterDataService.deactivateFormulary(id)
  },
}

function displayValue(value: unknown) {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return value == null || value === '' ? '—' : String(value)
}

export default function PharmacyAdminPage() {
  const [tab, setTab] = useState<Tab>('generic-medicines')
  const [query, setQuery] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, FormValue>>({})
  const qc = useQueryClient()
  const { data = [], isLoading, isError } = useQuery<Record<string, unknown>[]>({ queryKey: ['pharmacy-admin', tab, query], queryFn: async () => api.list(tab, query) as unknown as Record<string, unknown>[] })
  const mutation = useMutation({
    mutationFn: async (): Promise<unknown> => editingId ? api.update(tab, editingId, form) : api.create(tab, form),
    onSuccess: () => { setForm({}); setEditingId(null); qc.invalidateQueries({ queryKey: ['pharmacy-admin', tab] }) },
  })
  const deactivateMutation = useMutation({ mutationFn: async (id: string): Promise<unknown> => api.deactivate(tab, id), onSuccess: () => qc.invalidateQueries({ queryKey: ['pharmacy-admin', tab] }) })
  const config = fields[tab]

  const beginEdit = (item: Record<string, unknown>) => {
    const values: Record<string, FormValue> = {}
    config.forEach(field => { if (field.key in item) values[field.key] = (item[field.key] ?? '') as FormValue })
    setEditingId(String(item.id))
    setForm(values)
  }

  return (
    <div className="p-6 space-y-5">
      <div>
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Pharmacy Master Data</h1>
            <p className="text-sm text-gray-500 mt-1">Manage controlled medicine, product, and formulary records.</p>
          </div>
          <a href="/admin/pharmacy/purchase-orders" className="px-3 py-2 rounded-lg border border-primary text-primary text-sm font-medium hover:bg-primary/5 whitespace-nowrap">
            Purchase Orders
          </a>
        </div>
      </div>
      <div className="flex gap-1 overflow-x-auto border-b border-gray-200">
        {TABS.map(item => <button key={item.id} type="button" onClick={() => { setTab(item.id); setQuery(''); setForm({}); setEditingId(null) }} className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 ${tab === item.id ? 'border-primary text-primary font-semibold' : 'border-transparent text-gray-500 hover:text-gray-800'}`}>{item.label}</button>)}
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-5 items-start">
        <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-gray-200 flex gap-3">
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search records" className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm" />
            <button type="button" onClick={() => { setForm({}); setEditingId(null) }} className="px-3 py-2 rounded-lg bg-primary text-white text-sm">New</button>
          </div>
          {isLoading && <p className="p-5 text-sm text-gray-500">Loading records…</p>}
          {isError && <p className="p-5 text-sm text-red-600">Could not load records.</p>}
          {!isLoading && !isError && <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-gray-50 text-left text-xs uppercase text-gray-500"><tr><th className="px-4 py-3">Record</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Actions</th></tr></thead><tbody className="divide-y divide-gray-100">{data.map(item => <tr key={String(item.id)}><td className="px-4 py-3"><div className="font-medium text-gray-900">{displayValue(item.name ?? item.brand_name ?? item.code ?? item.medicine_product_id)}</div><div className="text-xs text-gray-500">{displayValue(item.code ?? item.department_id)}</div></td><td className="px-4 py-3">{item.is_active === false ? <span className="text-gray-400">Inactive</span> : <span className="text-emerald-700">Active</span>}</td><td className="px-4 py-3 text-right space-x-2"><button type="button" onClick={() => beginEdit(item)} className="text-primary hover:underline">Edit</button>{item.is_active !== false && <button type="button" onClick={() => deactivateMutation.mutate(String(item.id))} className="text-red-600 hover:underline">Deactivate</button>}</td></tr>)}</tbody></table>{data.length === 0 && <p className="p-5 text-sm text-gray-500">No records found.</p>}</div>}
        </section>
        <section className="bg-white border border-gray-200 rounded-xl p-5">
          <h2 className="font-semibold text-gray-900">{editingId ? 'Edit record' : 'Add record'}</h2>
          <form onSubmit={event => { event.preventDefault(); mutation.mutate() }} className="mt-4 space-y-3">
            {config.map(field => <label key={field.key} className="block text-sm text-gray-700">{field.label}{field.type === 'boolean' ? <input type="checkbox" checked={Boolean(form[field.key])} onChange={event => setForm(prev => ({ ...prev, [field.key]: event.target.checked }))} className="ml-2 accent-primary" /> : <input type={field.type === 'date' ? 'date' : 'text'} value={String(form[field.key] ?? '')} onChange={event => setForm(prev => ({ ...prev, [field.key]: event.target.value }))} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" />}</label>)}
            {mutation.isError && <p className="text-sm text-red-600">Could not save this record. Check the values and permissions.</p>}
            <button type="submit" disabled={mutation.isPending} className="w-full rounded-lg bg-primary text-white py-2.5 text-sm font-medium disabled:opacity-50">{mutation.isPending ? 'Saving…' : editingId ? 'Save changes' : 'Create record'}</button>
          </form>
        </section>
      </div>
    </div>
  )
}
