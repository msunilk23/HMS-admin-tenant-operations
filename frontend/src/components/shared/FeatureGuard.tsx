import { Lock } from 'lucide-react'
import { useAuthStore } from '@/features/auth/authStore'

interface FeatureGuardProps {
  feature: string
  children: React.ReactNode
}

const FEATURE_LABELS: Record<string, string> = {
  appointments: 'Appointments',
  opd_queue: 'OPD Queue',
  vitals: 'Vitals',
  nurse_roster: 'Nurse Roster',
  consultations: 'Consultations',
  prescriptions: 'Prescriptions',
  lab: 'Laboratory',
  pharmacy: 'Pharmacy',
  billing: 'Billing & Invoicing',
}

/**
 * Shows a "Feature Not Available" wall when the tenant's plan does not include
 * the requested feature, instead of silently redirecting to /dashboard.
 * Works in tandem with the backend require_feature() dependency.
 */
export default function FeatureGuard({ feature, children }: FeatureGuardProps) {
  const hasFeature = useAuthStore((s) => s.hasFeature)

  if (!hasFeature(feature)) {
    const label = FEATURE_LABELS[feature] ?? feature
    return (
      <div className="flex flex-1 items-center justify-center p-12">
        <div className="text-center max-w-sm">
          <div className="w-16 h-16 rounded-2xl bg-amber-50 flex items-center justify-center mx-auto mb-5">
            <Lock className="w-8 h-8 text-amber-500" />
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Feature Not Available</h2>
          <p className="text-sm text-gray-600 mb-1">
            The <span className="font-medium text-gray-800">{label}</span> module is not
            enabled on your hospital's current plan.
          </p>
          <p className="text-xs text-gray-400 mt-3">
            Contact your platform administrator to upgrade your plan.
          </p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
