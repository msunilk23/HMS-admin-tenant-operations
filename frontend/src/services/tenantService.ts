import apiClient from './apiClient'

export interface DisplayToken {
  display_token: string
  display_url_path: string
}

export const tenantService = {
  getDisplayToken: () =>
    apiClient.get<DisplayToken>('/tenants/display-token').then(r => r.data),

  rotateDisplayToken: () =>
    apiClient.post<DisplayToken>('/tenants/display-token/rotate').then(r => r.data),
}
