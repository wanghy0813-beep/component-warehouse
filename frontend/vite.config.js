import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { API_BASE, HEALTH_URL, PERSONAL_BASE, TEAM_BASE } from './src/shared/appPaths.js'

const target = process.env.VITE_APP_TARGET || 'personal'
const isTeam = target === 'team'
const isDesktop = process.env.VITE_DESKTOP === '1'
const personalTitle = process.env.VITE_BRAND_PERSONAL_TITLE || 'WXY LAB Hardware · 个人硬件研发工作台'
const teamTitle = process.env.VITE_BRAND_TEAM_TITLE || 'WXY LAB Hardware Workspace · 团队版暂停维护'
const personalAppName = process.env.VITE_PWA_PERSONAL_NAME || 'WXY LAB Hardware'
const teamAppName = process.env.VITE_PWA_TEAM_NAME || 'WXY LAB Hardware Workspace 团队版'
const elementName = (name) => name
  .replace(/^El/, '')
  .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
  .toLowerCase()
const elementParentComponents = {
  'collapse-item': 'collapse',
  'descriptions-item': 'descriptions',
  'dropdown-item': 'dropdown',
  'dropdown-menu': 'dropdown',
  'form-item': 'form',
  option: 'select',
  'radio-button': 'radio',
  'radio-group': 'radio',
  'skeleton-item': 'skeleton',
  'tab-pane': 'tabs',
  'table-column': 'table',
  'timeline-item': 'timeline'
}
const elementStyles = (name) => [
  'element-plus/es/components/base/style/css',
  `element-plus/es/components/${name}/style/css`
]
const directElementPlusResolver = (name) => {
  if (!/^El[A-Z]/.test(name) || /^ElIcon[A-Z]/.test(name)) return
  const partial = elementName(name)
  const moduleName = elementParentComponents[partial] || partial
  return {
    name,
    from: `element-plus/es/components/${moduleName}/index`,
    sideEffects: elementStyles(moduleName)
  }
}
const directElementPlusDirectiveResolver = {
  type: 'directive',
  resolve(name) {
    if (name !== 'Loading') return
    return {
      name: 'ElLoadingDirective',
      from: 'element-plus/es/components/loading/index',
      sideEffects: elementStyles('loading')
    }
  }
}

export default defineConfig({
  base: isDesktop ? './' : (isTeam ? TEAM_BASE : PERSONAL_BASE),
  plugins: [
    vue(),
    Components({
      resolvers: [directElementPlusResolver, directElementPlusDirectiveResolver],
      dts: false
    }),
    {
      name: 'component-warehouse-dual-entry',
      transformIndexHtml: {
        order: 'pre',
        handler(html) {
          const appName = isTeam ? teamAppName : personalAppName
          const titledHtml = html
            .replace('<title>WXY LAB Hardware · 个人硬件研发工作台</title>', `<title>${isTeam ? teamTitle : personalTitle}</title>`)
            .replace('<meta name="application-name" content="WXY LAB Hardware" />', `<meta name="application-name" content="${appName}" />`)
            .replace('<meta name="apple-mobile-web-app-title" content="WXY LAB Hardware" />', `<meta name="apple-mobile-web-app-title" content="${appName}" />`)
          if (!isTeam) return titledHtml
          return titledHtml
            .replace('/src/personal/main.js', '/src/team/main.js')
            .replace(`${TEAM_BASE}manifest.webmanifest`, `${TEAM_BASE}team-manifest.webmanifest`)
        }
      }
    }
  ],
  build: {
    outDir: isDesktop ? 'dist/desktop' : `dist/${target}`,
    emptyOutDir: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/echarts')) return 'vendor-charts'
          if (id.includes('node_modules/markdown-it')) return 'vendor-markdown'
          if (id.includes('node_modules/vue')) return 'vendor-vue'
          if (id.includes('node_modules/axios')) return 'vendor-http'
        }
      }
    }
  },
  server: {
    port: 5173,
    proxy: {
      [API_BASE]: {
        target: 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(API_BASE, '/api')
      },
      [HEALTH_URL]: {
        target: 'http://127.0.0.1:8000',
        rewrite: () => '/health'
      }
    }
  }
})
