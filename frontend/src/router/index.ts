import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', component: AppLayout, children: [
    { path: '', name: 'home', component: () => import('@/views/StatsView.vue') },
    { path: 'generate', name: 'generate', component: () => import('@/views/GenerationView.vue') },
    { path: 'review', name: 'review', component: () => import('@/views/ReviewView.vue') },
    { path: 'stats', name: 'stats', component: () => import('@/views/StatsView.vue') },
    { path: 'knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeView.vue') },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue') },
  ]},
]
export default createRouter({ history: createWebHistory(), routes })
