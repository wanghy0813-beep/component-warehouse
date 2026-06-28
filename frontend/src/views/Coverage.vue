<template>
  <section class="page coverage-page">
    <div class="coverage-hero">
      <div>
        <span class="eyebrow">Coverage Map</span>
        <h1>规格覆盖</h1>
        <p>按核心规格和值域查看电阻、电容、电感库存覆盖。封装作为横向分层展示，采购前能快速看出已有、重复和缺口。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <section class="coverage-summary">
      <article v-for="item in summaryCards" :key="item.label" class="summary-card" :class="item.tone">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.hint }}</small>
      </article>
    </section>

    <div class="panel coverage-controls">
      <div class="control-left">
        <el-segmented v-model="activeCategory" :options="categoryOptions" />
        <el-select v-model="packageFilter" clearable placeholder="封装/规格" @change="load">
          <el-option v-for="item in packageOptions" :key="item" :label="item" :value="item" />
        </el-select>
      </div>
      <el-checkbox v-model="onlyAvailable" @change="load">只看有库存</el-checkbox>
    </div>

    <section class="coverage-layout" v-loading="loading">
      <article class="panel map-panel">
        <div class="section-head">
          <div>
            <h2>{{ activeCategory }}核心规格分布</h2>
            <span>横轴是{{ activeCategory }}核心值的对数轴，越靠右规格值越大 · {{ visibleItems.length }} 个规格点</span>
          </div>
          <el-tag effect="plain">{{ activeData.unit || unitLabel }}</el-tag>
        </div>

        <div class="chart-legend">
          <span><i class="legend-dot strong"></i>圆点 = 一个元器件规格</span>
          <span><i class="legend-dot soft"></i>圆点越大 = 可用库存越多</span>
          <span><i class="legend-dot empty"></i>灰色 = 暂无可用库存</span>
        </div>

        <div v-if="axisTicks.length" class="axis-ruler">
          <span v-for="tick in axisTicks" :key="tick.label" :style="{ left: `${tick.left}%` }">{{ tick.label }}</span>
        </div>

        <div v-if="packageLanes.length" class="lane-stack">
          <div v-for="lane in packageLanes" :key="lane.name" class="coverage-lane">
            <div class="lane-meta">
              <strong>{{ lane.name }}</strong>
              <span>{{ lane.count }} 项 · 可用 {{ lane.available }}</span>
            </div>
            <div class="lane-track">
              <button
                v-for="point in lane.points"
                :key="point.key"
                class="lane-point"
                :class="{ empty: point.available_quantity <= 0 }"
                :style="{
                  left: `${point.left}%`,
                  width: `${point.size}px`,
                  height: `${point.size}px`,
                  background: point.available_quantity > 0 ? lane.color : '#cbd5e1'
                }"
                :title="point.title"
              >
                <span>{{ point.display_value }}</span>
              </button>
            </div>
          </div>
        </div>

        <el-empty v-else-if="!loading" description="暂无可展示规格" :image-size="86" />
      </article>

      <aside class="side-column">
        <article class="panel compact-panel">
          <div class="section-head small">
            <div>
              <h2>规格段</h2>
              <span>按对数值域聚合</span>
            </div>
          </div>
          <div class="bucket-grid">
            <div v-for="bucket in valueBuckets" :key="bucket.label" class="bucket-card">
              <span>{{ bucket.label }}</span>
              <strong>{{ bucket.count }}</strong>
              <small>可用 {{ bucket.available }}</small>
              <i :style="{ width: `${bucket.percent}%` }"></i>
            </div>
          </div>
        </article>

        <article class="panel compact-panel">
          <div class="section-head small">
            <div>
              <h2>封装覆盖</h2>
              <span>数量越多条越长</span>
            </div>
          </div>
          <div class="package-stack">
            <div v-for="item in packageStats" :key="item.name" class="package-row">
              <div>
                <strong>{{ item.name }}</strong>
                <span>{{ item.count }} 项 · 可用 {{ item.available }}</span>
              </div>
              <div class="mini-bar"><i :style="{ width: `${item.percent}%`, background: item.color }"></i></div>
            </div>
          </div>
        </article>
      </aside>
    </section>

    <section class="insight-grid">
      <article class="panel insight-panel">
        <div class="section-head small">
          <div>
            <h2>覆盖状态</h2>
            <span>用比例图判断规格资料和库存可用性</span>
          </div>
        </div>
        <div class="coverage-rings">
          <div v-for="ring in coverageRings" :key="ring.label" class="ring-card">
            <div class="ring" :style="{ background: ring.gradient }">
              <span>{{ ring.percent }}%</span>
            </div>
            <div>
              <strong>{{ ring.label }}</strong>
              <small>{{ ring.hint }}</small>
            </div>
          </div>
        </div>
      </article>

      <article class="panel insight-panel">
        <div class="section-head small">
          <div>
            <h2>待整理</h2>
            <span>缺少高置信核心规格，暂时无法进入覆盖轴</span>
          </div>
        </div>
        <div class="unparsed-card">
          <strong>{{ activeData.unparsed_count || 0 }}</strong>
          <span>个{{ activeCategory }}需要 AI 或人工补齐规格</span>
        </div>
      </article>
    </section>

    <section class="panel coverage-list">
      <div class="section-head">
        <div>
          <h2>规格清单</h2>
          <span>{{ visibleItems.length }} 项，显示前 {{ listItems.length }} 项</span>
        </div>
      </div>
      <div class="coverage-table">
        <div class="table-head">
          <span>规格</span>
          <span>型号 / 名称</span>
          <span>封装</span>
          <span>库存</span>
        </div>
        <div v-for="item in listItems" :key="item.id" class="coverage-row">
          <strong>{{ item.display_value }}</strong>
          <span>{{ item.model || item.name }}</span>
          <span>{{ item.package || item.normalized_spec || '未标封装' }}</span>
          <span>总 {{ item.quantity }} · 可用 {{ item.available_quantity }}</span>
        </div>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from '../shared/elementApi'
import { Refresh } from '@element-plus/icons-vue'
import { getComponentCoverage } from '../api/client'

const categoryOptions = ['电阻', '电容', '电感']
const activeCategory = ref('电阻')
const packageFilter = ref('')
const onlyAvailable = ref(true)
const loading = ref(false)
const coverage = ref([])
const palette = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#475569', '#0d9488', '#ea580c', '#6366f1', '#ca8a04']

const activeData = computed(() => coverage.value.find((item) => item.category === activeCategory.value) || {})
const unitLabel = computed(() => ({ 电阻: 'Ω', 电容: 'F', 电感: 'H' }[activeCategory.value] || ''))
const packageOptions = computed(() => activeData.value.packages || [])
const visibleItems = computed(() => activeData.value.items || [])
const listItems = computed(() => visibleItems.value.slice(0, 160))

const numericValues = computed(() => visibleItems.value.map((item) => Number(item.value)).filter((value) => Number.isFinite(value) && value > 0))
const logRange = computed(() => {
  if (!numericValues.value.length) return { min: 0, max: 1, spread: 1 }
  const min = Math.log10(Math.min(...numericValues.value))
  const max = Math.log10(Math.max(...numericValues.value))
  return { min, max, spread: Math.max(max - min, 0.0001) }
})

const summaryCards = computed(() => {
  const categories = coverage.value || []
  const parsed = categories.reduce((sum, item) => sum + (item.items?.length || 0), 0)
  const unparsed = categories.reduce((sum, item) => sum + (item.unparsed_count || 0), 0)
  const stock = categories.reduce((sum, item) => sum + (item.items || []).reduce((inner, row) => inner + (row.available_quantity || 0), 0), 0)
  const packages = new Set(categories.flatMap((item) => item.packages || [])).size
  return [
    { label: '可绘制规格', value: parsed, hint: '已进入覆盖轴', tone: 'blue' },
    { label: '可用库存', value: stock, hint: '当前筛选汇总', tone: 'green' },
    { label: '封装覆盖', value: packages, hint: '不同封装/规格组', tone: 'amber' },
    { label: '待整理', value: unparsed, hint: '缺少高置信规格', tone: 'red' },
  ]
})

const rangeSummary = computed(() => {
  const values = numericValues.value
  const unit = activeData.value.unit || unitLabel.value
  if (!values.length) return { min: '-', max: '-', count: 0 }
  return {
    min: formatValue(Math.min(...values), unit),
    max: formatValue(Math.max(...values), unit),
    count: values.length,
  }
})

const packageStats = computed(() => {
  const items = visibleItems.value
  const total = Math.max(items.length, 1)
  const map = new Map()
  for (const item of items) {
    const name = item.package || item.normalized_spec || '未标封装'
    if (!map.has(name)) map.set(name, { name, count: 0, available: 0, color: colorForPackage(name) })
    const stat = map.get(name)
    stat.count += 1
    stat.available += item.available_quantity || 0
  }
  return Array.from(map.values())
    .map((item) => ({ ...item, percent: Math.max(6, Math.round((item.count / total) * 100)) }))
    .sort((a, b) => b.count - a.count)
})

const packageLanes = computed(() => {
  const maxAvailable = Math.max(...visibleItems.value.map((item) => item.available_quantity || 0), 1)
  return packageStats.value.slice(0, 10).map((stat) => {
    const points = visibleItems.value
      .filter((item) => (item.package || item.normalized_spec || '未标封装') === stat.name)
      .slice(0, 80)
      .map((item) => {
        const available = item.available_quantity || 0
        const size = Math.max(9, Math.min(20, 8 + Math.sqrt(available / maxAvailable) * 12))
        return {
          ...item,
          key: `${item.id}-${item.value}`,
          left: logPosition(item.value),
          size,
          title: `${item.display_value} | ${item.model || item.name} | ${stat.name} | 可用 ${available}`
        }
      })
    return { ...stat, points }
  })
})

const axisTicks = computed(() => {
  const values = numericValues.value
  if (!values.length) return []
  const unit = activeData.value.unit || unitLabel.value
  const min = Math.log10(Math.min(...values))
  const max = Math.log10(Math.max(...values))
  const count = Math.min(6, Math.max(3, Math.ceil(max - min) + 2))
  return Array.from({ length: count }, (_, index) => {
    const ratio = count === 1 ? 0 : index / (count - 1)
    const value = Math.pow(10, min + (max - min) * ratio)
    return { left: Math.round(ratio * 100), label: formatValue(value, unit) }
  })
})

const valueBuckets = computed(() => {
  const values = numericValues.value
  if (!values.length) return []
  const unit = activeData.value.unit || unitLabel.value
  const count = Math.min(8, Math.max(4, Math.ceil(logRange.value.spread * 1.4)))
  const buckets = Array.from({ length: count }, (_, index) => {
    const startRatio = index / count
    const endRatio = (index + 1) / count
    const start = Math.pow(10, logRange.value.min + logRange.value.spread * startRatio)
    const end = Math.pow(10, logRange.value.min + logRange.value.spread * endRatio)
    return { start, end, label: `${formatValue(start, unit)}-${formatValue(end, unit)}`, count: 0, available: 0 }
  })
  for (const item of visibleItems.value) {
    const value = Number(item.value)
    if (!Number.isFinite(value) || value <= 0) continue
    const position = Math.min(count - 1, Math.max(0, Math.floor(((Math.log10(value) - logRange.value.min) / logRange.value.spread) * count)))
    buckets[position].count += 1
    buckets[position].available += item.available_quantity || 0
  }
  const maxCount = Math.max(...buckets.map((item) => item.count), 1)
  return buckets.map((item) => ({ ...item, percent: Math.max(4, Math.round((item.count / maxCount) * 100)) }))
})

const coverageRings = computed(() => {
  const parsed = visibleItems.value.length
  const unparsed = activeData.value.unparsed_count || 0
  const total = parsed + unparsed
  const availableSpecs = visibleItems.value.filter((item) => (item.available_quantity || 0) > 0).length
  const parsedPercent = total ? Math.round((parsed / total) * 100) : 0
  const availablePercent = parsed ? Math.round((availableSpecs / parsed) * 100) : 0
  return [
    {
      label: '规格可视化率',
      percent: parsedPercent,
      hint: `${parsed} 个已进入轴，${unparsed} 个待整理`,
      gradient: `conic-gradient(#2563eb ${parsedPercent}%, #e5e7eb 0)`
    },
    {
      label: '库存可用规格',
      percent: availablePercent,
      hint: `${availableSpecs} 个规格有可用库存`,
      gradient: `conic-gradient(#059669 ${availablePercent}%, #e5e7eb 0)`
    }
  ]
})

function colorForPackage(name) {
  const text = String(name || '未标封装')
  let hash = 0
  for (let index = 0; index < text.length; index += 1) hash = (hash * 31 + text.charCodeAt(index)) >>> 0
  return palette[hash % palette.length]
}

function logPosition(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return 0
  return Math.max(0, Math.min(100, ((Math.log10(numeric) - logRange.value.min) / logRange.value.spread) * 100))
}

function formatValue(value, unit) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return ''
  const ranges = unit === 'Ω'
    ? [['TΩ', 1e12], ['GΩ', 1e9], ['MΩ', 1e6], ['kΩ', 1e3], ['Ω', 1], ['mΩ', 1e-3]]
    : unit === 'F'
      ? [['mF', 1e-3], ['µF', 1e-6], ['nF', 1e-9], ['pF', 1e-12]]
      : [['H', 1], ['mH', 1e-3], ['µH', 1e-6], ['nH', 1e-9]]
  const picked = ranges.find(([, scale]) => Math.abs(numeric) >= scale) || ranges[ranges.length - 1]
  return `${Number((numeric / picked[1]).toPrecision(4))}${picked[0]}`
}

async function load() {
  loading.value = true
  try {
    const data = await getComponentCoverage({
      category: activeCategory.value,
      package: packageFilter.value,
      only_available: onlyAvailable.value,
    })
    coverage.value = data.categories || []
  } catch (error) {
    ElMessage.error('读取覆盖图失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

watch(activeCategory, () => {
  packageFilter.value = ''
  load()
})
</script>

<style scoped>
.coverage-page {
  gap: 14px;
}

.coverage-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--cw-border);
  border-radius: 16px;
  background: #fff;
}

.coverage-hero h1 {
  margin: 0;
  font-size: 25px;
  font-weight: 780;
}

.coverage-hero p {
  max-width: 760px;
  margin: 6px 0 0;
  color: var(--cw-muted);
  font-size: 13px;
}

.eyebrow {
  display: inline-flex;
  margin-bottom: 6px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 760;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.coverage-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.summary-card {
  display: grid;
  gap: 4px;
  padding: 14px 16px;
  border: 1px solid var(--cw-border);
  border-radius: 16px;
  background: #fff;
}

.summary-card span,
.summary-card small,
.section-head span,
.lane-meta span,
.package-row span,
.insight-row small {
  color: var(--cw-muted);
}

.summary-card span,
.summary-card small {
  font-size: 12px;
}

.summary-card strong {
  font-size: 27px;
  font-weight: 820;
  line-height: 1.05;
}

.summary-card.blue strong { color: #2563eb; }
.summary-card.green strong { color: #059669; }
.summary-card.amber strong { color: #d97706; }
.summary-card.red strong { color: #dc2626; }
.summary-card.blue { border-color: #bfdbfe; background: #eff6ff; }
.summary-card.green { border-color: #a7f3d0; background: #ecfdf5; }
.summary-card.amber { border-color: #fde68a; background: #fffbeb; }
.summary-card.red { border-color: #fecdd3; background: #fff1f2; }

.coverage-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.control-left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.coverage-controls .el-select {
  width: 180px;
}

.coverage-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 14px;
  align-items: start;
}

.map-panel {
  min-height: 0;
}

.side-column,
.package-stack,
.lane-stack,
.insight-list,
.bucket-grid {
  display: grid;
  gap: 10px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-head h2 {
  margin: 0;
  font-size: 16px;
}

.section-head span {
  font-size: 12px;
}

.section-head.small {
  margin-bottom: 10px;
}

.axis-ruler {
  position: relative;
  height: 24px;
  margin: 0 6px 8px 150px;
  border-bottom: 1px solid #e5eaf3;
}

.axis-ruler span {
  position: absolute;
  bottom: 5px;
  transform: translateX(-50%);
  color: #667085;
  font-size: 11px;
  white-space: nowrap;
}

.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: -4px 0 10px;
  color: #53627a;
  font-size: 12px;
}

.chart-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid #e5eaf3;
  border-radius: 999px;
  background: #f8fafc;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.legend-dot.strong { background: #2563eb; }
.legend-dot.soft { background: #93c5fd; }
.legend-dot.empty { background: #cbd5e1; }

.coverage-lane {
  display: grid;
  grid-template-columns: 132px minmax(0, 1fr);
  gap: 14px;
  align-items: center;
  padding: 9px 10px;
  border: 1px solid #edf1f7;
  border-radius: 16px;
  background: #fff;
}

.lane-meta {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.lane-meta strong {
  overflow: hidden;
  color: var(--cw-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lane-meta span {
  font-size: 11px;
}

.lane-track {
  position: relative;
  height: 40px;
  border: 1px solid #e5eaf3;
  border-radius: 16px;
  background:
    linear-gradient(to right, transparent 24.5%, rgba(148, 163, 184, 0.18) 25%, transparent 25.5%),
    linear-gradient(to right, transparent 49.5%, rgba(148, 163, 184, 0.18) 50%, transparent 50.5%),
    linear-gradient(to right, transparent 74.5%, rgba(148, 163, 184, 0.18) 75%, transparent 75.5%),
    #f8fafc;
}

.lane-point {
  position: absolute;
  top: 45%;
  transform: translate(-50%, -50%);
  border: 2px solid #fff;
  border-radius: 999px;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.14);
  cursor: default;
}

.lane-point span {
  position: absolute;
  left: 50%;
  top: calc(100% + 2px);
  transform: translateX(-50%);
  max-width: 90px;
  overflow: hidden;
  color: #475569;
  font-size: 9px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
}

.lane-point.empty {
  opacity: 0.7;
}

.bucket-card {
  position: relative;
  display: grid;
  gap: 2px;
  overflow: hidden;
  padding: 8px 10px;
  border: 1px solid #e5eaf3;
  border-radius: var(--cw-radius-control);
  background: #fff;
}

.bucket-card span,
.bucket-card small {
  position: relative;
  z-index: 1;
  color: var(--cw-muted);
  font-size: 11px;
}

.bucket-card strong {
  position: relative;
  z-index: 1;
  font-size: 20px;
}

.bucket-card i {
  position: absolute;
  inset: auto auto 0 0;
  height: 3px;
  border-radius: 999px;
  background: #2563eb;
}

.package-row {
  display: grid;
  gap: 5px;
}

.package-row > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.package-row strong {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.package-row span {
  flex: none;
  font-size: 11px;
}

.mini-bar {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: #eef2f7;
}

.mini-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.insight-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 14px;
}

.coverage-rings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.ring-card {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 12px;
  border: 1px solid #e5eaf3;
  border-radius: 16px;
  background: #fff;
  text-align: center;
}

.ring {
  width: 96px;
  height: 96px;
  display: grid;
  place-items: center;
  border-radius: 50%;
}

.ring::before {
  content: "";
  position: absolute;
}

.ring span {
  width: 68px;
  height: 68px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #fff;
  color: #111827;
  font-size: 20px;
  font-weight: 800;
}

.ring-card strong {
  display: block;
  font-size: 14px;
}

.ring-card small {
  display: block;
  margin-top: 3px;
  color: var(--cw-muted);
  font-size: 11px;
}

.unparsed-card {
  display: grid;
  min-height: 96px;
  place-content: center;
  gap: 6px;
  border: 1px dashed #cbd5e1;
  border-radius: 16px;
  background: #f8fafc;
  text-align: center;
}

.unparsed-card strong {
  color: #dc2626;
  font-size: 38px;
  line-height: 1;
}

.unparsed-card span {
  color: var(--cw-muted);
  font-size: 12px;
}

.coverage-table {
  display: grid;
  overflow: hidden;
  border: 1px solid #e5eaf3;
  border-radius: 16px;
}

.table-head,
.coverage-row {
  display: grid;
  grid-template-columns: 110px minmax(0, 1.5fr) minmax(90px, 0.8fr) 150px;
  gap: 12px;
  align-items: center;
  padding: 10px 14px;
}

.table-head {
  background: #f8fafc;
  color: #667085;
  font-size: 12px;
  font-weight: 760;
}

.coverage-row {
  border-top: 1px solid #eef2f7;
  background: #fff;
  font-size: 13px;
}

.coverage-row strong {
  color: #111827;
  font-size: 14px;
}

.coverage-row span {
  overflow: hidden;
  color: #53627a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .coverage-layout,
  .insight-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .coverage-hero {
    flex-direction: column;
    align-items: stretch;
  }

  .coverage-summary {
    grid-template-columns: repeat(2, 1fr);
  }

  .coverage-controls {
    align-items: stretch;
  }

  .coverage-controls .el-segmented,
  .coverage-controls .el-select {
    width: 100%;
  }

  .axis-ruler {
    margin-left: 0;
  }

  .coverage-lane {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .table-head {
    display: none;
  }

  .coverage-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}

@media (max-width: 460px) {
  .coverage-summary {
    grid-template-columns: 1fr;
  }
}
</style>
