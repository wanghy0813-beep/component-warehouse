<template>
  <section class="page coverage-page">
    <div class="coverage-hero">
      <div>
        <span class="eyebrow">Passive Coverage</span>
        <h1>规格覆盖图</h1>
        <p>用对数轴散点图和热力矩阵看清电阻、电容、电感的规格、封装和库存覆盖，采购前先确认哪里缺、哪里重复。</p>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
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

    <section class="dual-chart-grid" v-loading="loading">
      <article class="panel coverage-panel">
        <div class="coverage-head">
          <div>
            <h2>规格分布散点图</h2>
            <span>{{ activeData.items?.length || 0 }} 个规格点 · 气泡大小 = 可用库存</span>
          </div>
          <el-tag effect="plain">{{ activeData.unit || unitLabel }}</el-tag>
        </div>
        <div ref="chartRef" class="coverage-chart"></div>
        <el-empty v-if="!loading && !(activeData.items || []).length" description="暂无可绘制规格" :image-size="86" />
      </article>

      <article class="panel coverage-panel">
        <div class="coverage-head">
          <div>
            <h2>覆盖热力矩阵</h2>
            <span>封装 × 规格段，颜色深浅 = 库存量</span>
          </div>
          <el-tag effect="plain">{{ activeData.unit || unitLabel }}</el-tag>
        </div>
        <div ref="heatmapRef" class="coverage-chart"></div>
        <el-empty v-if="!loading && !(activeData.items || []).length" description="暂无可绘制规格" :image-size="86" />
      </article>
    </section>

    <section class="panel coverage-side-panel">
      <div class="side-grid">
        <div class="range-card">
          <small>规格范围</small>
          <strong>{{ rangeSummary.min }} – {{ rangeSummary.max }}</strong>
          <span>{{ rangeSummary.count }} 个规格点</span>
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
      </div>
    </section>

    <section class="panel density-panel">
      <div class="section-head">
        <div>
          <h2>规格密度条</h2>
          <span>每个色块 = 一个可用规格，颜色按封装区分，悬停查看详情</span>
        </div>
      </div>
      <div class="density-strip">
        <span
          v-for="item in visibleItems"
          :key="`density-${item.id}`"
          :title="`${item.display_value} ${item.model || item.name} | ${item.package || '未标封装'} | 可用 ${item.available_quantity}`"
          :style="{ background: colorForPackage(item.package || item.normalized_spec || '未标封装') }"
        >
          {{ item.display_value }}
        </span>
      </div>
    </section>

    <section class="panel coverage-list">
      <div class="section-head">
        <div>
          <h2>当前规格点</h2>
          <span>{{ visibleItems.length }} 项，按规格值从小到大排列</span>
        </div>
      </div>
      <div class="coverage-table">
        <div v-for="item in visibleItems" :key="item.id" class="coverage-row">
          <div class="value-pill" :style="{ background: colorForPackage(item.package || item.normalized_spec || '未标封装') }">{{ item.display_value }}</div>
          <div>
            <strong>{{ item.model || item.name }}</strong>
            <span>{{ item.name }}</span>
            <small>{{ item.package || item.normalized_spec || '未标封装' }} · 总 {{ item.quantity }} · 可用 {{ item.available_quantity }}</small>
          </div>
        </div>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { ScatterChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, DataZoomComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { getComponentCoverage } from '../api/client'

echarts.use([ScatterChart, HeatmapChart, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, DataZoomComponent, CanvasRenderer])

const categoryOptions = ['电阻', '电容', '电感']
const activeCategory = ref('电阻')
const packageFilter = ref('')
const onlyAvailable = ref(true)
const loading = ref(false)
const coverage = ref([])
const chartRef = ref(null)
const heatmapRef = ref(null)
let chart
let heatmapChart

const activeData = computed(() => coverage.value.find((item) => item.category === activeCategory.value) || {})
const unitLabel = computed(() => ({ 电阻: 'Ω', 电容: 'F', 电感: 'H' }[activeCategory.value] || ''))
const packageOptions = computed(() => activeData.value.packages || [])
const visibleItems = computed(() => activeData.value.items || [])
const palette = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#475569', '#0d9488', '#ea580c', '#6366f1', '#ca8a04']

const summaryCards = computed(() => {
  const categories = coverage.value || []
  const parsed = categories.reduce((sum, item) => sum + (item.items?.length || 0), 0)
  const unparsed = categories.reduce((sum, item) => sum + (item.unparsed_count || 0), 0)
  const stock = categories.reduce((sum, item) => sum + (item.items || []).reduce((inner, row) => inner + (row.available_quantity || 0), 0), 0)
  const packages = new Set(categories.flatMap((item) => item.packages || [])).size
  return [
    { label: '可绘制规格', value: parsed, hint: '已解析到轴上的规格点', tone: 'blue' },
    { label: '可用库存', value: stock, hint: '当前筛选下可用数量', tone: 'green' },
    { label: '封装覆盖', value: packages, hint: '不同封装/规格组', tone: 'amber' },
    { label: '待整理', value: unparsed, hint: '缺少高置信规格', tone: 'red' },
  ]
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
    .map((item) => ({ ...item, percent: Math.max(8, Math.round((item.count / total) * 100)) }))
    .sort((a, b) => b.count - a.count)
})

const rangeSummary = computed(() => {
  const values = visibleItems.value.map((item) => Number(item.value)).filter((value) => Number.isFinite(value) && value > 0)
  const unit = activeData.value.unit || unitLabel.value
  if (!values.length) return { min: '-', max: '-', count: 0 }
  return {
    min: formatValue(Math.min(...values), unit),
    max: formatValue(Math.max(...values), unit),
    count: values.length,
  }
})

function colorForPackage(name) {
  const text = String(name || '未标封装')
  let hash = 0
  for (let index = 0; index < text.length; index += 1) hash = (hash * 31 + text.charCodeAt(index)) >>> 0
  return palette[hash % palette.length]
}

function formatValue(value, unit) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return ''
  const ranges = unit === 'Ω'
    ? [['TΩ', 1e12], ['GΩ', 1e9], ['MΩ', 1e6], ['kΩ', 1e3], ['Ω', 1], ['mΩ', 1e-3]]
    : unit === 'F'
      ? [['mF', 1e-3], ['µF', 1e-6], ['nF', 1e-9], ['pF', 1e-12]]
      : [['mH', 1e-3], ['µH', 1e-6], ['nH', 1e-9]]
  const picked = ranges.find(([, scale]) => Math.abs(numeric) >= scale) || ranges[ranges.length - 1]
  return `${Number((numeric / picked[1]).toPrecision(4))}${picked[0]}`
}

function buildHeatmapData(items, unit) {
  if (!items.length) return { data: [], xLabels: [], yLabels: [] }

  const values = items.map((item) => Number(item.value)).filter((v) => Number.isFinite(v) && v > 0)
  if (!values.length) return { data: [], xLabels: [], yLabels: [] }

  const logMin = Math.log10(Math.min(...values))
  const logMax = Math.log10(Math.max(...values))
  const binCount = Math.min(12, Math.max(6, Math.ceil((logMax - logMin) * 1.5)))
  const binStep = (logMax - logMin) / Math.max(binCount - 1, 1)

  const xLabels = []
  for (let i = 0; i < binCount; i++) {
    const logStart = logMin + i * binStep
    const logEnd = logMin + (i + 1) * binStep
    const midValue = Math.pow(10, (logStart + logEnd) / 2)
    xLabels.push(formatValue(midValue, unit))
  }

  const packages = [...new Set(items.map((item) => item.package || item.normalized_spec || '未标封装'))].slice(0, 16)
  const matrix = {}
  for (const pkg of packages) {
    matrix[pkg] = new Array(binCount).fill(0)
  }

  let maxVal = 0
  for (const item of items) {
    const v = Number(item.value)
    if (!Number.isFinite(v) || v <= 0) continue
    const pkg = item.package || item.normalized_spec || '未标封装'
    if (!matrix[pkg]) continue
    const binIndex = Math.min(binCount - 1, Math.max(0, Math.floor((Math.log10(v) - logMin) / binStep)))
    matrix[pkg][binIndex] += item.available_quantity || 0
    maxVal = Math.max(maxVal, matrix[pkg][binIndex])
  }

  const data = []
  for (let yi = 0; yi < packages.length; yi++) {
    for (let xi = 0; xi < binCount; xi++) {
      data.push([xi, yi, matrix[packages[yi]][xi]])
    }
  }

  return { data, xLabels, yLabels: packages, maxVal }
}

function renderChart() {
  if (!chartRef.value) return
  chart ||= echarts.init(chartRef.value)
  const data = activeData.value
  const items = data.items || []
  const unit = data.unit || unitLabel.value
  const packages = [...new Set(items.map((item) => item.package || item.normalized_spec || '未标封装'))]
  const positives = items.map((item) => Number(item.value)).filter((value) => value > 0)
  const zeroFloor = positives.length ? Math.min(...positives) / 10 : 1
  const series = packages.map((pkg, packageIndex) => ({
    name: pkg,
    type: 'scatter',
    itemStyle: { color: colorForPackage(pkg), borderColor: '#fff', borderWidth: 1.5, shadowBlur: 4, shadowColor: 'rgba(0,0,0,0.08)' },
    emphasis: { focus: 'series', scale: true, itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.15)' } },
    symbolSize: (point) => Math.max(12, Math.min(40, 8 + Math.sqrt(point[2] || 0) * 3.5)),
    data: items
      .filter((item) => (item.package || item.normalized_spec || '未标封装') === pkg)
      .map((item) => [Number(item.value) > 0 ? item.value : zeroFloor, packageIndex, item.available_quantity, item]),
  }))
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 60, right: 28, top: 32, bottom: 64 },
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e5e7eb',
      borderWidth: 1,
      padding: [12, 16],
      textStyle: { color: '#17202a', fontSize: 13 },
      formatter: (params) => {
        const item = params.data[3]
        const model = item.model || item.name
        const name = item.model ? item.name : ''
        const lcsc = item.lcsc_number ? `<span style="color:#667085">立创 ${item.lcsc_number}</span>` : ''
        return [
          `<div style="font-weight:700;font-size:15px;margin-bottom:6px">${item.display_value} <span style="color:${params.color}">${params.seriesName}</span></div>`,
          `<div style="font-weight:600">${model}</div>`,
          name ? `<div style="color:#667085;font-size:12px">${name}</div>` : '',
          `<div style="margin-top:6px;display:flex;gap:16px">`,
          `<span>总量 <b>${item.quantity}</b></span>`,
          `<span>可用 <b style="color:${item.available_quantity > 0 ? '#059669' : '#dc2626'}">${item.available_quantity}</b></span>`,
          `</div>`,
          lcsc ? `<div style="margin-top:4px">${lcsc}</div>` : '',
        ].filter(Boolean).join('')
      },
    },
    legend: { bottom: 0, type: 'scroll', icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { fontSize: 11 } },
    xAxis: {
      type: 'log',
      min: zeroFloor / 2,
      name: unit,
      nameTextStyle: { color: '#667085', fontSize: 12, padding: [0, 0, 0, 4] },
      axisLabel: { formatter: (value) => formatValue(value, unit), color: '#667085', fontSize: 11 },
      splitLine: { lineStyle: { color: '#e9eef6', type: 'dashed' } },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
    },
    yAxis: {
      type: 'category',
      data: packages,
      axisLabel: { color: '#475467', fontSize: 11, fontWeight: 500 },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: '#f1f5f9', type: 'dashed' } },
    },
    series,
  }, true)
  chart.resize()
}

function renderHeatmap() {
  if (!heatmapRef.value) return
  heatmapChart ||= echarts.init(heatmapRef.value)
  const data = activeData.value
  const items = data.items || []
  const unit = data.unit || unitLabel.value
  const hm = buildHeatmapData(items, unit)

  heatmapChart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 72, right: 28, top: 16, bottom: 64 },
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e5e7eb',
      borderWidth: 1,
      padding: [10, 14],
      formatter: (params) => {
        const pkg = hm.yLabels[params.value[1]]
        const range = hm.xLabels[params.value[0]]
        const qty = params.value[2]
        return `<div style="font-weight:600">${pkg}</div><div>${range}</div><div>可用库存：<b style="color:${qty > 0 ? '#059669' : '#94a3b8'}">${qty}</b></div>`
      },
    },
    xAxis: {
      type: 'category',
      data: hm.xLabels,
      axisLabel: { color: '#667085', fontSize: 10, rotate: 30 },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      splitArea: { show: true, areaStyle: { color: ['rgba(248,250,252,0.6)', 'rgba(255,255,255,0.6)'] } },
    },
    yAxis: {
      type: 'category',
      data: hm.yLabels,
      axisLabel: { color: '#475467', fontSize: 11, fontWeight: 500 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    visualMap: {
      min: 0,
      max: Math.max(hm.maxVal || 1, 1),
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 14,
      itemHeight: 120,
      textStyle: { color: '#667085', fontSize: 11 },
      inRange: {
        color: ['#f0fdf4', '#bbf7d0', '#4ade80', '#16a34a', '#065f46']
      },
    },
    series: [{
      type: 'heatmap',
      data: hm.data,
      label: {
        show: hm.data.length <= 80,
        formatter: (params) => params.value[2] || '',
        fontSize: 10,
        color: '#374151',
      },
      emphasis: {
        itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.2)' },
      },
      itemStyle: {
        borderColor: '#fff',
        borderWidth: 2,
        borderRadius: 4,
      },
    }],
  }, true)
  heatmapChart.resize()
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
    await nextTick()
    renderChart()
    renderHeatmap()
  } catch (error) {
    ElMessage.error('读取覆盖图失败')
  } finally {
    loading.value = false
  }
}

function handleResize() {
  chart?.resize()
  heatmapChart?.resize()
}

onMounted(() => {
  load()
  window.addEventListener('resize', handleResize)
})

watch(activeCategory, () => {
  packageFilter.value = ''
  load()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  heatmapChart?.dispose()
})
</script>

<style scoped>
.coverage-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--cw-border);
  border-radius: 18px;
  background: #fff;
  box-shadow: var(--cw-shadow-soft);
}

.coverage-hero h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 760;
}

.coverage-hero p {
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
  box-shadow: var(--cw-shadow-soft);
}

.summary-card span {
  color: var(--cw-muted);
  font-size: 12px;
}

.summary-card strong {
  font-size: 26px;
  font-weight: 800;
  line-height: 1.1;
}

.summary-card small {
  color: var(--cw-muted);
  font-size: 11px;
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

.dual-chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  gap: 14px;
}

.coverage-panel {
  min-height: 400px;
}

.coverage-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.coverage-head h2 {
  margin: 0;
  font-size: 16px;
}

.coverage-head span {
  color: var(--cw-muted);
  font-size: 12px;
}

.coverage-chart {
  width: 100%;
  height: 340px;
}

.coverage-side-panel {
  background: var(--cw-panel);
}

.side-grid {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.range-card {
  display: grid;
  gap: 4px;
  padding: 14px;
  border: 1px solid var(--cw-border);
  border-radius: 14px;
  background: #fff;
}

.range-card small {
  color: var(--cw-muted);
  font-size: 12px;
}

.range-card strong {
  font-size: 18px;
  font-weight: 700;
  color: var(--cw-text);
}

.range-card span {
  color: var(--cw-muted);
  font-size: 12px;
}

.package-stack {
  display: grid;
  gap: 8px;
}

.package-row {
  display: grid;
  gap: 4px;
}

.package-row > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.package-row strong {
  font-size: 13px;
}

.package-row span {
  color: var(--cw-muted);
  font-size: 12px;
}

.mini-bar {
  height: 6px;
  border-radius: 999px;
  background: #eef2f7;
  overflow: hidden;
}

.mini-bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-head h2 {
  margin: 0;
  font-size: 16px;
}

.section-head span {
  color: var(--cw-muted);
  font-size: 13px;
}

.density-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.density-strip span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  height: 28px;
  padding: 0 6px;
  border-radius: 6px;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  text-shadow: 0 1px 2px rgba(0,0,0,0.2);
  cursor: default;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}

.density-strip span:hover {
  transform: scale(1.15);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  z-index: 1;
}

.coverage-table {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}

.coverage-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--cw-border);
  border-radius: 12px;
  background: #fff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.coverage-row:hover {
  border-color: #bfdbfe;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
}

.value-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 52px;
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  text-shadow: 0 1px 2px rgba(0,0,0,0.15);
  white-space: nowrap;
}

.coverage-row strong {
  font-size: 13px;
}

.coverage-row span {
  color: var(--cw-muted);
  font-size: 12px;
}

.coverage-row small {
  color: var(--cw-muted);
  font-size: 11px;
}

@media (max-width: 1100px) {
  .dual-chart-grid {
    grid-template-columns: 1fr;
  }
  .side-grid {
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
  .coverage-chart {
    height: 280px;
  }
}

@media (max-width: 460px) {
  .coverage-summary {
    grid-template-columns: 1fr;
  }
}
</style>
