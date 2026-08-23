<template>
  <section class="assembly-workbench" :class="{ compact, 'is-public': Boolean(publicCode), 'is-workspace': workspaceMode }">
    <header class="assembly-head">
      <div>
        <span class="eyebrow">{{ workspaceMode ? 'MANUFACTURING VIEW' : 'GERBER ASSEMBLY' }}</span>
        <h2>{{ publicCode ? '装配简图' : (workspaceMode ? '制造资料与可视化装配' : '可视化装配工作台') }}</h2>
        <p v-if="!publicCode">Gerber 制造包先解析为可确认的板图与位号；启用后才与当前 PCB 版本和实物板关联。</p>
        <p v-else>脱敏只读板图，不含原始制造包、库存、成员和内部备注。</p>
      </div>
      <div v-if="!publicCode" class="assembly-head-actions">
        <el-upload
          :show-file-list="false"
          accept=".zip"
          :disabled="effectiveReadonly"
          :http-request="uploadPackage"
        >
          <el-button type="primary" :loading="uploading" :disabled="effectiveReadonly">上传 Gerber 制造包</el-button>
        </el-upload>
        <el-button :disabled="effectiveReadonly || !activeRevision" @click="boardDialog = true">批量创建实物板</el-button>
        <label v-if="activeRevision && !workspaceMode" class="public-toggle">
          <el-switch v-model="publicEnabled" :disabled="effectiveReadonly" @change="changePublicSetting" />公开装配简图
        </label>
        <el-dropdown v-if="activeRevision" trigger="click" @command="handleRevisionCommand">
          <el-button>文件版本 · V{{ activeRevision.revision_number }}</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="item in revisions" :key="item.id" :command="`open:${item.id}`">
                V{{ item.revision_number }} · {{ revisionStatus(item.status) }}
              </el-dropdown-item>
              <el-dropdown-item command="diff" divided>查看版本差异</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <el-alert
      v-if="revisionNotice"
      class="revision-notice"
      :type="revisionNotice.type"
      :closable="false"
      show-icon
    >
      <template #title>{{ revisionNotice.title }}</template>
      <div class="notice-actions">
        <span>{{ revisionNotice.detail }}</span>
        <el-button v-if="selectedRevision?.status === 'mapping_required'" size="small" @click="mappingDialog = true">人工映射</el-button>
        <el-upload
          v-if="selectedRevision && ['mapping_required', 'failed', 'review'].includes(selectedRevision.status)"
          :show-file-list="false"
          accept=".csv,.txt,.pos,.xlsx"
          :http-request="uploadSupplement"
        >
          <el-button size="small">补传 BOM/CPL</el-button>
        </el-upload>
        <el-button
          v-if="selectedRevision?.status === 'review'"
          size="small"
          type="success"
          :loading="activating"
          @click="activateRevision(false)"
        >确认并启用</el-button>
      </div>
    </el-alert>

    <div v-if="view?.revision" class="assembly-toolbar" role="toolbar" aria-label="装配工具">
      <div v-if="!effectiveReadonly" class="mode-switch">
        <button v-for="item in modes" :key="item.value" type="button" :class="[`mode-${item.value}`, { active: mode === item.value }]" @click="mode = item.value">
          <span>{{ item.icon }}</span>{{ item.label }}<kbd>{{ item.key }}</kbd>
        </button>
      </div>
      <strong v-if="!effectiveReadonly" class="current-mode">当前模式：{{ modes.find((item) => item.value === mode)?.label }}</strong>
      <el-segmented v-model="side" :options="sideOptions" @change="loadView" />
      <div class="view-actions">
        <el-button size="small" @click="fitView">适配视图</el-button>
        <el-button size="small" @click="zoomBy(-0.15)">－</el-button>
        <span>{{ Math.round(zoom * 100) }}%</span>
        <el-button size="small" @click="zoomBy(0.15)">＋</el-button>
        <el-button v-if="lastOperation && !effectiveReadonly" size="small" :loading="acting" @click="undoLast">撤销最近操作</el-button>
      </div>
    </div>

    <div v-if="lossPrompt && !effectiveReadonly" class="loss-prompt">
      <span>已记录报损；在报损模式再次点击该位号可撤销。</span>
      <el-button size="small" type="danger" plain @click="noteDialog = true">补充原因</el-button>
      <button type="button" aria-label="关闭" @click="lossPrompt = false">×</button>
    </div>

    <div v-if="view?.revision" class="assembly-layout">
      <aside class="placement-panel">
        <div class="placement-search">
          <el-input v-model="keyword" clearable placeholder="搜索位号、型号、参数、封装" />
          <el-select v-model="statusFilter" aria-label="状态筛选">
            <el-option v-for="item in filterOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </div>
        <div class="assembly-stats">
          <span><i class="dot pending"></i>待焊 {{ stats.pending || 0 }}</span>
          <span><i class="dot soldered"></i>已焊 {{ stats.soldered || 0 }}</span>
          <span><i class="dot loss"></i>报损 {{ stats.losses || 0 }}</span>
          <span><i class="dot unpositioned"></i>未定位 {{ stats.unpositioned || 0 }}</span>
        </div>
        <div v-if="view.boards?.length" class="board-picker">
          <el-select v-model="boardId" @change="loadView">
            <el-option v-for="board in view.boards" :key="board.id" :label="`${board.name}${board.status === 'archived' ? '（已归档）' : ''}`" :value="board.id" />
          </el-select>
          <el-dropdown v-if="currentBoard && !effectiveReadonly" @command="handleBoardCommand">
            <el-button text>管理</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="complete">标记完成</el-dropdown-item>
                <el-dropdown-item command="archive" divided>归档</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div ref="placementList" class="placement-list">
          <button
            v-for="item in filteredPlacements"
            :key="item.id"
            :ref="(element) => rememberRow(item.id, element)"
            type="button"
            class="placement-row"
            :class="[`status-${item.status}`, { selected: selectedId === item.id }]"
            @click="selectPlacement(item, true)"
          >
            <span class="state-icon" :title="statusLabel(item)">{{ statusIcon(item) }}</span>
            <span class="placement-copy">
              <strong>{{ item.designator }}</strong>
              <small>{{ item.model || item.value || item.component_name || '未匹配物料' }}</small>
              <em>{{ item.footprint || '无封装' }} · {{ sideLabel(item.board_side) }}</em>
            </span>
            <span class="placement-state">
              {{ statusLabel(item) }}
              <b v-if="item.loss_count">×{{ item.loss_count }}</b>
            </span>
          </button>
          <el-empty v-if="!filteredPlacements.length" description="没有符合条件的位号" :image-size="52" />
        </div>
      </aside>

      <main class="canvas-panel">
        <div class="layer-strip">
          <label v-for="role in layerRoles" :key="role.value">
            <input v-model="visibleLayers" type="checkbox" :value="role.value" />{{ role.label }}
          </label>
          <span v-if="side === 'bottom'">底面翻板视角</span>
        </div>
        <div
          ref="viewport"
          class="board-viewport"
          :class="[`mode-${mode}`, { dragging: pointer.panning }]"
          tabindex="0"
          @wheel.prevent="handleWheel"
          @pointerdown="startPan"
          @pointermove="movePointer"
          @pointerup="endPointer"
          @pointercancel="endPointer"
        >
          <div class="board-world" :style="worldStyle">
            <div class="board-surface" :style="surfaceStyle">
              <div
                v-for="layer in displayedLayers"
                :key="layer.id"
                class="gerber-layer"
                :class="`layer-${layer.role}`"
                :style="layerStyle(layer)"
                v-html="layer.svg_markup"
              ></div>
              <div v-if="!displayedLayers.some((item) => item.role === 'outline')" class="fallback-outline"></div>
              <button
                v-for="item in positionedPlacements"
                :key="item.id"
                type="button"
                class="board-part"
                :class="[`status-${item.status}`, { selected: selectedId === item.id, dense: zoom < 0.8 }]"
                :style="partStyle(item)"
                :aria-label="`${item.designator} ${statusLabel(item)}`"
                @pointerdown.stop="startPartPointer(item, $event)"
                @click.stop="activatePlacement(item)"
              >
                <span class="part-shape"></span>
                <strong>{{ item.designator }}</strong>
                <em v-if="item.loss_count">×{{ item.loss_count }}</em>
              </button>
            </div>
          </div>
          <div class="zoom-hint">拖动画布 · 滚轮/双指缩放 · V/S/L/Esc · Ctrl/Cmd+Z</div>
        </div>

        <section v-if="unpositionedPlacements.length" class="unpositioned-tray">
          <div><strong>未定位托盘</strong><span>保留库存需求；拖入或放到中心后才计入可视化进度。</span></div>
          <div v-for="item in unpositionedPlacements" :key="item.id" class="tray-item">
            <strong>{{ item.designator }}</strong>
            <span v-if="effectiveReadonly">未定位</span>
            <template v-else><button type="button" @click="placeAtCenter(item, 'top')">放到顶面</button><button type="button" @click="placeAtCenter(item, 'bottom')">放到底面</button></template>
          </div>
        </section>

        <section v-if="mode === 'calibrate' && !effectiveReadonly" class="calibration-panel">
          <strong>整体校准</strong>
          <label>X 偏移 mm<el-input-number v-model="calibration.offset_x_mm" :step="0.1" size="small" /></label>
          <label>Y 偏移 mm<el-input-number v-model="calibration.offset_y_mm" :step="0.1" size="small" /></label>
          <label>旋转 °<el-input-number v-model="calibration.rotation_deg" :step="1" size="small" /></label>
          <el-checkbox v-model="calibration.mirror">镜像</el-checkbox>
          <el-button size="small" type="primary" :loading="savingCalibration" @click="saveCalibration">保存整体校准</el-button>
          <el-button size="small" :loading="savingCalibration" @click="resetCalibration">重置整体校准</el-button>
          <label v-if="selectedPlacement?.positioned">当前位号旋转 °<el-input-number v-model="selectedPlacement.rotation_deg" :step="1" size="small" /></label>
          <el-button v-if="selectedPlacement?.positioned" size="small" @click="savePlacementRotation">保存位号旋转</el-button>
          <el-button v-if="selectedPlacement?.manually_adjusted" size="small" @click="resetPlacement">恢复当前位号解析值</el-button>
        </section>
      </main>
    </div>

    <el-empty v-else-if="!loading" description="上传 Gerber ZIP（含 BOM 与 CPL）后，在这里预览并开始装配" />
    <div v-if="loading" class="assembly-loading" v-loading="true">正在读取装配数据</div>

    <el-dialog v-model="mappingDialog" title="确认 BOM / CPL 映射" width="min(680px, 94vw)" append-to-body>
      <el-alert v-if="selectedRevision?.ai_assisted" type="warning" :closable="false" show-icon>
        以下包含 AI 映射建议，仅发送过 BOM/CPL 内容和文件名；Gerber、库存、人员及团队数据未发送。必须人工确认后才会重新解析。
      </el-alert>
      <el-form label-width="120px" class="mapping-form">
        <el-form-item label="BOM 文件"><el-select v-model="mappingForm.bom_file" filterable clearable><el-option v-for="file in tableFiles" :key="file.name" :label="file.name" :value="file.name" /></el-select></el-form-item>
        <el-form-item label="CPL 文件"><el-select v-model="mappingForm.cpl_file" filterable clearable><el-option v-for="file in tableFiles" :key="file.name" :label="file.name" :value="file.name" /></el-select></el-form-item>
        <el-form-item label="单位"><el-select v-model="mappingForm.units"><el-option label="毫米 mm" value="mm" /><el-option label="英寸 inch" value="inch" /><el-option label="密尔 mil" value="mil" /></el-select></el-form-item>
        <el-divider>列名（必须与文件表头完全一致）</el-divider>
        <div class="column-grid">
          <el-form-item v-for="field in mappingFields" :key="field.key" :label="field.label"><el-input v-model="mappingForm.columns[field.key]" /></el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="mappingDialog = false">取消</el-button><el-button type="primary" :loading="mappingSaving" @click="saveMapping">确认并重新解析</el-button></template>
    </el-dialog>

    <el-dialog v-model="diffDialog" title="制造版本差异" width="min(900px, 96vw)" append-to-body>
      <div v-if="revisionDiff" class="diff-grid">
        <article><span>新增位号</span><strong>{{ revisionDiff.summary.added }}</strong></article>
        <article><span>删除位号</span><strong>{{ revisionDiff.summary.removed }}</strong></article>
        <article><span>坐标变化</span><strong>{{ revisionDiff.summary.moved }}</strong></article>
        <article><span>物料变化</span><strong>{{ revisionDiff.summary.changed }}</strong></article>
        <article class="danger"><span>历史冲突</span><strong>{{ revisionDiff.summary.conflicts }}</strong></article>
      </div>
      <el-table v-if="revisionDiff" :data="diffRows" max-height="420">
        <el-table-column prop="type" label="类型" width="110" />
        <el-table-column prop="designator" label="位号" width="120" />
        <el-table-column prop="detail" label="详情" min-width="300" />
      </el-table>
    </el-dialog>

    <el-dialog v-model="boardDialog" title="批量创建实物板" width="460px" append-to-body>
      <el-form label-width="100px"><el-form-item label="创建数量"><el-input-number v-model="boardForm.count" :min="1" :max="100" /></el-form-item><el-form-item label="名称前缀"><el-input v-model="boardForm.name_prefix" placeholder="默认：第 N 板" /></el-form-item></el-form>
      <template #footer><el-button @click="boardDialog = false">取消</el-button><el-button type="primary" :loading="creatingBoards" @click="createBoards">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="noteDialog" title="补充报损原因" width="480px" append-to-body>
      <el-input v-model="lossNote" type="textarea" :rows="4" placeholder="例如：焊盘过热、引脚弯折、方向装反后拆除损坏" />
      <template #footer><el-button @click="noteDialog = false">取消</el-button><el-button type="primary" :loading="savingNote" @click="saveLossNote">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from '../elementApi'
import { getPublicAssemblyView } from '../../api/client'
import {
  activateFabricationRevision,
  createAssemblyBoards,
  getAssemblyView,
  getFabricationRevision,
  getFabricationRevisionDiff,
  listFabricationRevisions,
  performAssemblyAction,
  saveAssemblyCalibration,
  saveAssemblyPlacement,
  setPublicAssemblyView,
  submitFabricationMapping,
  undoAssemblyAction,
  updateAssemblyActionNote,
  updateAssemblyBoard,
  uploadFabricationRevision,
  uploadFabricationSupplement
} from '../engineeringApi'

const props = defineProps({
  projectId: { type: [Number, String], default: null },
  libraryId: { type: String, default: '' },
  publicCode: { type: String, default: '' },
  workspaceVersionId: { type: String, default: '' },
  readonly: { type: Boolean, default: false },
  compact: { type: Boolean, default: false }
})
const emit = defineEmits(['changed'])
const revisions = ref([])
const selectedRevision = ref(null)
const revisionDiff = ref(null)
const view = ref(null)
const loading = ref(false)
const uploading = ref(false)
const activating = ref(false)
const mappingSaving = ref(false)
const acting = ref(false)
const savingCalibration = ref(false)
const savingNote = ref(false)
const creatingBoards = ref(false)
const mode = ref('select')
const side = ref('top')
const boardId = ref(null)
const keyword = ref('')
const statusFilter = ref('all')
const selectedId = ref(null)
const zoom = ref(1)
const pan = reactive({ x: 0, y: 0 })
const viewportSize = reactive({ width: 900, height: 470 })
const pointer = reactive({ panning: false, placement: null, startX: 0, startY: 0, panX: 0, panY: 0, sourceX: 0, sourceY: 0, moved: false })
const touchPointers = new Map()
const pinch = { distance: 0, zoom: 1 }
const rowElements = new Map()
const viewport = ref(null)
const placementList = ref(null)
const visibleLayers = ref(['outline', 'copper', 'mask', 'silk', 'other'])
const mappingDialog = ref(false)
const diffDialog = ref(false)
const boardDialog = ref(false)
const noteDialog = ref(false)
const lossPrompt = ref(false)
const publicEnabled = ref(false)
const lossNote = ref('')
const lastOperation = ref(null)
const pollTimer = ref(null)
const calibration = reactive({ offset_x_mm: 0, offset_y_mm: 0, rotation_deg: 0, mirror: false })
const mappingForm = reactive({ bom_file: '', cpl_file: '', units: 'mm', columns: {} })
const boardForm = reactive({ count: 1, name_prefix: '' })
const modes = [
  { value: 'select', label: '选择', icon: '⌖', key: 'V' },
  { value: 'solder', label: '焊接', icon: '✓', key: 'S' },
  { value: 'loss', label: '报损', icon: '!', key: 'L' },
  { value: 'calibrate', label: '校准', icon: '↔', key: '' }
]
const sideOptions = [{ label: '顶面', value: 'top' }, { label: '底面', value: 'bottom' }]
const filterOptions = [
  { label: '全部状态', value: 'all' }, { label: '待焊', value: 'pending' }, { label: '已焊', value: 'soldered' },
  { label: '报损', value: 'loss' }, { label: 'DNP', value: 'dnp' }, { label: '未定位', value: 'unpositioned' }, { label: '风险', value: 'risk' }
]
const layerRoles = [{ value: 'outline', label: '板框' }, { value: 'copper', label: '铜层' }, { value: 'mask', label: '阻焊' }, { value: 'silk', label: '丝印' }, { value: 'other', label: '其他' }]
const mappingFields = [
  { key: 'designator', label: '位号' }, { key: 'value', label: '参数/值' }, { key: 'model', label: '型号' },
  { key: 'footprint', label: '封装' }, { key: 'x', label: '中心 X' }, { key: 'y', label: '中心 Y' },
  { key: 'rotation', label: '旋转' }, { key: 'side', label: '板面' }, { key: 'dnp', label: 'DNP' }
]

const effectiveReadonly = computed(() => props.readonly || Boolean(props.publicCode) || view.value?.can_edit === false)
const workspaceMode = computed(() => Boolean(props.workspaceVersionId))
const activeRevision = computed(() => revisions.value.find((item) => item.status === 'active') || view.value?.revision || null)
const placements = computed(() => view.value?.placements || selectedRevision.value?.placements || [])
const stats = computed(() => view.value?.stats || {
  pending: placements.value.filter((item) => item.status === 'pending').length,
  soldered: placements.value.filter((item) => item.soldered).length,
  losses: placements.value.reduce((sum, item) => sum + Number(item.loss_count || 0), 0),
  unpositioned: placements.value.filter((item) => !item.positioned).length
})
const currentBoard = computed(() => view.value?.boards?.find((item) => item.id === boardId.value) || null)
const selectedPlacement = computed(() => placements.value.find((item) => item.id === selectedId.value) || null)
const positionedPlacements = computed(() => placements.value.filter((item) => item.positioned && item.board_side === side.value))
const unpositionedPlacements = computed(() => placements.value.filter((item) => !item.positioned))
const displayedLayers = computed(() => (view.value?.layers || selectedRevision.value?.layers || []).filter((item) => item.svg_markup && visibleLayers.value.includes(item.role) && (item.side === 'both' || item.side === side.value)))
const bounds = computed(() => view.value?.revision?.bounds || selectedRevision.value?.bounds || { min_x: 0, min_y: 0, max_x: 100, max_y: 80 })
const widthMm = computed(() => Math.max(1, Number(bounds.value.max_x || 100) - Number(bounds.value.min_x || 0)))
const heightMm = computed(() => Math.max(1, Number(bounds.value.max_y || 80) - Number(bounds.value.min_y || 0)))
const boardPixelSize = computed(() => {
  const availableWidth = Math.max(120, viewportSize.width - 72)
  const availableHeight = Math.max(100, viewportSize.height - 72)
  const ratio = Math.min(availableWidth / widthMm.value, availableHeight / heightMm.value)
  return { width: widthMm.value * ratio, height: heightMm.value * ratio }
})
const worldStyle = computed(() => ({
  width: `${boardPixelSize.value.width}px`,
  height: `${boardPixelSize.value.height}px`,
  transform: `translate(-50%, -50%) translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom.value})`
}))
const surfaceMirrored = computed(() => (side.value === 'bottom') !== Boolean(calibration.mirror))
const surfaceStyle = computed(() => ({
  transform: `translate(${calibration.offset_x_mm / widthMm.value * 100}%, ${-calibration.offset_y_mm / heightMm.value * 100}%) rotate(${calibration.rotation_deg}deg) scaleX(${surfaceMirrored.value ? -1 : 1})`
}))
const filteredPlacements = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return placements.value.filter((item) => {
    if (item.board_side !== side.value && item.positioned) return false
    if (statusFilter.value === 'loss' && !item.loss_count) return false
    if (statusFilter.value !== 'all' && statusFilter.value !== 'loss' && item.status !== statusFilter.value) return false
    if (!query) return true
    return [item.designator, item.model, item.value, item.footprint, item.component_name].filter(Boolean).join(' ').toLowerCase().includes(query)
  })
})
const tableFiles = computed(() => (selectedRevision.value?.summary?.files || []).filter((item) => ['bom', 'cpl', 'other'].includes(item.role) && /\.(csv|txt|pos|xlsx)$/i.test(item.name)))
const revisionNotice = computed(() => {
  const item = selectedRevision.value
  if (!item || item.status === 'active') return null
  if (['queued', 'parsing', 'uploaded'].includes(item.status)) return { type: 'info', title: `V${item.revision_number} 正在解析`, detail: '持久化单任务队列会在服务重启后继续。' }
  if (item.status === 'mapping_required') return { type: 'warning', title: `V${item.revision_number} 需要人工映射`, detail: '请选择 BOM、CPL 与列映射后重新解析；AI 建议不会自动提交。' }
  if (item.status === 'review') return { type: 'success', title: `V${item.revision_number} 已完成预览`, detail: `${item.summary?.layer_count || 0} 个图层，${item.summary?.placement_count || 0} 个位号；确认前不改变装配或库存。` }
  if (item.status === 'failed') return { type: 'error', title: `V${item.revision_number} 解析失败`, detail: item.error_message || '请检查制造包，或补传 BOM/CPL。' }
  return { type: 'info', title: `制造版本 V${item.revision_number}`, detail: revisionStatus(item.status) }
})
const diffRows = computed(() => {
  if (!revisionDiff.value) return []
  return [
    ...revisionDiff.value.added.map((item) => ({ type: '新增', designator: item.designator, detail: `${sideLabel(item.board_side)} ${item.model || item.value || ''}` })),
    ...revisionDiff.value.removed.map((item) => ({ type: '删除', designator: item.designator, detail: '已有消耗历史时不会自动返库或删除历史' })),
    ...revisionDiff.value.moved.map((item) => ({ type: '坐标变化', designator: item.after.designator, detail: `${item.before.x_mm},${item.before.y_mm} → ${item.after.x_mm},${item.after.y_mm}` })),
    ...revisionDiff.value.changed.map((item) => ({ type: '物料变化', designator: item.after.designator, detail: `${item.before.model || item.before.value || '-'} → ${item.after.model || item.after.value || '-'}` }))
  ]
})

onMounted(() => { window.addEventListener('keydown', handleKey); window.addEventListener('resize', updateViewportSize); loadAll() })
onBeforeUnmount(() => { window.removeEventListener('keydown', handleKey); window.removeEventListener('resize', updateViewportSize); stopPolling() })
watch(() => [props.projectId, props.libraryId, props.publicCode, props.workspaceVersionId], loadAll)

function detailMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : detail?.message || error?.message || fallback
}
function revisionStatus(status) { return ({ uploaded: '已上传', queued: '排队中', parsing: '解析中', mapping_required: '待映射', review: '待确认', active: '已启用', failed: '失败', archived: '已归档' })[status] || status }
function sideLabel(value) { return value === 'bottom' ? '底面' : '顶面' }
function statusLabel(item) { return ({ pending: '待焊', soldered: '已焊', lost: '已报损', dnp: 'DNP', unpositioned: '未定位', risk: '仅 CPL 风险' })[item.status] || item.status }
function statusIcon(item) { return ({ pending: '○', soldered: '✓', lost: '!', dnp: '—', unpositioned: '◇', risk: '△' })[item.status] || '○' }
function rememberRow(id, element) { if (element) rowElements.set(id, element); else rowElements.delete(id) }
function stopPolling() { if (pollTimer.value) window.clearTimeout(pollTimer.value); pollTimer.value = null }
function schedulePolling() {
  stopPolling()
  if (selectedRevision.value && ['queued', 'parsing', 'uploaded'].includes(selectedRevision.value.status)) {
    pollTimer.value = window.setTimeout(async () => { await loadRevisions(selectedRevision.value.id); schedulePolling() }, 1500)
  }
}
async function loadAll() {
  stopPolling()
  loading.value = true
  try {
    if (props.publicCode) {
      view.value = await getPublicAssemblyView(props.publicCode, { side: side.value, board_id: boardId.value || undefined })
      boardId.value = view.value.active_board_id
      Object.assign(calibration, view.value.revision?.calibration || {})
    } else if (props.projectId) {
      await loadRevisions()
      await loadView()
    } else view.value = null
  } catch (error) {
    if (error?.response?.status !== 404) ElMessage.error(detailMessage(error, '装配工作台加载失败'))
    view.value = null
  } finally { loading.value = false; await nextTick(); updateViewportSize() }
}
async function loadRevisions(preferId = null) {
  revisions.value = await listFabricationRevisions(props.projectId, props.libraryId, props.workspaceVersionId)
  const preferred = revisions.value.find((item) => item.id === preferId)
    || revisions.value.find((item) => item.id === selectedRevision.value?.id)
    || revisions.value.find((item) => ['queued', 'parsing', 'mapping_required', 'review', 'failed'].includes(item.status))
    || revisions.value[0]
    || null
  if (preferred) {
    selectedRevision.value = await getFabricationRevision(props.projectId, preferred.id, props.libraryId, props.workspaceVersionId)
    fillMapping(selectedRevision.value.mapping)
  } else selectedRevision.value = null
  schedulePolling()
}
async function loadView() {
  if (props.publicCode) {
    view.value = await getPublicAssemblyView(props.publicCode, { side: side.value, board_id: boardId.value || undefined })
  } else if (props.projectId) {
    view.value = await getAssemblyView(props.projectId, { side: side.value, board_id: boardId.value || undefined }, props.libraryId, props.workspaceVersionId)
  }
  boardId.value = view.value?.active_board_id || boardId.value
  publicEnabled.value = Boolean(view.value?.project?.public_assembly_view_enabled)
  Object.assign(calibration, view.value?.revision?.calibration || { offset_x_mm: 0, offset_y_mm: 0, rotation_deg: 0, mirror: false })
  await nextTick(); updateViewportSize()
}
async function uploadPackage(options) {
  uploading.value = true
  try {
    const revision = await uploadFabricationRevision(props.projectId, options.file, props.libraryId, props.workspaceVersionId)
    ElMessage.success(`制造包 V${revision.revision_number} 已进入解析队列`)
    await loadRevisions(revision.id)
  } catch (error) { ElMessage.error(detailMessage(error, '制造包上传失败')) }
  finally { uploading.value = false }
}
async function uploadSupplement(options) {
  try {
    await uploadFabricationSupplement(props.projectId, selectedRevision.value.id, options.file, props.libraryId, props.workspaceVersionId)
    ElMessage.success('补传文件已加入当前版本并重新解析')
    await loadRevisions(selectedRevision.value.id)
  } catch (error) { ElMessage.error(detailMessage(error, '补传失败')) }
}
function fillMapping(mapping = {}) {
  mappingForm.bom_file = mapping.bom_file || ''
  mappingForm.cpl_file = mapping.cpl_file || ''
  mappingForm.units = mapping.units || 'mm'
  mappingForm.columns = { ...(mapping.ai_suggestion?.columns || {}), ...(mapping.columns || {}) }
}
async function saveMapping() {
  mappingSaving.value = true
  try {
    await submitFabricationMapping(props.projectId, selectedRevision.value.id, {
      bom_file: mappingForm.bom_file || null,
      cpl_file: mappingForm.cpl_file || null,
      units: mappingForm.units,
      columns: mappingForm.columns
    }, props.libraryId, props.workspaceVersionId)
    mappingDialog.value = false
    ElMessage.success('映射已确认，正在重新解析')
    await loadRevisions(selectedRevision.value.id)
  } catch (error) { ElMessage.error(detailMessage(error, '映射保存失败')) }
  finally { mappingSaving.value = false }
}
async function activateRevision(acceptConflicts) {
  activating.value = true
  try {
    await activateFabricationRevision(props.projectId, selectedRevision.value.id, acceptConflicts, props.libraryId, props.workspaceVersionId)
    ElMessage.success('制造版本已启用，装配位号已按精确板面和位号关联')
    await loadRevisions(selectedRevision.value.id)
    await loadView()
    emit('changed')
  } catch (error) {
    const detail = error?.response?.data?.detail
    if (error?.response?.status === 409 && detail?.diff && !acceptConflicts) {
      revisionDiff.value = detail.diff
      try {
        await ElMessageBox.confirm(`${detail.message}。冲突 ${detail.diff.summary.conflicts} 项，继续将保留旧历史并创建新的待焊点。`, '确认版本冲突', { type: 'warning', confirmButtonText: '保留历史并启用', cancelButtonText: '取消' })
        await activateRevision(true)
      } catch { /* user cancelled */ }
    } else ElMessage.error(detailMessage(error, '制造版本启用失败'))
  } finally { activating.value = false }
}
async function handleRevisionCommand(command) {
  if (command === 'diff') {
    const revision = selectedRevision.value || activeRevision.value
    if (!revision) return
    revisionDiff.value = await getFabricationRevisionDiff(props.projectId, revision.id, props.libraryId, props.workspaceVersionId)
    diffDialog.value = true
    return
  }
  if (command.startsWith('open:')) {
    const id = command.slice(5)
    selectedRevision.value = await getFabricationRevision(props.projectId, id, props.libraryId, props.workspaceVersionId)
    fillMapping(selectedRevision.value.mapping)
    if (selectedRevision.value.status === 'active') await loadView()
  }
}
function updateViewportSize() {
  if (!viewport.value) return
  viewportSize.width = viewport.value.clientWidth || 900
  viewportSize.height = viewport.value.clientHeight || 470
}
function fitView() { updateViewportSize(); zoom.value = 1; pan.x = 0; pan.y = 0 }
function zoomBy(delta) { zoom.value = Math.min(5, Math.max(0.25, zoom.value + delta)) }
function handleWheel(event) {
  const previous = zoom.value
  const next = Math.min(5, Math.max(0.25, previous * (event.deltaY > 0 ? 0.9 : 1.1)))
  if (!viewport.value) return zoom.value = next
  const rect = viewport.value.getBoundingClientRect()
  const x = event.clientX - rect.left - rect.width / 2
  const y = event.clientY - rect.top - rect.height / 2
  const ratio = next / previous
  pan.x = x - (x - pan.x) * ratio
  pan.y = y - (y - pan.y) * ratio
  zoom.value = next
}
function startPan(event) {
  if (event.button !== 0 || pointer.placement) return
  if (event.pointerType === 'touch') {
    touchPointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
    event.currentTarget.setPointerCapture?.(event.pointerId)
    if (touchPointers.size >= 2) {
      const [first, second] = [...touchPointers.values()]
      pinch.distance = Math.hypot(second.x - first.x, second.y - first.y) || 1
      pinch.zoom = zoom.value
      pointer.panning = false
      return
    }
  }
  pointer.panning = true
  pointer.startX = event.clientX
  pointer.startY = event.clientY
  pointer.panX = pan.x
  pointer.panY = pan.y
  event.currentTarget.setPointerCapture?.(event.pointerId)
}
function startPartPointer(item, event) {
  selectedId.value = item.id
  if (mode.value !== 'calibrate' || effectiveReadonly.value) return
  pointer.placement = item
  pointer.startX = event.clientX
  pointer.startY = event.clientY
  pointer.sourceX = Number(item.x_mm)
  pointer.sourceY = Number(item.y_mm)
  pointer.moved = false
  viewport.value?.setPointerCapture?.(event.pointerId)
}
function movePointer(event) {
  if (event.pointerType === 'touch' && touchPointers.has(event.pointerId)) {
    touchPointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
    if (touchPointers.size >= 2) {
      const [first, second] = [...touchPointers.values()]
      const distance = Math.hypot(second.x - first.x, second.y - first.y) || 1
      zoom.value = Math.min(5, Math.max(0.25, pinch.zoom * distance / Math.max(1, pinch.distance)))
      return
    }
  }
  if (pointer.placement) {
    const dx = (event.clientX - pointer.startX) / zoom.value / Math.max(1, viewport.value?.clientWidth || 1) * widthMm.value
    const dy = (event.clientY - pointer.startY) / zoom.value / Math.max(1, viewport.value?.clientHeight || 1) * heightMm.value
    pointer.placement.x_mm = pointer.sourceX + (surfaceMirrored.value ? -dx : dx)
    pointer.placement.y_mm = pointer.sourceY - dy
    pointer.moved = Math.abs(dx) + Math.abs(dy) > 0.02
  } else if (pointer.panning) {
    pan.x = pointer.panX + event.clientX - pointer.startX
    pan.y = pointer.panY + event.clientY - pointer.startY
  }
}
async function endPointer(event) {
  if (event.pointerType === 'touch') touchPointers.delete(event.pointerId)
  if (pointer.placement) {
    const item = pointer.placement
    pointer.placement = null
    viewport.value?.releasePointerCapture?.(event.pointerId)
    if (pointer.moved) {
      try {
        await saveAssemblyPlacement(props.projectId, view.value.revision.id, item.id, { x_mm: item.x_mm, y_mm: item.y_mm }, props.libraryId, props.workspaceVersionId)
        ElMessage.success(`${item.designator} 人工坐标已保存`)
      } catch (error) { ElMessage.error(detailMessage(error, '坐标保存失败')); await loadView() }
    }
  }
  pointer.panning = false
}
function calibratedPoint(item) {
  const centerX = (Number(bounds.value.min_x) + Number(bounds.value.max_x)) / 2
  const centerY = (Number(bounds.value.min_y) + Number(bounds.value.max_y)) / 2
  let x = Number(item.x_mm)
  const y = Number(item.y_mm)
  if (surfaceMirrored.value) x = centerX * 2 - x
  const dx = x - centerX
  const dy = y - centerY
  const radians = Number(calibration.rotation_deg || 0) * Math.PI / 180
  return {
    x: centerX + Math.cos(radians) * dx + Math.sin(radians) * dy + Number(calibration.offset_x_mm || 0),
    y: centerY - Math.sin(radians) * dx + Math.cos(radians) * dy + Number(calibration.offset_y_mm || 0)
  }
}
function partStyle(item) {
  const x = (Number(item.x_mm) - Number(bounds.value.min_x || 0)) / widthMm.value * 100
  const y = (Number(bounds.value.max_y || 80) - Number(item.y_mm)) / heightMm.value * 100
  const footprint = String(item.footprint || '').toLowerCase()
  const size = /qfn|bga|lga|sop|dip/.test(footprint) ? 18 : /conn|header|usb/.test(footprint) ? 24 : 12
  return { left: `${x}%`, top: `${y}%`, width: `${size}px`, height: `${Math.max(9, size * 0.62)}px`, transform: `translate(-50%, -50%) rotate(${Number(item.rotation_deg || 0)}deg)` }
}
function layerStyle(layer) {
  const layerBounds = layer.bounds || {}
  if (layerBounds.min_x == null || layerBounds.max_x == null || layerBounds.min_y == null || layerBounds.max_y == null) {
    return {}
  }
  const left = (Number(layerBounds.min_x) - Number(bounds.value.min_x || 0)) / widthMm.value * 100
  const top = (Number(bounds.value.max_y || 0) - Number(layerBounds.max_y)) / heightMm.value * 100
  const width = (Number(layerBounds.max_x) - Number(layerBounds.min_x)) / widthMm.value * 100
  const height = (Number(layerBounds.max_y) - Number(layerBounds.min_y)) / heightMm.value * 100
  return {
    inset: 'auto', left: `${left}%`, top: `${top}%`, width: `${width}%`, height: `${height}%`
  }
}
function selectPlacement(item, focusCanvas = false) {
  selectedId.value = item.id
  if (item.positioned && focusCanvas) {
    zoom.value = Math.max(zoom.value, 1.8)
    const point = calibratedPoint(item)
    pan.x = -((point.x - Number(bounds.value.min_x)) / widthMm.value - 0.5) * (viewport.value?.clientWidth || 500) * zoom.value
    pan.y = -((Number(bounds.value.max_y) - point.y) / heightMm.value - 0.5) * (viewport.value?.clientHeight || 400) * zoom.value
  }
}
async function activatePlacement(item) {
  selectPlacement(item)
  if (effectiveReadonly.value || mode.value === 'select' || mode.value === 'calibrate') {
    await nextTick(); rowElements.get(item.id)?.scrollIntoView?.({ block: 'nearest' }); return
  }
  if (!item.point_id) return ElMessage.warning(item.dnp ? 'DNP 位号不进入装配状态' : '该坐标未匹配 BOM，不会写入库存或装配状态')
  if (item.point_state === 'lost' && mode.value !== 'loss') return ElMessage.warning('该位号已报损，请切换到报损模式点击撤销')
  const action = mode.value === 'loss'
    ? (item.point_state === 'lost' ? 'undo_loss' : 'loss')
    : (item.soldered ? 'unsolder' : 'solder')
  await runAction(action, [item])
}
async function runAction(action, items) {
  if (acting.value) return
  acting.value = true
  try {
    const result = await performAssemblyAction(props.projectId, {
      board_id: boardId.value,
      action,
      point_ids: items.map((item) => item.point_id),
      versions: Object.fromEntries(items.map((item) => [item.point_id, item.state_version])),
      idempotency_key: `${Date.now()}-${crypto.randomUUID?.() || Math.random().toString(36).slice(2)}`
    }, props.libraryId, props.workspaceVersionId)
    lastOperation.value = result
    if (action === 'loss') { lossPrompt.value = true; lossNote.value = '' }
    await loadView()
    emit('changed')
  } catch (error) { ElMessage.error(detailMessage(error, '装配操作失败')) }
  finally { acting.value = false }
}
async function undoLast() {
  if (!lastOperation.value) return
  acting.value = true
  try {
    await undoAssemblyAction(props.projectId, lastOperation.value.operation_id, { idempotency_key: `undo-${lastOperation.value.operation_id}` }, props.libraryId, props.workspaceVersionId)
    lastOperation.value = null
    lossPrompt.value = false
    await loadView()
    ElMessage.success('最近操作已撤销')
    emit('changed')
  } catch (error) { ElMessage.error(detailMessage(error, '撤销失败')) }
  finally { acting.value = false }
}
async function saveLossNote() {
  if (!lossNote.value.trim() || !lastOperation.value) return ElMessage.warning('请填写报损原因')
  savingNote.value = true
  try {
    await updateAssemblyActionNote(props.projectId, lastOperation.value.operation_id, lossNote.value, props.libraryId, props.workspaceVersionId)
    noteDialog.value = false; lossPrompt.value = false; ElMessage.success('报损原因已补充')
  } catch (error) { ElMessage.error(detailMessage(error, '原因保存失败')) }
  finally { savingNote.value = false }
}
async function saveCalibration() {
  savingCalibration.value = true
  try { await saveAssemblyCalibration(props.projectId, view.value.revision.id, calibration, props.libraryId, props.workspaceVersionId); ElMessage.success('整体校准已保存') }
  catch (error) { ElMessage.error(detailMessage(error, '校准保存失败')) }
  finally { savingCalibration.value = false }
}
async function resetCalibration() {
  Object.assign(calibration, { offset_x_mm: 0, offset_y_mm: 0, rotation_deg: 0, mirror: false })
  await saveCalibration()
}
async function savePlacementRotation() {
  try {
    await saveAssemblyPlacement(props.projectId, view.value.revision.id, selectedPlacement.value.id, { rotation_deg: selectedPlacement.value.rotation_deg }, props.libraryId, props.workspaceVersionId)
    await loadView(); ElMessage.success(`${selectedPlacement.value?.designator || '位号'} 旋转已保存`)
  } catch (error) { ElMessage.error(detailMessage(error, '位号旋转保存失败')) }
}
async function placeAtCenter(item, targetSide = side.value) {
  if (effectiveReadonly.value) return
  try {
    await saveAssemblyPlacement(props.projectId, view.value.revision.id, item.id, { x_mm: Number(bounds.value.min_x) + widthMm.value / 2, y_mm: Number(bounds.value.min_y) + heightMm.value / 2, board_side: targetSide, rotation_deg: 0 }, props.libraryId, props.workspaceVersionId)
    side.value = targetSide
    await loadView(); selectedId.value = item.id; ElMessage.success(`${item.designator} 已放到板中心，请在校准模式拖动微调`)
  } catch (error) { ElMessage.error(detailMessage(error, '位号定位失败')) }
}
async function resetPlacement() {
  try { await saveAssemblyPlacement(props.projectId, view.value.revision.id, selectedPlacement.value.id, { reset: true }, props.libraryId, props.workspaceVersionId); await loadView(); ElMessage.success('已恢复解析坐标') }
  catch (error) { ElMessage.error(detailMessage(error, '恢复失败')) }
}
async function createBoards() {
  creatingBoards.value = true
  try {
    await createAssemblyBoards(props.projectId, boardForm, props.libraryId, props.workspaceVersionId)
    boardDialog.value = false; await loadView(); ElMessage.success(`已创建 ${boardForm.count} 块实物板`); emit('changed')
  } catch (error) { ElMessage.error(detailMessage(error, '实物板创建失败')) }
  finally { creatingBoards.value = false }
}
async function changePublicSetting(enabled) {
  try {
    await setPublicAssemblyView(props.projectId, enabled, props.libraryId)
    ElMessage.success(enabled ? '公开项目页已显示脱敏装配简图' : '公开装配简图已关闭')
    emit('changed')
  } catch (error) {
    publicEnabled.value = !enabled
    ElMessage.error(detailMessage(error, '公开设置保存失败'))
  }
}
async function handleBoardCommand(command) {
  try {
    if (command === 'rename') {
      const { value } = await ElMessageBox.prompt('输入新的实物板名称', '重命名', { inputValue: currentBoard.value.name })
      await updateAssemblyBoard(props.projectId, boardId.value, { name: value }, props.libraryId, props.workspaceVersionId)
    } else if (command === 'complete') await updateAssemblyBoard(props.projectId, boardId.value, { status: 'completed' }, props.libraryId, props.workspaceVersionId)
    else if (command === 'archive') {
      await ElMessageBox.confirm('归档后不再进入默认装配视图，但历史不会删除。', '归档实物板', { type: 'warning' })
      await updateAssemblyBoard(props.projectId, boardId.value, { status: 'archived' }, props.libraryId, props.workspaceVersionId)
    }
    await loadView()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(detailMessage(error, '实物板更新失败')) }
}
async function handleKey(event) {
  if (/input|textarea|select/i.test(event.target?.tagName) || event.target?.isContentEditable) return
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); await undoLast(); return }
  if (effectiveReadonly.value) return
  if (event.key.toLowerCase() === 'v') mode.value = 'select'
  else if (event.key.toLowerCase() === 's') mode.value = 'solder'
  else if (event.key.toLowerCase() === 'l') mode.value = 'loss'
  else if (event.key === 'Escape') mode.value = 'select'
}
</script>

<style scoped>
.assembly-workbench { --pending:#f59e0b; --soldered:#16a34a; --loss:#dc2626; --dnp:#64748b; --unpositioned:#8b5cf6; --selected:#2563eb; display:grid; gap:14px; min-width:0; }
.assembly-head,.assembly-toolbar,.notice-actions,.view-actions,.board-picker,.layer-strip,.calibration-panel,.loss-prompt { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.assembly-head { justify-content:space-between; }
.assembly-head h2 { margin:3px 0; font-size:22px; }
.assembly-head p { margin:0; color:var(--cw-muted,#64748b); max-width:760px; }
.assembly-head-actions { display:flex; gap:8px; flex-wrap:wrap; }
.public-toggle{display:flex;align-items:center;gap:6px;font-size:12px;color:#475569;padding:0 4px}
.revision-notice :deep(.el-alert__content) { width:100%; }
.notice-actions { justify-content:space-between; }
.notice-actions > span { flex:1; min-width:220px; }
.assembly-toolbar { justify-content:space-between; padding:10px 12px; border:1px solid var(--cw-border,#dbe3ef); border-radius:12px; background:var(--cw-panel,#fff); }
.mode-switch { display:flex; gap:4px; padding:3px; background:#eef2f7; border-radius:10px; }
.mode-switch button { border:0; background:transparent; color:#475569; padding:7px 9px; border-radius:8px; cursor:pointer; }
.mode-switch button.active { color:#fff; background:#1d4ed8; box-shadow:0 4px 12px #1d4ed833; }
.mode-switch kbd { margin-left:5px; font-size:10px; opacity:.68; }.current-mode{font-size:12px;color:#1d4ed8}
.view-actions > span { min-width:42px; text-align:center; font-size:12px; color:#64748b; }
.loss-prompt { padding:9px 12px; background:#fff1f2; border:1px solid #fecdd3; border-radius:10px; color:#9f1239; }
.loss-prompt > span { flex:1; }
.loss-prompt > button:last-child { border:0; background:none; font-size:20px; color:inherit; cursor:pointer; }
.assembly-layout { display:grid; grid-template-columns:minmax(270px, 34%) minmax(0, 1fr); min-height:610px; border:1px solid var(--cw-border,#dbe3ef); border-radius:14px; overflow:hidden; background:var(--cw-panel,#fff); }
.placement-panel { display:flex; flex-direction:column; min-width:0; border-right:1px solid var(--cw-border,#dbe3ef); }
.placement-search { display:grid; grid-template-columns:1fr 120px; gap:8px; padding:12px; border-bottom:1px solid #e5eaf1; }
.assembly-stats { display:flex; gap:8px 12px; flex-wrap:wrap; padding:9px 12px; font-size:12px; color:#475569; border-bottom:1px solid #e5eaf1; }
.dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:4px; }.dot.pending{background:var(--pending)}.dot.soldered{background:var(--soldered)}.dot.loss{background:var(--loss)}.dot.unpositioned{background:var(--unpositioned)}
.board-picker { padding:8px 12px; border-bottom:1px solid #e5eaf1; }.board-picker .el-select{flex:1}
.placement-list { flex:1; overflow:auto; max-height:510px; }
.placement-row { width:100%; display:grid; grid-template-columns:26px minmax(0,1fr) auto; gap:8px; align-items:center; border:0; border-bottom:1px solid #eef2f7; background:transparent; text-align:left; padding:10px 12px; cursor:pointer; color:inherit; }
.placement-row:hover { background:#f8fafc; }.placement-row.selected { background:#eff6ff; box-shadow:inset 3px 0 var(--selected); }
.state-icon { display:grid; place-items:center; width:24px; height:24px; border-radius:7px; color:#fff; background:var(--pending); font-weight:800; }
.status-soldered .state-icon,.board-part.status-soldered{background:var(--soldered)}.status-lost .state-icon,.board-part.status-lost{background:var(--loss)}.status-risk .state-icon,.board-part.status-risk{background:#eab308}.status-dnp .state-icon,.board-part.status-dnp{background:var(--dnp)}.status-unpositioned .state-icon{background:var(--unpositioned)}
.placement-copy { min-width:0; display:flex; flex-direction:column; }.placement-copy strong{font-size:14px}.placement-copy small,.placement-copy em{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#64748b;font-size:11px;font-style:normal}.placement-state{font-size:11px;color:#64748b;text-align:right}.placement-state b{color:var(--loss)}
.canvas-panel { min-width:0; display:flex; flex-direction:column; background:#f8fafc; }.layer-strip{min-height:42px;padding:7px 12px;border-bottom:1px solid #e5eaf1;background:#fff}.layer-strip label{font-size:12px;color:#475569}.layer-strip span{margin-left:auto;font-size:12px;color:#7c3aed}
.board-viewport { position:relative; min-height:470px; overflow:hidden; outline:none; touch-action:none; cursor:grab; background-color:#e9eef5; background-image:linear-gradient(#cbd5e144 1px,transparent 1px),linear-gradient(90deg,#cbd5e144 1px,transparent 1px);background-size:20px 20px; }
.board-viewport.dragging{cursor:grabbing}.board-viewport.mode-solder{cursor:crosshair}.board-viewport.mode-loss{cursor:not-allowed}.board-viewport.mode-calibrate{cursor:move}
.board-world { position:absolute; left:50%; top:50%; transition:transform .08s linear; transform-origin:center; }
.board-surface { position:absolute; inset:0; background:#163f34; border-radius:5px; box-shadow:0 18px 55px #0f172a44; transform-origin:center; overflow:hidden; }
.gerber-layer { position:absolute; inset:0; pointer-events:none; mix-blend-mode:screen; opacity:.72; }.gerber-layer :deep(svg){width:100%;height:100%;display:block}.layer-outline{opacity:1;filter:brightness(1.7)}.layer-copper{color:#d19b2c;opacity:.48}.layer-mask{color:#0e7669;opacity:.55}.layer-silk{color:#f8fafc;opacity:.95}.layer-other{opacity:.35}
.fallback-outline { position:absolute; inset:2px; border:2px solid #e2e8f0; border-radius:4px; pointer-events:none; }
.board-part { position:absolute; display:grid; place-items:center; min-width:10px; min-height:8px; border:1px solid #fed7aa; border-radius:2px; background:var(--pending); color:#fff; box-shadow:0 1px 4px #0005; cursor:pointer; z-index:10; padding:0; }
.board-part .part-shape{position:absolute;inset:2px;border:1px solid #fff8;border-radius:1px}.board-part strong{position:absolute;top:-16px;left:50%;transform:translateX(-50%);font-size:10px;text-shadow:0 1px 2px #000;white-space:nowrap}.board-part.dense strong{display:none}.board-part.selected{outline:3px solid #60a5fa;z-index:20}.board-part em{position:absolute;right:-8px;top:-8px;background:var(--loss);border-radius:9px;padding:1px 3px;font-size:9px;font-style:normal}
.zoom-hint{position:absolute;right:10px;bottom:8px;background:#0f172acc;color:#fff;padding:5px 8px;border-radius:7px;font-size:10px;pointer-events:none}
.unpositioned-tray{display:flex;gap:8px;align-items:center;overflow:auto;padding:10px 12px;background:#f5f3ff;border-top:1px solid #ddd6fe}.unpositioned-tray>div{display:flex;flex-direction:column;min-width:180px}.unpositioned-tray span{font-size:10px;color:#6d28d9}.unpositioned-tray .tray-item{display:flex;flex-direction:row;align-items:center;gap:5px;min-width:auto;border:1px solid #c4b5fd;background:#fff;color:#6d28d9;border-radius:8px;padding:5px 7px;white-space:nowrap}.unpositioned-tray .tray-item button{border:0;background:#ede9fe;color:#6d28d9;border-radius:6px;padding:5px 7px;cursor:pointer}
.calibration-panel{padding:10px 12px;background:#fff;border-top:1px solid #e5eaf1}.calibration-panel label{display:flex;align-items:center;gap:6px;font-size:12px}.calibration-panel :deep(.el-input-number){width:118px}
.assembly-loading{min-height:240px;display:grid;place-items:center;color:#64748b}.mapping-form .el-select{width:100%}.column-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}.diff-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px}.diff-grid article{padding:12px;background:#f8fafc;border-radius:10px;display:flex;flex-direction:column}.diff-grid strong{font-size:24px}.diff-grid .danger{background:#fff1f2;color:#be123c}
.assembly-workbench.is-workspace {
  --pending:#b56a2f; --soldered:#287264; --loss:#a44740; --dnp:#66787e; --unpositioned:#7a8751; --selected:#006b78;
  gap:16px; color:var(--pv2-ink,#102a32);
}
.is-workspace .assembly-head { align-items:flex-end; gap:18px; }
.is-workspace .assembly-head h2 { margin:5px 0 4px; color:var(--pv2-ink,#102a32); font-size:20px; }
.is-workspace .assembly-head p { color:var(--pv2-muted,#52666f); line-height:1.6; }
.is-workspace .eyebrow { color:var(--pv2-teal,#006b78); font-size:11px; font-weight:800; letter-spacing:.15em; }
.is-workspace .assembly-head-actions { justify-content:flex-end; }
.is-workspace .assembly-head-actions :deep(.el-button) { min-height:36px; border-radius:10px; }
.is-workspace .assembly-head-actions :deep(.el-button--primary) { border-color:var(--pv2-teal,#006b78); background:var(--pv2-teal,#006b78); }
.is-workspace .assembly-toolbar { border-color:var(--pv2-line,#cedadd); border-radius:14px; padding:10px 12px; background:#f7fafa; }
.is-workspace .mode-switch { background:#e4edef; }
.is-workspace .mode-switch button { color:#405861; }
.is-workspace .mode-switch button.active { background:var(--pv2-teal,#006b78); box-shadow:0 5px 14px rgba(0,107,120,.18); }
.is-workspace .current-mode { color:var(--pv2-teal,#006b78); }
.is-workspace .assembly-layout { min-height:600px; border-color:var(--pv2-line,#cedadd); border-radius:18px; background:#fff; box-shadow:0 12px 30px rgba(23,55,63,.07); }
.is-workspace .placement-panel { border-right-color:#d8e3e5; background:#fbfdfd; }
.is-workspace .placement-search,.is-workspace .assembly-stats,.is-workspace .board-picker { border-bottom-color:#dce6e8; }
.is-workspace .placement-row { border-bottom-color:#e3eaec; }
.is-workspace .placement-row:hover { background:#eef5f5; }
.is-workspace .placement-row.selected { background:#e2f0f1; box-shadow:inset 3px 0 var(--pv2-teal,#006b78); }
.is-workspace .placement-copy small,.is-workspace .placement-copy em,.is-workspace .placement-state,.is-workspace .assembly-stats { color:var(--pv2-muted,#52666f); }
.is-workspace .canvas-panel { background:#eaf0f1; }
.is-workspace .layer-strip { border-bottom-color:#d7e2e4; background:#f8fbfb; }
.is-workspace .board-viewport { background-color:#dfe8e9; background-image:linear-gradient(rgba(64,88,97,.10) 1px,transparent 1px),linear-gradient(90deg,rgba(64,88,97,.10) 1px,transparent 1px); }
.is-workspace .board-surface { background:#174b40; box-shadow:0 20px 52px rgba(16,42,50,.30), inset 0 0 0 1px rgba(255,255,255,.16); }
.is-workspace .loss-prompt { border-color:#e0b5ae; color:#7d332e; background:#f8e9e6; }
.is-workspace .unpositioned-tray { border-top-color:#d9e2cf; color:#56602f; background:#f1f4e7; }
.is-workspace .unpositioned-tray span { color:#667234; }
.is-workspace .unpositioned-tray .tray-item { border-color:#bdc99a; color:#56602f; }
.is-workspace .unpositioned-tray .tray-item button { color:#56602f; background:#e7edd2; }
@media (max-width: 980px){.assembly-layout{grid-template-columns:minmax(240px,40%) minmax(0,1fr)}.board-viewport{min-height:430px}.placement-list{max-height:480px}.assembly-head{align-items:flex-start}.diff-grid{grid-template-columns:repeat(3,1fr)}}
@media (max-width: 720px){.assembly-head-actions,.mode-switch{width:100%}.mode-switch button{flex:1}.mode-switch .mode-calibrate,.calibration-panel{display:none}.assembly-layout{display:flex;flex-direction:column}.placement-panel{border-right:0;border-bottom:1px solid #dbe3ef}.placement-list{max-height:220px}.board-viewport{min-height:390px}.placement-search{grid-template-columns:1fr}.assembly-toolbar{align-items:flex-start}.column-grid{grid-template-columns:1fr}.diff-grid{grid-template-columns:repeat(2,1fr)}.layer-strip span{width:100%;margin-left:0}.zoom-hint{display:none}}
</style>
