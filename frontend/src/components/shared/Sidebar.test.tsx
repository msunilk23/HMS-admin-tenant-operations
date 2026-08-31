import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import Sidebar from './Sidebar'
import { useAuthStore } from '@/features/auth/authStore'

const ALL_FEATURES = ['appointments', 'opd_queue', 'vitals', 'nurse_roster', 'lab', 'pharmacy', 'billing']

function setRole(role: string) {
  useAuthStore.setState({
    accessToken: 'test-token',
    refreshToken: 'test-refresh',
    sessionExpired: false,
    features: ALL_FEATURES,
    user: {
      id: 'user-1',
      email: '',
      fullName: 'Test User',
      role,
      tenantSchema: 'demo',
      hospitalName: 'Demo Hospital',
      mustChangePassword: false,
    },
  })
}

function renderSidebar(initialPath: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="*" element={<Sidebar mobileOpen={false} onCloseMobile={() => {}} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  cleanup()
  useAuthStore.setState({ accessToken: null, refreshToken: null, user: null, features: null, sessionExpired: false })
})

describe('Sidebar active-route behaviour', () => {
  it('expands and highlights the parent domain of the active route', () => {
    setRole('doctor')
    renderSidebar('/doctor/consultation')

    expect(screen.getByRole('button', { name: 'Clinical Care' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Consultation' })).toHaveAttribute('aria-current', 'page')
  })

  it('activates Doctor Workspace/Consultation for a dynamic prescription route', () => {
    setRole('doctor')
    renderSidebar('/doctor/prescription/abc-123')

    expect(screen.getByRole('button', { name: 'Clinical Care' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Consultation' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('Sidebar nested subsection collapse', () => {
  it('collapses and expands Nursing independently of Doctor Workspace', () => {
    setRole('hospital_admin')
    renderSidebar('/dashboard')

    fireEvent.click(screen.getByRole('button', { name: 'Clinical Care' }))
    const nursing = screen.getByRole('button', { name: 'Nursing' })
    const doctorWorkspace = screen.getByRole('button', { name: 'Doctor Workspace' })
    expect(nursing).toHaveAttribute('aria-expanded', 'false')
    expect(doctorWorkspace).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Vitals' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Consultation' })).not.toBeInTheDocument()

    fireEvent.click(nursing)
    expect(nursing).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Vitals' })).toBeInTheDocument()
    expect(doctorWorkspace).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Consultation' })).not.toBeInTheDocument()

    fireEvent.click(doctorWorkspace)
    expect(screen.getByRole('link', { name: 'Consultation' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Vitals' })).toBeInTheDocument()

    fireEvent.click(nursing)
    expect(nursing).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Vitals' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Consultation' })).toBeInTheDocument()
  })
})

describe('Sidebar collapsed/expanded persistence', () => {
  it('starts expanded when no preference has been saved', () => {
    setRole('hospital_admin')
    renderSidebar('/dashboard')

    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
    expect(screen.getByText('Front Desk')).toBeInTheDocument()
  })

  it('restores a collapsed preference from localStorage', () => {
    window.localStorage.setItem('hms.sidebar.collapsed', 'true')
    setRole('hospital_admin')
    renderSidebar('/dashboard')

    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
    expect(screen.queryByText('Front Desk')).not.toBeInTheDocument()
  })
})

describe('Sidebar keyboard interaction', () => {
  it('expands and collapses a domain group via keyboard activation', () => {
    setRole('hospital_admin')
    renderSidebar('/dashboard')

    const frontDesk = screen.getByRole('button', { name: 'Front Desk' })
    expect(frontDesk).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Patients' })).not.toBeInTheDocument()

    fireEvent.keyDown(frontDesk, { key: 'Enter' })
    expect(frontDesk).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Patients' })).toBeInTheDocument()

    fireEvent.keyDown(frontDesk, { key: ' ' })
    expect(frontDesk).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Patients' })).not.toBeInTheDocument()
  })
})
