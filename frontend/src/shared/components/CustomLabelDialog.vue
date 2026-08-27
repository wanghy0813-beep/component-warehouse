<template>
  <component
    :is="standalone ? 'section' : 'el-dialog'"
    v-model="visible"
    class="custom-label-dialog"
    :class="{ standalone }"
    title="自定义标签"
    width="980px"
  >
    <div v-if="standalone" class="custom-label-page-head">
      <div>
        <strong>自定义标签</strong>
        <span>标签模板、素材和打印样式</span>
      </div>
      <div class="page-actions">
        <el-button :loading="saving" @click="saveCurrent">保存模板</el-button>
        <el-button :disabled="!selectedId" @click="duplicateCurrent">复制模板</el-button>
        <el-button :disabled="!selectedId" type="danger" plain @click="archiveCurrent">归档</el-button>
        <el-button :loading="exporting" @click="exportCalibration">校准页</el-button>
        <el-button type="primary" :loading="exporting" @click="exportCurrent">导出 40 格</el-button>
      </div>
    </div>
    <div class="custom-label-layout">
      <aside class="template-list">
        <div class="section-title">
          <strong>模板记录</strong>
          <el-button size="small" plain @click="newTemplate">新建</el-button>
        </div>
        <button
          v-for="item in templates"
          :key="item.id"
          class="template-item"
          :class="{ active: item.id === selectedId }"
          type="button"
          @click="selectTemplate(item)"
        >
          <strong>{{ item.name }}</strong>
          <span>{{ item.assets?.length || 0 }} 个素材</span>
        </button>
        <el-empty v-if="!templates.length" description="暂无自定义标签" :image-size="60" />
        <div class="template-examples">
          <div class="section-title compact">
            <strong>案例模板</strong>
            <span>按需导入到当前模板</span>
          </div>
          <el-button class="import-example-button" plain @click="templateExamplesOpen = true">导入案例模板</el-button>
        </div>
        <div class="style-list">
          <div class="section-title compact">
            <strong>当前模板内样式</strong>
            <el-button size="small" plain @click="addStyle">新增样式</el-button>
          </div>
          <button
            v-for="style in draft.content.styles"
            :key="style.id"
            class="style-item"
            :class="{ active: style.id === activeStyleId }"
            type="button"
            @click="selectStyle(style.id)"
          >
            <span>{{ style.name }}</span>
            <small>{{ style.elements?.length || 0 }} 个元素</small>
          </button>
          <el-button v-if="draft.content.styles?.length > 1" size="small" type="danger" plain @click="removeActiveStyle">删除当前样式</el-button>
        </div>
      </aside>

      <main class="designer">
        <section class="preview-panel">
          <div class="section-title">
            <strong>实时预览</strong>
            <span>A4 40 格中的单张标签尺寸</span>
          </div>
          <div class="preview-shell">
            <article class="preview-label" :class="{ 'standard-category-preview-label': isStandardCategoryGroup }">
              <img v-if="showTemplateLogo" class="preview-logo" :src="brandLogoUrl" :alt="BRAND_SHORT" />
              <div class="preview-canvas" :class="{ 'without-logo': !showTemplateLogo }">
                <div v-if="isStandardCategoryGroup" class="standard-category-preview">
                  <span class="standard-category-kicker"><b>分类标签</b><span>常用料盒</span></span>
                  <span class="standard-category-title-band"><strong>{{ activeStandardCategoryName }}</strong></span>
                  <span class="standard-category-package" :class="{ muted: !activeStandardCategorySummary }">
                    {{ activeStandardCategorySummary ? `${activeStandardCategoryLabel} ${activeStandardCategorySummary}` : '当前库里暂无此分类器件，导出时不生成' }}
                  </span>
                </div>
                <template v-else>
                  <i
                    v-for="guide in snapGuides"
                    :key="`${guide.axis}-${guide.value}`"
                    class="snap-guide"
                    :class="`snap-guide-${guide.axis}`"
                    :style="snapGuideStyle(guide)"
                  ></i>
                  <div
                    v-for="element in draft.content.elements"
                    :key="element.id"
                    class="preview-element"
                    :class="{ active: element.id === activeElementId }"
                    :style="elementStyle(element)"
                    @pointerdown.stop="startElementDrag($event, element)"
                  >
                    <div v-if="element.type === 'text'" class="preview-text" :style="textStyle(element)">{{ element.text }}</div>
                    <div v-else-if="element.type === 'field'" class="preview-text field-token" :style="textStyle(element)">{{ fieldPreview(element) }}</div>
                    <div v-else-if="element.type === 'category_badge'" class="preview-text category-token" :style="textStyle(element)">{{ fieldPreview(element) }}</div>
                    <div v-else-if="element.type === 'shape'" class="shape-token" :style="shapeStyle(element)"></div>
                    <img v-else-if="assetPreviewUrl(element.asset_id)" :src="assetPreviewUrl(element.asset_id)" alt="" @error="markAssetFailed(element.asset_id)" />
                    <button v-else class="missing-asset" type="button" @click.stop="retryAssetPreview(element.asset_id)">
                      {{ assetPreviewText(element.asset_id) }}
                    </button>
                    <i class="resize-handle" @pointerdown.stop="startElementResize($event, element)"></i>
                  </div>
                </template>
              </div>
              <em>{{ printMeta }}</em>
            </article>
          </div>
        </section>

        <section class="editor-panel">
          <div class="editor-grid">
            <el-form label-position="top">
              <el-form-item label="模板名称">
                <el-input v-model="draft.name" maxlength="160" placeholder="例如 纸盒分类 / 临时标记" />
              </el-form-item>
              <el-form-item label="品牌 Logo">
                <el-switch
                  v-model="draft.content.show_logo"
                  inline-prompt
                  active-text="显示"
                  inactive-text="隐藏"
                />
              </el-form-item>
              <el-form-item label="标签内容">
                <el-input v-model="quickText" type="textarea" :rows="3" placeholder="输入文字后点击“替换为文字标签”" />
              </el-form-item>
              <div class="editor-actions">
                <el-button plain @click="replaceWithText">替换为文字标签</el-button>
                <el-button plain @click="addText">追加文字</el-button>
                <el-button plain @click="addField('warehouse_code')">器件 ID</el-button>
                <el-button plain @click="addField('package', '封装 ')">封装</el-button>
                <el-button plain @click="addField('first_stocked_at', '入库 ')">入库日期</el-button>
                <el-upload :show-file-list="false" accept=".png,.jpg,.jpeg,.webp,.svg" :http-request="uploadElementAsset">
                  <el-button plain :loading="assetUploading">插入图片 / SVG</el-button>
                </el-upload>
              </div>
              <p v-if="assetUploadHint" class="upload-hint">{{ assetUploadHint }}</p>
            </el-form>

            <div class="preset-panel">
              <div class="section-title compact">
                <strong>分类预设</strong>
                <span>可直接套用后再拖动微调</span>
              </div>
              <div class="preset-grid">
                <button v-for="preset in categoryPresets" :key="preset.name" type="button" @click="applyCategoryPreset(preset)">
                  {{ preset.name }}
                </button>
              </div>
            </div>

            <div class="preset-panel">
              <div class="section-title compact">
                <strong>样式案例</strong>
                <span>作用于当前模板的当前样式</span>
              </div>
              <div class="style-example-grid">
                <button v-for="style in styleExamples" :key="style.id" type="button" @click="applyStyleExample(style)">
                  <strong>{{ style.name }}</strong>
                  <span>{{ style.use }}</span>
                </button>
              </div>
            </div>

            <div class="element-list">
              <div class="section-title compact">
                <strong>元素</strong>
                <span>X/Y 是位置，宽度/高度是大小</span>
              </div>
              <article v-for="element in draft.content.elements" :key="element.id" class="element-card">
                <div class="element-head">
                  <strong>{{ elementLabel(element) }}</strong>
                  <el-button size="small" text type="danger" @click="removeElement(element.id)">删除</el-button>
                </div>
                <el-input v-if="element.type === 'text'" v-model="element.text" size="small" />
                <el-select v-if="['field', 'category_badge'].includes(element.type)" v-model="element.field" size="small">
                  <el-option v-for="field in fieldOptions" :key="field.value" :label="field.label" :value="field.value" />
                </el-select>
                <div class="alignment-tools">
                  <div>
                    <span>元素对齐</span>
                    <div class="alignment-button-group">
                      <el-button size="small" @click="alignElement(element, 'left')">左</el-button>
                      <el-button size="small" @click="alignElement(element, 'center')">水平居中</el-button>
                      <el-button size="small" @click="alignElement(element, 'right')">右</el-button>
                    </div>
                    <div class="alignment-button-group">
                      <el-button size="small" @click="alignElement(element, 'top')">顶端</el-button>
                      <el-button size="small" @click="alignElement(element, 'middle')">垂直居中</el-button>
                      <el-button size="small" @click="alignElement(element, 'bottom')">底端</el-button>
                    </div>
                  </div>
                  <div v-if="['text', 'field', 'category_badge'].includes(element.type)">
                    <span>文字对齐</span>
                    <el-radio-group v-model="element.align" size="small">
                      <el-radio-button label="left">左</el-radio-button>
                      <el-radio-button label="center">中</el-radio-button>
                      <el-radio-button label="right">右</el-radio-button>
                    </el-radio-group>
                  </div>
                </div>
                <div class="element-controls">
                  <label>X 位置 mm <el-input-number :model-value="boxValue(element, 'x')" size="small" :min="-2" :max="52.5" :step="0.1" :precision="1" :controls="false" @update:model-value="setBoxValue(element, 'x', $event)" /></label>
                  <label>Y 位置 mm <el-input-number :model-value="boxValue(element, 'y')" size="small" :min="-2" :max="29.7" :step="0.1" :precision="1" :controls="false" @update:model-value="setBoxValue(element, 'y', $event)" /></label>
                  <label>宽度 mm <el-input-number :model-value="boxValue(element, 'width')" size="small" :min="2" :max="52.5" :step="0.1" :precision="1" :controls="false" @update:model-value="setBoxValue(element, 'width', $event)" /></label>
                  <label>高度 mm <el-input-number :model-value="boxValue(element, 'height')" size="small" :min="2" :max="29.7" :step="0.1" :precision="1" :controls="false" @update:model-value="setBoxValue(element, 'height', $event)" /></label>
                  <label v-if="isTextElement(element)">字号 <el-input-number v-model="element.font_size" size="small" :min="5" :max="28" :step="0.5" :precision="1" :controls="false" /></label>
                  <label v-if="isTextElement(element)">字体
                    <el-select v-model="element.font_family" size="small">
                      <el-option v-for="font in fontOptions" :key="font.value" :label="font.label" :value="font.value" />
                    </el-select>
                  </label>
                </div>
              </article>
            </div>
          </div>
        </section>
      </main>
    </div>

    <template v-if="!standalone" #footer>
      <el-button :loading="saving" @click="saveCurrent">保存模板</el-button>
      <el-button :disabled="!selectedId" @click="duplicateCurrent">复制模板</el-button>
      <el-button :disabled="!selectedId" type="danger" plain @click="archiveCurrent">归档</el-button>
      <el-button :loading="exporting" @click="exportCalibration">校准页</el-button>
      <el-button type="primary" :loading="exporting" @click="exportCurrent">导出 40 格</el-button>
    </template>
    <el-dialog v-model="templateExamplesOpen" title="导入案例模板" width="520px" append-to-body>
      <div class="example-picker">
        <button
          v-for="example in templateExamples"
          :key="example.id"
          class="example-item"
          type="button"
          @click="importTemplateExample(example)"
        >
          <strong>{{ example.name }}</strong>
          <span>{{ example.use }}</span>
        </button>
      </div>
    </el-dialog>
  </component>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from '../elementApi'
import brandLogoUrl from '../../assets/brand-logo.png'
import { BRAND_SHORT, BRAND_SHOW_LOGO } from '../branding'

const props = defineProps({
  modelValue: Boolean,
  standalone: Boolean,
  templates: { type: Array, default: () => [] },
  categorySummaries: { default: null },
  saving: Boolean,
  exportSheet: { type: Function, required: true },
  saveTemplate: { type: Function, required: true },
  archiveTemplate: { type: Function, required: true },
  uploadAsset: { type: Function, required: true },
  loadAsset: { type: Function, default: null }
})

const emit = defineEmits(['update:modelValue', 'refresh'])
const visible = computed({
  get: () => props.standalone || props.modelValue,
  set: (value) => {
    if (!props.standalone) emit('update:modelValue', value)
  }
})
const selectedId = ref('')
const quickText = ref('纸盒分类')
const assetUploading = ref(false)
const assetUploadHint = ref('')
const exporting = ref(false)
const templateExamplesOpen = ref(false)
const draft = reactive(defaultDraft())
const assetPreviewUrls = reactive({})
const assetPreviewStates = reactive({})
const assetPreviewInflight = new Map()
const assetPreviewQueue = []
let assetPreviewActive = 0
const activeElementId = ref('')
const activeStyleId = ref('')
const dragState = ref(null)
const snapGuides = ref([])
const IMAGE_COMPRESS_MIN_BYTES = 900 * 1024
const IMAGE_MAX_SIDE = 1600
const IMAGE_QUALITY = 0.82
const CANVAS_MM = { width: 52.5, height: 29.7 }
const PREVIEW_PX_PER_MM = 10
const CSS_PX_PER_MM = 96 / 25.4
const FONT_PREVIEW_SCALE = PREVIEW_PX_PER_MM / CSS_PX_PER_MM
const SNAP_THRESHOLD_MM = 0.75
const TEXT_ELEMENT_TYPES = new Set(['text', 'field', 'category_badge'])
const FONT_STYLE_ID = 'cw-custom-label-fonts'
const fieldOptions = [
  { label: '器件 ID', value: 'warehouse_code' },
  { label: '名称', value: 'name' },
  { label: '型号', value: 'model' },
  { label: '分类', value: 'category' },
  { label: '封装', value: 'package' },
  { label: '核心规格', value: 'normalized_spec' },
  { label: '立创 ID', value: 'lcsc_number' },
  { label: '位置', value: 'location' },
  { label: '库存数量', value: 'quantity' },
  { label: '首次入库', value: 'first_stocked_at' },
  { label: '最近入库', value: 'last_stocked_at' }
]
const fontOptions = [
  { label: '系统黑体', value: 'system' },
  { label: '得意黑', value: 'deyi' },
  { label: '钉钉进步体', value: 'dingtalk' },
  { label: 'MiSans', value: 'misans' },
  { label: '思源黑体', value: 'noto' },
  { label: '等宽', value: 'mono' }
]
const fontStacks = {
  system: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
  deyi: '"Smiley Sans", "smiley-sans", "得意黑", "Microsoft YaHei", sans-serif',
  dingtalk: '"DingTalk JinBuTi", "钉钉进步体", "Microsoft YaHei", sans-serif',
  misans: '"MiSans", "Microsoft YaHei", sans-serif',
  noto: '"Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif',
  mono: '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
}
const fieldPreviewValues = {
  warehouse_code: 'RES-00000001',
  name: '10k 电阻',
  model: '0805W8F1002T5E',
  category: '贴片电阻',
  package: '0805',
  normalized_spec: '10kΩ',
  lcsc_number: 'C17414',
  location: 'A-01',
  quantity: '100',
  first_stocked_at: '2026-07-01',
  last_stocked_at: '2026-07-01',
  print_date: '2026-07-01',
  scan_url: 'https://wxy-lab.example/scan/RES-00000001'
}
const categoryPresets = [
  '贴片电阻',
  '直插/采样电阻',
  'MLCC',
  '电解/固态',
  '电感/晶振',
  '二极管/保护',
  'BJT/MOS',
  '电源IC',
  '模拟IC',
  '数字/接口IC',
  '传感器',
  '排针/排母',
  'PH/XH/ZH/MX',
  'USB/XT/线束',
  '开关/机电',
  '模块/开发板/显示',
  '结构/工具/电池'
].map((name) => ({ name }))
const modelSummaryCategories = new Set(['模块/开发板/显示', '开关/机电', '传感器', '结构/工具/电池'])
const templateExamples = [
  { id: 'category-bin', name: '分类料盒标签', use: '抽屉 / 分格盒 / 货架' },
  { id: 'inventory-check', name: '待盘点/待确认标签', use: '复核 / 临时标记' }
]
const styleExamples = [
  { id: 'big-text', name: '大字', use: '料盒主标签' },
  { id: 'warning', name: '盘点', use: '待确认状态' },
  { id: 'plain-text', name: '纯文字', use: '临时备注' }
]

const printMeta = computed(() => {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `P:${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
})
const showTemplateLogo = computed(() => BRAND_SHOW_LOGO && draft.content?.show_logo !== false)
const isStandardCategoryGroup = computed(() => draft.content?.kind === 'standard_category_group')
const categorySummaryMap = computed(() => {
  const map = new Map()
  for (const item of props.categorySummaries || []) {
    if (!item?.category || !item?.summary) continue
    map.set(String(item.category), String(item.summary))
  }
  return map
})
const activeStandardCategoryName = computed(() => {
  const style = (draft.content.styles || []).find((item) => item.id === activeStyleId.value) || draft.content.styles?.[0]
  if (!style) return '元器件'
  if (style.category_name) return style.category_name
  const title = (style.elements || []).find((item) => item?.role === 'category_title' || item?.type === 'text')
  return title?.text || String(style.name || '元器件').replace(' 分类标签', '')
})
const activeStandardCategorySummary = computed(() => categorySummaryMap.value.get(activeStandardCategoryName.value) || '')
const activeStandardCategoryLabel = computed(() => (modelSummaryCategories.has(activeStandardCategoryName.value) ? '型号' : '封装'))

onMounted(() => {
  ensurePreviewFonts()
})

watch(() => props.templates, () => {
  if (!visible.value) return
  if (selectedId.value && props.templates.some((item) => item.id === selectedId.value)) return
  if (props.templates[0]) selectTemplate(props.templates[0])
}, { deep: true, immediate: true })

watch(visible, (value) => {
  if (!value) return
  if (props.templates[0]) selectTemplate(props.templates[0])
  else newTemplate()
})

watch(
  () => (draft.assets || []).map((asset) => `${asset.id}:${asset.url}:${asset.mime_type}`).join('|'),
  () => syncAssetPreviews(),
  { immediate: true }
)

function defaultDraft() {
  return {
    id: '',
    name: '自定义标签',
    assets: [],
    content: {
      show_logo: true,
      elements: [
        { id: `text-${Date.now()}`, type: 'text', text: '自定义标签', x_mm: 8, y_mm: 9, width_mm: 36.5, height_mm: 9, font_size: 18, font_family: 'system', color: '#111827', align: 'center' }
      ]
    }
  }
}

function applyDraft(value) {
  const source = value || defaultDraft()
  selectedId.value = source.id || ''
  draft.id = source.id || ''
  draft.name = source.name || '自定义标签'
  draft.assets = Array.isArray(source.assets) ? source.assets : []
  draft.content = cloneContent(source.content)
  activeStyleId.value = draft.content.active_style_id || draft.content.styles?.[0]?.id || ''
  activateStyle(activeStyleId.value)
}

function cloneContent(content) {
  const parsed = JSON.parse(JSON.stringify(content || {}))
  parsed.show_logo = Object.prototype.hasOwnProperty.call(parsed, 'show_logo') ? parsed.show_logo !== false : true
  if (!Array.isArray(parsed.elements) || !parsed.elements.length) parsed.elements = defaultDraft().content.elements
  parsed.elements = withoutDuplicatePrintDate(parsed.elements)
  if (!Array.isArray(parsed.styles) || !parsed.styles.length) {
    parsed.styles = [{ id: 'style-default', name: '默认样式', elements: JSON.parse(JSON.stringify(parsed.elements)) }]
  } else {
    parsed.styles = parsed.styles
      .filter((style) => style && typeof style === 'object')
      .map((style, index) => ({
        id: String(style.id || `style-${index + 1}`),
        name: String(style.name || `样式 ${index + 1}`),
        category_name: String(style.category_name || ''),
        elements: withoutDuplicatePrintDate(Array.isArray(style.elements) && style.elements.length ? style.elements : JSON.parse(JSON.stringify(parsed.elements)))
      }))
  }
  parsed.active_style_id = parsed.active_style_id || parsed.styles[0]?.id || 'style-default'
  return parsed
}

function syncActiveStyle() {
  const style = (draft.content.styles || []).find((item) => item.id === activeStyleId.value)
  if (style) style.elements = JSON.parse(JSON.stringify(draft.content.elements || []))
  draft.content.active_style_id = activeStyleId.value
}

function activateStyle(id) {
  const style = (draft.content.styles || []).find((item) => item.id === id) || draft.content.styles?.[0]
  if (!style) return
  activeStyleId.value = style.id
  draft.content.active_style_id = style.id
  draft.content.elements = JSON.parse(JSON.stringify(style.elements || []))
  activeElementId.value = ''
  syncAssetPreviews()
}

function selectStyle(id) {
  if (id === activeStyleId.value) return
  syncActiveStyle()
  activateStyle(id)
}

function addStyle() {
  syncActiveStyle()
  const id = `style-${Date.now()}`
  draft.content.styles = [...(draft.content.styles || []), { id, name: `样式 ${(draft.content.styles || []).length + 1}`, elements: JSON.parse(JSON.stringify(defaultDraft().content.elements)) }]
  activateStyle(id)
}

function removeActiveStyle() {
  if ((draft.content.styles || []).length <= 1) return
  const index = draft.content.styles.findIndex((item) => item.id === activeStyleId.value)
  draft.content.styles = draft.content.styles.filter((item) => item.id !== activeStyleId.value)
  activateStyle(draft.content.styles[Math.max(0, index - 1)]?.id || draft.content.styles[0]?.id)
}

function contentForSave() {
  syncActiveStyle()
  draft.content.elements = withoutDuplicatePrintDate(draft.content.elements)
  draft.content.styles = (draft.content.styles || []).map((style) => ({
    ...style,
    elements: withoutDuplicatePrintDate(style.elements || [])
  }))
  return JSON.parse(JSON.stringify(draft.content))
}

function withoutDuplicatePrintDate(elements) {
  return (Array.isArray(elements) ? elements : []).filter((item) => !(item?.type === 'field' && item?.field === 'print_date'))
}

function selectTemplate(item) {
  applyDraft(item)
}

function newTemplate() {
  applyDraft(defaultDraft())
}

function replaceWithText() {
  draft.content.elements = [{ id: `text-${Date.now()}`, type: 'text', text: quickText.value || '自定义标签', x: 14, y: 32, width: 72, height: 32, font_size: 16, font_family: 'system', color: '#111827', align: 'center' }]
}

function elementsForTemplateExample(id) {
  const stamp = Date.now()
  const examples = {
    'category-bin': [
      ...standardCategoryElements('贴片电阻', stamp)
    ],
    'inventory-check': [
      { id: `status-${stamp}`, type: 'text', text: '待确认', x_mm: 4.8, y_mm: 6.4, width_mm: 17, height_mm: 6, font_size: 15, font_family: 'system', color: '#b42318', align: 'left' },
      { id: `code-${stamp}`, type: 'field', field: 'warehouse_code', x_mm: 23, y_mm: 6.8, width_mm: 24.5, height_mm: 4, font_size: 9, font_family: 'system', color: '#111827', align: 'right' },
      { id: `name-${stamp}`, type: 'field', field: 'name', x_mm: 4.8, y_mm: 13.4, width_mm: 42.7, height_mm: 5.2, font_size: 10, font_family: 'system', color: '#000000', align: 'left' },
      { id: `qty-${stamp}`, type: 'field', field: 'quantity', prefix: '账面 ', x_mm: 4.8, y_mm: 21.8, width_mm: 16, height_mm: 3.2, font_size: 7, font_family: 'system', color: '#475569', align: 'left' },
      { id: `loc-${stamp}`, type: 'field', field: 'location', prefix: '位置 ', x_mm: 25, y_mm: 21.8, width_mm: 22.5, height_mm: 3.2, font_size: 7, font_family: 'system', color: '#475569', align: 'right' }
    ]
  }
  return examples[id] || examples['category-bin']
}

function applyTemplateExample(example) {
  syncActiveStyle()
  draft.name = example.name
  draft.content.show_logo = true
  if (example.id === 'category-bin') {
    draft.content.kind = 'standard_category_group'
    draft.content.styles = categoryPresets.map((preset, index) => ({
      id: `category-${index + 1}`,
      name: `${preset.name} 分类标签`,
      category_name: preset.name,
      elements: standardCategoryElements(preset.name, `${Date.now()}-${index}`)
    }))
  } else {
    delete draft.content.kind
    const elements = JSON.parse(JSON.stringify(elementsForTemplateExample(example.id)))
    draft.content.styles = [
      { id: 'style-default', name: '默认样式', elements }
    ]
  }
  activateStyle(draft.content.styles?.[0]?.id || 'style-default')
}

function importTemplateExample(example) {
  applyTemplateExample(example)
  templateExamplesOpen.value = false
  ElMessage.success(`已导入「${example.name}」`)
}

function applyStyleExample(style) {
  const nameMap = {
    'big-text': '大字',
    warning: '待确认',
    'plain-text': '纯文字'
  }
  const elements = style.id === 'big-text'
    ? elementsForTemplateExample('category-bin')
    : style.id === 'warning'
    ? elementsForTemplateExample('inventory-check')
    : [{ id: `text-${Date.now()}`, type: 'text', text: quickText.value || '临时备注', x_mm: 5, y_mm: 9, width_mm: 42.5, height_mm: 9, font_size: 18, font_family: 'system', color: '#111827', align: 'center' }]
  draft.content.elements = JSON.parse(JSON.stringify(elements))
  draft.content.show_logo = true
  const active = (draft.content.styles || []).find((item) => item.id === activeStyleId.value)
  if (active) active.name = nameMap[style.id] || active.name
  syncActiveStyle()
}

function addText() {
  const box = nextTextBox(32, 7)
  draft.content.elements.push({ id: `text-${Date.now()}`, type: 'text', text: quickText.value || '文字', ...box, font_size: 13, font_family: 'system', color: '#000000', align: 'center' })
}

function addField(field, prefix = '') {
  const box = nextTextBox(34, 4.2)
  draft.content.elements.push({ id: `field-${Date.now()}`, type: 'field', field, prefix, ...box, font_size: 8, font_family: 'system', color: '#000000', align: 'left' })
}

function applyCategoryPreset(preset) {
  draft.name = `${preset.name} 分类标签`
  quickText.value = preset.name
  draft.content.show_logo = true
  draft.content.kind = ''
  draft.content.elements = standardCategoryElements(preset.name)
  syncActiveStyle()
}

function standardCategoryElements(name, seed = Date.now()) {
  return [
    { id: `title-${seed}`, role: 'category_title', type: 'text', text: name, x_mm: 5, y_mm: 6.7, width_mm: 42.5, height_mm: 9.2, font_size: 22, font_family: 'dingtalk', color: '#000000', align: 'center', font_weight: 400 },
    { id: `hint-${seed}`, type: 'text', text: '料盒 / 分类 / 常用', x_mm: 8, y_mm: 15.9, width_mm: 36.5, height_mm: 4.4, font_size: 9, font_family: 'system', color: '#334155', align: 'center' },
    { id: `package-${seed}`, type: 'text', text: '封装按库存汇总', x_mm: 8, y_mm: 21, width_mm: 36.5, height_mm: 4.6, font_size: 9, font_family: 'dingtalk', color: '#000000', align: 'center', font_weight: 400 }
  ]
}

function removeElement(id) {
  draft.content.elements = draft.content.elements.filter((item) => item.id !== id)
  if (!draft.content.elements.length) replaceWithText()
}

async function saveCurrent() {
  const saved = await props.saveTemplate({ id: draft.id, name: draft.name || '自定义标签', content: contentForSave() })
  if (saved) {
    applyDraft(saved)
    emit('refresh')
    ElMessage.success('自定义标签已保存')
  }
  return saved
}

async function ensureSavedTemplate() {
  if (draft.id) return { id: draft.id, assets: draft.assets }
  return saveCurrent()
}

async function duplicateCurrent() {
  const copy = await props.saveTemplate({ name: `${draft.name || '自定义标签'} 副本`, content: contentForSave() })
  if (copy) {
    applyDraft(copy)
    emit('refresh')
    ElMessage.success('已复制模板')
  }
}

async function archiveCurrent() {
  if (!draft.id) return
  await ElMessageBox.confirm(`归档模板「${draft.name}」？`, '归档自定义标签', { type: 'warning' })
  await props.archiveTemplate(draft.id)
  emit('refresh')
  newTemplate()
  ElMessage.success('已归档')
}

async function uploadElementAsset({ file }) {
  assetUploading.value = true
  assetUploadHint.value = file?.type === 'image/svg+xml' ? '正在上传 SVG…' : '正在检查并压缩图片…'
  try {
    const template = await ensureSavedTemplate()
    if (!template?.id) return
    const preparedFile = await prepareAssetFile(file)
    if (preparedFile !== file && preparedFile.size < file.size) {
      assetUploadHint.value = `已压缩：${formatBytes(file.size)} → ${formatBytes(preparedFile.size)}，正在上传…`
    } else {
      assetUploadHint.value = '正在上传素材…'
    }
    const asset = await props.uploadAsset(template.id, preparedFile)
    draft.assets = [...(draft.assets || []), asset]
    primeAssetPreview(asset.id, preparedFile)
    draft.content.elements.push({
      id: `asset-${Date.now()}`,
      type: asset.mime_type === 'image/svg+xml' ? 'svg' : 'image',
      asset_id: asset.id,
      x: 23,
      y: 28,
      width: 54,
      height: 42,
      rotate: 0
    })
    await saveCurrent()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error.response?.data?.detail || '素材上传失败')
  } finally {
    assetUploading.value = false
    window.setTimeout(() => {
      if (!assetUploading.value) assetUploadHint.value = ''
    }, 1800)
  }
}

async function exportCurrent() {
  await exportWithOptions(false)
}

async function exportCalibration() {
  await exportWithOptions(true)
}

async function exportWithOptions(calibration) {
  exporting.value = true
  try {
    const saved = await saveCurrent()
    const blob = await props.exportSheet({ template_id: saved?.id || draft.id, content: contentForSave(), copies: 1, start_slot: 1, calibration })
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener')
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error.response?.data?.detail || '导出自定义标签失败')
  } finally {
    exporting.value = false
  }
}

function assetPreviewUrl(assetId) {
  if (!assetId) return ''
  const url = assetPreviewUrls[assetId] || ''
  if (!url) {
    const asset = (draft.assets || []).find((item) => item.id === assetId)
    if (asset) queueAssetPreview(asset)
  }
  return url
}

function assetPreviewText(assetId) {
  if (!assetId) return '素材未上传'
  const state = assetPreviewStates[assetId]
  if (state === 'loading') return '素材加载中…'
  if (state === 'failed') return '素材加载失败，可重新上传'
  return '素材未上传'
}

function markAssetFailed(assetId) {
  if (!assetId) return
  revokePreviewUrl(assetId)
  assetPreviewStates[assetId] = 'failed'
}

function syncAssetPreviews() {
  const activeIds = new Set((draft.assets || []).map((asset) => asset.id).filter(Boolean))
  for (const id of Object.keys(assetPreviewUrls)) {
    if (!activeIds.has(id)) revokePreviewUrl(id)
  }
  const visibleAssetIds = new Set((draft.content?.elements || []).map((item) => item?.asset_id).filter(Boolean))
  const visibleAssets = (draft.assets || []).filter((asset) => visibleAssetIds.has(asset?.id))
  const restAssets = (draft.assets || []).filter((asset) => asset?.id && !visibleAssetIds.has(asset.id))
  for (const asset of [...visibleAssets, ...restAssets]) {
    if (asset?.id) queueAssetPreview(asset)
  }
}

function queueAssetPreview(asset, force = false) {
  if (!asset?.id || assetPreviewInflight.has(asset.id)) return
  if (!force && assetPreviewUrls[asset.id]) return
  if (!force && assetPreviewStates[asset.id] === 'failed') return
  assetPreviewQueue.push({ asset, force })
  drainAssetPreviewQueue()
}

function retryAssetPreview(assetId) {
  const asset = (draft.assets || []).find((item) => item.id === assetId)
  if (!asset) return
  revokePreviewUrl(assetId)
  delete assetPreviewStates[assetId]
  queueAssetPreview(asset, true)
}

function drainAssetPreviewQueue() {
  while (assetPreviewActive < 2 && assetPreviewQueue.length) {
    const { asset, force } = assetPreviewQueue.shift()
    if (!force && (assetPreviewUrls[asset.id] || assetPreviewStates[asset.id] === 'failed')) continue
    assetPreviewActive += 1
    loadAssetPreview(asset, force).finally(() => {
      assetPreviewActive = Math.max(0, assetPreviewActive - 1)
      drainAssetPreviewQueue()
    })
  }
}

async function loadAssetPreview(asset, force = false) {
  if (!asset?.id || assetPreviewUrls[asset.id] || assetPreviewInflight.has(asset.id)) return
  if (!force && assetPreviewStates[asset.id] === 'failed') return
  if (!props.loadAsset) {
    assetPreviewStates[asset.id] = 'failed'
    return
  }
  assetPreviewStates[asset.id] = 'loading'
  const task = Promise.resolve()
    .then(() => props.loadAsset(asset.id))
    .then((blob) => {
      if (!blob) throw new Error('empty asset')
      primeAssetPreview(asset.id, blob)
    })
    .catch(() => {
      revokePreviewUrl(asset.id)
      assetPreviewStates[asset.id] = 'failed'
    })
    .finally(() => assetPreviewInflight.delete(asset.id))
  assetPreviewInflight.set(asset.id, task)
  await task
}

function primeAssetPreview(assetId, blobOrFile) {
  if (!assetId || !blobOrFile) return
  revokePreviewUrl(assetId)
  assetPreviewUrls[assetId] = URL.createObjectURL(blobOrFile)
  assetPreviewStates[assetId] = 'ready'
}

function revokePreviewUrl(assetId) {
  const url = assetPreviewUrls[assetId]
  if (url) URL.revokeObjectURL(url)
  delete assetPreviewUrls[assetId]
}

function cleanupPreviewUrls() {
  for (const id of Object.keys(assetPreviewUrls)) revokePreviewUrl(id)
  assetPreviewQueue.splice(0)
  assetPreviewInflight.clear()
}

function isRasterImage(file) {
  const type = String(file?.type || '').toLowerCase()
  return ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'].includes(type)
}

async function prepareAssetFile(file) {
  if (!file || !isRasterImage(file)) return file
  try {
    const image = await loadImage(file)
    const width = image.naturalWidth || image.width
    const height = image.naturalHeight || image.height
    if (!width || !height) return file
    const scale = Math.min(1, IMAGE_MAX_SIDE / Math.max(width, height))
    if (scale >= 1 && file.size <= IMAGE_COMPRESS_MIN_BYTES) return file
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    const context = canvas.getContext('2d', { alpha: true })
    if (!context) return file
    context.imageSmoothingEnabled = true
    context.imageSmoothingQuality = 'high'
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const blob = await canvasToBlob(canvas, 'image/webp', IMAGE_QUALITY)
      || await canvasToBlob(canvas, 'image/jpeg', IMAGE_QUALITY)
    if (!blob || blob.size >= file.size) return file
    const extension = blob.type === 'image/jpeg' ? 'jpg' : 'webp'
    const name = `${String(file.name || 'label-image').replace(/\.[^.]+$/, '')}.${extension}`
    return new File([blob], name, { type: blob.type || 'image/webp', lastModified: Date.now() })
  } catch {
    return file
  }
}

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const image = new Image()
    image.onload = () => {
      URL.revokeObjectURL(url)
      resolve(image)
    }
    image.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('image load failed'))
    }
    image.src = url
  })
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality))
}

function formatBytes(bytes) {
  const value = Number(bytes || 0)
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
  if (value >= 1024) return `${Math.round(value / 1024)} KB`
  return `${value} B`
}

function elementStyle(element) {
  if (hasMmBox(element)) {
    return {
      left: `${mmToPx(Number(element.x_mm || 0))}px`,
      top: `${mmToPx(Number(element.y_mm || 0))}px`,
      width: `${mmToPx(Number(element.width_mm || 10))}px`,
      height: `${mmToPx(Number(element.height_mm || 6))}px`,
      transform: `rotate(${Number(element.rotate || 0)}deg)`
    }
  }
  return {
    left: `${Number(element.x || 0)}%`,
    top: `${Number(element.y || 0)}%`,
    width: `${Number(element.width || 20)}%`,
    height: `${Number(element.height || 20)}%`,
    transform: `rotate(${Number(element.rotate || 0)}deg)`
  }
}

function shapeStyle(element) {
  return {
    width: '100%',
    height: '100%',
    background: element.fill || '#eff6ff',
    border: `1px solid ${element.stroke || '#93c5fd'}`,
    borderRadius: `${Number(element.radius || 1) * 10}px`
  }
}

function textStyle(element) {
  const justify = element.align === 'left' ? 'flex-start' : element.align === 'right' ? 'flex-end' : 'center'
  const defaultWeight = element.type === 'field' || element.type === 'category_badge' ? 800 : 400
  return {
    color: element.color || '#111827',
    fontFamily: fontStacks[element.font_family] || fontStacks.system,
    fontSize: `${printFontToPreviewPx(element.font_size || 13)}px`,
    fontWeight: Number(element.font_weight || defaultWeight),
    textAlign: element.align || 'center',
    justifyContent: justify
  }
}

function printFontToPreviewPx(size) {
  return Number(size || 13) * FONT_PREVIEW_SCALE
}

function isTextElement(element) {
  return TEXT_ELEMENT_TYPES.has(element?.type)
}

function ensurePreviewFonts() {
  if (typeof document === 'undefined' || document.getElementById(FONT_STYLE_ID)) return
  const base = import.meta.env.BASE_URL || '/'
  const style = document.createElement('style')
  style.id = FONT_STYLE_ID
  style.textContent = `
@import url('${base}fonts/dingtalk/font.css');
@import url('${base}fonts/misans/MiSans.min.css');
@font-face {
  font-family: 'Smiley Sans';
  src: url('${base}fonts/deyi/SmileySans-Oblique.woff2') format('woff2');
  font-display: swap;
}
@font-face {
  font-family: 'smiley-sans';
  src: url('${base}fonts/deyi/SmileySans-Oblique.woff2') format('woff2');
  font-display: swap;
}
@font-face {
  font-family: '得意黑';
  src: url('${base}fonts/deyi/SmileySans-Oblique.woff2') format('woff2');
  font-display: swap;
}
`
  document.head.appendChild(style)
}

function elementLabel(element) {
  return {
    text: '文字',
    field: '动态字段',
    category_badge: '分类徽标',
    shape: '形状',
    svg: 'SVG',
    image: '图片'
  }[element.type] || '元素'
}

function fieldPreview(element) {
  const field = element.field || 'name'
  const sample = fieldPreviewValues[field] || field
  return `${element.prefix || ''}${sample}`
}

function hasMmBox(element) {
  return ['x_mm', 'y_mm', 'width_mm', 'height_mm'].some((key) => Object.prototype.hasOwnProperty.call(element, key))
}

function ensureMmBox(element) {
  if (hasMmBox(element)) return
  element.x_mm = Number(element.x || 0) / 100 * CANVAS_MM.width
  element.y_mm = Number(element.y || 0) / 100 * CANVAS_MM.height
  element.width_mm = Number(element.width || 20) / 100 * CANVAS_MM.width
  element.height_mm = Number(element.height || 20) / 100 * CANVAS_MM.height
}

function boxValue(element, key) {
  ensureMmBox(element)
  return Number(element[`${key}_mm`] || 0)
}

function setBoxValue(element, key, value) {
  ensureMmBox(element)
  element[`${key}_mm`] = Number(value || 0)
}

function alignElement(element, direction) {
  ensureMmBox(element)
  activeElementId.value = element.id
  const width = Number(element.width_mm || 0)
  const height = Number(element.height_mm || 0)
  if (direction === 'left') element.x_mm = 0
  if (direction === 'center') element.x_mm = Math.max(0, (CANVAS_MM.width - width) / 2)
  if (direction === 'right') element.x_mm = Math.max(0, CANVAS_MM.width - width)
  if (direction === 'top') element.y_mm = 0
  if (direction === 'middle') element.y_mm = Math.max(0, (CANVAS_MM.height - height) / 2)
  if (direction === 'bottom') element.y_mm = Math.max(0, CANVAS_MM.height - height)
  snapGuides.value = []
}

function mmToPx(mm) {
  return mm * PREVIEW_PX_PER_MM
}

function pxToMm(px) {
  return px / PREVIEW_PX_PER_MM
}

function elementBox(element) {
  ensureMmBox(element)
  const width = Number(element.width_mm || 1)
  const height = Number(element.height_mm || 1)
  return {
    x: Number(element.x_mm || 0),
    y: Number(element.y_mm || 0),
    width,
    height,
    centerX: Number(element.x_mm || 0) + width / 2,
    centerY: Number(element.y_mm || 0) + height / 2,
    right: Number(element.x_mm || 0) + width,
    bottom: Number(element.y_mm || 0) + height
  }
}

function snapGuideStyle(guide) {
  return guide.axis === 'x'
    ? { left: `${mmToPx(guide.value)}px` }
    : { top: `${mmToPx(guide.value)}px` }
}

function textElements() {
  return (draft.content.elements || []).filter((item) => isTextElement(item))
}

function nextTextBox(width, height) {
  const previous = [...textElements()].reverse().find((item) => item?.id)
  if (!previous) return { x_mm: 10, y_mm: 10, width_mm: width, height_mm: height }
  const box = elementBox(previous)
  return {
    x_mm: Math.max(0, Math.min(CANVAS_MM.width - width, box.x)),
    y_mm: Math.max(0, Math.min(CANVAS_MM.height - height, box.bottom)),
    width_mm: width,
    height_mm: height
  }
}

function nearestSnap(source, targets) {
  let winner = null
  for (const target of targets) {
    const delta = target.value - source.value
    if (Math.abs(delta) > SNAP_THRESHOLD_MM) continue
    if (!winner || Math.abs(delta) < Math.abs(winner.delta)) {
      winner = { delta, axis: source.axis, value: target.value }
    }
  }
  return winner
}

function snapElementBox(element, nextX, nextY) {
  const width = Number(element.width_mm || 1)
  const height = Number(element.height_mm || 1)
  const otherBoxes = (draft.content.elements || [])
    .filter((item) => item && item.id !== element.id)
    .map((item) => elementBox(item))
  const xTargets = [
    { value: 0 },
    { value: CANVAS_MM.width / 2 },
    { value: CANVAS_MM.width },
    ...otherBoxes.flatMap((box) => [{ value: box.x }, { value: box.centerX }, { value: box.right }])
  ]
  const yTargets = [
    { value: 0 },
    { value: CANVAS_MM.height / 2 },
    { value: CANVAS_MM.height },
    ...otherBoxes.flatMap((box) => [{ value: box.y }, { value: box.centerY }, { value: box.bottom }])
  ]
  const xSources = [
    { axis: 'x', value: nextX },
    { axis: 'x', value: nextX + width / 2 },
    { axis: 'x', value: nextX + width }
  ]
  const ySources = [
    { axis: 'y', value: nextY },
    { axis: 'y', value: nextY + height / 2 },
    { axis: 'y', value: nextY + height }
  ]
  const snapX = xSources.map((source) => nearestSnap(source, xTargets)).filter(Boolean).sort((a, b) => Math.abs(a.delta) - Math.abs(b.delta))[0]
  const snapY = ySources.map((source) => nearestSnap(source, yTargets)).filter(Boolean).sort((a, b) => Math.abs(a.delta) - Math.abs(b.delta))[0]
  const snappedX = snapX ? nextX + snapX.delta : nextX
  const snappedY = snapY ? nextY + snapY.delta : nextY
  snapGuides.value = [snapX, snapY].filter(Boolean).map((item) => ({ axis: item.axis, value: item.value }))
  return {
    x: Math.max(-2, Math.min(CANVAS_MM.width - width, snappedX)),
    y: Math.max(-2, Math.min(CANVAS_MM.height - height, snappedY))
  }
}

function startElementDrag(event, element) {
  ensureMmBox(element)
  activeElementId.value = element.id
  dragState.value = {
    mode: 'move',
    id: element.id,
    startX: event.clientX,
    startY: event.clientY,
    x: Number(element.x_mm || 0),
    y: Number(element.y_mm || 0)
  }
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopPointerAction, { once: true })
}

function startElementResize(event, element) {
  ensureMmBox(element)
  activeElementId.value = element.id
  dragState.value = {
    mode: 'resize',
    id: element.id,
    startX: event.clientX,
    startY: event.clientY,
    width: Number(element.width_mm || 10),
    height: Number(element.height_mm || 6)
  }
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopPointerAction, { once: true })
}

function handlePointerMove(event) {
  const state = dragState.value
  if (!state) return
  const element = draft.content.elements.find((item) => item.id === state.id)
  if (!element) return
  const dx = pxToMm(event.clientX - state.startX)
  const dy = pxToMm(event.clientY - state.startY)
  if (state.mode === 'move') {
    const snapped = snapElementBox(element, state.x + dx, state.y + dy)
    element.x_mm = snapped.x
    element.y_mm = snapped.y
  } else {
    element.width_mm = Math.max(2, Math.min(CANVAS_MM.width, state.width + dx))
    element.height_mm = Math.max(2, Math.min(CANVAS_MM.height, state.height + dy))
    snapGuides.value = []
  }
}

function stopPointerAction() {
  window.removeEventListener('pointermove', handlePointerMove)
  dragState.value = null
  snapGuides.value = []
}

onBeforeUnmount(() => {
  cleanupPreviewUrls()
  window.removeEventListener('pointermove', handlePointerMove)
})
</script>

<style scoped>
.custom-label-dialog.standalone {
  display: block;
  min-width: 0;
}

.custom-label-page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.custom-label-page-head > div:first-child {
  display: grid;
  gap: 3px;
}

.custom-label-page-head strong {
  color: var(--cw-text);
  font-size: 22px;
}

.custom-label-page-head span {
  color: var(--cw-text-muted);
  font-size: 13px;
}

.page-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.custom-label-layout {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  gap: 14px;
  min-width: 0;
}

.template-list,
.preview-panel,
.editor-panel {
  min-width: 0;
  border: 1px solid var(--cw-border);
  border-radius: var(--cw-radius-card);
  background: #fff;
  padding: 14px;
}

.template-list {
  display: grid;
  align-content: start;
  gap: 8px;
  max-height: 620px;
  overflow: auto;
}

.style-list,
.template-examples {
  display: grid;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--cw-border);
}

.import-example-button {
  width: 100%;
}

.example-picker {
  display: grid;
  gap: 10px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  color: #667085;
}

.section-title strong {
  color: #172b4d;
}

.section-title.compact {
  margin-bottom: 8px;
}

.template-item {
  display: grid;
  gap: 4px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e4eaf2;
  border-radius: var(--cw-radius-control);
  background: #fff;
  color: #344054;
  text-align: left;
  cursor: pointer;
}

.template-item.active {
  border-color: #93c5fd;
  background: #eff6ff;
}

.template-item span {
  color: #667085;
  font-size: 12px;
}

.style-item,
.example-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #e4eaf2;
  border-radius: var(--cw-radius-control);
  color: #344054;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.style-item small {
  color: #667085;
}

.style-item.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.example-item {
  align-items: flex-start;
  flex-direction: column;
  background: #f8fafc;
}

.example-item strong {
  color: #172b4d;
}

.example-item span {
  color: #667085;
  font-size: 12px;
}

.designer,
.editor-grid,
.element-list {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.preview-shell {
  overflow: auto;
  padding: 12px;
  border-radius: var(--cw-radius-card);
  background: #f1f5f9;
}

.preview-label {
  position: relative;
  width: 525px;
  height: 297px;
  overflow: hidden;
  margin: 0 auto;
  border: 2px solid #cbd5e1;
  border-radius: var(--cw-radius-card);
  background: #fff;
  transform-origin: top left;
}

.preview-logo {
  position: absolute;
  z-index: 3;
  top: 10px;
  right: 16px;
  width: 118px;
  height: 44px;
  object-fit: contain;
}

.preview-label em {
  position: absolute;
  right: 14px;
  bottom: 8px;
  color: #98a2b3;
  font-size: 11px;
  font-style: normal;
}

.preview-canvas {
  position: relative;
  width: 100%;
  height: 100%;
  padding: 0;
}

.preview-canvas.without-logo {
  padding: 0;
}

.standard-category-preview-label .preview-logo {
  width: 108px;
  height: 38px;
}

.standard-category-preview {
  display: grid;
  grid-template-rows: 46px minmax(0, 1fr) 58px;
  gap: 8.5px;
  width: 100%;
  height: 100%;
  padding: 21.5px 25.5px 20.5px;
  font-family: "DingTalk JinBuTi", "钉钉进步体", "Microsoft YaHei", sans-serif;
  font-synthesis: none;
  text-align: center;
}

.standard-category-kicker {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  padding-right: 128px;
  color: #475569;
  font-size: 19.5px;
  font-weight: 400;
  line-height: 1;
  white-space: nowrap;
}

.standard-category-kicker b {
  color: #111827;
  font-weight: 400;
}

.standard-category-title-band {
  display: grid;
  place-items: center;
  min-width: 0;
  min-height: 0;
  border-top: 2px solid #d8dee8;
  border-bottom: 2px solid #d8dee8;
}

.standard-category-title-band strong {
  max-width: 452px;
  overflow: hidden;
  color: #000;
  font-size: 77px;
  font-weight: 400;
  letter-spacing: 0;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.standard-category-package {
  display: -webkit-box;
  align-self: start;
  justify-self: center;
  max-width: 450px;
  max-height: 57px;
  overflow: hidden;
  color: #111827;
  font-size: 24.2px;
  font-weight: 400;
  letter-spacing: 0;
  line-height: 1.12;
  text-overflow: ellipsis;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.standard-category-package.muted {
  color: #64748b;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size: 18px;
}

.preview-element {
  position: absolute;
  overflow: hidden;
  overflow-wrap: anywhere;
  cursor: move;
  user-select: none;
  touch-action: none;
}

.preview-element.active {
  outline: 2px solid #2563eb;
  outline-offset: 1px;
}

.preview-element img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.preview-text {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;
  white-space: pre-wrap;
  line-height: 1.18;
}

.snap-guide {
  position: absolute;
  z-index: 2;
  pointer-events: none;
  background: rgba(37, 99, 235, .5);
}

.snap-guide-x {
  top: 0;
  bottom: 0;
  width: 1px;
}

.snap-guide-y {
  left: 0;
  right: 0;
  height: 1px;
}

.field-token,
.category-token {
  font-weight: 800;
}

.shape-token {
  box-sizing: border-box;
}

.resize-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 12px;
  height: 12px;
  border: 2px solid #fff;
  border-radius: 999px;
  background: #2563eb;
  box-shadow: 0 0 0 1px rgba(37, 99, 235, .3);
  cursor: nwse-resize;
}

.missing-asset {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  border: 1px dashed #cbd5e1;
  border-radius: var(--cw-radius-control);
  color: #98a2b3;
  background: #fff;
  cursor: pointer;
  font: inherit;
  padding: 0;
}

.editor-actions,
.element-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.preset-panel {
  min-width: 0;
  padding: 10px;
  border: 1px solid #e4eaf2;
  border-radius: var(--cw-radius-card);
}

.preset-grid,
.style-example-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(86px, 1fr));
  gap: 8px;
}

.preset-grid button,
.style-example-grid button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 34px;
  border: 1px solid #dbe5f2;
  border-radius: var(--cw-radius-control);
  background: #fff;
  color: #17202a;
  font-weight: 700;
  cursor: pointer;
}

.style-example-grid button {
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  min-height: 54px;
  padding: 8px 10px;
  text-align: left;
}

.style-example-grid strong,
.style-example-grid span {
  display: block;
}

.style-example-grid strong {
  color: #172b4d;
}

.style-example-grid span {
  color: #667085;
  font-size: 12px;
  font-weight: 600;
}

.preset-grid span {
  font-size: 16px;
}

.element-card {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e4eaf2;
  border-radius: var(--cw-radius-card);
}

.alignment-tools {
  display: grid;
  gap: 8px;
  padding: 8px;
  border: 1px solid #edf2f7;
  border-radius: var(--cw-radius-control);
  background: #f8fafc;
}

.alignment-tools > div {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.alignment-tools span {
  min-width: 58px;
  color: #667085;
  font-size: 12px;
  font-weight: 700;
}

.alignment-button-group {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
}

.upload-hint {
  margin: 8px 0 0;
  color: #667085;
  font-size: 12px;
}

.element-head {
  justify-content: space-between;
}

.element-controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
  gap: 8px;
}

.element-controls label {
  display: grid;
  gap: 4px;
  color: #667085;
  font-size: 12px;
}

.element-controls :deep(.el-input-number) {
  width: 100%;
}

.element-controls :deep(.el-input__wrapper) {
  width: 100%;
}

:deep(.el-dialog),
:deep(.el-button),
:deep(.el-radio-button__inner),
:deep(.el-input__wrapper),
:deep(.el-textarea__inner),
:deep(.el-input-number),
:deep(.el-upload) {
  border-radius: var(--cw-radius-control);
}

:deep(.el-dialog) {
  max-height: calc(100dvh - 32px);
  display: flex;
  flex-direction: column;
}

:deep(.el-dialog__body) {
  overflow: auto;
  padding-top: 12px;
}

:deep(.el-dialog__footer) {
  padding-top: 10px;
}

@media (max-width: 760px) {
  .custom-label-layout {
    grid-template-columns: 1fr;
  }

  .preview-shell {
    padding: 8px;
  }

  .preview-label {
    width: min(525px, 86vw);
    height: calc(min(525px, 86vw) * 0.5657);
  }

  .template-list {
    max-height: 132px;
  }

  .editor-panel,
  .preview-panel {
    padding: 10px;
  }
}
</style>
