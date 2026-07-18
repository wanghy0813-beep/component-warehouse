<template>
  <el-config-provider>
    <div v-if="checking" class="boot notranslate" lang="zh-CN" translate="no">正在加载...</div>
    <div v-else-if="isPublicRoute" class="standalone-shell notranslate" lang="zh-CN" translate="no">
      <router-view />
      <app-footer />
    </div>
    <div v-else-if="needsLogin" class="standalone-shell notranslate" lang="zh-CN" translate="no">
      <auth-panel
        class="standalone-auth"
        :eyebrow="BRAND_NAME"
        title="个人版"
        subtitle="个人器件库存、项目 BOM 与 AI 工程知识"
        @authenticated="handleAuthenticated"
      />
      <app-footer />
    </div>
    <div v-else class="personal-app notranslate" lang="zh-CN" translate="no">
      <header class="personal-header">
        <router-link class="personal-brand" to="/">
          <img class="brand-icon" :src="appIcon" alt="" />
          <img v-if="BRAND_SHOW_LOGO" :src="logo" :alt="BRAND_SHORT" />
          <span><strong>{{ BRAND_NAME }}</strong><small>个人版</small></span>
        </router-link>
        <nav class="personal-desktop-nav" aria-label="个人版主导航">
          <router-link to="/" @click="trackNav('dashboard')"><DataBoard />仪表盘</router-link>
          <router-link to="/components" @click="trackNav('components')"><Box />元器件</router-link>
          <router-link to="/coverage" @click="trackNav('coverage')"><Monitor />覆盖图</router-link>
          <router-link to="/projects" @click="trackNav('projects')"><Files />项目</router-link>
          <router-link v-if="FEATURE_EDA_ENABLED" to="/eda" @click="trackNav('eda')"><Cpu />EDA 库</router-link>
          <router-link to="/about" @click="trackNav('management')"><InfoFilled />管理</router-link>
        </nav>
        <div class="personal-header-actions">
          <account-popover
            v-if="authRequired"
            :user="currentUser"
            @logout="handleLogout"
            @user-updated="handleProfileUpdated"
          />
        </div>
      </header>

      <main class="personal-main">
        <router-view />
        <app-footer />
      </main>

      <nav class="personal-mobile-nav" aria-label="个人版移动导航">
        <router-link to="/" @click="trackNav('mobile_dashboard')"><DataBoard />仪表盘</router-link>
        <router-link to="/components" @click="trackNav('mobile_components')"><Box />元器件</router-link>
        <router-link to="/projects" @click="trackNav('mobile_projects')"><Files />项目</router-link>
        <router-link v-if="FEATURE_EDA_ENABLED" to="/eda" @click="trackNav('mobile_eda')"><Cpu />EDA</router-link>
        <router-link to="/about" @click="trackNav('mobile_management')"><InfoFilled />管理</router-link>
      </nav>
      <back-to-top @click="trackBackToTop" />
    </div>
  </el-config-provider>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from '../shared/elementApi'
import { useRoute, useRouter } from 'vue-router'
import { Box, Cpu, DataBoard, Files, InfoFilled, Monitor } from '@element-plus/icons-vue'
import logo from '../assets/brand-logo.png'
import appIcon from '../assets/generated/cw-app-icon.png'
import { authConfig, getCurrentUser, recordUsageEvent } from '../api/client'
import { getAuthToken, getStoredUser, logoutAuthSession, rememberAuth, setupAuthActivityTracking } from '../api/authSessionApi'
import { BRAND_NAME, BRAND_SHORT, BRAND_SHOW_LOGO } from '../shared/branding'
import { FEATURE_EDA_ENABLED } from '../shared/features'
import AuthPanel from '../components/AuthPanel.vue'
import AccountPopover from '../shared/components/AccountPopover.vue'
import AppFooter from '../shared/components/AppFooter.vue'
import BackToTop from '../shared/components/BackToTop.vue'
import { setupPwaInstallPrompt } from '../shared/pwaInstall'
import { trackUsage } from '../shared/usageTracker'

const route = useRoute()
const router = useRouter()
const checking = ref(true)
const authRequired = ref(true)
const accessToken = ref(getAuthToken())
const currentUser = ref(getStoredUser())
const sessionVerified = ref(false)
localStorage.removeItem('personal_sidebar_collapsed')
localStorage.removeItem('cw_sidebar_collapsed')

const isPublicRoute = computed(() => route.path.startsWith('/public/') || route.name === 'personal-scan' || route.name === 'auth-callback')
const needsLogin = computed(() => authRequired.value && (!accessToken.value || !sessionVerified.value))
onMounted(async () => {
  setupPwaInstallPrompt()
  setupAuthActivityTracking()
  window.addEventListener('cw-auth-cleared', handleAuthCleared)
  window.addEventListener('cw-profile-updated', handleProfileEvent)
  window.addEventListener('cw-native-auth-session', handleNativeAuthSession)
  try {
    const config = await authConfig()
    authRequired.value = config.auth_required
    if (authRequired.value && accessToken.value) {
      await refreshCurrentUser()
    } else if (!authRequired.value) {
      sessionVerified.value = true
    }
  } catch (error) {
    authRequired.value = true
    sessionVerified.value = false
    ElMessage.error('无法验证登录状态，请联网后重试')
  } finally {
    checking.value = false
  }
})

watch(
  () => route.fullPath,
  () => {
    if (!needsLogin.value && !isPublicRoute.value) {
      trackUsage(recordUsageEvent, 'ui.page.view', { entry: 'personal-router' })
    }
  },
  { immediate: false }
)

function trackNav(entry) {
  trackUsage(recordUsageEvent, 'ui.nav.click', { entry })
}

function trackBackToTop() {
  trackUsage(recordUsageEvent, 'ui.back_to_top.click', { entry: 'personal-app' })
}

onBeforeUnmount(() => {
  window.removeEventListener('cw-auth-cleared', handleAuthCleared)
  window.removeEventListener('cw-profile-updated', handleProfileEvent)
  window.removeEventListener('cw-native-auth-session', handleNativeAuthSession)
})

function handleAuthCleared() {
  accessToken.value = ''
  currentUser.value = null
  sessionVerified.value = false
}

function handleProfileUpdated(user) {
  currentUser.value = { ...currentUser.value, ...user }
}

function handleProfileEvent(event) {
  if (event.detail) handleProfileUpdated(event.detail)
}

async function handleNativeAuthSession(event) {
  const session = rememberAuth(event.detail || {})
  if (!session.token) return
  await handleAuthenticated(session)
}

async function handleAuthenticated(data) {
  accessToken.value = data.token
  currentUser.value = data.user || null
  checking.value = true
  await refreshCurrentUser()
  checking.value = false
  if (!isPublicRoute.value && route.path !== '/') router.replace('/')
}

async function refreshCurrentUser() {
  try {
    const data = await getCurrentUser()
    currentUser.value = data.user || null
    sessionVerified.value = Boolean(currentUser.value)
    if (currentUser.value) {
      localStorage.setItem('cw_legacy_user', JSON.stringify(currentUser.value))
    }
  } catch (error) {
    sessionVerified.value = false
    accessToken.value = ''
    currentUser.value = null
  }
}

async function handleLogout() {
  await logoutAuthSession()
  accessToken.value = ''
  currentUser.value = null
  sessionVerified.value = false
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

.login-page {
  background: linear-gradient(135deg, rgba(248, 250, 252, 0.98), rgba(255, 255, 255, 0.98));
}

.login-shell {
  width: min(920px, calc(100vw - 32px));
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 18px;
  align-items: stretch;
}

.login-intro,
.login-card {
  border: 1px solid var(--cw-border);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: var(--cw-shadow);
}

.login-intro {
  padding: 36px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.login-mark {
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  margin-bottom: 22px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--cw-accent) 12%, transparent);
  color: var(--cw-accent);
}

.login-intro h1 {
  margin: 0;
  font-size: clamp(34px, 5vw, 56px);
  line-height: 1;
  letter-spacing: 0;
}

.login-intro p {
  max-width: 420px;
  margin: 18px 0 0;
  color: var(--cw-muted);
  font-size: 16px;
  line-height: 1.75;
}

.login-notes {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 32px;
}

.login-notes span {
  padding: 8px 10px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 13px;
  font-weight: 700;
}

.login-card {
  padding: 10px;
}

.login-card-head {
  margin-bottom: 18px;
}

.login-card-head strong,
.login-card-head small {
  display: block;
}

.login-card-head strong {
  font-size: 24px;
}

.login-card-head small {
  margin-top: 6px;
  color: var(--cw-muted);
}

.login-alert {
  margin: 16px 0;
}

.login-button {
  width: 100%;
  height: 44px;
  border-radius: 16px;
}

.auth-tabs {
  margin-top: -6px;
}

.code-button {
  width: 100%;
  margin-bottom: 16px;
}

@media (max-width: 760px) {
  .login-shell {
    grid-template-columns: 1fr;
  }

  .login-intro {
    padding: 24px;
  }
}

.personal-app {
  min-height: 100vh;
  background: var(--cw-bg);
}

.standalone-shell,
.standalone-auth {
  min-height: 100vh;
  min-height: 100dvh;
  background: var(--cw-bg);
}

.standalone-shell {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
}

.standalone-shell > :first-child {
  min-height: 0;
}

.personal-header {
  position: sticky;
  top: 0;
  z-index: 20;
  min-height: 66px;
  display: grid;
  grid-template-columns: minmax(230px, auto) minmax(420px, 1fr) auto;
  gap: 20px;
  align-items: center;
  padding: 0 max(20px, calc((100vw - 1280px) / 2));
  border-bottom: 1px solid var(--cw-border);
  background: rgba(255, 255, 255, .94);
  backdrop-filter: blur(18px);
}

.personal-brand {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  color: inherit;
  text-decoration: none;
}

.personal-brand img {
  width: 104px;
  height: 44px;
  flex: 0 0 auto;
  object-fit: contain;
}

.personal-brand .brand-icon {
  width: 36px;
  height: 36px;
  border-radius: 9px;
}

.personal-brand span {
  min-width: 0;
  display: grid;
  gap: 1px;
}

.personal-brand strong {
  overflow: hidden;
  color: #9a3412;
  font-size: 15px;
  letter-spacing: .03em;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.personal-brand small {
  color: var(--cw-muted);
  font-size: 12px;
  line-height: 1.25;
}

.personal-desktop-nav {
  min-width: 0;
  display: flex;
  justify-content: center;
  gap: 6px;
}

.personal-desktop-nav a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 13px;
  border-radius: var(--cw-radius-control);
  color: #506866;
  text-decoration: none;
  white-space: nowrap;
}

.personal-desktop-nav svg {
  width: 18px;
  height: 18px;
}

.personal-desktop-nav a.router-link-exact-active {
  color: #c2410c;
  background: #fff7ed;
  font-weight: 700;
}

.personal-header-actions {
  min-width: 0;
  display: flex;
  justify-content: flex-end;
}

.personal-main {
  width: min(1560px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 18px 0 40px;
}

.personal-mobile-nav {
  display: none;
}

@media (max-width: 1040px) {
  .personal-header {
    grid-template-columns: auto 1fr auto;
    gap: 12px;
  }

  .personal-brand span {
    display: none;
  }

  .personal-desktop-nav a {
    padding-inline: 10px;
  }
}

@media (max-width: 760px) {
  .personal-header {
    min-height: 58px;
    grid-template-columns: 1fr auto;
    padding: 0 12px;
  }

  .personal-brand img {
    width: 88px;
    height: 38px;
  }

  .personal-brand .brand-icon {
    width: 34px;
    height: 34px;
  }

  .personal-desktop-nav {
    display: none;
  }

  .personal-main {
    width: min(100% - 20px, 1280px);
    padding: 14px 0 104px;
  }

  .personal-mobile-nav {
    position: fixed;
    left: max(10px, env(safe-area-inset-left));
    right: max(10px, env(safe-area-inset-right));
    bottom: calc(8px + env(safe-area-inset-bottom));
    z-index: 30;
    display: flex;
    justify-content: space-between;
    gap: 4px;
    width: min(100% - 20px, 520px);
    margin: 0 auto;
    padding: 6px;
    border: 1px solid rgba(226, 232, 240, .92);
    border-radius: 22px;
    background: rgba(255, 255, 255, .94);
    box-shadow: 0 10px 28px rgba(15, 23, 42, .14);
    backdrop-filter: blur(14px);
  }

  .personal-mobile-nav a {
    min-width: 0;
    flex: 1 1 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    min-height: 52px;
    padding: 6px 2px;
    border-radius: 16px;
    overflow: hidden;
    color: #71817f;
    font-size: 11px;
    line-height: 1.2;
    text-decoration: none;
    text-overflow: ellipsis;
    white-space: nowrap;
    transition: color .18s ease, background-color .18s ease, transform .18s ease;
  }

  .personal-mobile-nav svg {
    width: 21px;
    height: 21px;
  }

  .personal-mobile-nav a.router-link-exact-active {
    background: linear-gradient(180deg, #fff7ed, #ffedd5);
    color: #c2410c;
    font-weight: 700;
    box-shadow: inset 0 0 0 1px rgba(251, 146, 60, .22);
  }

  .personal-mobile-nav a:active {
    transform: translateY(1px) scale(.98);
  }
}

:global(.cw-app-embedded) .personal-header,
:global(.cw-app-embedded) .personal-mobile-nav {
  display: none;
}

:global(.cw-app-embedded) .personal-main {
  width: 100%;
  padding: max(10px, env(safe-area-inset-top)) 10px max(12px, env(safe-area-inset-bottom));
}
</style>
