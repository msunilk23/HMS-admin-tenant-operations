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
  visitService: { get: vi.fn() },
}))

const mockedLabService = vi.mocked(labService)
const mockedVisitService = vi.mocked(visitService)
const visit = {
  id: 'visit-1',
  created_at: '2026-09-01T08:00:00Z',
  status: 'CLOSED',
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
  mockedVisitService.get.mockResolvedValue(visit as never)
  mockedLabService.listOrders.mockImplementation((params) =>
    Promise.resolve(params?.visit_id ? [verifiedOrder] : [verifiedOrder]),
  )
})
afterEach(cleanup)

describe('DoctorLabResultsPage', () => {
  it('includes a CLOSED PF-1 Visit with verified results and renders its critical result', async () => {
    renderPage()
    await screen.findByRole('option', { name: /Asha/ })
    fireEvent.change(screen.getByLabelText('Select Patient/Visit'), { target: { value: 'visit-1' } })

    expect(await screen.findByText('Complete Blood Count')).toBeInTheDocument()
    expect(screen.getByText('15.2')).toBeInTheDocument()
    expect(screen.getByText('CRITICAL')).toBeInTheDocument()
    expect(mockedLabService.listOrders).toHaveBeenCalledWith({ visit_id: 'visit-1', status: 'verified' })
  })

  it('deduplicates a Visit with multiple verified Lab orders and displays all its results', async () => {
    const secondOrder = {
      ...verifiedOrder,
      id: 'order-2',
      result: { ...verifiedOrder.result, id: 'result-2', lab_order_id: 'order-2', results: { LFT: '42' }, critical_flags: {}, verified_at: '2026-09-02T09:30:00Z' },
      tests: [{ test_code: 'LFT', test_name: 'Liver Function Test', unit: 'U/L', reference_range: '0-40' }],
    }
    mockedLabService.listOrders.mockImplementation((params) =>
      Promise.resolve(params?.visit_id ? [verifiedOrder, secondOrder] : [verifiedOrder, secondOrder]),
    )
    renderPage()
    await screen.findByRole('option', { name: /Asha/ })
    expect(screen.getAllByRole('option', { name: /Asha/ })).toHaveLength(1)
    fireEvent.change(screen.getByLabelText('Select Patient/Visit'), { target: { value: 'visit-1' } })
    expect(await screen.findByText('Complete Blood Count')).toBeInTheDocument()
    expect(screen.getByText('Liver Function Test')).toBeInTheDocument()
  })

  it('keeps a legacy CONSULTATION_COMPLETED Visit with verified results visible', async () => {
    mockedVisitService.get.mockResolvedValue({ ...visit, status: 'CONSULTATION_COMPLETED' } as never)
    renderPage()
    expect(await screen.findByRole('option', { name: /Asha.*UHID-001/ })).toBeInTheDocument()
  })

  it('excludes closed encounters without verified results by deriving candidates only from verified orders', async () => {
    mockedLabService.listOrders.mockResolvedValue([])
    renderPage()
    expect(await screen.findByText('No verified Lab results available')).toBeInTheDocument()
    expect(mockedVisitService.get).not.toHaveBeenCalled()
  })

  it('renders accessible loading, error, empty, and date-filter states', async () => {
    mockedLabService.listOrders.mockImplementation(() => new Promise(() => {}))
    renderPage()
    expect(await screen.findByRole('status')).toHaveTextContent('Loading verified Lab results')
    cleanup()

    mockedLabService.listOrders.mockRejectedValue(new Error('offline'))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load verified Lab results')
    cleanup()

    mockedLabService.listOrders.mockImplementation((params) =>
      Promise.resolve(params?.visit_id ? [verifiedOrder] : [verifiedOrder]),
    )
    renderPage()
    await screen.findByRole('option', { name: /Asha/ })
    fireEvent.change(screen.getByLabelText('Select Patient/Visit'), { target: { value: 'visit-1' } })
    fireEvent.change(screen.getByLabelText('From Date'), { target: { value: '2026-09-02' } })
    await waitFor(() => expect(screen.getByText('No lab results found for this visit.')).toBeInTheDocument())
  })
})