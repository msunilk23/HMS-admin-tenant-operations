import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PatientReturnsPage from './PatientReturnsPage'
import { patientReturnService } from '@/services/returnsService'

vi.mock('@/services/returnsService', () => ({
  patientReturnService: { eligibleDispenses: vi.fn(), eligibility: vi.fn(), list: vi.fn(), create: vi.fn() },
}))
const service = vi.mocked(patientReturnService)
const renderPage = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><PatientReturnsPage /></QueryClientProvider>)
const eligible = { dispense_id: 'dispense-1', patient_id: 'patient-1', patient_name: 'P30 Patient', patient_uhid: 'P30-001', visit_id: 'visit-1', prescription_id: 'rx-1', invoice_id: 'invoice-1', dispense_reference: 'DSP-P30-1' }
const allocation = (id: string, batch: string, remaining: string) => ({ allocation_id: `allocation-${id}`, inventory_batch_id: id, batch_number: batch, expiry_date: '2027-06-30T00:00:00Z', originally_dispensed_quantity: '5', previously_returned_quantity: '1', remaining_returnable_quantity: remaining })
const response = (allocations = [allocation('batch-1', 'P30-SINGLE', '4')]) => ({ ...eligible, facility_id: 'facility-1', pharmacy_location_id: 'location-1', items: [{ dispense_item_id: 'item-1', medicine_name: 'P30 Medicine', prescribed_quantity: '5', originally_dispensed_quantity: '5', previously_returned_quantity: '1', remaining_returnable_quantity: allocations.reduce((total, item) => total + Number(item.remaining_returnable_quantity), 0).toString(), allocations }] })
const created = { id: 'return-1', tenant_id: 'tenant-1', facility_id: 'facility-1', pharmacy_location_id: 'location-1', patient_id: 'patient-1', visit_id: 'visit-1', dispense_id: 'dispense-1', status: 'REQUESTED', reference_key: 'PR-P30-001', return_reason: 'Sealed patient return', total_return_quantity: '1', total_return_amount: '0', refunded_amount: '0', restockable_count: 0, non_restockable_count: 0, requested_at: '2026-08-30T00:00:00Z', created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z', items: [] }

beforeEach(() => { vi.clearAllMocks(); service.eligibleDispenses.mockResolvedValue([eligible]); service.eligibility.mockResolvedValue(response()); service.list.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0, total_pages: 0 }); service.create.mockResolvedValue(created) })
afterEach(cleanup)
async function select() { renderPage(); await screen.findByRole('option', { name: /P30 Patient/ }); fireEvent.change((await screen.findAllByRole('combobox'))[0], { target: { value: 'dispense-1' } }); await screen.findByText('P30 Medicine') }

describe('PatientReturnsPage P30', () => {
  it('renders loading, empty eligibility, and eligibility failure states', async () => {
    service.eligibleDispenses.mockImplementation(() => new Promise(() => {})); renderPage(); expect(screen.getByText('Loading eligible dispenses...')).toBeInTheDocument(); cleanup()
    service.eligibleDispenses.mockResolvedValue([]); renderPage(); await waitFor(() => expect(screen.getByRole('option', { name: 'Select a dispense' })).toBeInTheDocument()); cleanup()
    service.eligibleDispenses.mockRejectedValue(new Error('Eligibility unavailable')); renderPage(); expect(await screen.findByRole('alert')).toHaveTextContent('Eligibility unavailable')
  })
  it('renders patient references and original single-batch quantities', async () => {
    await select(); expect(screen.getByText('P30 Patient')).toBeInTheDocument(); expect(screen.getByText(/Prescription: rx-1/)).toBeInTheDocument(); expect(screen.getByText(/Batch P30-SINGLE/)).toBeInTheDocument(); expect(screen.getByText(/Originally dispensed 5; previously returned 1; remaining 4/)).toBeInTheDocument()
  })
  it('renders each multi-batch allocation and submits their exact total payload', async () => {
    service.eligibility.mockResolvedValue(response([allocation('batch-1', 'P30-A', '3'), allocation('batch-2', 'P30-B', '2')])); await select()
    fireEvent.change(screen.getByLabelText('Return quantity for P30-A'), { target: { value: '2' } }); fireEvent.change(screen.getByLabelText('Return quantity for P30-B'), { target: { value: '1' } }); fireEvent.change(screen.getByLabelText('Return reason'), { target: { value: 'Sealed patient return' } }); fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'P30 note' } }); fireEvent.click(screen.getByRole('button', { name: 'Submit return' }))
    await waitFor(() => expect(service.create).toHaveBeenCalledOnce()); expect(service.create).toHaveBeenCalledWith(expect.objectContaining({ dispense_id: 'dispense-1', return_reason: 'Sealed patient return', notes: 'P30 note', items: [{ dispense_item_id: 'item-1', returned_quantity: 3, restockable: true, batch_allocations: [{ inventory_batch_id: 'batch-1', returned_quantity: 2 }, { inventory_batch_id: 'batch-2', returned_quantity: 1 }] }] }))
  })
  it('blocks zero, negative, and excess allocation quantities without a request', async () => {
    await select(); fireEvent.change(screen.getByLabelText('Return reason'), { target: { value: 'Sealed patient return' } }); fireEvent.click(screen.getByRole('button', { name: 'Submit return' })); expect(await screen.findByRole('alert')).toHaveTextContent('positive quantity'); fireEvent.change(screen.getByLabelText('Return quantity for P30-SINGLE'), { target: { value: '-1' } }); fireEvent.click(screen.getByRole('button', { name: 'Submit return' })); expect(await screen.findByRole('alert')).toHaveTextContent('positive quantity'); fireEvent.change(screen.getByLabelText('Return quantity for P30-SINGLE'), { target: { value: '5' } }); fireEvent.click(screen.getByRole('button', { name: 'Submit return' })); expect(await screen.findByRole('alert')).toHaveTextContent('exceeds'); expect(service.create).not.toHaveBeenCalled()
  })
  it('keeps the idempotency key across a retriable backend field error and displays it', async () => {
    service.create.mockRejectedValueOnce({ response: { data: { detail: 'items.0.batch_allocations: invalid allocation' } } }).mockResolvedValueOnce(created); await select(); fireEvent.change(screen.getByLabelText('Return quantity for P30-SINGLE'), { target: { value: '1' } }); fireEvent.change(screen.getByLabelText('Return reason'), { target: { value: 'Sealed patient return' } }); fireEvent.click(screen.getByRole('button', { name: 'Submit return' })); expect(await screen.findByRole('alert')).toHaveTextContent('invalid allocation'); fireEvent.click(screen.getByRole('button', { name: 'Submit return' })); await waitFor(() => expect(service.create).toHaveBeenCalledTimes(2)); const first = service.create.mock.calls[0][0].idempotency_key; expect(first).toBeTruthy(); expect(service.create.mock.calls[1][0].idempotency_key).toBe(first); expect(await screen.findByRole('status')).toHaveTextContent('PR-P30-001')
  })
  it('prevents duplicate clicks while pending and refreshes after success', async () => {
    let resolveCreate: ((value: typeof created) => void) | undefined; service.create.mockImplementation(() => new Promise((resolve) => { resolveCreate = resolve })); await select(); fireEvent.change(screen.getByLabelText('Return quantity for P30-SINGLE'), { target: { value: '1' } }); fireEvent.change(screen.getByLabelText('Return reason'), { target: { value: 'Sealed patient return' } }); await waitFor(() => { expect(screen.getByLabelText('Return quantity for P30-SINGLE')).toHaveValue(1); expect(screen.getByLabelText('Return reason')).toHaveValue('Sealed patient return') }); fireEvent.click(screen.getByRole('button', { name: 'Submit return' })); await waitFor(() => expect(service.create).toHaveBeenCalledOnce()); fireEvent.click(screen.getByRole('button', { name: 'Submitting...' })); expect(service.create).toHaveBeenCalledOnce(); resolveCreate?.(created); expect(await screen.findByRole('status')).toHaveTextContent('created'); await waitFor(() => expect(service.eligibleDispenses.mock.calls.length).toBeGreaterThan(1))
  })
})
