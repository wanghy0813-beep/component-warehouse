<template>
  <section class="page admin-page">
    <div class="page-header admin-hero">
      <div>
        <h1 class="page-title">管理员看板</h1>
        <p class="page-subtitle">查看注册用户、月活、功能使用排行和最近使用情况。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <div class="admin-metrics">
      <article>
        <span>注册用户</span>
        <strong>{{ data.registered_users || 0 }}</strong>
        <small>当前镜像账号总数</small>
      </article>
      <article>
        <span>月活用户</span>
        <strong>{{ data.monthly_active_users || 0 }}</strong>
        <small>近 30 天有界面操作</small>
      </article>
      <article>
        <span>7 日活跃</span>
        <strong>{{ data.weekly_active_users || 0 }}</strong>
        <small>近 7 天有界面操作</small>
      </article>
      <article>
        <span>今日活跃</span>
        <strong>{{ data.today_active_users || 0 }}</strong>
        <small>今日有界面操作</small>
      </article>
      <article>
        <span>30 天操作</span>
        <strong>{{ data.ui_events_30d || 0 }}</strong>
        <small>仅统计 ui.* 埋点</small>
      </article>
    </div>

    <div class="admin-grid">
      <section class="panel">
        <div class="section-head">
          <h2>常用功能排行</h2>
          <span>近 30 天</span>
        </div>
        <div class="feature-list">
          <div v-for="item in data.top_features || []" :key="item.action">
            <span>
              <strong>{{ item.label }}</strong>
              <small>{{ item.action }}</small>
            </span>
            <em>{{ item.count }}</em>
            <i :style="{ width: featureWidth(item.count) }"></i>
          </div>
          <el-empty v-if="!(data.top_features || []).length" description="暂无埋点数据" :image-size="72" />
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <h2>近期活跃用户</h2>
          <span>按最后使用排序</span>
        </div>
        <div class="user-list">
          <article v-for="user in data.recent_users || []" :key="user.user_id">
            <div>
              <strong>{{ user.nickname || `用户 ${user.user_id}` }}</strong>
              <small>{{ maskPhone(user.phone) }} · {{ formatTime(user.last_seen_at) }}</small>
            </div>
            <em>{{ user.event_count_30d }} 次</em>
          </article>
          <el-empty v-if="!(data.recent_users || []).length" description="暂无活跃用户" :image-size="72" />
        </div>
      </section>

      <section class="panel admin-wide">
        <div class="section-head">
          <h2>30 天趋势</h2>
          <span>轻量统计，不加载图表库</span>
        </div>
        <div class="spark-bars" aria-label="近 30 天操作量">
          <span
            v-for="day in data.daily || []"
            :key="day.date"
            :title="`${day.date} · ${day.events} 次 · ${day.users} 人`"
            :style="{ height: dayHeight(day.events) }"
          ></span>
        </div>
      </section>

      <section class="panel admin-wide">
        <div class="section-head">
          <h2>最近界面操作</h2>
          <span>只显示最近少量记录</span>
        </div>
        <el-table :data="data.recent_events || []" row-key="id" stripe class="admin-table" max-height="420" empty-text="暂无记录">
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="用户" width="150">
            <template #default="{ row }">{{ row.user || '-' }}</template>
          </el-table-column>
          <el-table-column prop="label" label="功能" min-width="160" />
          <el-table-column prop="page" label="页面" min-width="180" show-overflow-tooltip />
          <el-table-column prop="entry" label="入口" min-width="120" show-overflow-tooltip />
        </el-table>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from '../shared/elementApi'
import { getAdminUsageDashboard } from '../api/client'

const loading = ref(false)
const data = ref({})
const maxFeatureCount = computed(() => Math.max(1, ...(data.value.top_features || []).map((item) => Number(item.count || 0))))
const maxDailyEvents = computed(() => Math.max(1, ...(data.value.daily || []).map((item) => Number(item.events || 0))))

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function maskPhone(value) {
  const phone = String(value || '')
  if (phone.length < 7) return phone || '-'
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`
}

function featureWidth(value) {
  return `${Math.max(8, Math.round((Number(value || 0) / maxFeatureCount.value) * 100))}%`
}

function dayHeight(value) {
  return `${Math.max(8, Math.round((Number(value || 0) / maxDailyEvents.value) * 100))}%`
}

async function load() {
  loading.value = true
  try {
    data.value = await getAdminUsageDashboard()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '读取管理员看板失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.admin-hero,
.admin-metrics article,
.feature-list > div,
.user-list article {
  border: 1px solid var(--cw-border);
  border-radius: var(--cw-radius-card);
  background: rgba(255, 255, 255, 0.88);
}

.admin-hero {
  padding: 22px;
}

.admin-metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.admin-metrics article {
  padding: 16px;
}

.admin-metrics span,
.admin-metrics small {
  display: block;
  color: var(--cw-muted);
}

.admin-metrics strong {
  display: block;
  margin: 8px 0 4px;
  color: var(--cw-text);
  font-size: 30px;
  line-height: 1;
}

.admin-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}

.admin-wide {
  grid-column: 1 / -1;
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
  font-size: 18px;
}

.section-head span {
  color: var(--cw-muted);
  font-size: 13px;
}

.feature-list,
.user-list {
  display: grid;
  gap: 10px;
}

.feature-list > div {
  position: relative;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 12px;
}

.feature-list i {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 4px;
  border-radius: 999px;
  background: linear-gradient(90deg, #60a5fa, #f97316);
}

.feature-list strong,
.feature-list small,
.user-list strong,
.user-list small {
  display: block;
}

.feature-list small,
.user-list small {
  margin-top: 3px;
  color: var(--cw-muted);
}

.feature-list em,
.user-list em {
  color: #0f172a;
  font-style: normal;
  font-weight: 800;
}

.user-list article {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
}

.spark-bars {
  height: 150px;
  display: flex;
  align-items: end;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--cw-border);
  border-radius: var(--cw-radius-card);
  background: #f8fafc;
}

.spark-bars span {
  flex: 1;
  min-width: 4px;
  border-radius: 999px 999px 4px 4px;
  background: linear-gradient(180deg, #3b82f6, #93c5fd);
}

.admin-table {
  border-radius: var(--cw-radius-card);
  overflow: hidden;
}

@media (max-width: 980px) {
  .admin-metrics,
  .admin-grid {
    grid-template-columns: 1fr;
  }
}
</style>
