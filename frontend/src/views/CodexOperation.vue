<template>
  <section class="page operation-page">
    <header class="page-header operation-hero">
      <div>
        <el-button text @click="$router.push('/integrations/codex')">← 返回 Codex 接入</el-button>
        <h1 class="page-title">写操作审批</h1>
        <p class="page-subtitle">{{ operation?.reason || '查看 Codex 生成的标准化差异，确认后才会修改数据。' }}</p>
      </div>
      <el-tag v-if="operation" :type="statusType(operation.status)" effect="dark" size="large">{{ statusLabel(operation.status) }}</el-tag>
    </header>

    <el-skeleton v-if="loading" :rows="8" animated />
    <template v-else-if="operation">
      <el-alert
        v-if="operation.status === 'pending_approval'"
        :type="operation.risk_level === 'high' ? 'warning' : 'info'"
        show-icon
        :closable="false"
        :title="`审批将在 ${formatTime(operation.approval_expires_at)} 失效；目标状态变化后本单会拒绝执行。`"
      />
      <el-alert v-if="operation.failure_message" type="error" show-icon :closable="false" :title="operation.failure_message" />

      <section class="panel operation-summary">
        <div><span>操作编号</span><code>{{ operation.id }}</code></div>
        <div><span>风险级别</span><strong>{{ operation.risk_level === 'high' ? '高风险' : '常规' }}</strong></div>
        <div><span>原子动作</span><strong>{{ operation.preview?.length || 0 }}</strong></div>
        <div><span>创建时间</span><strong>{{ formatTime(operation.created_at) }}</strong></div>
      </section>

      <section class="change-grid">
        <article v-for="(item, index) in operation.preview || []" :key="`${item.action}-${index}`" class="panel change-card">
          <header>
            <span class="sequence">{{ index + 1 }}</span>
            <div><strong>{{ item.label }}</strong><small>{{ item.action }}</small></div>
            <el-tag :type="item.risk_level === 'high' ? 'danger' : 'info'" effect="plain">{{ item.risk_level === 'high' ? '需重点确认' : '常规' }}</el-tag>
          </header>
          <div class="diff-columns">
            <section>
              <h3>执行前</h3>
              <pre>{{ pretty(item.before) }}</pre>
            </section>
            <section>
              <h3>拟变更</h3>
              <pre>{{ pretty(item.after) }}</pre>
            </section>
          </div>
        </article>
      </section>

      <footer class="approval-bar">
        <template v-if="operation.can_approve">
          <el-button size="large" :loading="rejecting" @click="reject">拒绝</el-button>
          <el-button type="danger" size="large" :loading="approving" @click="approve">批准并执行</el-button>
        </template>
        <el-button v-else-if="operation.can_undo" type="warning" plain size="large" :loading="undoing" @click="requestUndo">申请撤销</el-button>
        <el-button size="large" @click="load">刷新状态</el-button>
      </footer>
    </template>
  </section>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from '../shared/elementApi'
import { approveCodexOperation, getCodexOperation, rejectCodexOperation, requestCodexOperationUndo } from '../api/client'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const approving = ref(false)
const rejecting = ref(false)
const undoing = ref(false)
const operation = ref(null)

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function pretty(value) {
  if (value === null || value === undefined) return '无'
  return JSON.stringify(value, null, 2)
}

function statusLabel(value) {
  return {
    pending_approval: '待审批', succeeded: '已执行', rejected: '已拒绝', expired: '已过期',
    stale: '目标已变化', failed: '执行失败', undone: '已撤销',
  }[value] || value
}

function statusType(value) {
  return { pending_approval: 'warning', succeeded: 'success', rejected: 'info', undone: 'info', stale: 'danger', failed: 'danger' }[value] || 'info'
}

async function load() {
  loading.value = true
  try {
    operation.value = await getCodexOperation(route.params.operationId)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '读取审批单失败')
  } finally {
    loading.value = false
  }
}

async function approve() {
  const highRisk = operation.value.risk_level === 'high'
  if (highRisk) {
    const { value } = await ElMessageBox.prompt('这是高风险操作。输入“批准执行”后继续。', '二次确认', {
      type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消',
      inputValidator: (text) => String(text || '').trim() === '批准执行' || '必须输入：批准执行',
    })
    if (value !== '批准执行') return
  } else {
    await ElMessageBox.confirm('确认按上方差异执行全部动作？任一动作失败时会整体回滚。', '批准 Codex 操作', {
      type: 'warning', confirmButtonText: '批准并执行', cancelButtonText: '取消',
    })
  }
  approving.value = true
  try {
    operation.value = await approveCodexOperation(operation.value.id)
    ElMessage.success('操作已在一个事务内执行')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '审批执行失败')
    await load()
  } finally {
    approving.value = false
  }
}

async function reject() {
  await ElMessageBox.confirm('拒绝后本审批单不会产生任何写入。', '拒绝 Codex 操作', {
    confirmButtonText: '拒绝', cancelButtonText: '取消', type: 'info',
  })
  rejecting.value = true
  try {
    operation.value = await rejectCodexOperation(operation.value.id)
    ElMessage.success('操作已拒绝')
  } finally {
    rejecting.value = false
  }
}

async function requestUndo() {
  await ElMessageBox.confirm('系统会生成一张新的反向变更审批单；仍需再次审核后才执行撤销。', '申请撤销', {
    confirmButtonText: '生成撤销单', cancelButtonText: '取消', type: 'warning',
  })
  undoing.value = true
  try {
    const undo = await requestCodexOperationUndo(operation.value.id)
    ElMessage.success('撤销审批单已生成')
    await router.push(`/integrations/codex/operations/${undo.id}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '生成撤销单失败')
  } finally {
    undoing.value = false
  }
}

watch(() => route.params.operationId, load)
onMounted(load)
</script>

<style scoped>
.operation-page { display: grid; gap: 14px; padding-bottom: 96px; }
.operation-hero { padding: 18px; border: 1px solid var(--cw-border); border-radius: var(--cw-radius-card); background: var(--cw-solid); }
.operation-hero h1 { margin-top: 8px; }
.operation-summary { display: grid; grid-template-columns: 1.4fr repeat(3, minmax(0, 1fr)); gap: 12px; }
.operation-summary > div { padding: 10px; border-radius: var(--cw-radius-control); background: var(--cw-soft); }
.operation-summary span, .operation-summary strong, .operation-summary code { display: block; }
.operation-summary span { color: var(--cw-muted); font-size: 12px; margin-bottom: 5px; }
.operation-summary code { overflow-wrap: anywhere; }
.change-grid { display: grid; gap: 12px; }
.change-card header { display: flex; align-items: center; gap: 12px; }
.change-card header > div { flex: 1; min-width: 0; }
.change-card header strong, .change-card header small { display: block; }
.change-card header small { color: var(--cw-muted); margin-top: 3px; }
.sequence { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: #dbeafe; color: #1d4ed8; font-weight: 800; }
.diff-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.diff-columns section { min-width: 0; padding: 12px; border-radius: var(--cw-radius-control); background: var(--cw-soft); }
.diff-columns h3 { margin: 0 0 8px; font-size: 13px; color: var(--cw-muted); }
.diff-columns pre { max-height: 360px; overflow: auto; margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.6 ui-monospace, monospace; }
.approval-bar { position: sticky; bottom: 12px; display: flex; justify-content: flex-end; gap: 10px; padding: 12px; border: 1px solid var(--cw-border); border-radius: var(--cw-radius-card); background: color-mix(in srgb, var(--cw-solid) 92%, transparent); backdrop-filter: blur(16px); box-shadow: 0 14px 34px rgba(15, 23, 42, .14); }
@media (max-width: 760px) { .operation-summary, .diff-columns { grid-template-columns: 1fr; } }
</style>
