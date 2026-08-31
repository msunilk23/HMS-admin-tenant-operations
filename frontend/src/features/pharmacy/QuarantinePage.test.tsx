import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import QuarantinePage from './QuarantinePage'
import { quarantineService, type StockQuarantine } from '@/services/quarantineService'

const auth = vi.hoisted(() => ({ user: { id: 'pharmacist-1', role: 'pharmacist' } as { id: string; role: string } }))
vi.mock('@/features/auth/authStore', () => ({ useAuthStore: (selector: (state: { user: typeof auth.user }) => unknown) => selector({ user: auth.user }) }))
vi.mock('@/services/quarantineService', () => ({ quarantineService: { batches: vi.fn(), list: vi.fn(), create: vi.fn(), release: vi.fn(), dispose: vi.fn() } }))

const service = vi.mocked(quarantineService)
const batch = { id: 'batch-1', pharmacy_location_id: 'location-1', medicine_id: 'medicine-1', batch_number: 'P31-BATCH', expiry_date: '2027-12-31', available_quantity: '5', status: 'ACTIVE' }
const record = (reason: StockQuarantine['reason'] = 'INVESTIGATION', overrides: Partial<StockQuarantine> = {}): StockQuarantine => ({
  id: 'quarantine-1', tenant_id: 'tenant-1', facility_id: 'facility-1', pharmacy_location_id: 'location-1', inventory_batch_id: 'batch-1', status: 'QUARANTINED', reference_key: 'QT-P31-001', reason, total_quantity_quarantined: '2', remaining_quantity: '2', notes: 'Inspection required', quarantined_by: 'pharmacist-1', quarantined_at: '2026-08-30T10:00:00Z', created_at: '2026-08-30T10:00:00Z', updated_at: '2026-08-30T10:00:00Z', ...overrides,
})
const renderPage = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><QuarantinePage /></QueryClientProvider>)

beforeEach(() => {
  service.batches.mockReset()
  service.list.mockReset()
  service.create.mockReset()
  service.release.mockReset()
  service.dispose.mockReset()
  auth.user = { id: 'pharmacist-1', role: 'pharmacist' }
  service.batches.mockResolvedValue([batch])
  service.list.mockResolvedValue({ items: [], total: 0 })
  service.create.mockResolvedValue(record())
  service.release.mockResolvedValue(record('INVESTIGATION', { status: 'RELEASED', remaining_quantity: '0' }))
  service.dispose.mockResolvedValue(record('DAMAGED', { status: 'DISPOSED', remaining_quantity: '0' }))
})
afterEach(cleanup)

async function chooseBatch() {
  renderPage()
  await screen.findByRole('option', { name: /P31-BATCH/ })
  await userEvent.setup().selectOptions(screen.getByLabelText('Batch and location'), 'batch-1')
}

describe('QuarantinePage P31', () => {
  it('renders eligible batch location and saleable quantity and validates quantity', async () => {
    await chooseBatch()
    expect(screen.getByText('Saleable quantity: 5')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /location-1/ })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Quarantine quantity'), { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Quarantine stock' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('exceeds available')
    expect(service.create).not.toHaveBeenCalled()
  })

  it('submits the quarantine payload and refreshes batch and register queries', async () => {
    await chooseBatch()
    fireEvent.change(screen.getByLabelText('Quarantine quantity'), { target: { value: '2' } })
    await userEvent.setup().selectOptions(screen.getByLabelText('Quarantine reason'), 'DAMAGED')
    fireEvent.change(screen.getByLabelText('Quarantine notes'), { target: { value: 'Packaging visibly compromised' } })
    fireEvent.click(screen.getByRole('button', { name: 'Quarantine stock' }))
    await waitFor(() => expect(service.create).toHaveBeenCalledOnce())
    expect(service.create).toHaveBeenCalledWith({ inventory_batch_id: 'batch-1', quantity: 2, reason: 'DAMAGED', notes: 'Packaging visibly compromised', idempotency_key: expect.any(String) })
    await waitFor(() => expect(service.batches.mock.calls.length).toBeGreaterThan(1))
    expect(service.list.mock.calls.length).toBeGreaterThan(1)
  })

  it('reuses one idempotency key on retry and suppresses duplicate clicks while pending', async () => {
    service.create.mockRejectedValueOnce({ response: { data: { detail: 'Temporary validation failure' } } }).mockResolvedValueOnce(record())
    await chooseBatch()
    fireEvent.change(screen.getByLabelText('Quarantine quantity'), { target: { value: '1' } })
    const button = screen.getByRole('button', { name: 'Quarantine stock' })
    fireEvent.click(button)
    await screen.findByText('Temporary validation failure')
    fireEvent.click(button)
    await waitFor(() => expect(service.create).toHaveBeenCalledTimes(2))
    expect(service.create.mock.calls[0][0].idempotency_key).toBe(service.create.mock.calls[1][0].idempotency_key)
    let resolveCreate: ((value: StockQuarantine) => void) | undefined
    service.create.mockImplementationOnce(() => new Promise((resolve) => { resolveCreate = resolve }))
    await userEvent.setup().selectOptions(screen.getByLabelText('Batch and location'), 'batch-1')
    fireEvent.change(screen.getByLabelText('Quarantine quantity'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Quarantine stock' }))
    expect(await screen.findByRole('button', { name: 'Quarantining...' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Quarantining...' }))
    expect(service.create).toHaveBeenCalledTimes(3)
    resolveCreate?.(record())
  })

  it('shows release only for investigative stock and only to a different approver', async () => {
    auth.user = { id: 'admin-1', role: 'hospital_admin' }
    service.list.mockResolvedValue({ items: [record('INVESTIGATION')], total: 1 })
    renderPage()
    expect(await screen.findByRole('button', { name: 'Release stock' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dispose stock' })).toBeInTheDocument()
    cleanup()
    service.list.mockResolvedValue({ items: [record('EXPIRED')], total: 1 })
    renderPage()
    await screen.findAllByText('QT-P31-001')
    expect(screen.queryByRole('button', { name: 'Release stock' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Dispose stock' })).toBeInTheDocument()
    cleanup()
    service.list.mockResolvedValue({ items: [record('DAMAGED')], total: 1 })
    renderPage()
    await screen.findAllByText('QT-P31-001')
    expect(screen.queryByRole('button', { name: 'Release stock' })).toBeNull()
  })

  it('captures disposal evidence and displays backend validation errors', async () => {
    auth.user = { id: 'admin-1', role: 'hospital_admin' }
    service.list.mockResolvedValue({ items: [record('DAMAGED')], total: 1 })
    service.dispose.mockRejectedValue({ response: { data: { detail: 'Witness cannot approve this disposal' } } })
    renderPage()
    await screen.findByLabelText('Disposal reason')
    fireEvent.change(screen.getByLabelText('Disposal reason'), { target: { value: 'Confirmed damaged and unsafe stock' } })
    fireEvent.change(screen.getByLabelText('Disposal method'), { target: { value: 'Licensed waste vendor' } })
    fireEvent.change(screen.getByLabelText('Witness user ID'), { target: { value: 'witness-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Dispose stock' }))
    await waitFor(() => expect(service.dispose).toHaveBeenCalledWith('quarantine-1', expect.objectContaining({ disposal_reason: 'Confirmed damaged and unsafe stock', disposal_method: 'Licensed waste vendor', witnessed_by: 'witness-1', disposal_date: expect.any(String) })))
    expect(await screen.findByRole('alert')).toHaveTextContent('Witness cannot approve')
  })

  it('hides approval for pharmacists, unauthorized roles, terminal records, and self-approval', async () => {
    service.list.mockResolvedValue({ items: [record()], total: 1 })
    renderPage()
    await screen.findAllByText('QT-P31-001')
    expect(screen.queryByRole('button', { name: 'Release stock' })).toBeNull()
    cleanup()
    auth.user = { id: 'admin-1', role: 'hospital_admin' }
    service.list.mockResolvedValue({ items: [record('INVESTIGATION', { quarantined_by: 'admin-1' })], total: 1 })
    renderPage()
    expect(await screen.findByText(/different manager or administrator/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dispose stock' })).toBeNull()
    cleanup()
    auth.user = { id: 'nurse-1', role: 'nurse' }
    service.list.mockResolvedValue({ items: [record('DAMAGED', { status: 'DISPOSED', remaining_quantity: '0' })], total: 1 })
    renderPage()
    await screen.findAllByText('QT-P31-001')
    expect(screen.queryByText('Create quarantine')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Dispose stock' })).toBeNull()
  })
})