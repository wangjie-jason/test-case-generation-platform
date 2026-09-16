import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  // 登录页独立于 AppLayout（无侧边栏/页头）
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  { path: '/', component: AppLayout, children: [
    { path: '', name: 'home', component: () => import('@/views/StatsView.vue') },
    { path: 'generate', name: 'generate', component: () => import('@/views/GenerationView.vue') },
    { path: 'review', name: 'review', component: () => import('@/views/ReviewView.vue') },
    // 看板挂在 '' 上；'stats' 只做兼容重定向——UI 里没有指向它的入口，
    // 但早期链接/书签可能停在 /stats，保留 redirect 比直接 404 友好。
    { path: 'stats', redirect: '/' },
    { path: 'knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeView.vue') },
    { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue') },
  ]},
]
const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    // 已登录再访问登录页，直接回首页。
    if (to.name === 'login' && auth.token) return { path: '/' }
    return true
  }
  if (!auth.token) {
    return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : undefined }
  }
  // 刷新后内存里没有 user，先用 token 恢复一次（失败会清态并被下一轮守卫拦回登录页）。
  await auth.ensureLoaded()
  if (!auth.user) return { path: '/login' }
  return true
})

export default router
