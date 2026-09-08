import apiClient from '@/services/apiClient'

export interface ProviderField { field_code: string; label: string; required: boolean; masked?: boolean; write_only?: boolean; configured?: boolean }
export interface SupportedProvider {
  provider_code: string
  display_name: string
  capability: 'communication' | 'payment' | 'document_storage'
  supported_environments: ('TEST' | 'LIVE')[]
  public_fields: ProviderField[]
  secret_fields: ProviderField[]
  supports_connection_test: boolean
  supports_webhooks: boolean
}

export interface IntegrationConnection {
  id: string; provider: string; capability: string; environment: string; status: string
  connection_name: string | null; public_configuration: Record<string, string>
}

export const integrationService = {
  providers: () => apiClient.get<{ providers: SupportedProvider[] }>('/integrations/providers').then(response => response.data.providers),
  connections: () => apiClient.get<IntegrationConnection[]>('/integrations/connections').then(response => response.data),
  create: (payload: { provider_code: string; capability: string; environment: string; connection_name?: string; public_configuration: Record<string, string>; secrets: Record<string, string> }) => apiClient.post<IntegrationConnection>('/integrations/connections', payload).then(response => response.data),
  test: (provider: string, payload: { environment: string; credential_type: string }) => apiClient.post(`/integrations/connections/${provider}/test`, payload).then(response => response.data),
}