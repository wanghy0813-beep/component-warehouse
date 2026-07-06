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
const SEMICONDUCTOR_MODEL_CATEGORIES = ['二极管', '三极管', '晶体管', '场效应管', 'MOS', 'MOSFET', 'BJT', 'IGBT']
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

function isSemiconductorCategory(category) {
  const text = String(category || '').toLocaleUpperCase()
  return SEMICONDUCTOR_MODEL_CATEGORIES.some((name) => text.includes(name.toLocaleUpperCase()))
}

function isRatingToken(value) {
  const text = String(value || '').trim()
  if (!text) return false
  return /^[-+]?\d+(?:\.\d+)?(?:V|KV|MV|A|MA|UA|µA|Ω|OHM|W|MW|PF|NF|UF|µF|H|NH|UH|MH|HZ|KHZ|MHZ|GHZ|%)$/iu.test(text)
}

function isRatingPhrase(value) {
  const text = String(value || '').trim()
  if (!text) return false
  const parts = text.split(/\s+/).filter(Boolean)
  if (parts.length > 1 && parts.every(isRatingToken)) return true
  return /^(?:[-+]?\d+(?:\.\d+)?(?:V|KV|MV|A|MA|UA|µA|Ω|OHM|W|MW|PF|NF|UF|µF|H|NH|UH|MH|HZ|KHZ|MHZ|GHZ|%))+$/iu.test(text.replace(/\s+/g, ''))
}

function isPackageToken(value) {
  const text = String(value || '').trim().toLocaleUpperCase()
  return /^(?:SOT|SOP|SOIC|DIP|TO|DO|SMA|SMB|SMC|DFN|QFN|LQFP|TSSOP|SSOP|0603|0805|1206)(?:[-_/]?[A-Z0-9.]+)*$/u.test(text)
}

function isUsableModelText(value) {
  const text = String(value || '').trim()
  if (!text) return false
  if (/[\p{Script=Han}:：]/u.test(text)) return false
  const compact = text.replace(/\s+/g, '')
  if (isRatingPhrase(text)) return false
  if (!/[A-Za-z]/.test(compact) || !/\d/.test(compact)) return false
  const tokens = compact.split(/[,+，;；、]+/).filter(Boolean)
  if (tokens.length && tokens.every(isRatingToken)) return false
  if (isPackageToken(compact)) return false
  return true
}

function cleanModelToken(value) {
  return String(value || '')
    .trim()
    .replace(/^(?:型号|规格型号|丝印|料号|part\s*number|model)[:：=]/iu, '')
    .replace(/[()（）\[\]【】]/g, '')
    .trim()
}

function modelCandidateFromText(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  for (const raw of text.split(/[\s,，;；、|]+/u)) {
    const token = cleanModelToken(raw)
    if (isUsableModelText(token)) return token
  }
  const leading = cleanModelToken(text.match(/^[A-Za-z0-9][A-Za-z0-9._+/:-]{1,}/u)?.[0] || '')
  return isUsableModelText(leading) ? leading : ''
}

function semiconductorDisplayModel(item) {
  const directModel = cleanModelToken(item?.model)
  if (isUsableModelText(directModel)) return directModel
  for (const spec of keySpecsFor(item)) {
    const name = normalizeKey(spec?.name)
    if (!['型号', '规格型号', 'model', 'partnumber', 'partno', '料号'].includes(name)) continue
    const value = modelCandidateFromText(spec?.value)
    if (value) return value
  }
  for (const value of [item?.name, item?.source_title, item?.normalized_spec, item?.parameters]) {
    const candidate = modelCandidateFromText(value)
    if (candidate) return candidate
  }
  return ''
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
  if (isSemiconductorCategory(category)) {
    const model = semiconductorDisplayModel(item)
    if (model) return model
    return String(item?.warehouse_code || item?.name || '未命名器件').trim()
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
