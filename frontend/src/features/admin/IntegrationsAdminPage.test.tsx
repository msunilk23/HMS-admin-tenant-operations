import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import IntegrationsAdminPage from './IntegrationsAdminPage'
import { integrationService } from '@/services/integrationService'

vi.mock('@/services/integrationService', () => ({ integrationService: { providers: vi.fn(), connections: vi.fn(), create: vi.fn(), test: vi.fn() } }))

const providers = [
  { provider_code: 'twilio', display_name: 'Twilio', capability: 'communication', supported_environments: ['TEST', 'LIVE'], public_fields: [{ field_code: 'account_sid', label: 'Account SID', required: true }], secret_fields: [{ field_code: 'api_key_secret', label: 'API Key Secret', required: true, write_only: true, configured: false }], supports_connection_test: true, supports_webhooks: true },
  { provider_code: 'razorpay', display_name: 'Razorpay', capability: 'payment', supported_environments: ['TEST', 'LIVE'], public_fields: [{ field_code: 'key_id', label: 'Key ID', required: true }], secret_fields: [{ field_code: 'key_secret', label: 'Key Secret', required: true, write_only: true, configured: false }], supports_connection_test: true, supports_webhooks: true },
]

afterEach(() => vi.clearAllMocks())

describe('IntegrationsAdminPage', () => {
  it('filters supported providers and renders only selected provider fields', async () => {
    vi.mocked(integrationService.providers).mockResolvedValue(providers as never)
    vi.mocked(integrationService.connections).mockResolvedValue([])
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><IntegrationsAdminPage /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Twilio' })).toBeInTheDocument())
    const provider = screen.getByLabelText('Provider')
    expect(screen.queryByRole('option', { name: 'Razorpay' })).not.toBeInTheDocument()
    fireEvent.change(provider, { target: { value: 'twilio' } })
    expect(screen.getByLabelText('Account SID')).toBeInTheDocument()
    expect(screen.getByLabelText('API Key Secret')).toHaveAttribute('type', 'password')
    fireEvent.change(screen.getByLabelText('Capability'), { target: { value: 'payment' } })
    await waitFor(() => expect(screen.getByRole('option', { name: 'Razorpay' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'razorpay' } })
    expect(screen.getByLabelText('Key ID')).toBeInTheDocument()
    expect(screen.queryByLabelText('Account SID')).not.toBeInTheDocument()
  })
})