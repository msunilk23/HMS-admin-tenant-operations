import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PermissionGuard from '@/components/shared/PermissionGuard'
import { P34_PERMISSIONS, pharmacyDashboardService } from '@/services/pharmacyDashboardService'
import PharmacyDashboardPage from './PharmacyDashboardPage'

vi.mock('@/services/pharmacyDashboardService', async importOriginal => {
  const original = await importOriginal<typeof import('@/services/pharmacyDashboardService')>()
  return { ...original, pharmacyDashboardService: { capabilities: vi.fn(), dashboard: vi.fn(), reportCatalogue: vi.fn(), report: vi.fn(), exportReport: vi.fn(), alerts: vi.fn(), acknowledge: vi.fn(), configuration: vi.fn(), updateConfiguration: vi.fn() } }
})
const service = vi.mocked(pharmacyDashboardService)
const dashboard = {
  metadata: { business_date: '2026-08-31', timezone: 'Asia/Kolkata', facility_id: 'facility-1', generated_at: '2026-08-31T12:00:00Z', currencies: ['INR'] },
  financial_data_visible: false,
  cards: {
    sales: { currency: 'INR', gross: '100', discount: '0', tax: '0', invoice_net: '100', refunds: '0', net_paid: '100' }, prescriptions_pending: 3,
    dispensed_today: { count: 2, quantity: '4' }, purchases_today: { count: 1, value: '50', currency: 'INR' }, patient_returns_today: { count: 0, refund_value: '0', currency: 'INR' }, supplier_returns_today: { count: 0, value: '0', currency: 'INR' }, stock_adjustments_today: { count: 1, quantity: '2', value: null }, low_stock_items: 2, out_of_stock_items: 1, expiring_stock: { '0_30': 1, '31_60': 2, '61_90': 3 }, inventory_valuation: { available: '260', reserved: '0', quarantined: '0', total_physical: '260', unvalued_quantity: '0', currency: 'INR' }, outside_purchases: { item_count: 0, quantity: '0' },
  },
}
const renderPage = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={['/pharmacy/dashboard']}><Routes><Route path="/dashboard" element={<h1>General dashboard</h1>} /><Route path="/pharmacy/dashboard" element={<PermissionGuard permission={P34_PERMISSIONS.dashboard}><PharmacyDashboardPage /></PermissionGuard>} /></Routes></MemoryRouter></QueryClientProvider>)

beforeEach(() => {
  vi.clearAllMocks()
  service.capabilities.mockResolvedValue({ permissions: [P34_PERMISSIONS.dashboard, P34_PERMISSIONS.reports, P34_PERMISSIONS.alerts] })
  service.dashboard.mockResolvedValue(dashboard)
  service.reportCatalogue.mockResolvedValue(['current-stock', 'dispensing', 'reorder'])
  service.report.mockResolvedValue({ report: 'current-stock', metadata: dashboard.metadata, filters: {}, items: [], total: 0, page: 1, page_size: 50 })
  service.alerts.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
})
afterEach(cleanup)

describe('PharmacyDashboardPage P34', () => {
  it('renders the dedicated operational dashboard without financial totals', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Pharmacy Dashboard' })).toBeInTheDocument()
    expect(await screen.findByText('Prescriptions pending')).toBeInTheDocument()
    expect(screen.getByText('Operational view. Financial totals and valuation require additional reporting access.')).toBeInTheDocument()
    expect(screen.queryByText("Today's Pharmacy sales")).not.toBeInTheDocument()
    expect(screen.queryByText('General dashboard')).not.toBeInTheDocument()
  })

  it('opens a card report in the separate Reports view', async () => {
    renderPage()
    fireEvent.click(await screen.findByText('Low-stock items'))
    const reportSelect = await screen.findByRole('combobox', { name: 'Pharmacy report' })
    await waitFor(() => expect(reportSelect).toHaveValue('reorder'))
    await waitFor(() => expect(service.report).toHaveBeenCalledWith('reorder', expect.objectContaining({ page: 1 })))
  })

  it('redirects denied users before requesting dashboard data', async () => {
    service.capabilities.mockResolvedValue({ permissions: [] })
    renderPage()
    expect(await screen.findByRole('heading', { name: 'General dashboard' })).toBeInTheDocument()
    expect(service.dashboard).not.toHaveBeenCalled()
  })
})
