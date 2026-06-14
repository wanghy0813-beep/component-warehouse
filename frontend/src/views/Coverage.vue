<template>
  <section class="page coverage-page">
    <div class="coverage-hero">
      <div>
        <span class="eyebrow">Passive Coverage</span>
        <h1>规格覆盖图</h1>
        <p>用一张对数轴地图看清电阻、电容、电感的规格、封装和库存覆盖，采购前先确认哪里缺、哪里重复。</p>
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

    <section class="coverage-grid" v-loading="loading">
      <article class="panel coverage-panel">
        <div class="coverage-head">
          <div>
            <h2>{{ activeData.category || activeCategory }}</h2>
            <span>{{ activeData.items?.length || 0 }} 个可解析规格 · {{ activeData.unparsed_count || 0 }} 个待整理</span>
          </div>
          <el-tag effect="plain">{{ activeData.unit || unitLabel }}</el-tag>
        </div>
        <div ref="chartRef" class="coverage-chart"></div>
        <el-empty v-if="!loading && !(activeData.items || []).length" description="暂无可绘制规格" :image-size="86" />
      </article>

      <aside class="panel coverage-side">
        <div class="section-head">
          <h2>覆盖摘要</h2>
          <span>{{ activeCategory }}</span>
        </div>
        <div class="range-card">
          <small>规格范围</small>
          <strong>{{ rangeSummary.min }} - {{ rangeSummary.max }}</strong>
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
      </aside>
    </section>

    <section class="panel density-panel">
      <div class="section-head">
        <div>
          <h2>规格密度</h2>
          <span>每个色块代表一个可用规格，颜色按封装区分</span>
        </div>
      </div>
      <div class="density-strip">
        <span
          v-for="item in visibleItems"
          :key="`density-${item.id}`"
          :title="`${item.display_value} ${item.model || item.name}`"
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
import { ScatterChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { getComponentCoverage } from '../api/client'

echarts.use([ScatterChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const categoryOptions = ['电阻', '电容', '电感']
const activeCategory = ref('电阻')
const packageFilter = ref('')
const onlyAvailable = ref(true)
const loading = ref(false)
const coverage = ref([])
const chartRef = ref(null)
let chart

const activeData = computed(() => coverage.value.find((item) => item.category === activeCategory.value) || {})
const unitLabel = computed(() => ({ 电阻: 'Ω', 电容: 'F', 电感: 'H' }[activeCategory.value] || '')
)
const packageOptions = computed(() => activeData.value.packages || [])
const visibleItems = computed(() => activeData.value.items || [])
const palette = ['#2563eb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#64748b']

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
    ? [['MΩ', 1e6], ['kΩ', 1e3], ['Ω', 1]]
    : unit === 'F'
      ? [['mF', 1e-3], ['µF', 1e-6], ['nF', 1e-9], ['pF', 1e-12]]
      : [['mH', 1e-3], ['µH', 1e-6], ['nH', 1e-9]]
  const picked = ranges.find(([, scale]) => Math.abs(numeric) >= scale) || ranges[ranges.length - 1]
  return `${Number((numeric / picked[1]).toPrecision(4))}${picked[0]}`
}

function renderChart() {
  if (!chartRef.value) return
  chart ||= echarts.init(chartRef.value)
  const data = activeData.value
  const items = data.items || []
  const packages = [...new Set(items.map((item) => item.package || item.normalized_spec || '未标封装'))]
  const positives = items.map((item) => Number(item.value)).filter((value) => value > 0)
  const zeroFloor = positives.length ? Math.min(...positives) / 10 : 1
  const series = packages.map((pkg, packageIndex) => ({
    name: pkg,
    type: 'scatter',
    itemStyle: { color: colorForPackage(pkg), borderColor: '#fff', borderWidth: 1 },
    emphasis: { focus: 'series', scale: true },
    symbolSize: (point) => Math.max(10, Math.min(34, 8 + Math.sqrt(point[2] || 0) * 3)),
    data: items
      .filter((item) => (item.package || item.normalized_spec || '未标封装') === pkg)
      .map((item) => [Number(item.value) > 0 ? item.value : zeroFloor, packageIndex, item.available_quantity, item]),
  }))
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 52, right: 24, top: 28, bottom: 58 },
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const item = params.data[3]
        return [
          `<strong>${item.display_value}</strong>`,
          item.model || item.name,
          `封装：${item.package || item.normalized_spec || '未标封装'}`,
          `总量：${item.quantity} / 可用：${item.available_quantity}`,
        ].join('<br/>')
      },
    },
    legend: { bottom: 0, type: 'scroll', icon: 'circle', itemWidth: 9, itemHeight: 9 },
    xAxis: {
      type: 'log',
      min: zeroFloor / 2,
      name: data.unit || unitLabel.value,
      axisLabel: { formatter: (value) => formatValue(value, data.unit || unitLabel.value) },
      splitLine: { lineStyle: { color: '#e9eef6' } },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
    },
    yAxis: {
      type: 'category',
      data: packages,
      axisLabel: { color: '#667085' },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series,
  }, true)
  chart.resize()
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
  } catch (error) {
    ElMessage.error('读取覆盖图失败')
  } finally {
    loading.value = false
  }
}

function handleResize() {
  chart?.resize()
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
})
</script>

<style scoped>
.coverage-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.coverage-controls .el-select {
  width: 180px;
}

.coverage-panel {
  min-height: 420px;
}

.coverage-head,
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.coverage-head h2,
.section-head h2 {
  margin: 0;
  font-size: 18px;
}

.coverage-head span,
.section-head span {
  color: var(--cw-muted);
  font-size: 13px;
}

.coverage-chart {
  width: 100%;
  height: 340px;
}

.coverage-table {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}

.coverage-row {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--cw-border);
  border-radius: 10px;
  background: #fff;
}

.coverage-row span,
.coverage-row small {
  color: var(--cw-muted);
}

@media (max-width: 760px) {
  .coverage-controls {
    align-items: stretch;
  }

  .coverage-controls .el-segmented,
  .coverage-controls .el-select {
    width: 100%;
  }

  .coverage-chart {
    height: 300px;
  }
}
</style>
