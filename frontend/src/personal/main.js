import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import '../styles/main.css'
import { installAppBridge } from '../shared/appBridge'
import { PERSONAL_BASE } from '../shared/appPaths'

installAppBridge({ surface: 'personal', router })
createApp(App).use(router).mount('#app')

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(`${PERSONAL_BASE}sw.js`, { scope: PERSONAL_BASE }).catch(() => {})
  })
}
