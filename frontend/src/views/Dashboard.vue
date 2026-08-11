<template>
  <section class="page dashboard-page">
    <div class="dashboard-hero">
      <div>
        <h1 class="page-title">库存概览</h1>
        <p class="page-subtitle">只显示和日常拿料、补货、整理最相关的信息</p>
      </div>
      <div class="hero-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button :icon="Box" type="primary" @click="go('/components')">元器件库</el-button>
        <el-button :icon="Files" plain @click="go('/projects')">项目</el-button>
      </div>
    </div>

    <div class="metric-grid dashboard-metrics">
      <article v-for="item in metrics" :key="item.label" class="metric dashboard-metric" :class="item.tone">
        <span>{{ item.label }}</span>
        <el-button
          v-if="item.sensitive"
          class="metric-visibility"
          text
          circle
          :icon="showInventoryValues ? View : Hide"
          :aria-label="showInventoryValues ? '隐藏库存估值' : '显示库存估值'"
          @click="toggleInventoryValues"
        />
        <strong>{{ item.value }}</strong>
        <small>{{ item.hint }}</small>
      </article>
    </div>

    <section class="panel important-panel">
      <div class="section-head">
        <h2>重要分类库存</h2>
        <span>{{ importantCategories.length }} 类</span>
      </div>
      <div class="category-grid">
        <button v-for="item in importantCategories" :key="item.name" class="category-card" type="button" @click="goCategory(item.name)">
          <div>
            <strong>{{ item.name }}</strong>
            <span>{{ item.value || 0 }} 种</span>
          </div>
          <b>{{ item.quantity || 0 }}</b>
          <small :class="{ danger: item.low_stock > 0 }">低库存 {{ item.low_stock || 0 }}</small>
        </button>
      </div>
    </section>

    <div class="dashboard-grid">
      <section class="panel action-panel">
        <div class="section-head">
          <h2>需要处理</h2>
          <span>{{ actionItems.length }} 项</span>
        </div>
        <div class="action-list">
          <article v-for="item in actionItems" :key="`${item.type}-${item.title}`" class="action-item" :class="item.severity">
            <strong>{{ item.title }}</strong>
            <span>{{ item.hint }}</span>
          </article>
          <el-empty v-if="!actionItems.length" description="暂无需要处理的事项" :image-size="72" />
        </div>
      </section>

      <section class="panel low-stock-panel">
        <div class="section-head">
          <h2>低库存元器件</h2>
          <span>{{ summary.low_stock || 0 }} 项</span>
        </div>
        <div class="low-stock-list">
          <button v-for="item in lowStockItems" :key="item.id" type="button" @click="go(`/components?component=${encodeURIComponent(item.warehouse_code || item.id)}`)">
            <strong>{{ item.normalized_spec || item.model || item.name }}</strong>
            <span>{{ item.category?.name || '未分类' }} · 可用 {{ item.available_quantity || 0 }} · 安全 {{ item.safety_quantity || 0 }}</span>
          </button>
          <el-empty v-if="!lowStockItems.length" description="没有低库存提醒" :image-size="72" />
        </div>
      </section>
    </div>

    <section class="panel quick-panel">
      <div class="section-head">
        <h2>快捷入口</h2>
        <span>常用操作</span>
      </div>
      <div class="quick-grid">
        <button class="quick-item" @click="go('/components')">
          <small>查找 / 入库</small>
          <strong>元器件</strong>
        </button>
        <button class="quick-item" @click="go('/coverage')">
          <small>查看规格</small>
          <strong>覆盖图</strong>
        </button>
        <button v-if="FEATURE_EDA_ENABLED" class="quick-item" @click="go('/eda')">
          <small>管理资料</small>
          <strong>EDA 库</strong>
        </button>
        <button class="quick-item" @click="go('/about')">
          <small>备份 / 日志</small>
          <strong>管理</strong>
        </button>
      </div>
    </section>
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

const metrics = computed(() => [
  { label: '元器件种类', value: summary.value.total_kinds || 0, hint: '当前有效条目', tone: 'tone-blue' },
  { label: '库存总量', value: summary.value.total_quantity || 0, hint: '所有库存数量', tone: 'tone-green' },
  { label: '设备占用', value: summary.value.occupied_quantity || 0, hint: '使用中或借出的设备台数', tone: 'tone-amber' },
  { label: '可用库存', value: summary.value.available_quantity || 0, hint: '扣除项目预留和设备占用后的可用数', tone: 'tone-green' },
  { label: '全部库存总值', value: inventoryValue(summary.value.inventory_value_total), hint: `已计价 ${summary.value.priced_component_count || 0} 种 · 未计价 ${summary.value.unpriced_component_count || 0} 种`, tone: 'tone-blue', sensitive: true },
  { label: '可用库存总值', value: inventoryValue(summary.value.available_inventory_value_total), hint: '按扣除项目预留和设备占用后的可用数量估值', tone: 'tone-green', sensitive: true },
  { label: '低库存', value: summary.value.low_stock || 0, hint: '常用件低于安全库存', tone: 'tone-red' },
  { label: '常用器件', value: summary.value.common_count || 0, hint: '已标记为常用', tone: 'tone-amber' },
  { label: '分类数量', value: summary.value.category_count || 0, hint: '库存分类总数', tone: 'tone-purple' }
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
const actionItems = computed(() => summary.value.action_items || [])
const lowStockItems = computed(() => summary.value.low_stock_items || [])

async function load() {
  try {
    summary.value = await dashboardSummary()
  } catch (error) {
    ElMessage.error('读取仪表盘失败')
  }
}

function go(path) {
  router.push(path)
}

function goCategory(name) {
  router.push({ path: '/components', query: { keyword: name } })
}

onMounted(load)
</script>

<style scoped>
.dashboard-hero,
.dashboard-metric,
.panel,
.category-card,
.action-item,
.low-stock-list button,
.quick-item {
  border-radius: var(--cw-radius-card);
}

.dashboard-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--cw-border);
  background: #fff;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.dashboard-metrics {
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
}

.dashboard-metric {
  position: relative;
  min-height: 112px;
  display: grid;
  gap: 6px;
  align-content: center;
  background: #fff;
}

.metric-visibility {
  position: absolute;
  top: 8px;
  right: 8px;
  color: #667085;
}

.dashboard-metric span,
.dashboard-metric small,
.section-head span,
.category-card span,
.category-card small,
.action-item span,
.low-stock-list span,
.quick-item small {
  color: var(--cw-muted);
}

.dashboard-metric strong {
  color: var(--tone, #111827);
  font-size: 30px;
  line-height: 1;
}

.tone-blue { --tone: #2563eb; }
.tone-green { --tone: #059669; }
.tone-red { --tone: #dc2626; }
.tone-amber { --tone: #d97706; }
.tone-purple { --tone: #7c3aed; }

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-head h2 {
  margin: 0;
  color: #172b4d;
}

.category-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 12px;
}

.category-card {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 14px;
  border: 1px solid #e4eaf2;
  background: #fbfdff;
  text-align: left;
  cursor: pointer;
}

.category-card strong,
.low-stock-list strong {
  color: #172b4d;
}

.category-card b {
  color: #0f766e;
  font-size: 26px;
}

.category-card small {
  grid-column: 1 / -1;
}

.category-card small.danger {
  color: #dc2626;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}

.action-list,
.low-stock-list {
  display: grid;
  gap: 10px;
}

.action-item,
.low-stock-list button {
  display: grid;
  gap: 5px;
  padding: 12px;
  border: 1px solid #e4eaf2;
  background: #fff;
  text-align: left;
}

.action-item.danger { border-color: #fecaca; background: #fff7f7; }
.action-item.warning { border-color: #fed7aa; background: #fffaf2; }
.action-item.info { border-color: #bfdbfe; background: #f8fbff; }

.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}

.quick-item {
  display: grid;
  gap: 6px;
  padding: 16px;
  border: 1px solid #e4eaf2;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.quick-item strong {
  color: #172b4d;
  font-size: 18px;
}

@media (max-width: 860px) {
  .dashboard-hero,
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .dashboard-hero {
    display: grid;
  }
}
</style>
