import { useQuery } from '@tanstack/react-query'
import { pharmacyDashboardService } from '@/services/pharmacyDashboardService'

export function usePharmacyCapabilities(enabled = true) {
  const query = useQuery({
    queryKey: ['pharmacy-dashboard-capabilities'],
    queryFn: pharmacyDashboardService.capabilities,
    enabled,
    staleTime: 60_000,
  })
  const permissions = query.data?.permissions ?? []
  return {
    ...query,
    permissions,
    hasPermission: (permission: string) => permissions.includes(permission),
  }
}
