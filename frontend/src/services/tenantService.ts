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

  updateBranding: (body: { primary_color?: string; secondary_color?: string }) =>
    apiClient.patch<TenantBranding>('/tenants/branding', body).then(r => r.data),

  uploadBrandingLogo: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    // Let the browser set the multipart boundary — override apiClient's default JSON content type.
    return apiClient
      .post<TenantBranding>('/tenants/branding/logo', formData, { headers: { 'Content-Type': undefined } })
      .then(r => r.data)
  },
}
