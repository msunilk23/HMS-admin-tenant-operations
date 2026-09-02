import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DoctorLabResultsPage from './LabResultsPage'
import { labService } from '@/services/labService'
import { visitService } from '@/services/visitService'

vi.mock('@/hooks/useWebSocket', () => ({ useWebSocket: vi.fn() }))
vi.mock('@/services/labService', () => ({
  labService: { listOrders: vi.fn() },
}))
vi.mock('@/services/visitService', () => ({
  visitService: { list: vi.fn() },
}))

const mockedLabService = vi.mocked(labService)
const mockedVisitService = vi.mocked(visitService)
const visit = {
  id: 'visit-1',
  created_at: '2026-09-01T08:00:00Z',
  patient: { first_name: 'Asha', uhid: 'UHID-001' },
}
const verifiedOrder = {
  id: 'order-1', visit_id: 'visit-1', status: 'verified' as const, ordered_at: '2026-09-01T08:00:00Z',
  tests: [{ test_code: 'CBC', test_name: 'Complete Blood Count', unit: 'cells/uL', reference_range: '4.5-11.0' }],
  result: {
    id: 'result-1', lab_order_id: 'order-1', results: { CBC: '15.2' }, critical_flags: { CBC: true },
    reported_at: '2026-09-01T09:00:00Z', verified_at: '2026-09-01T09:30:00Z',
  },
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DoctorLabResultsPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedVisitService.list.mockResolvedValue([visit] as never)
  mockedLabService.listOrders.mockResolvedValue([verifiedOrder])
})
afterEach(cleanup)

describe('DoctorLabResultsPage', () => {
  it('loads only verified results for the selected visit and renders critical details', async () => {
    renderPage()
    await screen.findByRole('option', { name: /Asha/ })
    fireEvent.change(screen.getByLabelText('Select Patient/Visit'), { target: { value: 'visit-1' } })

    expect(await screen.findByText('Complete Blood Count')).toBeInTheDocument()
    expect(screen.getByText('15.2')).toBeInTheDocument()
    expect(screen.getByText('CRITICAL')).toBeInTheDocument()
    expect(mockedLabService.listOrders).toHaveBeenCalledWith({ visit_id: 'visit-1', status: 'verified' })
  })

  it('renders loading, error, and empty states after visit selection', async () => {
    mockedLabService.listOrders.mockImplementation(() => new Promise(() => {}))
    renderPage()
    await screen.findByRole('option', { name: /Asha/ })
    fireEvent.change(await screen.findByLabelText('Select Patient/Visit'), { target: { value: 'visit-1' } })
    expect(screen.getByRole('status')).toHaveTextContent('Loading lab results')
    cleanup()

    mockedLabService.listOrders.mockRejectedValue(new Error('offline'))
    renderPage()
    await screen.findByRole('option', { name: /Asha/ })
    fireEvent.change(await screen.findByLabelText('Select Patient/Visit'), { target: { value: 'visit-1' } })
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load lab results')
    cleanup()

    mockedLabService.listOrders.mockResolvedValue([])
    renderPage()
    await screen.findByRole('option', { name: /Asha/ })
    fireEvent.change(await screen.findByLabelText('Select Patient/Visit'), { target: { value: 'visit-1' } })
    await waitFor(() => expect(screen.getByText('No lab results found for this visit.')).toBeInTheDocument())
  })
})