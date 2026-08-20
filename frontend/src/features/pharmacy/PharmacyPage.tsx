/**
 * Pharmacy Queue Page
 *
 * Shows patients dispatched to pharmacy.
 * Pharmacist can Dispense (opens billing modal) or Cancel any active order.
 */
import { useCallback, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { pharmacyService } from '@/services/pharmacyService'
import { useWebSocket } from '@/hooks/useWebSocket'
import PharmacyDispenseModal from './PharmacyDispenseModal'
import type { PharmacyQueueItem } from '@/types/common'
import ClinicalAlertBanner from '@/components/shared/ClinicalAlertBanner'

export default function PharmacyPage() {
  const qc = useQueryClient()
  const [dispenseItem, setDispenseItem] = useState<PharmacyQueueItem | null>(null)

  const { data: items = [], refetch } = useQuery({
    queryKey: ['pharmacy'],
    queryFn: () => pharmacyService.list(),
    refetchInterval: 30_000,
  })

  useWebSocket('pharmacy:update', useCallback(() => refetch(), [refetch]))
  useWebSocket('visit:update', useCallback(() => refetch(), [refetch]))

  const { mutate: advance, isPending } = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      pharmacyService.updateStatus(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pharmacy'] }),
  })

  const handleDispense = useCallback((item: PharmacyQueueItem) => {
    setDispenseItem(item)
  }, [])

  const handleModalDone = useCallback(() => {
    setDispenseItem(null)
    qc.invalidateQueries({ queryKey: ['pharmacy'] })
  }, [qc])

  const active = items.filter((i: PharmacyQueueItem) => i.status !== 'dispensed' && i.status !== 'cancelled')
  const dispensed = items.filter((i: PharmacyQueueItem) => i.status === 'dispensed')

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Pharmacy Queue</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {active.length} active · {dispensed.length} dispensed today
        </p>
      </div>

      {/* Active orders */}
      {active.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400">
          No pending pharmacy orders
        </div>
      ) : (
        <div className="space-y-3">
          {active.map((item: PharmacyQueueItem) => <PharmacyCard key={item.id} item={item} onAdvance={advance} onDispense={handleDispense} advancing={isPending} />)}
        </div>
      )}

      {/* Dispensed (collapsed) */}
      {dispensed.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-700 list-none flex items-center gap-1">
            <svg className="w-4 h-4 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            {dispensed.length} dispensed orders today
          </summary>
          <div className="mt-2 space-y-2">
            {dispensed.map((item: PharmacyQueueItem) => <PharmacyCard key={item.id} item={item} onAdvance={advance} onDispense={handleDispense} advancing={isPending} />)}
          </div>
        </details>
      )}

      {dispenseItem && (
        <PharmacyDispenseModal
          item={dispenseItem}
          onClose={() => setDispenseItem(null)}
          onDone={handleModalDone}
        />
      )}
    </div>
  )
}

function PharmacyCard({
  item,
  onAdvance,
  onDispense,
  advancing,
}: {
  item: PharmacyQueueItem
  onAdvance: (args: { id: string; status: string }) => void
  onDispense: (item: PharmacyQueueItem) => void
  advancing: boolean
}) {
  const isActionable = item.status !== 'dispensed' && item.status !== 'cancelled'

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <p className="font-semibold text-gray-900">{item.patient_name || 'Patient'}</p>
          </div>
          <ClinicalAlertBanner patientId={item.patient_id} />
          <p className="text-xs text-gray-400">{new Date(item.updated_at).toLocaleTimeString()}</p>

          {item.medicines && item.medicines.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium text-gray-500 mb-1.5">Medicines:</p>
              <div className="space-y-1">
                {item.medicines.map((m, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-400 shrink-0" />
                    <span className="font-medium text-gray-800">{m.name}</span>
                    {m.dose && <span className="text-gray-500">{m.dose}</span>}
                    {m.frequency && <span className="text-gray-400 text-xs">— {m.frequency}</span>}
                    {m.duration && <span className="text-gray-400 text-xs">× {m.duration}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {isActionable && (
          <div className="flex flex-col gap-2 shrink-0">
            <button
              disabled={advancing}
              onClick={() => onDispense(item)}
              className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium disabled:opacity-50"
            >
              Dispense
            </button>
            <button
              disabled={advancing}
              onClick={() => onAdvance({ id: item.id, status: 'cancelled' })}
              className="px-4 py-2 bg-white hover:bg-red-50 text-red-600 border border-red-300 rounded-lg text-sm font-medium disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
