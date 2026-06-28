import axios from 'axios'
import { shouldRefreshAccess } from '../shared/authSession'
import { accountErrorMessage, isAccountServiceUnavailable } from '../shared/accountErrors'
import { API_BASE } from '../shared/appPaths'

export const ACCOUNT_BASE =
  import.meta.env.VITE_ACCOUNT_BASE || ''
export const ACCOUNT_WEB_CLIENT_ID =
  import.meta.env.VITE_ACCOUNT_WEB_CLIENT_ID || 'componentwarehouse-web'

const ACCESS_KEY = 'cw_auth_access_token'
const REFRESH_KEY = 'cw_auth_refresh_token'
const ACCESS_EXPIRES_KEY = 'cw_auth_access_expires_at'
const USER_KEY = 'cw_auth_user'
let refreshPromise = null
let authRuntime = {
  accountMode: 'account-v1',
  providerLabel: 'Account V1',
  accountBase: ACCOUNT_BASE,
  webClientId: ACCOUNT_WEB_CLIENT_ID,
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

function normalizeUser(user) {
  if (!user) return null
  return {
    ...user,
    id: user.accountId,
    nickname: user.displayName || '',
    avatar_url: user.avatarUrl || ''
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
  localStorage.setItem(ACCESS_KEY, session.accessToken)
  localStorage.setItem(REFRESH_KEY, session.refreshToken)
  localStorage.setItem(ACCESS_EXPIRES_KEY, session.accessExpiresAt || '')
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
  for (const key of [ACCESS_KEY, REFRESH_KEY, ACCESS_EXPIRES_KEY, USER_KEY]) {
    localStorage.removeItem(key)
  }
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
    const client = isLocalPasswordAuth() ? localAuthApi : authApi
    const url = isLocalPasswordAuth() ? '/auth/local/token/refresh' : '/token/refresh'
    refreshPromise = client.post(url, { refreshToken })
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
  if (accessNeedsRefresh()) await refreshAuthSession()
  return getAuthToken()
}

export async function fetchCaptcha() {
  if (isLocalPasswordAuth()) return { captchaId: '', imageDataUrl: '' }
  const { data } = await authApi.get('/captcha')
  return data
}

export async function checkAccountHealth() {
  if (isLocalPasswordAuth()) {
    const { data } = await localAuthApi.get('/auth/config', { timeout: 8000 })
    return data
  }
  const { data } = await authApi.get('/health', { timeout: 8000 })
  return data
}

export async function sendSmsCode(payload) {
  if (isLocalPasswordAuth()) throw new Error('本地账号模式不需要短信验证码')
  const { data } = await authApi.post('/sms/send', payload)
  return data
}

export async function loginWithSms(phone, code) {
  const { data } = await authApi.post('/login/sms', { phone, code })
  return rememberAuth(data)
}

export async function loginWithPassword(phone, password) {
  if (isLocalPasswordAuth()) {
    const { data } = await localAuthApi.post('/auth/local/login', { username: phone, password })
    return rememberAuth(data)
  }
  const { data } = await authApi.post('/login/password', { phone, password })
  return rememberAuth(data)
}

export async function registerWithPassword(payload) {
  if (isLocalPasswordAuth()) {
    const { data } = await localAuthApi.post('/auth/local/register', {
      phone: payload.phone,
      nickname: payload.nickname,
      password: payload.password
    })
    return rememberAuth(data)
  }
  const { data } = await authApi.post('/register', {
    phone: payload.phone,
    code: payload.code,
    displayName: payload.nickname,
    password: payload.password
  })
  return rememberAuth(data)
}

export async function resetAuthPassword(payload) {
  if (isLocalPasswordAuth()) throw new Error('本地账号模式请登录后在账号设置中修改密码')
  const { data } = await authApi.post('/password/reset', {
    phone: payload.phone,
    code: payload.code,
    newPassword: payload.newPassword
  })
  return data
}

async function accountRequest(method, url, data) {
  const token = await getValidAuthToken()
  if (isLocalPasswordAuth()) {
    if (method === 'get' && url === '/me') {
      return localAuthApi.get('/auth/me', { headers: { Authorization: `Bearer ${token}` } }).then((response) => response.data)
    }
    if (method === 'patch' && url === '/me') {
      return localAuthApi.patch('/auth/local/me', data, { headers: { Authorization: `Bearer ${token}` } }).then((response) => response.data)
    }
    if (method === 'post' && url === '/password/change') {
      return localAuthApi.post('/auth/local/password/change', data, { headers: { Authorization: `Bearer ${token}` } }).then((response) => response.data)
    }
    if (method === 'get' && url === '/sessions') {
      return { sessions: [{ sessionId: 'local-current', current: true, clients: ['本地账号'], createdAt: '' }] }
    }
    throw new Error('本地账号模式暂不支持此账号设置操作')
  }
  return authApi.request({
    method,
    url,
    data,
    headers: { Authorization: `Bearer ${token}` }
  }).then((response) => response.data)
}

export async function fetchAccountProfile() {
  const data = await accountRequest('get', '/me')
  return rememberUser(data.user)
}

export async function updateAccountProfile(payload) {
  const data = await accountRequest('patch', '/me', {
    displayName: payload.displayName,
    avatarUrl: payload.avatarUrl || ''
  })
  return rememberUser(data.user)
}

export async function changeAccountPassword(payload) {
  return accountRequest('post', '/password/change', payload)
}

export async function changeAccountPhone(payload) {
  const data = await accountRequest('post', '/phone/change', payload)
  return rememberUser(data.user)
}

export async function listAccountSessions() {
  return accountRequest('get', '/sessions')
}

export async function logoutAuthSession() {
  const token = getAuthToken()
  try {
    if (token && isLocalPasswordAuth()) {
      await localAuthApi.post('/auth/local/logout', null, {
        headers: { Authorization: `Bearer ${token}` }
      })
    } else if (token) {
      await authApi.post('/logout', null, {
        headers: { Authorization: `Bearer ${token}` }
      })
    }
  } finally {
    clearStoredAuth()
  }
}

export { accountErrorMessage, isAccountServiceUnavailable }
