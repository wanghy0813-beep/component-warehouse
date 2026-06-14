import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
    { path: '/components', name: 'components', component: () => import('../views/Components.vue') },
    { path: '/coverage', name: 'coverage', component: () => import('../views/Coverage.vue') },
    { path: '/projects', name: 'projects', component: () => import('../views/Projects.vue') },
    { path: '/about', name: 'about', component: () => import('../views/About.vue') }
  ]
})

export default router
