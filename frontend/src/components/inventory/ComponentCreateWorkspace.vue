<template>
  <div class="create-workspace">
    <header class="create-intro-card">
      <div>
        <span class="create-eyebrow">统一录入工作台</span>
        <h2>选择最顺手的录入方式</h2>
        <p>一次只展开当前任务；自动识别只生成草稿，最终保存前仍可统一核对。</p>
      </div>
      <div class="create-progress" aria-label="新增元器件步骤">
        <span class="is-done"><b>1</b>选择方式</span>
        <i></i>
        <span :class="{ 'is-done': activeMethod !== 'batch' || batchStarted }"><b>2</b>{{ activeMethod === 'batch' ? '上传并预览' : '生成草稿' }}</span>
        <i></i>
        <span :class="{ 'is-done': draftReady && activeMethod !== 'batch' }"><b>3</b>确认入库</span>
      </div>
    </header>

    <section class="create-section method-section">
      <div class="section-heading">
        <div>
          <span class="section-step">01</span>
          <div>
            <h3>录入方式</h3>
            <p>可随时切换，已填写的草稿不会丢失。</p>
          </div>
        </div>
        <el-tag effect="plain">{{ activeMethodMeta.short }}</el-tag>
      </div>
      <div class="method-card-grid">
        <button
          v-for="method in methods"
          :key="method.value"
          type="button"
          class="method-card"
          :class="[`tone-${method.tone}`, { 'is-active': activeMethod === method.value }]"
          :aria-pressed="activeMethod === method.value"
          @click="selectMethod(method.value)"
        >
          <span class="method-icon">{{ method.icon }}</span>
          <span class="method-copy">
            <strong>{{ method.label }}</strong>
            <small>{{ method.description }}</small>
          </span>
          <span v-if="method.recommended" class="method-badge">推荐</span>
          <span class="method-check">{{ activeMethod === method.value ? '✓' : '›' }}</span>
        </button>
      </div>
    </section>

    <section v-if="activeMethod === 'batch'" class="create-section batch-section">
      <div class="section-heading">
        <div>
          <span class="section-step">02</span>
          <div>
            <h3>选择批量来源</h3>
            <p>文件先进入预览，不会直接写入库存。</p>
          </div>
        </div>
      </div>
      <div class="batch-card-grid">
        <article class="batch-source-card tone-green">
          <span class="batch-type">XLSX</span>
          <div>
            <strong>立创订单</strong>
            <p>按立创编号判断新增、合并与跳过，适合订单到货后批量入库。</p>
          </div>
          <el-upload :show-file-list="false" accept=".xlsx,.xls" :http-request="uploadLcscOrder">
            <el-button type="primary" :loading="importing">选择立创订单</el-button>
          </el-upload>
        </article>

        <article class="batch-source-card tone-purple">
          <span class="batch-type">IMG</span>
          <div>
            <strong>购物平台截图</strong>
            <p>识别淘宝、京东等订单或商品截图，逐项确认后新增或合并。</p>
          </div>
          <el-upload :show-file-list="false" accept=".jpg,.jpeg,.png,.webp" :http-request="uploadImage">
            <el-button type="primary" plain :loading="importingImages">选择购物截图</el-button>
          </el-upload>
        </article>

        <article class="batch-source-card tone-blue">
          <span class="batch-type">AI</span>
          <div>
            <strong>其他平台订单</strong>
            <p>AI 整理淘宝等平台导出的 Excel，适合表头和商品描述不统一的订单。</p>
          </div>
          <div class="batch-actions">
            <el-upload :show-file-list="false" accept=".xlsx,.xls" :disabled="externalParsing" :http-request="uploadExternalOrder">
              <el-button type="primary" plain :loading="externalParsing" :disabled="externalParsing">选择订单表格</el-button>
            </el-upload>
            <el-button text @click="downloadTemplate">下载样表</el-button>
          </div>
        </article>
      </div>
      <el-alert type="info" :closable="false" show-icon title="导入完成前请核对型号、数量和自动合并目标；低置信度截图项建议改为跳过后手动录入。" />
    </section>

    <el-form v-else label-position="top" :model="form" class="create-form">
      <section class="create-section method-workspace-section">
        <div class="section-heading">
          <div>
            <span class="section-step">02</span>
            <div>
              <h3>{{ activeMethodMeta.workspaceTitle }}</h3>
              <p>{{ activeMethodMeta.workspaceDescription }}</p>
            </div>
          </div>
        </div>

        <lcsc-paste-import
          v-if="activeMethod === 'lcsc'"
          ref="lcscImporter"
          :lookup="lookup"
          @draft="forwardLcscDraft"
          @existing="$emit('lcsc-existing', $event)"
        />

        <div v-else-if="activeMethod === 'ai'" class="ai-create-panel">
          <el-input
            :model-value="quickPrompt"
            type="textarea"
            :rows="3"
            maxlength="300"
            show-word-limit
            placeholder="例如：AMS1117-3.3 SOT-223 10个；或 0805 10k 1% 电阻"
            @update:model-value="$emit('update:quickPrompt', $event)"
          />
          <div class="panel-actions">
            <el-button type="primary" :loading="aiLoading" @click="$emit('ai-complete')">AI 生成草稿</el-button>
            <span v-if="aiSuggestion">置信度：{{ confidenceLabel(aiSuggestion.confidence) }}</span>
            <span v-else>AI 不会直接保存，可在下方修改。</span>
          </div>
          <div v-if="aiSuggestion" class="ai-result-strip">
            <strong>草稿已更新</strong>
            <span>{{ aiSuggestion.summary || '请继续核对关键字段。' }}</span>
            <el-tag v-if="aiSuggestion.need_datasheet_check" type="warning" effect="plain">需核对手册</el-tag>
          </div>
        </div>

        <div v-else class="manual-create-panel">
          <span class="manual-mark">✎</span>
          <div>
            <strong>从基础信息开始</strong>
            <p>名称或型号至少填写一项；不确定的资料可以稍后补充。</p>
          </div>
          <el-button plain @click="focusNameField">定位到名称</el-button>
        </div>
      </section>

      <section class="create-section draft-section">
        <div class="section-heading">
          <div>
            <span class="section-step">03</span>
            <div>
              <h3>确认入库草稿</h3>
              <p>先核对核心字段，扩展资料按需展开。</p>
            </div>
          </div>
          <span class="draft-completeness">已填写 {{ completedCoreFields }}/6 项核心信息</span>
        </div>

        <div class="draft-card core-draft-card">
          <div class="draft-card-title">
            <div>
              <strong>器件信息</strong>
              <span>名称、型号、分类与封装</span>
            </div>
            <el-tag v-if="draftReady" type="success" effect="plain">可保存</el-tag>
            <el-tag v-else type="warning" effect="plain">待完善</el-tag>
          </div>
          <p class="required-hint"><span>*</span> 名称或型号至少填写一项；库存允许从 0 开始。</p>
          <div class="field-grid">
            <el-form-item label="名称" required class="field-name">
              <el-input ref="nameInput" v-model="form.name" placeholder="例如 10kΩ 电阻 / AMS1117-3.3" />
            </el-form-item>
            <el-form-item label="型号"><el-input v-model="form.model" placeholder="厂商型号 MPN，可空" /></el-form-item>
            <el-form-item label="分类">
              <el-select v-model="form.category_id" clearable filterable placeholder="选择现有分类" style="width: 100%">
                <el-option v-for="item in categories" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="封装"><el-input v-model="form.package" placeholder="例如 0805 / SOT-223 / QFN-32" /></el-form-item>
            <el-form-item label="厂商"><el-input v-model="form.manufacturer" placeholder="例如 TI / ST / 国巨" /></el-form-item>
            <el-form-item label="立创编号"><el-input v-model="form.lcsc_number" placeholder="Cxxxxxx，可空" /></el-form-item>
          </div>
        </div>

        <div class="draft-card inventory-draft-card">
          <div class="draft-card-title">
            <div>
              <strong>库存与来源</strong>
              <span>数量、位置和采购来源</span>
            </div>
          </div>
          <div class="field-grid inventory-field-grid">
            <el-form-item label="库存数量" required><el-input-number v-model="form.quantity" :min="0" style="width: 100%" /></el-form-item>
            <el-form-item label="均价（元/件，可空）"><el-input-number v-model="form.average_unit_price" :min="0" :precision="6" :step="0.01" controls-position="right" style="width: 100%" /></el-form-item>
            <el-form-item label="安全库存"><el-input-number v-model="form.safety_quantity" :min="0" style="width: 100%" /></el-form-item>
            <el-form-item label="存放位置"><el-input v-model="form.location" placeholder="例如 A03-2 / 元件柜 1；运输进度请在采购中管理" /></el-form-item>
            <el-form-item label="来源"><el-input v-model="form.source" placeholder="手动新增 / 立创 / 其他平台" /></el-form-item>
          </div>
        </div>

        <el-collapse v-model="advancedSections" class="advanced-collapse">
          <el-collapse-item name="details">
            <template #title>
              <div class="collapse-title">
                <strong>扩展资料</strong>
                <span>参数、描述、标签、链接与备注</span>
              </div>
            </template>
            <div class="field-grid advanced-field-grid">
              <el-form-item label="参数" class="wide-field"><el-input v-model="form.parameters" type="textarea" :rows="2" /></el-form-item>
              <el-form-item label="描述" class="wide-field"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
              <el-form-item label="标签"><el-input v-model="form.tags" placeholder="多个标签使用逗号分隔" /></el-form-item>
              <el-form-item label="数据手册"><el-input v-model="form.datasheet_url" placeholder="PDF 链接" /></el-form-item>
              <el-form-item label="立创商品"><el-input v-model="form.buy_url" placeholder="立创商品页链接" /></el-form-item>
              <el-form-item label="备注" class="wide-field"><el-input v-model="form.remark" type="textarea" :rows="3" /></el-form-item>
            </div>
            <el-form-item label="属性标签" class="flag-checks">
              <el-checkbox v-model="form.is_common">常用</el-checkbox>
              <el-checkbox v-model="form.low_stock_exempt">免低库存预警</el-checkbox>
              <el-checkbox v-model="form.is_hand_solder_friendly">适合手焊</el-checkbox>
              <el-checkbox v-model="form.is_power_component">电源</el-checkbox>
              <el-checkbox v-model="form.is_signal_component">信号</el-checkbox>
              <el-checkbox v-model="form.is_high_current">大电流</el-checkbox>
              <el-checkbox v-model="form.is_high_voltage">高压</el-checkbox>
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
      </section>

      <div class="create-save-bar">
        <div class="save-summary">
          <strong>{{ form.name || form.model || '未命名草稿' }}</strong>
          <span>{{ saveSummary }}</span>
        </div>
        <div class="save-actions">
          <el-button @click="$emit('cancel')">取消</el-button>
          <el-button type="primary" :loading="saving" @click="$emit('submit')">确认保存</el-button>
        </div>
      </div>
    </el-form>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import LcscPasteImport from '../../shared/components/LcscPasteImport.vue'

const props = defineProps({
  form: { type: Object, required: true },
  categories: { type: Array, default: () => [] },
  lookup: { type: Function, required: true },
  quickPrompt: { type: String, default: '' },
  aiLoading: { type: Boolean, default: false },
  aiSuggestion: { type: Object, default: null },
  saving: { type: Boolean, default: false },
  importing: { type: Boolean, default: false },
  importingImages: { type: Boolean, default: false },
  externalParsing: { type: Boolean, default: false },
  lcscOrderUpload: { type: Function, required: true },
  imageUpload: { type: Function, required: true },
  externalOrderUpload: { type: Function, required: true },
  downloadTemplate: { type: Function, required: true }
})

const emit = defineEmits([
  'update:quickPrompt',
  'ai-complete',
  'lcsc-draft',
  'lcsc-existing',
  'cancel',
  'submit'
])

const methods = [
  { value: 'lcsc', label: '立创复制录入', short: '单件 · 官方补全', description: '粘贴一键复制文本，自动查询官方资料', icon: 'C', tone: 'green', recommended: true, workspaceTitle: '粘贴立创器件信息', workspaceDescription: '识别完整 C 编号后自动查询，官方值会写入下方草稿。' },
  { value: 'ai', label: 'AI 描述新增', short: '单件 · 智能整理', description: '输入型号或规格，快速生成可编辑草稿', icon: 'AI', tone: 'blue', workspaceTitle: '描述你要录入的器件', workspaceDescription: '型号、规格、封装和用途都可以写，信息越完整结果越准确。' },
  { value: 'manual', label: '手动填写', short: '单件 · 完全可控', description: '直接填写核心字段，适合熟悉的物料', icon: '✎', tone: 'slate', workspaceTitle: '手动建立器件草稿', workspaceDescription: '跳过自动识别，直接在下方填写需要的字段。' },
  { value: 'batch', label: '批量导入', short: '多件 · 文件识别', description: '立创订单、购物截图或其他平台表格', icon: '批', tone: 'purple', workspaceTitle: '选择批量来源', workspaceDescription: '上传后先预览，再决定新增、合并或跳过。' }
]

const activeMethod = ref('lcsc')
const advancedSections = ref([])
const lcscImporter = ref(null)
const nameInput = ref(null)
const batchStarted = ref(false)
const activeMethodMeta = computed(() => methods.find((item) => item.value === activeMethod.value) || methods[0])
const draftReady = computed(() => Boolean(String(props.form.name || props.form.model || '').trim()))
const completedCoreFields = computed(() => [props.form.name || props.form.model, props.form.category_id, props.form.package, props.form.manufacturer, props.form.lcsc_number, props.form.quantity !== null && props.form.quantity !== undefined].filter(Boolean).length)
const saveSummary = computed(() => {
  const parts = [props.form.model, props.form.package, `库存 ${Number(props.form.quantity || 0)}`].filter(Boolean)
  return parts.join(' · ')
})

function confidenceLabel(value) {
  return ({ high: '高', medium: '中', low: '低' })[value] || '待核对'
}

function selectMethod(value) {
  activeMethod.value = value
  if (value === 'manual' && !props.form.source) props.form.source = '手动新增'
  if (value === 'ai' && !props.form.source) props.form.source = 'AI 辅助新增'
}

function focusNameField() {
  nextTick(() => nameInput.value?.focus?.())
}

function forwardLcscDraft(...args) {
  emit('lcsc-draft', ...args)
}

async function uploadLcscOrder(options) {
  batchStarted.value = true
  return props.lcscOrderUpload(options)
}

async function uploadImage(options) {
  batchStarted.value = true
  return props.imageUpload(options)
}

async function uploadExternalOrder(options) {
  batchStarted.value = true
  return props.externalOrderUpload(options)
}

function reset() {
  activeMethod.value = 'lcsc'
  advancedSections.value = []
  batchStarted.value = false
  nextTick(() => lcscImporter.value?.reset())
}

defineExpose({ reset, selectMethod })
</script>

<style scoped>
.create-workspace {
  --create-border: #e4eaf2;
  display: grid;
  gap: 14px;
  padding-bottom: 4px;
}

.create-intro-card,
.create-section,
.draft-card {
  border: 1px solid var(--create-border);
  border-radius: var(--cw-radius-card);
  background: #fff;
}

.create-intro-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 20px;
  background: linear-gradient(135deg, #f8fafc 0%, #fff 58%, #fff7ed 100%);
}

.create-eyebrow,
.section-step {
  color: #ea580c;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .08em;
}

.create-intro-card h2 {
  margin: 5px 0 4px;
  color: #172033;
  font-size: 21px;
}

.create-intro-card p,
.section-heading p,
.manual-create-panel p,
.batch-source-card p {
  margin: 0;
  color: #667085;
  line-height: 1.5;
}

.create-progress {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 8px;
}

.create-progress span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #98a2b3;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.create-progress b {
  display: inline-grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border: 1px solid #d0d5dd;
  border-radius: 50%;
  background: #fff;
}

.create-progress span.is-done { color: #344054; }
.create-progress span.is-done b { border-color: #fdba74; background: #fff7ed; color: #c2410c; }
.create-progress i { width: 18px; height: 1px; background: #d0d5dd; }

.create-section { padding: 16px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.section-heading > div { display: flex; align-items: flex-start; gap: 10px; }
.section-step { display: inline-grid; min-width: 30px; height: 30px; place-items: center; border-radius: 10px; background: #fff7ed; }
.section-heading h3 { margin: 0 0 3px; color: #172033; font-size: 17px; }
.section-heading p { font-size: 13px; }

.method-card-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.method-card {
  position: relative;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 18px;
  gap: 10px;
  min-height: 102px;
  padding: 13px;
  border: 1px solid #e4e7ec;
  border-radius: 14px;
  background: #fff;
  color: #344054;
  text-align: left;
  cursor: pointer;
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
}
.method-card:hover { transform: translateY(-1px); border-color: #f4a261; box-shadow: 0 8px 20px rgba(15, 23, 42, .07); }
.method-card.is-active { border-color: var(--method-color, #f97316); box-shadow: 0 0 0 2px color-mix(in srgb, var(--method-color, #f97316) 14%, transparent); background: var(--method-bg, #fff7ed); }
.method-icon { display: inline-grid; width: 42px; height: 42px; place-items: center; border-radius: 13px; background: var(--method-icon-bg, #f2f4f7); color: var(--method-color, #475467); font-size: 14px; font-weight: 900; }
.method-copy { display: grid; align-content: start; gap: 5px; min-width: 0; }
.method-copy strong { color: #172033; font-size: 15px; }
.method-copy small { color: #667085; font-size: 12px; line-height: 1.45; }
.method-check { align-self: center; color: var(--method-color, #98a2b3); font-size: 18px; font-weight: 900; }
.method-badge { position: absolute; top: -8px; right: 10px; padding: 2px 7px; border-radius: 999px; background: #047857; color: #fff; font-size: 10px; font-weight: 800; }
.tone-green { --method-color: #047857; --method-bg: #f0fdf9; --method-icon-bg: #d1fae5; }
.tone-blue { --method-color: #2563eb; --method-bg: #f5f8ff; --method-icon-bg: #dbeafe; }
.tone-slate { --method-color: #475467; --method-bg: #f8fafc; --method-icon-bg: #e2e8f0; }
.tone-purple { --method-color: #7c3aed; --method-bg: #faf7ff; --method-icon-bg: #ede9fe; }

.method-workspace-section { background: #fbfcfe; }
.method-workspace-section :deep(.lcsc-paste-card) { margin: 0; background: #fff; }
.ai-create-panel { display: grid; gap: 11px; padding: 14px; border: 1px solid #bfdbfe; border-radius: 14px; background: #fff; }
.panel-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; color: #667085; font-size: 13px; }
.ai-result-strip { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 10px 12px; border-radius: 12px; background: #eff6ff; color: #475467; }
.ai-result-strip strong { color: #1d4ed8; }
.manual-create-panel { display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; gap: 13px; align-items: center; padding: 16px; border: 1px dashed #cbd5e1; border-radius: 14px; background: #fff; }
.manual-mark { display: inline-grid; width: 48px; height: 48px; place-items: center; border-radius: 14px; background: #f1f5f9; color: #475569; font-size: 22px; font-weight: 800; }
.manual-create-panel strong { display: block; margin-bottom: 4px; color: #172033; }

.batch-card-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.batch-source-card { display: grid; align-content: start; gap: 13px; min-height: 218px; padding: 16px; border: 1px solid color-mix(in srgb, var(--method-color) 24%, #e4e7ec); border-radius: 14px; background: var(--method-bg); }
.batch-source-card strong { display: block; margin-bottom: 5px; color: #172033; font-size: 16px; }
.batch-type { display: inline-grid; width: 48px; height: 34px; place-items: center; border-radius: 10px; background: var(--method-icon-bg); color: var(--method-color); font-size: 12px; font-weight: 900; }
.batch-source-card :deep(.el-upload) { width: 100%; }
.batch-source-card :deep(.el-button) { width: 100%; margin-left: 0; }
.batch-actions { display: grid; gap: 4px; margin-top: auto; }

.draft-section { display: grid; gap: 12px; }
.draft-section > .section-heading { margin-bottom: 0; }
.draft-completeness { color: #667085; font-size: 12px; font-weight: 700; }
.draft-card { padding: 15px; }
.draft-card-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.draft-card-title > div { display: grid; gap: 2px; }
.draft-card-title strong { color: #172033; }
.draft-card-title span { color: #667085; font-size: 12px; }
.required-hint { margin: 0 0 10px; color: #667085; font-size: 12px; }
.required-hint span { color: #dc2626; font-weight: 900; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.field-grid .wide-field { grid-column: 1 / -1; }
.inventory-field-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.draft-card :deep(.el-form-item), .advanced-collapse :deep(.el-form-item) { margin-bottom: 12px; }
.draft-card :deep(.el-form-item__label), .advanced-collapse :deep(.el-form-item__label) { margin-bottom: 5px; color: #344054; font-weight: 650; }

.advanced-collapse { overflow: hidden; border: 1px solid var(--create-border); border-radius: var(--cw-radius-card); background: #fff; }
.advanced-collapse :deep(.el-collapse-item__header) { height: auto; min-height: 58px; padding: 0 16px; border-bottom: 0; }
.advanced-collapse :deep(.el-collapse-item__wrap) { border-bottom: 0; }
.advanced-collapse :deep(.el-collapse-item__content) { padding: 0 16px 10px; }
.collapse-title { display: grid; gap: 2px; text-align: left; }
.collapse-title strong { color: #172033; }
.collapse-title span { color: #667085; font-size: 12px; font-weight: 400; }
.flag-checks :deep(.el-form-item__content) { display: flex; flex-wrap: wrap; gap: 8px 14px; }
.flag-checks :deep(.el-checkbox) { margin-right: 0; }

.create-save-bar { position: sticky; bottom: -4px; z-index: 3; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 13px 14px; border: 1px solid #e4e7ec; border-radius: 16px; background: rgba(255, 255, 255, .96); box-shadow: 0 -10px 30px rgba(15, 23, 42, .08); backdrop-filter: blur(12px); }
.save-summary { display: grid; gap: 2px; min-width: 0; }
.save-summary strong { overflow: hidden; color: #172033; text-overflow: ellipsis; white-space: nowrap; }
.save-summary span { color: #667085; font-size: 12px; }
.save-actions { display: flex; flex: 0 0 auto; gap: 8px; }
.save-actions .el-button { min-width: 104px; margin-left: 0; }

@media (max-width: 860px) {
  .create-intro-card { align-items: flex-start; flex-direction: column; }
  .method-card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .batch-card-grid { grid-template-columns: 1fr; }
  .batch-source-card { min-height: auto; }
  .inventory-field-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 620px) {
  .create-workspace { gap: 10px; }
  .create-intro-card, .create-section { padding: 13px; }
  .create-progress { width: 100%; justify-content: space-between; }
  .create-progress span { display: grid; justify-items: center; gap: 4px; font-size: 10px; }
  .create-progress i { flex: 1 1 auto; }
  .method-card-grid { grid-template-columns: 1fr 1fr; gap: 8px; }
  .method-card { grid-template-columns: 36px minmax(0, 1fr); min-height: 94px; padding: 11px; }
  .method-icon { width: 36px; height: 36px; }
  .method-check { display: none; }
  .method-copy small { font-size: 11px; }
  .section-heading { align-items: flex-start; }
  .section-heading > .el-tag, .draft-completeness { display: none; }
  .field-grid, .inventory-field-grid { grid-template-columns: 1fr; }
  .manual-create-panel { grid-template-columns: 42px minmax(0, 1fr); }
  .manual-mark { width: 42px; height: 42px; }
  .manual-create-panel .el-button { grid-column: 1 / -1; width: 100%; }
  .panel-actions { display: grid; grid-template-columns: 1fr; }
  .panel-actions .el-button { width: 100%; }
  .create-save-bar { align-items: stretch; flex-direction: column; padding: 10px; }
  .save-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .save-actions .el-button { width: 100%; min-width: 0; }
}
</style>
