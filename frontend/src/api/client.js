import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
})

// Attach JWT to every request
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Auto-refresh on 401
let _refreshing = false
let _refreshQueue = []

client.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      if (_refreshing) {
        return new Promise((resolve, reject) => {
          _refreshQueue.push({ resolve, reject })
        }).then((token) => {
          original.headers.Authorization = `Bearer ${token}`
          return client(original)
        })
      }
      _refreshing = true
      try {
        const refreshToken = localStorage.getItem('refresh_token')
        if (!refreshToken) throw new Error('No refresh token')
        const resp = await axios.post('/auth/refresh', { refresh_token: refreshToken })
        const { access_token, refresh_token } = resp.data
        localStorage.setItem('access_token', access_token)
        localStorage.setItem('refresh_token', refresh_token)
        _refreshQueue.forEach(({ resolve }) => resolve(access_token))
        _refreshQueue = []
        original.headers.Authorization = `Bearer ${access_token}`
        return client(original)
      } catch (e) {
        _refreshQueue.forEach(({ reject }) => reject(e))
        _refreshQueue = []
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        window.location.href = '/login'
        return Promise.reject(e)
      } finally {
        _refreshing = false
      }
    }
    return Promise.reject(error)
  }
)

export default client
