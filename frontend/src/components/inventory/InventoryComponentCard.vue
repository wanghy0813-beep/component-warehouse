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
    <div class="chip-row">
      <span v-for="chip in chips" :key="`${chip.label}-${chip.value}`" class="mini-chip">
        <small>{{ chip.label }}</small>{{ chip.value }}
      </span>
    </div>
    <p class="usage">{{ usage }}</p>
    <div class="meta-row">
      <span v-if="item.location">位置 {{ item.location }}</span>
      <span v-for="tag in tags" :key="tag">{{ tag }}</span>
    </div>
    <div class="actions" @click.stop>
      <slot name="actions" />
    </div>
    <div class="stock-row">
      <span>总量 {{ item.quantity || 0 }}</span>
      <span v-if="item.reserved_quantity" class="reserved-note">预留 {{ item.reserved_quantity }}</span>
      <strong>可用 {{ item.available_quantity || 0 }}</strong>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { componentOneLineUsage, extractComponentChips, packageTagStyle, splitTags } from '../../utils/componentUi'
import { componentDisplaySubtitle, componentDisplayTitle } from '../../shared/componentDisplay'

const props = defineProps({
  item: { type: Object, required: true }
})

defineEmits(['open'])

const primary = computed(() => componentDisplayTitle(props.item))
const secondary = computed(() => componentDisplaySubtitle(props.item, primary.value) || '暂无型号信息')
const chips = computed(() => extractComponentChips(props.item, 4))
const tags = computed(() => splitTags([props.item.tags, props.item.ai_tags].filter(Boolean).join(',' )).slice(0, 4))
const usage = computed(() => componentOneLineUsage(props.item))
const packageStyle = computed(() => packageTagStyle(props.item.package))
const syncLabel = computed(() => {
  if (!props.item.sync_status) return ''
  return props.item.sync_status === 'live' ? '实时库存' : '离队快照'
})
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
.card-top, .tag-row, .card-badges, .meta-row, .actions, .stock-row, .chip-row { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
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
.usage { flex: 1; display: -webkit-box; overflow: hidden; color: #667085; line-height: 1.42; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.mini-chip, .meta-row span { padding: 3px 7px; border: 1px solid #dfe7f2; border-radius: var(--cw-radius-chip); color: #344054; font-size: 12px; }
.mini-chip small { margin-right: 5px; color: #7a8699; }
.meta-row span { background: #f8fafc; }
.actions:empty { display: none; }
.stock-row { padding-top: 7px; border-top: 1px solid #eef2f7; color: #667085; font-size: 13px; }
.stock-row strong { color: #172b4d; }
.reserved-note { color: #98a2b3; }
</style>
