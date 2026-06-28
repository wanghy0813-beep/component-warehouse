export const BRAND_NAME = import.meta.env.VITE_BRAND_NAME || 'Component Warehouse'
export const BRAND_SHORT = import.meta.env.VITE_BRAND_SHORT || BRAND_NAME
export const BRAND_PERSONAL_TITLE = import.meta.env.VITE_BRAND_PERSONAL_TITLE || `${BRAND_NAME} · Personal`
export const BRAND_TEAM_TITLE = import.meta.env.VITE_BRAND_TEAM_TITLE || `${BRAND_NAME} · Team`
export const BRAND_SHOW_LOGO = import.meta.env.VITE_BRAND_SHOW_LOGO === '1'
