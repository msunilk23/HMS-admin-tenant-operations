import { Navigate } from 'react-router-dom'
import { usePharmacyCapabilities } from '@/hooks/usePharmacyCapabilities'

interface PermissionGuardProps {
  permission: string
  children: React.ReactNode
}

export default function PermissionGuard({ permission, children }: PermissionGuardProps) {
  const { isLoading, isError, hasPermission } = usePharmacyCapabilities()

  if (isLoading) {
    return <div className="p-6" role="status">Checking access...</div>
  }
  if (isError || !hasPermission(permission)) {
    return <Navigate to="/dashboard" replace />
  }
  return <>{children}</>
}
