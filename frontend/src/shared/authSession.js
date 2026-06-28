export function shouldRefreshAccess(expiresAtValue, hasAccessToken, now = Date.now()) {
  const expiresAt = Date.parse(expiresAtValue || '')
  return !hasAccessToken || !expiresAt || expiresAt - now < 60_000
}
