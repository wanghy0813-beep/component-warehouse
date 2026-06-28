<template>
  <section class="page more-page">
    <div class="page-header more-hero">
      <div>
        <h1 class="page-title">更多</h1>
        <p class="page-subtitle">管理导入记录、AI 整理、数据备份、操作记录和危险操作</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <nav class="more-shortcuts" aria-label="更多功能入口">
      <router-link to="/coverage"><strong>覆盖图</strong><span>查看仓储位置</span></router-link>
      <router-link to="/purchases"><strong>采购</strong><span>计划、到货与入库</span></router-link>
      <router-link to="/risks"><strong>风险</strong><span>缺料与封装检查</span></router-link>
      <router-link v-if="FEATURE_EDA_ENABLED" to="/eda-guide"><strong>AD 说明</strong><span>Windows 同步和库使用文档</span></router-link>
      <router-link to="/manual"><strong>使用说明书</strong><span>个人版、团队版和完整工作流</span></router-link>
      <router-link v-if="isAdmin" to="/admin"><strong>管理</strong><span>用户与埋点统计</span></router-link>
    </nav>

    <div class="more-grid">
      <section class="panel">
        <div class="section-head">
          <h2>导入批次</h2>
          <span>订单导入、自动合并和回滚</span>
        </div>
        <div class="batch-list">
          <article v-for="batch in importBatches" :key="batch.id" class="batch-card">
            <div>
              <strong>#{{ batch.id }} {{ batch.source_file || 'Excel 导入' }}</strong>
              <span>{{ formatTime(batch.created_at) }} · 新增 {{ batch.created_count }} · 合并 {{ batch.merged_count }} · 跳过 {{ batch.skipped_count }} · 抵消待采购 {{ batch.resolved_pending_count }}</span>
              <small v-if="batch.rollback_summary">{{ batch.rollback_summary }}</small>
            </div>
            <el-tag :type="batch.status === 'rolled_back' ? 'info' : 'success'">{{ batch.status === 'rolled_back' ? '已撤销' : '有效' }}</el-tag>
            <el-button size="small" :disabled="batch.status === 'rolled_back'" @click="rollbackBatch(batch)">撤销</el-button>
          </article>
          <el-empty v-if="!importBatches.length" description="暂无导入批次" :image-size="80" />
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <h2>AI 维护</h2>
          <span>后台静默队列</span>
        </div>
        <div class="maintenance-grid">
          <button class="maintenance-card" @click="enqueueOrganize">
            <small>分类整理</small>
            <strong>重新整理分类</strong>
            <span>把待整理/旧分类物料加入 AI 规范化队列</span>
          </button>
          <button class="maintenance-card" @click="resetAi">
            <small>AI 重置</small>
            <strong>重置并重跑</strong>
            <span>清除旧 AI 摘要和标签，重新建立规范字段</span>
          </button>
        </div>
        <div class="task-strip">
          <div><span>待处理</span><strong>{{ taskSummary.pending || 0 }}</strong></div>
          <div><span>需更新</span><strong>{{ taskSummary.stale || 0 }}</strong></div>
          <div><span>失败</span><strong>{{ taskSummary.failed || 0 }}</strong></div>
          <div><span>完成</span><strong>{{ taskSummary.completed || 0 }}</strong></div>
        </div>
      </section>

      <section class="panel backup-panel">
        <div class="section-head">
          <h2>数据备份</h2>
          <el-tag type="success" effect="plain">ZIP</el-tag>
        </div>
        <p>导出 SQLite 一致性快照和 data 目录全部文件，用于服务器异常、迁移或重装前留档。</p>
        <div class="backup-actions">
          <el-button type="primary" plain :loading="backupLoading" @click="downloadBackup">导出数据备份</el-button>
          <el-upload :show-file-list="false" accept=".zip" :http-request="inspectBackupUpload">
            <el-button plain :loading="restoreInspecting">上传并预览恢复</el-button>
          </el-upload>
        </div>
        <div class="backup-list">
          <div v-for="item in backups.slice(0, 4)" :key="item.filename">
            <strong>{{ backupTypeLabel(item.type) }}</strong>
            <span>{{ formatTime(item.created_at) }} · {{ formatBytes(item.bytes) }}</span>
          </div>
          <small v-if="!backups.length">暂无本机自动备份</small>
        </div>
      </section>

      <section class="panel category-code-panel">
        <div class="section-head">
          <h2>类别与器件编号</h2>
          <span>由系统统一维护</span>
        </div>
        <p class="category-policy">订单中已有明确类别时优先采用订单类别；没有可靠类别时，只有高置信度 AI 建议才会自动分类。系统限制使用统一类别，并为每类自动分配唯一三字符前缀。</p>
        <div class="category-code-list">
          <div v-for="category in categories" :key="category.id">
            <strong>{{ category.name }}</strong>
            <code>{{ category.code_prefix || '自动生成中' }}</code>
            <el-tag type="success" effect="plain">系统管理</el-tag>
          </div>
        </div>
      </section>

      <section class="panel danger-panel">
        <div class="section-head">
          <h2>清库重录</h2>
          <el-tag type="danger" effect="plain">危险操作</el-tag>
        </div>
        <p>清空元器件、项目、BOM、导入批次、AI 任务和台账日志，只保留默认分类。适合你决定重新导入全部立创订单前使用。</p>
        <el-button type="danger" plain @click="clearAllData">三次确认后清空数据库</el-button>
      </section>
    </div>

    <section class="panel">
      <div class="section-head">
        <h2>操作记录</h2>
        <span>入库、出库、BOM、导入和维护记录，最多显示最近 {{ visibleLogs.length }} 条</span>
      </div>
      <el-table :data="visibleLogs" row-key="id" stripe class="ledger-table" max-height="560" empty-text="暂无操作记录">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="summary" label="操作" min-width="320" show-overflow-tooltip />
        <el-table-column prop="action" label="类型" width="180" show-overflow-tooltip />
        <el-table-column label="数量" width="90" align="right">
          <template #default="{ row }">{{ row.quantity_delta || '-' }}</template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="restoreDialog" title="恢复数据库备份" width="560px" append-to-body>
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
        <el-input v-model="restoreConfirm" placeholder="输入：恢复数据库" />
      </template>
      <template #footer>
        <el-button @click="restoreDialog = false">取消</el-button>
        <el-button type="danger" :loading="restoreLoading" :disabled="restoreConfirm !== '恢复数据库'" @click="submitRestore">确认恢复</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../shared/elementApi'
import { Refresh } from '@element-plus/icons-vue'
import { FEATURE_EDA_ENABLED } from '../shared/features'
import {
  clearDatabase,
  dashboardSummary,
  enqueueOrganizeAiTasks,
  exportDataBackup,
  getCategories,
  getDataBackups,
  getActivityLogs,
  getAiTaskSummary,
  getOrderImportBatches,
  inspectDataBackup,
  resetAndReorganize,
  restoreDataBackup,
  rollbackOrderImportBatch,
} from '../api/client'

const summary = ref({})
const storedUser = (() => {
  try { return JSON.parse(localStorage.getItem('cw_legacy_user') || '{}') }
  catch { return {} }
})()
const isAdmin = Boolean(storedUser.isAdmin || storedUser.is_admin)
const taskSummary = ref({ pending: 0, stale: 0, completed: 0, failed: 0 })
const logs = ref([])
const importBatches = ref([])
const backups = ref([])
const categories = ref([])
const backupLoading = ref(false)
const restoreDialog = ref(false)
const restoreFile = ref(null)
const restorePreview = ref(null)
const restoreConfirm = ref('')
const restoreInspecting = ref(false)
const restoreLoading = ref(false)
const visibleLogs = computed(() => logs.value.slice(0, 120))

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

async function loadImportBatches() {
  importBatches.value = await getOrderImportBatches({ limit: 20 })
}

async function loadBackups() {
  const result = await getDataBackups()
  backups.value = result.items || []
}

async function load() {
  try {
    const [dashboard, tasks, activity, categoryRows] = await Promise.all([
      dashboardSummary(),
      getAiTaskSummary(),
      getActivityLogs({ limit: 160 }),
      getCategories(),
      loadImportBatches(),
      loadBackups(),
    ])
    summary.value = dashboard
    taskSummary.value = tasks
    logs.value = activity
    categories.value = categoryRows
  } catch (error) {
    ElMessage.error('读取维护信息失败')
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

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
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

async function downloadBackup() {
  backupLoading.value = true
  try {
    const blob = await exportDataBackup()
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    downloadBlob(blob, `component-warehouse-backup-${stamp}.zip`)
    ElMessage.success('数据备份已开始下载')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '导出数据备份失败')
  } finally {
    backupLoading.value = false
  }
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

async function clearAllData() {
  await ElMessageBox.confirm('第一次确认：这会清空所有业务数据，只保留默认分类。', '清空数据库', { type: 'error' })
  await ElMessageBox.confirm('第二次确认：请确认你已经准备好重新导入所有立创订单和项目。', '再次确认', { type: 'error' })
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
.more-hero {
  padding: 22px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: none;
}

.more-shortcuts {
  display: none;
}

.more-grid {
  display: grid;
  grid-template-columns: 1.35fr 1fr 0.9fr;
  gap: 14px;
}

.section-head,
.batch-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

h2 {
  margin: 0;
  font-size: 17px;
}

.batch-list {
  display: grid;
  gap: 10px;
}

.batch-card,
.maintenance-card {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  background: #fff;
}

.batch-card strong,
.batch-card span,
.batch-card small {
  display: block;
}

.batch-card span,
.batch-card small {
  margin-top: 4px;
  color: var(--cw-muted);
  font-size: 12px;
}

.maintenance-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.maintenance-card {
  text-align: left;
  cursor: pointer;
}

.maintenance-card small,
.maintenance-card strong,
.maintenance-card span {
  display: block;
}

.maintenance-card small {
  color: #2563eb;
  font-weight: 700;
}

.maintenance-card span {
  margin-top: 6px;
  color: var(--cw-muted);
  font-size: 12px;
  line-height: 1.5;
}

.task-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-top: 14px;
}

.task-strip div {
  padding: 10px;
  border-radius: var(--cw-radius-control);
  background: #f8fafc;
}

.task-strip span,
.task-strip strong {
  display: block;
}

.task-strip span {
  color: var(--cw-muted);
  font-size: 12px;
}

.task-strip strong {
  margin-top: 4px;
  font-size: 22px;
}

.backup-panel {
  border-color: #bbf7d0;
  background: linear-gradient(135deg, #f0fdf4, #fff);
}

.backup-panel p {
  color: #166534;
  line-height: 1.65;
}

.backup-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.backup-list {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.backup-list div {
  display: grid;
  gap: 3px;
  padding: 9px;
  border: 1px solid #bbf7d0;
  border-radius: var(--cw-radius-control);
  background: rgba(255, 255, 255, 0.72);
}

.backup-list strong {
  color: #14532d;
}

.backup-list span,
.backup-list small {
  color: var(--cw-muted);
  font-size: 12px;
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

.category-code-list {
  display: grid;
  gap: 8px;
}

.category-policy {
  color: var(--cw-muted);
  line-height: 1.65;
}

.category-code-list > div {
  display: grid;
  grid-template-columns: minmax(100px, 1fr) 108px 96px;
  gap: 8px;
  align-items: center;
}

.category-code-list code {
  padding: 8px 10px;
  border: 1px solid var(--cw-border);
  border-radius: var(--cw-radius-control);
  background: var(--cw-soft);
  text-align: center;
}

.danger-panel {
  border-color: #fecdd3;
  background: linear-gradient(135deg, #fff1f2, #fff);
}

.danger-panel p {
  color: #7f1d1d;
  line-height: 1.65;
}

.ledger-table {
  border-radius: 16px;
  overflow: hidden;
}

@media (max-width: 1100px) {
  .more-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 620px) {
  .more-shortcuts {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 12px;
  }

  .more-shortcuts a {
    min-width: 0;
    display: grid;
    gap: 4px;
    padding: 12px 8px;
    border: 1px solid var(--cw-border);
    border-radius: var(--cw-radius-control);
    background: var(--cw-solid);
    color: var(--cw-text);
    text-align: center;
    text-decoration: none;
  }

  .more-shortcuts span {
    overflow: hidden;
    color: var(--cw-muted);
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .maintenance-grid,
  .task-strip,
  .category-code-list > div {
    grid-template-columns: 1fr;
  }
}
</style>
