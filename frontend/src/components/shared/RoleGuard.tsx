import { Navigate } from 'react-router-dom'
import { useAuthStore } from '@/features/auth/authStore'

interface Props {
  allowed: string[]
  children: React.ReactNode
}

/**
 * Wraps a route element and redirects to "/" if the current user's role
 * is not in the allowed list. Use inside <Route element={<RoleGuard ...>}>.
 */
export default function RoleGuard({ allowed, children }: Props) {
  const role = useAuthStore((s) => s.user?.role ?? '')
  if (!allowed.includes(role)) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}
