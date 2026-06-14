<template>
  <section class="page about-page">
    <div class="page-header hero-panel">
      <div>
        <h1 class="page-title">关于 Component Warehouse</h1>
        <p class="page-subtitle">版本、引用、统计和系统日志</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <div class="metric-grid about-metrics">
      <div v-for="item in metrics" :key="item.label" class="metric">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
        <div class="metric-hint">{{ item.hint }}</div>
      </div>
    </div>

    <div class="about-grid">
      <div class="panel">
        <h2>版本更新</h2>
        <div class="version-card">
          <strong>v0.3.0 · 分类整理与选型工作台增强</strong>
          <span>2026-06-12</span>
          <ul>
            <li>新增 AI 元器件规范化：规则给边界，MiMo 生成短名称、分类、标签和规格。</li>
            <li>连接件分类统一收纳排针、排母、端子、线束、螺丝、螺母和铜柱。</li>
            <li>BOM 导入保留低置信候选，补充作用说明、缺料建议和立创搜索。</li>
            <li>元器件卡片移除误导性的 AI 已完成徽标，减少重复 Tag。</li>
            <li>新增电阻、电容、电感单位换算，帮助快速理解 Ω/kΩ、pF/nF/µF、nH/µH/mH。</li>
            <li>首页低库存改为库存行动建议，更关注项目缺料、常用耗材和资料缺失。</li>
            <li>侧边栏常驻并支持收起，BOM 物料可跳转到元器件库查看详情。</li>
          </ul>
        </div>
        <div class="version-card soft">
          <strong>v0.2.0 · AI 知识卡片与 BOM 流程</strong>
          <span>2026-06-12</span>
          <ul>
            <li>AI 知识卡片按设计洞察、风险、PCB 注意、替代料检查等分组展示。</li>
            <li>BOM 状态重构为预占、已取料、已释放；完成只用于项目整体。</li>
            <li>支持购物截图识别预览导入，确认后再入库。</li>
          </ul>
        </div>
      </div>

      <div class="panel">
        <h2>引用与资料来源</h2>
        <div class="reference-list">
          <div v-for="item in references" :key="item.title" class="reference-item">
            <strong>{{ item.title }}</strong>
            <span>{{ item.description }}</span>
            <el-button v-if="item.url" size="small" text @click="openUrl(item.url)">打开</el-button>
          </div>
        </div>
      </div>

      <div class="panel">
        <h2>系统统计</h2>
        <div class="stat-list">
          <div><span>元器件种类</span><strong>{{ summary.total_kinds || 0 }}</strong></div>
          <div><span>库存总量</span><strong>{{ summary.total_quantity || 0 }}</strong></div>
          <div><span>项目占用</span><strong>{{ summary.reserved_quantity || 0 }}</strong></div>
          <div><span>可用库存</span><strong>{{ summary.available_quantity || 0 }}</strong></div>
          <div><span>行动建议</span><strong>{{ summary.action_items?.length || 0 }}</strong></div>
          <div><span>AI 等待/过期</span><strong>{{ taskSummary.pending + taskSummary.stale }}</strong></div>
          <div><span>AI 失败</span><strong>{{ taskSummary.failed }}</strong></div>
          <div><span>缺数据手册</span><strong>{{ summary.datasheet_missing || 0 }}</strong></div>
        </div>
      </div>
    </div>

    <div class="about-grid logs-grid">
      <div class="panel">
        <h2>登录日志</h2>
        <div class="log-list">
          <div v-for="log in loginLogs" :key="log.id" class="log-row">
            <span>{{ formatTime(log.created_at) }}</span>
            <strong>{{ log.summary }}</strong>
          </div>
          <el-empty v-if="!loginLogs.length" description="暂无登录日志" :image-size="72" />
        </div>
      </div>

      <div class="panel">
        <h2>变更日志</h2>
        <div class="log-list">
          <div v-for="log in changeLogs" :key="log.id" class="log-row">
            <span>{{ formatTime(log.created_at) }} · {{ log.action }}</span>
            <strong>{{ log.summary }}</strong>
          </div>
          <el-empty v-if="!changeLogs.length" description="暂无变更日志" :image-size="72" />
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { dashboardSummary, getActivityLogs, getAiTaskSummary } from '../api/client'

const summary = ref({})
const taskSummary = ref({ pending: 0, stale: 0, completed: 0, failed: 0 })
const logs = ref([])

const metrics = computed(() => [
  { label: '当前版本', value: 'v0.3.0', hint: '分类整理与选型工作台增强' },
  { label: '元器件', value: summary.value.total_kinds || 0, hint: '库存种类' },
  { label: '可用库存', value: summary.value.available_quantity || 0, hint: '扣除项目预占' },
  { label: 'AI 任务', value: taskSummary.value.pending + taskSummary.value.stale, hint: '等待或需更新' }
])

const references = [
  {
    title: '小米 MiMo API',
    description: '用于元器件说明、名称规范化、BOM 辅助匹配和图片识别预览。',
    url: 'https://api.xiaomimimo.com/v1'
  },
  {
    title: '立创商城公开搜索',
    description: '用于从元器件型号、立创编号或缺料关键词跳转搜索。',
    url: 'https://m.szlcsc.com/pages-list/global-product/index?keyword=CKSMBJ30CA'
  },
  {
    title: '本地库存数据库',
    description: 'SQLite 保存元器件、项目 BOM、AI 缓存、知识卡片和活动日志。'
  },
  {
    title: '技术栈',
    description: 'Vue 3 + Vite + Element Plus，FastAPI，SQLite，Docker Compose。'
  }
]

const loginLogs = computed(() => logs.value.filter((item) => item.action?.startsWith('auth.login')).slice(0, 12))
const changeLogs = computed(() =>
  logs.value
    .filter((item) => !item.action?.startsWith('auth.login'))
    .filter((item) => /component|bom|project|import|ai/i.test(item.action || ''))
    .slice(0, 24)
)

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function openUrl(url) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

async function load() {
  try {
    const [dashboard, tasks, activity] = await Promise.all([
      dashboardSummary(),
      getAiTaskSummary(),
      getActivityLogs({ limit: 120 })
    ])
    summary.value = dashboard
    taskSummary.value = tasks
    logs.value = activity
  } catch (error) {
    ElMessage.error('读取关于信息失败')
  }
}

onMounted(load)
</script>

<style scoped>
.hero-panel {
  padding: 22px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow: var(--cw-shadow);
  backdrop-filter: blur(22px);
}

.about-metrics {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-hint {
  margin-top: 6px;
  color: var(--cw-muted);
  font-size: 12px;
}

.about-grid {
  display: grid;
  grid-template-columns: 1.25fr 1fr 0.9fr;
  gap: 14px;
}

.logs-grid {
  grid-template-columns: 1fr 1.4fr;
}

h2 {
  margin: 0 0 12px;
  font-size: 16px;
}

.version-card,
.reference-item,
.log-row {
  padding: 12px;
  border: 1px solid #e6ecf5;
  border-radius: 14px;
  background: #fff;
}

.version-card + .version-card {
  margin-top: 10px;
}

.version-card.soft {
  background: #f8fafc;
}

.version-card strong,
.version-card span,
.reference-item strong,
.reference-item span,
.log-row span,
.log-row strong {
  display: block;
}

.version-card span,
.reference-item span,
.log-row span {
  margin-top: 4px;
  color: var(--cw-muted);
  font-size: 12px;
}

.version-card ul {
  margin: 10px 0 0;
  padding-left: 18px;
  color: #344054;
  line-height: 1.65;
}

.reference-list,
.log-list {
  display: grid;
  gap: 10px;
}

.stat-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.stat-list div {
  padding: 12px;
  border-radius: 14px;
  background: #fff;
}

.stat-list span {
  display: block;
  color: var(--cw-muted);
  font-size: 12px;
}

.stat-list strong {
  display: block;
  margin-top: 5px;
  color: #101828;
  font-size: 22px;
}

.log-row strong {
  margin-top: 4px;
  color: #1f2937;
}

@media (max-width: 1100px) {
  .about-grid,
  .logs-grid,
  .about-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
