<template>
  <div class="login-wrap">
    <n-card class="login-card" :bordered="false">
      <div class="login-header">
        <span class="login-logo">🧬</span>
        <n-h2 style="margin: 8px 0 4px">ProtFaiss</n-h2>
        <n-text depth="3">{{ t('login.subtitle') }}</n-text>
      </div>

      <n-tabs v-model:value="tab" type="line" animated style="margin-top: 24px">
        <!-- Login tab -->
        <n-tab-pane name="login" :tab="t('login.tab.login')">
          <n-form ref="loginFormRef" :model="loginForm" :rules="loginRules" style="margin-top: 16px">
            <n-form-item path="username" :label="t('login.username')">
              <n-input
                v-model:value="loginForm.username"
                :placeholder="t('login.username')"
                @keydown.enter="handleLogin"
              />
            </n-form-item>
            <n-form-item path="password" :label="t('login.password')">
              <n-input
                v-model:value="loginForm.password"
                type="password"
                show-password-on="click"
                :placeholder="t('login.password')"
                @keydown.enter="handleLogin"
              />
            </n-form-item>
            <n-alert v-if="loginError" type="error" :title="loginError" style="margin-bottom: 16px" />
            <n-button type="primary" block :loading="loading" @click="handleLogin">
              {{ t('login.btnLogin') }}
            </n-button>
          </n-form>
        </n-tab-pane>

        <!-- Register tab -->
        <n-tab-pane name="register" :tab="t('login.tab.register')">
          <n-form ref="regFormRef" :model="regForm" :rules="regRules" style="margin-top: 16px">
            <n-form-item path="username" :label="t('login.username')">
              <n-input v-model:value="regForm.username" :placeholder="t('login.usernamePlaceholder')" />
            </n-form-item>
            <n-form-item path="email" :label="t('login.email')">
              <n-input v-model:value="regForm.email" :placeholder="t('login.emailPlaceholder')" />
            </n-form-item>
            <n-form-item path="password" :label="t('login.password')">
              <n-input
                v-model:value="regForm.password"
                type="password"
                show-password-on="click"
                :placeholder="t('login.passwordPlaceholder')"
              />
            </n-form-item>
            <n-alert v-if="regError" type="error" :title="regError" style="margin-bottom: 16px" />
            <n-alert v-if="regSuccess" type="success" :title="t('login.registerSuccess')" style="margin-bottom: 16px" />
            <n-button type="primary" block :loading="loading" @click="handleRegister">
              {{ t('login.btnRegister') }}
            </n-button>
          </n-form>
        </n-tab-pane>
      </n-tabs>
    </n-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { register } from '../api/auth'
import { useI18n } from '../i18n/index.js'

const { t } = useI18n()
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

const loginRules = computed(() => ({
  username: { required: true, message: t('login.rule.usernameRequired'), trigger: 'blur' },
  password: { required: true, message: t('login.rule.passwordRequired'), trigger: 'blur' },
}))
const regRules = computed(() => ({
  username: [
    { required: true, message: t('login.rule.usernameRequired'), trigger: 'blur' },
    { min: 3, max: 64, message: t('login.rule.usernameLength'), trigger: 'blur' },
  ],
  password: [
    { required: true, message: t('login.rule.passwordRequired'), trigger: 'blur' },
    { min: 6, message: t('login.rule.passwordLength'), trigger: 'blur' },
  ],
}))

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
