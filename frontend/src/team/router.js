import { createRouter, createWebHistory } from 'vue-router'
import { FEATURE_EDA_ENABLED } from '../shared/features'

const routes = [
  { path: '/', name: 'libraries', component: () => import('./views/Libraries.vue') },
  { path: '/join/:token', name: 'join', meta: { publicJoin: true }, component: () => import('./views/Join.vue') },
  {
    path: '/scan/:libraryId/:itemId',
    redirect: (to) => ({
      name: 'team-components',
      params: { libraryId: to.params.libraryId },
      query: { component: to.params.itemId }
    })
  },
  { path: '/library/:libraryId/components', name: 'team-components', component: () => import('./views/Components.vue') },
  { path: '/library/:libraryId/pcbs', name: 'team-pcbs', component: () => import('./views/Pcbs.vue') },
  { path: '/library/:libraryId/projects', name: 'team-projects', component: () => import('./views/Projects.vue') },
  { path: '/library/:libraryId/manual', name: 'team-manual', component: () => import('../shared/views/UserManual.vue') },
  { path: '/library/:libraryId/purchases', name: 'team-purchases', component: () => import('../shared/views/Purchases.vue') },
  { path: '/library/:libraryId/risks', name: 'team-risks', component: () => import('../shared/views/Risks.vue') },
  { path: '/library/:libraryId/members', name: 'team-members', component: () => import('./views/Members.vue') },
  { path: '/library/:libraryId/logs', name: 'team-logs', component: () => import('./views/Logs.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

if (FEATURE_EDA_ENABLED) {
  routes.splice(6, 0,
    { path: '/library/:libraryId/eda', name: 'team-eda', component: () => import('../shared/views/EdaLibrary.vue') },
    { path: '/library/:libraryId/eda-guide', name: 'team-eda-guide', component: () => import('../shared/views/EdaGuide.vue') }
  )
}

export default createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})
