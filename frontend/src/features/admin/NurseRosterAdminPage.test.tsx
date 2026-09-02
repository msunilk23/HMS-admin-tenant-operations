import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import NurseRosterAdminPage from './NurseRosterAdminPage'
import { nurseRosterService } from '@/services/nurseRosterService'
import { departmentService, doctorService, userService } from '@/services/clinicalService'

vi.mock('@/services/nurseRosterService', () => ({
  nurseRosterService: { list: vi.fn(), create: vi.fn(), update: vi.fn(), auditHistory: vi.fn() },
}))
vi.mock('@/services/clinicalService', () => ({
  departmentService: { list: vi.fn() }, doctorService: { list: vi.fn() }, userService: { list: vi.fn() },
}))

const rosterService = vi.mocked(nurseRosterService)
const row = {
  id: 'roster-1', facility_id: 'facility-1', user_id: 'nurse-1', roster_date: '2026-09-01', shift: 'morning' as const,
  department_id: 'department-1', is_present: false, is_active: true, nurse_name: 'Nurse One', department_name: 'Ward One',
}
const renderPage = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><NurseRosterAdminPage /></QueryClientProvider>)

beforeEach(() => {
  vi.clearAllMocks()
  rosterService.list.mockResolvedValue([row])
  rosterService.auditHistory.mockResolvedValue([])
  rosterService.update.mockResolvedValue({ ...row, is_active: false })
  vi.mocked(userService.list).mockResolvedValue([{ id: 'nurse-1', full_name: 'Nurse One' }] as never)
  vi.mocked(departmentService.list).mockResolvedValue([{ id: 'department-1', name: 'Ward One' }] as never)
  vi.mocked(doctorService.list).mockResolvedValue([])
})
afterEach(cleanup)

describe('NurseRosterAdminPage', () => {
  it('renders loading, error, and empty roster states', async () => {
    rosterService.list.mockImplementation(() => new Promise(() => {})); renderPage(); expect(screen.getByRole('status')).toHaveTextContent('Loading roster'); cleanup()
    rosterService.list.mockRejectedValue(new Error('offline')); renderPage(); expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the roster'); cleanup()
    rosterService.list.mockResolvedValue([]); renderPage(); expect(await screen.findByText('No roster entries match the current filters.')).toBeInTheDocument()
  })

  it('requires confirmation reason and submits the successful deactivation', async () => {
    renderPage()
    await screen.findByText('Nurse One')
    fireEvent.click(screen.getByRole('button', { name: 'Deactivate' }))
    const submit = screen.getAllByRole('button', { name: 'Deactivate' }).at(-1)!
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'Coverage changed' } })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    await waitFor(() => expect(rosterService.update).toHaveBeenCalledWith('roster-1', { is_active: false, reason: 'Coverage changed' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Roster entry updated')
  })

  it('renders audit success and failure states', async () => {
    rosterService.auditHistory.mockResolvedValue([{ id: 'audit-1', action: 'DEACTIVATE', reason: 'Coverage changed', timestamp: '2026-09-01T10:00:00Z' }]); renderPage(); expect(await screen.findByText('Coverage changed')).toBeInTheDocument(); cleanup()
    rosterService.auditHistory.mockRejectedValue(new Error('offline')); renderPage(); expect(await screen.findByText('Could not load roster audit history.')).toBeInTheDocument()
  })
})