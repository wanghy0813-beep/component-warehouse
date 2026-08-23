export const IS_DESKTOP_PATHS = (
  import.meta.env?.VITE_DESKTOP === '1'
  || (typeof process !== 'undefined' && process.env?.VITE_DESKTOP === '1')
)
export const APP_ROOT = '/hardware'
export const SERVICE_ROOT = APP_ROOT
export const PERSONAL_BASE = `${APP_ROOT}/`
export const TEAM_BASE = '/component-warehouse/team/'
export const API_BASE = IS_DESKTOP_PATHS ? 'http://127.0.0.1:18764/api' : `${SERVICE_ROOT}/api`
export const HEALTH_URL = IS_DESKTOP_PATHS ? 'http://127.0.0.1:18764/health' : `${SERVICE_ROOT}/health`
