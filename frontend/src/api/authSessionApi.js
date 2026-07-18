import axios from 'axios'
import { shouldRefreshAccess } from '../shared/authSession'
import { accountErrorMessage, isAccountServiceUnavailable } from '../shared/accountErrors'
import { API_BASE } from '../shared/appPaths'

export const ACCOUNT_BASE =
  import.meta.env.VITE_ACCOUNT_BASE || ''
export const ACCOUNT_WEB_CLIENT_ID =
  import.meta.env.VITE_ACCOUNT_WEB_CLIENT_ID || 'componentwarehouse-web'
export const ACCOUNT_PROFILE_PATH = '/account/profile'

const ACCESS_KEY = 'cw_auth_access_token'
const REFRESH_KEY = 'cw_auth_refresh_token'
const ACCESS_EXPIRES_KEY = 'cw_auth_access_expires_at'
const USER_KEY = 'cw_auth_user'
const LAST_ACTIVE_KEY = 'cw_auth_last_active_at'
const SESSION_STARTED_KEY = 'cw_auth_session_started_at'
const SSO_STATE_KEY = 'cw_sso_state'
const SSO_VERIFIER_KEY = 'cw_sso_code_verifier'
const SSO_RETURN_KEY = 'cw_sso_return_to'
const SSO_REDIRECT_KEY = 'cw_sso_redirect_uri'
const IDLE_TIMEOUT_MS = Math.max(5, Number(import.meta.env.VITE_AUTH_IDLE_TIMEOUT_MINUTES || 30)) * 60 * 1000
const MAX_SESSION_MS = Math.max(1, Number(import.meta.env.VITE_AUTH_MAX_SESSION_HOURS || 168)) * 60 * 60 * 1000
let refreshPromise = null
let activityTrackingStarted = false
let activityTimer = null
let authRuntime = {
  accountMode: 'account-v1',
  providerLabel: 'Account V1',
  accountBase: ACCOUNT_BASE,
  webClientId: ACCOUNT_WEB_CLIENT_ID,
  ssoEnabled: false,
  ssoAuthorizeUrl: '',
  ssoRedirectUri: '',
  authRequired: true,
  registrationEnabled: true
}

for (const legacyKey of [
  'cw_legacy_token', 'cw_token', 'contest_token',
  'cw_legacy_user', 'cw_user', 'contest_user'
]) {
  localStorage.removeItem(legacyKey)
}

const legacyClientIdHeader = ['X', ['W', 'XY'].join(''), 'Client', 'Id'].join('-')

const authApi = axios.create({
  baseURL: ACCOUNT_BASE,
  timeout: 20000,
  headers: {
    'X-Account-Client-Id': ACCOUNT_WEB_CLIENT_ID,
    [legacyClientIdHeader]: ACCOUNT_WEB_CLIENT_ID
  }
})

const localAuthApi = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || API_BASE,
  timeout: 20000
})

export function setAuthRuntimeConfig(config = {}) {
  authRuntime = {
    ...authRuntime,
    accountMode: config.account_mode || authRuntime.accountMode,
    providerLabel: config.provider_label || authRuntime.providerLabel,
    accountBase: config.auth_base_url || authRuntime.accountBase,
    webClientId: config.web_client_id || authRuntime.webClientId,
    ssoEnabled: Boolean(config.sso_enabled),
    ssoAuthorizeUrl: config.sso_authorize_url || authRuntime.ssoAuthorizeUrl,
    ssoRedirectUri: config.sso_redirect_uri || authRuntime.ssoRedirectUri,
    authRequired: config.auth_required !== false,
    registrationEnabled: config.registration_enabled !== false
  }
  authApi.defaults.baseURL = authRuntime.accountBase
  authApi.defaults.headers.common['X-Account-Client-Id'] = authRuntime.webClientId
  authApi.defaults.headers.common[legacyClientIdHeader] = authRuntime.webClientId
  return authRuntime
}

export function getAuthRuntimeConfig() {
  return authRuntime
}

export function isLocalPasswordAuth() {
  return authRuntime.accountMode === 'local-password'
}

export function accountProfileUrl() {
  if (typeof window === 'undefined') return ACCOUNT_PROFILE_PATH
  return new URL(ACCOUNT_PROFILE_PATH, window.location.origin).href
}

export function openAccountProfile() {
  if (typeof window === 'undefined') return
  window.location.assign(accountProfileUrl())
}

export function resolveAccountAvatarUrl(value = '') {
  const raw = String(value || '').trim()
  if (!raw) return ''
  if (/^(https?:|data:|blob:)/i.test(raw)) return raw
  const fallbackBase = typeof window === 'undefined' ? 'https://wxylab.ltd' : window.location.origin
  const accountBase = authRuntime.accountBase || ACCOUNT_BASE || fallbackBase
  try {
    return new URL(raw, accountBase.endsWith('/') ? accountBase : `${accountBase}/`).href
  } catch {
    return raw
  }
}

async function ensureAuthRuntimeReady() {
  if (authRuntime.accountBase) return authRuntime
  const { data } = await localAuthApi.get('/auth/config', { timeout: 8000 })
  return setAuthRuntimeConfig(data)
}

function nowMs() {
  return Date.now()
}

function randomUrlSafe(bytes = 32) {
  const values = new Uint8Array(bytes)
  crypto.getRandomValues(values)
  return btoa(String.fromCharCode(...values)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

async function sha256UrlSafe(value) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function fallbackSsoRedirectUri() {
  if (typeof window === 'undefined') return ''
  return new URL('/component-warehouse/personal/auth/callback', window.location.origin).href
}

function clearPendingSso() {
  for (const key of [SSO_STATE_KEY, SSO_VERIFIER_KEY, SSO_RETURN_KEY, SSO_REDIRECT_KEY]) {
    sessionStorage.removeItem(key)
  }
}

function numericStorageValue(key) {
  return Number(localStorage.getItem(key) || 0)
}

function markAuthActivity() {
  if (getAuthToken()) localStorage.setItem(LAST_ACTIVE_KEY, String(nowMs()))
}

function sessionTimedOut() {
  if (!getAuthToken()) return false
  const now = nowMs()
  const lastActive = numericStorageValue(LAST_ACTIVE_KEY) || now
  const started = numericStorageValue(SESSION_STARTED_KEY) || now
  return now - lastActive > IDLE_TIMEOUT_MS || now - started > MAX_SESSION_MS
}

export function setupAuthActivityTracking() {
  if (typeof window === 'undefined' || activityTrackingStarted) return
  activityTrackingStarted = true
  const activityEvents = ['click', 'keydown', 'pointerdown', 'touchstart', 'scroll']
  for (const eventName of activityEvents) {
    window.addEventListener(eventName, markAuthActivity, { passive: true })
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') markAuthActivity()
  })
  activityTimer = window.setInterval(() => {
    if (sessionTimedOut()) clearStoredAuth()
  }, 60_000)
}

function normalizeUser(user) {
  if (!user) return null
  const avatarUrl = resolveAccountAvatarUrl(user.avatarUrl || user.avatar_url || '')
  return {
    ...user,
    id: user.accountId,
    nickname: user.displayName || '',
    avatarUrl,
    avatar_url: avatarUrl
  }
}

function normalizedSession(data) {
  const session = data?.session || {}
  return {
    ...data,
    token: session.accessToken || '',
    user: normalizeUser(data?.user)
  }
}

export function getAuthToken() {
  return localStorage.getItem(ACCESS_KEY) || ''
}

export function getStoredUser() {
  try {
    return normalizeUser(JSON.parse(localStorage.getItem(USER_KEY) || 'null'))
  } catch {
    return null
  }
}

export function rememberAuth(data) {
  const session = data?.session
  if (!session?.accessToken || !session?.refreshToken) return normalizedSession(data)
  const now = String(nowMs())
  localStorage.setItem(ACCESS_KEY, session.accessToken)
  localStorage.setItem(REFRESH_KEY, session.refreshToken)
  localStorage.setItem(ACCESS_EXPIRES_KEY, session.accessExpiresAt || '')
  localStorage.setItem(LAST_ACTIVE_KEY, now)
  localStorage.setItem(SESSION_STARTED_KEY, localStorage.getItem(SESSION_STARTED_KEY) || now)
  if (data.user) localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  window.dispatchEvent(new CustomEvent('cw-profile-updated', { detail: normalizeUser(data.user) }))
  return normalizedSession(data)
}

export function rememberUser(user) {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  const normalized = normalizeUser(user)
  window.dispatchEvent(new CustomEvent('cw-profile-updated', { detail: normalized }))
  return normalized
}

export function clearStoredAuth() {
  for (const key of [ACCESS_KEY, REFRESH_KEY, ACCESS_EXPIRES_KEY, USER_KEY, LAST_ACTIVE_KEY, SESSION_STARTED_KEY]) {
    localStorage.removeItem(key)
  }
  clearPendingSso()
  window.dispatchEvent(new CustomEvent('cw-auth-cleared'))
}

function accessNeedsRefresh() {
  return shouldRefreshAccess(
    localStorage.getItem(ACCESS_EXPIRES_KEY),
    Boolean(getAuthToken())
  )
}

export async function refreshAuthSession() {
  const refreshToken = localStorage.getItem(REFRESH_KEY)
  if (!refreshToken) {
    clearStoredAuth()
    throw new Error('登录已失效')
  }
  if (!refreshPromise) {
    refreshPromise = localAuthApi.post('/auth/account/token/refresh', { refreshToken })
      .then(({ data }) => rememberAuth(data))
      .catch((error) => {
        clearStoredAuth()
        throw error
      })
      .finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

export async function getValidAuthToken() {
  if (!getAuthToken() && !localStorage.getItem(REFRESH_KEY)) return ''
  if (sessionTimedOut()) {
    clearStoredAuth()
    return ''
  }
  if (accessNeedsRefresh()) await refreshAuthSession()
  return getAuthToken()
}

export async function checkAccountHealth() {
  await ensureAuthRuntimeReady()
  const { data } = await localAuthApi.get('/auth/account/health', { timeout: 8000 })
  return data
}

async function startLegacySsoLogin(returnTo = '') {
  const state = randomUrlSafe(24)
  const codeVerifier = randomUrlSafe(48)
  const codeChallenge = await sha256UrlSafe(codeVerifier)
  const redirectUri = authRuntime.ssoRedirectUri || fallbackSsoRedirectUri()
  sessionStorage.setItem(SSO_STATE_KEY, state)
  sessionStorage.setItem(SSO_VERIFIER_KEY, codeVerifier)
  sessionStorage.setItem(SSO_RETURN_KEY, returnTo || window.location.href)
  sessionStorage.setItem(SSO_REDIRECT_KEY, redirectUri)
  const target = new URL(authRuntime.ssoAuthorizeUrl)
  target.searchParams.set('client_id', authRuntime.webClientId)
  target.searchParams.set('redirect_uri', redirectUri)
  target.searchParams.set('state', state)
  target.searchParams.set('code_challenge', codeChallenge)
  target.searchParams.set('code_challenge_method', 'S256')
  window.location.assign(target.href)
}

export async function startSsoLogin(returnTo = '') {
  await ensureAuthRuntimeReady()
  if (!authRuntime.ssoEnabled || !authRuntime.ssoAuthorizeUrl) {
    throw new Error('统一账号 SSO 暂未配置')
  }
  const redirectUri = authRuntime.ssoRedirectUri || fallbackSsoRedirectUri()
  try {
    const { data } = await localAuthApi.post('/auth/account/sso/start', {
      returnTo: returnTo || window.location.href,
      redirectUri
    })
    sessionStorage.setItem(SSO_STATE_KEY, data.state || '')
    sessionStorage.setItem(SSO_RETURN_KEY, data.returnTo || returnTo || window.location.href)
    sessionStorage.setItem(SSO_REDIRECT_KEY, data.redirectUri || redirectUri)
    window.location.assign(data.authorizeUrl)
  } catch (error) {
    if (![404, 405].includes(error?.response?.status)) throw error
    await startLegacySsoLogin(returnTo)
  }
}

export async function finishSsoLogin(queryString = '') {
  await ensureAuthRuntimeReady()
  const params = new URLSearchParams(String(queryString || '').replace(/^\?/, ''))
  const code = params.get('code') || ''
  const state = params.get('state') || ''
  const expectedState = sessionStorage.getItem(SSO_STATE_KEY) || ''
  const codeVerifier = sessionStorage.getItem(SSO_VERIFIER_KEY) || ''
  const redirectUri = sessionStorage.getItem(SSO_REDIRECT_KEY) || authRuntime.ssoRedirectUri || fallbackSsoRedirectUri()
  const returnTo = sessionStorage.getItem(SSO_RETURN_KEY) || ''
  if (!code || !state || (expectedState && state !== expectedState)) {
    clearPendingSso()
    throw new Error('统一账号登录状态校验失败，请重新登录')
  }
  try {
    const payload = {
      code,
      state,
      redirectUri
    }
    if (codeVerifier) payload.codeVerifier = codeVerifier
    const { data } = await localAuthApi.post('/auth/account/sso/token', payload)
    return { session: rememberAuth(data), returnTo: data.returnTo || returnTo }
  } finally {
    clearPendingSso()
  }
}

async function accountRequest(method, url, data) {
  const token = await getValidAuthToken()
  await ensureAuthRuntimeReady()
  return authApi.request({
    method,
    url,
    data,
    headers: { Authorization: `Bearer ${token}` }
  }).then((response) => response.data)
}

export async function fetchAccountProfile() {
  const token = await getValidAuthToken()
  await ensureAuthRuntimeReady()
  let data
  try {
    data = await localAuthApi.get('/auth/account/me', {
      headers: { Authorization: `Bearer ${token}` }
    }).then((response) => response.data)
  } catch (error) {
    data = await accountRequest('get', '/me')
  }
  const user = data.user || data.account || data
  return rememberUser({
    ...user,
    avatarUrl: user?.avatarUrl || data.avatarUrl || ''
  })
}

export async function logoutAuthSession() {
  const token = getAuthToken()
  try {
    if (token) {
      await ensureAuthRuntimeReady()
      await localAuthApi.post('/auth/account/logout', null, {
        headers: { Authorization: `Bearer ${token}` }
      })
    }
  } finally {
    clearStoredAuth()
  }
}

export { accountErrorMessage, isAccountServiceUnavailable }
