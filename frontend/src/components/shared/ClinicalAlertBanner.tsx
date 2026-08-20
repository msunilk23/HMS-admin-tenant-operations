import { useQuery } from '@tanstack/react-query'
import { clinicalAlertService } from '@/services/clinicalAlertService'

export default function ClinicalAlertBanner({ patientId }: { patientId?: string }) {
  const { data: alerts = [] } = useQuery({
    queryKey: ['clinical-alerts', patientId],
    queryFn: () => clinicalAlertService.listForPatient(patientId!),
    enabled: !!patientId,
    staleTime: 15_000,
  })

  if (!alerts.length) return null

  return (
    <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900" role="alert">
      <div className="flex items-center gap-2 text-sm font-bold">
        <span aria-hidden="true">!</span>
        Active clinical alerts
      </div>
      <ul className="mt-1 space-y-1 text-sm">
        {alerts.map(alert => (
          <li key={alert.id}>
            <span className="font-semibold uppercase text-xs">{alert.severity}</span>{' '}
            {alert.alert_type === 'allergy' ? 'Allergy: ' : ''}{alert.description}
          </li>
        ))}
      </ul>
    </div>
  )
}