<template>
  <el-dialog
    class="scanner-dialog"
    :model-value="modelValue"
    :title="title"
    width="min(760px, 96vw)"
    append-to-body
    destroy-on-close
    @open="handleOpen"
    @closed="handleClosed"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="scanner-layout">
      <section class="scanner-camera">
        <div class="video-shell">
          <video ref="video" muted playsinline />
          <div class="scan-overlay" aria-hidden="true">
            <span
              v-for="box in highlightBoxes"
              :key="box.key"
              class="scan-box"
              :class="box.tone"
              :style="box.style"
            >
              <b>{{ box.label }}</b>
            </span>
          </div>
        </div>
        <div class="scanner-actions">
          <el-button v-if="!scanning" type="primary" @click="startCamera">打开相机实时扫描</el-button>
          <el-button v-else @click="stopCamera">停止扫描</el-button>
          <el-button v-if="embedded" @click="requestNativeScan">使用 App 扫码</el-button>
          <el-button v-if="codes.length" @click="clearCodes">清空结果</el-button>
        </div>
        <p class="scanner-tip">{{ capabilityText }}</p>
        <p v-if="cameraError" class="scanner-error">{{ cameraError }}</p>
      </section>

      <section class="scanner-results">
        <details class="expected-picker">
          <summary>可选：指定要找的器件</summary>
          <el-select
            v-model="expectedCode"
            filterable
            remote
            clearable
            reserve-keyword
            :remote-method="searchExpected"
            :loading="candidateLoading"
            placeholder="输入器件 ID、立创 ID、型号、规格或名称"
          >
            <el-option
              v-for="candidate in candidates"
              :key="candidate.warehouse_code || candidate.id"
              :label="componentCandidateLabel(candidate)"
              :value="candidate.warehouse_code || candidate.id"
            />
          </el-select>
          <small>选中后会在画面中高亮目标；点击下方结果再进入详情。</small>
        </details>
        <el-input
          v-model="manualInput"
          type="textarea"
          :rows="2"
          placeholder="也可直接粘贴器件 ID、立创 ID 或二维码内容，每行一个"
          @change="addManualCodes"
        />
        <div class="scanner-summary">
          <strong>{{ scanSummaryText }}</strong>
          <span v-if="resolving">正在实时查找…</span>
          <span v-else>找到 {{ matchedCount }} 个器件</span>
        </div>
        <div class="scanner-code-list">
          <article
            v-for="item in results"
            :key="item.value"
            :class="`status-${item.status}`"
            @click="item.component && $emit('select', item.component)"
          >
            <div>
              <strong v-if="item.component">
                {{ componentDisplayTitle(item.component) }}
              </strong>
              <strong v-else>{{ statusLabel(item.status) }}</strong>
              <small v-if="item.component">{{ componentDisplaySubtitle(item.component) || item.value }}</small>
              <small v-else>{{ item.value }}</small>
            </div>
            <span v-if="item.component">
              {{ item.component.warehouse_code || item.component.id }}
            </span>
          </article>
          <el-empty v-if="!codes.length" description="将二维码放入取景框，可连续识别并自动去重" :image-size="56" />
        </div>
      </section>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { appBridgeContext } from '../appBridge'
import { componentCandidateLabel, componentDisplaySubtitle, componentDisplayTitle } from '../componentDisplay'

const props = defineProps({
  modelValue: Boolean,
  title: { type: String, default: '扫描二维码查找器件' },
  resolveBatch: { type: Function, required: true },
  searchCandidates: { type: Function, default: null },
  maxCodes: { type: Number, default: 200 }
})
const emit = defineEmits(['update:modelValue', 'resolved', 'select'])

const video = ref(null)
const scanning = ref(false)
const cameraError = ref('')
const codes = ref([])
const results = ref([])
const resolving = ref(false)
const manualInput = ref('')
const expectedCode = ref('')
const candidates = ref([])
const candidateLoading = ref(false)
const droppedCodeCount = ref(0)
const embedded = appBridgeContext.embedded
const multiDetectorSupported = 'BarcodeDetector' in window
const capabilityText = computed(() => (
  multiDetectorSupported
    ? '可同时识别多个二维码，并在画面中框出目标。'
    : '可连续识别二维码；不支持画面框选时仍会在列表显示结果。'
))
const matchedCount = computed(() => results.value.filter((item) => item.status === 'matched').length)
const retainedCodeLimit = computed(() => Math.max(20, Number(props.maxCodes) || 200))
const scanSummaryText = computed(() => {
  if (!droppedCodeCount.value) return `已识别 ${codes.value.length} 个二维码`
  return `已识别 ${codes.value.length + droppedCodeCount.value} 个，列表保留最近 ${codes.value.length} 个`
})
const highlightBoxes = computed(() => {
  const byValue = new Map(results.value.map((item) => [item.value, item]))
  return detectionBoxes.value.map((box) => {
    const result = byValue.get(box.value)
    const code = String(result?.component?.warehouse_code || result?.component?.id || '')
    const isExpected = result?.status === 'matched' && expectedCode.value && code === expectedCode.value
    const isMatched = result?.status === 'matched'
    if (expectedCode.value && !isExpected) return null
    if (!expectedCode.value && !isMatched) return null
    const label = isExpected ? '目标器件' : '已识别'
    return {
      ...box,
      tone: 'target',
      label,
      style: {
        left: `${box.x}%`,
        top: `${box.y}%`,
        width: `${box.width}%`,
        height: `${box.height}%`
      }
    }
  }).filter(Boolean)
})

let stream = null
let scannerControls = null
let animationFrame = 0
let lastDetectionAt = 0
let resolveTimer = 0
let resolveSequence = 0
let candidateSequence = 0
let matchedExpectedCode = ''
const detectionBoxes = ref([])

watch(expectedCode, () => {
  matchedExpectedCode = ''
  detectionBoxes.value = []
  if (codes.value.length) scheduleResolve()
})

function normalizeCode(value) {
  return String(value || '').trim()
}

function addCodes(values, options = {}) {
  const next = [...codes.value]
  let changed = false
  let dropped = 0
  for (const raw of values) {
    const value = normalizeCode(raw)
    if (!value || next.includes(value)) continue
    next.push(value)
    while (next.length > retainedCodeLimit.value) {
      next.shift()
      dropped += 1
    }
    changed = true
  }
  if (!changed) return
  codes.value = next
  if (dropped) droppedCodeCount.value += dropped
  if (options.feedback && !expectedCode.value) signalDetected()
  scheduleResolve()
}

function addManualCodes() {
  addCodes(manualInput.value.split(/\r?\n|,/))
  manualInput.value = ''
}

function clearCodes() {
  codes.value = []
  results.value = []
  detectionBoxes.value = []
  manualInput.value = ''
  matchedExpectedCode = ''
  droppedCodeCount.value = 0
}

async function searchExpected(query) {
  const value = String(query || '').trim()
  const sequence = ++candidateSequence
  if (!props.searchCandidates || !value) {
    candidates.value = []
    return
  }
  candidateLoading.value = true
  try {
    const rows = await props.searchCandidates(value)
    if (sequence === candidateSequence) candidates.value = rows || []
  } catch {
    if (sequence === candidateSequence) candidates.value = []
  } finally {
    if (sequence === candidateSequence) candidateLoading.value = false
  }
}

function scheduleResolve() {
  window.clearTimeout(resolveTimer)
  resolveTimer = window.setTimeout(resolveNow, 180)
}

async function resolveNow() {
  if (!codes.value.length) return
  const sequence = ++resolveSequence
  resolving.value = true
  try {
    const data = await props.resolveBatch([...codes.value])
    if (sequence !== resolveSequence) return
    let nextResults = data.results || []
    if (expectedCode.value) {
      nextResults = nextResults
        .map((item) => {
          const code = String(item.component?.warehouse_code || item.component?.id || '')
          if (item.status === 'matched' && code !== expectedCode.value) {
            return { ...item, status: 'expected_mismatch' }
          }
          return item
        })
        .sort((left, right) => {
          const leftMatch = left.status === 'matched' && String(left.component?.warehouse_code || left.component?.id) === expectedCode.value
          const rightMatch = right.status === 'matched' && String(right.component?.warehouse_code || right.component?.id) === expectedCode.value
          return Number(rightMatch) - Number(leftMatch)
        })
    }
    results.value = nextResults
    emit('resolved', data)
    const expectedMatch = nextResults.find((item) => (
      item.status === 'matched'
      && String(item.component?.warehouse_code || item.component?.id) === expectedCode.value
    ))
    if (expectedMatch && matchedExpectedCode !== expectedCode.value) {
      matchedExpectedCode = expectedCode.value
      signalExpectedMatch()
    }
  } catch (error) {
    if (sequence !== resolveSequence) return
    results.value = codes.value.map((value) => ({
      value,
      status: 'error',
      error: { code: error?.response?.data?.detail || 'RESOLVE_FAILED' }
    }))
  } finally {
    if (sequence === resolveSequence) resolving.value = false
  }
}

async function detectLoop(detector) {
  if (!scanning.value || !video.value) return
  const now = performance.now()
  if (now - lastDetectionAt >= 180 && video.value.readyState >= 2) {
    lastDetectionAt = now
    try {
      const detected = await detector.detect(video.value)
      rememberDetections(detected)
      addCodes(detected.map((item) => item.rawValue), { feedback: true })
    } catch {
      detectionBoxes.value = []
      // Camera frames can briefly be unavailable while WebView orientation changes.
    }
  }
  animationFrame = requestAnimationFrame(() => detectLoop(detector))
}

function rememberDetections(detected) {
  if (!Array.isArray(detected) || !video.value) {
    detectionBoxes.value = []
    return
  }
  const videoWidth = video.value.videoWidth || video.value.clientWidth || 1
  const videoHeight = video.value.videoHeight || video.value.clientHeight || 1
  const displayBox = currentVideoDisplayBox(videoWidth, videoHeight)
  const currentBoxes = []
  for (const item of detected) {
    const value = normalizeCode(item.rawValue)
    if (!value) continue
    const box = detectionBoxFromItem(item, videoWidth, videoHeight, displayBox)
    if (!box) continue
    currentBoxes.push({ ...box, value, key: `${value}-${Math.round(box.x)}-${Math.round(box.y)}` })
  }
  detectionBoxes.value = currentBoxes.slice(-retainedCodeLimit.value)
}

function detectionBoxFromItem(item, videoWidth, videoHeight, displayBox) {
  const rect = item.boundingBox
  if (rect && Number.isFinite(rect.x) && Number.isFinite(rect.y) && Number.isFinite(rect.width) && Number.isFinite(rect.height)) {
    return normalizeBox(rect.x, rect.y, rect.width, rect.height, videoWidth, videoHeight, displayBox)
  }
  const points = item.cornerPoints || []
  if (points.length) {
    const xs = points.map((point) => Number(point.x)).filter(Number.isFinite)
    const ys = points.map((point) => Number(point.y)).filter(Number.isFinite)
    if (xs.length && ys.length) {
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const minY = Math.min(...ys)
      const maxY = Math.max(...ys)
      return normalizeBox(minX, minY, maxX - minX, maxY - minY, videoWidth, videoHeight, displayBox)
    }
  }
  return null
}

function currentVideoDisplayBox(videoWidth, videoHeight) {
  const element = video.value
  const clientWidth = Math.max(1, element?.clientWidth || videoWidth || 1)
  const clientHeight = Math.max(1, element?.clientHeight || videoHeight || 1)
  const naturalRatio = videoWidth > 0 && videoHeight > 0 ? videoWidth / videoHeight : clientWidth / clientHeight
  const boxRatio = clientWidth / clientHeight
  const objectFit = element ? window.getComputedStyle(element).objectFit : 'contain'
  let contentWidth = clientWidth
  let contentHeight = clientHeight
  let offsetX = 0
  let offsetY = 0

  if (objectFit === 'cover') {
    if (boxRatio > naturalRatio) {
      contentWidth = clientWidth
      contentHeight = clientWidth / naturalRatio
      offsetY = (clientHeight - contentHeight) / 2
    } else {
      contentHeight = clientHeight
      contentWidth = clientHeight * naturalRatio
      offsetX = (clientWidth - contentWidth) / 2
    }
  } else if (boxRatio > naturalRatio) {
    contentHeight = clientHeight
    contentWidth = clientHeight * naturalRatio
    offsetX = (clientWidth - contentWidth) / 2
  } else {
    contentWidth = clientWidth
    contentHeight = clientWidth / naturalRatio
    offsetY = (clientHeight - contentHeight) / 2
  }

  return { clientWidth, clientHeight, contentWidth, contentHeight, offsetX, offsetY }
}

function normalizeBox(x, y, width, height, videoWidth, videoHeight, displayBox) {
  const box = displayBox || currentVideoDisplayBox(videoWidth, videoHeight)
  const padPx = Math.max(4, Math.min(box.contentWidth, box.contentHeight) * 0.012)
  const leftPx = box.offsetX + (x / videoWidth) * box.contentWidth
  const topPx = box.offsetY + (y / videoHeight) * box.contentHeight
  const widthPx = (width / videoWidth) * box.contentWidth
  const heightPx = (height / videoHeight) * box.contentHeight
  const left = Math.max(0, ((leftPx - padPx) / box.clientWidth) * 100)
  const top = Math.max(0, ((topPx - padPx) / box.clientHeight) * 100)
  const right = Math.min(100, ((leftPx + widthPx + padPx) / box.clientWidth) * 100)
  const bottom = Math.min(100, ((topPx + heightPx + padPx) / box.clientHeight) * 100)
  return {
    x: left,
    y: top,
    width: Math.max(2, right - left),
    height: Math.max(2, bottom - top)
  }
}

async function startCamera() {
  if (scanning.value) return
  cameraError.value = ''
  await nextTick()
  try {
    if (multiDetectorSupported) {
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: isMobileViewport() ? 960 : 1280 },
          height: { ideal: isMobileViewport() ? 1280 : 960 },
          aspectRatio: { ideal: isMobileViewport() ? 3 / 4 : 4 / 3 }
        },
        audio: false
      })
      video.value.srcObject = stream
      await video.value.play()
      scanning.value = true
      const detector = new window.BarcodeDetector({ formats: ['qr_code'] })
      detectLoop(detector)
      return
    }
    const { BrowserQRCodeReader } = await import('@zxing/browser')
    const reader = new BrowserQRCodeReader()
    scanning.value = true
    scannerControls = await reader.decodeFromVideoDevice(undefined, video.value, (result) => {
      if (result) addCodes([result.getText()], { feedback: true })
    })
  } catch (error) {
    scanning.value = false
    cameraError.value = error?.name === 'NotAllowedError'
      ? '未获得相机权限，请在浏览器或 App 中允许相机访问。'
      : '相机启动失败，可使用 App 扫码或手动粘贴二维码内容。'
  }
}

function stopCamera() {
  scanning.value = false
  cancelAnimationFrame(animationFrame)
  animationFrame = 0
  detectionBoxes.value = []
  scannerControls?.stop()
  scannerControls = null
  for (const track of stream?.getTracks?.() || []) track.stop()
  stream = null
  if (video.value) video.value.srcObject = null
}

function requestNativeScan() {
  window.ComponentWarehouseBridge?.requestScan?.({
    continuous: true,
    multiple: true,
    formats: ['qr_code']
  })
}

function isMobileViewport() {
  return window.matchMedia?.('(max-width: 680px)').matches
}

function signalDetected() {
  navigator.vibrate?.([16, 28, 18])
}

function signalExpectedMatch() {
  navigator.vibrate?.([34, 42, 58, 36, 34])
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext
    if (!AudioContext) return
    const context = new AudioContext()
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.frequency.value = 880
    gain.gain.setValueAtTime(0.06, context.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.16)
    oscillator.connect(gain)
    gain.connect(context.destination)
    oscillator.start()
    oscillator.stop(context.currentTime + 0.16)
  } catch {
    // Optional feedback can be blocked by browser or WebView policy.
  }
}

function handleNativeScan(event) {
  if (!props.modelValue) return
  const payload = event.detail || {}
  addCodes(payload.values || [payload.value], { feedback: true })
}

function handleOpen() {
  window.removeEventListener('cw-native-scan', handleNativeScan)
  window.addEventListener('cw-native-scan', handleNativeScan)
}

function handleClosed() {
  stopCamera()
  window.removeEventListener('cw-native-scan', handleNativeScan)
}

function statusLabel(status) {
  if (status === 'expected_mismatch') return '不是预期器件，继续扫描'
  if (status === 'ambiguous') return '匹配到多个器件'
  if (status === 'error') return '查找失败'
  return '未找到器件'
}

onBeforeUnmount(() => {
  window.clearTimeout(resolveTimer)
  handleClosed()
})
</script>

<style scoped>
:deep(.scanner-dialog) {
  max-height: calc(100dvh - 28px);
  display: flex;
  flex-direction: column;
}
:deep(.scanner-dialog .el-dialog__body) {
  overflow: auto;
  padding-top: 10px;
}
.scanner-layout { display: grid; grid-template-columns: minmax(260px, .9fr) minmax(320px, 1.1fr); gap: 14px; }
.scanner-camera, .scanner-results { min-width: 0; display: grid; align-content: start; gap: 10px; }
.video-shell { position: relative; overflow: hidden; border-radius: var(--cw-radius-card); background: #111827; aspect-ratio: 4 / 3; }
.scanner-camera video { width: 100%; height: 100%; background: #111827; object-fit: contain; display: block; }
.scan-overlay { position: absolute; inset: 0; pointer-events: none; }
.scan-box { position: absolute; border: 3px solid #22c55e; border-radius: var(--cw-radius-control); box-shadow: 0 0 0 4px rgba(34,197,94,.16); }
.scan-box b { position: absolute; left: 0; top: -26px; padding: 3px 8px; border-radius: 999px; background: #16a34a; color: #fff; font-size: 12px; white-space: nowrap; }
.scan-box.target { border-color: #22c55e; box-shadow: 0 0 0 4px rgba(34,197,94,.18); }
.scan-box.target b { background: #16a34a; }
.expected-picker { display: grid; gap: 7px; padding: 10px; border: 1px solid #e2e8f0; border-radius: var(--cw-radius-control); background: #f8fafc; }
.expected-picker summary { cursor: pointer; font-weight: 800; color: #344054; }
.expected-picker small { color: #667085; }
.scanner-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.scanner-actions .el-button + .el-button { margin-left: 0; }
.scanner-tip { margin: 0; padding: 8px 10px; border-radius: var(--cw-radius-control); background: #f8fafc; color: #667085; font-size: 13px; }
.scanner-summary { display: flex; justify-content: space-between; gap: 10px; color: #667085; }
.scanner-summary strong { color: #17202a; }
.scanner-code-list { max-height: min(420px, 45dvh); display: grid; gap: 8px; overflow: auto; }
.scanner-code-list article { min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 11px 12px; border: 1px solid #e5e7eb; border-radius: var(--cw-radius-control); background: #fff; }
.scanner-code-list article.status-matched { border-color: #86efac; cursor: pointer; }
.scanner-code-list article.status-not_found, .scanner-code-list article.status-ambiguous, .scanner-code-list article.status-error { border-color: #fed7aa; background: #fffaf5; }
.scanner-code-list article.status-expected_mismatch { border-color: #fca5a5; background: #fef2f2; }
.scanner-code-list article div { min-width: 0; display: grid; gap: 3px; }
.scanner-code-list article strong, .scanner-code-list article small { overflow-wrap: anywhere; }
.scanner-code-list article small { color: #667085; }
.scanner-error { margin: 0; color: #dc2626; }
@media (max-width: 680px) {
  :deep(.scanner-dialog) {
    width: min(94vw, 520px) !important;
    margin: 8px auto !important;
    max-height: calc(100dvh - 16px);
  }
  :deep(.scanner-dialog .el-dialog__header) {
    padding: 14px 16px 6px;
  }
  :deep(.scanner-dialog .el-dialog__title) {
    font-size: 19px;
  }
  :deep(.scanner-dialog .el-dialog__body) {
    padding: 8px 12px 12px;
  }
  .scanner-layout { grid-template-columns: 1fr; }
  .video-shell {
    width: min(100%, calc(56dvh * 3 / 4));
    margin-inline: auto;
    aspect-ratio: 3 / 4;
  }
  .scanner-camera video { object-fit: cover; }
  .scanner-actions :deep(.el-button) { flex: 1 1 120px; }
  .expected-picker { padding: 8px 10px; }
  .scanner-tip { font-size: 12px; padding: 7px 9px; }
  .scanner-code-list { max-height: 28dvh; }
}
</style>
