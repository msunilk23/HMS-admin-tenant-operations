import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, ClipboardList, X } from 'lucide-react'
import apiClient from '@/services/apiClient'
import { useAuthStore } from '@/features/auth/authStore'
import { useWebSocket } from '@/hooks/useWebSocket'

// ── Types ──────────────────────────────────────────────────────────────────

interface Requisition {
  id: string
  seq: number
  indent_number: string
  requested_by_id: string
  requested_by_name: string
  from_location: string
  to_location: string
  request_date: string
  need_by_date: string
  items: string | null
  status: string
  amount: number | null
  created_at: string
}

interface CreatePayload {
  from_location: string
  to_location: string
  need_by_date: string
  items?: string
}

// ── Master department list ─────────────────────────────────────────────────

const HOSPITAL_DEPARTMENTS = [
  'Reception / Front Office',
  'OPD - General Medicine',
  'OPD - Paediatrics',
  'OPD - Gynaecology & Obstetrics',
  'OPD - Orthopaedics',
  'OPD - ENT',
  'OPD - Ophthalmology',
  'OPD - Dermatology',
  'OPD - Cardiology',
  'OPD - Neurology',
  'OPD - Psychiatry',
  'OPD - Oncology',
  'OPD - Urology',
  'OPD - Nephrology',
  'OPD - Endocrinology',
  'OPD - Pulmonology',
  'OPD - Gastroenterology',
  'OPD - Nurse Station',
  'Emergency / Casualty',
  'ICU / Critical Care',
  'Operation Theater (OT)',
  'Post-Operative Ward',
  'General Ward',
  'Private Ward',
  'Labour Room / Delivery Suite',
  'Neonatal ICU (NICU)',
  'Paediatric Ward',
  'Pharmacy',
  'Laboratory / Pathology',
  'Radiology / Imaging',
  'Physiotherapy & Rehabilitation',
  'Dietetics & Nutrition',
  'Blood Bank',
  'CSSD (Sterile Supply)',
  'Laundry',
  'Housekeeping',
  'Biomedical Engineering',
  'Medical Records',
  'Ambulance / Transport',
  'Administration',
  'Accounts & Billing',
  'HR / Staffing',
  'Security',
  'Canteen / Kitchen',
  'Mortuary',
]

// ── API helpers ────────────────────────────────────────────────────────────

const fetchRequisitions = (mine: boolean) =>
  apiClient.get<Requisition[]>('/indents', { params: mine ? { mine: true } : {} }).then(r => r.data)

const createRequisition = (payload: CreatePayload) =>
  apiClient.post<Requisition>('/indents', payload).then(r => r.data)

const updateStatus = (id: string, status: string) =>
  apiClient.patch<Requisition>(`/indents/${id}/status`, { status }).then(r => r.data)

const updateAmount = (id: string, amount: number | null) =>
  apiClient.patch<Requisition>(`/indents/${id}/amount`, { amount }).then(r => r.data)

const updateItems = (id: string, items: string) =>
  apiClient.patch<Requisition>(`/indents/${id}/items`, { items }).then(r => r.data)

// ── Parse item string to rows ──────────────────────────────────────────────

function parseItemRows(itemsStr: string | null): { item: string; qty: string }[] {
  if (!itemsStr?.trim()) return [{ item: '', qty: '' }]
  return itemsStr.split(',').map(s => {
    const match = s.trim().match(/^(.+)\s+x(\d+(?:\.\d+)?)$/i)
    if (match) return { item: match[1].trim(), qty: match[2] }
    return { item: s.trim(), qty: '' }
  })
}

function serializeItemRows(rows: { item: string; qty: string }[]): string {
  return rows
    .filter(r => r.item.trim())
    .map(r => r.qty.trim() ? `${r.item.trim()} x${r.qty.trim()}` : r.item.trim())
    .join(', ')
}

// ── Status badge ───────────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, string> = {
  pending:   'bg-yellow-100 text-yellow-700',
  approved:  'bg-blue-100 text-blue-700',
  rejected:  'bg-red-100 text-red-600',
  fulfilled: 'bg-green-100 text-green-700',
}

const STATUS_LABEL: Record<string, string> = {
  pending:   'Pending',
  approved:  'Approved',
  rejected:  'Rejected',
  fulfilled:  'Fulfilled',
}

const TO_LOCATIONS = ['Pharmacy', 'General Store']

// ── Add Indent Modal ──────────────────────────────────────────────────

function AddRequisitionModal({
  onClose,
  onSubmit,
  submitting,
}: {
  onClose: () => void
  onSubmit: (payload: CreatePayload) => void
  submitting: boolean
}) {
  const today = new Date().toISOString().split('T')[0]
  const [fromLocation, setFromLocation] = useState('')
  const [fromSearch, setFromSearch] = useState('')
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [toLocation, setToLocation] = useState(TO_LOCATIONS[0])

  const suggestions = fromSearch.trim().length >= 3
    ? HOSPITAL_DEPARTMENTS.filter(d => d.toLowerCase().includes(fromSearch.trim().toLowerCase()))
    : []
  const [needByDate, setNeedByDate] = useState('')
  const [itemRows, setItemRows] = useState([{ item: '', qty: '' }])

  const addRow = () => setItemRows(r => [...r, { item: '', qty: '' }])
  const updateRow = (i: number, field: 'item' | 'qty', value: string) =>
    setItemRows(r => r.map((row, idx) => idx === i ? { ...row, [field]: value } : row))
  const removeRow = (i: number) => setItemRows(r => r.filter((_, idx) => idx !== i))

  const handleSubmit = () => {
    if (!fromLocation || !needByDate) return
    const itemsStr = itemRows
      .filter(r => r.item.trim())
      .map(r => r.qty.trim() ? `${r.item.trim()} x${r.qty.trim()}` : r.item.trim())
      .join(', ')
    onSubmit({
      from_location: fromLocation,
      to_location: toLocation,
      need_by_date: needByDate,
      items: itemsStr,
    })
  }

  const isValid = !!fromLocation && !!needByDate && itemRows.some(r => r.item.trim())

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">New Indent</h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* From — searchable combobox */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">From</label>
            <div className="relative">
              <input
                type="text"
                value={fromSearch}
                onChange={e => {
                  setFromSearch(e.target.value)
                  setFromLocation('')
                  setShowSuggestions(true)
                }}
                onFocus={() => setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                placeholder={fromLocation || 'Search department…'}
                className={`w-full border rounded-lg px-3 py-2 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${fromLocation ? 'border-blue-400 bg-blue-50/40 text-blue-900' : 'border-gray-300'}`}
              />
              {fromLocation && (
                <button
                  type="button"
                  onClick={() => { setFromLocation(''); setFromSearch('') }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
              {showSuggestions && suggestions.length > 0 && (
                <ul className="absolute z-50 left-0 right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-52 overflow-y-auto text-sm">
                  {suggestions.map(d => (
                    <li
                      key={d}
                      onMouseDown={() => { setFromLocation(d); setFromSearch(d); setShowSuggestions(false) }}
                      className="px-3 py-2 cursor-pointer hover:bg-blue-50 text-gray-700"
                    >
                      {d}
                    </li>
                  ))}
                </ul>
              )}
              {showSuggestions && fromSearch.trim().length >= 3 && suggestions.length === 0 && (
                <div className="absolute z-50 left-0 right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-sm px-3 py-2 text-sm text-gray-400">
                  No match found
                </div>
              )}
            </div>
            {fromSearch.trim().length > 0 && fromSearch.trim().length < 3 && (
              <p className="text-xs text-gray-400 mt-1">Type {3 - fromSearch.trim().length} more character{3 - fromSearch.trim().length !== 1 ? 's' : ''} to search</p>
            )}
          </div>

          {/* To */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">To</label>
            <div className="flex gap-2">
              {TO_LOCATIONS.map(loc => (
                <button
                  key={loc}
                  onClick={() => setToLocation(loc)}
                  className={`flex-1 py-1.5 rounded-lg border text-sm font-medium transition-colors ${toLocation === loc ? 'bg-indigo-50 border-indigo-400 text-indigo-700' : 'border-gray-300 text-gray-500 hover:bg-gray-50'}`}
                >
                  {loc}
                </button>
              ))}
            </div>
          </div>

          {/* Request Date (read-only) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Request Date</label>
            <input
              type="date"
              value={today}
              readOnly
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50 text-gray-500 cursor-not-allowed"
            />
          </div>

          {/* Need By */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Need By <span className="text-red-500">*</span></label>
            <input
              type="date"
              value={needByDate}
              min={today}
              onChange={e => setNeedByDate(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Items */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-gray-700">Items <span className="text-red-500">*</span></label>
              <button
                type="button"
                onClick={addRow}
                className="flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Item
              </button>
            </div>
            <div className="space-y-2">
              <div className="grid grid-cols-[1fr_80px_32px] gap-2">
                <span className="text-xs text-gray-400 font-medium px-1">Item</span>
                <span className="text-xs text-gray-400 font-medium px-1">Quantity</span>
                <span />
              </div>
              {itemRows.map((row, i) => (
                <div key={i} className="grid grid-cols-[1fr_80px_32px] gap-2 items-center">
                  <input
                    type="text"
                    value={row.item}
                    onChange={e => updateRow(i, 'item', e.target.value)}
                    placeholder="e.g. Sanitizer"
                    className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <input
                    type="number"
                    min="1"
                    value={row.qty}
                    onChange={e => updateRow(i, 'qty', e.target.value)}
                    placeholder="Qty"
                    className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-center"
                  />
                  {itemRows.length > 1 ? (
                    <button
                      type="button"
                      onClick={() => removeRow(i)}
                      className="flex items-center justify-center w-7 h-7 rounded-lg text-gray-300 hover:text-red-400 hover:bg-red-50 transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  ) : <span />}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!isValid || submitting}
            className="px-5 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Submitting…' : 'Submit Indent'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Status Dropdown (admin only) ────────────────────────────────────────────

function StatusDropdown({ requisition, onUpdate }: { requisition: Requisition; onUpdate: (id: string, status: string) => void }) {
  const statuses = ['pending', 'approved', 'rejected', 'fulfilled']
  return (
    <div className="relative">
      <select
        value={requisition.status}
        onChange={e => onUpdate(requisition.id, e.target.value)}
        className={`appearance-none text-xs font-medium px-2.5 py-1 rounded-full border-0 cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500 ${STATUS_BADGE[requisition.status] ?? 'bg-gray-100 text-gray-600'}`}
      >
        {statuses.map(s => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
      </select>
    </div>
  )
}

// ── Indent Detail Modal (admin) ─────────────────────────────────────────────

function IndentDetailModal({
  indent,
  onClose,
  onStatusUpdate,
  onAmountUpdate,
  onItemsUpdate,
}: {
  indent: Requisition
  onClose: () => void
  onStatusUpdate: (id: string, status: string) => void
  onAmountUpdate: (id: string, amount: number | null) => void
  onItemsUpdate: (id: string, items: string) => void
}) {
  const statuses = ['pending', 'approved', 'rejected', 'fulfilled']
  const [amountInput, setAmountInput] = useState(
    indent.amount !== null ? String(indent.amount) : ''
  )
  const [amountSaved, setAmountSaved] = useState(false)
  const [itemRows, setItemRows] = useState(() => parseItemRows(indent.items))
  const [itemsSaved, setItemsSaved] = useState(false)

  const addItemRow = () => setItemRows(r => [...r, { item: '', qty: '' }])
  const updateItemRow = (i: number, field: 'item' | 'qty', value: string) =>
    setItemRows(r => r.map((row, idx) => idx === i ? { ...row, [field]: value } : row))
  const removeItemRow = (i: number) => setItemRows(r => r.filter((_, idx) => idx !== i))

  const handleAmountSave = () => {
    const parsed = amountInput.trim() === '' ? null : parseFloat(amountInput)
    if (amountInput.trim() !== '' && (isNaN(parsed!) || parsed! < 0)) return
    onAmountUpdate(indent.id, parsed)
    setAmountSaved(true)
    setTimeout(() => setAmountSaved(false), 2000)
  }

  const handleItemsSave = () => {
    const str = serializeItemRows(itemRows)
    onItemsUpdate(indent.id, str)
    setItemsSaved(true)
    setTimeout(() => setItemsSaved(false), 2000)
  }

  const field = (label: string, value: React.ReactNode) => (
    <div className="flex justify-between items-start py-2.5 border-b border-gray-50 last:border-0">
      <span className="text-xs font-medium text-gray-500 w-36 shrink-0">{label}</span>
      <span className="text-sm text-gray-800 text-right">{value}</span>
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
          <div>
            <h2 className="text-base font-semibold text-gray-900">{indent.indent_number}</h2>
            <p className="text-xs text-gray-400 mt-0.5">Indent Details</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-0 overflow-y-auto">
          {field('Order Date', indent.request_date)}
          {field('Requested By', indent.requested_by_name)}
          {field('From', indent.from_location)}
          {field('Requested To', indent.to_location)}
          {field('Need By', indent.need_by_date)}

          {/* Items — editable rows */}
          <div className="py-3 border-b border-gray-50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-500">Items</span>
              <button
                type="button"
                onClick={addItemRow}
                className="flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Item
              </button>
            </div>
            <div className="space-y-1.5">
              <div className="grid grid-cols-[1fr_72px_28px] gap-2">
                <span className="text-xs text-gray-400 px-1">Item</span>
                <span className="text-xs text-gray-400 px-1">Qty</span>
                <span />
              </div>
              {itemRows.map((row, i) => (
                <div key={i} className="grid grid-cols-[1fr_72px_28px] gap-2 items-center">
                  <input
                    type="text"
                    value={row.item}
                    onChange={e => updateItemRow(i, 'item', e.target.value)}
                    placeholder="e.g. Sanitizer"
                    className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <input
                    type="number"
                    min="1"
                    value={row.qty}
                    onChange={e => updateItemRow(i, 'qty', e.target.value)}
                    placeholder="Qty"
                    className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-center"
                  />
                  {itemRows.length > 1 ? (
                    <button
                      type="button"
                      onClick={() => removeItemRow(i)}
                      className="flex items-center justify-center w-7 h-7 rounded-lg text-gray-300 hover:text-red-400 hover:bg-red-50 transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  ) : <span />}
                </div>
              ))}
            </div>
            <div className="flex justify-end mt-2">
              <button
                onClick={handleItemsSave}
                className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                {itemsSaved ? '✓ Items Saved' : 'Save Items'}
              </button>
            </div>
          </div>

          {/* Status */}
          <div className="flex justify-between items-center py-2.5 border-b border-gray-50">
            <span className="text-xs font-medium text-gray-500 w-36 shrink-0">Status</span>
            <select
              value={indent.status}
              onChange={e => onStatusUpdate(indent.id, e.target.value)}
              className={`appearance-none text-xs font-medium px-2.5 py-1 rounded-full border-0 cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500 ${STATUS_BADGE[indent.status] ?? 'bg-gray-100 text-gray-600'}`}
            >
              {statuses.map(s => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </div>

          {/* Amount */}
          <div className="flex justify-between items-center py-3">
            <span className="text-xs font-medium text-gray-500 w-36 shrink-0">Amount (₹)</span>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min="0"
                step="0.01"
                value={amountInput}
                onChange={e => { setAmountInput(e.target.value); setAmountSaved(false) }}
                placeholder="e.g. 250.50"
                className="w-28 border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-right"
              />
              <button
                onClick={handleAmountSave}
                className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                {amountSaved ? '✓ Saved' : 'Save'}
              </button>
            </div>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 flex justify-end shrink-0">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900">
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function RequisitionsPage() {
  const qc = useQueryClient()
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'hospital_admin' || user?.role === 'store_manager'

  const [showAdd, setShowAdd] = useState(false)
  const [viewMine, setViewMine] = useState(!isAdmin)
  const [selectedIndent, setSelectedIndent] = useState<Requisition | null>(null)

  const { data: requisitions = [], isLoading } = useQuery({
    queryKey: ['indents', viewMine],
    queryFn: () => fetchRequisitions(viewMine),
    refetchInterval: 30_000,
  })

  const createMutation = useMutation({
    mutationFn: createRequisition,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['indents'] })
      setShowAdd(false)
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => updateStatus(id, status),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['indents'] })
      setSelectedIndent(prev => prev?.id === updated.id ? updated : prev)
    },
  })

  const amountMutation = useMutation({
    mutationFn: ({ id, amount }: { id: string; amount: number | null }) => updateAmount(id, amount),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['indents'] })
      setSelectedIndent(prev => prev?.id === updated.id ? updated : prev)
    },
  })

  const itemsMutation = useMutation({
    mutationFn: ({ id, items }: { id: string; items: string }) => updateItems(id, items),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['indents'] })
      setSelectedIndent(prev => prev?.id === updated.id ? updated : prev)
    },
  })

  const handleStatusUpdate = useCallback((id: string, status: string) => {
    statusMutation.mutate({ id, status })
  }, [statusMutation])

  const handleAmountUpdate = useCallback((id: string, amount: number | null) => {
    amountMutation.mutate({ id, amount })
  }, [amountMutation])

  const handleItemsUpdate = useCallback((id: string, items: string) => {
    itemsMutation.mutate({ id, items })
  }, [itemsMutation])

  // Real-time updates — refetch when admin changes any indent
  useWebSocket('indent:update', useCallback(() => {
    qc.invalidateQueries({ queryKey: ['indents'] })
  }, [qc]))

  return (
    <div className="p-6 flex flex-col gap-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Indent</h1>
          <p className="text-sm text-gray-500 mt-0.5">Raise and track internal supply requests across departments.</p>
        </div>
        {!isAdmin && (
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            Add Indent
          </button>
        )}
      </div>

      {/* Filter toggle (admin) */}
      {isAdmin && (
        <div className="flex gap-2">
          <button
            onClick={() => setViewMine(false)}
            className={`px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors ${!viewMine ? 'bg-blue-50 border-blue-400 text-blue-700' : 'border-gray-300 text-gray-500 hover:bg-gray-50'}`}
          >
            All Indents
          </button>
          <button
            onClick={() => setViewMine(true)}
            className={`px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors ${viewMine ? 'bg-blue-50 border-blue-400 text-blue-700' : 'border-gray-300 text-gray-500 hover:bg-gray-50'}`}
          >
            My Indents
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden shadow-sm">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-sm text-gray-400">Loading…</div>
        ) : requisitions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <div className="w-14 h-14 rounded-2xl bg-blue-50 flex items-center justify-center">
              <ClipboardList className="w-7 h-7 text-blue-400" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-gray-700">No indents yet</p>
              <p className="text-xs text-gray-400 mt-1">{isAdmin ? 'No indents have been raised yet.' : 'Click "Add Indent" to raise your first request.'}</p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">#Indent</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Order Date</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Requested By</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">From</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Requested To</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Need By</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Items</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Amount (₹)</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {requisitions.map(req => (
                  <tr
                    key={req.id}
                    className={`hover:bg-gray-50/60 transition-colors ${isAdmin ? 'cursor-pointer' : ''}`}
                    onClick={isAdmin ? () => setSelectedIndent(req) : undefined}
                  >
                    <td className="px-4 py-3 font-medium text-gray-900">{req.indent_number}</td>
                    <td className="px-4 py-3 text-gray-600">{req.request_date}</td>
                    <td className="px-4 py-3 text-gray-700">{req.requested_by_name}</td>
                    <td className="px-4 py-3 text-gray-700">{req.from_location}</td>
                    <td className="px-4 py-3 text-gray-700">{req.to_location}</td>
                    <td className="px-4 py-3 text-gray-600">{req.need_by_date}</td>
                    <td className="px-4 py-3">
                      {req.items ? (
                        <div className="flex flex-wrap gap-1">
                          {parseItemRows(req.items).map((r, i) => (
                            <span key={i} className="inline-flex items-center gap-1 text-xs bg-gray-100 text-gray-700 rounded-md px-2 py-0.5">
                              {r.item}{r.qty ? <span className="font-semibold text-gray-500">×{r.qty}</span> : null}
                            </span>
                          ))}
                        </div>
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3 text-gray-700 font-medium">
                      {req.amount !== null ? `₹${Number(req.amount).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      {isAdmin ? (
                        <StatusDropdown requisition={req} onUpdate={handleStatusUpdate} />
                      ) : (
                        <span className={`inline-block text-xs font-medium px-2.5 py-1 rounded-full ${STATUS_BADGE[req.status] ?? 'bg-gray-100 text-gray-600'}`}>
                          {STATUS_LABEL[req.status] ?? req.status}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Modal */}
      {showAdd && (
        <AddRequisitionModal
          onClose={() => setShowAdd(false)}
          onSubmit={payload => createMutation.mutate(payload)}
          submitting={createMutation.isPending}
        />
      )}

      {/* Indent Detail Modal (admin) */}
      {isAdmin && selectedIndent && (
        <IndentDetailModal
          indent={selectedIndent}
          onClose={() => setSelectedIndent(null)}
          onStatusUpdate={handleStatusUpdate}
          onAmountUpdate={handleAmountUpdate}
          onItemsUpdate={handleItemsUpdate}
        />
      )}
    </div>
  )
}
