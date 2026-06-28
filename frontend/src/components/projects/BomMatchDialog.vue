<template>
  <el-dialog v-model="dialogVisible" title="BOM AI 库存分拣" width="min(1180px, 96vw)" append-to-body align-center destroy-on-close class="bom-match-dialog">
    <div class="match-summary-grid">
      <div class="match-summary-card"><span>总行数</span><strong>{{ bomMatchStats.total }}</strong></div>
      <div class="match-summary-card tone-green"><span>库内已匹配</span><strong>{{ bomMatchStats.matched }}</strong></div>
      <div class="match-summary-card tone-amber"><span>需确认</span><strong>{{ bomMatchStats.review }}</strong></div>
      <div class="match-summary-card tone-red"><span>待采购</span><strong>{{ bomMatchStats.missing }}</strong></div>
      <div class="match-summary-card tone-blue"><span>待确认导入</span><strong>{{ pendingSelectedCount }}</strong></div>
    </div>
    <div class="dialog-progress">
      <div class="segmented-progress">
        <span class="segment matched" :style="{ width: `${bomMatchStats.matchedPercent}%` }"></span>
        <span class="segment review" :style="{ width: `${bomMatchStats.reviewPercent}%` }"></span>
        <span class="segment missing" :style="{ width: `${bomMatchStats.missingPercent}%` }"></span>
      </div>
      <span>{{ bomMatchStats.rate }}% 可直接使用库存</span>
    </div>
    <el-alert v-if="bomMatchRows.some((row) => row.ai_error)" type="warning" show-icon :closable="false" class="bom-match-alert">
      部分行 AI 辅助失败，已保留库存预匹配结果；可以继续手动确认或导入已选择项。
    </el-alert>
    <el-tabs v-model="activeTab" class="bom-match-tabs">
      <el-tab-pane :label="`库内已匹配 ${bomMatchBuckets.matched.length}`" name="matched" />
      <el-tab-pane :label="`需确认 ${bomMatchBuckets.review.length}`" name="review" />
      <el-tab-pane :label="`待采购 ${bomMatchBuckets.missing.length}`" name="missing" />
    </el-tabs>
    <el-table :data="activeBomMatchRows" row-key="id" max-height="520" empty-text="当前分栏没有 BOM 行" class="bom-match-table">
      <el-table-column prop="designator" label="位号" min-width="120" />
      <el-table-column prop="required_quantity" label="数量" width="80" />
      <el-table-column label="BOM 指定" min-width="240">
        <template #default="{ row }">
          <strong class="bom-primary-model">{{ bomPrimaryDisplay(row) }}</strong>
          <div class="muted compact-meta">
            <span v-for="(part, idx) in bomSecondaryDisplay(row)" :key="idx">{{ part }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="AI 判断 / 采购建议" min-width="280">
        <template #default="{ row }">
          <div class="match-role">{{ row.role }}</div>
          <el-tag size="small" :type="matchStatusType(row.status)">{{ matchStatusLabel(row.status) }}</el-tag>
          <el-tag v-if="row.auto_imported" size="small" type="success" effect="plain">已自动导入</el-tag>
          <el-tag v-if="row.ai_confidence" size="small" effect="plain">{{ row.ai_confidence }}</el-tag>
          <div v-if="row.matches?.[0]?.flags?.length" class="match-flags">
            <el-tag v-for="flag in row.matches[0].flags" :key="flag" size="small" effect="plain" :type="flag.includes('不一致') ? 'danger' : 'success'">{{ flag }}</el-tag>
          </div>
          <div v-if="row.ai_reason" class="match-reason">{{ row.ai_reason }}</div>
          <div v-if="row.auto_import_note" class="match-reason">{{ row.auto_import_note }}</div>
          <div v-if="row.ai_error" class="match-error">{{ row.ai_error }}</div>
          <div v-if="row.missing_suggestion?.alternatives?.length" class="match-alternatives">
            <span v-for="item in row.missing_suggestion.alternatives" :key="item.description">{{ item.description }}</span>
          </div>
          <div class="match-row-actions">
            <el-button v-if="row.missing_suggestion?.lcsc_search_url" size="small" text @click="openUrl(row.missing_suggestion.lcsc_search_url)">缺料搜索</el-button>
            <el-button v-if="canCreatePendingComponent(row)" size="small" text type="primary" @click="createPendingPurchase(row)">加入待采购库</el-button>
            <el-button v-if="canIgnoreBomRow(row)" size="small" text type="warning" @click="ignoreImportRow(row)">忽略此项</el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="匹配" min-width="320">
        <template #default="{ row }">
          <el-select
            v-model="row.selected_component_id"
            clearable
            filterable
            remote
            reserve-keyword
            style="width: 100%"
            placeholder="搜索库存或选择推荐"
            :loading="bomMatchOptionLoading[rowKey(row)]"
            :remote-method="(keyword) => searchBomMatchComponents(row, keyword)"
            @visible-change="(visible) => visible && ensureBomMatchOptions(row)"
            @change="(value) => handleBomRowSelection(row, value)"
          >
            <el-option v-for="match in matchSelectOptions(row)" :key="match.component.id" :value="match.component.id" :label="matchOptionLabel(match)" />
          </el-select>
          <div v-if="row.matches?.length" class="match-candidates">
            <span v-for="match in row.matches.slice(0, 3)" :key="match.component.id">{{ match.score }}% · {{ match.reason }}</span>
          </div>
          <div v-else class="missing-text">{{ row.missing_suggestion?.description || '暂无库存候选' }}</div>
          <div class="match-row-actions">
            <el-button size="small" text @click="openStockPicker(row)">更多库存</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button :disabled="!purchaseKeywords.length" :icon="CopyDocument" @click="copyPurchaseKeywords">复制采购关键词</el-button>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="importingMatchedBom" @click="confirmImportMatches">导入待确认项 {{ pendingSelectedCount }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { CopyDocument } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: Boolean,
  bomMatchRows: { type: Array, default: () => [] },
  bomMatchStats: { type: Object, required: true },
  bomMatchBuckets: { type: Object, required: true },
  activeBomMatchRows: { type: Array, default: () => [] },
  bomMatchTab: { type: String, default: 'matched' },
  pendingSelectedCount: { type: Number, default: 0 },
  purchaseKeywords: { type: Array, default: () => [] },
  importingMatchedBom: Boolean,
  bomMatchOptionLoading: { type: Object, default: () => ({}) },
  bomPrimaryDisplay: { type: Function, required: true },
  bomSecondaryDisplay: { type: Function, required: true },
  matchStatusType: { type: Function, required: true },
  matchStatusLabel: { type: Function, required: true },
  openUrl: { type: Function, required: true },
  canCreatePendingComponent: { type: Function, required: true },
  createPendingPurchase: { type: Function, required: true },
  canIgnoreBomRow: { type: Function, required: true },
  ignoreImportRow: { type: Function, required: true },
  rowKey: { type: Function, required: true },
  searchBomMatchComponents: { type: Function, required: true },
  ensureBomMatchOptions: { type: Function, required: true },
  handleBomRowSelection: { type: Function, required: true },
  matchSelectOptions: { type: Function, required: true },
  matchOptionLabel: { type: Function, required: true },
  openStockPicker: { type: Function, required: true },
  copyPurchaseKeywords: { type: Function, required: true },
  confirmImportMatches: { type: Function, required: true },
})

const emit = defineEmits(['update:modelValue', 'update:bomMatchTab'])

const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const activeTab = computed({
  get: () => props.bomMatchTab,
  set: (value) => emit('update:bomMatchTab', value),
})
</script>
