import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import '../styles/main.css'
import { installAppBridge } from '../shared/appBridge'

installAppBridge({ surface: 'personal', router })
createApp(App).use(router).mount('#app')
