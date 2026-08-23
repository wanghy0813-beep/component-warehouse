<template>
  <section class="page management-page">
    <div class="page-header management-hero">
      <div>
        <h1 class="page-title">管理</h1>
        <p class="page-subtitle">{{ IS_DESKTOP ? '本地导入、操作日志与数据管理' : '导入、AI、备份、日志和危险操作' }}</p>
      </div>
      <div class="management-actions">
        <install-app-button />
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="management-grid">
      <section class="panel import-panel">
        <div class="section-head">
          <h2>导入批次</h2>
          <span>最近 {{ importBatches.length }} 批</span>
        </div>
        <div class="batch-list">
          <article v-for="batch in importBatches" :key="batch.id" class="batch-card">
            <div>
              <strong>#{{ batch.id }} {{ batch.source_file || 'Excel 导入' }}</strong>
              <span>{{ formatTime(batch.created_at) }} · 新增 {{ batch.created_count }} · 合并 {{ batch.merged_count }} · 跳过 {{ batch.skipped_count }}</span>
              <small v-if="batch.rollback_summary">{{ batch.rollback_summary }}</small>
            </div>
            <div class="row-actions">
              <el-tag :type="batch.status === 'rolled_back' ? 'info' : 'success'" effect="plain">{{ batch.status === 'rolled_back' ? '已撤销' : '有效' }}</el-tag>
              <el-button size="small" plain :disabled="batch.status === 'rolled_back'" @click="rollbackBatch(batch)">撤销</el-button>
            </div>
          </article>
          <el-empty v-if="!importBatches.length" description="暂无导入批次" :image-size="72" />
        </div>
      </section>

      <section v-if="!IS_DESKTOP" class="panel ai-panel">
        <div class="section-head">
          <h2>AI 维护</h2>
          <span>后台队列</span>
        </div>
        <div class="maintenance-actions">
          <button class="maintenance-card" type="button" @click="enqueueOrganize">
            <small>分类整理</small>
            <strong>重新整理</strong>
          </button>
          <button class="maintenance-card" type="button" @click="resetAi">
            <small>AI 重置</small>
            <strong>重置重跑</strong>
          </button>
        </div>
        <div class="task-strip">
          <div><span>待处理</span><strong>{{ taskSummary.pending || 0 }}</strong></div>
          <div><span>需更新</span><strong>{{ taskSummary.stale || 0 }}</strong></div>
          <div><span>失败</span><strong>{{ taskSummary.failed || 0 }}</strong></div>
          <div><span>完成</span><strong>{{ taskSummary.completed || 0 }}</strong></div>
        </div>
      </section>

      <section v-if="!IS_DESKTOP" class="panel backup-panel">
        <div class="section-head">
          <h2>数据备份</h2>
          <span>{{ backups.length }} 个</span>
        </div>
        <div class="backup-actions">
          <el-upload :show-file-list="false" accept=".zip" :http-request="inspectBackupUpload">
            <el-button plain :loading="restoreInspecting">预览恢复</el-button>
          </el-upload>
          <el-button plain type="warning" :disabled="!cleanupPreview.candidate_count" @click="cleanupBackups">清理旧备份</el-button>
        </div>
        <small class="cleanup-preview">可回收 {{ formatBytes(cleanupPreview.reclaimable_bytes) }}；{{ cleanupPreview.preserved || '会保留新版备份和最近检查点' }}</small>
        <div class="backup-list">
          <div v-for="item in backups.slice(0, 4)" :key="item.filename">
            <strong>{{ backupTypeLabel(item.type) }}</strong>
            <span>{{ formatTime(item.created_at) }} · {{ formatBytes(item.bytes) }}</span>
          </div>
          <small v-if="!backups.length">暂无备份</small>
        </div>
      </section>

      <section v-if="!IS_DESKTOP" class="panel codex-panel">
        <div class="section-head">
          <h2>Codex 接入</h2>
          <el-tag type="success" effect="plain">查询 + 审批草案</el-tag>
        </div>
        <p>让 ChatGPT 分析板卡和 BOM 时直接查询个人库存；写入只生成网页审批单。</p>
        <div class="codex-points">
          <span>个人库隔离</span><span>逐单审批</span><span>30 天可撤销</span>
        </div>
        <el-button type="primary" plain @click="$router.push('/integrations/codex')">管理 Codex 接入</el-button>
      </section>

      <section v-else class="panel online-only-panel">
        <div class="section-head">
          <h2>在线专属功能</h2>
          <el-tag type="info" effect="plain">网页端</el-tag>
        </div>
        <p>AI、Codex 接入、账号安全、团队工作区和服务器备份管理仅在在线网页使用。</p>
        <small>离线不影响库存、项目、EDA、标签和文件操作。</small>
      </section>

      <section class="panel danger-panel">
        <div class="section-head">
          <h2>清库重录</h2>
          <el-tag type="danger" effect="plain">危险</el-tag>
        </div>
        <p>清空元器件、项目、BOM、导入批次、AI 任务和台账日志。</p>
        <el-button type="danger" plain @click="clearAllData">三次确认后清空数据库</el-button>
      </section>
    </div>

    <section v-if="isAdmin && !IS_DESKTOP" class="panel admin-panel">
      <div class="section-head">
        <h2>用户统计</h2>
        <span>近 30 天</span>
      </div>
      <div class="admin-metrics">
        <article><span>注册用户</span><strong>{{ adminData.registered_users || 0 }}</strong></article>
        <article><span>月活</span><strong>{{ adminData.monthly_active_users || 0 }}</strong></article>
        <article><span>7 日活跃</span><strong>{{ adminData.weekly_active_users || 0 }}</strong></article>
        <article><span>今日活跃</span><strong>{{ adminData.today_active_users || 0 }}</strong></article>
        <article><span>30 天操作</span><strong>{{ adminData.ui_events_30d || 0 }}</strong></article>
      </div>
      <div class="admin-grid">
        <section class="admin-card">
          <div class="section-head compact">
            <h3>常用功能</h3>
            <span>排行</span>
          </div>
          <div class="feature-list">
            <div v-for="item in adminData.top_features || []" :key="item.action">
              <span><strong>{{ item.label }}</strong><small>{{ item.action }}</small></span>
              <em>{{ item.count }}</em>
              <i :style="{ width: featureWidth(item.count) }"></i>
            </div>
            <el-empty v-if="!(adminData.top_features || []).length" description="暂无数据" :image-size="72" />
          </div>
        </section>
        <section class="admin-card">
          <div class="section-head compact">
            <h3>近期用户</h3>
            <span>最后使用</span>
          </div>
          <div class="user-list">
            <article v-for="user in adminData.recent_users || []" :key="user.user_id">
              <span><strong>{{ user.nickname || `用户 ${user.user_id}` }}</strong><small>{{ maskPhone(user.phone) }} · {{ formatTime(user.last_seen_at) }}</small></span>
              <em>{{ user.event_count_30d }} 次</em>
            </article>
            <el-empty v-if="!(adminData.recent_users || []).length" description="暂无数据" :image-size="72" />
          </div>
        </section>
        <section class="admin-card admin-wide">
          <div class="section-head compact">
            <h3>趋势</h3>
            <span>30 天</span>
          </div>
          <div class="spark-bars" aria-label="近 30 天操作量">
            <span
              v-for="day in adminData.daily || []"
              :key="day.date"
              :title="`${day.date} · ${day.events} 次 · ${day.users} 人`"
              :style="{ height: dayHeight(day.events) }"
            ></span>
          </div>
        </section>
        <section class="admin-card admin-wide">
          <div class="section-head compact">
            <h3>最近界面操作</h3>
            <span>{{ (adminData.recent_events || []).length }} 条</span>
          </div>
          <el-table :data="adminData.recent_events || []" row-key="id" stripe class="compact-table" max-height="360" empty-text="暂无记录">
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="用户" width="140">
              <template #default="{ row }">{{ row.user || '-' }}</template>
            </el-table-column>
            <el-table-column prop="label" label="功能" min-width="150" />
            <el-table-column prop="page" label="页面" min-width="180" show-overflow-tooltip />
            <el-table-column prop="entry" label="入口" min-width="120" show-overflow-tooltip />
          </el-table>
        </section>
      </div>
    </section>

    <section class="panel">
      <div class="section-head">
        <h2>操作记录</h2>
        <span>最近 {{ visibleLogs.length }} 条</span>
      </div>
      <el-table :data="visibleLogs" row-key="id" stripe class="compact-table" max-height="520" empty-text="暂无操作记录">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="summary" label="操作" min-width="320" show-overflow-tooltip />
        <el-table-column prop="action" label="类型" width="170" show-overflow-tooltip />
        <el-table-column label="数量" width="90" align="right">
          <template #default="{ row }">{{ row.quantity_delta || '-' }}</template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-if="!IS_DESKTOP" v-model="restoreDialog" title="恢复数据库备份" width="560px" append-to-body>
      <template v-if="restorePreview">
        <el-alert type="warning" show-icon :closable="false" title="恢复会覆盖当前 SQLite 数据库。系统会先自动生成 pre-restore 备份。" />
        <dl class="restore-preview">
          <div><dt>文件</dt><dd>{{ restorePreview.filename }}</dd></div>
          <div><dt>备份时间</dt><dd>{{ formatTime(restorePreview.created_at) }}</dd></div>
          <div><dt>数据库</dt><dd>{{ formatBytes(restorePreview.snapshot_bytes) }} · {{ restorePreview.table_count }} 张表</dd></div>
          <div><dt>文件数</dt><dd>{{ restorePreview.file_count }}</dd></div>
          <div><dt>SHA256</dt><dd>{{ restorePreview.snapshot_sha256 }}</dd></div>
        </dl>
        <el-alert v-for="warning in restorePreview.warnings || []" :key="warning" type="info" show-icon :closable="false" :title="warning" />
        <el-input v-model="restoreConfirm" :placeholder="`输入：${restorePreview.required_confirm_text || '恢复数据库'}`" />
      </template>
      <template #footer>
        <el-button @click="restoreDialog = false">取消</el-button>
        <el-button type="danger" :loading="restoreLoading" :disabled="restoreConfirm !== (restorePreview?.required_confirm_text || '恢复数据库')" @click="submitRestore">确认恢复</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../shared/elementApi'
import { Refresh } from '@element-plus/icons-vue'
import InstallAppButton from '../shared/components/InstallAppButton.vue'
import { IS_DESKTOP } from '../shared/desktopBridge'
import {
  clearDatabase,
  cleanupOldDataBackups,
  enqueueOrganizeAiTasks,
  getActivityLogs,
  getAdminUsageDashboard,
  getAiTaskSummary,
  getDataBackups,
  getOrderImportBatches,
  inspectDataBackup,
  resetAndReorganize,
  restoreDataBackup,
  rollbackOrderImportBatch,
} from '../api/client'

const storedUser = (() => {
  try { return JSON.parse(localStorage.getItem('cw_legacy_user') || '{}') }
  catch { return {} }
})()
const isAdmin = Boolean(storedUser.isAdmin || storedUser.is_admin)
const loading = ref(false)
const taskSummary = ref({ pending: 0, stale: 0, completed: 0, failed: 0 })
const logs = ref([])
const importBatches = ref([])
const backups = ref([])
const cleanupPreview = ref({ candidate_count: 0, reclaimable_bytes: 0 })
const adminData = ref({})
const restoreDialog = ref(false)
const restoreFile = ref(null)
const restorePreview = ref(null)
const restoreConfirm = ref('')
const restoreInspecting = ref(false)
const restoreLoading = ref(false)
const visibleLogs = computed(() => logs.value.slice(0, 120))
const maxFeatureCount = computed(() => Math.max(1, ...(adminData.value.top_features || []).map((item) => Number(item.count || 0))))
const maxDailyEvents = computed(() => Math.max(1, ...(adminData.value.daily || []).map((item) => Number(item.events || 0))))

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function backupTypeLabel(value) {
  return { auto: '自动备份', pre_restore: '恢复前', pre_clear: '清库前', manual: '手动' }[value] || value || '备份'
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

async function loadMaintenance() {
  if (IS_DESKTOP) {
    const [activity, batches] = await Promise.all([
      getActivityLogs({ limit: 160 }),
      getOrderImportBatches({ limit: 20 }),
    ])
    logs.value = activity
    importBatches.value = batches
    return
  }
  const [tasks, activity, batches, backupResult] = await Promise.all([
    getAiTaskSummary(),
    getActivityLogs({ limit: 160 }),
    getOrderImportBatches({ limit: 20 }),
    getDataBackups(),
  ])
  taskSummary.value = tasks
  logs.value = activity
  importBatches.value = batches
  backups.value = backupResult.items || []
  cleanupPreview.value = backupResult.cleanup || { candidate_count: 0, reclaimable_bytes: 0 }
}

async function loadAdmin() {
  if (!isAdmin || IS_DESKTOP) return
  try {
    adminData.value = await getAdminUsageDashboard()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '读取用户统计失败')
  }
}

async function load() {
  loading.value = true
  try {
    await Promise.all([loadMaintenance(), loadAdmin()])
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '读取管理信息失败')
  } finally {
    loading.value = false
  }
}

async function rollbackBatch(batch) {
  await ElMessageBox.confirm(`撤销导入批次 #${batch.id}？库存会回退到该批次导入前状态。`, '撤销导入批次', {
    type: 'warning',
    confirmButtonText: '撤销',
    cancelButtonText: '取消',
  })
  const result = await rollbackOrderImportBatch(batch.id)
  ElMessage.success(result.rollback_summary || '已撤销导入批次')
  await load()
}

async function enqueueOrganize() {
  const result = await enqueueOrganizeAiTasks(true)
  ElMessage.success(`已加入整理队列：${result.queued || result.organize_queued || 0}`)
  await load()
}

async function resetAi() {
  await ElMessageBox.confirm('将清除 AI 摘要、知识卡片和规范标签，并重新整理全部元器件。', '重置 AI', {
    type: 'warning',
    confirmButtonText: '重置',
    cancelButtonText: '取消',
  })
  const result = await resetAndReorganize()
  ElMessage.success(`已重置：整理 ${result.organize_queued || 0}，分析 ${result.analyze_queued || 0}`)
  await load()
}

async function inspectBackupUpload({ file }) {
  restoreInspecting.value = true
  try {
    restoreFile.value = file
    restorePreview.value = await inspectDataBackup(file)
    restoreConfirm.value = ''
    restoreDialog.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '备份文件校验失败')
  } finally {
    restoreInspecting.value = false
  }
}

async function submitRestore() {
  if (!restoreFile.value) return
  restoreLoading.value = true
  try {
    const result = await restoreDataBackup(restoreFile.value, restoreConfirm.value)
    ElMessage.success(result.message || '数据库已恢复')
    restoreDialog.value = false
    restoreFile.value = null
    restorePreview.value = null
    restoreConfirm.value = ''
    await load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '恢复数据库失败')
  } finally {
    restoreLoading.value = false
  }
}

async function cleanupBackups() {
  const required = cleanupPreview.value.required_confirm_text || '清理旧备份'
  const { value } = await ElMessageBox.prompt(
    `将删除 ${cleanupPreview.value.candidate_count || 0} 个历史项并回收 ${formatBytes(cleanupPreview.value.reclaimable_bytes)}。该操作不可恢复，请输入“${required}”。`,
    '清理旧备份',
    {
      type: 'warning',
      inputValidator: (text) => String(text || '').trim() === required || `必须输入：${required}`,
    },
  )
  const result = await cleanupOldDataBackups(cleanupPreview.value.preview_id, value)
  ElMessage.success(`已清理 ${result.removed_count || 0} 项，回收 ${formatBytes(result.reclaimed_bytes)}`)
  await load()
}

async function clearAllData() {
  await ElMessageBox.confirm('第一次确认：这会清空所有业务数据。', '清空数据库', { type: 'error' })
  await ElMessageBox.confirm('第二次确认：请确认你已经准备好重新导入订单和项目。', '再次确认', { type: 'error' })
  const { value } = await ElMessageBox.prompt('第三次确认：输入“清空数据库”继续。', '最终确认', {
    confirmButtonText: '清空',
    cancelButtonText: '取消',
    inputValidator: (value) => String(value || '').trim() === '清空数据库' || '必须输入：清空数据库',
  })
  await clearDatabase(value)
  ElMessage.success('数据库已清空，可以重新导入订单')
  await load()
}

onMounted(load)
</script>

<style scoped>
.management-hero {
  padding: 18px;
  border: 1px solid var(--cw-border);
  border-radius: var(--cw-radius-card);
  background: var(--cw-solid);
}

.management-page :deep(.el-button) {
  width: 116px;
  min-width: 116px;
  height: 40px;
  padding: 0 14px;
  justify-content: center;
  border-radius: var(--cw-radius-control);
  margin-left: 0;
  white-space: nowrap;
}

.management-page :deep(.el-button > span) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.management-page :deep(.el-tag) {
  min-width: 56px;
  max-width: 100%;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 10px;
  line-height: 1;
  text-align: center;
  white-space: nowrap;
}

.management-page :deep(.el-tag__content) {
  min-width: 0;
  overflow: hidden;
  text-align: center;
  text-overflow: ellipsis;
}

.management-actions,
.backup-actions,
.row-actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.backup-actions :deep(.el-upload) {
  width: 116px;
}

.backup-actions :deep(.el-upload .el-button) {
  width: 100%;
}

.cleanup-preview { display: block; margin: 10px 0; color: var(--cw-muted); line-height: 1.5; }

.management-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  align-items: stretch;
}

.management-grid > .panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.management-grid > .panel:not(.danger-panel) {
  min-height: 0;
}

.codex-panel {
  grid-column: span 2;
}

.danger-panel {
  grid-column: auto;
  border-color: #fecdd3;
}

.section-head {
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-head.compact {
  margin-bottom: 10px;
}

h2,
h3 {
  margin: 0;
  color: var(--cw-text);
  line-height: 1.25;
}

h2 {
  font-size: 18px;
}

h3 {
  font-size: 16px;
}

.section-head span {
  min-width: 0;
  color: var(--cw-muted);
  font-size: 12px;
  text-align: right;
  white-space: nowrap;
}

.batch-list,
.backup-list,
.feature-list,
.user-list {
  display: grid;
  gap: 10px;
}

.batch-card,
.maintenance-card,
.backup-list div,
.admin-card,
.feature-list > div,
.user-list article {
  border: 1px solid var(--cw-border);
  border-radius: var(--cw-radius-control);
  background: var(--cw-solid);
}

.batch-card {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 132px;
  gap: 12px;
  align-items: center;
  padding: 12px;
}

.batch-card strong,
.batch-card span,
.batch-card small,
.backup-list strong,
.backup-list span,
.backup-list small {
  display: block;
  min-width: 0;
}

.backup-list div {
  min-width: 0;
}

.batch-card strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.batch-card span,
.batch-card small,
.backup-list strong,
.backup-list span,
.backup-list small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.batch-card span,
.batch-card small,
.backup-list span,
.backup-list small {
  margin-top: 4px;
  color: var(--cw-muted);
  font-size: 12px;
}

.maintenance-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.maintenance-card {
  width: 100%;
  min-height: 82px;
  padding: 12px;
  text-align: left;
  cursor: pointer;
}

.maintenance-card small,
.maintenance-card strong {
  display: block;
}

.maintenance-card small {
  color: #2563eb;
  font-weight: 700;
}

.maintenance-card strong {
  margin-top: 8px;
  font-size: 18px;
}

.task-strip,
.admin-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.task-strip div,
.admin-metrics article {
  padding: 10px;
  border-radius: var(--cw-radius-control);
  background: var(--cw-soft);
}

.task-strip span,
.task-strip strong,
.admin-metrics span,
.admin-metrics strong {
  display: block;
}

.task-strip span,
.admin-metrics span {
  color: var(--cw-muted);
  font-size: 12px;
}

.task-strip strong,
.admin-metrics strong {
  margin-top: 4px;
  font-size: 24px;
  line-height: 1;
}

.backup-panel {
  border-color: #bbf7d0;
}

.codex-panel {
  border-color: #bfdbfe;
  background: linear-gradient(145deg, var(--cw-solid), #eff6ff);
}

.codex-panel p {
  margin: 6px 0 14px;
  color: var(--cw-muted);
  line-height: 1.6;
}

.codex-points {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-bottom: 16px;
}

.codex-points span {
  padding: 6px 9px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
}

.backup-panel .backup-actions {
  justify-content: flex-end;
}

.backup-list {
  flex: 1;
  margin-top: 12px;
}

.backup-list div {
  padding: 10px;
}

.danger-panel p {
  margin: 0 0 14px;
  color: #7f1d1d;
  line-height: 1.6;
}

.danger-panel :deep(.el-button) {
  width: 220px;
  min-width: 220px;
}

.row-actions {
  min-width: 0;
  justify-content: flex-end;
}

.row-actions :deep(.el-button) {
  width: 64px;
  min-width: 64px;
  height: 32px;
  padding: 0 10px;
}

.row-actions :deep(.el-tag) {
  width: 56px;
  min-width: 56px;
}

.section-head :deep(.el-tag) {
  width: 56px;
  min-width: 56px;
}

.admin-panel {
  display: grid;
  gap: 12px;
}

.admin-metrics {
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin-top: 0;
}

.admin-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.admin-card {
  padding: 12px;
}

.admin-wide {
  grid-column: 1 / -1;
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
  font-size: 12px;
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
  height: 132px;
  display: flex;
  align-items: end;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--cw-border);
  border-radius: var(--cw-radius-control);
  background: var(--cw-soft);
}

.spark-bars span {
  flex: 1;
  min-width: 4px;
  border-radius: 999px 999px 4px 4px;
  background: linear-gradient(180deg, #3b82f6, #93c5fd);
}

.compact-table {
  border-radius: var(--cw-radius-card);
  overflow: hidden;
}

.restore-preview {
  display: grid;
  gap: 10px;
  margin: 14px 0;
}

.restore-preview div {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  gap: 10px;
}

.restore-preview dt,
.restore-preview dd {
  margin: 0;
}

.restore-preview dt {
  color: var(--cw-muted);
}

.restore-preview dd {
  min-width: 0;
  color: var(--cw-text);
  font-weight: 700;
  overflow-wrap: anywhere;
}

@media (max-width: 1180px) {
  .management-grid,
  .admin-grid {
    grid-template-columns: 1fr;
  }

  .management-grid > .panel:not(.danger-panel) {
    min-height: 0;
  }

  .danger-panel,
  .codex-panel,
  .admin-wide {
    grid-column: auto;
  }

  .admin-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .management-hero,
  .batch-card {
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .management-actions,
  .backup-actions,
  .row-actions {
    justify-content: flex-start;
  }

  .management-actions,
  .backup-actions {
    flex-wrap: wrap;
  }

  .management-page :deep(.el-button),
  .backup-actions :deep(.el-upload),
  .danger-panel :deep(.el-button) {
    width: 100%;
    min-width: 0;
  }

  .row-actions {
    display: grid;
    grid-template-columns: 56px 64px;
    justify-content: start;
  }

  .maintenance-actions,
  .task-strip,
  .admin-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
