import { reactive } from 'vue'

export const teamState = reactive({
  user: null,
  authDegraded: false,
  serviceUnavailable: false,
  networkOnline: navigator.onLine,
  offlineReadonly: !navigator.onLine,
  activeLibrary: null
})

export function setNetworkOnline(online) {
  teamState.networkOnline = online
  teamState.offlineReadonly = !online || teamState.serviceUnavailable
}

export function setSession(data) {
  teamState.user = data?.user || null
  teamState.authDegraded = Boolean(data?.auth_degraded)
  teamState.serviceUnavailable = false
  teamState.offlineReadonly = !navigator.onLine
}

export function markServiceUnavailable() {
  teamState.serviceUnavailable = true
  teamState.offlineReadonly = true
}

export function markServiceAvailable() {
  teamState.serviceUnavailable = false
  teamState.offlineReadonly = !navigator.onLine
}
