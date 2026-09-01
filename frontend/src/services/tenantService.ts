import apiClient from './apiClient'

export interface DisplayToken {
  display_token: string
  display_url_path: string
}

export interface TenantBranding {
  hospital_name: string
  logo_url: string | null
  primary_color: string | null
  secondary_color: string | null
}

export const tenantService = {
  getDisplayToken: () =>
    apiClient.get<DisplayToken>('/tenants/display-token').then(r => r.data),

  rotateDisplayToken: () =>
    apiClient.post<DisplayToken>('/tenants/display-token/rotate').then(r => r.data),

  getBranding: () =>
    apiClient.get<TenantBranding>('/tenants/branding').then(r => r.data),
}
