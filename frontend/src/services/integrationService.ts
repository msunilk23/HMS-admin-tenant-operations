import apiClient from '@/services/apiClient'

export interface ProviderField { field_code: string; label: string; required: boolean; masked?: boolean; write_only?: boolean; configured?: boolean }
export interface SupportedProvider {
  provider_code: string
  display_name: string
  capability: 'communication' | 'payment' | 'document_storage'
  supported_channels: ('SMS' | 'WHATSAPP')[]
  supported_environments: ('TEST' | 'LIVE')[]
  public_fields: ProviderField[]
  secret_fields: ProviderField[]
  supports_connection_test: boolean
  supports_webhooks: boolean
}

export interface IntegrationConnection {
  id: string; provider: string; capability: string; environment: string; status: string
  connection_name: string | null; public_configuration: Record<string, string>; credential_version?: number
}

export interface CommunicationRoutes {
  SMS: { provider: string; environment: string } | null
  WHATSAPP: { provider: string; environment: string } | null
}

export const integrationService = {
  providers: () => apiClient.get<{ providers: SupportedProvider[] }>('/integrations/providers').then(response => response.data.providers),
  connections: () => apiClient.get<IntegrationConnection[]>('/integrations/connections').then(response => response.data),
  communicationRoutes: () => apiClient.get<{ routes: CommunicationRoutes }>('/integrations/communication-routes').then(response => response.data.routes),
  setCommunicationRoute: (channel: keyof CommunicationRoutes, payload: { provider: string; environment: string }) =>
    apiClient.put(`/integrations/communication-routes/${channel}`, payload).then(response => response.data),
  clearCommunicationRoute: (channel: keyof CommunicationRoutes) =>
    apiClient.delete(`/integrations/communication-routes/${channel}`).then(response => response.data),
  create: (payload: { provider_code: string; capability: string; environment: string; connection_name?: string; public_configuration: Record<string, string>; secrets: Record<string, string> }) => apiClient.post<IntegrationConnection>('/integrations/connections', payload).then(response => response.data),
  update: (provider: string, payload: { environment: string; connection_name?: string; public_configuration?: Record<string, string> }) => apiClient.patch<IntegrationConnection>(`/integrations/connections/${provider}`, payload).then(response => response.data),
  rotateSecret: (provider: string, payload: { environment: string; credential_type: string; secret: string }) => apiClient.post(`/integrations/connections/${provider}/rotate`, payload).then(response => response.data),
  enable: (provider: string, environment?: string) => apiClient.post(`/integrations/connections/${provider}/enable`, undefined, { params: { environment } }).then(response => response.data),
  disable: (provider: string, environment?: string) => apiClient.post(`/integrations/connections/${provider}/disable`, undefined, { params: { environment } }).then(response => response.data),
  test: (provider: string, payload: { environment: string; credential_type: string }) => apiClient.post(`/integrations/connections/${provider}/test`, payload).then(response => response.data),
}