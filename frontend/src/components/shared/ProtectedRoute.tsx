import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/features/auth/authStore'

export default function ProtectedRoute() {
  const location = useLocation()
  const accessToken = useAuthStore((s) => s.accessToken)
  const mustChangePassword = useAuthStore((s) => s.user?.mustChangePassword ?? false)
  const isAuthenticated = useAuthStore.getState().isAuthenticated

  if (!accessToken || !isAuthenticated()) {
    return <Navigate to="/login" replace />
  }

  if (mustChangePassword && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }

  return <Outlet />
}
