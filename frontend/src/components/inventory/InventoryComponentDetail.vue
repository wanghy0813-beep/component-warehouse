<template>
  <div class="inventory-detail">
    <section class="summary-card">
      <div class="tag-row">
        <el-tag effect="plain" :style="{ background: item.category?.color || '#eef2f7' }">{{ item.category?.name || '未分类' }}</el-tag>
        <el-tag v-if="item.package" effect="plain" :style="packageStyle">封装 {{ item.package }}</el-tag>
        <el-tag v-if="item.warehouse_code" effect="plain" type="info">{{ item.warehouse_code }}</el-tag>
        <el-tag v-if="item.sync_status" :type="item.sync_status === 'live' ? 'success' : 'warning'">
          {{ item.sync_status === 'live' ? '个人版实时同步' : '成员离队冻结快照' }}
        </el-tag>
      </div>
      <h2>{{ title }}</h2>
      <p class="subtitle">{{ subtitle }}</p>
      <p>{{ item.description || item.ai_summary || item.parameters || '暂无摘要' }}</p>
      <p v-if="item.manufacturer" class="manufacturer">厂商：{{ item.manufacturer }}</p>
      <div v-if="chips.length" class="spec-grid">
        <span v-for="chip in chips" :key="`${chip.label}-${chip.value}`">
          <small>{{ chip.label }}</small><strong>{{ chip.value }}</strong>
        </span>
      </div>
      <div v-if="unitHints.length" class="unit-hints">
        <strong>常用换算</strong><span v-for="hint in unitHints" :key="hint">{{ hint }}</span>
      </div>
      <div class="stock-tags">
        <el-tag>总量 {{ item.quantity || 0 }}</el-tag>
        <el-tag type="success">可用 {{ item.available_quantity || 0 }}</el-tag>
        <el-tag v-if="item.reserved_quantity" type="info" effect="plain">项目预留 {{ item.reserved_quantity }}</el-tag>
        <el-tag v-if="item.location" effect="plain">团队位置 {{ item.location }}</el-tag>
      </div>
      <slot name="actions" />
    </section>

    <section class="stock-lot-card">
      <div class="section-head">
        <h3>库存批次 / 采购渠道</h3>
        <el-button size="small" text :loading="lotsLoading" @click="$emit('load-lots')">刷新</el-button>
      </div>
      <div class="lot-create-row">
        <el-select v-model="lotForm.source_type" size="small" placeholder="渠道">
          <el-option v-for="option in lotSourceOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <el-input v-model="lotForm.source_reference" size="small" placeholder="订单号/链接/备注" />
        <el-input v-model="lotForm.location" size="small" placeholder="位置" />
        <el-input-number v-model="lotForm.quantity" size="small" :min="1" />
        <el-input-number v-model="lotForm.unit_cost" size="small" :min="0" :precision="4" placeholder="单价" />
        <el-button size="small" type="primary" :loading="lotSaving" :disabled="!canEditInventoryLots" @click="submitLot">新增批次</el-button>
      </div>
      <div v-loading="lotsLoading" class="lot-list">
        <article v-for="lot in inventoryLots" :key="lot.id" class="lot-row">
          <div>
            <strong>{{ sourceLabel(lot.source_type) }}</strong>
            <span v-if="lot.source_reference">{{ lot.source_reference }}</span>
            <small>{{ lot.location || '未填写位置' }} · {{ formatTime(lot.received_at || lot.created_at) }}</small>
          </div>
          <div class="lot-quantity">
            <span>剩余 {{ lot.remaining_quantity }}</span>
            <small>原始 {{ lot.initial_quantity }}<template v-if="lot.unit_cost !== null && lot.unit_cost !== undefined"> · ¥{{ lot.unit_cost }}</template></small>
          </div>
          <div class="lot-actions">
            <el-button
              size="small"
              :loading="lotConsumeIds.has(lot.id)"
              :disabled="!lot.remaining_quantity || !canEditInventoryLots || lotConsumeIds.has(lot.id)"
              @click="$emit('consume-lot', lot)"
            >扣 1</el-button>
            <el-button
              v-if="lot.can_delete"
              size="small"
              type="danger"
              text
              :loading="lotSaving"
              :disabled="!canEditInventoryLots"
              @click="$emit('delete-lot', lot)"
            >删除</el-button>
          </div>
        </article>
        <el-empty v-if="!inventoryLots.length && !lotsLoading" description="暂无批次记录，旧库存会自动保留为 legacy 批次" :image-size="48" />
      </div>
    </section>

    <details v-if="engineeringEnabled" class="engineering-card">
      <summary class="section-head">
        <h3>高级：供应商 / AD 工程资料</h3>
        <span>{{ edaLoading ? '加载中…' : `${supplierParts.length} 个料号 · ${edaBindings.length} 个绑定` }}</span>
      </summary>
      <div v-if="supplierParts.length" class="supplier-list">
        <span v-for="part in supplierParts" :key="part.id"><strong>{{ part.supplier }}</strong>{{ part.supplier_part_number }}<em v-if="part.is_preferred">首选</em></span>
      </div>
      <p v-else class="soft-empty">暂无供应商料号</p>
      <div v-if="edaBindings.length" class="binding-list">
        <article v-for="binding in edaBindings" :key="binding.id">
          <div><el-tag :type="verificationType(binding.verification_status)">{{ binding.verification_status }}</el-tag><strong>{{ binding.symbol?.name || '缺少 Symbol' }}</strong></div>
          <p>{{ binding.footprint?.name || '缺少 Footprint' }}</p>
          <small>{{ binding.datasheet?.original_name || '缺少数据手册' }} · {{ binding.model?.original_name || '缺少 3D 模型' }}</small>
        </article>
      </div>
      <p v-else class="soft-empty">尚未绑定 AD Symbol / Footprint</p>
    </details>

    <section class="knowledge-card">
      <h3>AI 知识与工程信息</h3>
      <p v-if="usage.usage">{{ usage.usage }}</p>
      <div class="knowledge-grid">
        <article v-for="section in knowledgeSections" :key="section.title" v-show="section.items.length">
          <strong>{{ section.title }}</strong>
          <ul><li v-for="value in section.items" :key="value">{{ value }}</li></ul>
        </article>
      </div>
    </section>

    <section class="ai-ask-card">
      <div class="section-head"><h3>问这个元器件</h3><span>AI 只按当前资料回答</span></div>
      <el-input v-model="aiQuestion" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="例如：这个芯片能不能替代另一个型号？封装和外围要注意什么？" />
      <div class="ask-actions">
        <el-button type="primary" :loading="aiAskLoading" :disabled="!aiQuestion.trim()" @click="submitAiQuestion">提问</el-button>
        <el-button text @click="aiQuestion = ''">清空</el-button>
      </div>
      <article v-if="aiAnswer?.answer" class="ai-answer">
        <strong>回答</strong>
        <p>{{ aiAnswer.answer }}</p>
        <div class="tag-row">
          <el-tag effect="plain">置信度 {{ confidenceLabel(aiAnswer.confidence) }}</el-tag>
          <el-tag v-if="aiAnswer.needs_datasheet_check" type="warning" effect="plain">需查数据手册</el-tag>
        </div>
        <div v-if="aiAnswer.evidence?.length" class="answer-list"><small>依据</small><span v-for="item in aiAnswer.evidence" :key="item">{{ item }}</span></div>
        <div v-if="aiAnswer.risks?.length" class="answer-list warning"><small>风险</small><span v-for="item in aiAnswer.risks" :key="item">{{ item }}</span></div>
      </article>
    </section>

    <section v-if="showUsage" class="usage-card">
      <button class="section-head usage-toggle" type="button" @click="toggleUsage">
        <h3>使用记录</h3>
        <span>{{ usageExpanded ? '收起' : `展开${usageRecords.length ? ` · ${usageRecords.length} 条` : ''}` }}</span>
      </button>
      <div v-show="usageExpanded" v-loading="usageLoading" class="usage-content">
      <el-timeline v-if="usageRecords.length">
        <el-timeline-item v-for="record in usageRecords" :key="record.id" :timestamp="formatTime(record.created_at)" placement="top">
          <strong>{{ record.action_label }} {{ quantityText(record.quantity_delta) }}</strong>
          <p>{{ record.project_name || '未关联项目' }}<span v-if="record.project_code"> · {{ record.project_code }}</span></p>
          <p v-if="record.designators?.length">位号：{{ record.designators.join('、') }}</p>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无焊接、报损或返还记录" :image-size="64" />
      <el-button v-if="usageRecords.length >= 20" text type="primary" @click="$emit('load-usage', usageRecords.length + 20)">继续加载</el-button>
      </div>
    </section>

    <slot />
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { componentUnitHints, extractComponentChips, packageTagStyle, parseJsonValue } from '../../utils/componentUi'
import { componentDisplaySubtitle, componentDisplayTitle } from '../../shared/componentDisplay'

const props = defineProps({
  item: { type: Object, required: true },
  usageRecords: { type: Array, default: () => [] },
  edaBindings: { type: Array, default: () => [] },
  supplierParts: { type: Array, default: () => [] },
  inventoryLots: { type: Array, default: () => [] },
  edaLoading: Boolean,
  lotsLoading: Boolean,
  lotSaving: Boolean,
  lotConsumeIds: { type: Set, default: () => new Set() },
  canEditInventoryLots: { type: Boolean, default: true },
  aiAskLoading: Boolean,
  aiAnswer: { type: Object, default: null },
  showUsage: { type: Boolean, default: true },
  usageLoading: Boolean,
  engineeringEnabled: { type: Boolean, default: true }
})
const emit = defineEmits(['load-usage', 'load-lots', 'add-lot', 'consume-lot', 'delete-lot', 'ask-ai'])
const usageExpanded = ref(false)
const aiQuestion = ref('')
const lotForm = reactive({ source_type: 'manual', source_reference: '', location: '', quantity: 1, unit_cost: null, note: '' })
const lotSourceOptions = [
  { label: '手动', value: 'manual' },
  { label: '立创', value: 'lcsc' },
  { label: '淘宝', value: 'taobao' },
  { label: '外部订单', value: 'external_order' },
  { label: '采购到货', value: 'purchase' },
  { label: '旧库存', value: 'legacy' }
]

const title = computed(() => componentDisplayTitle(props.item))
const subtitle = computed(() => componentDisplaySubtitle(props.item, title.value))
const chips = computed(() => extractComponentChips(props.item, 10))
const unitHints = computed(() => componentUnitHints(props.item))
const packageStyle = computed(() => packageTagStyle(props.item.package))
const usage = computed(() => {
  const parsed = parseJsonValue(props.item.ai_usage)
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : { usage: typeof parsed === 'string' ? parsed : '' }
})
const list = (value) => {
  const parsed = parseJsonValue(value)
  if (Array.isArray(parsed)) return parsed.map((item) => typeof item === 'string' ? item : item?.value || item?.name).filter(Boolean)
  if (parsed && typeof parsed === 'object') return Object.values(parsed).flatMap((item) => list(item))
  return parsed ? [String(parsed)] : []
}
const knowledgeSections = computed(() => [
  { title: '适合用途', items: list(usage.value.typical_applications) },
  { title: '设计洞察', items: list(usage.value.design_insights) },
  { title: '不适合场景', items: list(usage.value.do_not_use_for) },
  { title: '手册核对项', items: list(usage.value.datasheet_notes) },
  { title: '推荐搭配', items: list(usage.value.recommended_pairings) },
  { title: '风险提示', items: list(props.item.ai_risk_notes) },
  { title: 'PCB 注意', items: list(props.item.ai_pcb_notes) },
  { title: '替代料检查', items: list(props.item.ai_substitutes) }
])
const verificationType = (status) => ({ verified: 'success', tested: 'success', checked: 'primary', raw: 'warning', deprecated: 'danger' })[status] || 'info'
const sourceLabel = (value) => ({
  manual: '手动',
  lcsc: '立创',
  taobao: '淘宝',
  external_order: '外部',
  purchase: '采购',
  purchase_receipt: '采购',
  legacy: '旧库存',
  manual_lot_create: '手动批次',
  manual_restock: '手动入库',
  component_create: '初始库存',
  team_lot_create: '团队批次'
})[value] || value || '未知渠道'
const confidenceLabel = (value) => ({ high: '高', medium: '中', low: '低' })[value] || value || '中'

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}
function quantityText(value) {
  const number = Number(value || 0)
  return number ? `(${number > 0 ? '+' : ''}${number})` : ''
}
function toggleUsage() {
  usageExpanded.value = !usageExpanded.value
  if (usageExpanded.value && !props.usageRecords.length) emit('load-usage', 20)
}

function submitLot() {
  emit('add-lot', { ...lotForm })
  Object.assign(lotForm, { source_type: 'manual', source_reference: '', location: '', quantity: 1, unit_cost: null, note: '' })
}

function submitAiQuestion() {
  const question = aiQuestion.value.trim()
  if (!question) return
  emit('ask-ai', question)
}
</script>

<style scoped>
.inventory-detail { min-width: 0; display: grid; gap: 14px; }
.summary-card, .knowledge-card, .usage-card, .engineering-card, .stock-lot-card, .ai-ask-card { padding: 18px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-card); background: #fff; }
.tag-row, .stock-tags, .unit-hints { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
h2 { margin: 14px 0 6px; color: #101828; font-size: clamp(24px, 4vw, 32px); overflow-wrap: anywhere; }
h3 { margin: 0 0 12px; color: #243b53; }
p { color: #475467; line-height: 1.65; overflow-wrap: anywhere; }
.subtitle { margin: 0 0 8px; color: #667085; font-weight: 650; }
.manufacturer { color: #344054; font-weight: 650; }
.spec-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 9px; margin: 16px 0; }
.spec-grid span { display: grid; gap: 5px; padding: 11px; border: 1px solid #dde6f2; border-radius: var(--cw-radius-control); background: #fbfdff; }
.spec-grid small { color: #667085; }.spec-grid strong { color: #172b4d; overflow-wrap: anywhere; }
.unit-hints { margin: 12px 0; padding: 10px; border-radius: var(--cw-radius-control); background: #eefaff; color: #075985; }
.unit-hints span { padding: 4px 9px; border-radius: 999px; background: #fff; }
.stock-tags { margin-top: 14px; }
.lot-create-row { min-width: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); gap: 8px; align-items: center; margin-bottom: 12px; }
.lot-create-row .el-button { width: 100%; }
.lot-list { display: grid; gap: 8px; }
.lot-row { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(76px, auto) auto; gap: 10px; align-items: center; padding: 10px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-control); background: #fbfdff; }
.lot-row div { min-width: 0; display: grid; gap: 3px; }
.lot-row span, .lot-row small { min-width: 0; color: #667085; overflow-wrap: anywhere; }
.lot-row strong { color: #172b4d; }
.lot-quantity { text-align: right; }
.lot-actions { display: flex !important; grid-auto-flow: column; gap: 4px !important; justify-content: end; }
.knowledge-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
.knowledge-grid article { padding: 13px; border-radius: var(--cw-radius-control); background: linear-gradient(145deg, #f5f9ff, #fff); border: 1px solid #e0e8f5; }
.knowledge-grid ul { margin: 8px 0 0; padding-left: 18px; color: #475467; line-height: 1.55; }
.ask-actions { display: flex; gap: 8px; margin-top: 10px; }
.ai-answer { margin-top: 12px; padding: 12px; border: 1px solid #dbeafe; border-radius: var(--cw-radius-control); background: #f8fbff; }
.ai-answer p { margin: 6px 0 10px; }
.answer-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.answer-list small { width: 100%; color: #667085; }
.answer-list span { padding: 4px 8px; border-radius: var(--cw-radius-chip); background: #fff; border: 1px solid #dbeafe; color: #344054; }
.answer-list.warning span { border-color: #fed7aa; background: #fff7ed; color: #9a3412; }
.section-head { display: flex; justify-content: space-between; color: #667085; }
.section-head h3 { margin: 0; }
details.engineering-card > summary {
  cursor: pointer;
  list-style: none;
}
details.engineering-card > summary::-webkit-details-marker {
  display: none;
}
details.engineering-card > summary::after {
  content: "展开";
  margin-left: 10px;
  color: #2563eb;
  font-size: 13px;
}
details.engineering-card[open] > summary {
  margin-bottom: 12px;
}
details.engineering-card[open] > summary::after {
  content: "收起";
}
.soft-empty {
  margin: 10px 0 0;
  color: #98a2b3;
  font-size: 13px;
}
.usage-card p { margin: 4px 0 0; }
.usage-toggle { width: 100%; padding: 0; border: 0; background: transparent; cursor: pointer; text-align: left; }
.usage-content { max-height: 360px; overflow: auto; margin-top: 14px; padding-right: 6px; }
.supplier-list { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }.supplier-list span { display: flex; gap: 6px; align-items: center; padding: 7px 10px; border-radius: var(--cw-radius-control); background: #f8fafc; color: #475467; }.supplier-list em { color: #c2410c; font-style: normal; font-size: 11px; }
.binding-list { display: grid; gap: 9px; }.binding-list article { padding: 12px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-control); }.binding-list article div { display: flex; gap: 8px; align-items: center; }.binding-list p { margin: 7px 0 3px; }.binding-list small { color: #667085; }
@media (max-width: 720px) {
  .lot-create-row, .lot-row { grid-template-columns: 1fr; }
  .lot-quantity { text-align: left; }
}
</style>
