<template>
  <n-layout has-sider style="height: 100vh">
    <!-- Sidebar -->
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div class="logo" :class="{ collapsed }">
        <span class="logo-icon">🧬</span>
        <span v-if="!collapsed" class="logo-text">FaaIndex</span>
      </div>
      <n-menu
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        :options="menuOptions"
        :value="activeKey"
        @update:value="handleMenuSelect"
      />
    </n-layout-sider>

    <!-- Main content -->
    <n-layout>
      <!-- Top bar -->
      <n-layout-header bordered style="height: 56px; padding: 0 20px; display: flex; align-items: center; justify-content: space-between;">
        <n-text style="font-size: 1rem; font-weight: 600; color: var(--n-text-color)">
          {{ pageTitle }}
        </n-text>
        <n-space align="center">
          <n-tag :type="gpuTagType" size="small" round>
            GPU {{ gpuStore.pool.used_slots }}/{{ gpuStore.pool.total_slots }}
          </n-tag>
          <n-dropdown :options="userMenuOptions" @select="handleUserAction">
            <n-button text style="cursor: pointer">
              <n-space align="center" :size="6">
                <n-avatar round size="small" style="background: #18a058; color: white; font-size: 0.75rem">
                  {{ userInitial }}
                </n-avatar>
                <n-text>{{ auth.user?.username }}</n-text>
                <n-tag v-if="auth.isAdmin" type="warning" size="small" round>Admin</n-tag>
              </n-space>
            </n-button>
          </n-dropdown>
        </n-space>
      </n-layout-header>

      <!-- Page content -->
      <n-layout-content style="padding: 28px 32px; overflow-y: auto; height: calc(100vh - 56px)">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup>
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NIcon } from 'naive-ui'
import {
  SearchOutline, HammerOutline, FolderOutline,
  HardwareChipOutline, PeopleOutline, SettingsOutline, LogOutOutline,
} from '@vicons/ionicons5'
import { useAuthStore } from '../stores/auth'
import { useGpuStore } from '../stores/gpu'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const gpuStore = useGpuStore()
const collapsed = ref(false)

const icon = (comp) => () => h(NIcon, null, { default: () => h(comp) })

const menuOptions = computed(() => {
  const items = [
    { label: 'Search', key: '/search', icon: icon(SearchOutline) },
    { label: 'Build Index', key: '/build', icon: icon(HammerOutline) },
    { label: 'Datasets', key: '/datasets', icon: icon(FolderOutline) },
    { label: 'GPU Queue', key: '/gpu', icon: icon(HardwareChipOutline) },
  ]
  if (auth.isAdmin) {
    items.push({ type: 'divider', key: 'div' })
    items.push({ label: 'Users', key: '/admin/users', icon: icon(PeopleOutline) })
    items.push({ label: 'System', key: '/admin/system', icon: icon(SettingsOutline) })
  }
  return items
})

const activeKey = computed(() => route.path)

const pageTitles = {
  '/search': 'Protein Search',
  '/build': 'Build Index',
  '/datasets': 'Manage Datasets',
  '/gpu': 'GPU Queue',
  '/admin/users': 'User Management',
  '/admin/system': 'System',
}
const pageTitle = computed(() => pageTitles[route.path] || 'FaaIndex')

const userInitial = computed(() => (auth.user?.username?.[0] || '?').toUpperCase())

const gpuTagType = computed(() => {
  const { used_slots, total_slots } = gpuStore.pool
  if (!total_slots) return 'default'
  const ratio = used_slots / total_slots
  if (ratio >= 1) return 'error'
  if (ratio >= 0.75) return 'warning'
  return 'success'
})

const userMenuOptions = [
  { label: 'Logout', key: 'logout', icon: icon(LogOutOutline) },
]

function handleMenuSelect(key) {
  router.push(key)
}

async function handleUserAction(key) {
  if (key === 'logout') {
    await auth.logout()
    router.push('/login')
  }
}

// Poll GPU status every 5s
let gpuTimer = null
onMounted(() => {
  gpuStore.fetchQueue()
  gpuTimer = setInterval(() => gpuStore.fetchQueue(), 5000)
})
onUnmounted(() => clearInterval(gpuTimer))
</script>

<style scoped>
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  gap: 10px;
  border-bottom: 1px solid var(--n-border-color);
  overflow: hidden;
}
.logo.collapsed { justify-content: center; padding: 0; }
.logo-icon { font-size: 1.4rem; flex-shrink: 0; }
.logo-text { font-size: 1.1rem; font-weight: 700; white-space: nowrap; }
</style>
