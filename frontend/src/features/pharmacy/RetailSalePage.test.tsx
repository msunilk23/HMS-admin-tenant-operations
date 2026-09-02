import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RetailSalePage from './RetailSalePage'
import { pharmacyRetailService } from '@/services/pharmacyRetailService'

vi.mock('@/services/pharmacyRetailService', () => ({
  pharmacyRetailService: { locations: vi.fn(), search: vi.fn(), create: vi.fn(), get: vi.fn(), verify: vi.fn(), dispense: vi.fn() },
}))

const service = vi.mocked(pharmacyRetailService)
const renderPage = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RetailSalePage /></QueryClientProvider>)
const otc = { id: 'otc-1', code: 'OTC-1', name: 'Paracetamol', available_quantity: '10', unit_price: '12.00', gst_rate: '5', requires_prescription: false, is_controlled_drug: false }
const controlled = { id: 'controlled-1', code: 'CTRL-1', name: 'Controlled Medicine', available_quantity: '3', unit_price: '40.00', gst_rate: '5', requires_prescription: true, is_controlled_drug: true }
const draft = { id: 'sale-1', pharmacy_location_id: 'location-1', classification: 'OTC' as const, status: 'DRAFT', controlled_sale: false, customer_reference: 'WALKIN-1', subtotal: '12.00', tax: '0.60', discount: '0.00', total: '12.60', payment_status: 'PENDING' }

beforeEach(() => {
  vi.clearAllMocks()
  service.locations.mockResolvedValue([{ id: 'location-1', location_name: 'Main Pharmacy', location_code: 'MAIN' }])
  service.search.mockResolvedValue([otc, controlled])
  service.create.mockResolvedValue(draft)
  service.get.mockResolvedValue(draft)
  service.dispense.mockResolvedValue({ ...draft, status: 'FULLY_DISPENSED', payment_status: 'PAID', payment_method: 'CASH', receipt_number: 'RTL-001' })
})
afterEach(cleanup)

async function selectLocation() {
  renderPage()
  await screen.findByRole('option', { name: 'Main Pharmacy (MAIN)' })
  fireEvent.change(screen.getByLabelText('Retail pharmacy location'), { target: { value: 'location-1' } })
  await screen.findByText('Paracetamol')
}

describe('RetailSalePage Release A', () => {
  it('blocks prescription medicines in OTC mode and completes a cash sale with a receipt', async () => {
    await selectLocation()
    expect(screen.getByText('Use External prescription mode.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add Controlled Medicine' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Add Paracetamol' }))
    fireEvent.change(screen.getByLabelText('Paracetamol quantity'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review payment' }))
    await waitFor(() => expect(service.create).toHaveBeenCalledWith(expect.objectContaining({ classification: 'OTC', items: [{ medicine_product_id: 'otc-1', quantity: 2, prescribed_quantity: undefined, duration_days: undefined }] }), expect.any(String)))
    fireEvent.click(await screen.findByRole('button', { name: 'Capture payment and dispense' }))
    await waitFor(() => expect(service.dispense).toHaveBeenCalledWith('sale-1', 'CASH', ''))
    expect(await screen.findByRole('status')).toHaveTextContent('Receipt RTL-001')
    expect(screen.getByRole('status')).toHaveTextContent('OTC')
  })

  it('requires complete external prescription fields before creating a sale', async () => {
    await selectLocation()
    fireEvent.click(screen.getByRole('button', { name: 'External prescription' }))
    await waitFor(() => expect(screen.getByLabelText('Patient name')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Add Controlled Medicine' }))
    expect(screen.getByLabelText('Government ID type')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Submit for verification' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Complete every required')
    expect(service.create).not.toHaveBeenCalled()
  })

  it('verifies an external prescription before exposing payment capture', async () => {
    await selectLocation()
    fireEvent.click(screen.getByRole('button', { name: 'External prescription' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add Controlled Medicine' }))
    const values: Record<string, string> = {
      'Patient name': 'Release Patient', 'Patient age': '35', 'Patient gender': 'female', 'Patient mobile': '9000000001',
      'Patient address': '1 Test Street', 'Prescriber name': 'External Doctor', 'Registration number': 'REG-1',
      'Issuing facility / clinic': 'External Clinic', 'Prescription reference': 'RX-1', 'Government ID type': 'Passport',
      'Government ID last four': '1234', 'Registered patient ID': 'patient-1',
    }
    for (const [label, value] of Object.entries(values)) fireEvent.change(screen.getByLabelText(label), { target: { value } })
    service.create.mockResolvedValue({ ...draft, classification: 'EXTERNAL_PRESCRIPTION', status: 'PENDING_VERIFICATION', controlled_sale: true })
    service.verify.mockResolvedValue({ ...draft, classification: 'EXTERNAL_PRESCRIPTION', status: 'VERIFIED', controlled_sale: true })
    fireEvent.click(screen.getByRole('button', { name: 'Submit for verification' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Verify original prescription' }))
    await waitFor(() => expect(service.verify).toHaveBeenCalledWith('sale-1'))
    expect(await screen.findByRole('button', { name: 'Capture payment and dispense' })).toBeInTheDocument()
    expect(screen.getByText(/different authorized Pharmacist/)).toBeInTheDocument()
  })

  it('resumes a verified sale for an authorized pharmacist handoff', async () => {
    renderPage()
    service.get.mockResolvedValue({ ...draft, classification: 'EXTERNAL_PRESCRIPTION', status: 'VERIFIED', controlled_sale: true })
    fireEvent.change(screen.getByLabelText('Retail sale ID'), { target: { value: 'sale-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    await waitFor(() => expect(service.get).toHaveBeenCalledWith('sale-1'))
    expect(await screen.findByRole('button', { name: 'Capture payment and dispense' })).toBeInTheDocument()
    expect(screen.getByText(/different authorized Pharmacist/)).toBeInTheDocument()
  })
})