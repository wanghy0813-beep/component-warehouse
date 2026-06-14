<template>
  <el-config-provider>
    <div v-if="checking" class="boot">Loading...</div>
    <div v-else-if="needsLogin" class="login-page">
      <el-card class="login-card" shadow="never">
        <div class="login-mark">
          <Cpu />
        </div>
        <h1>Component Warehouse</h1>
        <p>个人元器件库存与 PCB 选型工作台</p>
        <el-form @submit.prevent="submitLogin">
          <el-form-item>
            <el-input
              v-model="password"
              type="password"
              show-password
              placeholder="访问密码"
              @keyup.enter="submitLogin"
            />
          </el-form-item>
          <el-button type="primary" :loading="loggingIn" class="login-button" @click="submitLogin">
            登录
          </el-button>
        </el-form>
      </el-card>
    </div>
    <el-container v-else class="app-shell" :class="{ collapsed: sidebarCollapsed }">
      <el-aside :width="sidebarCollapsed ? '72px' : '228px'" class="sidebar">
        <div class="brand">
          <Cpu class="brand-icon" />
          <div v-if="!sidebarCollapsed">
            <strong>Component Warehouse</strong>
            <span>个人元器件库存</span>
          </div>
          <el-button class="collapse-button" text circle @click="toggleSidebar">
            <el-icon><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
          </el-button>
        </div>
        <el-menu :default-active="$route.path" router :collapse="sidebarCollapsed">
          <el-menu-item index="/">
            <el-icon><DataBoard /></el-icon>
            <span>Dashboard</span>
          </el-menu-item>
          <el-menu-item index="/components">
            <el-icon><Box /></el-icon>
            <span>元器件库</span>
          </el-menu-item>
          <el-menu-item index="/coverage">
            <el-icon><DataBoard /></el-icon>
            <span>覆盖图</span>
          </el-menu-item>
          <el-menu-item index="/projects">
            <el-icon><Files /></el-icon>
            <span>项目 BOM</span>
          </el-menu-item>
          <el-menu-item index="/about">
            <el-icon><InfoFilled /></el-icon>
            <span>关于</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      <el-container>
        <el-header class="topbar">
          <div>
            <span>{{ routeTitle }}</span>
            <small>库存优先，AI 辅助选型</small>
          </div>
          <el-button v-if="authRequired" size="small" @click="handleLogout">退出</el-button>
        </el-header>
        <el-main>
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Box, Cpu, DataBoard, Expand, Files, Fold, InfoFilled } from '@element-plus/icons-vue'
import { authConfig, login, logout } from './api/client'

const route = useRoute()
const checking = ref(true)
const authRequired = ref(false)
const password = ref('')
const loggingIn = ref(false)
const accessToken = ref(localStorage.getItem('cw_token') || '')
const sidebarCollapsed = ref(localStorage.getItem('cw_sidebar_collapsed') === '1')

const needsLogin = computed(() => authRequired.value && !accessToken.value)
const routeTitle = computed(() => {
  const titles = {
    '/': 'Dashboard',
    '/components': '元器件库',
    '/coverage': '覆盖图',
    '/projects': '项目 BOM',
    '/about': '关于'
  }
  return titles[route.path] || 'Component Warehouse'
})

onMounted(async () => {
  try {
    const config = await authConfig()
    authRequired.value = config.auth_required
  } catch (error) {
    ElMessage.error('无法连接后端服务')
  } finally {
    checking.value = false
  }
})

async function submitLogin() {
  loggingIn.value = true
  try {
    const data = await login(password.value)
    accessToken.value = data.token || localStorage.getItem('cw_token') || ''
    password.value = ''
    ElMessage.success('已登录')
  } catch (error) {
    ElMessage.error('密码错误')
  } finally {
    loggingIn.value = false
  }
}

function handleLogout() {
  logout()
  accessToken.value = ''
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('cw_sidebar_collapsed', sidebarCollapsed.value ? '1' : '0')
}
</script>

<style scoped>
.boot,
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.login-card {
  width: min(390px, calc(100vw - 32px));
  border: 1px solid var(--cw-border);
  border-radius: 8px;
  background: var(--cw-panel);
}

.login-mark {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  margin-bottom: 14px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--cw-accent) 12%, transparent);
  color: var(--cw-accent);
}

.login-card h1 {
  margin: 0;
  font-size: 24px;
}

.login-card p {
  margin: 8px 0 22px;
  color: var(--cw-muted);
  font-size: 14px;
}

.login-button {
  width: 100%;
}

.app-shell {
  min-height: 100vh;
  background: var(--cw-bg);
}

.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: auto;
  border-right: 1px solid var(--cw-border);
  background: var(--cw-panel);
  transition: width 0.18s ease;
}

.brand {
  height: 64px;
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 0 18px;
  border-bottom: 1px solid var(--cw-border);
}

.collapse-button {
  margin-left: auto;
}

.brand-icon {
  width: 28px;
  height: 28px;
  color: var(--cw-accent);
}

.brand strong,
.brand span {
  display: block;
}

.brand span {
  margin-top: 2px;
  color: var(--cw-muted);
  font-size: 12px;
}

.topbar {
  height: 60px;
  border-bottom: 1px solid var(--cw-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: color-mix(in srgb, var(--cw-panel) 90%, transparent);
  font-weight: 600;
  backdrop-filter: blur(10px);
}

.topbar small {
  display: block;
  margin-top: 2px;
  color: var(--cw-muted);
  font-size: 12px;
  font-weight: 500;
}

@media (max-width: 760px) {
  .app-shell {
    display: block;
  }

  .sidebar {
    position: static;
    height: auto;
    width: 100% !important;
    border-right: 0;
    border-bottom: 1px solid var(--cw-border);
  }

  .brand {
    height: 56px;
  }

  .sidebar :deep(.el-menu) {
    display: flex;
    overflow-x: auto;
    border-right: 0;
  }

  .sidebar :deep(.el-menu-item) {
    flex: 1 0 auto;
  }

  .topbar {
    height: 54px;
  }
}
</style>
