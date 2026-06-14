<template>
  <section class="page dashboard-page">
    <div class="dashboard-hero">
      <div>
        <h1 class="page-title">库存仪表盘</h1>
        <p class="page-subtitle">快速查看库存规模、分类结构和最近项目 BOM 状态</p>
      </div>
      <div class="hero-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button :icon="Box" type="primary" @click="go('/components')">元器件库</el-button>
        <el-button :icon="Files" plain @click="go('/projects')">项目 BOM</el-button>
      </div>
    </div>

    <div class="metric-grid dashboard-metrics">
      <div v-for="item in metrics" :key="item.label" class="metric dashboard-metric">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
        <div class="metric-hint">{{ item.hint }}</div>
      </div>
    </div>

    <div class="dashboard-focus-grid">
      <section class="panel match-overview-panel">
        <div class="section-head">
          <h2>项目 BOM 匹配态势</h2>
          <span>{{ matchOverview.total ? `最近项目 ${matchOverview.total} 行 BOM` : '导入 BOM 后显示' }}</span>
        </div>
        <div class="match-overview-body">
          <div class="match-score">
            <strong>{{ matchOverview.rate }}<small>%</small></strong>
            <span>库内已匹配</span>
            <div class="segmented-progress">
              <span class="segment matched" :style="{ width: `${matchOverview.matchedPercent}%` }"></span>
              <span class="segment review" :style="{ width: `${matchOverview.reviewPercent}%` }"></span>
              <span class="segment missing" :style="{ width: `${matchOverview.missingPercent}%` }"></span>
            </div>
            <div class="match-legend">
              <span><i class="dot matched"></i>已匹配 {{ matchOverview.matched }}</span>
              <span><i class="dot review"></i>需确认 {{ matchOverview.review }}</span>
              <span><i class="dot missing"></i>待采购 {{ matchOverview.missing }}</span>
            </div>
          </div>
          <div ref="projectMatchChartRef" class="chart compact-chart"></div>
        </div>
      </section>

      <section class="panel stock-usage-panel">
        <div class="section-head">
          <h2>库存占用</h2>
          <span>可用 {{ summary.available_quantity || 0 }}</span>
        </div>
        <div class="stock-usage-body">
          <div ref="stockChartRef" class="chart compact-chart"></div>
          <div class="stock-facts">
            <div><span>库存总量</span><strong>{{ summary.total_quantity || 0 }}</strong></div>
            <div><span>BOM 预占</span><strong>{{ summary.reserved_quantity || 0 }}</strong></div>
            <div><span>低库存</span><strong>{{ summary.low_stock || 0 }}</strong></div>
            <div><span>常用器件</span><strong>{{ summary.common_count || 0 }}</strong></div>
          </div>
        </div>
      </section>
    </div>

    <div class="dashboard-grid">
      <section class="panel inventory-panel">
        <div class="section-head">
          <h2>库存分类</h2>
          <span>{{ summary.category_count || 0 }} 类</span>
        </div>
        <div class="inventory-body">
          <div ref="categoryChartRef" class="chart"></div>
          <div class="category-list">
            <div v-for="item in topCategories" :key="item.name" class="category-row">
              <span>{{ item.name }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
        </div>
      </section>

      <section class="panel project-panel">
        <div class="section-head">
          <h2>最近项目 BOM</h2>
          <el-button size="small" text @click="go('/projects')">查看</el-button>
        </div>
        <div class="project-list">
          <article v-for="project in projectSnapshots" :key="project.id" class="project-card">
            <div>
              <strong>{{ project.name }}</strong>
              <span>{{ project.status || 'active' }} · 匹配 {{ projectMatchStats(project).rate }}%</span>
            </div>
            <div class="project-match-visual">
              <div class="mini-progress">
                <span class="segment matched" :style="{ width: `${projectMatchStats(project).matchedPercent}%` }"></span>
                <span class="segment review" :style="{ width: `${projectMatchStats(project).reviewPercent}%` }"></span>
                <span class="segment missing" :style="{ width: `${projectMatchStats(project).missingPercent}%` }"></span>
              </div>
              <div class="bom-counts">
                <span>物料 {{ project.bom_total }}</span>
                <span>满足 {{ project.satisfied }}</span>
                <strong :class="{ danger: project.shortage > 0 }">缺料 {{ project.shortage }}</strong>
                <strong v-if="project.bom_match_total" :class="{ danger: project.bom_match_missing > 0 }">待采购 {{ project.bom_match_missing }}</strong>
              </div>
            </div>
          </article>
          <el-empty v-if="!projectSnapshots.length" description="暂无项目" :image-size="72" />
        </div>
      </section>
    </div>

    <section class="panel quick-panel">
      <div class="section-head">
        <h2>今日工作入口</h2>
        <span>围绕项目、库存和覆盖图快速行动</span>
      </div>
      <div class="quick-grid">
        <button class="quick-item" @click="go('/projects')">
          <small>BOM 项目</small>
          <strong>{{ projectSnapshots.length }}</strong>
        </button>
        <button class="quick-item" @click="go('/components')">
          <small>可用库存</small>
          <strong>{{ summary.available_quantity || 0 }}</strong>
        </button>
        <button class="quick-item" @click="go('/coverage')">
          <small>规格覆盖</small>
          <strong>{{ topCategories.length }}</strong>
        </button>
        <button class="quick-item" @click="go('/components')">
          <small>AI 待处理</small>
          <strong>{{ summary.ai_pending || 0 }}</strong>
        </button>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Box, Files, Refresh } from '@element-plus/icons-vue'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { dashboardSummary } from '../api/client'

echarts.use([BarChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const router = useRouter()
const summary = ref({})
const categoryChartRef = ref(null)
const projectMatchChartRef = ref(null)
const stockChartRef = ref(null)
let categoryChart
let projectMatchChart
let stockChart

const metrics = computed(() => [
  { label: '元器件种类', value: summary.value.total_kinds || 0, hint: '已入库条目' },
  { label: '库存总量', value: summary.value.total_quantity || 0, hint: '所有库存数量' },
  { label: 'BOM 预占', value: summary.value.reserved_quantity || 0, hint: '项目锁定数量' },
  { label: '最近项目', value: projectSnapshots.value.length, hint: '首页展示项目' }
])

const topCategories = computed(() => (summary.value.category_stats || []).filter((item) => item.value > 0).slice(0, 8))
const projectSnapshots = computed(() => summary.value.project_snapshots || [])
const matchOverview = computed(() => {
  const totals = projectSnapshots.value.reduce(
    (acc, project) => {
      const stats = matchStats(project)
      acc.total += stats.total
      acc.matched += stats.matched
      acc.review += stats.review
      acc.missing += stats.missing
      return acc
    },
    { total: 0, matched: 0, review: 0, missing: 0 }
  )
  return matchStats(totals)
})

function matchStats(source) {
  const hasImportSnapshot = Number(source?.total ?? source?.bom_match_total) > 0
  const total = Math.max(0, Number(source?.total ?? source?.bom_match_total ?? source?.bom_total) || 0)
  const matched = Math.max(0, Number(source?.matched ?? (hasImportSnapshot ? source?.bom_match_matched : source?.satisfied)) || 0)
  const review = Math.max(0, Number(source?.review ?? (hasImportSnapshot ? source?.bom_match_review : 0)) || 0)
  const missing = Math.max(0, Number(source?.missing ?? (hasImportSnapshot ? source?.bom_match_missing : source?.shortage)) || 0)
  const percent = (value) => (total ? Math.round((value / total) * 100) : 0)
  return {
    total,
    matched,
    review,
    missing,
    rate: percent(matched),
    matchedPercent: percent(matched),
    reviewPercent: percent(review),
    missingPercent: percent(missing)
  }
}

function projectMatchStats(project) {
  return matchStats(project)
}

const chartPalette = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#475569', '#0d9488', '#ea580c', '#6366f1', '#ca8a04', '#be185d', '#0369a1', '#65a30d', '#b91c1c', '#8b5cf6', '#0e7490']

function renderCharts() {
  if (categoryChartRef.value) {
    categoryChart ||= echarts.init(categoryChartRef.value)
    const stats = (summary.value.category_stats || []).filter((item) => item.value > 0)
    categoryChart.setOption({
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e5e7eb',
        borderWidth: 1,
        formatter: (params) => `<div style="font-weight:600">${params.name}</div><div>${params.value} 种 · ${params.percent}%</div>`,
      },
      legend: { show: false },
      color: chartPalette,
      series: [
        {
          type: 'pie',
          radius: ['50%', '74%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          label: { color: '#475467', fontSize: 11, formatter: '{b}' },
          labelLine: { length: 12, length2: 8 },
          emphasis: { scaleSize: 6 },
          itemStyle: { borderColor: '#fff', borderWidth: 2 },
          data: stats,
        },
      ],
    })
    categoryChart.resize()
  }

  if (projectMatchChartRef.value) {
    projectMatchChart ||= echarts.init(projectMatchChartRef.value)
    const projects = projectSnapshots.value.slice(0, 5)
    projectMatchChart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e5e7eb',
        borderWidth: 1,
        formatter: (params) => {
          const name = params[0]?.name || ''
          const lines = params.map((p) => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:6px"></span>${p.seriesName} <b>${p.value}</b>`)
          return `<div style="font-weight:600;margin-bottom:4px">${name}</div>${lines.join('<br>')}`
        },
      },
      grid: { left: 8, right: 8, top: 18, bottom: 4, containLabel: true },
      xAxis: { type: 'value', max: 'dataMax', splitLine: { lineStyle: { color: '#eef2f7' } } },
      yAxis: { type: 'category', data: projects.map((project) => project.name), axisTick: { show: false }, axisLine: { show: false } },
      series: [
        { name: '已匹配', type: 'bar', stack: 'total', barWidth: 12, itemStyle: { color: '#22c55e', borderRadius: [6, 0, 0, 6] }, data: projects.map((project) => projectMatchStats(project).matched) },
        { name: '需确认', type: 'bar', stack: 'total', barWidth: 12, itemStyle: { color: '#f59e0b' }, data: projects.map((project) => projectMatchStats(project).review) },
        { name: '待采购', type: 'bar', stack: 'total', barWidth: 12, itemStyle: { color: '#ef4444', borderRadius: [0, 6, 6, 0] }, data: projects.map((project) => projectMatchStats(project).missing) }
      ]
    })
    projectMatchChart.resize()
  }

  if (stockChartRef.value) {
    stockChart ||= echarts.init(stockChartRef.value)
    stockChart.setOption({
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e5e7eb',
        borderWidth: 1,
        formatter: (params) => `<div style="font-weight:600">${params.name}</div><div>${params.value} 个 · ${params.percent}%</div>`,
      },
      legend: { bottom: 0, icon: 'circle', textStyle: { fontSize: 12 } },
      series: [
        {
          type: 'pie',
          radius: ['56%', '78%'],
          center: ['50%', '44%'],
          label: { show: false },
          emphasis: { scaleSize: 6 },
          itemStyle: { borderColor: '#fff', borderWidth: 2 },
          data: [
            { name: '可用', value: summary.value.available_quantity || 0, itemStyle: { color: '#22c55e' } },
            { name: '预占', value: summary.value.reserved_quantity || 0, itemStyle: { color: '#3b82f6' } }
          ]
        }
      ]
    })
    stockChart.resize()
  }
}

async function load() {
  try {
    summary.value = await dashboardSummary()
    await nextTick()
    renderCharts()
  } catch (error) {
    ElMessage.error('读取仪表盘失败')
  }
}

function go(path) {
  router.push(path)
}

function handleResize() {
  categoryChart?.resize()
  projectMatchChart?.resize()
  stockChart?.resize()
}

onMounted(() => {
  load()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  categoryChart?.dispose()
  projectMatchChart?.dispose()
  stockChart?.dispose()
})
</script>

<style scoped>
.dashboard-hero {
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

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.dashboard-metrics {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.dashboard-metric {
  border-radius: 14px;
  background: #fff;
}

.metric-hint {
  margin-top: 6px;
  color: var(--cw-muted);
  font-size: 12px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr);
  gap: 14px;
}

.dashboard-focus-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
  gap: 14px;
}

.match-overview-panel {
  border-color: #dbeafe;
  background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
}

.match-overview-body {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 18px;
  align-items: center;
}

.match-score {
  display: grid;
  gap: 6px;
}

.match-score strong {
  color: #14532d;
  font-size: 46px;
  line-height: 1;
}

.match-score small {
  font-size: 20px;
}

.match-score span {
  color: var(--cw-muted);
}

.match-bars {
  display: grid;
  gap: 12px;
}

.segmented-progress,
.mini-progress {
  display: flex;
  overflow: hidden;
  border-radius: 999px;
  background: #eef2f7;
}

.segmented-progress {
  height: 14px;
}

.mini-progress {
  height: 8px;
}

.segment.matched {
  background: #22c55e;
}

.segment.review {
  background: #f59e0b;
}

.segment.missing {
  background: #ef4444;
}

.match-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  color: var(--cw-muted);
  font-size: 13px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 6px;
  border-radius: 999px;
}

.dot.matched {
  background: #22c55e;
}

.dot.review {
  background: #f59e0b;
}

.dot.missing {
  background: #ef4444;
}

.stock-usage-panel {
  background: rgba(255, 255, 255, 0.9);
}

.stock-usage-body {
  display: grid;
  grid-template-columns: minmax(150px, 0.9fr) minmax(140px, 1fr);
  gap: 14px;
  align-items: center;
}

.compact-chart {
  height: 220px;
}

.stock-facts {
  display: grid;
  gap: 8px;
}

.stock-facts div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 10px;
  border: 1px solid var(--cw-border);
  border-radius: 12px;
  background: #fff;
}

.stock-facts span {
  color: var(--cw-muted);
  font-size: 13px;
}

.stock-facts strong {
  color: var(--cw-text);
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

.inventory-body {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(180px, 0.55fr);
  gap: 14px;
  align-items: center;
}

.chart {
  height: 260px;
}

.category-list,
.project-list,
.quick-grid {
  display: grid;
  gap: 10px;
}

.category-row,
.project-card,
.quick-item {
  border: 1px solid var(--cw-border);
  border-radius: 14px;
  background: #fff;
}

.category-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
}

.category-row span,
.project-card span,
.quick-item small {
  color: var(--cw-muted);
}

.project-card {
  display: grid;
  grid-template-columns: minmax(0, 0.8fr) minmax(190px, 1fr);
  gap: 14px;
  align-items: center;
  padding: 12px;
}

.project-card strong,
.project-card span {
  display: block;
}

.project-card > div:first-child strong {
  color: var(--cw-text);
  font-size: 16px;
}

.project-card > div:first-child span {
  margin-top: 4px;
  font-size: 12px;
}

.bom-counts {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  color: var(--cw-muted);
  font-size: 13px;
}

.project-match-visual {
  display: grid;
  gap: 8px;
}

.bom-counts strong {
  color: var(--cw-text);
}

.bom-counts .danger {
  color: var(--cw-red);
}

.quick-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.quick-item {
  appearance: none;
  text-align: left;
  cursor: pointer;
  padding: 14px;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease;
}

.quick-item:hover {
  transform: translateY(-1px);
  border-color: #bfdbfe;
  background: #fbfdff;
}

.quick-item strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
}

@media (max-width: 1120px) {
  .dashboard-focus-grid,
  .dashboard-grid,
  .inventory-body,
  .quick-grid,
  .dashboard-metrics,
  .match-overview-body,
  .stock-usage-body {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .dashboard-hero,
  .project-card {
    align-items: stretch;
    grid-template-columns: 1fr;
  }

  .dashboard-hero {
    flex-direction: column;
  }

  .hero-actions,
  .hero-actions .el-button {
    width: 100%;
  }

  .hero-actions {
    display: grid;
    grid-template-columns: 1fr;
  }

  .bom-counts {
    justify-content: flex-start;
  }

  .chart {
    height: 220px;
  }
}
</style>
