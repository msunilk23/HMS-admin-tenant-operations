import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import IntegrationsAdminPage from './IntegrationsAdminPage'
import { integrationService } from '@/services/integrationService'

vi.mock('@/services/integrationService', () => ({ integrationService: {
  providers: vi.fn(), connections: vi.fn(), communicationRoutes: vi.fn(),
  setCommunicationRoute: vi.fn(), clearCommunicationRoute: vi.fn(),
  create: vi.fn(), test: vi.fn(),
} }))

const providers = [
  { provider_code: 'twilio', display_name: 'Twilio', capability: 'communication', supported_channels: ['SMS', 'WHATSAPP'], supported_environments: ['TEST', 'LIVE'], public_fields: [{ field_code: 'account_sid', label: 'Account SID', required: true }], secret_fields: [{ field_code: 'api_key_secret', label: 'API Key Secret', required: true, write_only: true, configured: false }], supports_connection_test: true, supports_webhooks: true },
  { provider_code: 'msg91', display_name: 'MSG91', capability: 'communication', supported_channels: ['SMS'], supported_environments: ['TEST', 'LIVE'], public_fields: [{ field_code: 'otp_template_id', label: 'OTP Template ID', required: true }, { field_code: 'sms_template_id', label: 'SMS Flow Template ID', required: true }], secret_fields: [{ field_code: 'auth_key', label: 'Auth Key', required: true, write_only: true, configured: false }], supports_connection_test: false, supports_webhooks: false },
  { provider_code: 'razorpay', display_name: 'Razorpay', capability: 'payment', supported_channels: [], supported_environments: ['TEST', 'LIVE'], public_fields: [{ field_code: 'key_id', label: 'Key ID', required: true }], secret_fields: [{ field_code: 'key_secret', label: 'Key Secret', required: true, write_only: true, configured: false }], supports_connection_test: true, supports_webhooks: true },
]

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('IntegrationsAdminPage', () => {
  it('filters supported providers and renders only selected provider fields', async () => {
    vi.mocked(integrationService.providers).mockResolvedValue(providers as never)
    vi.mocked(integrationService.connections).mockResolvedValue([])
    vi.mocked(integrationService.communicationRoutes).mockResolvedValue({ SMS: null, WHATSAPP: null })
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><IntegrationsAdminPage /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Twilio' })).toBeInTheDocument())
    const provider = screen.getByLabelText('Provider')
    expect(screen.queryByRole('option', { name: 'Razorpay' })).not.toBeInTheDocument()
    fireEvent.change(provider, { target: { value: 'twilio' } })
    expect(screen.getByLabelText('Account SID')).toBeInTheDocument()
    expect(screen.getByLabelText('API Key Secret')).toHaveAttribute('type', 'password')
    fireEvent.change(provider, { target: { value: 'msg91' } })
    expect(screen.getByLabelText('Auth Key')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText('OTP Template ID')).toHaveAttribute('type', 'text')
    fireEvent.change(screen.getByLabelText('Capability'), { target: { value: 'payment' } })
    await waitFor(() => expect(screen.getByRole('option', { name: 'Razorpay' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'razorpay' } })
    expect(screen.getByLabelText('Key ID')).toBeInTheDocument()
    expect(screen.queryByLabelText('Account SID')).not.toBeInTheDocument()
  })

  it('allows independent SMS and WhatsApp routing and keeps MSG91 auth write-only', async () => {
    vi.mocked(integrationService.providers).mockResolvedValue(providers as never)
    vi.mocked(integrationService.connections).mockResolvedValue([
      { id: 'msg91-test', provider: 'msg91', capability: 'communication', environment: 'TEST', status: 'TEST', connection_name: 'MSG91 SMS', public_configuration: {}, credential_version: 1 },
      { id: 'twilio-live', provider: 'twilio', capability: 'communication', environment: 'LIVE', status: 'LIVE', connection_name: 'Twilio WA', public_configuration: {}, credential_version: 1 },
    ])
    vi.mocked(integrationService.communicationRoutes).mockResolvedValue({ SMS: null, WHATSAPP: null })
    vi.mocked(integrationService.setCommunicationRoute).mockResolvedValue({} as never)

    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><IntegrationsAdminPage /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('option', { name: 'MSG91 SMS · TEST' })).toBeInTheDocument())

    fireEvent.change(screen.getByRole('combobox', { name: 'SMS provider' }), { target: { value: 'msg91|TEST' } })
    await waitFor(() => expect(integrationService.setCommunicationRoute).toHaveBeenCalledWith('SMS', { provider: 'msg91', environment: 'TEST' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'WhatsApp provider' }), { target: { value: 'twilio|LIVE' } })
    await waitFor(() => expect(integrationService.setCommunicationRoute).toHaveBeenCalledWith('WHATSAPP', { provider: 'twilio', environment: 'LIVE' }))
  })

  it('does not offer MSG91 for WhatsApp routing', async () => {
    vi.mocked(integrationService.providers).mockResolvedValue(providers as never)
    vi.mocked(integrationService.connections).mockResolvedValue([
      { id: 'msg91-test', provider: 'msg91', capability: 'communication', environment: 'TEST', status: 'TEST', connection_name: 'MSG91 SMS', public_configuration: {}, credential_version: 1 },
    ])
    vi.mocked(integrationService.communicationRoutes).mockResolvedValue({ SMS: null, WHATSAPP: null })

    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><IntegrationsAdminPage /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('option', { name: 'MSG91 SMS · TEST' })).toBeInTheDocument())
    const whatsappOptions = screen.getByRole('combobox', { name: 'WhatsApp provider' }).querySelectorAll('option')
    expect(Array.from(whatsappOptions).map(option => option.textContent)).not.toContain('MSG91 SMS · TEST')
  })
})