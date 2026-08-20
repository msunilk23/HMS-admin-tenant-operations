import axios from 'axios'
import { useAuthStore } from '@/features/auth/authStore'

const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT on every request
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// On 401, attempt silent refresh then retry once; if that also fails, mark session expired
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true
      const { refreshToken, markSessionExpired, setTokens } = useAuthStore.getState()
      if (!refreshToken) {
        markSessionExpired()
        return Promise.reject(error)
      }
      try {
        const { data } = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
        setTokens(data.access_token, data.refresh_token)
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`
        return apiClient(originalRequest)
      } catch {
        // Refresh token also rejected — secret key likely changed
        markSessionExpired()
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
