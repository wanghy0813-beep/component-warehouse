<template>
  <section class="page dashboard-page">
    <header class="dashboard-hero">
      <div class="hero-copy">
        <span class="hero-eyebrow">PERSONAL INVENTORY</span>
        <h1>库存工作台</h1>
        <p>先看可用量、库存价值和需要处理的异常，再进入具体器件。</p>
      </div>
      <div class="hero-actions">
        <el-button :icon="Refresh" @click="load">刷新数据</el-button>
        <el-button :icon="Box" type="primary" @click="go('/components')">打开元器件库</el-button>
        <el-button :icon="Files" @click="go('/projects')">项目</el-button>
      </div>
    </header>

    <section class="primary-metrics" aria-label="库存主要指标">
      <article v-for="(item, index) in primaryMetrics" :key="item.label" class="primary-metric" :class="item.tone">
        <div class="metric-topline">
          <span>{{ item.label }}</span>
          <em>0{{ index + 1 }}</em>
        </div>
        <div class="metric-value-line">
          <strong :title="String(item.value)">{{ item.value }}</strong>
          <el-button
            v-if="item.sensitive"
            class="metric-visibility"
            text
            circle
            :icon="showInventoryValues ? View : Hide"
            :aria-label="showInventoryValues ? '隐藏库存估值' : '显示库存估值'"
            @click="toggleInventoryValues"
          />
        </div>
        <small>{{ item.hint }}</small>
      </article>
    </section>

    <section class="inventory-context" aria-label="库存补充信息">
      <div v-for="item in secondaryMetrics" :key="item.label">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.unit }}</small>
      </div>
    </section>

    <section class="panel structure-panel deferred-section">
      <div class="section-head">
        <div>
          <span class="section-kicker">库存结构</span>
          <h2>主要分类</h2>
          <p>默认显示数量最高且日常最常用的 6 类。</p>
        </div>
        <el-button v-if="importantCategories.length > 6" text @click="categoryExpanded = !categoryExpanded">
          {{ categoryExpanded ? '收起' : `查看全部 ${importantCategories.length} 类` }}
        </el-button>
      </div>
      <div class="category-ledger">
        <button v-for="item in visibleCategories" :key="item.name" type="button" @click="goCategory(item.name)">
          <div class="category-line">
            <strong>{{ item.name }}</strong>
            <span>{{ item.value || 0 }} 种</span>
            <b>{{ item.quantity || 0 }}</b>
          </div>
          <div class="category-track"><i :style="{ width: categoryShare(item) }" /></div>
          <small :class="{ danger: item.low_stock > 0 }">{{ item.low_stock ? `${item.low_stock} 项低库存` : '库存状态正常' }}</small>
        </button>
      </div>
    </section>

    <div class="dashboard-grid deferred-section">
      <section class="panel focus-panel">
        <div class="section-head compact">
          <div>
            <span class="section-kicker">ACTION</span>
            <h2>需要处理</h2>
          </div>
          <span>{{ actionItems.length }} 项</span>
        </div>
        <div class="focus-list">
          <article v-for="item in visibleActionItems" :key="`${item.type}-${item.title}`" class="focus-row" :class="item.severity">
            <i />
            <div><strong>{{ item.title }}</strong><span>{{ item.hint }}</span></div>
          </article>
          <el-empty v-if="!actionItems.length" description="暂无需要处理的事项" :image-size="64" />
        </div>
        <el-button v-if="actionItems.length > 4" class="list-more" text @click="actionExpanded = !actionExpanded">
          {{ actionExpanded ? '收起' : `查看其余 ${actionItems.length - 4} 项` }}
        </el-button>
      </section>

      <section class="panel focus-panel">
        <div class="section-head compact">
          <div>
            <span class="section-kicker">STOCK GUARD</span>
            <h2>低库存元器件</h2>
          </div>
          <span>{{ summary.low_stock || 0 }} 项</span>
        </div>
        <div class="focus-list low-stock-list">
          <button
            v-for="item in visibleLowStockItems"
            :key="item.id"
            type="button"
            @click="go(`/components?component=${encodeURIComponent(item.warehouse_code || item.id)}`)"
          >
            <div>
              <strong>{{ item.normalized_spec || item.model || item.name }}</strong>
              <span>{{ item.category?.name || '未分类' }}</span>
            </div>
            <small>可用 <b>{{ item.available_quantity || 0 }}</b> / 安全 {{ item.safety_quantity || 0 }}</small>
          </button>
          <el-empty v-if="!lowStockItems.length" description="没有低库存提醒" :image-size="64" />
        </div>
        <el-button v-if="lowStockItems.length > 4" class="list-more" text @click="lowStockExpanded = !lowStockExpanded">
          {{ lowStockExpanded ? '收起' : `查看其余 ${lowStockItems.length - 4} 项` }}
        </el-button>
      </section>
    </div>

    <nav class="quick-dock deferred-section" aria-label="常用入口">
      <span>常用入口</span>
      <button @click="go('/components')"><small>查找 / 入库</small><strong>元器件</strong></button>
      <button @click="go('/coverage')"><small>查看规格</small><strong>覆盖图</strong></button>
      <button v-if="FEATURE_EDA_ENABLED" @click="go('/eda')"><small>管理资料</small><strong>EDA 库</strong></button>
      <button @click="go('/about')"><small>备份 / 日志</small><strong>管理</strong></button>
    </nav>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from '../shared/elementApi'
import { useRouter } from 'vue-router'
import { Box, Files, Hide, Refresh, View } from '@element-plus/icons-vue'
import { dashboardSummary } from '../api/client'
import { FEATURE_EDA_ENABLED } from '../shared/features'

const router = useRouter()
const summary = ref({})
const categoryExpanded = ref(false)
const actionExpanded = ref(false)
const lowStockExpanded = ref(false)
const INVENTORY_VALUE_VISIBILITY_KEY = 'cw.dashboard.inventory-values-visible'
const showInventoryValues = ref(localStorage.getItem(INVENTORY_VALUE_VISIBILITY_KEY) !== 'hidden')
const priority = ['电阻', '电容', '电感', '芯片', '电源', '接口', '连接件', '传感器', '保护器件', '开关', '开发板']

function inventoryValue(value) {
  if (!showInventoryValues.value) return '••••••'
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  return `¥${new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount)}`
}

function toggleInventoryValues() {
  showInventoryValues.value = !showInventoryValues.value
  localStorage.setItem(INVENTORY_VALUE_VISIBILITY_KEY, showInventoryValues.value ? 'visible' : 'hidden')
}

const primaryMetrics = computed(() => [
  { label: '元器件种类', value: summary.value.total_kinds || 0, hint: '当前有效库存条目', tone: 'tone-mineral' },
  { label: '可用库存', value: summary.value.available_quantity || 0, hint: `可用库存总值 ${inventoryValue(summary.value.available_inventory_value_total)} · 已扣除项目预留与设备占用`, tone: 'tone-sage' },
  { label: '全部库存总值', value: inventoryValue(summary.value.inventory_value_total), hint: `已计价 ${summary.value.priced_component_count || 0} 种 · 未计价 ${summary.value.unpriced_component_count || 0} 种`, tone: 'tone-copper', sensitive: true },
  { label: '低库存', value: summary.value.low_stock || 0, hint: '常用件低于安全库存', tone: 'tone-alert' }
])

const secondaryMetrics = computed(() => [
  { label: '库存总量', value: summary.value.total_quantity || 0, unit: '件' },
  { label: '设备占用', value: summary.value.occupied_quantity || 0, unit: '台' },
  { label: '常用器件', value: summary.value.common_count || 0, unit: '种' },
  { label: '分类数量', value: summary.value.category_count || 0, unit: '类' }
])

const categoryStats = computed(() => summary.value.category_stats || [])
const importantCategories = computed(() => {
  const order = new Map(priority.map((name, index) => [name, index]))
  return [...categoryStats.value]
    .filter((item) => Number(item.value || item.quantity || 0) > 0)
    .sort((a, b) => {
      const ai = order.has(a.name) ? order.get(a.name) : 100
      const bi = order.has(b.name) ? order.get(b.name) : 100
      if (ai !== bi) return ai - bi
      return Number(b.quantity || 0) - Number(a.quantity || 0)
    })
    .slice(0, 12)
})
const visibleCategories = computed(() => categoryExpanded.value ? importantCategories.value : importantCategories.value.slice(0, 6))
const actionItems = computed(() => summary.value.action_items || [])
const lowStockItems = computed(() => summary.value.low_stock_items || [])
const visibleActionItems = computed(() => actionExpanded.value ? actionItems.value : actionItems.value.slice(0, 4))
const visibleLowStockItems = computed(() => lowStockExpanded.value ? lowStockItems.value : lowStockItems.value.slice(0, 4))

function categoryShare(item) {
  const maximum = Math.max(1, ...importantCategories.value.map((row) => Number(row.quantity || 0)))
  return `${Math.max(3, Math.round(Number(item.quantity || 0) / maximum * 100))}%`
}

async function load() {
  try {
    summary.value = await dashboardSummary()
  } catch (error) {
    ElMessage.error('读取仪表盘失败')
  }
}

function go(path) { router.push(path) }
function goCategory(name) { router.push({ path: '/components', query: { keyword: name } }) }
onMounted(load)
</script>

<style scoped>
.dashboard-page { gap: 18px; }

.dashboard-hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  min-height: 158px;
  padding: 28px 30px;
  overflow: hidden;
  border: 1px solid rgba(104, 145, 151, .28);
  border-radius: 24px;
  color: #f3f7f7;
  background: linear-gradient(132deg, #172b30 0%, #24484e 72%, #31575b 100%);
  box-shadow: 0 20px 48px rgba(24, 43, 48, .18);
}

.dashboard-hero::before {
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(225, 233, 229, .72), transparent);
  content: '';
}

.dashboard-hero::after {
  position: absolute;
  width: 360px;
  height: 360px;
  right: -130px;
  top: -210px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(183, 121, 71, .34), transparent 68%);
  content: '';
  pointer-events: none;
}

.hero-copy { position: relative; z-index: 1; min-width: 0; }
.hero-eyebrow { color: #9fc2c4; font-size: 11px; font-weight: 760; letter-spacing: .16em; }
.dashboard-hero h1 { margin: 8px 0 8px; font-size: clamp(30px, 4vw, 44px); line-height: 1; }
.dashboard-hero p { max-width: 650px; margin: 0; color: #c6d4d5; line-height: 1.6; }
.hero-actions { position: relative; z-index: 1; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 9px; }
.hero-actions :deep(.el-button) { border-color: rgba(225, 235, 234, .32); color: #e8efef; background: rgba(255, 255, 255, .07); }
.hero-actions :deep(.el-button--primary) { border-color: #b45a22; color: #fff; background: #b45a22; }

.primary-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.primary-metric {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 154px;
  flex-direction: column;
  justify-content: space-between;
  padding: 22px 22px 20px;
  overflow: hidden;
  border: 1px solid var(--cw-border);
  border-radius: 20px;
  background: linear-gradient(145deg, #fcfdfc, #f4f7f6);
  box-shadow: var(--cw-shadow-soft);
}

.primary-metric::after {
  position: absolute;
  inset: auto 0 0;
  height: 4px;
  background: var(--tone);
  content: '';
}

.metric-topline { display: flex; justify-content: space-between; gap: 12px; color: #637177; font-size: 13px; }
.metric-topline em { color: #60747d; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; font-style: normal; }
.metric-value-line { display: flex; align-items: center; gap: 8px; min-width: 0; margin: 13px 0 9px; }
.primary-metric strong { min-width: 0; overflow: hidden; color: #202d32; font-size: clamp(28px, 2.6vw, 38px); line-height: 1.1; text-overflow: ellipsis; white-space: nowrap; }
.primary-metric small { min-height: 34px; color: var(--cw-muted); font-size: 12px; line-height: 1.45; }
.metric-visibility { flex: 0 0 auto; color: var(--tone); }
.tone-mineral { --tone: #006b78; }
.tone-sage { --tone: #2f7565; }
.tone-copper { --tone: #b45a22; }
.tone-alert { --tone: #a63f3b; }

.inventory-context {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--cw-border);
  border-radius: 16px;
  background: rgba(248, 250, 249, .78);
}

.inventory-context > div { display: flex; align-items: baseline; gap: 8px; min-width: 0; padding: 15px 20px; }
.inventory-context > div + div { border-left: 1px solid var(--cw-border); }
.inventory-context span { min-width: 0; overflow: hidden; color: #6a767b; text-overflow: ellipsis; white-space: nowrap; }
.inventory-context strong { color: #27363b; font-size: 19px; }
.inventory-context small { color: var(--cw-muted); }

.panel { padding: 22px; }
.deferred-section { content-visibility: auto; contain-intrinsic-size: auto 420px; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.section-head > div { min-width: 0; }
.section-head h2 { margin: 3px 0 4px; color: #203036; font-size: 21px; }
.section-head p { margin: 0; color: var(--cw-muted); font-size: 12px; }
.section-head > span { color: var(--cw-muted); font-size: 13px; }
.section-kicker { color: #50777b; font-size: 10px; font-weight: 780; letter-spacing: .14em; }

.category-ledger { display: grid; grid-template-columns: 1fr 1fr; column-gap: 30px; }
.category-ledger button { min-width: 0; padding: 15px 0 13px; border: 0; border-bottom: 1px solid #dce4e4; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.category-ledger button:nth-last-child(-n + 2) { border-bottom-color: transparent; }
.category-line { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: baseline; gap: 8px; min-width: 0; }
.category-line strong { overflow: hidden; color: #26353a; text-overflow: ellipsis; white-space: nowrap; }
.category-line span { color: var(--cw-muted); font-size: 12px; }
.category-line b { min-width: 56px; color: #315f63; font-size: 20px; text-align: right; }
.category-track { height: 3px; margin: 9px 0 7px; overflow: hidden; border-radius: 2px; background: #e3e9e8; }
.category-track i { display: block; height: 100%; border-radius: inherit; background: #6b9998; }
.category-ledger small { color: var(--cw-muted); font-size: 11px; }
.category-ledger small.danger { color: #a84e4b; }

.dashboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.section-head.compact { align-items: center; margin-bottom: 10px; }
.focus-list { display: grid; }
.focus-row,
.low-stock-list button { display: grid; min-width: 0; border: 0; border-bottom: 1px solid #dde4e4; background: transparent; }
.focus-row:last-child,
.low-stock-list button:last-child { border-bottom: 0; }
.focus-row { grid-template-columns: 8px minmax(0, 1fr); gap: 12px; align-items: center; padding: 14px 2px; }
.focus-row i { width: 7px; height: 7px; border-radius: 50%; background: #728589; box-shadow: 0 0 0 4px rgba(114, 133, 137, .10); }
.focus-row.warning i { background: #896512; }
.focus-row.danger i { background: #a63f3b; }
.focus-row div { min-width: 0; display: grid; gap: 4px; }
.focus-row strong,
.focus-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.focus-row strong { color: #26343a; }
.focus-row span { color: var(--cw-muted); font-size: 12px; }

.low-stock-list button { grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: center; width: 100%; padding: 14px 2px; color: inherit; text-align: left; cursor: pointer; }
.low-stock-list button > div { min-width: 0; display: grid; gap: 4px; }
.low-stock-list strong,
.low-stock-list span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.low-stock-list span { color: var(--cw-muted); font-size: 12px; }
.low-stock-list small { color: #737f84; white-space: nowrap; }
.low-stock-list b { color: #a84e4b; }
.list-more { width: 100%; margin-top: 6px; }

.quick-dock {
  display: grid;
  grid-template-columns: auto repeat(4, minmax(130px, 1fr));
  gap: 0;
  align-items: stretch;
  overflow: hidden;
  border: 1px solid var(--cw-border);
  border-radius: 17px;
  background: #263a3f;
  box-shadow: var(--cw-shadow-soft);
}
.quick-dock > span { display: grid; place-items: center; padding: 16px 22px; color: #a9bcbc; font-size: 12px; letter-spacing: .08em; }
.quick-dock button { display: grid; gap: 3px; padding: 14px 18px; border: 0; border-left: 1px solid rgba(220, 232, 231, .14); color: #f0f5f4; background: transparent; text-align: left; cursor: pointer; }
.quick-dock button:hover { background: rgba(255, 255, 255, .05); }
.quick-dock small { color: #9cafb0; }

@media (max-width: 1100px) {
  .primary-metrics { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 860px) {
  .dashboard-hero { display: grid; padding: 24px; }
  .hero-actions { justify-content: flex-start; }
  .dashboard-grid { grid-template-columns: 1fr; }
  .category-ledger { grid-template-columns: 1fr; }
  .category-ledger button:nth-last-child(2) { border-bottom-color: #dce4e4; }
  .quick-dock { grid-template-columns: 1fr 1fr; }
  .quick-dock > span { grid-column: 1 / -1; place-items: start; }
  .quick-dock button:nth-of-type(odd) { border-left: 0; }
}

@media (max-width: 620px) {
  .dashboard-page { gap: 13px; }
  .dashboard-hero { min-height: 0; padding: 22px 18px; border-radius: 19px; }
  .hero-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .hero-actions :deep(.el-button) { width: 100%; margin-left: 0; }
  .hero-actions :deep(.el-button--primary) { grid-column: 1 / -1; grid-row: 1; }
  .primary-metrics { gap: 10px; }
  .primary-metric { min-height: 142px; padding: 18px 16px; }
  .primary-metric strong { font-size: 27px; }
  .inventory-context { grid-template-columns: 1fr 1fr; }
  .inventory-context > div { padding: 13px 14px; }
  .inventory-context > div:nth-child(3) { border-left: 0; border-top: 1px solid var(--cw-border); }
  .inventory-context > div:nth-child(4) { border-top: 1px solid var(--cw-border); }
  .panel { padding: 17px; border-radius: 17px; }
  .low-stock-list button { grid-template-columns: 1fr; gap: 5px; }
}

@media (max-width: 390px) {
  .primary-metrics { grid-template-columns: 1fr; }
  .primary-metric { min-height: 130px; }
  .quick-dock { grid-template-columns: 1fr; }
  .quick-dock > span { grid-column: auto; }
  .quick-dock button { border-left: 0; border-top: 1px solid rgba(220, 232, 231, .14); }
}
</style>
