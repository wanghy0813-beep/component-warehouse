import MarkdownIt from 'markdown-it'

export const lcscMobileSearchBase = 'https://m.szlcsc.com/pages-list/global-product/index'
export const lcscDesktopSearchBase = 'https://so.szlcsc.com/global.html'

function isMobileDevice() {
  if (typeof navigator === 'undefined') return false
  return /Android|iPhone|iPad|iPod|Mobile|Windows Phone/i.test(navigator.userAgent || '')
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true
})

export function makeLcscSearchUrl(keyword) {
  const text = cleanSearchKeyword(keyword)
  if (!text) return ''
  if (isMobileDevice()) return `${lcscMobileSearchBase}?keyword=${encodeURIComponent(text)}`
  return `${lcscDesktopSearchBase}?k=${encodeURIComponent(text)}`
}

export function cleanSearchKeyword(keyword) {
  const text = String(keyword || '').trim()
  if (!text) return ''
  const lcsc = text.match(/\bC\d{3,}\b/i)
  if (lcsc) return lcsc[0].toUpperCase()
  const model = text.match(/\b[A-Z0-9][A-Z0-9._-]{2,}(?:-[A-Z0-9._]+)*\b/i)
  if (model && text.length > 28) return model[0]
  return text
    .replace(/包邮|现货|热卖|特价|淘宝|天猫|拼多多|1688|旗舰店|官方|正品|原装|新品|促销|编带|袋装/g, ' ')
    .split(/[,，;；\s]+/)
    .filter(Boolean)
    .slice(0, 4)
    .join(' ')
}

export function renderAiMarkdown(markdown) {
  return md.render(String(markdown || '暂无建议'))
}

export function parseJsonValue(value) {
  if (!value) return ''
  if (typeof value !== 'string') return value
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

export function splitTags(text) {
  const seen = new Set()
  return String(text || '')
    .split(/[,，;；\s]+/)
    .map((item) => item.trim())
    .filter((item) => {
      const key = normalizeToken(item)
      if (!item || seen.has(key)) return false
      seen.add(key)
      return true
    })
}

const PACKAGE_TONES = [
  { background: '#eff6ff', borderColor: '#93c5fd', color: '#1d4ed8' },
  { background: '#f0fdf4', borderColor: '#86efac', color: '#15803d' },
  { background: '#fff7ed', borderColor: '#fdba74', color: '#c2410c' },
  { background: '#f5f3ff', borderColor: '#c4b5fd', color: '#6d28d9' },
  { background: '#ecfeff', borderColor: '#67e8f9', color: '#0e7490' },
  { background: '#fdf2f8', borderColor: '#f9a8d4', color: '#be185d' },
  { background: '#f8fafc', borderColor: '#cbd5e1', color: '#334155' },
  { background: '#fefce8', borderColor: '#fde047', color: '#a16207' }
]

export function normalizePackageName(value) {
  return String(value || '')
    .trim()
    .replace(/^封装[:：\s]*/i, '')
    .replace(/\s+/g, ' ')
    .toUpperCase()
}

export function packageTagStyle(value) {
  const normalized = normalizePackageName(value)
  if (!normalized) return {}
  let hash = 0
  for (const char of normalized) hash = ((hash * 31) + char.charCodeAt(0)) >>> 0
  return PACKAGE_TONES[hash % PACKAGE_TONES.length]
}

export function normalizeToken(value) {
  return String(value || '')
    .replace(/^(封装|规格|标签|分类|阻值|容值|感值)[:：]?/, '')
    .replace(/[，,;；\s_/-]+/g, '')
    .replace('贴片电容mlcc', '贴片电容')
    .replace('贴片电容(mlcc)', '贴片电容')
    .replace('贴片电阻器', '贴片电阻')
    .replace('厚膜电阻', '贴片电阻')
    .replace('tvs/esd', '静电保护')
    .replace('静电和浪涌保护(tvs/esd)', '静电保护')
    .replace('插针', '排针')
    .replace('插座', '连接器')
    .replace('跳线', '线材')
    .toLowerCase()
}

function pushChip(chips, seen, label, value, tone = 'blue') {
  const text = String(value || '').trim()
  if (!text) return
  const keyText = normalizeToken(text)
  const key = `${label}:${keyText}`
  const valueKey = `value:${keyText}`
  if (seen.has(key) || seen.has(valueKey)) return
  seen.add(key)
  seen.add(valueKey)
  chips.push({ label, value: text, tone })
}

function tidyNumber(value) {
  const rounded = value >= 100 ? Math.round(value * 100) / 100 : Math.round(value * 100000) / 100000
  return String(rounded).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
}

export function unitEquivalents(value) {
  const raw = String(value || '').replace('μ', 'µ').replace('UF', 'µF').replace('uF', 'µF').replace('uH', 'µH').replace('KΩ', 'kΩ')
  const match = raw.match(/(\d+(?:\.\d+)?)\s*(mΩ|Ω|R|kΩ|MΩ|pF|nF|µF|nH|µH|mH|H)/i)
  if (!match) return []
  const number = Number(match[1])
  const unit = match[2].replace('R', 'Ω')
  if (!Number.isFinite(number)) return []
  if (/mΩ|Ω|kΩ|MΩ/i.test(unit)) {
    const ohms = unit === 'mΩ' ? number / 1000 : unit === 'kΩ' ? number * 1000 : unit === 'MΩ' ? number * 1000000 : number
    const values = [`${tidyNumber(ohms)}Ω`]
    if (ohms >= 1000) values.push(`${tidyNumber(ohms / 1000)}kΩ`)
    if (ohms >= 1000000) values.push(`${tidyNumber(ohms / 1000000)}MΩ`)
    if (ohms < 1) values.push(`${tidyNumber(ohms * 1000)}mΩ`)
    return [...new Set(values)]
  }
  if (/pF|nF|µF/i.test(unit)) {
    const pf = unit === 'nF' ? number * 1000 : unit === 'µF' ? number * 1000000 : number
    const values = [`${tidyNumber(pf)}pF`]
    if (pf >= 1000) values.push(`${tidyNumber(pf / 1000)}nF`)
    if (pf >= 1000000) values.push(`${tidyNumber(pf / 1000000)}µF`)
    return [...new Set(values)]
  }
  if (/nH|µH|mH|H/i.test(unit)) {
    const nh = unit === 'µH' ? number * 1000 : unit === 'mH' ? number * 1000000 : unit === 'H' ? number * 1000000000 : number
    const values = [`${tidyNumber(nh)}nH`]
    if (nh >= 1000) values.push(`${tidyNumber(nh / 1000)}µH`)
    if (nh >= 1000000) values.push(`${tidyNumber(nh / 1000000)}mH`)
    return [...new Set(values)]
  }
  return []
}

function pushUnitChip(chips, seen, label, value, tone) {
  const equivalents = unitEquivalents(value)
  pushChip(chips, seen, label, equivalents[0] || value, tone)
  if (equivalents.length > 1) {
    pushChip(chips, seen, '换算', equivalents.slice(1).join(' = '), 'cyan')
  }
}

export function componentUnitHints(item) {
  const usage = parseJsonValue(item?.ai_usage)
  const keySpecs = usage?.key_specs
  if (Array.isArray(keySpecs)) {
    for (const spec of keySpecs) {
      const val = String(spec.value || '')
      const equivalents = unitEquivalents(val)
      if (equivalents.length > 1) return equivalents
    }
  }
  return []
}

export function extractComponentChips(item, max = 4) {
  if (!item) return []
  const chips = []
  const seen = new Set()
  const usage = parseJsonValue(item.ai_usage)
  const keySpecs = usage?.key_specs
  if (Array.isArray(keySpecs)) {
    for (const spec of keySpecs) {
      const val = String(spec.value || '').trim()
      if (!val) continue
      if (/^\d+(\.\d+)?$/.test(val)) continue
      const tone = spec.confidence === 'low' ? 'amber' : 'indigo'
      pushChip(chips, seen, spec.name || '参数', val, tone)
    }
  }
  return chips.slice(0, max)
}

export function componentOneLineUsage(item) {
  const usage = parseJsonValue(item?.ai_usage)
  const text = typeof usage === 'object' && !Array.isArray(usage) ? usage.usage : (typeof usage === 'string' ? usage : '')
  if (text) {
    const first = String(text).split(/[。；;\n]/).filter(Boolean)[0]
    if (first && (first.startsWith('{') || first.startsWith('['))) return ''
    return first || ''
  }
  if (item?.ai_summary) return String(item.ai_summary).split(/[。；;\n]/).filter(Boolean)[0]
  const category = item?.category?.name || ''
  const defaults = {
    电阻: '用于限流、分压、上拉下拉或信号匹配。',
    电容: '用于去耦、滤波、储能或时序相关电路。',
    电感: '用于电源滤波、储能或 EMI 抑制。',
    二极管: '用于整流、续流、保护或信号钳位。',
    MOS管: '用于开关、功率驱动或电平控制。',
    芯片: '用于实现特定控制、接口或电源功能。',
    电源: '用于稳压、升降压、充电或电源分配。',
    接口: '用于板级连接、外部通信或供电接入。',
    连接件: '用于板级连接、线束转接、固定或机械装配。',
    时钟源: '用于为 MCU、FPGA 或数字逻辑提供时钟基准。',
    开关: '用于人机输入或电源/信号切换。',
    开发板: '用于原型验证、主控开发或功能扩展。',
    功能模块: '用于快速接入已带外围电路的功能小板。',
    通信模块: '用于无线、定位或远距离通信链路。',
    显示模块: '用于状态显示、参数显示或人机界面。',
    机电件: '用于风扇、电机、继电器等需要驱动的外设。',
    散热件: '用于热管理、导热、固定或风道辅助。',
    保护器件: '用于过压、过流、浪涌或静电防护。',
    传感器: '用于采集环境、距离、姿态、电流等物理量。',
    结构件: '用于外壳、支架、面板或机械固定。'
  }
  return defaults[category] || '用于项目中的库存物料。'
}

export function familyLabel(value) {
  return {
    component: '元器件',
    module: '模块',
    sensor_module: '传感器模块',
    communication_module: '通信模块',
    display_module: '显示模块',
    fan: '风扇',
    motor: '电机',
    pump: '水泵',
    buzzer: '蜂鸣器',
    relay: '继电器',
    heatsink: '散热件',
    enclosure: '外壳',
    bracket: '支架',
    cable_assembly: '线束',
    pin_header: '排针',
    screw: '螺丝',
    nut: '螺母',
    standoff: '铜柱',
    wire: '线材',
    other: '其他'
  }[value || 'component'] || value
}
