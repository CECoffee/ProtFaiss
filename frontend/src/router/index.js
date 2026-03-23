import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('../layouts/AppLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/search' },
      { path: 'search', component: () => import('../views/SearchView.vue') },
      { path: 'build', component: () => import('../views/BuilderView.vue') },
      { path: 'datasets', component: () => import('../views/DatasetsView.vue') },
      { path: 'gpu', component: () => import('../views/GpuDashboard.vue') },
      {
        path: 'admin',
        component: () => import('../views/admin/AdminLayout.vue'),
        meta: { requiresAdmin: true },
        children: [
          { path: '', redirect: '/admin/users' },
          { path: 'users', component: () => import('../views/admin/UsersView.vue') },
          { path: 'system', component: () => import('../views/admin/SystemView.vue') },
          { path: 'cluster', component: () => import('../views/admin/ClusterView.vue') },
        ],
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // Try to restore session on first load
  if (!auth.user && auth.accessToken) {
    await auth.fetchMe()
  }

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return '/login'
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return '/search'
  }
  if (to.path === '/login' && auth.isAuthenticated) {
    return '/search'
  }
})

export default router
