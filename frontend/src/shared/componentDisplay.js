export function comparableDisplayText(value) {
  return String(value || '')
    .trim()
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '')
}

export function uniqueDisplayParts(values, primary = '') {
  const seen = []
  const primaryKey = comparableDisplayText(primary)
  if (primaryKey) seen.push(primaryKey)
  const result = []
  for (const raw of values || []) {
    const value = String(raw || '').trim()
    const key = comparableDisplayText(value)
    if (!key) continue
    if (seen.some((old) => old === key || old.includes(key) || key.includes(old))) continue
    result.push(value)
    seen.push(key)
  }
  return result
}

const PASSIVE_VALUE_CATEGORIES = new Set(['电阻', '电容', '电感'])
const PASSIVE_SPEC_NAMES = {
  电阻: ['阻值', '电阻值', '标称阻值'],
  电容: ['容值', '容量', '标称容值', '标称容量', '电容值'],
  电感: ['感值', '电感值', '标称感值', '阻抗', '标称阻抗', '磁珠阻抗']
}

function categoryName(item) {
  return String(item?.category?.name || item?.category || '').trim()
}

function normalizeKey(value) {
  return String(value || '').trim().replace(/[，,;；\s_/-]+/g, '').toLocaleLowerCase()
}

function parseJsonValue(value) {
  if (!value) return ''
  if (typeof value !== 'string') return value
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

function keySpecsFor(item) {
  const usage = parseJsonValue(item?.ai_usage)
  const specs = usage && typeof usage === 'object' && !Array.isArray(usage) ? usage.key_specs : []
  return Array.isArray(specs) ? specs : []
}

function hasPassiveUnit(value, category) {
  const text = String(value || '').replace(/\s+/g, '')
  if (!text) return false
  if (category === '电阻') return /(mΩ|Ω|ohm|kΩ|kohm|MΩ|Mohm|GΩ|Gohm)$/i.test(text)
  if (category === '电容') return /(pF|nF|uF|µF|μF|mF)$/i.test(text)
  if (category === '电感') return /(nH|uH|µH|μH|mH|H)$/i.test(text)
  return false
}

function firstPassiveValueFromText(text, category) {
  const raw = String(text || '').replace('μ', 'µ')
  const patterns = {
    电阻: /(?:^|[^\p{L}\p{N}.])(\d+(?:\.\d+)?\s*(?:mΩ|Ω|ohm|kΩ|kohm|MΩ|Mohm|GΩ|Gohm))(?:$|[^\p{L}\p{N}])/iu,
    电容: /(?:^|[^\p{L}\p{N}.])(\d+(?:\.\d+)?\s*(?:pF|nF|uF|µF|mF))(?:$|[^\p{L}\p{N}])/iu,
    电感: /(?:^|[^\p{L}\p{N}.])(\d+(?:\.\d+)?\s*(?:nH|uH|µH|mH|H))(?:$|[^\p{L}\p{N}])/iu
  }
  const match = raw.match(patterns[category])
  return match?.[1]?.replace(/\s+/g, '') || ''
}

function passiveDisplayValue(item, category) {
  const wanted = (PASSIVE_SPEC_NAMES[category] || []).map(normalizeKey)
  for (const spec of keySpecsFor(item)) {
    const name = normalizeKey(spec?.name)
    const value = String(spec?.value || '').trim()
    if (wanted.includes(name)) {
      const fromValue = firstPassiveValueFromText(value, category) || value
      if (hasPassiveUnit(fromValue, category)) return fromValue.replace(/\s+/g, '')
    }
  }
  for (const value of [item?.normalized_spec, item?.parameters, item?.name, item?.source_title, item?.tags, item?.ai_tags]) {
    const parsed = firstPassiveValueFromText(value, category)
    if (parsed) return parsed
  }
  return ''
}

export function componentDisplayTitle(item) {
  const category = categoryName(item)
  if (PASSIVE_VALUE_CATEGORIES.has(category)) {
    const passive = passiveDisplayValue(item, category)
    if (passive) return passive
  }
  return String(
    item?.model
      || item?.name
      || item?.normalized_spec
      || item?.warehouse_code
      || '未命名器件'
  ).trim()
}

export function componentDisplaySubtitle(item, primary = componentDisplayTitle(item)) {
  const category = categoryName(item)
  const values = PASSIVE_VALUE_CATEGORIES.has(category)
    ? [item?.model, item?.name, item?.package, item?.lcsc_number, item?.normalized_spec]
    : [item?.normalized_spec, item?.name, item?.package, item?.lcsc_number]
  return uniqueDisplayParts(values, primary).slice(0, 3).join(' · ')
}

export function componentCandidateLabel(item) {
  const title = componentDisplayTitle(item)
  const subtitle = componentDisplaySubtitle(item, title)
  return [item?.warehouse_code, title, subtitle].filter(Boolean).join(' · ')
}
