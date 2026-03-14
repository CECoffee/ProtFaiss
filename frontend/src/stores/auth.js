import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as apiLogin, logout as apiLogout, getMe } from '../api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const accessToken = ref(localStorage.getItem('access_token') || null)
  const refreshToken = ref(localStorage.getItem('refresh_token') || null)

  const isAuthenticated = computed(() => !!accessToken.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function login(username, password) {
    const data = await apiLogin(username, password)
    accessToken.value = data.access_token
    refreshToken.value = data.refresh_token
    user.value = data.user
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
  }

  async function logout() {
    try {
      if (refreshToken.value) await apiLogout(refreshToken.value)
    } catch {}
    accessToken.value = null
    refreshToken.value = null
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  async function fetchMe() {
    if (!accessToken.value) return
    try {
      user.value = await getMe(accessToken.value)
    } catch {
      await logout()
    }
  }

  return { user, accessToken, refreshToken, isAuthenticated, isAdmin, login, logout, fetchMe }
})
