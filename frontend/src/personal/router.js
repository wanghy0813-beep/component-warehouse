import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import { FEATURE_EDA_ENABLED } from '../shared/features'
import { IS_DESKTOP } from '../shared/desktopBridge'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/auth/callback', name: 'auth-callback', component: () => import('../shared/views/AuthCallback.vue') },
  { path: '/public/components/:code', name: 'public-component', component: () => import('../views/PublicComponent.vue') },
  { path: '/scan/:code', name: 'personal-scan', component: () => import('../views/PublicComponent.vue') },
  { path: '/components', name: 'components', component: () => import('../views/Components.vue') },
  { path: '/labels', name: 'custom-labels', component: () => import('../views/CustomLabels.vue') },
  { path: '/coverage', name: 'coverage', component: () => import('../views/Coverage.vue') },
  { path: '/projects', name: 'projects', component: () => import('../views/ProjectWorkspace.vue') },
  { path: '/projects/:projectId([0-9a-fA-F-]{36})', name: 'project-detail', component: () => import('../views/ProjectWorkspace.vue') },
  { path: '/projects/:legacyPath(.*)*', redirect: '/projects' },
  { path: '/public/projects/:legacyPath(.*)*', redirect: '/projects' },
  { path: '/manual', name: 'manual', component: () => import('../shared/views/UserManual.vue') },
  { path: '/purchases', name: 'purchases', component: () => import('../shared/views/Purchases.vue') },
  { path: '/risks', name: 'risks', component: () => import('../shared/views/Risks.vue') },
  ...(IS_DESKTOP ? [
    { path: '/integrations/codex/:pathMatch(.*)*', redirect: '/about' }
  ] : [
    { path: '/integrations/codex', name: 'codex-integrations', component: () => import('../views/CodexIntegrations.vue') },
    { path: '/integrations/codex/oauth/:requestId', name: 'codex-oauth', component: () => import('../views/CodexOauthAuthorize.vue') },
    { path: '/integrations/codex/operations/:operationId', name: 'codex-operation', component: () => import('../views/CodexOperation.vue') }
  ]),
  { path: '/admin', redirect: '/about' },
  { path: '/about', name: 'about', component: () => import('../views/About.vue') }
]

if (IS_DESKTOP) {
  routes.push({ path: '/sync-conflicts', name: 'sync-conflicts', component: () => import('../views/SyncConflicts.vue') })
}

if (FEATURE_EDA_ENABLED) {
  routes.splice(7, 0,
    { path: '/eda', name: 'eda', component: () => import('../shared/views/EdaLibrary.vue') },
    { path: '/eda-guide', name: 'eda-guide', component: () => import('../shared/views/EdaGuide.vue') }
  )
}

const router = createRouter({
  history: import.meta.env.VITE_DESKTOP === '1' ? createWebHashHistory() : createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
