import axios, { type AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/authStore'

const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

// Request interceptor: attach JWT token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const auth = useAuthStore()
    if (auth.accessToken) {
      config.headers.Authorization = `Bearer ${auth.accessToken}`
    }
    // Forward correlation ID if provided
    if (auth.correlationId) {
      config.headers['X-Correlation-ID'] = auth.correlationId
    }
    return config
  },
  (error: AxiosError) => Promise.reject(error)
)

// Response interceptor: handle 401 → refresh token
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    // Capture correlation ID from response headers
    const corrId = response.headers['x-correlation-id']
    if (corrId) {
      const auth = useAuthStore()
      auth.setCorrelationId(String(corrId))
    }
    return response
  },
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
    if (!originalRequest) return Promise.reject(error)

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true
      const auth = useAuthStore()
      try {
        await auth.refreshAccessToken()
        originalRequest.headers.Authorization = `Bearer ${auth.accessToken}`
        return apiClient(originalRequest)
      } catch {
        auth.logout()
        window.location.href = '/login'
        return Promise.reject(error)
      }
    }
    return Promise.reject(error)
  }
)

export default apiClient
