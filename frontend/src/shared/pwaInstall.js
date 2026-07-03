import { computed, ref } from 'vue'

const deferredPrompt = ref(null)
const installed = ref(false)
let initialized = false

function isStandaloneDisplay() {
  if (typeof window === 'undefined') return false
  return window.matchMedia?.('(display-mode: standalone)')?.matches || window.navigator?.standalone === true
}

export const canInstallPwa = computed(() => Boolean(deferredPrompt.value) && !installed.value)
export const hasNativeInstallPrompt = computed(() => Boolean(deferredPrompt.value) && !installed.value)
export const isPwaInstalled = computed(() => installed.value)
export const canShowPwaInstall = computed(() => !installed.value)

export function setupPwaInstallPrompt() {
  if (typeof window === 'undefined' || initialized) return
  initialized = true
  installed.value = isStandaloneDisplay()

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault()
    if (!installed.value) deferredPrompt.value = event
  })

  window.addEventListener('appinstalled', () => {
    installed.value = true
    deferredPrompt.value = null
  })

  window.matchMedia?.('(display-mode: standalone)')?.addEventListener?.('change', (event) => {
    installed.value = Boolean(event.matches)
    if (installed.value) deferredPrompt.value = null
  })
}

export async function requestPwaInstall() {
  const prompt = deferredPrompt.value
  if (installed.value) return { outcome: 'installed' }
  if (!prompt) return { outcome: 'manual' }
  deferredPrompt.value = null
  await prompt.prompt()
  const choice = await prompt.userChoice
  if (choice?.outcome === 'accepted') installed.value = true
  return choice || { outcome: 'dismissed' }
}
