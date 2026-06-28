<template>
  <el-config-provider>
    <div v-if="checking" class="team-boot">正在连接 {{ BRAND_NAME }}…</div>
    <div v-else-if="route.meta.publicJoin && !token" class="team-standalone-shell">
      <router-view @authenticated="handleAuthenticated" />
      <app-footer />
    </div>
    <div v-else-if="!token" class="team-standalone-shell">
      <auth-panel
        :eyebrow="BRAND_NAME"
        title="团队版"
        subtitle="团队器件、PCB、成员协作与操作记录"
        @authenticated="handleAuthenticated"
      />
      <app-footer />
    </div>
    <div v-else class="team-app">
      <header class="team-header">
        <router-link class="team-brand" to="/">
          <img v-if="BRAND_SHOW_LOGO" :src="logo" :alt="BRAND_SHORT" />
          <span><strong>{{ BRAND_NAME }}</strong><small>团队版</small></span>
        </router-link>
        <nav v-if="libraryId" class="desktop-nav">
          <router-link :to="libraryPath('components')" @click="trackTeamNav('components')">元器件</router-link>
          <router-link :to="libraryPath('pcbs')" @click="trackTeamNav('pcbs')">PCB</router-link>
          <router-link :to="libraryPath('projects')" @click="trackTeamNav('projects')">项目</router-link>
          <router-link v-if="FEATURE_EDA_ENABLED" :to="libraryPath('eda')" @click="trackTeamNav('eda')">EDA 库</router-link>
          <router-link :to="libraryPath('purchases')" @click="trackTeamNav('purchases')">采购</router-link>
          <router-link :to="libraryPath('risks')" @click="trackTeamNav('risks')">风险</router-link>
          <router-link :to="libraryPath('members')" @click="trackTeamNav('members')">成员</router-link>
          <router-link :to="libraryPath('logs')" @click="trackTeamNav('logs')">日志</router-link>
          <router-link :to="libraryPath('manual')" @click="trackTeamNav('manual')">手册</router-link>
        </nav>
        <div class="header-actions">
          <el-tag v-if="teamState.authDegraded && !teamState.offlineReadonly" type="warning">身份缓冲</el-tag>
          <el-tag v-if="teamState.offlineReadonly" type="danger">离线只读</el-tag>
          <account-popover
            :user="teamState.user"
            @logout="logout"
            @user-updated="handleProfileUpdated"
          />
        </div>
      </header>

      <main class="team-main">
        <router-view />
        <app-footer />
      </main>

      <nav v-if="libraryId" class="mobile-nav">
        <router-link :to="libraryPath('components')"><Box />元器件</router-link>
        <router-link :to="libraryPath('projects')"><Files />项目</router-link>
        <router-link v-if="FEATURE_EDA_ENABLED" :to="libraryPath('eda')"><Cpu />EDA</router-link>
        <router-link :to="libraryPath('members')"><UserFilled />成员</router-link>
        <router-link :to="libraryPath('risks')"><WarningFilled />风险</router-link>
      </nav>
      <back-to-top @click="trackTeamBackToTop" />
    </div>
  </el-config-provider>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from '../shared/elementApi'
import { useRoute, useRouter } from 'vue-router'
import { Box, Cpu, Files, UserFilled, WarningFilled } from '@element-plus/icons-vue'
import logo from '../assets/brand-logo.png'
import { BRAND_NAME, BRAND_SHORT, BRAND_SHOW_LOGO } from '../shared/branding'
import { FEATURE_EDA_ENABLED } from '../shared/features'
import AuthPanel from '../components/AuthPanel.vue'
import AccountPopover from '../shared/components/AccountPopover.vue'
import AppFooter from '../shared/components/AppFooter.vue'
import BackToTop from '../shared/components/BackToTop.vue'
import { authConfig } from '../api/client'
import { getAuthToken, getStoredUser, logoutAuthSession, rememberAuth } from '../api/authSessionApi'
import { clearAccountSnapshots } from './cache'
import { recordTeamUsageEvent, teamSession } from './api'
import { teamState, setNetworkOnline, setSession } from './store'
import { trackUsage } from '../shared/usageTracker'

const route = useRoute()
const router = useRouter()
const checking = ref(true)
const token = ref(getAuthToken())
const libraryId = computed(() => route.params.libraryId || '')

function libraryPath(page) {
  return `/library/${libraryId.value}/${page}`
}

async function loadSession() {
  if (!token.value) return
  try {
    const session = await teamSession()
    setSession(session)
    localStorage.setItem('cw_team_user', JSON.stringify(session.user || null))
  } catch (error) {
    if (error?.response?.status === 401) {
      token.value = ''
      setSession(null)
    } else if (!error?.response || error?.response?.status === 503) {
      let stored = null
      try {
        stored = JSON.parse(localStorage.getItem('cw_team_user') || 'null') || getStoredUser()
      } catch {
        stored = getStoredUser()
      }
      if (stored) {
        teamState.user = stored
        teamState.offlineReadonly = true
      } else {
        token.value = ''
        setSession(null)
      }
    } else {
      token.value = ''
      setSession(null)
      ElMessage.error('无法验证登录状态，请重新登录')
    }
  }
}

async function handleAuthenticated(data) {
  token.value = data.token
  await loadSession()
  if (route.meta.publicJoin) return
  router.replace('/')
}

async function logout() {
  const userId = teamState.user?.id
  await logoutAuthSession()
  if (userId) await clearAccountSnapshots(userId)
  token.value = ''
  setSession(null)
  localStorage.removeItem('cw_team_user')
  router.replace('/')
  ElMessage.success('已退出登录')
}

async function handleAuthCleared() {
  const userId = teamState.user?.id
  if (userId) await clearAccountSnapshots(userId)
  token.value = ''
  setSession(null)
  localStorage.removeItem('cw_team_user')
}

function handleProfileUpdated(user) {
  teamState.user = { ...teamState.user, ...user }
}

function handleProfileEvent(event) {
  if (event.detail) handleProfileUpdated(event.detail)
}

async function handleNativeAuthSession(event) {
  const session = rememberAuth(event.detail || {})
  if (!session.token) return
  await handleAuthenticated(session)
}

onMounted(async () => {
  window.addEventListener('online', () => setNetworkOnline(true))
  window.addEventListener('offline', () => setNetworkOnline(false))
  window.addEventListener('cw-auth-cleared', handleAuthCleared)
  window.addEventListener('cw-profile-updated', handleProfileEvent)
  window.addEventListener('cw-native-auth-session', handleNativeAuthSession)
  await authConfig()
  await loadSession()
  checking.value = false
})

watch(
  () => route.fullPath,
  () => {
    if (token.value && libraryId.value) {
      trackUsage((payload) => recordTeamUsageEvent(libraryId.value, payload), 'ui.page.view', { entry: 'team-router' })
    }
  }
)

function trackTeamNav(entry) {
  if (!libraryId.value) return
  trackUsage((payload) => recordTeamUsageEvent(libraryId.value, payload), 'ui.nav.click', { entry, target_type: 'team_library', target_id: libraryId.value })
}

function trackTeamBackToTop() {
  if (!libraryId.value) return
  trackUsage((payload) => recordTeamUsageEvent(libraryId.value, payload), 'ui.back_to_top.click', { entry: 'team-app', target_type: 'team_library', target_id: libraryId.value })
}

onBeforeUnmount(() => {
  window.removeEventListener('cw-auth-cleared', handleAuthCleared)
  window.removeEventListener('cw-profile-updated', handleProfileEvent)
  window.removeEventListener('cw-native-auth-session', handleNativeAuthSession)
})
</script>
