import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import './styles.css'
import { TEAM_BASE } from '../shared/appPaths'
import { installAppBridge } from '../shared/appBridge'

installAppBridge({ surface: 'team', router })
createApp(App).use(router).mount('#app')

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(`${TEAM_BASE}team-sw.js`, { scope: TEAM_BASE }).catch(() => {})
  })
}
