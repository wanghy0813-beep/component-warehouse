const recentEvents = new Map()

export function trackUsage(sendEvent, event, payload = {}) {
  if (typeof sendEvent !== 'function' || !event) return
  const body = {
    event,
    page: payload.page || window.location.pathname,
    target_type: payload.target_type || payload.targetType || null,
    target_id: payload.target_id ?? payload.targetId ?? null,
    entry: payload.entry || null,
    detail: payload.detail || {},
    viewport_width: window.innerWidth || 0,
    viewport_height: window.innerHeight || 0
  }
  const key = `${body.event}|${body.page}|${body.entry || ''}|${body.target_type || ''}|${body.target_id || ''}`
  const now = Date.now()
  if (now - (recentEvents.get(key) || 0) < 2500) return
  recentEvents.set(key, now)
  window.setTimeout(() => {
    sendEvent(body).catch(() => {
      // Usage tracking must never interrupt the main workflow.
    })
  }, 0)
}
