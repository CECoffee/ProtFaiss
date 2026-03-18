import { ref, computed, watchEffect } from 'vue'
import { darkTheme } from 'naive-ui'

const STORAGE_KEY = 'protfaiss-theme'

const mode = ref(localStorage.getItem(STORAGE_KEY) || 'system')

const systemDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)
const mq = window.matchMedia('(prefers-color-scheme: dark)')
mq.addEventListener('change', (e) => { systemDark.value = e.matches })

const resolvedDark = computed(() => {
  if (mode.value === 'dark') return true
  if (mode.value === 'light') return false
  return systemDark.value
})

const naiveTheme = computed(() => resolvedDark.value ? darkTheme : null)

watchEffect(() => { localStorage.setItem(STORAGE_KEY, mode.value) })

function cycleMode() {
  const order = ['light', 'dark', 'system']
  mode.value = order[(order.indexOf(mode.value) + 1) % order.length]
}

export function useThemeStore() {
  return { mode, resolvedDark, naiveTheme, cycleMode }
}
