import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LabPage from './LabPage'
import { labService } from '@/services/labService'

vi.mock('@/hooks/useWebSocket', () => ({ useWebSocket: vi.fn() }))
vi.mock('@/services/labService', () => ({
  labService: {
    listOrders: vi.fn(), updateStatus: vi.fn(), rejectOrder: vi.fn(), enterResults: vi.fn(),
    verifyResults: vi.fn(), uploadReport: vi.fn(), getReportUrl: vi.fn(),
  },
}))

const mockedLabService = vi.mocked(labService)
const processingOrder = {
  id: 'order-1', visit_id: 'visit-1', patient_name: 'Asha Patient', doctor_name: 'Doctor One',
  status: 'processing' as const, ordered_at: '2026-09-01T08:00:00Z',
  tests: [{ test_code: 'CBC', test_name: 'Complete Blood Count' }],
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <LabPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedLabService.listOrders.mockResolvedValue([processingOrder])
  mockedLabService.updateStatus.mockResolvedValue(processingOrder)
  mockedLabService.enterResults.mockResolvedValue({
    id: 'result-1', lab_order_id: 'order-1', results: { CBC: 'normal' }, reported_at: '2026-09-01T09:00:00Z',
  })
  mockedLabService.verifyResults.mockResolvedValue({ ...processingOrder, status: 'verified' })
})
afterEach(cleanup)

describe('LabPage', () => {
  it('renders the empty worklist state', async () => {
    mockedLabService.listOrders.mockResolvedValue([])
    renderPage()
    expect(await screen.findByText('No pending lab orders')).toBeInTheDocument()
  })

  it('opens result entry and submits values through the dedicated result endpoint', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Enter Results' }))
    expect(await screen.findByRole('heading', { name: 'Enter Lab Results' })).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Enter value…'), { target: { value: '15.2' } })
    fireEvent.change(screen.getByPlaceholderText(/Observations/), { target: { value: 'Repeat confirmed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Results' }))

    await waitFor(() => expect(mockedLabService.enterResults).toHaveBeenCalledWith('order-1', {
      results: { CBC: '15.2' }, notes: 'Repeat confirmed',
    }))
    expect(mockedLabService.updateStatus).not.toHaveBeenCalled()
  })

  it('uses lifecycle and verification endpoints for their respective states', async () => {
    mockedLabService.listOrders.mockResolvedValueOnce([
      { ...processingOrder, id: 'ordered-1', status: 'ordered' },
      { ...processingOrder, id: 'ready-1', status: 'result_ready' },
    ])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Await Sample' }))
    fireEvent.click(screen.getByRole('button', { name: 'Verify Results' }))

    await waitFor(() => expect(mockedLabService.updateStatus).toHaveBeenCalledWith('ordered-1', 'sample_pending'))
    await waitFor(() => expect(mockedLabService.verifyResults).toHaveBeenCalledWith('ready-1'))
  })
})