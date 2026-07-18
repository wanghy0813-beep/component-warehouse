<template>
  <section class="lcsc-paste-card">
    <div class="lcsc-card-head">
      <div>
        <strong>立创一键录入</strong>
        <p>粘贴立创器件的“一键复制”文本，识别到 C 编号后会自动查询并填充草稿。</p>
      </div>
      <el-tag v-if="status" :type="statusMeta.type" effect="plain">{{ statusMeta.label }}</el-tag>
    </div>
    <el-input
      v-model="rawText"
      type="textarea"
      :rows="5"
      maxlength="4000"
      show-word-limit
      placeholder="名称：3.3V 250mA 5.5V&#10;型号：LP5907MFX-3.3/NOPB&#10;品牌：TI(德州仪器)&#10;封装：SOT-23-5&#10;编号：C80670"
    />
    <div class="lcsc-actions">
      <el-button type="primary" plain :loading="loading" :disabled="!detectedNumber" @click="runLookup(true)">
        {{ response ? '重新查询' : '识别并补全' }}
      </el-button>
      <span v-if="detectedNumber">已识别 {{ detectedNumber }}</span>
      <span v-else>等待完整的 Cxxxx 编号</span>
    </div>
    <el-alert v-if="errorText" type="error" :closable="false" show-icon :title="errorText" />
    <div v-if="response" class="lcsc-result">
      <p class="result-summary">{{ statusMeta.summary }}</p>
      <el-alert
        v-if="response.existing_component"
        type="warning"
        :closable="false"
        show-icon
        :title="`当前账号已存在 ${response.existing_component.warehouse_code || response.existing_component.name || detectedNumber}`"
      >
        <template #default>
          <el-button size="small" type="warning" plain @click="$emit('existing', response.existing_component)">
            {{ existingActionLabel }}
          </el-button>
        </template>
      </el-alert>
      <ul v-if="response.warnings?.length" class="warning-list">
        <li v-for="warning in response.warnings" :key="warning">{{ warning }}</li>
      </ul>
      <div v-if="response.sources?.length" class="source-links">
        <span>资料来源</span>
        <a v-for="source in response.sources" :key="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">
          {{ source.title || source.site_name || '打开来源' }}
        </a>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  lookup: { type: Function, required: true },
  existingActionLabel: { type: String, default: '打开现有器件' }
})

const emit = defineEmits(['draft', 'existing'])
const rawText = ref('')
const loading = ref(false)
const response = ref(null)
const errorText = ref('')
let requestSequence = 0
let lookupTimer = 0
let requestController = null

const detectedNumber = computed(() => {
  const match = rawText.value.match(/(?:^|[^A-Za-z0-9])C\s*(\d{3,})(?!\d)/i)
  return match ? `C${match[1]}` : ''
})

const status = computed(() => response.value?.status || '')
const statusMeta = computed(() => ({
  official: { label: '立创官方', type: 'success', summary: '已直接读取立创官方商品数据；核心字段以官方结果为准。' },
  ai_fallback: { label: 'AI 联网补全', type: 'warning', summary: '立创商品页未直接读取成功，已使用带精确编号证据的 AI 联网结果。' },
  parsed_only: { label: '仅文本解析', type: 'danger', summary: '未完成联网核验，仅保留粘贴文本和低风险整理；保存前请逐项核对。' }
})[status.value] || { label: '', type: 'info', summary: '' })

function errorMessage(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  return error?.message || '立创器件查询失败，请稍后重试'
}

function scheduleLookup() {
  clearTimeout(lookupTimer)
  if (!detectedNumber.value) return
  lookupTimer = window.setTimeout(() => runLookup(false), 450)
}

async function runLookup(force = false) {
  if (!detectedNumber.value || loading.value && !force) return
  clearTimeout(lookupTimer)
  requestController?.abort()
  requestController = new AbortController()
  const sequence = ++requestSequence
  loading.value = true
  errorText.value = ''
  try {
    const result = await props.lookup(rawText.value, { signal: requestController.signal })
    if (sequence !== requestSequence) return
    response.value = result
    emit('draft', result.draft || {}, result)
  } catch (error) {
    if (sequence !== requestSequence || error?.name === 'CanceledError' || error?.name === 'AbortError') return
    response.value = null
    errorText.value = errorMessage(error)
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

function reset() {
  clearTimeout(lookupTimer)
  requestController?.abort()
  requestSequence += 1
  rawText.value = ''
  loading.value = false
  response.value = null
  errorText.value = ''
}

watch(rawText, (value, previous) => {
  if (!value.trim()) {
    reset()
    return
  }
  if (value !== previous) scheduleLookup()
})

onBeforeUnmount(() => {
  clearTimeout(lookupTimer)
  requestController?.abort()
})

defineExpose({ reset, runLookup })
</script>

<style scoped>
.lcsc-paste-card {
  display: grid;
  gap: 11px;
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid #99f6e4;
  border-radius: var(--cw-radius-card);
  background: linear-gradient(135deg, #ecfdf5, #ffffff 72%);
}
.lcsc-card-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.lcsc-card-head strong { color: #065f46; font-size: 16px; }
.lcsc-card-head p, .result-summary { margin: 4px 0 0; color: #52606d; line-height: 1.55; }
.lcsc-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; color: #667085; }
.lcsc-result { display: grid; gap: 9px; }
.warning-list { margin: 0; padding-left: 20px; color: #9a3412; line-height: 1.55; }
.source-links { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; color: #667085; }
.source-links a { color: #0f766e; font-weight: 650; overflow-wrap: anywhere; }
@media (max-width: 620px) {
  .lcsc-card-head { align-items: stretch; flex-direction: column; }
  .lcsc-actions { display: grid; grid-template-columns: 1fr; }
  .lcsc-actions .el-button { width: 100%; }
}
</style>
