import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', component: AppLayout, children: [
    { path: '', name: 'home', component: () => import('@/views/StatsView.vue') },
    { path: 'generate', name: 'generate', component: () => import('@/views/GenerationView.vue') },
    { path: 'review', name: 'review', component: () => import('@/views/ReviewView.vue') },
    // 看板挂在 '' 上；'stats' 只做兼容重定向——UI 里没有指向它的入口，
    // 但早期链接/书签可能停在 /stats，保留 redirect 比直接 404 友好。
    { path: 'stats', redirect: '/' },
    { path: 'knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeView.vue') },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue') },
  ]},
]
export default createRouter({ history: createWebHistory(), routes })
