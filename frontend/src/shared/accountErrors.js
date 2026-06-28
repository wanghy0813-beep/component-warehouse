export function isAccountServiceUnavailable(error) {
  const status = Number(error?.response?.status || 0)
  return [502, 503, 504].includes(status)
    || error?.code === 'ECONNABORTED'
    || error?.code === 'ERR_NETWORK'
    || (!error?.response && Boolean(error?.request))
}

export function accountErrorMessage(error, fallback = '账号操作失败，请稍后重试') {
  const status = Number(error?.response?.status || 0)
  const apiMessage = error?.response?.data?.error?.message
    || error?.response?.data?.detail
  if (typeof apiMessage === 'string' && apiMessage.trim()) return apiMessage.trim()
  if ([502, 503, 504].includes(status)) {
    return `统一账号服务暂时不可用（HTTP ${status}），请稍后重试`
  }
  if (error?.code === 'ECONNABORTED') return '统一账号服务响应超时，请稍后重试'
  if (error?.code === 'ERR_NETWORK' || (!error?.response && error?.request)) {
    return '无法连接统一账号服务，请检查网络后重试'
  }
  if (status >= 500) return `统一账号服务异常（HTTP ${status}），请稍后重试`
  return error?.message || fallback
}

export function createMessageDeduper(windowMs = 2500) {
  let lastMessage = ''
  let lastAt = 0
  return (message, now = Date.now()) => {
    if (message === lastMessage && now - lastAt < windowMs) return false
    lastMessage = message
    lastAt = now
    return true
  }
}
