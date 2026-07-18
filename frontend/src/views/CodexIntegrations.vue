<template>
  <section class="page codex-page">
    <header class="page-header codex-hero">
      <div>
        <el-button text @click="$router.push('/about')">← 返回管理</el-button>
        <h1 class="page-title">Codex 接入</h1>
        <p class="page-subtitle">长期令牌仅查询个人库；所有写入必须在这里逐单审批。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="板卡图片、原理图和本地 BOM 不会上传；技能只发送提取后的结构化器件需求。"
    />

    <div class="codex-grid">
      <section class="panel token-panel">
        <div class="section-head">
          <div>
            <h2>查询令牌</h2>
            <span>默认 365 天 · 读取个人库并提交无副作用草案</span>
          </div>
          <el-button type="primary" @click="openCreate">新建令牌</el-button>
        </div>
        <div class="token-list">
          <article v-for="token in tokens" :key="token.id" class="token-card">
            <div>
              <strong>{{ token.name }}</strong>
              <code>{{ token.prefix }}…</code>
              <small>到期 {{ formatTime(token.expires_at) }} · 最近使用 {{ formatTime(token.last_used_at) }}</small>
            </div>
            <div class="token-actions">
              <el-tag :type="token.status === 'active' ? 'success' : 'info'" effect="plain">{{ statusLabel(token.status) }}</el-tag>
              <el-button v-if="token.status === 'active'" type="danger" plain size="small" @click="revoke(token)">撤销</el-button>
            </div>
          </article>
          <el-empty v-if="!tokens.length" description="还没有 Codex 令牌" :image-size="72" />
        </div>
      </section>

      <section class="panel operation-panel">
        <div class="section-head">
          <div>
            <h2>写操作审批</h2>
            <span>10 分钟有效 · 成功后 30 天可申请撤销</span>
          </div>
          <el-tag type="warning" effect="plain">逐单审批</el-tag>
        </div>
        <div class="operation-list">
          <router-link
            v-for="operation in operations"
            :key="operation.id"
            :to="`/integrations/codex/operations/${operation.id}`"
            class="operation-card"
          >
            <span class="risk-dot" :class="operation.risk_level"></span>
            <div>
              <strong>{{ operation.reason || operation.preview?.[0]?.label || 'Codex 操作' }}</strong>
              <small>{{ operation.preview?.length || 0 }} 个动作 · {{ formatTime(operation.created_at) }}</small>
            </div>
            <el-tag :type="operationTag(operation.status)" effect="plain">{{ operationLabel(operation.status) }}</el-tag>
          </router-link>
          <el-empty v-if="!operations.length" description="暂无待审批操作" :image-size="72" />
        </div>
      </section>
    </div>

    <el-dialog v-model="createVisible" title="新建 Codex 只读令牌" width="480px" append-to-body>
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="tokenForm.name" maxlength="120" placeholder="例如：工作站 Codex" />
        </el-form-item>
        <el-form-item label="有效期">
          <el-input-number v-model="tokenForm.expires_in_days" :min="1" :max="3650" />
          <span class="form-hint">天；建议保留默认 365 天</span>
        </el-form-item>
      </el-form>
      <el-alert type="warning" show-icon :closable="false" title="密钥只显示一次。关闭后无法再次查看，只能撤销并重建。" />
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" :disabled="!tokenForm.name.trim()" @click="create">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="secretVisible" title="保存 Codex 令牌" width="620px" append-to-body :close-on-click-modal="false">
      <el-alert type="success" show-icon :closable="false" title="令牌创建成功，请立即复制到技能配置中。" />
      <div class="secret-box">
        <code>{{ oneTimeSecret }}</code>
        <el-button type="primary" @click="copySecret">复制</el-button>
      </div>
      <p class="secret-note">请勿把令牌放进命令行参数、聊天回答、日志、仓库或截图。</p>
      <template #footer>
        <el-button type="primary" @click="closeSecret">我已安全保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from '../shared/elementApi'
import { createCodexToken, listCodexOperations, listCodexTokens, revokeCodexToken } from '../api/client'

const loading = ref(false)
const creating = ref(false)
const createVisible = ref(false)
const secretVisible = ref(false)
const oneTimeSecret = ref('')
const tokens = ref([])
const operations = ref([])
const tokenForm = reactive({ name: '', expires_in_days: 365 })

function formatTime(value) {
  if (!value) return '从未'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function statusLabel(value) {
  return { active: '有效', revoked: '已撤销', expired: '已过期' }[value] || value
}

function operationLabel(value) {
  return {
    pending_approval: '待审批', succeeded: '已执行', rejected: '已拒绝', expired: '已过期',
    stale: '目标已变化', failed: '失败', undone: '已撤销',
  }[value] || value
}

function operationTag(value) {
  return { pending_approval: 'warning', succeeded: 'success', rejected: 'info', undone: 'info', stale: 'danger', failed: 'danger' }[value] || 'info'
}

async function load() {
  loading.value = true
  try {
    const [tokenRows, operationRows] = await Promise.all([listCodexTokens(), listCodexOperations()])
    tokens.value = tokenRows
    operations.value = operationRows
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '读取 Codex 接入信息失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  tokenForm.name = ''
  tokenForm.expires_in_days = 365
  createVisible.value = true
}

async function create() {
  creating.value = true
  try {
    const result = await createCodexToken({ name: tokenForm.name.trim(), expires_in_days: tokenForm.expires_in_days })
    oneTimeSecret.value = result.token
    createVisible.value = false
    secretVisible.value = true
    await load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '创建令牌失败')
  } finally {
    creating.value = false
  }
}

async function revoke(token) {
  await ElMessageBox.confirm(`撤销“${token.name}”？使用该令牌的技能会立即停止访问。`, '撤销 Codex 令牌', {
    type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消',
  })
  await revokeCodexToken(token.id)
  ElMessage.success('令牌已撤销')
  await load()
}

async function copySecret() {
  try {
    await navigator.clipboard.writeText(oneTimeSecret.value)
    ElMessage.success('令牌已复制')
  } catch {
    ElMessage.warning('浏览器未允许复制，请手动选择令牌')
  }
}

function closeSecret() {
  oneTimeSecret.value = ''
  secretVisible.value = false
}

onMounted(load)
</script>

<style scoped>
.codex-page { display: grid; gap: 14px; }
.codex-hero { padding: 18px; border: 1px solid var(--cw-border); border-radius: var(--cw-radius-card); background: var(--cw-solid); }
.codex-hero h1 { margin-top: 8px; }
.codex-grid { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); gap: 14px; }
.token-list, .operation-list { display: grid; gap: 10px; margin-top: 14px; }
.token-card, .operation-card { display: flex; align-items: center; gap: 12px; padding: 14px; border: 1px solid var(--cw-border); border-radius: var(--cw-radius-control); background: var(--cw-soft); }
.token-card > div:first-child, .operation-card > div { min-width: 0; flex: 1; }
.token-card strong, .token-card code, .token-card small, .operation-card strong, .operation-card small { display: block; }
.token-card code { margin: 5px 0; color: #2563eb; }
.token-card small, .operation-card small, .form-hint, .secret-note { color: var(--cw-muted); }
.token-actions { display: flex; align-items: center; gap: 8px; }
.operation-card { color: inherit; text-decoration: none; transition: border-color .18s ease, transform .18s ease; }
.operation-card:hover { border-color: #60a5fa; transform: translateY(-1px); }
.risk-dot { width: 9px; height: 36px; border-radius: 999px; background: #60a5fa; }
.risk-dot.high { background: #ef4444; }
.form-hint { margin-left: 10px; }
.secret-box { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; margin: 16px 0 8px; }
.secret-box code { overflow-wrap: anywhere; padding: 14px; border-radius: 10px; background: #0f172a; color: #e2e8f0; }
@media (max-width: 900px) { .codex-grid { grid-template-columns: 1fr; } }
</style>
