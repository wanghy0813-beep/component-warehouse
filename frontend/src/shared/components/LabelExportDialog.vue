<template>
  <el-dialog v-model="visible" title="A4 直角 40 格标签" width="560px">
    <el-alert type="info" :closable="false" show-icon>
      纸张规格固定为 52.5 × 29.7 mm，4列×10行。打印时选择 A4、实际大小 100%、无页边距、关闭页眉页脚。
    </el-alert>
    <el-form label-width="110px" class="label-form">
      <el-form-item v-if="showScope" label="导出范围">
        <el-segmented v-model="form.scope" :options="scopeChoices" />
      </el-form-item>
      <el-form-item v-if="showScope && form.scope === 'imported'" label="导入日期">
        <el-date-picker
          v-model="form.imported_range"
          type="daterange"
          unlink-panels
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          range-separator="至"
        />
      </el-form-item>
      <el-form-item v-if="showScope" label="排除类别">
        <el-select
          v-model="form.excluded_categories"
          multiple
          filterable
          clearable
          collapse-tags
          collapse-tags-tooltip
          placeholder="例如：开发板、连接件"
        >
          <el-option
            v-for="item in excludedCategoryOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="起始格号"><el-input-number v-model="form.start_slot" :min="1" :max="40" /></el-form-item>
      <el-form-item label="每项份数"><el-input-number v-model="form.copies" :min="1" :max="20" /></el-form-item>
      <el-form-item label="横向偏移"><el-input-number v-model="form.offset_x_mm" :min="-5" :max="5" :step="0.1" :precision="1" /><span>mm</span></el-form-item>
      <el-form-item label="纵向偏移"><el-input-number v-model="form.offset_y_mm" :min="-5" :max="5" :step="0.1" :precision="1" /><span>mm</span></el-form-item>
      <el-form-item v-if="showScope && customLabelOptions.length" label="附加标签">
        <div class="append-labels">
          <el-select
            v-model="form.custom_label_ids"
            multiple
            filterable
            clearable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择要追加打印的自定义标签"
          >
            <el-option
              v-for="item in customLabelOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <article v-for="item in selectedCustomLabels" :key="item.id" class="append-label-row">
            <span>{{ item.name }}</span>
            <label>份数 <el-input-number v-model="form.custom_label_copies[item.id]" :min="1" :max="40" /></label>
          </article>
        </div>
      </el-form-item>
    </el-form>
    <p class="calibration-note">首次使用建议先打印校准页，检查第 1、4、37、40 格边界，再调整偏移。设置只保存在当前浏览器。</p>
    <template #footer>
      <el-button :loading="loading" @click="submit(true)">打印校准页</el-button>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submit(false)">生成标签</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { ElMessage } from '../elementApi'

const props = defineProps({
  modelValue: Boolean,
  loading: Boolean,
  showScope: Boolean,
  categoryOptions: { type: Array, default: () => [] },
  scopeOptions: { type: Array, default: () => [] },
  customLabelTemplates: { type: Array, default: () => [] }
})
const emit = defineEmits(['update:modelValue', 'export'])
const storageKey = 'cw_label_40_settings'
const defaults = {
  scope: 'imported',
  imported_range: [],
  excluded_categories: ['开发板'],
  start_slot: 1,
  copies: 1,
  offset_x_mm: 0,
  offset_y_mm: 0,
  custom_label_ids: [],
  custom_label_copies: {},
  exclusion_default_version: 1
}
const defaultScopeOptions = [
  { label: '指定日期', value: 'imported' },
  { label: '全部库存', value: 'all' }
]
let stored = {}
try { stored = JSON.parse(localStorage.getItem(storageKey) || '{}') } catch {}
const form = reactive({ ...defaults, ...stored })
if (!Array.isArray(form.excluded_categories)) form.excluded_categories = []
if (stored.exclusion_default_version !== 1 && !form.excluded_categories.includes('开发板')) form.excluded_categories.push('开发板')
form.exclusion_default_version = 1
if (!Array.isArray(form.custom_label_ids)) form.custom_label_ids = []
if (!form.custom_label_copies || typeof form.custom_label_copies !== 'object' || Array.isArray(form.custom_label_copies)) form.custom_label_copies = {}
const scopeChoices = computed(() => props.scopeOptions?.length ? props.scopeOptions : defaultScopeOptions)
const excludedCategoryOptions = computed(() => {
  const names = new Set()
  for (const item of props.categoryOptions || []) {
    const name = typeof item === 'string' ? item : item?.name
    if (name) names.add(String(name))
  }
  names.add('未分类')
  return [...names].map((name) => ({ label: name, value: name }))
})
const customLabelOptions = computed(() => (props.customLabelTemplates || []).map((item) => ({ label: item.name || '自定义标签', value: item.id })))
const selectedCustomLabels = computed(() => {
  const selected = new Set(form.custom_label_ids || [])
  return (props.customLabelTemplates || []).filter((item) => selected.has(item.id))
})
const visible = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
watch([visible, scopeChoices], () => {
  if (!props.showScope) return
  if (!scopeChoices.value.some((item) => item.value === form.scope)) {
    form.scope = scopeChoices.value[0]?.value || 'imported'
  }
}, { immediate: true })
watch(form, () => localStorage.setItem(storageKey, JSON.stringify(form)), { deep: true })
watch(() => form.custom_label_ids, () => {
  const selected = new Set(form.custom_label_ids || [])
  for (const id of selected) {
    if (!form.custom_label_copies[id]) form.custom_label_copies[id] = 1
  }
  for (const id of Object.keys(form.custom_label_copies || {})) {
    if (!selected.has(id)) delete form.custom_label_copies[id]
  }
}, { deep: true })
function submit(calibration) {
  const effectiveScope = !props.showScope
    ? 'single'
    : scopeChoices.value.some((item) => item.value === form.scope)
    ? form.scope
    : scopeChoices.value[0]?.value || 'imported'
  const payload = { ...form, scope: effectiveScope, calibration }
  payload.excluded_categories = props.showScope && Array.isArray(form.excluded_categories)
    ? form.excluded_categories.filter(Boolean)
    : []
  payload.custom_labels = props.showScope && !calibration
    ? (form.custom_label_ids || []).filter(Boolean).map((id) => ({
      template_id: id,
      copies: Math.max(1, Math.min(40, Number(form.custom_label_copies?.[id] || 1)))
    }))
    : []
  if (effectiveScope === 'imported') {
    const range = Array.isArray(form.imported_range) ? form.imported_range : []
    if (!range[0] || !range[1]) {
      ElMessage.warning('请选择要导出的导入日期范围')
      return
    }
    payload.scope = 'all'
    payload.imported_from = range[0]
    payload.imported_to = range[1]
  } else {
    payload.imported_from = null
    payload.imported_to = null
  }
  emit('export', payload)
}
</script>

<style scoped>
.label-form { margin-top: 16px; }
.label-form span { margin-left: 8px; color: #667085; }
.calibration-note { padding: 10px 12px; border-radius: var(--cw-radius-control); background: #fff7ed; color: #9a3412; line-height: 1.55; }
.append-labels {
  width: 100%;
  display: grid;
  gap: 8px;
  min-width: 0;
}

.append-label-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--cw-border);
  border-radius: var(--cw-radius-control);
  background: #fbfdff;
}

.append-label-row > span {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: #344054;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.append-label-row label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #667085;
  white-space: nowrap;
}

.append-label-row :deep(.el-input-number) {
  width: 116px;
}

.label-form :deep(.el-segmented),
.label-form :deep(.el-input-number),
.label-form :deep(.el-input__wrapper),
.label-form :deep(.el-select__wrapper),
.label-form :deep(.el-date-editor),
.label-form :deep(.el-range-editor),
:deep(.el-dialog),
:deep(.el-button) {
  border-radius: var(--cw-radius-control);
}

.label-form :deep(.el-date-editor) {
  width: 100%;
}

.label-form :deep(.el-select) {
  width: 100%;
}

.label-form :deep(.el-input-number) {
  width: min(220px, 100%);
}

@media (max-width: 620px) {
  .label-form :deep(.el-form-item) {
    display: block;
  }

  .label-form :deep(.el-form-item__label) {
    justify-content: flex-start;
    margin-bottom: 6px;
  }

  .label-form :deep(.el-input-number),
  .label-form :deep(.el-date-editor),
  .label-form :deep(.el-select),
  .label-form :deep(.el-segmented) {
    width: 100%;
  }

  .append-label-row {
    grid-template-columns: 1fr;
  }

  .append-label-row label {
    justify-content: space-between;
  }
}
</style>
