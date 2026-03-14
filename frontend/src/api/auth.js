import client from './client'

export async function login(username, password) {
  const resp = await client.post('/auth/login', { username, password })
  return resp.data
}

export async function register(username, password, email) {
  const resp = await client.post('/auth/register', { username, password, email })
  return resp.data
}

export async function logout(refreshToken) {
  await client.post('/auth/logout', { refresh_token: refreshToken })
}

export async function getMe(token) {
  const resp = await client.get('/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  return resp.data
}
