<template>
  <section class="team-page component-page">
    <div class="team-page-head">
      <div>
        <h1>{{ library?.name || '元器件库' }}</h1>
        <p>团队器件实时读取来源成员的个人版库存，并共享位置、标记与备注。</p>
      </div>
      <div class="team-toolbar">
        <el-button :icon="Camera" @click="openScanner()">扫码查找</el-button>
        <el-button @click="exportTeamInventory">导出库存 XLSX</el-button>
        <el-button v-if="isCaptain" @click="exportAllTeamLabels">导出全库二维码</el-button>
        <el-button @click="openCustomLabelDialog">自定义标签</el-button>
        <el-button @click="router.push('/')">切换团队器件库</el-button>
        <el-button type="primary" :disabled="readonly" @click="openAddDialog">添加器件</el-button>
      </div>
    </div>

    <el-alert v-if="readonly" class="readonly-banner" type="warning" :closable="false" show-icon title="当前只读：可搜索、筛选和查看详情，不能修改数据。" />

    <div class="team-panel team-toolbar filter-panel">
      <el-input v-model="keyword" clearable placeholder="搜索器件 ID、名称、型号、规格、立创 ID、位置或标签" />
      <el-select v-model="categoryFilter" clearable placeholder="分类">
        <el-option v-for="name in categoryOptions" :key="name" :label="name" :value="name" />
      </el-select>
      <el-select v-model="syncFilter" clearable placeholder="同步状态">
        <el-option label="实时库存" value="live" />
        <el-option label="离队快照" value="frozen" />
      </el-select>
      <el-select v-model="markerCategoryFilter" clearable placeholder="标记分类">
        <el-option v-for="name in markerCategoryOptions" :key="name" :label="name" :value="name" />
      </el-select>
      <el-select v-model="markerColorFilter" clearable placeholder="标记颜色">
        <el-option v-for="color in markerColors" :key="color.value" :label="color.label" :value="color.value">
          <span class="marker-color-option"><i :style="{ background: color.value }"></i>{{ color.label }}</span>
        </el-option>
      </el-select>
      <el-select v-model="flaggedFilter" clearable placeholder="旗标">
        <el-option label="仅旗标器件" value="yes" />
        <el-option label="无旗标器件" value="no" />
      </el-select>
      <el-button @click="reloadFromFirstPage">刷新</el-button>
      <el-button @click="aiDialog = true">AI 查询</el-button>
      <span class="muted">{{ resultTotal }} 种 · 合计 {{ totalQuantity }}</span>
    </div>

    <div v-loading="loading" class="category-stack">
      <div v-if="loading && !items.length" class="component-skeleton-grid">
        <el-skeleton v-for="index in 8" :key="index" animated>
          <template #template><el-skeleton-item variant="rect" class="component-skeleton" /></template>
        </el-skeleton>
      </div>
      <section v-for="group in groupedItems" :key="group.name" class="category-block">
        <button class="category-head" type="button" @click="toggleCategory(group.name)">
          <span class="category-dot" :style="{ background: group.color }"></span>
          <strong>{{ group.name }}</strong>
          <span>{{ group.items.length }} 个</span>
        </button>
        <div v-show="!collapsedCategories.has(group.name)" class="component-grid">
          <inventory-component-card v-for="row in group.items" :key="row.id" :item="row" @open="openDetail(row)">
            <template #badges>
              <span
                v-for="marker in (row.markers || []).slice(0, 3)"
                :key="marker.id"
                class="marker-badge"
                :style="{ '--marker-color': marker.color }"
              >{{ marker.flagged ? '⚑ ' : '' }}{{ marker.category }}</span>
            </template>
            <template #actions>
              <el-button size="small" plain @click="openDetail(row)">详情</el-button>
              <el-button v-if="row.warehouse_code" size="small" text @click="copyText(row.warehouse_code, '器件 ID')">复制器件 ID</el-button>
              <el-button v-if="row.lcsc_number" size="small" text @click="copyText(row.lcsc_number, '立创 ID')">复制立创 ID</el-button>
            </template>
            <template #stock-action>
              <el-button
                size="small"
                type="primary"
                plain
                title="按先进先出从可用库存扣减 1 个"
                :loading="quickConsumeIds.has(row.id)"
                :disabled="readonly || !row.can_edit_quantity || Number(row.available_quantity || 0) <= 0"
                @click.stop="quickConsume(row)"
              >领用 1 个</el-button>
            </template>
          </inventory-component-card>
        </div>
      </section>
      <div ref="autoLoadSentinel" class="auto-load-sentinel" aria-live="polite">
        <span v-if="loading && items.length">正在加载更多…</span>
        <el-button v-else-if="autoLoadError && categoryPaging.hasMore" class="load-more" @click="loadMoreCategories">重新加载</el-button>
        <span v-else-if="categoryPaging.hasMore">继续下滑自动加载</span>
        <span v-else-if="items.length">已加载全部类别</span>
      </div>
      <div v-if="!loading && !filteredItems.length" class="team-panel empty-state">没有符合条件的物料</div>
    </div>

    <el-drawer
      v-model="detailVisible"
      class="component-detail-drawer"
      modal-class="component-detail-overlay"
      append-to-body
      destroy-on-close
      :title="selected?.warehouse_code || '元器件详情'"
      size="min(1040px, calc(100vw - 40px))"
      @opened="resetDetailDrawerScroll"
    >
      <inventory-component-detail
        v-if="selected"
        :item="selected"
        :usage-records="usageRecords"
        :show-usage="selected.can_view_usage"
        :usage-loading="usageLoading"
        :eda-bindings="edaBindings"
        :supplier-parts="supplierParts"
        :inventory-lots="inventoryLots"
        :eda-loading="edaLoading"
        :engineering-enabled="FEATURE_EDA_ENABLED"
        :lots-loading="lotsLoading"
        :lot-saving="lotSaving"
        :lot-consume-ids="lotConsumeIds"
        :can-edit-inventory-lots="!readonly && selected.can_edit_quantity"
        :ai-ask-loading="componentAiAskLoading"
        :ai-answer="componentAiAnswer"
        @load-usage="loadUsage"
        @load-lots="loadLots"
        @add-lot="addInventoryLot"
        @consume-lot="consumeInventoryLot"
        @delete-lot="deleteInventoryLot"
        @ask-ai="askSelectedComponentAi"
      >
        <template #actions>
          <div class="detail-actions">
            <el-button v-if="selected.warehouse_code" plain @click="copyText(selected.warehouse_code, '器件 ID')">复制器件 ID</el-button>
            <el-button v-if="selected.lcsc_number" plain @click="copyText(selected.lcsc_number, '立创 ID')">复制立创 ID</el-button>
            <el-button plain :icon="Camera" @click="openScannerForSelected">扫码定位此器件</el-button>
            <el-button v-if="selected.buy_url" @click="openUrl(selected.buy_url)">立创商品</el-button>
            <el-button v-if="selected.datasheet_url" @click="openUrl(selected.datasheet_url)">数据手册</el-button>
            <el-dropdown trigger="click" @command="handleDetailCommand">
              <el-button circle :icon="MoreFilled" aria-label="更多操作" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="quantity" :disabled="readonly || !selected.can_edit_quantity">修改器件数量</el-dropdown-item>
                  <el-dropdown-item command="team-info" :disabled="readonly">编辑团队信息</el-dropdown-item>
                  <el-dropdown-item v-if="selected.sync_status === 'frozen' && isCaptain" command="rebind" :disabled="readonly">重新绑定</el-dropdown-item>
                  <el-dropdown-item command="remove" divided :disabled="readonly">从团队器件库移除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </template>
        <el-form v-if="teamEditVisible" class="team-edit" label-position="top">
          <el-form-item label="团队位置"><el-input v-model="teamForm.location" /></el-form-item>
          <el-form-item label="团队标签"><el-input v-model="teamForm.tags" /></el-form-item>
          <el-form-item label="团队备注"><el-input v-model="teamForm.remark" type="textarea" :rows="3" /></el-form-item>
          <el-button type="primary" :disabled="readonly" @click="saveTeamMeta">保存团队信息</el-button>
        </el-form>
        <section class="marker-manager">
          <div class="marker-head"><h3>团队标记</h3><el-button size="small" :disabled="readonly" @click="openMarkerEditor()">新增标记</el-button></div>
          <div v-if="selected.markers?.length" class="marker-list">
            <article v-for="marker in selected.markers" :key="marker.id" :style="{ '--marker-color': marker.color }">
              <div><strong>{{ marker.flagged ? '⚑ ' : '' }}{{ marker.category }}</strong><small>{{ marker.creator_name }}</small></div>
              <p>{{ marker.note || '无备注' }}</p>
              <div>
                <el-button size="small" text @click="openMarkerEditor(marker)">编辑</el-button>
                <el-button size="small" text type="danger" @click="removeMarker(marker)">删除</el-button>
              </div>
            </article>
          </div>
          <el-empty v-else description="暂无团队标记" :image-size="48" />
        </section>
        <el-alert v-if="selected.sync_status === 'frozen'" type="warning" :closable="false" show-icon title="来源成员已离队，当前显示离队时快照；队长可重新绑定到自己的个人版器件。" />
      </inventory-component-detail>
    </el-drawer>

    <el-dialog v-model="quantityDialog" title="修改器件数量" width="min(460px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="库存总量"><el-input-number v-model="quantityForm.quantity" :min="0" /></el-form-item>
        <el-form-item label="变更备注"><el-input v-model="quantityForm.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button type="primary" :loading="quantitySaving" @click="saveQuantity">保存并同步</el-button></template>
    </el-dialog>

    <el-dialog v-model="markerDialog" :title="markerForm.id ? '编辑标记' : '新增标记'" width="min(500px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="分类" required><el-input v-model="markerForm.category" maxlength="80" placeholder="例如：待采购、需复核、常用" /></el-form-item>
        <el-form-item label="颜色">
          <div class="marker-color-presets" role="radiogroup" aria-label="标记颜色">
            <button
              v-for="color in markerColors"
              :key="color.value"
              type="button"
              class="marker-color-button"
              :class="{ selected: markerForm.color === color.value }"
              :style="{ '--preset-color': color.value }"
              role="radio"
              :aria-checked="markerForm.color === color.value"
              :aria-label="color.label"
              @click="markerForm.color = color.value"
            >
              <span></span>{{ color.label }}
            </button>
          </div>
        </el-form-item>
        <el-form-item><el-checkbox v-model="markerForm.flagged">显示旗标</el-checkbox></el-form-item>
        <el-form-item label="备注"><el-input v-model="markerForm.note" type="textarea" :rows="3" maxlength="1000" /></el-form-item>
      </el-form>
      <template #footer><el-button type="primary" :loading="markerSaving" @click="saveMarker">保存标记</el-button></template>
    </el-dialog>

    <el-dialog v-model="addDialog" title="添加团队物料" width="min(920px, 96vw)" @closed="stopScanner">
      <el-tabs v-model="addTab">
        <el-tab-pane label="从我的个人版选择" name="personal">
          <div class="team-toolbar">
            <el-input v-model="cwKeyword" placeholder="器件 ID、名称、型号或立创 ID" @keyup.enter="searchPersonal" />
            <el-button :loading="personalLoading" @click="searchPersonal">搜索</el-button>
          </div>
          <el-table :data="cwOptions" @selection-change="personalSelection = $event">
            <el-table-column type="selection" width="48" />
            <el-table-column prop="warehouse_code" label="器件 ID" width="150" />
            <el-table-column label="物料" min-width="240">
              <template #default="{ row }"><strong>{{ componentDisplayTitle(row) }}</strong><div class="muted">{{ componentDisplaySubtitle(row) || row.lcsc_number || '非立创物料' }}</div></template>
            </el-table-column>
            <el-table-column prop="quantity" label="总量" width="80" />
            <el-table-column prop="available_quantity" label="可用" width="80" />
          </el-table>
          <el-button type="primary" class="dialog-action" :disabled="!personalSelection.length" @click="submitPersonal">加入所选物料</el-button>
        </el-tab-pane>

        <el-tab-pane label="Excel / CSV 导入" name="import">
          <el-alert type="info" :closable="false" title="表格中的陌生器件会先创建到你的个人版，再加入团队器件库；已有立创 ID 只建立实时绑定。" />
          <div class="import-actions">
            <a :href="templateUrl" target="_blank">下载 CSV 模板</a>
            <el-upload :auto-upload="false" :limit="1" accept=".csv,.xlsx" :on-change="file => importFile = file.raw">
              <el-button>选择表格</el-button>
            </el-upload>
            <el-button type="primary" :disabled="!importFile" @click="submitImport">开始导入</el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="扫描 / 输入器件 ID" name="scan">
          <div class="scan-grid">
            <div>
              <video ref="video" muted playsinline />
              <el-button v-if="!scanning" @click="startScanner">打开相机扫码</el-button>
              <el-button v-else @click="stopScanner">关闭相机</el-button>
            </div>
            <div>
              <el-input v-model="scanCode" placeholder="输入器件 ID、立创 ID 或二维码内容" @keyup.enter="resolveCode" />
              <el-button @click="resolveCode">查找</el-button>
              <el-card v-if="scanResult" shadow="never">
                <strong>{{ componentDisplayTitle(scanResult) }}</strong>
                <p class="muted">{{ scanResult.warehouse_code }} · 可用 {{ scanResult.available_quantity }}</p>
                <el-button type="primary" @click="addScanned">加入团队器件库</el-button>
              </el-card>
              <p class="muted">相机不可用时可直接粘贴二维码内容或手动输入。</p>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="手动新增到个人版" name="manual">
          <el-form label-position="top">
            <lcsc-paste-import
              ref="lcscImporter"
              :lookup="previewLcscComponent"
              existing-action-label="复用并加入团队库"
              @draft="applyTeamLcscDraft"
              @existing="reuseExistingLcscComponent"
            />
            <section class="quick-create-card">
              <strong>AI 快速新增</strong>
              <p>手机上可先输入一句大概信息，AI 自动整理名称、型号、分类、标签和备注。保存前仍可手动修改。</p>
              <el-input
                v-model="manualQuickPrompt"
                type="textarea"
                :rows="2"
                maxlength="300"
                show-word-limit
                placeholder="例如：CH340C SOP-16 5个，或 0805 100nF 电容 50个"
              />
              <div class="quick-create-actions">
                <el-button type="primary" plain :loading="manualAiLoading" @click="completeManualWithAi">AI 补齐草稿</el-button>
                <span v-if="manualAiDraft" class="ai-confidence">置信度：{{ confidenceLabel(manualAiDraft.confidence) }}</span>
              </div>
            </section>
            <p class="required-hint"><span>*</span> 必填：名称或型号、库存数量；分类和封装由 AI 建议但保存前请核对。</p>
            <div class="form-grid">
              <el-form-item label="名称" required><el-input v-model="manualForm.name" placeholder="例如 CH340C / 10kΩ 电阻" /></el-form-item>
              <el-form-item label="型号"><el-input v-model="manualForm.model" /></el-form-item>
              <el-form-item label="厂商"><el-input v-model="manualForm.manufacturer" /></el-form-item>
              <el-form-item label="立创 ID"><el-input v-model="manualForm.lcsc_number" /></el-form-item>
              <el-form-item label="库存数量" required><el-input-number v-model="manualForm.quantity" :min="0" /></el-form-item>
              <el-form-item label="位置"><el-input v-model="manualForm.location" /></el-form-item>
              <el-form-item label="分类"><el-input v-model="manualForm.category" /></el-form-item>
              <el-form-item label="封装"><el-input v-model="manualForm.package" placeholder="0805 / SOT-223 / SOP-16" /></el-form-item>
              <el-form-item label="参数"><el-input v-model="manualForm.parameters" /></el-form-item>
              <el-form-item label="描述"><el-input v-model="manualForm.description" type="textarea" :rows="2" /></el-form-item>
              <el-form-item label="标签"><el-input v-model="manualForm.tags" /></el-form-item>
              <el-form-item label="数据手册"><el-input v-model="manualForm.datasheet_url" /></el-form-item>
              <el-form-item label="立创商品"><el-input v-model="manualForm.buy_url" /></el-form-item>
              <el-form-item label="备注"><el-input v-model="manualForm.remark" type="textarea" :rows="3" /></el-form-item>
            </div>
          </el-form>
          <el-button type="primary" class="dialog-action" @click="submitManual">创建并加入团队器件库</el-button>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <el-dialog v-model="rebindDialog" title="重新绑定到我的个人版" width="min(760px, 94vw)">
      <div class="team-toolbar">
        <el-input v-model="rebindKeyword" placeholder="搜索器件 ID、名称、型号或立创 ID" @keyup.enter="searchRebind" />
        <el-button @click="searchRebind">搜索</el-button>
      </div>
      <el-table :data="rebindOptions">
        <el-table-column prop="warehouse_code" label="器件 ID" width="150" />
        <el-table-column label="候选物料" min-width="260">
          <template #default="{ row }"><strong>{{ componentDisplayTitle(row) }}</strong><div class="muted">{{ componentDisplaySubtitle(row) || `可用 ${row.available_quantity}` }}</div></template>
        </el-table-column>
        <el-table-column width="100"><template #default="{ row }"><el-button type="primary" link @click="confirmRebind(row)">绑定</el-button></template></el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="aiDialog" title="团队版 AI 查询" width="min(760px, 94vw)">
      <el-select v-model="aiForm.query_type" style="width: 100%">
        <el-option label="口语化找料" value="find_components" />
        <el-option label="个人版人工核对候选" value="match_cw" />
        <el-option label="库内替代建议" value="alternatives" />
        <el-option label="PCB 推荐" value="recommend_pcbs" />
      </el-select>
      <el-input v-model="aiForm.prompt" type="textarea" :rows="4" placeholder="例如：找一个能接 3.3V MCU 的低功耗运放" />
      <el-button type="primary" :loading="aiLoading" :disabled="readonly" @click="askAi">手动查询</el-button>
      <el-card v-if="aiResult" shadow="never" class="ai-result">
        <strong>{{ aiResult.answer }}</strong>
        <ul><li v-for="item in aiResult.component_matches || []" :key="`${item.id}-${item.cw_component_id}`">{{ item.reason }} {{ item.warning }}</li></ul>
        <ul><li v-for="item in aiResult.pcb_matches || []" :key="item.id">{{ item.reason }} {{ item.warning }}</li></ul>
        <p class="muted">AI 只提供排序和解释，不会自动修改数据。</p>
      </el-card>
    </el-dialog>

    <multi-qr-scanner
      v-model="scannerVisible"
      title="扫描二维码查找团队器件"
      :resolve-batch="resolveCurrentTeamScanBatch"
      :search-candidates="searchCurrentTeamScanCandidates"
      :initial-expected-code="scannerTarget?.warehouse_code || scannerTarget?.id || ''"
      :initial-expected-label="scannerTarget ? componentDisplayTitle(scannerTarget) : ''"
      @select="openScannedComponent"
    />
    <label-export-dialog
      v-model="labelDialog"
      :loading="labelExporting"
      show-scope
      :scope-options="teamLabelScopeOptions"
      :category-options="categoryOptions"
      :custom-label-templates="customLabels"
      @export="runTeamLabelExport"
    />
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/elementApi'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { Camera, MoreFilled } from '@element-plus/icons-vue'
import InventoryComponentCard from '../../components/inventory/InventoryComponentCard.vue'
import InventoryComponentDetail from '../../components/inventory/InventoryComponentDetail.vue'
import MultiQrScanner from '../../shared/components/MultiQrScanner.vue'
import { applyInventoryLotConsumption } from '../../shared/inventoryLotState'
import LabelExportDialog from '../../shared/components/LabelExportDialog.vue'
import LcscPasteImport from '../../shared/components/LcscPasteImport.vue'
import {
  bulkAddComponents,
  askTeamComponentAi,
  aiComponentInfo,
  teamImportTemplateUrl,
  createTeamComponentLot,
  deleteTeamComponentLot,
  createComponentMarker,
  createComponent,
  deleteComponent,
  deleteComponentMarker,
  decrementTeamComponentQuantity,
  exportTeamComponentLabels,
  exportTeamComponentInventory,
  getLibrary,
  getTeamScannedComponent,
  importComponents,
  previewLcscComponent,
  listTeamCustomLabels,
  listTeamComponentLots,
  listComponents,
  listTeamComponentUsage,
  recordTeamUsageEvent,
  rebindComponent,
  resolveCwCode,
  resolveTeamScanBatch,
  runTeamAi,
  searchCwComponents,
  searchTeamScanCandidates,
  updateComponent,
  updateComponentMarker,
  updateComponentQuantity
} from '../api'
import { clearLibrarySnapshots, readSnapshot, writeSnapshot } from '../cache'
import { teamState } from '../store'
import {
  DEFAULT_TEAM_MARKER_COLOR,
  normalizeTeamMarkerColor,
  TEAM_MARKER_COLORS
} from '../../shared/markerColors'
import { componentDisplaySubtitle, componentDisplayTitle } from '../../shared/componentDisplay'
import { listEdaBindings, listSupplierParts } from '../../shared/engineeringApi'
import { trackUsage } from '../../shared/usageTracker'
import { FEATURE_EDA_ENABLED } from '../../shared/features'

const emptyForm = () => ({
  name: '',
  model: '',
  manufacturer: '',
  description: '',
  lcsc_number: '',
  quantity: 0,
  location: '',
  category: '',
  package: '',
  parameters: '',
  tags: '',
  remark: '',
  datasheet_url: '',
  buy_url: '',
  source: '',
  source_title: ''
})
const teamLabelScopeOptions = [
  { label: '指定日期', value: 'imported' },
  { label: '全部库存', value: 'all' }
]
const route = useRoute()
const router = useRouter()
const libraryId = route.params.libraryId
const library = ref(null)
const items = ref([])
const loading = ref(false)
const autoLoadSentinel = ref(null)
const autoLoadError = ref(false)
let autoLoadObserver = null
const keyword = ref('')
const categoryFilter = ref('')
const syncFilter = ref('')
const markerCategoryFilter = ref('')
const markerColorFilter = ref('')
const flaggedFilter = ref('')
const collapsedCategories = ref(new Set())
const addDialog = ref(false)
const addTab = ref('personal')
const cwKeyword = ref('')
const cwOptions = ref([])
const personalSelection = ref([])
const personalLoading = ref(false)
const importFile = ref(null)
const templateUrl = teamImportTemplateUrl
const manualForm = reactive(emptyForm())
const manualQuickPrompt = ref('')
const manualAiLoading = ref(false)
const manualAiDraft = ref(null)
const lcscImporter = ref(null)
const lastTeamLcscDraft = ref({})
const video = ref(null)
const scanning = ref(false)
const scanCode = ref('')
const scanResult = ref(null)
const detailVisible = ref(false)
const selected = ref(null)
const usageRecords = ref([])
const usageLoading = ref(false)
const edaBindings = ref([])
const supplierParts = ref([])
const edaLoading = ref(false)
const inventoryLots = ref([])
const lotsLoading = ref(false)
const lotSaving = ref(false)
const lotConsumeIds = reactive(new Set())
const quickConsumeIds = reactive(new Set())
const componentAiAskLoading = ref(false)
const componentAiAnswer = ref(null)
const teamEditVisible = ref(false)
const teamForm = reactive({ location: '', tags: '', remark: '' })
const rebindDialog = ref(false)
const rebindKeyword = ref('')
const rebindOptions = ref([])
const aiDialog = ref(false)
const aiLoading = ref(false)
const aiForm = reactive({ query_type: 'find_components', prompt: '', force: false })
const aiResult = ref(null)
const quantityDialog = ref(false)
const quantitySaving = ref(false)
const quantityForm = reactive({ quantity: 0, remark: '' })
const markerDialog = ref(false)
const markerSaving = ref(false)
const scannerVisible = ref(false)
const scannerTarget = ref(null)
const labelDialog = ref(false)
const labelExporting = ref(false)
const customLabels = ref([])
const markerColors = TEAM_MARKER_COLORS
const markerForm = reactive({ id: '', category: '', color: DEFAULT_TEAM_MARKER_COLOR, flagged: false, note: '' })
const categoryOptions = ref([])
const markerCategoryOptions = ref([])
const resultTotal = ref(0)
const totalQuantity = ref(0)
const categoryPaging = reactive({ page: 1, pageSize: 3, categoryTotal: 0, hasMore: false })
let scannerControls = null
let loadController = null
let loadSequence = 0
let filterTimer = 0

const readonly = computed(() => teamState.offlineReadonly || library.value?.role === 'viewer')
const isCaptain = computed(() => library.value?.role === 'captain')
const filteredItems = computed(() => items.value)
const groupedItems = computed(() => {
  const groups = new Map()
  for (const item of filteredItems.value) {
    const name = item.category?.name || '未分类'
    if (!groups.has(name)) groups.set(name, { name, color: item.category?.color || '#eef2f7', items: [] })
    groups.get(name).items.push(item)
  }
  return [...groups.values()]
})

function componentRequestParams() {
  return {
    page: categoryPaging.page,
    page_size: categoryPaging.pageSize,
    keyword: keyword.value.trim() || undefined,
    category: categoryFilter.value || undefined,
    linked: syncFilter.value ? syncFilter.value === 'live' : undefined,
    marker_category: markerCategoryFilter.value || undefined,
    marker_color: markerColorFilter.value || undefined,
    flagged: flaggedFilter.value ? flaggedFilter.value === 'yes' : undefined
  }
}

function applyComponentResponse(data, append = false) {
  const nextItems = data.items || []
  if (append) {
    const itemsById = new Map(items.value.map((item) => [item.id, item]))
    for (const item of nextItems) itemsById.set(item.id, item)
    items.value = [...itemsById.values()]
  } else {
    items.value = nextItems
  }
  resultTotal.value = Number(data.total || 0)
  totalQuantity.value = Number(data.total_quantity || 0)
  categoryPaging.categoryTotal = Number(data.category_total || 0)
  categoryPaging.hasMore = Boolean(data.has_more)
  const options = data.filter_options || {}
  categoryOptions.value = options.categories || categoryOptions.value
  markerCategoryOptions.value = options.marker_categories || markerCategoryOptions.value
}

async function load({ append = false } = {}) {
  const sequence = ++loadSequence
  loadController?.abort()
  loadController = new AbortController()
  if (!append) categoryPaging.page = 1
  loading.value = true
  try {
    const [libraryData, componentData] = await Promise.all([
      library.value ? Promise.resolve(library.value) : getLibrary(libraryId),
      listComponents(libraryId, componentRequestParams(), { signal: loadController.signal })
    ])
    if (sequence !== loadSequence) return
    library.value = libraryData
    teamState.activeLibrary = libraryData
    applyComponentResponse(componentData, append)
    if (!append) {
      void writeSnapshot(teamState.user?.id, libraryId, 'components', {
        library: libraryData,
        response: componentData
      })
    }
    const requestedId = String(route.query.component || '')
    if (requestedId && !detailVisible.value) {
      const requested = items.value.find((item) => String(item.id) === requestedId)
      if (requested) {
        openDetail(requested)
      } else {
        try {
          openDetail(await getTeamScannedComponent(libraryId, requestedId))
        } catch {
          // The requested component can have been removed after the QR was printed.
        }
      }
    }
  } catch (error) {
    if (error?.code === 'ERR_CANCELED' || sequence !== loadSequence) return
    if (error?.response?.status === 404) {
      await clearLibrarySnapshots(teamState.user?.id, libraryId)
      items.value = []
      ElMessage.error(error?.response?.data?.detail || '你已不再是该团队器件库成员')
      return
    }
    if (items.value.length) {
      teamState.offlineReadonly = true
      ElMessage.warning('网络不可用，已显示最近一次缓存')
    } else {
      ElMessage.error(error?.response?.data?.detail || '器件加载失败')
    }
    if (append) throw error
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function bootstrap() {
  const cached = await readSnapshot(teamState.user?.id, libraryId, 'components')
  if (cached?.data) {
    const data = cached.data
    if (Array.isArray(data)) {
      items.value = data
      resultTotal.value = data.length
    } else {
      library.value = data.library || null
      if (data.response) applyComponentResponse(data.response)
    }
  }
  await Promise.all([load(), loadCustomLabels()])
  await nextTick()
  setupAutoLoadObserver()
}

async function reloadFromFirstPage() {
  categoryPaging.page = 1
  autoLoadError.value = false
  await load()
  await nextTick()
  setupAutoLoadObserver()
}

async function loadMoreCategories() {
  if (loading.value || !categoryPaging.hasMore) return
  categoryPaging.page += 1
  try {
    autoLoadError.value = false
    trackUsage((payload) => recordTeamUsageEvent(libraryId, payload), 'ui.team_components.auto_load', { entry: 'category-sentinel', target_type: 'team_library', target_id: libraryId, detail: { page: categoryPaging.page } })
    await load({ append: true })
  } catch {
    categoryPaging.page = Math.max(1, categoryPaging.page - 1)
    autoLoadError.value = true
  } finally {
    await nextTick()
    setupAutoLoadObserver()
  }
}

function stopAutoLoadObserver() {
  if (!autoLoadObserver) return
  autoLoadObserver.disconnect()
  autoLoadObserver = null
}

function setupAutoLoadObserver() {
  stopAutoLoadObserver()
  if (!categoryPaging.hasMore || !autoLoadSentinel.value) return
  autoLoadObserver = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) loadMoreCategories()
  }, { rootMargin: '420px 0px 420px 0px', threshold: 0.01 })
  autoLoadObserver.observe(autoLoadSentinel.value)
}

function toggleCategory(name) {
  const next = new Set(collapsedCategories.value)
  next.has(name) ? next.delete(name) : next.add(name)
  collapsedCategories.value = next
}

function openUrl(url) {
  window.open(url, '_blank', 'noopener')
}

async function openAddDialog() {
  Object.assign(manualForm, emptyForm())
  manualQuickPrompt.value = ''
  manualAiDraft.value = null
  lastTeamLcscDraft.value = {}
  addDialog.value = true
  nextTick(() => lcscImporter.value?.reset())
  await searchPersonal()
}

async function searchPersonal() {
  personalLoading.value = true
  try {
    cwOptions.value = await searchCwComponents({ keyword: cwKeyword.value, personal_only: true, limit: 200 })
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '个人版器件加载失败')
  } finally {
    personalLoading.value = false
  }
}

async function submitPersonal() {
  const payload = personalSelection.value.map((row) => ({ cw_component_id: row.id }))
  const result = await bulkAddComponents(libraryId, payload)
  ElMessage.success(`新增 ${result.created}，已存在 ${result.merged}`)
  addDialog.value = false
  await load()
}

async function submitImport() {
  const result = await importComponents(libraryId, importFile.value)
  ElMessage.success(`新增 ${result.created}，已存在 ${result.merged}，跳过 ${result.skipped}`)
  addDialog.value = false
  await load()
}

async function resolveCode() {
  if (!scanCode.value.trim()) return
  try {
    scanResult.value = await resolveCwCode(scanCode.value.trim())
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '没有在你的个人版中找到该器件')
  }
}

async function startScanner() {
  try {
    const { BrowserQRCodeReader } = await import('@zxing/browser')
    const reader = new BrowserQRCodeReader()
    scanning.value = true
    scannerControls = await reader.decodeFromVideoDevice(undefined, video.value, async (result) => {
      if (!result) return
      scanCode.value = result.getText()
      stopScanner()
      await resolveCode()
    })
  } catch {
    scanning.value = false
    ElMessage.warning('相机不可用，请使用手动输入')
  }
}
function stopScanner() { scannerControls?.stop(); scannerControls = null; scanning.value = false }

async function addScanned() {
  await createComponent(libraryId, { cw_component_id: scanResult.value.id, name: scanResult.value.name, quantity: 0 })
  addDialog.value = false
  await load()
}

async function submitManual() {
  if (!manualForm.name.trim() && manualQuickPrompt.value.trim()) manualForm.name = manualQuickPrompt.value.trim()
  if (!manualForm.name.trim()) return ElMessage.warning('请填写名称')
  await createComponent(libraryId, manualForm)
  Object.assign(manualForm, emptyForm())
  manualQuickPrompt.value = ''
  manualAiDraft.value = null
  lastTeamLcscDraft.value = {}
  lcscImporter.value?.reset()
  addDialog.value = false
  await load()
}

const teamLcscAutoFields = [
  'name',
  'model',
  'manufacturer',
  'description',
  'lcsc_number',
  'category',
  'package',
  'parameters',
  'tags',
  'datasheet_url',
  'buy_url',
  'source',
  'source_title'
]

function applyTeamLcscDraft(draft) {
  const normalizedDraft = { ...draft, category: draft?.category_name || '' }
  const previous = lastTeamLcscDraft.value || {}
  for (const field of teamLcscAutoFields) {
    const nextValue = normalizedDraft[field]
    if (nextValue === undefined || nextValue === null || nextValue === '') continue
    const current = manualForm[field]
    if (current === null || current === undefined || String(current).trim() === '' || current === previous[field]) {
      manualForm[field] = nextValue
    }
  }
  manualForm.quantity = Number(manualForm.quantity || 0)
  lastTeamLcscDraft.value = Object.fromEntries(teamLcscAutoFields.map((field) => [field, normalizedDraft[field]]))
  manualAiDraft.value = null
  ElMessage.success('立创器件草稿已填充，请核对数量和本地信息后保存')
}

async function reuseExistingLcscComponent(component) {
  if (!component?.id) return
  try {
    const result = await createComponent(libraryId, { cw_component_id: component.id, name: component.name, quantity: 0 })
    addDialog.value = false
    lastTeamLcscDraft.value = {}
    await load()
    ElMessage.success(result.merged ? '该器件已在团队库中，已直接打开' : '已复用个人版器件并加入团队库')
    await openDetail(result.item)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '复用个人版器件失败')
  }
}

function confidenceLabel(value) {
  return { high: '高', medium: '中', low: '低' }[value] || '待确认'
}

function manualKeySpecsToText(result) {
  const specs = Array.isArray(result?.key_specs) ? result.key_specs : []
  return specs
    .filter((item) => item?.value && item.confidence !== 'low')
    .slice(0, 6)
    .map((item) => `${item.name || '参数'} ${item.value}`)
    .join('；')
}

function manualPackageSuggestion(result) {
  const specs = Array.isArray(result?.key_specs) ? result.key_specs : []
  const hit = specs.find((item) => String(item?.name || '').includes('封装') && item?.value && item.confidence !== 'low')
  return hit?.value || ''
}

function mergeManualTags(current, next) {
  const seen = new Set()
  const result = []
  for (const value of [current, Array.isArray(next) ? next.join(',') : next]) {
    String(value || '')
      .split(/[,，、\s]+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .forEach((tag) => {
        const key = tag.toLowerCase()
        if (seen.has(key)) return
        seen.add(key)
        result.push(tag)
      })
  }
  return result.join(', ')
}

async function completeManualWithAi() {
  const query = manualQuickPrompt.value.trim() || [manualForm.model, manualForm.name, manualForm.parameters, manualForm.package, manualForm.lcsc_number].filter(Boolean).join(' ')
  if (!query) return ElMessage.warning('先输入一个大概的器件信息')
  manualAiLoading.value = true
  try {
    const result = await aiComponentInfo({
      query,
      known_specs: JSON.stringify({
        name: manualForm.name,
        model: manualForm.model,
        parameters: manualForm.parameters,
        package: manualForm.package,
        lcsc_number: manualForm.lcsc_number
      }),
      web_search: 'auto'
    })
    manualAiDraft.value = result
    if (!manualForm.name) manualForm.name = result.normalized_name || query
    if (!manualForm.model) manualForm.model = query
    if (!manualForm.category) manualForm.category = result.category_suggestion || ''
    if (!manualForm.package) manualForm.package = manualPackageSuggestion(result)
    if (!manualForm.parameters) manualForm.parameters = manualKeySpecsToText(result)
    if (!manualForm.remark) manualForm.remark = result.summary || ''
    manualForm.tags = mergeManualTags(manualForm.tags, result.ai_tags)
    trackUsage((body) => recordTeamUsageEvent(libraryId, body), 'ui.team_components.ai_quick_create', { target_type: 'team_library', target_id: libraryId, entry: 'manual-create', detail: { confidence: result.confidence || '' } })
    ElMessage.success('AI 已生成草稿，请核对后保存')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || 'AI 补齐失败，请手动填写必填项')
  } finally {
    manualAiLoading.value = false
  }
}

async function openDetail(row) {
  trackUsage((body) => recordTeamUsageEvent(libraryId, body), 'ui.team_components.detail_open', { target_type: 'team_component', target_id: row?.id })
  selected.value = row
  Object.assign(teamForm, { location: row.location || '', tags: row.tags || '', remark: row.remark || '' })
  teamEditVisible.value = false
  usageRecords.value = []
  detailVisible.value = true
  resetDetailDrawerScroll()
  edaBindings.value = []
  supplierParts.value = []
  inventoryLots.value = []
  componentAiAnswer.value = null
  if (row.cw_component_id) {
    edaLoading.value = true
    lotsLoading.value = true
    const engineeringRequests = FEATURE_EDA_ENABLED
      ? [listEdaBindings(row.cw_component_id, libraryId), listSupplierParts(row.cw_component_id, libraryId)]
      : [Promise.resolve([]), Promise.resolve([])]
    const [bindingsResult, suppliersResult, lotsResult] = await Promise.allSettled([
      ...engineeringRequests,
      listTeamComponentLots(libraryId, row.id)
    ])
    if (selected.value?.id !== row.id) return
    edaBindings.value = bindingsResult.status === 'fulfilled' ? bindingsResult.value : []
    supplierParts.value = suppliersResult.status === 'fulfilled' ? suppliersResult.value : []
    if (lotsResult.status === 'fulfilled') {
      inventoryLots.value = lotsResult.value || []
    } else {
      inventoryLots.value = []
      ElMessage.error(lotsResult.reason?.response?.data?.detail || '库存批次加载失败')
    }
    edaLoading.value = false
    lotsLoading.value = false
  }
}

function resetDetailDrawerScroll() {
  nextTick(() => {
    const body = document.querySelector('.component-detail-drawer .el-drawer__body')
    body?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  })
}

function resolveCurrentTeamScanBatch(values) {
  return resolveTeamScanBatch(libraryId, values)
}

function searchCurrentTeamScanCandidates(query) {
  return searchTeamScanCandidates(libraryId, query)
}

function openScannedComponent(component) {
  const current = items.value.find((item) => String(item.id) === String(component?.id))
  scannerVisible.value = false
  openDetail(current || component)
}

function openScanner(target = null) {
  scannerTarget.value = target
  scannerVisible.value = true
}

function openScannerForSelected() {
  if (!selected.value) return
  openScanner(selected.value)
}

async function exportAllTeamLabels() {
  await loadCustomLabels()
  labelDialog.value = true
}

async function openCustomLabelDialog() {
  router.push({ name: 'team-custom-labels', params: { libraryId } })
}

async function loadCustomLabels() {
  try {
    customLabels.value = await listTeamCustomLabels(libraryId)
  } catch {
    customLabels.value = []
  }
}

async function exportTeamInventory() {
  try {
    const blob = await exportTeamComponentInventory(libraryId)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `team-component-inventory-${new Date().toISOString().slice(0, 10)}.xlsx`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '导出团队库存失败')
  }
}

async function runTeamLabelExport(options) {
  labelExporting.value = true
  try {
    const blob = await exportTeamComponentLabels(libraryId, options)
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '导出团队二维码失败')
  } finally {
    labelExporting.value = false
  }
}

async function loadUsage(limit = 20) {
  if (!selected.value?.can_view_usage || !selected.value?.cw_component_id) return
  usageLoading.value = true
  try {
    usageRecords.value = await listTeamComponentUsage(libraryId, selected.value.id, { limit })
  } catch {
    usageRecords.value = []
  } finally {
    usageLoading.value = false
  }
}

async function loadLots() {
  if (!selected.value?.id) return
  lotsLoading.value = true
  try {
    inventoryLots.value = await listTeamComponentLots(libraryId, selected.value.id)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '库存批次加载失败')
  } finally {
    lotsLoading.value = false
  }
}

async function addInventoryLot(payload) {
  if (!selected.value?.id || readonly.value || !selected.value.can_edit_quantity) return
  lotSaving.value = true
  try {
    await createTeamComponentLot(libraryId, selected.value.id, payload)
    await loadLots()
    await load()
    const current = items.value.find((item) => item.id === selected.value.id)
    if (current) selected.value = current
    trackUsage((body) => recordTeamUsageEvent(libraryId, body), 'ui.team_components.lot_create', { target_type: 'team_component', target_id: selected.value.id, detail: { source_type: payload.source_type } })
    ElMessage.success('库存批次已新增')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '新增库存批次失败')
  } finally {
    lotSaving.value = false
  }
}

async function consumeInventoryLot(lot) {
  if (!selected.value?.id || !lot?.id || readonly.value || !selected.value.can_edit_quantity || lotConsumeIds.has(lot.id)) return
  const componentId = selected.value.id
  lotConsumeIds.add(lot.id)
  try {
    const updated = await decrementTeamComponentQuantity(libraryId, componentId, { quantity: 1, lot_id: lot.id, remark: `从 ${lot.source_reference || lot.source_type || '指定批次'} 扣减` })
    items.value = items.value.map((item) => item.id === updated.id ? updated : item)
    totalQuantity.value = Math.max(0, Number(totalQuantity.value || 0) - 1)
    if (selected.value?.id === componentId) {
      selected.value = updated
      inventoryLots.value = applyInventoryLotConsumption(inventoryLots.value, lot.id, 1)
    }
    inventoryChannel?.postMessage({
      type: 'quantity-updated',
      componentId: updated.cw_component_id,
      quantity: updated.quantity,
      availableQuantity: updated.available_quantity,
      reservedQuantity: updated.reserved_quantity,
      status: updated.status
    })
    trackUsage((body) => recordTeamUsageEvent(libraryId, body), 'ui.team_components.lot_consume', { target_type: 'team_component', target_id: componentId, detail: { lot_id: lot.id, source_type: lot.source_type } })
    ElMessage.success({ message: '已从指定批次扣减 1', grouping: true, duration: 1400 })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批次扣减失败')
  } finally {
    lotConsumeIds.delete(lot.id)
  }
}

async function quickConsume(row) {
  if (!row?.id || readonly.value || !row.can_edit_quantity || quickConsumeIds.has(row.id) || Number(row.available_quantity || 0) <= 0) return
  quickConsumeIds.add(row.id)
  try {
    const updated = await decrementTeamComponentQuantity(libraryId, row.id, { quantity: 1, remark: '团队器件卡片快捷领用 1 个' })
    items.value = items.value.map((item) => item.id === updated.id ? updated : item)
    totalQuantity.value = Math.max(0, Number(totalQuantity.value || 0) - 1)
    if (selected.value?.id === updated.id) selected.value = updated
    inventoryChannel?.postMessage({
      type: 'quantity-updated',
      componentId: updated.cw_component_id,
      quantity: updated.quantity,
      availableQuantity: updated.available_quantity,
      reservedQuantity: updated.reserved_quantity,
      status: updated.status
    })
    trackUsage((body) => recordTeamUsageEvent(libraryId, body), 'ui.team_components.quick_consume', {
      target_type: 'team_component',
      target_id: updated.id,
      entry: 'inventory-card',
      detail: { quantity: 1 }
    })
    ElMessage.success(`${row.name || row.model || row.warehouse_code || '器件'} 已领用 1 个，可用 ${updated.available_quantity || 0}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '领用登记失败')
  } finally {
    quickConsumeIds.delete(row.id)
  }
}

async function deleteInventoryLot(lot) {
  if (!selected.value?.id || !lot?.id || readonly.value || !selected.value.can_edit_quantity) return
  try {
    await ElMessageBox.confirm(
      `确认删除批次「${lot.source_reference || lot.source_type || '手工批次'}」？总库存将同步减少 ${lot.initial_quantity || 0}。`,
      '删除误添加批次',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
    lotSaving.value = true
    const result = await deleteTeamComponentLot(libraryId, selected.value.id, lot.id)
    selected.value = result.component
    await loadLots()
    await load()
    trackUsage((body) => recordTeamUsageEvent(libraryId, body), 'ui.team_components.lot_delete', { target_type: 'team_component', target_id: selected.value.id, detail: { lot_id: lot.id, source_type: lot.source_type } })
    ElMessage.success(`批次已删除，总库存已减少 ${result.removed_quantity || 0}`)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.response?.data?.detail || '删除库存批次失败')
  } finally {
    lotSaving.value = false
  }
}

async function askSelectedComponentAi(question) {
  if (!selected.value?.id) return
  componentAiAskLoading.value = true
  try {
    componentAiAnswer.value = await askTeamComponentAi(libraryId, selected.value.id, { question })
    trackUsage((body) => recordTeamUsageEvent(libraryId, body), 'ui.team_components.ai_ask', { target_type: 'team_component', target_id: selected.value.id })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'AI 问答失败')
  } finally {
    componentAiAskLoading.value = false
  }
}

async function saveTeamMeta() {
  const updated = await updateComponent(libraryId, selected.value.id, teamForm)
  selected.value = updated
  teamEditVisible.value = false
  await load()
  ElMessage.success('团队信息已保存')
}

async function remove(row) {
  await ElMessageBox.confirm(`把“${row.name}”移出团队器件库？不会删除来源账号的个人版库存。`, '移出团队器件库', { type: 'warning' })
  await deleteComponent(libraryId, row.id)
  detailVisible.value = false
  await load()
}

function handleDetailCommand(command) {
  if (command === 'quantity') {
    quantityForm.quantity = Number(selected.value?.quantity || 0)
    quantityForm.remark = ''
    quantityDialog.value = true
  } else if (command === 'team-info') {
    teamEditVisible.value = !teamEditVisible.value
  } else if (command === 'rebind') {
    openRebind(selected.value)
  } else if (command === 'remove') {
    remove(selected.value)
  }
}

async function saveQuantity() {
  quantitySaving.value = true
  try {
    const updated = await updateComponentQuantity(libraryId, selected.value.id, quantityForm)
    selected.value = updated
    quantityDialog.value = false
    inventoryChannel?.postMessage({
      type: 'quantity-updated',
      componentId: updated.cw_component_id,
      quantity: updated.quantity,
      availableQuantity: updated.available_quantity,
      reservedQuantity: updated.reserved_quantity,
      status: updated.status
    })
    await load()
    ElMessage.success('数量已同步到个人版')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '数量修改失败')
  } finally {
    quantitySaving.value = false
  }
}

function openMarkerEditor(marker = null) {
  Object.assign(markerForm, marker
    ? { id: marker.id, category: marker.category, color: normalizeTeamMarkerColor(marker.color), flagged: marker.flagged, note: marker.note || '' }
    : { id: '', category: '', color: DEFAULT_TEAM_MARKER_COLOR, flagged: false, note: '' })
  markerDialog.value = true
}

async function saveMarker() {
  if (!markerForm.category.trim()) return ElMessage.warning('请填写标记分类')
  markerSaving.value = true
  try {
    const payload = {
      category: markerForm.category.trim(),
      color: normalizeTeamMarkerColor(markerForm.color),
      flagged: markerForm.flagged,
      note: markerForm.note
    }
    if (markerForm.id) {
      await updateComponentMarker(libraryId, selected.value.id, markerForm.id, payload)
    } else {
      await createComponentMarker(libraryId, selected.value.id, payload)
    }
    markerDialog.value = false
    await refreshSelected()
    ElMessage.success('团队标记已保存')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '标记保存失败')
  } finally {
    markerSaving.value = false
  }
}

async function removeMarker(marker) {
  await ElMessageBox.confirm(`删除标记“${marker.category}”？`, '删除标记', { type: 'warning' })
  await deleteComponentMarker(libraryId, selected.value.id, marker.id)
  await refreshSelected()
}

async function refreshSelected() {
  const id = selected.value?.id
  await load()
  selected.value = items.value.find((item) => item.id === id) || selected.value
}

async function copyText(value, label) {
  try {
    await navigator.clipboard.writeText(String(value))
    ElMessage.success(`${label}已复制`)
  } catch {
    ElMessage.error('复制失败')
  }
}

async function openRebind(row) {
  selected.value = row
  rebindKeyword.value = row.lcsc_number || row.model || row.name
  rebindDialog.value = true
  await searchRebind()
}

const inventoryChannel = 'BroadcastChannel' in window ? new BroadcastChannel('cw-inventory-sync') : null
async function searchRebind() { rebindOptions.value = await searchCwComponents({ keyword: rebindKeyword.value, personal_only: true, limit: 100 }) }
async function confirmRebind(cw) {
  await ElMessageBox.confirm(`绑定到你的 ${cw.warehouse_code}？之后数量将实时读取该物料。`, '确认重新绑定')
  await rebindComponent(libraryId, selected.value.id, cw.id)
  rebindDialog.value = false
  detailVisible.value = false
  await load()
}

async function askAi() {
  if (!aiForm.prompt.trim()) return ElMessage.warning('请输入查询内容')
  aiLoading.value = true
  try {
    const data = await runTeamAi(libraryId, aiForm)
    aiResult.value = data.result
    ElMessage.success(data.cached ? '已使用缓存结果' : 'AI 查询完成')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || 'AI 查询失败')
  } finally {
    aiLoading.value = false
  }
}

watch(
  [keyword, categoryFilter, syncFilter, markerCategoryFilter, markerColorFilter, flaggedFilter],
  () => {
    window.clearTimeout(filterTimer)
    filterTimer = window.setTimeout(reloadFromFirstPage, 260)
  }
)

watch(
  () => [detailVisible.value, selected.value?.id || ''],
  ([visible]) => {
    if (visible) resetDetailDrawerScroll()
  }
)

bootstrap()
onBeforeRouteLeave(() => { loadController?.abort(); stopScanner(); stopAutoLoadObserver() })
onBeforeUnmount(() => {
  window.clearTimeout(filterTimer)
  loadController?.abort()
  stopScanner()
  stopAutoLoadObserver()
  inventoryChannel?.close()
})
</script>

<style scoped>
.filter-panel { display: grid; grid-template-columns: minmax(240px, 1fr) repeat(5, minmax(130px, auto)) auto auto auto; }
.category-stack { display: grid; gap: 14px; }
.category-block { padding: 14px; border: 1px solid #e2e8f0; border-radius: 16px; background: #fff; }
.category-head { width: 100%; display: flex; align-items: center; gap: 9px; padding: 0 0 12px; border: 0; background: transparent; color: #425466; cursor: pointer; text-align: left; }
.category-head strong { color: #17202a; font-size: 17px; }.category-head span:last-child { margin-left: auto; color: #667085; }
.category-dot { width: 12px; height: 12px; border-radius: 50%; }
.component-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(370px, 1fr)); gap: 12px; }
.component-skeleton-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(370px, 1fr)); gap: 12px; }
.component-skeleton { width: 100%; height: 420px; border-radius: 16px; }
.load-more { justify-self: center; min-width: 180px; }
.auto-load-sentinel { min-height: 44px; display: grid; place-items: center; color: #667085; font-size: 13px; }
.dialog-action { margin-top: 14px; }
.import-actions, .detail-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px; }
.import-actions a { color: #0b7769; font-weight: 700; }
:global(.component-detail-drawer.el-drawer) {
  max-width: calc(100vw - 40px);
  border-radius: var(--cw-radius-card) 0 0 var(--cw-radius-card);
  box-shadow: -18px 0 48px rgba(15, 23, 42, 0.18);
}
:global(.component-detail-drawer.el-drawer .el-drawer__header) {
  position: sticky;
  top: 0;
  z-index: 4;
  margin: 0;
  padding: 22px 28px 16px;
  border-bottom: 1px solid #edf1f7;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(10px);
}
:global(.component-detail-drawer.el-drawer .el-drawer__body) {
  padding: 18px 28px 28px;
  overflow-x: hidden;
}
:global(.component-detail-overlay.el-overlay) {
  background-color: rgba(15, 23, 42, 0.48);
}
.scan-grid, .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.quick-create-card { display: grid; gap: 10px; margin-bottom: 14px; padding: 14px; border: 1px solid #bfdbfe; border-radius: var(--cw-radius-card); background: linear-gradient(135deg, #eff6ff, #ffffff 70%); }
.quick-create-card p, .required-hint { margin: 2px 0 0; color: #667085; line-height: 1.55; }
.quick-create-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.ai-confidence { color: #2563eb; font-size: 13px; font-weight: 700; }
.required-hint { margin-bottom: 12px; font-size: 13px; }
.required-hint span { color: #dc2626; font-weight: 800; }
.scan-grid video { display: block; width: 100%; min-height: 260px; margin-bottom: 10px; border-radius: 16px; background: #12201f; }
.scan-grid .el-card { margin-top: 14px; }.ai-result, .team-edit { margin-top: 16px; }
.marker-color-option { display: inline-flex; align-items: center; gap: 8px; }
.marker-color-option i { width: 12px; height: 12px; border-radius: 50%; }
.marker-color-presets { display: grid; grid-template-columns: repeat(4, minmax(76px, 1fr)); gap: 10px; width: 100%; }
.marker-color-button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 40px; padding: 8px 10px; border: 1px solid #dcdfe6; border-radius: var(--cw-radius-control); color: #475467; background: #fff; cursor: pointer; }
.marker-color-button span { width: 18px; height: 18px; border-radius: 50%; background: var(--preset-color); box-shadow: inset 0 0 0 1px rgba(0, 0, 0, .08); }
.marker-color-button.selected { border-color: var(--preset-color); box-shadow: 0 0 0 2px color-mix(in srgb, var(--preset-color) 24%, transparent); color: #1f2937; font-weight: 700; }
.marker-badge { padding: 3px 8px; border: 1px solid color-mix(in srgb, var(--marker-color) 55%, white); border-radius: 999px; color: #7c2d12; background: color-mix(in srgb, var(--marker-color) 12%, white); font-size: 12px; }
.marker-manager { margin-top: 16px; padding: 16px; border: 1px solid #e2e8f0; border-radius: 16px; background: #f8fafc; }
.marker-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.marker-head h3 { margin: 0; }
.marker-list { display: grid; gap: 10px; margin-top: 12px; }
.marker-list article { display: grid; grid-template-columns: minmax(140px, .7fr) 1fr auto; gap: 12px; align-items: center; padding: 12px; border-left: 4px solid var(--marker-color); border-radius: var(--cw-radius-control); background: #fff; }
.marker-list article div:first-child { display: grid; gap: 4px; }
.marker-list article small { color: #667085; }
.marker-list article p { margin: 0; color: #475467; }
@media (max-width: 980px) { .filter-panel { display: flex; } }
@media (max-width: 680px) {
  :global(.component-detail-drawer.el-drawer) {
    width: 100vw !important;
    max-width: 100vw;
    border-radius: 0;
  }
  :global(.component-detail-drawer.el-drawer .el-drawer__header) {
    padding: 16px 16px 12px;
  }
  :global(.component-detail-drawer.el-drawer .el-drawer__body) {
    padding: 12px 12px 20px;
  }
  .team-page-head { align-items: stretch; }
  .team-toolbar { display: grid; grid-template-columns: 1fr 1fr; width: 100%; }
  .team-toolbar > :first-child,
  .team-toolbar > :last-child { grid-column: 1 / -1; }
  .team-toolbar .el-button,
  .team-toolbar .el-input,
  .team-toolbar .el-select { width: 100%; }
  .filter-panel { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .filter-panel > :first-child,
  .filter-panel > :last-child,
  .filter-panel > .muted { grid-column: 1 / -1; }
  .scan-grid,
  .form-grid { grid-template-columns: 1fr; }
  .component-grid { grid-template-columns: 1fr; }
  .marker-color-presets { grid-template-columns: repeat(2, minmax(90px, 1fr)); }
  .quick-create-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .quick-create-actions .el-button { width: 100%; }
}
</style>
