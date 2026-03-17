<template>
  <n-config-provider :theme="theme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-notification-provider>
        <MessageMount />
        <router-view />
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { h, defineComponent } from 'vue'
import { useMessage } from 'naive-ui'
import { useThemeStore } from './stores/theme'

// Mount $message globally so components can use window.$message
const MessageMount = defineComponent({
  setup() {
    window.$message = useMessage()
    return () => null
  },
})

const themeStore = useThemeStore()
const theme = themeStore.naiveTheme

const themeOverrides = {
  common: {
    primaryColor: '#18a058',
    primaryColorHover: '#36ad6a',
    primaryColorPressed: '#0c7a43',
    primaryColorSuppl: '#36ad6a',
    borderRadius: '8px',
  },
}
</script>

<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
</style>
