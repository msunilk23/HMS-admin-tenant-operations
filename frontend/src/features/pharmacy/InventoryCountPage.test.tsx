import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InventoryCountPage from './InventoryCountPage'
import { p33Service, type StockCount } from '@/services/p33Service'

const auth = vi.hoisted(() => ({ user: { id: 'counter-1', role: 'pharmacist' } as { id: string; role: string } }))
vi.mock('@/features/auth/authStore', () => ({ useAuthStore: (selector: (state: { user: typeof auth.user }) => unknown) => selector({ user: auth.user }) }))
vi.mock('@/services/p33Service', () => ({ p33Service: { locations: vi.fn(), batches: vi.fn(), counts: vi.fn(), count: vi.fn(), create: vi.fn(), start: vi.fn(), record: vi.fn(), addUnexpected: vi.fn(), submit: vi.fn(), requestRecount: vi.fn(), startRecount: vi.fn(), recordRecount: vi.fn(), resubmit: vi.fn(), approve: vi.fn(), apply: vi.fn(), cancel: vi.fn() } }))
const service = vi.mocked(p33Service)
const base: StockCount = { id: 'count-1', pharmacy_location_id: 'location-1', status: 'IN_PROGRESS', count_type: 'PARTIAL', reference_key: 'SC-001', selected_batch_ids: ['batch-1'], quantity_tolerance_percent: '0.500', expected_total_quantity: '11.000', physical_total_quantity: '0.000', variance_quantity: '0.000', total_items_counted: 0, total_variance_items: 0, recount_count: 0, initiated_by: 'counter-1', created_at: '2026-09-01T00:00:00Z', details: [{ id: 'detail-1', count_id: 'count-1', inventory_batch_id: 'batch-1', medicine_id: 'medicine-1', batch_number: 'P33-B1', system_quantity: '11.000', available_quantity: '10.000', reserved_quantity: '1.000', unit_cost: '20.00', classifications: [], is_unexpected: false, version: 1 }], recounts: [], history: [{ action: 'START', resource_type: 'stock_count', resource_id: 'count-1', timestamp: '2026-09-01T00:01:00Z' }] }
const renderPage = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><InventoryCountPage /></QueryClientProvider>)

beforeEach(() => {
  Object.values(service).forEach(mock => mock.mockReset())
  auth.user = { id: 'counter-1', role: 'pharmacist' }
  service.locations.mockResolvedValue([{ id: 'location-1', location_name: 'Central Pharmacy', location_code: 'CENTRAL', active: true }])
  service.batches.mockResolvedValue([{ id: 'batch-1', pharmacy_location_id: 'location-1', medicine_id: 'medicine-1', batch_number: 'P33-B1', available_quantity: '10', reserved_quantity: '1', status: 'ACTIVE' }])
  service.counts.mockResolvedValue({ items: [base], total: 1, page: 1, page_size: 25 })
  service.count.mockResolvedValue(base)
  service.create.mockResolvedValue({ ...base, status: 'CREATED' })
  service.record.mockResolvedValue({ ...base.details![0], physical_quantity: '10', variance_quantity: '-1', classifications: ['OUTSIDE_TOLERANCE'], version: 2 })
  service.approve.mockResolvedValue({ ...base, status: 'APPROVED' })
  service.apply.mockResolvedValue({ ...base, status: 'APPLIED' })
})
afterEach(cleanup)

describe('P33 inventory count workflow', () => {
  it('requires explicit partial scope and creates the selected count', async () => {
    renderPage()
    await screen.findByRole('option', { name: 'Central Pharmacy' })
    await userEvent.setup().selectOptions(screen.getByLabelText('Pharmacy location'), 'location-1')
    await userEvent.setup().click(screen.getByRole('button', { name: 'PARTIAL' }))
    const create = screen.getByRole('button', { name: 'Create count' })
    expect(create).toBeDisabled()
    await userEvent.setup().click(await screen.findByLabelText(/P33-B1/))
    await userEvent.setup().click(create)
    await waitFor(() => expect(service.create).toHaveBeenCalledWith(expect.objectContaining({ count_type: 'PARTIAL', selected_batch_ids: ['batch-1'] }), expect.any(String)))
  })

  it('records physical quantity with the optimistic version and suppresses duplicate clicks', async () => {
    let resolve!: (value: typeof base.details extends (infer T)[] | undefined ? T : never) => void
    service.record.mockImplementation(() => new Promise(done => { resolve = done }))
    renderPage(); await userEvent.setup().click(await screen.findByText('SC-001'))
    const quantity = await screen.findByLabelText('Physical quantity P33-B1')
    fireEvent.change(quantity, { target: { value: '10' } })
    const save = screen.getByRole('button', { name: 'Save' })
    fireEvent.click(save); fireEvent.click(save)
    await waitFor(() => expect(service.record).toHaveBeenCalledOnce())
    expect(service.record).toHaveBeenCalledWith('count-1', 'detail-1', expect.objectContaining({ physical_quantity: 10, version: 1 }), expect.any(String))
    resolve({ ...base.details![0], physical_quantity: '10', version: 2 })
  })

  it('requires a separate manager confirmation before applying adjustments', async () => {
    auth.user = { id: 'manager-1', role: 'store_manager' }
    service.counts.mockResolvedValue({ items: [{ ...base, status: 'APPROVED' }], total: 1, page: 1, page_size: 25 })
    service.count.mockResolvedValue({ ...base, status: 'APPROVED' })
    renderPage(); await userEvent.setup().click(await screen.findByText('SC-001'))
    expect(await screen.findByRole('button', { name: 'Review adjustment application' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply adjustments' })).toBeNull()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Review adjustment application' }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Apply adjustments' }))
    await waitFor(() => expect(service.apply).toHaveBeenCalledWith('count-1', '', expect.any(String)))
  })

  it('records unexpected zero-system stock with mandatory evidence', async () => {
    service.batches.mockResolvedValue([{ id: 'batch-zero', pharmacy_location_id: 'location-1', medicine_id: 'medicine-1', batch_number: 'P33-ZERO', available_quantity: '0', reserved_quantity: '0', status: 'INACTIVE' }])
    service.addUnexpected.mockResolvedValue({ ...base.details![0], id: 'detail-zero', inventory_batch_id: 'batch-zero', batch_number: 'P33-ZERO', system_quantity: '0', physical_quantity: '2', variance_quantity: '2', evidence: 'Sealed pack found', is_unexpected: true })
    renderPage(); await userEvent.setup().click(await screen.findByText('SC-001'))
    await userEvent.setup().selectOptions(await screen.findByLabelText('Unexpected stock batch'), 'batch-zero')
    await userEvent.setup().type(screen.getByLabelText('Unexpected physical quantity'), '2')
    const add = screen.getByRole('button', { name: 'Add unexpected stock' })
    expect(add).toBeDisabled()
    await userEvent.setup().type(screen.getByLabelText('Unexpected stock evidence'), 'Sealed pack found')
    await userEvent.setup().click(add)
    await waitFor(() => expect(service.addUnexpected).toHaveBeenCalledWith('count-1', { inventory_batch_id: 'batch-zero', physical_quantity: 2, evidence: 'Sealed pack found' }, expect.any(String)))
  })

  it('hides post-submission cancellation from pharmacists', async () => {
    service.counts.mockResolvedValue({ items: [{ ...base, status: 'SUBMITTED' }], total: 1, page: 1, page_size: 25 })
    service.count.mockResolvedValue({ ...base, status: 'SUBMITTED' })
    renderPage(); await userEvent.setup().click(await screen.findByText('SC-001'))
    expect(await screen.findByText('SUBMITTED', { selector: 'span' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel count' })).toBeNull()
  })

  it('blocks manager approval when the manager recorded a detail', async () => {
    auth.user = { id: 'manager-1', role: 'store_manager' }
    const submitted = { ...base, status: 'SUBMITTED' as const, initiated_by: 'counter-1', completed_by: 'counter-1', details: [{ ...base.details![0], counted_by: 'manager-1' }] }
    service.counts.mockResolvedValue({ items: [submitted], total: 1, page: 1, page_size: 25 })
    service.count.mockResolvedValue(submitted)
    renderPage(); await userEvent.setup().click(await screen.findByText('SC-001'))
    expect(await screen.findByRole('button', { name: 'Approve count' })).toBeDisabled()
  })

  it('keeps tenant admin view-only while showing count history', async () => {
    auth.user = { id: 'admin-1', role: 'hospital_admin' }
    renderPage(); await userEvent.setup().click(await screen.findByText('SC-001'))
    expect(await screen.findByText('START')).toBeInTheDocument()
    expect(screen.queryByText('Create count')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
    expect(screen.queryByText('Manager review')).toBeNull()
  })
})