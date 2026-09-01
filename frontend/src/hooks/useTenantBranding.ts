import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/features/auth/authStore'
import { tenantService } from '@/services/tenantService'

/**
 * Live tenant branding (logo/colors), polled independently of the JWT so an
 * already-open session picks up a Super Admin's changes without re-login.
 * Falls back to the JWT-embedded values until the first poll resolves.
 */
export function useTenantBranding() {
  const user = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)
  const isTenantUser = Boolean(user) && user?.role !== 'super_admin'

  const query = useQuery({
    queryKey: ['tenant-branding'],
    queryFn: tenantService.getBranding,
    enabled: Boolean(accessToken) && isTenantUser,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  return {
    isTenantUser,
    logoUrl: isTenantUser ? (query.data?.logo_url ?? user?.logoUrl ?? null) : null,
    primaryColor: isTenantUser ? (query.data?.primary_color ?? user?.primaryColor ?? null) : null,
    secondaryColor: isTenantUser ? (query.data?.secondary_color ?? user?.secondaryColor ?? null) : null,
    hospitalName: query.data?.hospital_name ?? user?.hospitalName ?? null,
  }
}
