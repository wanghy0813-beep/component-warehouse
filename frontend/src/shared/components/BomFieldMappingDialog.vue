<template>
  <el-dialog :model-value="modelValue" title="确认 BOM 字段映射" width="min(900px, 96vw)" @update:model-value="$emit('update:modelValue', $event)">
    <el-alert type="info" :closable="false" show-icon>
      系统仅按表头精确识别。请修正未识别或识别错误的列；数量列为必填。
    </el-alert>
    <div class="mapping-grid">
      <label v-for="field in fields" :key="field.key">
        <span>{{ field.label }}<em v-if="field.required">*</em></span>
        <el-select v-model="mapping[field.key]" clearable filterable placeholder="不导入">
          <el-option v-for="header in inspection.headers || []" :key="header" :label="header" :value="header" />
        </el-select>
      </label>
    </div>
    <div class="preview">
      <strong>文件预览：{{ fileName || '-' }}，表头位于第 {{ inspection.header_row || '-' }} 行</strong>
      <div class="preview-scroll">
        <table>
          <thead><tr><th v-for="header in inspection.headers || []" :key="header">{{ header }}</th></tr></thead>
          <tbody>
            <tr v-for="(row, index) in inspection.preview || []" :key="index">
              <td v-for="(value, cellIndex) in row" :key="cellIndex">{{ value }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="confirm">按此映射分析</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, watch } from 'vue'
import { ElMessage } from '../elementApi'

const props = defineProps({
  modelValue: Boolean,
  inspection: { type: Object, default: () => ({}) },
  fileName: { type: String, default: '' },
  loading: Boolean
})
const emit = defineEmits(['update:modelValue', 'confirm'])
const fields = [
  { key: 'designator', label: 'Designator / 位号' },
  { key: 'quantity', label: 'Quantity / 数量', required: true },
  { key: 'comment', label: 'Comment / 备注' },
  { key: 'value', label: 'Value / 参数' },
  { key: 'footprint', label: 'Footprint / 封装' },
  { key: 'manufacturer', label: 'Manufacturer / 厂商' },
  { key: 'manufacturer_part', label: 'MPN / 厂商型号' },
  { key: 'supplier', label: 'Supplier / 供应商' },
  { key: 'supplier_part', label: 'LCSC / 供应商料号' },
  { key: 'category', label: 'Category / 分类' },
  { key: 'primary_category', label: 'Primary Category / 主分类' }
]
const mapping = reactive({})
watch(
  () => props.inspection,
  (value) => {
    for (const field of fields) mapping[field.key] = value?.detected_mapping?.[field.key] || ''
  },
  { immediate: true, deep: true }
)
function confirm() {
  if (!mapping.quantity) return ElMessage.warning('必须选择数量列')
  emit('confirm', {
    __header_row: props.inspection.header_row,
    ...Object.fromEntries(Object.entries(mapping).filter(([, value]) => value))
  })
}
</script>

<style scoped>
.mapping-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.mapping-grid label { display: grid; gap: 6px; color: #475467; }.mapping-grid em { color: #dc2626; font-style: normal; }
.preview { display: grid; gap: 8px; margin-top: 18px; }.preview-scroll { max-width: 100%; overflow: auto; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-control); }
table { border-collapse: collapse; min-width: 100%; font-size: 12px; }th, td { padding: 7px 9px; border-right: 1px solid #e4eaf2; border-bottom: 1px solid #e4eaf2; white-space: nowrap; text-align: left; }th { background: #f8fafc; }
@media (max-width: 680px) { .mapping-grid { grid-template-columns: 1fr; } }
</style>
