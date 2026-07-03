<template>
  <main class="public-page" v-loading="loading">
    <section v-if="project" class="public-shell">
      <header class="public-brand">
        <div class="brand-lockup">
          <img class="brand-icon" :src="appIcon" alt="" />
          <img v-if="BRAND_SHOW_LOGO" :src="brandLogo" :alt="BRAND_SHORT" />
          <div>
            <span>{{ BRAND_NAME }} · 个人版</span>
            <strong>公开项目</strong>
          </div>
        </div>
        <el-tag effect="plain" type="info">{{ project.project_code }}</el-tag>
      </header>

      <section class="hero-card">
        <div class="hero-top">
          <div>
            <span class="eyebrow">扫码查看项目</span>
            <h1>{{ project.name }}</h1>
            <p>{{ project.description || '无描述' }}</p>
          </div>
          <div class="progress-ring">
            <strong>{{ boardStats.progress || 0 }}%</strong>
            <span>焊接</span>
          </div>
        </div>
        <div class="stats">
          <article><span>BOM 项</span><strong>{{ project.total_items || 0 }}</strong></article>
          <article><span>当前板位号</span><strong>{{ boardStats.total || 0 }}</strong></article>
          <article><span>已焊 / 报损</span><strong>{{ boardStats.soldered || 0 }} / {{ boardStats.lost || 0 }}</strong></article>
        </div>
      </section>

      <section v-if="projectBoards.length" class="board-strip">
        <button
          v-for="board in projectBoards"
          :key="board.id"
          type="button"
          class="board-tab"
          :class="{ active: board.id === activeBoardId }"
          @click="activeBoardId = board.id"
        >
          <span>{{ board.name }}</span>
          <small>{{ board.soldered_count || 0 }}/{{ board.solder_total || 0 }} · 损 {{ board.lost_count || 0 }}</small>
        </button>
      </section>

      <section class="toolbar">
        <el-input v-model="keyword" clearable placeholder="搜索位号、型号、参数、封装、自有 ID" />
        <el-segmented v-model="filter" :options="filterOptions" />
      </section>

      <section class="bom-list">
        <article v-for="item in visibleItems" :key="item.id" class="bom-card">
          <div class="bom-main">
            <div class="tag-line">
              <el-tag effect="plain" :style="{ background: item.component.category_color || '#eef2ff' }">{{ item.component.category || '未分类' }}</el-tag>
              <el-tag v-if="item.component.warehouse_code" effect="plain" type="info">{{ item.component.warehouse_code }}</el-tag>
              <el-tag v-if="itemBoardTotal(item) && itemBoardSoldered(item) >= itemBoardTotal(item)" type="success">当前板已焊</el-tag>
            </div>
            <h2>{{ item.component.model || item.component.name || item.component.warehouse_code }}</h2>
            <p>{{ item.component.normalized_spec || item.component.parameters || item.component.name || '-' }}</p>
            <div class="meta">
              <span>封装 {{ item.component.package || '-' }}</span>
              <span>立创 {{ item.component.lcsc_number || '-' }}</span>
              <span>需求 {{ item.required_quantity }}</span>
            </div>
          </div>
          <div class="designators">
            <button
              v-for="point in itemBoardPoints(item)"
              :key="point.id"
              class="solder-chip"
              :class="{ done: point.soldered }"
              type="button"
            >
              <span>{{ point.designator }}</span>
              <small>{{ point.soldered ? '已焊' : '待焊' }}</small>
              <em v-if="point.lost">报损</em>
            </button>
            <span v-if="!itemBoardPoints(item).length" class="empty-designator">无位号</span>
          </div>
        </article>
      </section>

      <el-empty v-if="!visibleItems.length" description="没有符合条件的 BOM 项" />

      <footer class="public-footer">
        <div class="footer-brand">
          <img v-if="BRAND_SHOW_LOGO" :src="brandLogo" :alt="BRAND_SHORT" />
          <strong>Powered by {{ BRAND_NAME }}</strong>
        </div>
        <span>只读公开页面，不提供库存修改权限。</span>
      </footer>
    </section>

    <el-empty v-else-if="!loading" description="没有找到这个项目" />
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from '../shared/elementApi'
import { useRoute } from 'vue-router'
import { getPublicProject } from '../api/client'
import brandLogo from '../assets/brand-logo.png'
import appIcon from '../assets/generated/cw-app-icon.png'
import { BRAND_NAME, BRAND_SHORT, BRAND_SHOW_LOGO } from '../shared/branding'

const route = useRoute()
const loading = ref(false)
const project = ref(null)
const keyword = ref('')
const filter = ref('all')
const activeBoardId = ref(null)
const filterOptions = [
  { label: '全部', value: 'all' },
  { label: '待焊', value: 'pending' },
  { label: '已焊', value: 'done' },
  { label: '报损', value: 'lost' }
]

const projectBoards = computed(() => project.value?.boards || [])
const activeBoard = computed(() => projectBoards.value.find((board) => board.id === activeBoardId.value) || projectBoards.value[0] || null)
const boardStats = computed(() => ({
  total: activeBoard.value?.solder_total || 0,
  soldered: activeBoard.value?.soldered_count || 0,
  lost: activeBoard.value?.lost_count || 0,
  pending: activeBoard.value?.pending_count || 0,
  progress: activeBoard.value?.solder_progress || 0
}))

function itemBoardPoints(item) {
  const boardId = activeBoard.value?.id
  return (item?.solder_points || []).filter((point) => !boardId || point.board_id === boardId)
}

function itemBoardTotal(item) {
  return itemBoardPoints(item).length
}

function itemBoardSoldered(item) {
  return itemBoardPoints(item).filter((point) => point.soldered).length
}

function itemBoardLost(item) {
  return itemBoardPoints(item).filter((point) => point.lost).length
}

function matchesFilter(item) {
  if (filter.value === 'done') return itemBoardTotal(item) && itemBoardSoldered(item) >= itemBoardTotal(item)
  if (filter.value === 'lost') return itemBoardLost(item) > 0
  if (filter.value === 'pending') return !itemBoardTotal(item) || itemBoardSoldered(item) < itemBoardTotal(item)
  return true
}

function matchesKeyword(item) {
  const value = keyword.value.trim().toLowerCase().replace(/µ|μ/g, 'u')
  if (!value) return true
  const text = [
    item.component?.warehouse_code,
    item.component?.name,
    item.component?.model,
    item.component?.parameters,
    item.component?.normalized_spec,
    item.component?.package,
    item.component?.lcsc_number,
    item.remark,
    ...itemBoardPoints(item).flatMap((point) => [point.designator, point.bom_value, point.bom_model, point.bom_footprint])
  ].filter(Boolean).join(' ').toLowerCase().replace(/µ|μ/g, 'u')
  return text.includes(value)
}

const visibleItems = computed(() => (project.value?.bom_items || []).filter((item) => matchesFilter(item) && matchesKeyword(item)))

async function load() {
  loading.value = true
  try {
    project.value = await getPublicProject(route.params.code)
    activeBoardId.value = project.value?.active_board_id || project.value?.boards?.[0]?.id || null
  } catch {
    ElMessage.error('读取公开项目失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.public-page {
  min-height: 100vh;
  padding: 24px;
  background: #f7f9fc;
}

.public-shell {
  width: min(1120px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 16px;
}

.public-brand,
.hero-card,
.board-strip,
.toolbar,
.bom-card,
.public-footer {
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 16px;
  background: #fff;
}

.public-brand,
.public-footer,
.brand-lockup,
.footer-brand,
.hero-top,
.toolbar,
.meta,
.tag-line,
.designators {
  display: flex;
  align-items: center;
  gap: 12px;
}

.public-brand,
.public-footer {
  justify-content: space-between;
  padding: 14px 16px;
}

.brand-lockup img {
  width: 154px;
  height: 58px;
  object-fit: contain;
  object-position: center;
}

.brand-lockup .brand-icon {
  width: 38px;
  height: 38px;
  border-radius: 9px;
}

.footer-brand img {
  width: 118px;
  height: 44px;
  object-fit: contain;
  object-position: center;
}

.hero-card {
  padding: 22px;
}

.hero-top {
  justify-content: space-between;
  align-items: flex-start;
}

.eyebrow,
.public-brand span,
.public-footer span,
.hero-card p,
.meta,
.stats span {
  color: #667085;
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  margin-top: 8px;
  font-size: clamp(34px, 6vw, 64px);
  line-height: 1;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.progress-ring {
  width: 104px;
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  border: 8px solid #bbf7d0;
  border-radius: 999px;
  color: #15803d;
}

.progress-ring strong,
.progress-ring span {
  grid-column: 1;
  grid-row: 1;
}

.progress-ring span {
  align-self: end;
  margin-bottom: 18px;
  font-size: 12px;
}

.progress-ring strong {
  align-self: center;
  font-size: 26px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.stats article {
  padding: 14px;
  border: 1px solid #dbeafe;
  border-radius: var(--cw-radius-control);
  background: #f8fbff;
}

.board-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px;
}

.board-tab {
  display: grid;
  gap: 3px;
  min-width: 116px;
  padding: 9px 12px;
  border: 1px solid #d1d5db;
  border-radius: var(--cw-radius-control);
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.board-tab.active {
  border-color: #60a5fa;
  background: #eff6ff;
}

.board-tab span {
  font-weight: 760;
}

.board-tab small {
  color: #667085;
}

.stats strong {
  display: block;
  margin-top: 6px;
  font-size: 26px;
}

.toolbar {
  grid-template-columns: minmax(0, 1fr) auto;
  padding: 12px;
}

.bom-list {
  display: grid;
  gap: 12px;
}

.bom-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 0.7fr);
  gap: 14px;
  padding: 16px;
}

.bom-main {
  min-width: 0;
  display: grid;
  gap: 8px;
}

.bom-main h2 {
  font-size: 22px;
  overflow-wrap: anywhere;
}

.meta,
.tag-line,
.designators {
  flex-wrap: wrap;
}

.solder-chip {
  display: grid;
  gap: 2px;
  min-width: 72px;
  padding: 8px 10px;
  border: 1px solid #fecaca;
  border-radius: var(--cw-radius-control);
  color: #991b1b;
  background: #fff7f7;
}

.solder-chip.done {
  border-color: #86efac;
  color: #166534;
  background: #f0fdf4;
}

.solder-chip small,
.empty-designator {
  color: #667085;
}

.solder-chip em {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  padding: 2px 7px;
  border: 1px solid #fed7aa;
  border-radius: 999px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 11px;
  font-style: normal;
  line-height: 1.2;
}

@media (max-width: 760px) {
  .public-page {
    padding: 12px;
  }

  .hero-top,
  .public-brand,
  .public-footer,
  .toolbar,
  .bom-card {
    display: grid;
  }

  .brand-lockup {
    min-width: 0;
  }

  .brand-lockup img {
    width: 140px;
    height: 54px;
  }

  .stats {
    grid-template-columns: 1fr;
  }
}
</style>
