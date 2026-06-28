<template>
  <el-dialog v-model="visible" class="custom-label-dialog" title="自定义标签" width="980px">
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
      </aside>

      <main class="designer">
        <section class="preview-panel">
          <div class="section-title">
            <strong>实时预览</strong>
            <span>A4 40 格中的单张标签尺寸</span>
          </div>
          <div class="preview-shell">
            <article class="preview-label">
              <img v-if="BRAND_SHOW_LOGO" class="preview-logo" :src="brandLogoUrl" :alt="BRAND_SHORT" />
              <div class="preview-canvas">
                <div
                  v-for="element in draft.content.elements"
                  :key="element.id"
                  class="preview-element"
                  :style="elementStyle(element)"
                >
                  <div v-if="element.type === 'text'" class="preview-text" :style="textStyle(element)">{{ element.text }}</div>
                  <img v-else-if="assetPreviewUrl(element.asset_id)" :src="assetPreviewUrl(element.asset_id)" alt="" @error="markAssetFailed(element.asset_id)" />
                  <div v-else class="missing-asset">
                    {{ assetPreviewText(element.asset_id) }}
                  </div>
                </div>
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
              <el-form-item label="标签内容">
                <el-input v-model="quickText" type="textarea" :rows="3" placeholder="输入文字后点击“替换为文字标签”" />
              </el-form-item>
              <div class="editor-actions">
                <el-button plain @click="replaceWithText">替换为文字标签</el-button>
                <el-button plain @click="addText">追加文字</el-button>
                <el-upload :show-file-list="false" accept=".png,.jpg,.jpeg,.webp,.svg" :http-request="uploadElementAsset">
                  <el-button plain :loading="assetUploading">插入图片 / SVG</el-button>
                </el-upload>
              </div>
              <p v-if="assetUploadHint" class="upload-hint">{{ assetUploadHint }}</p>
            </el-form>

            <div class="element-list">
              <div class="section-title compact">
                <strong>元素</strong>
                <span>X/Y 是位置，宽度/高度是大小</span>
              </div>
              <article v-for="element in draft.content.elements" :key="element.id" class="element-card">
                <div class="element-head">
                  <strong>{{ element.type === 'text' ? '文字' : element.type === 'svg' ? 'SVG' : '图片' }}</strong>
                  <el-button size="small" text type="danger" @click="removeElement(element.id)">删除</el-button>
                </div>
                <el-input v-if="element.type === 'text'" v-model="element.text" size="small" />
                <div class="element-controls">
                  <label>X 位置 <el-input-number v-model="element.x" size="small" :min="0" :max="100" :controls="false" /></label>
                  <label>Y 位置 <el-input-number v-model="element.y" size="small" :min="0" :max="100" :controls="false" /></label>
                  <label>宽度 <el-input-number v-model="element.width" size="small" :min="4" :max="100" :controls="false" /></label>
                  <label>高度 <el-input-number v-model="element.height" size="small" :min="4" :max="100" :controls="false" /></label>
                  <label v-if="element.type === 'text'">字号 <el-input-number v-model="element.font_size" size="small" :min="5" :max="28" :controls="false" /></label>
                </div>
              </article>
            </div>
          </div>
        </section>
      </main>
    </div>

    <template #footer>
      <el-button :loading="saving" @click="saveCurrent">保存模板</el-button>
      <el-button :disabled="!selectedId" @click="duplicateCurrent">复制模板</el-button>
      <el-button :disabled="!selectedId" type="danger" plain @click="archiveCurrent">归档</el-button>
      <el-button :loading="exporting" @click="exportCalibration">校准页</el-button>
      <el-button type="primary" :loading="exporting" @click="exportCurrent">导出 40 格</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from '../elementApi'
import brandLogoUrl from '../../assets/brand-logo.png'
import { BRAND_SHORT, BRAND_SHOW_LOGO } from '../branding'

const props = defineProps({
  modelValue: Boolean,
  templates: { type: Array, default: () => [] },
  saving: Boolean,
  exportSheet: { type: Function, required: true },
  saveTemplate: { type: Function, required: true },
  archiveTemplate: { type: Function, required: true },
  uploadAsset: { type: Function, required: true },
  loadAsset: { type: Function, default: null }
})

const emit = defineEmits(['update:modelValue', 'refresh'])
const visible = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
const selectedId = ref('')
const quickText = ref('纸盒分类')
const assetUploading = ref(false)
const assetUploadHint = ref('')
const exporting = ref(false)
const draft = reactive(defaultDraft())
const assetPreviewUrls = reactive({})
const assetPreviewStates = reactive({})
const assetPreviewInflight = new Map()
const IMAGE_COMPRESS_MIN_BYTES = 900 * 1024
const IMAGE_MAX_SIDE = 1600
const IMAGE_QUALITY = 0.82

const printMeta = computed(() => {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `P:${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
})

watch(() => props.templates, () => {
  if (!visible.value) return
  if (selectedId.value && props.templates.some((item) => item.id === selectedId.value)) return
  if (props.templates[0]) selectTemplate(props.templates[0])
}, { deep: true })

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
      elements: [
        { id: `text-${Date.now()}`, type: 'text', text: '自定义标签', x: 18, y: 34, width: 64, height: 28, font_size: 16, color: '#111827', align: 'center' }
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
}

function cloneContent(content) {
  const parsed = JSON.parse(JSON.stringify(content || {}))
  if (!Array.isArray(parsed.elements) || !parsed.elements.length) parsed.elements = defaultDraft().content.elements
  return parsed
}

function selectTemplate(item) {
  applyDraft(item)
}

function newTemplate() {
  applyDraft(defaultDraft())
}

function replaceWithText() {
  draft.content.elements = [{ id: `text-${Date.now()}`, type: 'text', text: quickText.value || '自定义标签', x: 14, y: 32, width: 72, height: 32, font_size: 16, color: '#111827', align: 'center' }]
}

function addText() {
  draft.content.elements.push({ id: `text-${Date.now()}`, type: 'text', text: quickText.value || '文字', x: 20, y: 38, width: 60, height: 22, font_size: 13, color: '#111827', align: 'center' })
}

function removeElement(id) {
  draft.content.elements = draft.content.elements.filter((item) => item.id !== id)
  if (!draft.content.elements.length) replaceWithText()
}

async function saveCurrent() {
  const saved = await props.saveTemplate({ id: draft.id, name: draft.name || '自定义标签', content: draft.content })
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
  const copy = await props.saveTemplate({ name: `${draft.name || '自定义标签'} 副本`, content: draft.content })
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
    const blob = await props.exportSheet({ template_id: saved?.id || draft.id, content: draft.content, copies: 1, start_slot: 1, calibration })
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
    if (asset) loadAssetPreview(asset)
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
  for (const asset of draft.assets || []) {
    if (asset?.id) loadAssetPreview(asset)
  }
}

async function loadAssetPreview(asset) {
  if (!asset?.id || assetPreviewUrls[asset.id] || assetPreviewInflight.has(asset.id)) return
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
  return {
    left: `${Number(element.x || 0)}%`,
    top: `${Number(element.y || 0)}%`,
    width: `${Number(element.width || 20)}%`,
    height: `${Number(element.height || 20)}%`,
    transform: `rotate(${Number(element.rotate || 0)}deg)`
  }
}

function textStyle(element) {
  const justify = element.align === 'left' ? 'flex-start' : element.align === 'right' ? 'flex-end' : 'center'
  return {
    color: element.color || '#111827',
    fontSize: `${Number(element.font_size || 13)}px`,
    textAlign: element.align || 'center',
    justifyContent: justify
  }
}

onBeforeUnmount(cleanupPreviewUrls)
</script>

<style scoped>
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
  top: 12px;
  right: 16px;
  width: 164px;
  height: 58px;
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
  padding: 52px 18px 22px;
}

.preview-element {
  position: absolute;
  overflow: hidden;
  overflow-wrap: anywhere;
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

.missing-asset {
  display: grid;
  place-items: center;
  height: 100%;
  border: 1px dashed #cbd5e1;
  border-radius: var(--cw-radius-control);
  color: #98a2b3;
}

.editor-actions,
.element-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.element-card {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e4eaf2;
  border-radius: var(--cw-radius-card);
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
