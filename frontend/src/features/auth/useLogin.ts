import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from './authStore'
import apiClient from '@/services/apiClient'

interface LoginPayload {
  login_id: string   // email OR username
  password: string
}

interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  must_change_password: boolean
}

function homeForRole(role: string): string {
  if (role === 'doctor') return '/doctor/consultation'
  if (role === 'nurse') return '/nurse/vitals'
  if (role === 'pharmacist') return '/pharmacy'
  if (role === 'lab_technician') return '/lab'
  return '/dashboard'
}

export function useLogin() {
  const { setTokens } = useAuthStore()
  const navigate = useNavigate()

  return useMutation({
    mutationFn: (payload: LoginPayload) =>
      apiClient.post<TokenResponse>('/auth/login', payload).then((r) => r.data),
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token)
      const user = useAuthStore.getState().user
      if (user?.mustChangePassword) {
        navigate('/change-password', { replace: true })
        return
      }
      const role = user?.role ?? ''
      navigate(homeForRole(role), { replace: true })
    },
  })
}
