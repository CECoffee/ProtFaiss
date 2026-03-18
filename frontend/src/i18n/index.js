import { ref, computed, watchEffect } from 'vue'
import en from './en.js'
import zh from './zh.js'

const STORAGE_KEY = 'protfaiss-locale'
const messages = { en, zh }

const locale = ref(localStorage.getItem(STORAGE_KEY) || 'en')

watchEffect(() => { localStorage.setItem(STORAGE_KEY, locale.value) })

function t(key, vars = {}) {
  const str = messages[locale.value]?.[key] ?? messages.en[key] ?? key
  return str.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '')
}

function toggleLocale() {
  locale.value = locale.value === 'en' ? 'zh' : 'en'
}

export function useI18n() {
  return { locale, t, toggleLocale }
}
