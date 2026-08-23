export const IS_DESKTOP = import.meta.env.VITE_DESKTOP === '1'

let contextPromise = null

function invoke(name, payload = {}) {
  const command = window.__TAURI__?.core?.invoke
  if (!command) throw new Error('Windows 桌面桥未就绪')
  return command(name, payload)
}

export async function desktopContext() {
  if (!IS_DESKTOP) return null
  if (!contextPromise) contextPromise = invoke('desktop_context')
  return contextPromise
}

export async function desktopRequestConfig() {
  const context = await desktopContext()
  return {
    baseURL: context.apiBase,
    headers: { 'X-WXY-Desktop-Session': context.sessionKey }
  }
}

export const startDesktopAuthorization = () => invoke('start_device_authorization')
export const pollDesktopAuthorization = () => invoke('poll_device_authorization')
export const openDesktopUrl = (url) => invoke('open_external_url', { url })
export const syncDesktopNow = () => invoke('desktop_sync_now')
export const getDesktopConflicts = () => invoke('desktop_conflicts')
export const resolveDesktopConflict = (conflictId, resolution) => invoke('resolve_desktop_conflict', { conflictId, resolution })
