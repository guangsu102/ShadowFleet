import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '@/api/client'
import type {
  CurrentUser,
  LoginCredentials,
  TokenResponse,
} from '@/types/api'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const currentUser = ref<CurrentUser | null>(null)
  const correlationId = ref<string | null>(null)
  const initialized = ref(false)

  const isAuthenticated = computed(() => !!accessToken.value)
  const isAdmin = computed(() => currentUser.value?.role === 'admin')
  const isOperator = computed(() => ['admin', 'operator'].includes(currentUser.value?.role ?? ''))

  function setCorrelationId(id: string) {
    correlationId.value = id
  }

  async function login(credentials: LoginCredentials) {
    const { data } = await apiClient.post<TokenResponse>('/auth/login', credentials)
    accessToken.value = data.access_token
    refreshToken.value = data.refresh_token
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    initialized.value = true
    await fetchMe()
  }

  async function refreshAccessToken() {
    if (!refreshToken.value) throw new Error('No refresh token')
    const { data } = await apiClient.post<TokenResponse>('/auth/refresh', {
      refresh_token: refreshToken.value,
    })
    accessToken.value = data.access_token
    refreshToken.value = data.refresh_token
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
  }

  async function fetchMe() {
    if (!accessToken.value) {
      initialized.value = true
      return
    }
    try {
      const { data } = await apiClient.get<CurrentUser>('/auth/me')
      currentUser.value = data
    } catch {
      // Token may be expired; let the axios interceptor handle refresh
    } finally {
      initialized.value = true
    }
  }

  function logout() {
    accessToken.value = null
    refreshToken.value = null
    currentUser.value = null
    correlationId.value = null
    initialized.value = false
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  return {
    accessToken,
    refreshToken,
    currentUser,
    correlationId,
    initialized,
    isAuthenticated,
    isAdmin,
    isOperator,
    setCorrelationId,
    login,
    refreshAccessToken,
    fetchMe,
    logout,
  }
})
