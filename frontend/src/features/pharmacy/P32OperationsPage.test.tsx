import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import P32OperationsPage from './P32OperationsPage'
import { p32Service, type Recall, type Transfer } from '@/services/p32Service'

const auth = vi.hoisted(() => ({ user: { id: 'maker-1', role: 'pharmacist' } as { id: string; role: string } }))
vi.mock('@/features/auth/authStore', () => ({ useAuthStore: (selector: (state: { user: typeof auth.user }) => unknown) => selector({ user: auth.user }) }))
vi.mock('@/services/p32Service', () => ({ p32Service: { locations: vi.fn(), recalls: vi.fn(), affectedPatients: vi.fn(), createRecall: vi.fn(), approveRecall: vi.fn(), resolveRecall: vi.fn(), eligibleBatches: vi.fn(), transfers: vi.fn(), transfer: vi.fn(), createTransfer: vi.fn(), approveTransfer: vi.fn(), dispatchTransfer: vi.fn(), receiveTransfer: vi.fn(), reconcile: vi.fn() } }))
const service = vi.mocked(p32Service)
const recall: Recall = { id: 'recall-1', medicine_id: 'medicine-1', batch_number: 'B-1', status: 'DRAFT', reference_key: 'RC-1', recall_reason: 'Confirmed quality failure', notification_status: 'NOT_STARTED', initiated_by: 'maker-1', created_at: '2026-08-31T00:00:00Z' }
const transfer: Transfer = { id: 'transfer-1', from_location_id: 'source', to_location_id: 'destination', status: 'DRAFT', reference_key: 'TR-1', total_quantity: '5', requested_by: 'maker-1', created_at: '2026-08-31T00:00:00Z' }
const renderPage = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><P32OperationsPage /></QueryClientProvider>)

beforeEach(() => {
  Object.values(service).forEach((mock) => mock.mockReset())
  auth.user = { id: 'maker-1', role: 'pharmacist' }
  service.recalls.mockResolvedValue([]); service.affectedPatients.mockResolvedValue([]); service.locations.mockResolvedValue([{ id: 'source', location_name: 'Central', location_code: 'C', active: true }, { id: 'destination', location_name: 'OPD', location_code: 'O', active: true }]); service.eligibleBatches.mockResolvedValue([{ id: 'batch-1', pharmacy_location_id: 'source', medicine_id: 'medicine-1', batch_number: 'B-1', available_quantity: '5', reserved_quantity: '1', status: 'ACTIVE' }]); service.transfers.mockResolvedValue([]); service.createRecall.mockResolvedValue(recall); service.createTransfer.mockResolvedValue(transfer)
})
afterEach(cleanup)

describe('P32 recall and transfer operations', () => {
  it('renders affected patients and enforces recall maker-checker controls', async () => {
    auth.user = { id: 'manager-1', role: 'hospital_admin' }
    service.recalls.mockResolvedValue([recall]); service.affectedPatients.mockResolvedValue([{ dispense_id: 'dispense-1', patient_id: 'patient-1', uhid: 'UH-32', patient_name: 'Asha Rao', phone: '9000000000', dispensed_quantity: '2', notification_status: 'NOT_STARTED' }])
    renderPage(); await userEvent.setup().click(await screen.findByText('RC-1'))
    expect(await screen.findByText('Asha Rao')).toBeInTheDocument(); expect(screen.getByText('UH-32')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Approve recall' })).toBeInTheDocument()
    cleanup(); auth.user = { id: 'maker-1', role: 'hospital_admin' }; service.recalls.mockResolvedValue([recall]); renderPage(); await userEvent.setup().click(await screen.findByText('RC-1'))
    expect(await screen.findByText(/different authorized manager/)).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Approve recall' })).toBeNull()
  })

  it('validates locations and available transfer quantity without calling backend', async () => {
    renderPage(); await userEvent.setup().click(screen.getByRole('tab', { name: 'Stock transfers' })); await screen.findByLabelText('Source location')
    await userEvent.setup().selectOptions(screen.getByLabelText('Source location'), 'source'); await userEvent.setup().selectOptions(screen.getByLabelText('Destination location'), 'destination'); await screen.findByText(/B-1/); await userEvent.setup().selectOptions(screen.getByLabelText('Eligible batch'), 'batch-1'); fireEvent.change(screen.getByLabelText('Transfer quantity'), { target: { value: '5' } }); fireEvent.click(screen.getByRole('button', { name: 'Create draft' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('exceeds available'); expect(service.createTransfer).not.toHaveBeenCalled()
  })

  it('captures partial receipt discrepancy and handles backend errors', async () => {
    auth.user = { id: 'receiver-1', role: 'pharmacist' }; const inTransit = { ...transfer, status: 'IN_TRANSIT' as const, items: [{ id: 'item-1', inventory_batch_id: 'batch-1', transfer_quantity: '5' }] }
    service.transfers.mockResolvedValue([inTransit]); service.transfer.mockResolvedValue(inTransit); service.receiveTransfer.mockRejectedValue({ response: { data: { detail: 'Receipt conflict' } } })
    renderPage(); await userEvent.setup().click(screen.getByRole('tab', { name: 'Stock transfers' })); await userEvent.setup().click(await screen.findByText('TR-1')); await screen.findByLabelText('Quantity received'); fireEvent.change(screen.getByLabelText('Quantity received'), { target: { value: '3' } }); fireEvent.change(screen.getByLabelText('Discrepancy notes'), { target: { value: 'Two units missing' } }); fireEvent.click(screen.getByRole('button', { name: 'Receive stock' }))
    await waitFor(() => expect(service.receiveTransfer).toHaveBeenCalledWith('transfer-1', expect.objectContaining({ items: [expect.objectContaining({ quantity_received: 3, discrepancy_type: 'SHORTAGE', discrepancy_quantity: 2 })] }))); expect(await screen.findByRole('alert')).toHaveTextContent('Receipt conflict')
  })

  it('suppresses duplicate create clicks while pending and hides manager actions from pharmacist', async () => {
    let resolve!: (value: Recall) => void; service.createRecall.mockImplementation(() => new Promise((done) => { resolve = done })); service.recalls.mockResolvedValue([recall]); renderPage()
    fireEvent.change(screen.getByLabelText('Medicine ID'), { target: { value: 'medicine-1' } }); fireEvent.change(screen.getByLabelText('Batch number'), { target: { value: 'B-1' } }); fireEvent.change(screen.getByLabelText('Recall reason'), { target: { value: 'Confirmed quality failure' } }); const button = screen.getByRole('button', { name: 'Create recall' }); fireEvent.click(button); expect(await screen.findByRole('button', { name: 'Creating...' })).toBeDisabled(); fireEvent.click(screen.getByRole('button', { name: 'Creating...' })); expect(service.createRecall).toHaveBeenCalledOnce(); expect(screen.queryByRole('button', { name: 'Approve recall' })).toBeNull(); resolve(recall)
  })
})
