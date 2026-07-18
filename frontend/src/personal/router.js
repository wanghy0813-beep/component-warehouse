import { createRouter, createWebHistory } from 'vue-router'
import { FEATURE_EDA_ENABLED } from '../shared/features'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/auth/callback', name: 'auth-callback', component: () => import('../shared/views/AuthCallback.vue') },
  { path: '/public/components/:code', name: 'public-component', component: () => import('../views/PublicComponent.vue') },
  { path: '/scan/:code', name: 'personal-scan', component: () => import('../views/PublicComponent.vue') },
  { path: '/public/projects/:code', name: 'public-project', component: () => import('../views/PublicProject.vue') },
  { path: '/components', name: 'components', component: () => import('../views/Components.vue') },
  { path: '/labels', name: 'custom-labels', component: () => import('../views/CustomLabels.vue') },
  { path: '/coverage', name: 'coverage', component: () => import('../views/Coverage.vue') },
  { path: '/projects', name: 'projects', component: () => import('../views/Projects.vue') },
  { path: '/manual', name: 'manual', component: () => import('../shared/views/UserManual.vue') },
  { path: '/purchases', name: 'purchases', component: () => import('../shared/views/Purchases.vue') },
  { path: '/risks', name: 'risks', component: () => import('../shared/views/Risks.vue') },
  { path: '/admin', redirect: '/about' },
  { path: '/about', name: 'about', component: () => import('../views/About.vue') }
]

if (FEATURE_EDA_ENABLED) {
  routes.splice(7, 0,
    { path: '/eda', name: 'eda', component: () => import('../shared/views/EdaLibrary.vue') },
    { path: '/eda-guide', name: 'eda-guide', component: () => import('../shared/views/EdaGuide.vue') }
  )
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
