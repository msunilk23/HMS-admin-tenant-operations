import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Menu } from 'lucide-react'
import { useAuthStore } from '@/features/auth/authStore'
import { useTenantBranding } from '@/hooks/useTenantBranding'
import Sidebar from './Sidebar'
import hospitalLogo from '../../../logo/hospital-logo-design-vector-medical-cross_53876-136743.avif'

export default function AppLayout() {
  const { user, logout, refreshToken } = useAuthStore()
  const { logoUrl, hospitalName } = useTenantBranding()
  const navigate = useNavigate()
  const location = useLocation()
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const tenantLogo = logoUrl || hospitalLogo

  // Close the mobile drawer whenever the route changes (e.g. back/forward nav).
  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  const openUserMenu = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setUserMenuOpen(true)
  }
  const closeUserMenu = () => {
    closeTimer.current = setTimeout(() => setUserMenuOpen(false), 150)
  }

  const handleLogout = async () => {
    // Revoke the refresh token on the server before clearing local state.
    if (refreshToken) {
      try {
        await fetch('/api/v1/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
      } catch {
        // Proceed with local logout even if server call fails
      }
    }
    // Clearing auth state is enough — ProtectedRoute subscribes to accessToken
    // and will immediately redirect to /login when it becomes null.
    logout()
  }

  return (
    <div className="flex h-screen bg-primary-tint overflow-hidden">
      <Sidebar mobileOpen={mobileNavOpen} onCloseMobile={() => setMobileNavOpen(false)} />

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-16 flex-shrink-0 bg-white border-b-2 border-primary-tint flex items-center px-4 sm:px-6 gap-2">
          {/* Mobile nav toggle — sidebar becomes an overlay drawer below the lg breakpoint */}
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors lg:hidden"
            aria-label="Open navigation menu"
          >
            <Menu className="w-5 h-5" aria-hidden="true" />
          </button>

          {/* Left: logo + hospital / platform name — always visible */}
          <div className="flex items-center gap-2 min-w-0">
            {user?.role !== 'super_admin' && (
              <img src={tenantLogo} alt={`${hospitalName ?? 'Hospital'} logo`} className="w-8 h-8 rounded-full object-cover flex-shrink-0" />
            )}
            {user?.role === 'super_admin' ? (
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-primary">HMS Platform</p>
                <p className="text-xs text-gray-400">Super Admin Console</p>
              </div>
            ) : (
              <p className="text-base font-bold text-gray-900 truncate">{hospitalName ?? 'Hospital'}</p>
            )}
          </div>
          <div className="flex-1" />
          {/* Right: user avatar + hover dropdown */}
          <div
            className="relative"
            onMouseEnter={openUserMenu}
            onMouseLeave={closeUserMenu}
          >
            {/* Avatar trigger */}
            <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer hover:bg-gray-100 transition-colors select-none">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                <span className="text-sm font-semibold text-primary">
                  {user?.fullName?.charAt(0)?.toUpperCase() ?? 'U'}
                </span>
              </div>
              <div className="text-right hidden sm:block">
                <p className="text-sm font-medium text-gray-900 leading-tight">{user?.fullName}</p>
                <p className="text-xs text-gray-500 capitalize">{user?.role?.replace(/_/g, ' ')}</p>
              </div>
            </div>

            {/* Dropdown */}
            {userMenuOpen && (
              <div
                className="absolute right-0 top-full w-48 bg-white rounded-xl shadow-lg border border-gray-100 py-1 z-50"
                onMouseEnter={openUserMenu}
                onMouseLeave={closeUserMenu}
              >
                <button
                  onClick={() => { setUserMenuOpen(false); navigate('/change-password') }}
                  className="w-full flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                  </svg>
                  Change password
                </button>
                <div className="border-t border-gray-100 my-1" />
                <button
                  onClick={() => { setUserMenuOpen(false); handleLogout() }}
                  className="w-full flex items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                  </svg>
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
