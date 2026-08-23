<template>
  <section class="conflict-page">
    <header>
      <div>
        <p>桌面同步</p>
        <h1>冲突处理中心</h1>
        <span>只冻结冲突事务，其他数据仍会继续同步。</span>
      </div>
      <el-button :loading="loading" @click="loadConflicts">刷新</el-button>
    </header>

    <el-empty v-if="!loading && !items.length" description="当前没有待处理冲突" />
    <div v-else class="conflict-list">
      <article v-for="item in items" :key="item.id" class="conflict-card">
        <div class="conflict-summary">
          <div>
            <strong>{{ entityLabel(item.entity_type) }}</strong>
            <small>{{ reasonLabel(item.reason) }}</small>
          </div>
          <el-tag type="danger" effect="plain">{{ (item.conflict_fields || []).join('、') || '整笔事务' }}</el-tag>
        </div>
        <dl>
          <div><dt>服务器版本</dt><dd>{{ formatValue(item.server_version) }}</dd></div>
          <div><dt>本地版本</dt><dd>{{ formatValue(item.client_version?.fields || item.client_version) }}</dd></div>
        </dl>
        <footer>
          <el-button :loading="resolving === item.id" @click="resolve(item, 'server')">保留在线版本</el-button>
          <el-button type="primary" :loading="resolving === item.id" @click="resolve(item, 'client')">使用本地版本</el-button>
          <el-button type="danger" plain :loading="resolving === item.id" @click="resolve(item, 'delete')">确认删除</el-button>
        </footer>
      </article>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../shared/elementApi'
import { getDesktopConflicts, resolveDesktopConflict } from '../shared/desktopBridge'

const loading = ref(false)
const resolving = ref('')
const items = ref([])

const reasonLabels = {
  absolute_inventory: '库存绝对数与在线修改冲突',
  inventory_lot_version: '同一库存批次已变化',
  delete_vs_modify: '删除与修改同时发生',
  same_field_window: '5 分钟内同字段并发修改',
  clock_drift: '设备时钟偏差过大'
}

function reasonLabel(reason) { return reasonLabels[reason] || reason || '需要人工确认' }
function entityLabel(type) { return ({ components: '元器件', inventory_lots: '库存批次' })[type] || type || '业务事务' }
function formatValue(value) {
  const text = JSON.stringify(value || {}, null, 2)
  return text.length > 800 ? `${text.slice(0, 800)}…` : text
}

async function loadConflicts() {
  loading.value = true
  try {
    const result = await getDesktopConflicts()
    items.value = result.items || []
  } catch (error) {
    ElMessage.warning(error?.message || '当前离线，联网后可处理冲突')
  } finally {
    loading.value = false
  }
}

async function resolve(item, resolution) {
  const action = resolution === 'server' ? '保留在线版本' : (resolution === 'client' ? '使用本地版本' : '确认删除')
  await ElMessageBox.confirm(`确定${action}？处理后会立即同步到本机。`, '处理同步冲突', { type: 'warning' })
  resolving.value = item.id
  try {
    await resolveDesktopConflict(item.id, resolution)
    ElMessage.success('冲突已处理并同步')
    await loadConflicts()
  } catch (error) {
    ElMessage.error(error?.message || '冲突处理失败')
  } finally {
    resolving.value = ''
  }
}

onMounted(loadConflicts)
</script>

<style scoped>
.conflict-page { display: grid; gap: 20px; padding: 28px; max-width: 1180px; margin: 0 auto; }
.conflict-page > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.conflict-page h1 { margin: 4px 0 8px; font-size: 28px; }.conflict-page p { margin: 0; color: var(--cw-primary); font-weight: 700; }.conflict-page span { color: var(--cw-muted); }
.conflict-list { display: grid; gap: 14px; }.conflict-card { padding: 20px; border: 1px solid var(--cw-border); border-radius: 16px; background: var(--cw-surface); box-shadow: var(--cw-shadow-sm); }
.conflict-summary { display: flex; justify-content: space-between; gap: 16px; }.conflict-summary strong,.conflict-summary small { display: block; }.conflict-summary small { margin-top: 5px; color: var(--cw-muted); }
dl { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 18px 0; }dl > div { min-width: 0; padding: 12px; border-radius: 10px; background: var(--cw-surface-muted); }dt { margin-bottom: 8px; font-weight: 700; }dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.55 ui-monospace, monospace; color: var(--cw-muted); }
footer { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
@media (max-width: 720px) { .conflict-page { padding: 18px; } dl { grid-template-columns: 1fr; } }
</style>
