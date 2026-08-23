export function shortMonthDay(value) {
  if (!value) return '—'
  const dateValue = String(value).slice(0, 10)
  const [, month = '', day = ''] = dateValue.split('-')
  return month && day ? `${month}/${day}` : dateValue
}

export function isoWeekLabel(value) {
  if (!value) return ''
  const [year, month, day] = String(value).slice(0, 10).split('-').map(Number)
  if (!year || !month || !day) return ''
  const target = new Date(Date.UTC(year, month - 1, day))
  const weekday = target.getUTCDay() || 7
  target.setUTCDate(target.getUTCDate() + 4 - weekday)
  const isoYear = target.getUTCFullYear()
  const yearStart = new Date(Date.UTC(isoYear, 0, 1))
  const week = Math.ceil((((target - yearStart) / 86400000) + 1) / 7)
  return `${isoYear}W${String(week).padStart(2, '0')}`
}

export function weekBadge(value) {
  return value ? `（${isoWeekLabel(value)}）` : '（待填写）'
}
