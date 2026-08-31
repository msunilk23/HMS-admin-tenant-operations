import { useState, useRef } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { BarChart3, ClipboardCheck } from 'lucide-react'
import { useAuthStore } from '@/features/auth/authStore'
import { usePharmacyCapabilities } from '@/hooks/usePharmacyCapabilities'
import { P34_PERMISSIONS } from '@/services/pharmacyDashboardService'
import hospitalLogo from '../../../logo/hospital-logo-design-vector-medical-cross_53876-136743.avif'

interface NavItem {
  label: string
  to: string
  icon: React.ReactNode
  roles?: string[]
  feature?: string
  permission?: string
}

const NAV_ITEMS: NavItem[] = [
  {
    label: 'Dashboard',
    to: '/dashboard',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
    roles: ['hospital_admin'],
  },
  {
    label: 'Patients',
    to: '/patients',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    roles: ['receptionist', 'hospital_admin'],
  },
  {
    label: 'Register Visit',
    to: '/register-visit',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 4v16m8-8H4" />
      </svg>
    ),
    roles: ['receptionist', 'hospital_admin'],
  },
  {
    label: 'Appointments',
    to: '/appointments',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    ),
    roles: ['receptionist', 'hospital_admin'],
    feature: 'appointments',
  },
  {
    label: 'OPD Queue',
    to: '/queue',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
      </svg>
    ),
    roles: ['receptionist', 'hospital_admin'],
    feature: 'opd_queue',
  },
  {
    label: 'Vitals',
    to: '/nurse/vitals',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
      </svg>
    ),
    roles: ['nurse', 'hospital_admin'],
    feature: 'vitals',
  },
  {
    label: 'Nurse Roster',
    to: '/nurse/roster',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
      </svg>
    ),
    roles: ['nurse', 'hospital_admin'],
    feature: 'nurse_roster',
  },
  {
    label: 'Consultation',
    to: '/doctor/consultation',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
    roles: ['doctor', 'hospital_admin'],
  },
  {
    label: 'Lab Results',
    to: '/doctor/lab-results',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0010.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
      </svg>
    ),
    roles: ['doctor', 'hospital_admin'],
  },
  {
    label: 'Lab',
    to: '/lab',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
      </svg>
    ),
    roles: ['lab_technician', 'hospital_admin'],
    feature: 'lab',
  },
  {
    label: 'Pharmacy',
    to: '/pharmacy',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
    roles: ['pharmacist', 'store_manager', 'hospital_admin', 'auditor'],
    feature: 'pharmacy',
  },
  {
    label: 'Pharmacy Dashboard',
    to: '/pharmacy/dashboard',
    icon: <BarChart3 className="h-5 w-5" />,
    roles: ['pharmacist', 'hospital_admin'],
    feature: 'pharmacy',
    permission: P34_PERMISSIONS.dashboard,
  },
  {
    label: 'Patient Returns',
    to: '/pharmacy/patient-returns',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 7h16M4 12h9m-9 5h16" />
      </svg>
    ),
    roles: ['pharmacist', 'hospital_admin'],
    feature: 'pharmacy',
  },
  {
    label: 'Supplier Returns',
    to: '/pharmacy/supplier-returns',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M5 7h14v10H5zM9 7V5h6v2" />
      </svg>
    ),
    roles: ['pharmacist', 'hospital_admin'],
    feature: 'pharmacy',
  },
  {
    label: 'Stock Quarantine',
    to: '/pharmacy/quarantine',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 9v4m0 4h.01M5.2 20h13.6a2 2 0 001.74-3L13.74 5a2 2 0 00-3.48 0L3.46 17a2 2 0 001.74 3z" />
      </svg>
    ),
    roles: ['pharmacist', 'store_manager', 'hospital_admin'],
    feature: 'pharmacy',
  },
  {
    label: 'Recall & Transfers',
    to: '/pharmacy/operations',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M7 7h11l-3-3m3 3-3 3M17 17H6l3 3m-3-3 3-3" />
      </svg>
    ),
    roles: ['pharmacist', 'store_manager', 'hospital_admin'],
    feature: 'pharmacy',
  },
  {
    label: 'Inventory Counts',
    to: '/pharmacy/inventory-counts',
    icon: <ClipboardCheck className="h-5 w-5" />,
    roles: ['pharmacist', 'store_manager', 'hospital_admin', 'auditor'],
    feature: 'pharmacy',
  },
  {
    label: 'Billing',
    to: '/billing',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z" />
      </svg>
    ),
    roles: ['billing_officer', 'hospital_admin'],
    feature: 'billing',
  },
  {
    label: 'Indent',
    to: '/indent',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
      </svg>
    ),
    roles: ['hospital_admin', 'receptionist', 'nurse', 'doctor', 'lab_technician', 'pharmacist', 'billing_officer', 'store_manager'],
  },
  {
    label: 'Doctors',
    to: '/admin/doctors',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M5.121 17.804A13.937 13.937 0 0112 16c2.5 0 4.847.655 6.879 1.804M15 10a3 3 0 11-6 0 3 3 0 016 0zm6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    roles: ['hospital_admin'],
  },
  {
    label: 'Staff Users',
    to: '/admin/users',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    roles: ['hospital_admin'],
  },
  {
    label: 'Hospitals',
    to: '/super/hospitals',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
      </svg>
    ),
    roles: ['super_admin'],
  },
]

export default function AppLayout() {
  const { user, logout, hasFeature, refreshToken } = useAuthStore()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(true)
  const [hovered, setHovered] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hospitalName = user?.hospitalName ?? 'Hospital'
  const tenantLogo = user?.logoUrl || hospitalLogo

  const openUserMenu = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setUserMenuOpen(true)
  }
  const closeUserMenu = () => {
    closeTimer.current = setTimeout(() => setUserMenuOpen(false), 150)
  }
  const isExpanded = !collapsed || hovered
  const { hasPermission } = usePharmacyCapabilities(Boolean(user) && hasFeature('pharmacy'))

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

  const visibleItems = NAV_ITEMS.filter(
    (item) =>
      (!item.roles || (user && item.roles.includes(user.role))) &&
      (!item.feature || hasFeature(item.feature)) &&
      (!item.permission || hasPermission(item.permission)),
  )

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`flex-shrink-0 bg-white border-r border-gray-200 flex flex-col transition-all duration-200 overflow-hidden ${isExpanded ? 'w-64' : 'w-16'}`}
        onMouseEnter={() => { if (collapsed) setHovered(true) }}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Collapse toggle */}
        <div className="h-14 flex items-center justify-start px-3 border-b border-gray-200">
          <button
            onClick={() => { setCollapsed(c => !c); setHovered(false) }}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 px-3">
          <ul className="space-y-0.5">
            {visibleItems.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  title={!isExpanded ? item.label : undefined}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                      !isExpanded ? 'justify-center' : ''
                    } ${
                      isActive
                        ? 'bg-primary/10 text-primary font-medium'
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                    }`
                  }
                >
                  {item.icon}
                  {isExpanded && <span className="whitespace-nowrap">{item.label}</span>}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        {/* User footer — removed, user info moved to header */}
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-16 flex-shrink-0 bg-white border-b border-gray-200 flex items-center px-6">
          {/* Left: logo + hospital / platform name — always visible */}
          <div className="flex items-center gap-2">
            {user?.role !== 'super_admin' && (
              <img src={tenantLogo} alt={`${hospitalName} logo`} className="w-8 h-8 rounded-full object-cover flex-shrink-0" />
            )}
            {user?.role === 'super_admin' ? (
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-primary">HMS Platform</p>
                <p className="text-xs text-gray-400">Super Admin Console</p>
              </div>
            ) : (
              <p className="text-base font-bold text-gray-900">{user?.hospitalName ?? 'Hospital'}</p>
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
              <div className="text-right">
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
