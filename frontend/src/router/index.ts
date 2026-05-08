import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue'),
      },
      {
        path: 'assets',
        name: 'Assets',
        component: () => import('@/views/AssetsView.vue'),
      },
      {
        path: 'fleet',
        name: 'Fleet',
        component: () => import('@/views/FleetView.vue'),
      },
      {
        path: 'provisioner',
        name: 'Provisioner',
        component: () => import('@/views/ProvisionerView.vue'),
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/SettingsView.vue'),
      },
      {
        path: 'probes',
        name: 'Probes',
        component: () => import('@/views/ProbesView.vue'),
      },
      {
        path: 'sentinel',
        name: 'Sentinel',
        component: () => import('@/views/SentinelView.vue'),
      },
      {
        path: 'system',
        name: 'System',
        component: () => import('@/views/SystemView.vue'),
      },
      {
        path: 'abandonment',
        name: 'AccountAbandonment',
        component: () => import('@/views/AccountAbandonmentView.vue'),
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFoundView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // Wait for auth store to finish initializing (fetchMe call on app start)
  if (!auth.initialized && auth.accessToken) {
    await auth.fetchMe()
  }

  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
})

export default router
