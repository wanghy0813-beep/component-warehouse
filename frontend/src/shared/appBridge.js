import { API_BASE, PERSONAL_BASE, TEAM_BASE } from './appPaths'

const params = new URLSearchParams(window.location.search)
const userAgent = navigator.userAgent || ''
const legacyPrefix = ['W', 'XY'].join('')
const legacyNativeName = [legacyPrefix, 'LabNative'].join('')
const legacyBridgeName = [legacyPrefix, 'LabComponentWarehouse'].join('')
const legacyAppPattern = new RegExp([legacyPrefix, 'LAB[- /]App'].join(''), 'i')
const legacyWebkitHandler = ['w', 'xylab'].join('')

export const appBridgeContext = {
  protocolVersion: '1.0',
  embedded: (
    params.get('embed') === '1'
    || params.get('mode') === 'app'
    || legacyAppPattern.test(userAgent)
    || Boolean(window.ReactNativeWebView)
    || Boolean(window[legacyNativeName])
    || Boolean(window.webkit?.messageHandlers?.[legacyWebkitHandler])
  ),
  surface: '',
  apiBase: API_BASE,
  personalBase: PERSONAL_BASE,
  teamBase: TEAM_BASE
}

function nativeMessage(type, payload = {}) {
  const message = {
    source: 'component-warehouse-web',
    protocolVersion: appBridgeContext.protocolVersion,
    surface: appBridgeContext.surface,
    type,
    payload
  }
  const serialized = JSON.stringify(message)
  try {
    if (window.ReactNativeWebView?.postMessage) {
      window.ReactNativeWebView.postMessage(serialized)
      return true
    }
    if (window[legacyNativeName]?.postMessage) {
      window[legacyNativeName].postMessage(serialized)
      return true
    }
    if (window[legacyNativeName]?.onWebMessage) {
      window[legacyNativeName].onWebMessage(serialized)
      return true
    }
    if (window.webkit?.messageHandlers?.[legacyWebkitHandler]?.postMessage) {
      window.webkit.messageHandlers[legacyWebkitHandler].postMessage(message)
      return true
    }
    if (window.parent && window.parent !== window) {
      window.parent.postMessage(message, window.location.origin)
      return true
    }
  } catch {
    return false
  }
  return false
}

function dispatch(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

export function installAppBridge({ surface, router }) {
  appBridgeContext.surface = surface
  document.documentElement.classList.toggle('cw-app-embedded', appBridgeContext.embedded)
  document.body.classList.toggle('cw-app-embedded', appBridgeContext.embedded)

  const bridge = {
    protocolVersion: appBridgeContext.protocolVersion,
    getContext: () => ({
      ...appBridgeContext,
      path: router.currentRoute.value.fullPath
    }),
    navigate: (path) => router.push(String(path || '/')),
    openAccountSettings: () => dispatch('cw-open-account-settings'),
    receiveAuthSession: (session) => dispatch('cw-native-auth-session', session),
    receiveScan: (payload) => dispatch('cw-native-scan', {
      source: 'qr',
      ...(typeof payload === 'string' ? { value: payload } : payload)
    }),
    receiveNfc: (payload) => dispatch('cw-native-scan', {
      source: 'nfc',
      ...(typeof payload === 'string' ? { value: payload } : payload)
    }),
    requestScan: (options = {}) => nativeMessage('scan.request', options),
    requestNfc: (options = {}) => nativeMessage('nfc.request', options),
    notify: (type, payload = {}) => nativeMessage(type, payload)
  }

  window.ComponentWarehouseBridge = bridge
  window[legacyBridgeName] = bridge
  nativeMessage('web.ready', bridge.getContext())
  router.afterEach((to) => nativeMessage('navigation.changed', { path: to.fullPath }))
  return bridge
}
