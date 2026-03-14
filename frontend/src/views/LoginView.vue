<template>
  <div class="login-wrap">
    <n-card class="login-card" :bordered="false">
      <div class="login-header">
        <span class="login-logo">🧬</span>
        <n-h2 style="margin: 8px 0 4px">FaaIndex</n-h2>
        <n-text depth="3">Protein Sequence Similarity Search</n-text>
      </div>

      <n-tabs v-model:value="tab" type="line" animated style="margin-top: 24px">
        <!-- Login tab -->
        <n-tab-pane name="login" tab="Login">
          <n-form ref="loginFormRef" :model="loginForm" :rules="loginRules" style="margin-top: 16px">
            <n-form-item path="username" label="Username">
              <n-input
                v-model:value="loginForm.username"
                placeholder="Username"
                @keydown.enter="handleLogin"
              />
            </n-form-item>
            <n-form-item path="password" label="Password">
              <n-input
                v-model:value="loginForm.password"
                type="password"
                show-password-on="click"
                placeholder="Password"
                @keydown.enter="handleLogin"
              />
            </n-form-item>
            <n-alert v-if="loginError" type="error" :title="loginError" style="margin-bottom: 16px" />
            <n-button
              type="primary"
              block
              :loading="loading"
              @click="handleLogin"
            >
              Login
            </n-button>
          </n-form>
        </n-tab-pane>

        <!-- Register tab -->
        <n-tab-pane name="register" tab="Register">
          <n-form ref="regFormRef" :model="regForm" :rules="regRules" style="margin-top: 16px">
            <n-form-item path="username" label="Username">
              <n-input v-model:value="regForm.username" placeholder="3-64 characters" />
            </n-form-item>
            <n-form-item path="email" label="Email (optional)">
              <n-input v-model:value="regForm.email" placeholder="user@example.com" />
            </n-form-item>
            <n-form-item path="password" label="Password">
              <n-input
                v-model:value="regForm.password"
                type="password"
                show-password-on="click"
                placeholder="At least 6 characters"
              />
            </n-form-item>
            <n-alert v-if="regError" type="error" :title="regError" style="margin-bottom: 16px" />
            <n-alert v-if="regSuccess" type="success" title="Account created! Please login." style="margin-bottom: 16px" />
            <n-button
              type="primary"
              block
              :loading="loading"
              @click="handleRegister"
            >
              Create Account
            </n-button>
          </n-form>
        </n-tab-pane>
      </n-tabs>
    </n-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { register } from '../api/auth'

const router = useRouter()
const auth = useAuthStore()

const tab = ref('login')
const loading = ref(false)
const loginError = ref('')
const regError = ref('')
const regSuccess = ref(false)

const loginFormRef = ref(null)
const regFormRef = ref(null)

const loginForm = ref({ username: '', password: '' })
const regForm = ref({ username: '', email: '', password: '' })

const loginRules = {
  username: { required: true, message: 'Username required', trigger: 'blur' },
  password: { required: true, message: 'Password required', trigger: 'blur' },
}
const regRules = {
  username: [
    { required: true, message: 'Username required', trigger: 'blur' },
    { min: 3, max: 64, message: '3-64 characters', trigger: 'blur' },
  ],
  password: [
    { required: true, message: 'Password required', trigger: 'blur' },
    { min: 6, message: 'At least 6 characters', trigger: 'blur' },
  ],
}

async function handleLogin() {
  loginError.value = ''
  try {
    await loginFormRef.value?.validate()
  } catch { return }
  loading.value = true
  try {
    await auth.login(loginForm.value.username, loginForm.value.password)
    router.push('/search')
  } catch (e) {
    loginError.value = e.response?.data?.detail || 'Login failed'
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  regError.value = ''
  regSuccess.value = false
  try {
    await regFormRef.value?.validate()
  } catch { return }
  loading.value = true
  try {
    await register(regForm.value.username, regForm.value.password, regForm.value.email || undefined)
    regSuccess.value = true
    regForm.value = { username: '', email: '', password: '' }
    setTimeout(() => { tab.value = 'login' }, 1500)
  } catch (e) {
    regError.value = e.response?.data?.detail || 'Registration failed'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
}
.login-card {
  width: 400px;
  border-radius: 16px;
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.5);
}
.login-header {
  text-align: center;
  padding-top: 8px;
}
.login-logo { font-size: 2.5rem; }
</style>
