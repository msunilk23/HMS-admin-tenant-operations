import { useState, useEffect, useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { pharmacyService } from '@/services/pharmacyService'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { PharmacyLineItem } from '@/services/pharmacyService'
import type { PharmacyQueueItem } from '@/types/common'

interface Props {
  item: PharmacyQueueItem
  onClose: () => void
  onDone: () => void
}

function computeRowTotal(row: PharmacyLineItem): number {
  const base = row.qty * row.mrp * (1 - row.dis_pct / 100) * (1 + row.gst_pct / 100)
  return Math.round(base * 100) / 100
}

function emptyRow(name = ''): PharmacyLineItem {
  return { name, mfr: '', batch: '', expiry: '', qty: 1, mrp: 0, gst_pct: 0, dis_pct: 0, total: 0 }
}

export default function PharmacyDispenseModal({ item, onClose, onDone }: Props) {
  const qc = useQueryClient()
  const [rows, setRows] = useState<PharmacyLineItem[]>(() =>
    item.medicines && item.medicines.length > 0
      ? item.medicines.map(m => emptyRow(m.name))
      : [emptyRow()]
  )
  const [discount, setDiscount] = useState(0)
  const [payMethod, setPayMethod] = useState<'cash' | 'online'>('cash')
  const [onlineError, setOnlineError] = useState<string | null>(null)
  const [processingOnlinePayment, setProcessingOnlinePayment] = useState(false)

  // Listen for pharmacy online payment success via WebSocket
  useWebSocket('pharmacy:update', useCallback((msg: unknown) => {
    if (typeof msg === 'object' && msg !== null && 'event' in msg) {
      const message = msg as { event: string }
      if (message.event === 'pharmacy_online_paid') {
        setProcessingOnlinePayment(false)
        qc.invalidateQueries({ queryKey: ['pharmacy'] })
        setTimeout(() => onDone(), 500)
      }
    }
  }, [qc, onDone]))

  const subtotal = rows.reduce((s, r) => s + r.total, 0)
  const gstTotal = rows.reduce((s, r) => {
    const lineGst = r.qty * r.mrp * (r.gst_pct / 100) * (1 - r.dis_pct / 100)
    return s + Math.round(lineGst * 100) / 100
  }, 0)
  const grandTotal = Math.max(subtotal - discount, 0)

  const updateRow = (idx: number, field: keyof PharmacyLineItem, raw: string | number) => {
    setRows(prev => {
      const next = prev.map((r, i) => {
        if (i !== idx) return r
        const updated = { ...r, [field]: typeof raw === 'string' ? raw : Number(raw) }
        updated.total = computeRowTotal(updated)
        return updated
      })
      return next
    })
  }

  const addRow = () => setRows(prev => [...prev, emptyRow()])
  const removeRow = (idx: number) => setRows(prev => prev.filter((_, i) => i !== idx))

  const billMut = useMutation({
    mutationFn: (pm: 'cash' | 'online') =>
      pharmacyService.bill(item.id, { line_items: rows, discount, payment_method: pm }),
  })

  const handleCash = useCallback(async () => {
    await billMut.mutateAsync('cash')
    qc.invalidateQueries({ queryKey: ['pharmacy'] })
    onDone()
  }, [billMut, qc, onDone])

  const handleOnline = useCallback(async () => {
    setOnlineError(null)
    // Call the API which will create invoice + broadcast payment_request to POS kiosk
    try {
      await billMut.mutateAsync('online')
      setProcessingOnlinePayment(true)
    } catch {
      // error shown via billMut.error state
    }
  }, [billMut])

  // Close on Escape (unless processing online payment)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !processingOnlinePayment) onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose, processingOnlinePayment])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Dispense Medicines</h2>
            <p className="text-sm text-gray-500">{item.patient_name ?? 'Patient'}</p>
          </div>
          <button onClick={onClose} disabled={processingOnlinePayment} className="text-gray-400 hover:text-gray-600 text-xl leading-none disabled:opacity-50">✕</button>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-auto px-6 py-4">
          <table className="w-full text-sm border-separate border-spacing-y-1">
            <thead>
              <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <th className="pb-2 pr-2">Product Name</th>
                <th className="pb-2 pr-2">MFR</th>
                <th className="pb-2 pr-2">Batch</th>
                <th className="pb-2 pr-2">Expiry</th>
                <th className="pb-2 pr-2 text-right">Qty</th>
                <th className="pb-2 pr-2 text-right">MRP (₹)</th>
                <th className="pb-2 pr-2 text-right">GST%</th>
                <th className="pb-2 pr-2 text-right">Dis%</th>
                <th className="pb-2 text-right">Total (₹)</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr key={idx} className="bg-gray-50 rounded">
                  <td className="py-1 pr-2">
                    <input
                      value={row.name}
                      onChange={e => updateRow(idx, 'name', e.target.value)}
                      className="w-full px-2 py-1 rounded border border-gray-200 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
                      placeholder="Medicine name"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      value={row.mfr}
                      onChange={e => updateRow(idx, 'mfr', e.target.value)}
                      className="w-24 px-2 py-1 rounded border border-gray-200 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
                      placeholder="MFR"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      value={row.batch}
                      onChange={e => updateRow(idx, 'batch', e.target.value)}
                      className="w-24 px-2 py-1 rounded border border-gray-200 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
                      placeholder="Batch"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      value={row.expiry}
                      onChange={e => updateRow(idx, 'expiry', e.target.value)}
                      className="w-24 px-2 py-1 rounded border border-gray-200 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
                      placeholder="MM/YYYY"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      type="number" min={1}
                      value={row.qty}
                      onChange={e => updateRow(idx, 'qty', e.target.value)}
                      className="w-16 px-2 py-1 rounded border border-gray-200 text-sm text-right focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      type="number" min={0} step={0.01}
                      value={row.mrp}
                      onChange={e => updateRow(idx, 'mrp', e.target.value)}
                      className="w-20 px-2 py-1 rounded border border-gray-200 text-sm text-right focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      type="number" min={0} max={28} step={0.5}
                      value={row.gst_pct}
                      onChange={e => updateRow(idx, 'gst_pct', e.target.value)}
                      className="w-16 px-2 py-1 rounded border border-gray-200 text-sm text-right focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      type="number" min={0} max={100} step={0.5}
                      value={row.dis_pct}
                      onChange={e => updateRow(idx, 'dis_pct', e.target.value)}
                      className="w-16 px-2 py-1 rounded border border-gray-200 text-sm text-right focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                  </td>
                  <td className="py-1 text-right font-medium text-gray-800">₹{row.total.toFixed(2)}</td>
                  <td className="py-1 pl-2">
                    {rows.length > 1 && (
                      <button onClick={() => removeRow(idx)} className="text-red-400 hover:text-red-600 text-lg leading-none">✕</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <button
            onClick={addRow}
            className="mt-2 text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            + Add row
          </button>
        </div>

        {/* Summary + Payment */}
        <div className="px-6 py-4 border-t border-gray-200 space-y-4">
          <div className="flex items-end gap-8 justify-end">
            <div className="text-right space-y-1 text-sm text-gray-600">
              <div className="flex gap-8 justify-between"><span>Subtotal</span><span>₹{subtotal.toFixed(2)}</span></div>
              <div className="flex gap-8 justify-between"><span>GST</span><span>₹{gstTotal.toFixed(2)}</span></div>
              <div className="flex gap-8 justify-between items-center">
                <span>Discount (₹)</span>
                <input
                  type="number" min={0} step={1}
                  value={discount}
                  onChange={e => setDiscount(Number(e.target.value))}
                  className="w-24 px-2 py-1 rounded border border-gray-200 text-sm text-right focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>
              <div className="flex gap-8 justify-between font-semibold text-gray-900 text-base border-t border-gray-200 pt-1">
                <span>Grand Total</span><span>₹{grandTotal.toFixed(2)}</span>
              </div>
            </div>
          </div>

          {/* Payment method */}
          <div className="flex items-center gap-6">
            <span className="text-sm font-medium text-gray-700">Payment:</span>
            {(['cash', 'online'] as const).map(pm => (
              <label key={pm} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="pay-method"
                  value={pm}
                  checked={payMethod === pm}
                  onChange={() => setPayMethod(pm)}
                  className="accent-blue-600"
                />
                <span className="text-sm capitalize">{pm === 'online' ? 'Online (Razorpay)' : 'Cash'}</span>
              </label>
            ))}
          </div>

          {(billMut.error || onlineError) && (
            <p className="text-sm text-red-600">
              {onlineError ?? (billMut.error as Error)?.message ?? 'Something went wrong'}
            </p>
          )}

          {processingOnlinePayment && (
            <p className="text-sm text-blue-600 text-center">�️ Payment request sent to POS kiosk. Please complete payment on the terminal.</p>
          )}

          <div className="flex gap-3 justify-end">
            <button
              onClick={onClose}
              disabled={processingOnlinePayment || billMut.isPending}
              className="px-4 py-2 rounded-lg border border-gray-300 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              disabled={billMut.isPending || processingOnlinePayment || grandTotal <= 0}
              onClick={payMethod === 'cash' ? handleCash : handleOnline}
              className="px-6 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium disabled:opacity-50"
            >
              {billMut.isPending
                ? 'Processing…'
                : payMethod === 'cash'
                  ? `Collect ₹${grandTotal.toFixed(2)} Cash & Dispense`
                  : `Pay ₹${grandTotal.toFixed(2)} Online`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
