<template>
  <article class="inventory-card" @click="$emit('open')">
    <div class="card-top">
      <div class="tag-row">
        <el-tag effect="plain" :style="{ background: item.category?.color || '#eef2f7' }">{{ item.category?.name || '未分类' }}</el-tag>
        <el-tag v-if="item.package" effect="plain" :style="packageStyle">{{ item.package }}</el-tag>
        <el-tag v-if="item.warehouse_code" effect="plain" type="info">{{ item.warehouse_code }}</el-tag>
      </div>
      <div class="card-badges">
        <slot name="badges" />
        <el-tag v-if="item.low_stock_warning" size="small" type="danger">低库存</el-tag>
        <el-tag v-if="syncLabel" size="small" :type="item.sync_status === 'live' ? 'success' : 'warning'">{{ syncLabel }}</el-tag>
      </div>
    </div>
    <h3>{{ primary }}</h3>
    <p class="model-line">{{ secondary }}</p>
    <p v-if="item.search_unit_conversion" class="conversion-note">
      <span>等值换算</span>
      {{ item.search_unit_conversion.label }}
    </p>
    <div class="chip-row">
      <span v-for="chip in chips" :key="`${chip.label}-${chip.value}`" class="mini-chip">
        <small>{{ chip.label }}</small>{{ chip.value }}
      </span>
    </div>
    <p class="usage">{{ usage }}</p>
    <div class="meta-row">
      <span v-if="location">位置 {{ location }}</span>
      <span v-for="tag in tags" :key="tag">{{ tag }}</span>
    </div>
    <div class="actions" @click.stop>
      <slot name="actions" />
    </div>
    <p v-if="averagePriceLabel" class="average-price">均价 {{ averagePriceLabel }}/件</p>
    <div class="stock-row">
      <div class="stock-summary">
        <span>{{ quantityCopy.totalLabel }} {{ item.quantity || 0 }}</span>
        <span v-if="item.reserved_quantity && !durable" class="reserved-note">预留 {{ item.reserved_quantity }}</span>
        <span v-if="durable && item.occupied_quantity" class="occupied-note">占用 {{ item.occupied_quantity }}</span>
        <strong>{{ quantityCopy.availableLabel }} {{ item.available_quantity || 0 }}</strong>
      </div>
      <div class="stock-action" @click.stop><slot name="stock-action" /></div>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { componentOneLineUsage, extractComponentChips, packageTagStyle, splitTags } from '../../utils/componentUi'
import { componentDisplaySubtitle, componentDisplayTitle } from '../../shared/componentDisplay'
import { inventoryQuantityCopy, isDurableEquipment, visibleInventoryLocation } from '../../shared/componentInventorySemantics'

const props = defineProps({
  item: { type: Object, required: true }
})

defineEmits(['open'])

const primary = computed(() => componentDisplayTitle(props.item))
const secondary = computed(() => componentDisplaySubtitle(props.item, primary.value) || '暂无型号信息')
const chips = computed(() => Array.isArray(props.item.card_chips) ? props.item.card_chips.slice(0, 4) : extractComponentChips(props.item, 4))
const tags = computed(() => splitTags([props.item.tags, props.item.ai_tags].filter(Boolean).join(',' )).slice(0, 4))
const usage = computed(() => props.item.card_usage || componentOneLineUsage(props.item))
const packageStyle = computed(() => packageTagStyle(props.item.package))
const syncLabel = computed(() => {
  if (!props.item.sync_status) return ''
  return props.item.sync_status === 'live' ? '实时库存' : '离队快照'
})
const averagePriceLabel = computed(() => {
  if (props.item.average_unit_price === null || props.item.average_unit_price === undefined || props.item.average_unit_price === '') return ''
  const value = Number(props.item.average_unit_price)
  if (!Number.isFinite(value)) return ''
  return `¥${new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value)}`
})
const durable = computed(() => isDurableEquipment(props.item))
const location = computed(() => visibleInventoryLocation(props.item.location))
const quantityCopy = computed(() => inventoryQuantityCopy(props.item))
</script>

<style scoped>
.inventory-card {
  min-height: 218px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 11px;
  border: 1px solid #e3e9f1;
  border-radius: var(--cw-radius-card);
  background: #fff;
  cursor: pointer;
  transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease;
}
.inventory-card:hover { transform: translateY(-2px); border-color: #b9c9ef; box-shadow: 0 12px 30px rgba(40, 65, 100, .08); }
.card-top, .tag-row, .card-badges, .meta-row, .actions, .stock-row, .stock-summary, .chip-row { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.actions { gap: 8px; }
.actions :deep(.el-button) {
  min-height: var(--cw-control-height-small);
  margin-left: 0;
  padding-inline: 12px;
  border-radius: var(--cw-radius-control);
  box-shadow: none;
}
.card-top, .stock-row { justify-content: space-between; }
h3 { margin: 0; color: #14213d; font-size: 18px; line-height: 1.18; overflow-wrap: anywhere; }
p { margin: 0; }
.model-line { min-height: 20px; color: #5d6b7e; font-weight: 600; }
.conversion-note {
  display: flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  padding: 4px 8px;
  border: 1px solid #b7e4d1;
  border-radius: var(--cw-radius-chip);
  background: #ecfdf5;
  color: #067647;
  font-size: 12px;
  font-weight: 700;
}
.conversion-note span { color: #475467; font-weight: 600; }
.usage { flex: 1; display: -webkit-box; overflow: hidden; color: #667085; line-height: 1.42; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.mini-chip, .meta-row span { padding: 3px 7px; border: 1px solid #dfe7f2; border-radius: var(--cw-radius-chip); color: #344054; font-size: 12px; }
.mini-chip small { margin-right: 5px; color: #7a8699; }
.meta-row span { background: #f8fafc; }
.actions:empty { display: none; }
.average-price { align-self: flex-end; color: #98a2b3; font-size: 12px; line-height: 1.2; }
.stock-row { padding-top: 7px; border-top: 1px solid #eef2f7; color: #667085; font-size: 13px; }
.stock-summary { gap: 9px; }
.stock-row strong { color: #172b4d; }
.stock-action:empty { display: none; }
.stock-action { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
.stock-action :deep(.el-button) { min-height: 32px; margin: 0; border-radius: var(--cw-radius-control); font-weight: 700; }
.reserved-note { color: #98a2b3; }
.occupied-note { color: #d97706; font-weight: 700; }
</style>
