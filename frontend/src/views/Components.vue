<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">元器件库</h1>
        <p class="page-subtitle">库存优先，AI 在后台静默整理</p>
      </div>
      <div class="toolbar">
        <el-upload :show-file-list="false" accept=".jpg,.jpeg,.png,.webp" multiple :http-request="handleImageUpload">
          <el-button :icon="Picture" :loading="importingImages">图片识别导入</el-button>
        </el-upload>
        <el-upload :show-file-list="false" accept=".xlsx,.xls" :http-request="handleExcelUpload">
          <el-button :icon="Upload">导入 Excel</el-button>
        </el-upload>
        <el-dropdown trigger="click">
          <el-button plain>维护</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item :disabled="organizing" @click="enqueueOrganize">后台整理分类</el-dropdown-item>
              <el-dropdown-item divided :disabled="resetting" @click="resetAi">重置 AI 重新分类</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增元器件</el-button>
      </div>
    </div>

    <div class="panel filter-panel">
      <el-input v-model="filters.keyword" clearable placeholder="搜索名称、型号、参数、封装、立创编号、AI 摘要" @keyup.enter="reloadFromFirstPage" @clear="reloadFromFirstPage" />
      <el-select v-model="filters.category_id" clearable placeholder="分类" @change="reloadFromFirstPage">
        <el-option v-for="item in categories" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="库存状态" @change="reloadFromFirstPage">
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.ai_status" clearable placeholder="AI 状态" @change="reloadFromFirstPage">
        <el-option label="待整理" value="pending" />
        <el-option label="整理中" value="processing" />
        <el-option label="已完成" value="completed" />
        <el-option label="需更新" value="stale" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-select v-model="filters.stock" clearable placeholder="库存" @change="reloadFromFirstPage">
        <el-option label="有库存" value="available" />
        <el-option label="低库存" value="low" />
        <el-option label="缺货" value="empty" />
      </el-select>
      <el-segmented v-model="viewMode" :options="viewOptions" />
      <el-button type="primary" :icon="Search" @click="reloadFromFirstPage">查询</el-button>
    </div>

    <template v-if="viewMode === 'cards'">
      <div v-loading="loading" class="category-stack">
        <section v-for="group in groups" :key="group.category?.id || 'none'" class="category-block">
          <button class="category-head" @click="toggleGroup(group.category?.id || 'none')">
            <span class="category-color" :style="{ background: group.category?.color || '#eef2f7' }"></span>
            <strong>{{ group.category?.name || '未分类' }}</strong>
            <span>{{ group.total }} 个</span>
          </button>
          <div v-show="!collapsedGroups.has(group.category?.id || 'none')" class="component-grid">
            <article v-for="item in group.items" :key="item.id" class="component-card" @click="openDetail(item)">
              <div class="card-top">
                <el-tag effect="plain" :style="tagStyle(item.category)">{{ item.category?.name || '未分类' }}</el-tag>
                <div class="card-badges">
                  <el-tag v-if="item.source" effect="plain" type="info">{{ sourceLabel(item.source) }}</el-tag>
                  <el-tag v-if="showAiBadge(item.ai_status)" :type="aiStatusType(item.ai_status)" effect="plain">{{ aiStatusLabel(item.ai_status) }}</el-tag>
                </div>
              </div>
              <h3>{{ item._display.primary }}</h3>
              <p class="model-line">{{ item._display.secondary }}</p>
              <div class="tag-row">
                <el-tag v-if="item.status" size="small" :type="statusType(item.status)">{{ statusLabel(item.status) }}</el-tag>
                <el-tag v-for="tag in item._display.tags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
              </div>
              <div class="card-chip-row">
                <span v-for="chip in item._display.chips" :key="`${chip.label}-${chip.value}`" :class="`mini-chip tone-${chip.tone}`">
                  <small>{{ chip.label }}</small>{{ chip.value }}<small v-if="chip.tone === 'amber'">?</small>
                </span>
              </div>
              <p class="ai-line">{{ item._display.usage }}</p>
              <div class="card-links">
                <el-button size="small" text :icon="CopyDocument" @click.stop="copyComponentName(item)">复制型号</el-button>
                <el-button size="small" text @click.stop="openLcsc(item)">立创搜索</el-button>
              </div>
              <div class="stock-row">
                <span>总量 {{ item.quantity }}</span>
                <span>占用 {{ item.reserved_quantity }}</span>
                <strong>可用 {{ item.available_quantity }}</strong>
              </div>
            </article>
          </div>
        </section>
        <div v-if="showEmptyState" class="empty-search">
          <el-empty description="没有找到匹配的元器件" :image-size="86">
            <template #description>
              <div class="empty-copy">
                <strong>没有找到匹配的元器件</strong>
                <span v-if="filters.keyword">搜索词：{{ filters.keyword }}</span>
                <span v-if="activeFilterText">{{ activeFilterText }}</span>
              </div>
            </template>
            <div class="empty-actions">
              <el-button @click="clearFilters">清空筛选</el-button>
              <el-button v-if="filters.keyword" type="primary" plain @click="windowOpen(makeLcscSearchUrl(filters.keyword))">立创搜索</el-button>
            </div>
          </el-empty>
          <div v-if="suggestionLoading" class="suggestion-loading">AI 正在整理相近型号建议...</div>
          <div v-else-if="searchSuggestion?.suggestions?.length" class="suggestion-list">
            <article v-for="item in searchSuggestion.suggestions" :key="`${item.label}-${item.search_keyword}`" class="suggestion-card">
              <strong>{{ item.label }}</strong>
              <span>{{ item.reason }}</span>
              <el-button size="small" text @click="applySuggestion(item.search_keyword || item.label)">搜索 {{ item.search_keyword || item.label }}</el-button>
            </article>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="panel">
      <el-table class="desktop-table" v-loading="loading" :data="components" row-key="id" empty-text="暂无元器件" @row-click="openDetail">
        <el-table-column label="名称 / 型号" min-width="220">
          <template #default="{ row }">
            <strong>{{ primaryLabel(row) }}</strong>
            <div class="muted">{{ secondaryLabel(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="120">
          <template #default="{ row }"><el-tag effect="plain" :style="tagStyle(row.category)">{{ row.category?.name || '-' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="来源" width="140">
          <template #default="{ row }"><el-tag v-if="row.source" effect="plain" type="info">{{ sourceLabel(row.source) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="封装" width="110">
          <template #default="{ row }"><el-tag v-if="row.package" effect="plain">{{ row.package }}</el-tag></template>
        </el-table-column>
        <el-table-column label="库存" width="150">
          <template #default="{ row }">总 {{ row.quantity }} / 可用 {{ row.available_quantity }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" :icon="CopyDocument" @click.stop="copyComponentName(row)" />
            <el-button size="small" :disabled="row.quantity <= 0" @click.stop="quickConsume(row)">-1</el-button>
            <el-button size="small" :icon="Edit" @click.stop="openDetail(row, true)" />
          </template>
        </el-table-column>
      </el-table>
      <div class="mobile-card-list">
        <article v-for="item in components" :key="item.id" class="component-card" @click="openDetail(item)">
          <div class="card-top">
            <el-tag effect="plain" :style="tagStyle(item.category)">{{ item.category?.name || '未分类' }}</el-tag>
            <el-tag v-if="item.source" effect="plain" type="info">{{ sourceLabel(item.source) }}</el-tag>
          </div>
          <h3>{{ item._display.primary }}</h3>
          <p class="model-line">{{ item._display.secondary }}</p>
          <div class="card-links">
            <el-button size="small" text :icon="CopyDocument" @click.stop="copyComponentName(item)">复制型号</el-button>
          </div>
          <div class="stock-row"><span>总 {{ item.quantity }}</span><strong>可用 {{ item.available_quantity }}</strong></div>
        </article>
      </div>
      <div v-if="showEmptyState" class="empty-search">
        <el-empty description="没有找到匹配的元器件" :image-size="86">
          <template #description>
            <div class="empty-copy">
              <strong>没有找到匹配的元器件</strong>
              <span v-if="filters.keyword">搜索词：{{ filters.keyword }}</span>
              <span v-if="activeFilterText">{{ activeFilterText }}</span>
            </div>
          </template>
          <div class="empty-actions">
            <el-button @click="clearFilters">清空筛选</el-button>
            <el-button v-if="filters.keyword" type="primary" plain @click="windowOpen(makeLcscSearchUrl(filters.keyword))">立创搜索</el-button>
          </div>
        </el-empty>
        <div v-if="suggestionLoading" class="suggestion-loading">AI 正在整理相近型号建议...</div>
        <div v-else-if="searchSuggestion?.suggestions?.length" class="suggestion-list">
          <article v-for="item in searchSuggestion.suggestions" :key="`${item.label}-${item.search_keyword}`" class="suggestion-card">
            <strong>{{ item.label }}</strong>
            <span>{{ item.reason }}</span>
            <el-button size="small" text @click="applySuggestion(item.search_keyword || item.label)">搜索 {{ item.search_keyword || item.label }}</el-button>
          </article>
        </div>
      </div>
    </div>

    <div v-if="pagination.total > pagination.pageSize" class="pagination-bar">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :page-sizes="[12, 24, 40, 80]"
        :total="pagination.total"
        background
        layout="total, sizes, prev, pager, next"
        @current-change="load"
        @size-change="reloadFromFirstPage"
      />
    </div>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="700px">
      <template v-if="selected">
        <div class="detail-summary">
          <div class="detail-tags">
            <el-tag effect="plain" :style="tagStyle(selected.category)">{{ selected.category?.name || '未分类' }}</el-tag>
            <el-tag v-if="selected.source" effect="plain" type="info">{{ sourceLabel(selected.source) }}</el-tag>
          </div>
          <h2>{{ primaryLabel(selected) }}</h2>
          <p v-if="secondaryLabel(selected)" class="detail-model">{{ secondaryLabel(selected) }}</p>
          <p>{{ selected.ai_summary || selected.parameters || '暂无摘要' }}</p>
          <div v-if="specChips.length" class="spec-chip-grid">
            <span v-for="chip in specChips" :key="`${chip.label}-${chip.value}`" class="spec-chip" :class="`tone-${chip.tone}`">
              <small>{{ chip.label }}</small>
              <strong>{{ chip.value }}</strong>
            </span>
          </div>
          <div v-if="unitHints.length" class="unit-hints">
            <strong>常用换算</strong>
            <span v-for="hint in unitHints" :key="hint">{{ hint }}</span>
          </div>
          <div class="tag-row">
            <el-tag>总量 {{ selected.quantity }}</el-tag>
            <el-tag type="warning">占用 {{ selected.reserved_quantity }}</el-tag>
            <el-tag type="success">可用 {{ selected.available_quantity }}</el-tag>
            <el-tag :type="aiStatusType(selected.ai_status)">{{ aiStatusLabel(selected.ai_status) }}</el-tag>
          </div>
          <div class="detail-links">
            <el-button size="small" type="primary" plain :icon="CopyDocument" @click="copyComponentName(selected)">复制型号</el-button>
            <el-button size="small" type="primary" plain @click="openLcsc(selected)">立创搜索</el-button>
            <el-button v-if="selected.datasheet_url" size="small" plain @click="windowOpen(selected.datasheet_url)">数据手册</el-button>
          </div>
        </div>

        <div class="drawer-actions">
          <el-button :loading="aiRefreshing" @click="refreshAi('full')">AI 重新分析</el-button>
          <el-button :loading="aiRefreshing" @click="refreshAi('usage')">刷新用途</el-button>
          <el-button :loading="aiRefreshing" @click="refreshAi('risks')">刷新风险</el-button>
          <el-button :loading="aiRefreshing" @click="refreshAi('substitutes')">刷新替代料</el-button>
          <el-button type="primary" @click="editing = !editing">{{ editing ? '收起编辑' : '编辑' }}</el-button>
        </div>

        <div class="ai-section">
          <h3>AI 知识</h3>
          <p v-if="aiUsageText" class="ai-usage-text">{{ aiUsageText }}</p>
          <div class="knowledge-grid">
            <div v-if="keySpecList.length" class="knowledge-box tone-blue">
              <strong>关键参数</strong>
              <div class="mini-specs">
                <span v-for="item in keySpecList" :key="`${item.name}-${item.value}`">
                  <small>{{ item.name }}</small>
                  <b>{{ item.value }}</b>
                </span>
              </div>
            </div>
            <div v-if="aiUsage.typical_applications?.length" class="knowledge-box tone-green">
              <strong>适合用途</strong>
              <ul><li v-for="item in aiUsage.typical_applications" :key="item">{{ item }}</li></ul>
            </div>
            <div v-if="aiUsage.design_insights?.length" class="knowledge-box tone-indigo">
              <strong>设计洞察</strong>
              <ul><li v-for="item in aiUsage.design_insights" :key="item">{{ item }}</li></ul>
            </div>
            <div v-if="aiUsage.do_not_use_for?.length" class="knowledge-box tone-red">
              <strong>不适合场景</strong>
              <ul><li v-for="item in aiUsage.do_not_use_for" :key="item">{{ item }}</li></ul>
            </div>
            <div v-if="aiUsage.datasheet_notes?.length" class="knowledge-box tone-amber">
              <strong>手册核对项</strong>
              <ul><li v-for="item in aiUsage.datasheet_notes" :key="item">{{ item }}</li></ul>
            </div>
            <div v-if="aiUsage.recommended_pairings?.length" class="knowledge-box tone-purple">
              <strong>推荐搭配</strong>
              <ul><li v-for="item in aiUsage.recommended_pairings" :key="item">{{ item }}</li></ul>
            </div>
            <div v-if="riskList.length" class="knowledge-box tone-red">
              <strong>风险提示</strong>
              <ul><li v-for="item in riskList" :key="item">{{ item }}</li></ul>
            </div>
            <div v-if="pcbNoteList.length" class="knowledge-box tone-cyan">
              <strong>PCB 注意</strong>
              <ul><li v-for="item in pcbNoteList" :key="item">{{ item }}</li></ul>
            </div>
            <div v-if="substituteList.length" class="knowledge-box tone-slate">
              <strong>替代料检查</strong>
              <ul><li v-for="item in substituteList" :key="item">{{ item }}</li></ul>
            </div>
            <div v-if="aiUsage.source_notes?.length" class="knowledge-box tone-stone">
              <strong>依据说明</strong>
              <ul><li v-for="item in aiUsage.source_notes" :key="item">{{ item }}</li></ul>
            </div>
          </div>
          <div v-if="knowledgeCards.length" class="card-list">
            <el-collapse>
              <el-collapse-item v-for="card in knowledgeCards" :key="card.id" :title="card.title">
                <pre>{{ card.content }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>

        <el-form v-if="editing" label-width="92px" :model="form" class="edit-form">
          <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="型号"><el-input v-model="form.model" /></el-form-item>
          <el-form-item label="分类">
            <el-select v-model="form.category_id" clearable filterable style="width: 100%">
              <el-option v-for="item in categories" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="参数"><el-input v-model="form.parameters" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="封装"><el-input v-model="form.package" /></el-form-item>
          <el-form-item label="数量"><el-input-number v-model="form.quantity" :min="0" style="width: 100%" /></el-form-item>
          <el-form-item label="来源"><el-input v-model="form.source" placeholder="手动新增 / 立创商城 Excel / 图片识别导入" /></el-form-item>
          <el-form-item label="立创编号"><el-input v-model="form.lcsc_number" /></el-form-item>
          <el-form-item label="标签"><el-input v-model="form.tags" /></el-form-item>
          <el-form-item label="数据手册"><el-input v-model="form.datasheet_url" /></el-form-item>
          <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="AI 标签">
            <el-checkbox v-model="form.is_common">常用</el-checkbox>
            <el-checkbox v-model="form.is_hand_solder_friendly">适合手焊</el-checkbox>
            <el-checkbox v-model="form.is_power_component">电源</el-checkbox>
            <el-checkbox v-model="form.is_signal_component">信号</el-checkbox>
            <el-checkbox v-model="form.is_high_current">大电流</el-checkbox>
            <el-checkbox v-model="form.is_high_voltage">高压</el-checkbox>
          </el-form-item>
          <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
        </el-form>
      </template>
    </el-drawer>

    <el-dialog v-model="previewVisible" title="Excel 导入预览" width="90%">
      <el-alert type="info" show-icon :closable="false" class="import-alert">
        已导入过的订单物料会跳过；新物料/合并物料会自动加入 AI 后台整理队列。
      </el-alert>
      <el-table :data="previewRows" max-height="480" empty-text="没有可导入数据">
        <el-table-column prop="order_number" label="订单编号" min-width="140" />
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="model" label="型号" min-width="150" />
        <el-table-column prop="package" label="封装" width="100" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column prop="lcsc_number" label="立创编号" width="130" />
        <el-table-column label="处理" width="130">
          <template #default="{ row }">
            <el-select v-model="row.action" size="small" :disabled="row.already_imported">
              <el-option label="新增" value="create" :disabled="row.duplicate" />
              <el-option label="合并" value="merge" :disabled="!row.duplicate" />
              <el-option label="跳过" value="skip" />
            </el-select>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="previewVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="confirmImport">确认导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="imagePreviewVisible" title="图片识别导入预览" width="94%">
      <el-alert type="info" show-icon :closable="false" class="import-alert">
        图片识别只生成候选项；请确认后再新增或合并库存。低置信度项目建议手动核对。
      </el-alert>
      <el-table :data="imagePreviewRows" max-height="520" empty-text="暂无识别结果">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="model" label="型号" min-width="130" />
        <el-table-column prop="parameters" label="参数" min-width="180" />
        <el-table-column prop="normalized_spec" label="规格" width="110" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column label="置信度" width="100">
          <template #default="{ row }"><el-tag :type="row.confidence === 'high' ? 'success' : row.confidence === 'medium' ? 'warning' : 'danger'">{{ row.confidence || 'low' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="动作" width="150">
          <template #default="{ row }">
            <el-select v-model="row.action" size="small">
              <el-option label="新增" value="create" />
              <el-option label="合并已有" value="merge" :disabled="!row.matched_component_id" />
              <el-option label="跳过" value="skip" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="资料" width="110">
          <template #default="{ row }"><el-button size="small" text @click="windowOpen(row.lcsc_search_url)">立创</el-button></template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="imagePreviewVisible = false">取消</el-button>
        <el-button type="primary" :loading="importingImages" @click="confirmImageImport">确认处理</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import { CopyDocument, Edit, Picture, Plus, Search, Upload } from '@element-plus/icons-vue'
import {
  commitExcel,
  decrementComponentQuantity,
  incrementComponentQuantity,
  getCategories,
  getComponentAi,
  getComponents,
  getGroupedComponentsPage,
  getSearchSuggestions,
  enqueueOrganizeAiTasks,
  previewImageImport,
  previewExcel,
  refreshComponentAi,
  resetAndReorganize,
  saveComponent
} from '../api/client'
import { componentOneLineUsage, componentUnitHints, extractComponentChips, makeLcscSearchUrl, normalizeToken, splitTags } from '../utils/componentUi'

const categories = ref([])
const groups = ref([])
const components = ref([])
const loading = ref(false)
const suggestionLoading = ref(false)
const saving = ref(false)
const importing = ref(false)
const importingImages = ref(false)
const organizing = ref(false)
const aiRefreshing = ref(false)
const resetting = ref(false)
const previewVisible = ref(false)
const imagePreviewVisible = ref(false)
const previewRows = ref([])
const imagePreviewRows = ref([])
const drawerVisible = ref(false)
const selected = ref(null)
const knowledgeCards = ref([])
const editing = ref(false)
const viewMode = ref('cards')
const collapsedGroups = ref(new Set())
const route = useRoute()
const searchSuggestion = ref(null)
const pagination = reactive({ page: 1, pageSize: 24, total: 0 })
let suggestionRequestId = 0
const viewOptions = [
  { label: '分类卡片', value: 'cards' },
  { label: '紧凑表格', value: 'table' }
]

const filters = reactive({ keyword: '', category_id: null, status: '', ai_status: '', stock: '' })
const emptyForm = {
  id: null,
  name: '',
  model: '',
  category_id: null,
  parameters: '',
  package: '',
  quantity: 0,
  source: '',
  lcsc_number: '',
  tags: '',
  status: 'in_stock',
  location: '',
  remark: '',
  datasheet_url: '',
  is_hand_solder_friendly: false,
  is_power_component: false,
  is_signal_component: false,
  is_high_current: false,
  is_high_voltage: false,
  is_common: false
}
const form = reactive({ ...emptyForm })

const drawerTitle = computed(() => (selected.value ? selected.value.name : '元器件详情'))
const aiUsage = computed(() => {
  const parsed = parseJsonValue(selected.value?.ai_usage)
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    return {
      usage: typeof parsed.usage === 'string' ? parsed.usage : '',
      key_specs: Array.isArray(parsed.key_specs) ? parsed.key_specs.map(normalizeKeySpec).filter(Boolean) : [],
      typical_applications: valueList(parsed.typical_applications),
      design_insights: valueList(parsed.design_insights),
      do_not_use_for: valueList(parsed.do_not_use_for),
      datasheet_notes: valueList(parsed.datasheet_notes),
      recommended_pairings: valueList(parsed.recommended_pairings),
      source_notes: valueList(parsed.source_notes)
    }
  }
  return {
    usage: typeof parsed === 'string' ? parsed : '',
    key_specs: [],
    typical_applications: [],
    design_insights: [],
    do_not_use_for: [],
    datasheet_notes: [],
    recommended_pairings: [],
    source_notes: []
  }
})
const aiUsageText = computed(() => aiUsage.value.usage || '')
const riskList = computed(() => valueList(selected.value?.ai_risk_notes))
const pcbNoteList = computed(() => valueList(selected.value?.ai_pcb_notes))
const substituteList = computed(() => valueList(selected.value?.ai_substitutes))
const keySpecList = computed(() => aiUsage.value.key_specs || [])
const specChips = computed(() => extractComponentChips(selected.value, 10))
const unitHints = computed(() => componentUnitHints(selected.value))
const showEmptyState = computed(() => !loading.value && pagination.total === 0)
const activeFilterText = computed(() => {
  const parts = []
  const category = categories.value.find((item) => item.id === filters.category_id)
  if (category) parts.push(`分类：${category.name}`)
  if (filters.status) parts.push(`状态：${statusLabel(filters.status)}`)
  if (filters.ai_status) parts.push(`AI：${aiStatusLabel(filters.ai_status)}`)
  if (filters.stock) parts.push(`库存：${stockLabels[filters.stock] || filters.stock}`)
  return parts.join(' / ')
})
const statusOptions = [
  { label: '在库', value: 'in_stock' },
  { label: '低库存', value: 'low_stock' },
  { label: '待采购', value: 'pending_purchase' },
  { label: '待验证', value: 'pending' },
  { label: '停用', value: 'obsolete' }
]
const stockLabels = { available: '有库存', low: '低库存', empty: '缺货' }

function statusLabel(value) {
  return statusOptions.find((item) => item.value === value)?.label || value
}

function statusType(value) {
  return { in_stock: 'success', low_stock: 'warning', pending_purchase: 'warning', pending: 'info', obsolete: 'danger' }[value] || 'info'
}

function aiStatusLabel(value) {
  return { pending: '待整理', processing: '整理中', completed: '已完成', failed: '失败', stale: '需更新' }[value || 'pending'] || value
}

function aiStatusType(value) {
  return { pending: 'info', processing: 'warning', completed: 'success', failed: 'danger', stale: 'warning' }[value || 'pending'] || 'info'
}

function showAiBadge(value) {
  return ['pending', 'processing', 'stale'].includes(value || 'pending')
}

function tagStyle(category) {
  return { background: category?.color || '#eef2f7', borderColor: 'transparent', color: '#1f2937' }
}

function specNameKey(value) {
  return normalizeToken(value).replace(/^(标称|额定|最大|最小)/, '')
}

function comparableToken(value) {
  return normalizeToken(value)
    .replace(/[±+~≈约]/g, '')
    .replace(/µ/g, 'u')
}

function keySpecsFor(item) {
  const usage = parseJsonValue(item?.ai_usage)
  const specs = usage && typeof usage === 'object' && !Array.isArray(usage) ? usage.key_specs : []
  return Array.isArray(specs) ? specs.map(normalizeKeySpec).filter(Boolean) : []
}

const titleSpecNames = {
  电阻: ['阻值', '电阻值', '标称阻值'],
  电容: ['容值', '容量', '标称容值', '标称容量', '电容值'],
  电感: ['感值', '电感值', '标称感值'],
  时钟源: ['频率', '输出频率']
}

const descriptiveNameCategories = new Set([
  '传感器',
  '机电件',
  '散热件',
  '功能模块',
  '通信模块',
  '显示模块',
  '开发板',
  '结构件'
])

function findSpecByNames(item, names = []) {
  const wanted = names.map(specNameKey)
  return keySpecsFor(item).find((spec) => wanted.includes(specNameKey(spec.name)))
}

function titleSpec(item) {
  const category = item?.category?.name || ''
  return findSpecByNames(item, titleSpecNames[category] || [])
}

function clockTitleSuffix(item) {
  const tags = splitTags([item?.tags, item?.ai_tags].filter(Boolean).join(','))
  const crystalTag = tags.find((tag) => tag.includes('晶振') || tag.includes('振荡器') || tag.includes('谐振器'))
  if (crystalTag) return crystalTag
  return '时钟源'
}

function primaryLabel(item) {
  const category = item?.category?.name || ''
  const spec = titleSpec(item)
  if (spec?.value) {
    if (category === '电阻' && comparableToken(spec.value) === '0ω') return '0Ω 跳线电阻'
    if (category === '时钟源') return `${spec.value} ${clockTitleSuffix(item)}`
    return spec.value
  }
  if (category === '连接件' && item?.normalized_spec) return item.normalized_spec
  if (descriptiveNameCategories.has(category) && item?.name) return item.name
  return item?.model || item?.normalized_spec || item?.name || '未命名物料'
}

function secondaryLabel(item) {
  const primary = normalizeToken(primaryLabel(item))
  const coreSpec = titleSpec(item)
  const coreValue = comparableToken(coreSpec?.value)
  const seen = new Set([primary])
  const parts = [item?.model, item?.package, item?.normalized_spec]
    .filter(Boolean)
    .filter((part) => {
      const key = normalizeToken(part)
      const comparable = comparableToken(part)
      if (!key || seen.has(key)) return false
      if (coreValue && comparable.includes(coreValue)) return false
      seen.add(key)
      return true
    })
  return parts.join(' / ')
}

function cardChips(item) {
  const core = titleSpec(item)
  const blocked = new Set([specNameKey(core?.name), comparableToken(core?.value)].filter(Boolean))
  const chips = []
  const seen = new Set()
  for (const spec of keySpecsFor(item)) {
    const value = String(spec.value || '').trim()
    if (!value) continue
    if (spec.confidence === 'low') continue
    if (String(spec.name || '').includes('估算') || value.includes('未从资料确认')) continue
    const nameKey = specNameKey(spec.name)
    const valueKey = comparableToken(value)
    if (blocked.has(nameKey) || blocked.has(valueKey) || seen.has(`${nameKey}:${valueKey}`)) continue
    seen.add(`${nameKey}:${valueKey}`)
    chips.push({ label: spec.name || '参数', value, tone: spec.confidence === 'medium' ? 'cyan' : 'indigo' })
    if (chips.length >= 4) break
  }
  return chips
}

function displayTags(item) {
  const category = item.category?.name || ''
  const pkg = item.package || ''
  const spec = item.normalized_spec || ''
  const chips = cardChips(item)
  const blocked = new Set(
    [category, pkg, spec, item.model, item.name, secondaryLabel(item)]
      .filter(Boolean)
      .flatMap((value) => [normalizeToken(value), comparableToken(value)])
  )
  const core = titleSpec(item)
  if (core?.value) blocked.add(comparableToken(core.value))
  for (const chip of chips) {
    const v = comparableToken(chip.value)
    if (v) blocked.add(v)
  }
  const seen = new Set()
  const pkgNorm = comparableToken(pkg)
  return splitTags(item.tags || item.ai_tags).filter((tag) => {
    const key = comparableToken(tag)
    if (!key || blocked.has(key) || seen.has(key)) return false
    if (pkgNorm && (key.includes(pkgNorm) || pkgNorm.includes(key))) return false
    seen.add(key)
    return true
  })
}

function sourceLabel(source) {
  const text = String(source || '').trim()
  if (!text) return ''
  if (text.includes('Excel') && text.includes('立创')) return '立创商城 Excel'
  if (text.includes('立创')) return '立创商城'
  if (text.includes('图片')) return '图片识别导入'
  return text.length > 12 ? `${text.slice(0, 12)}…` : text
}

function oneLineUsage(item) {
  return componentOneLineUsage(item)
}

function windowOpen(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

function openLcsc(item) {
  windowOpen(makeLcscSearchUrl(item?.lcsc_number || item?.model || item?.name))
}

function componentCopyText(item) {
  return String(item?.model || item?.normalized_spec || item?.name || primaryLabel(item) || '').trim()
}

async function copyComponentName(item) {
  const text = componentCopyText(item)
  if (!text) return ElMessage.warning('没有可复制的型号')
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
  ElMessage.success(`已复制：${text}`)
}

function normalizeKeySpec(item) {
  if (!item) return null
  if (typeof item === 'string') {
    const [name, ...rest] = item.split(/[:：]/)
    return { name: rest.length ? name.trim() : '参数', value: (rest.join('：') || item).trim() }
  }
  const name = item.name || item.label || item.key || item.spec || '参数'
  const value = item.value || item.val || item.content || item.description
  if (!value) return null
  return { name: String(name).trim(), value: String(value).trim(), confidence: item.confidence }
}

function pretty(value) {
  if (!value) return '暂无'
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

function parseJsonValue(value) {
  if (!value) return ''
  if (typeof value !== 'string') return value
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

function flattenValue(value) {
  const parsed = parseJsonValue(value)
  if (!parsed) return []
  if (Array.isArray(parsed)) return parsed.flatMap(flattenValue)
  if (typeof parsed === 'object') return Object.values(parsed).flatMap(flattenValue)
  return String(parsed)
    .split(/\n+/)
    .map((item) => item.replace(/^[-*、\s]+/, '').trim())
    .filter(Boolean)
}

function valueList(value) {
  return [...new Set(flattenValue(value))]
}

function decorateComponent(item) {
  return {
    ...item,
    _display: {
      primary: primaryLabel(item),
      secondary: secondaryLabel(item),
      tags: displayTags(item).slice(0, 3),
      chips: cardChips(item),
      usage: oneLineUsage(item)
    }
  }
}

function toggleGroup(key) {
  const next = new Set(collapsedGroups.value)
  next.has(key) ? next.delete(key) : next.add(key)
  collapsedGroups.value = next
}

async function load() {
  loading.value = true
  try {
    const params = { ...filters, page: pagination.page, page_size: pagination.pageSize }
    if (viewMode.value === 'cards') {
      const data = await getGroupedComponentsPage(params)
      groups.value = (data.groups || []).map((group) => ({
        ...group,
        items: (group.items || []).map(decorateComponent)
      }))
      components.value = []
      pagination.total = data.total || 0
    } else {
      const data = await getComponents(params)
      components.value = (data.items || []).map(decorateComponent)
      groups.value = []
      pagination.total = data.total || 0
    }
    maybeLoadSearchSuggestions()
  } catch (error) {
    ElMessage.error('读取元器件失败')
  } finally {
    loading.value = false
  }
}

async function maybeLoadSearchSuggestions() {
  const requestId = ++suggestionRequestId
  searchSuggestion.value = null
  if (!String(filters.keyword || '').trim() || pagination.total > 0) {
    suggestionLoading.value = false
    return
  }
  suggestionLoading.value = true
  try {
    const suggestion = await getSearchSuggestions({
      keyword: filters.keyword,
      category_id: filters.category_id,
      status: filters.status,
      ai_status: filters.ai_status,
      stock: filters.stock
    })
    if (requestId === suggestionRequestId) searchSuggestion.value = suggestion
  } catch {
    if (requestId === suggestionRequestId) searchSuggestion.value = null
  } finally {
    if (requestId === suggestionRequestId) suggestionLoading.value = false
  }
}

async function reloadFromFirstPage() {
  pagination.page = 1
  await load()
}

function clearFilters() {
  filters.keyword = ''
  filters.category_id = null
  filters.status = ''
  filters.ai_status = ''
  filters.stock = ''
  reloadFromFirstPage()
}

function applySuggestion(keyword) {
  filters.keyword = keyword
  reloadFromFirstPage()
}

async function loadCategories() {
  categories.value = await getCategories()
}

function fillForm(row = {}) {
  Object.assign(form, emptyForm, row)
}

function openCreate() {
  selected.value = null
  fillForm()
  editing.value = true
  drawerVisible.value = true
}

async function openDetail(row, edit = false) {
  selected.value = row
  fillForm(row)
  editing.value = edit
  drawerVisible.value = true
  try {
    const data = await getComponentAi(row.id)
    selected.value = data.component
    fillForm(data.component)
    knowledgeCards.value = data.knowledge_cards || []
  } catch {
    knowledgeCards.value = []
  }
}

async function refreshAi(scope) {
  if (!selected.value) return
  aiRefreshing.value = true
  try {
    const data = await refreshComponentAi(selected.value.id, { scope, force: true })
    selected.value = data.component
    fillForm(data.component)
    knowledgeCards.value = data.knowledge_cards || []
    ElMessage.success('AI 信息已更新')
    load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'AI 更新失败')
  } finally {
    aiRefreshing.value = false
  }
}

async function submitForm() {
  if (!form.name) {
    ElMessage.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    const saved = await saveComponent(form)
    selected.value = saved
    fillForm(saved)
    editing.value = false
    ElMessage.success('已保存，AI 状态会按需更新')
    load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function quickConsume(row) {
  try {
    await decrementComponentQuantity(row.id, { quantity: 1, remark: '手动快捷扣库存' })
    ElMessage.success(`${row.name} 已扣减 1`)
    load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '扣减失败')
  }
}

async function handleExcelUpload({ file }) {
  try {
    previewRows.value = await previewExcel(file)
    previewVisible.value = true
  } catch {
    ElMessage.error('Excel 解析失败，请检查表头')
  }
}

async function handleImageUpload({ file }) {
  importingImages.value = true
  const notice = ElNotification({
    title: '图片识别中',
    message: '正在调用 MiMo 识别购物截图，通常需要 10-30 秒。请不要重复上传。',
    type: 'info',
    duration: 0
  })
  try {
    imagePreviewRows.value = await previewImageImport([file])
    imagePreviewVisible.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '图片识别失败')
  } finally {
    notice.close()
    importingImages.value = false
  }
}

async function enqueueOrganize() {
  organizing.value = true
  try {
    await enqueueOrganizeAiTasks(true)
    ElMessage.success('已加入全库分类整理队列，后台会逐个处理')
    await load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '整理任务创建失败')
  } finally {
    organizing.value = false
  }
}

async function resetAi() {
  try {
    await ElMessageBox.confirm('将清除所有 AI 分析结果、知识卡片和标签，然后重新分类整理全部元器件。确认继续？', '重置 AI 重新分类', {
      confirmButtonText: '确认重置',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  resetting.value = true
  try {
    const result = await resetAndReorganize()
    ElMessage.success(`已重置全部 AI 数据，整理 ${result.organize_queued} + 分析 ${result.analyze_queued} 个元器件加入队列`)
    await load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重置失败')
  } finally {
    resetting.value = false
  }
}

async function confirmImageImport() {
  importingImages.value = true
  try {
    let created = 0
    let merged = 0
    let skipped = 0
    for (const row of imagePreviewRows.value) {
      if (row.action === 'skip') {
        skipped += 1
      } else if (row.action === 'merge' && row.matched_component_id) {
        await incrementComponentQuantity(row.matched_component_id, { quantity: row.quantity || 1, remark: `图片识别合并：${row.evidence_text || row.name}` })
        merged += 1
      } else if (row.action === 'create') {
        await saveComponent({
          name: row.name || row.model || '图片识别物料',
          model: row.model,
          category_id: row.category_id,
          parameters: row.parameters,
          package: row.package,
          quantity: row.quantity || 1,
          source: row.source || '图片识别导入',
          lcsc_number: row.lcsc_number,
          tags: row.tags,
          source_title: row.source_title,
          part_family: row.part_family,
          count_mode: row.count_mode,
          normalized_spec: row.normalized_spec,
          status: 'in_stock',
          remark: row.evidence_text
        })
        created += 1
      }
    }
    ElMessage.success(`新增 ${created}，合并 ${merged}，跳过 ${skipped}`)
    imagePreviewVisible.value = false
    load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '图片导入确认失败')
  } finally {
    importingImages.value = false
  }
}

async function confirmImport() {
  importing.value = true
  try {
    const result = await commitExcel(previewRows.value)
    ElMessage.success(`新增 ${result.created}，合并 ${result.merged}，跳过 ${result.skipped}`)
    previewVisible.value = false
    load()
  } catch {
    ElMessage.error('导入失败')
  } finally {
    importing.value = false
  }
}

onMounted(async () => {
  if (route.query.keyword) filters.keyword = String(route.query.keyword)
  await loadCategories()
  await load()
})

watch(viewMode, () => {
  reloadFromFirstPage()
})

watch(
  () => route.query.keyword,
  async (keyword) => {
    if (keyword === undefined) return
    filters.keyword = String(keyword || '')
    await reloadFromFirstPage()
  }
)
</script>

<style scoped>
.page {
  --component-radius: 16px;
  --component-section-radius: 22px;
}

.page-header {
  padding: 4px 2px;
}

.filter-panel {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 140px 140px 140px 120px auto auto;
  gap: 10px;
  align-items: center;
  border-color: rgba(255, 255, 255, 0.78);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.055);
}

.filter-panel :deep(.el-input__wrapper),
.filter-panel :deep(.el-select__wrapper),
.filter-panel :deep(.el-segmented),
.filter-panel :deep(.el-button) {
  border-radius: 14px;
}

.toolbar :deep(.el-button) {
  border-radius: 14px;
  box-shadow: none;
}

.category-stack {
  display: grid;
  gap: 14px;
}

.category-block {
  padding: 14px;
  border-radius: var(--component-section-radius);
  border: 1px solid var(--cw-border);
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 8px 28px rgba(15, 23, 42, 0.045);
}

.category-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  border: 0;
  background: transparent;
  padding: 4px 2px 14px;
  color: var(--cw-text);
  cursor: pointer;
}

.category-head span:last-child {
  margin-left: auto;
  color: var(--cw-muted);
}

.category-color {
  width: 14px;
  height: 14px;
  border-radius: 999px;
}

.component-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 12px;
}

.component-card {
  min-height: 250px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--cw-border);
  border-radius: var(--component-radius);
  background: rgba(255, 255, 255, 0.9);
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.component-card:hover {
  border-color: #bfd1ff;
  background: #fbfdff;
  box-shadow: 0 10px 26px rgba(37, 99, 235, 0.07);
}

.card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.card-badges,
.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.component-card h3 {
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 20px;
  line-height: 1.2;
}

.component-card p {
  margin: 0;
  color: var(--cw-muted);
}

.model-line {
  min-height: 22px;
  color: #475467;
  font-weight: 600;
}

.ai-line {
  flex: 1;
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.55;
}

.card-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 28px;
}

.mini-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  min-height: 26px;
  padding: 3px 8px;
  border: 1px solid var(--cw-border);
  border-radius: 10px;
  color: #1f2937;
  font-size: 12px;
  line-height: 1.2;
}

.mini-chip small {
  color: #667085;
  font-size: 11px;
}

.mini-chip.tone-amber {
  border-style: dashed;
  border-color: #fbbf24;
}

.card-links,
.detail-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.card-links {
  margin-top: -4px;
}

.stock-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid #eef2f7;
  color: var(--cw-muted);
}

.stock-row strong {
  color: var(--cw-text);
}

.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 8px 0 2px;
  overflow-x: auto;
}

.empty-search {
  padding: 22px;
  border: 1px solid var(--cw-border);
  border-radius: var(--component-section-radius);
  background: #fff;
}

.empty-copy {
  display: grid;
  gap: 4px;
  color: var(--cw-muted);
}

.empty-copy strong {
  color: var(--cw-text);
}

.empty-actions,
.suggestion-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

.suggestion-loading {
  margin-top: 12px;
  text-align: center;
  color: var(--cw-muted);
}

.suggestion-list {
  margin-top: 14px;
  align-items: stretch;
}

.suggestion-card {
  width: min(280px, 100%);
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid #dbe5ff;
  border-radius: var(--component-radius);
  background: #f8fbff;
}

.suggestion-card span {
  color: var(--cw-muted);
  font-size: 13px;
  line-height: 1.45;
}

.detail-summary {
  max-width: 100%;
  padding: 18px;
  border: 1px solid #e6ecf5;
  border-radius: var(--component-section-radius);
  background: linear-gradient(180deg, #ffffff, #f8fbff);
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

.detail-summary h2 {
  margin: 12px 0 8px;
  color: #101828;
  font-size: clamp(22px, 4vw, 30px);
  line-height: 1.12;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.detail-summary p {
  margin: 0 0 12px;
  color: #344054;
  line-height: 1.62;
  overflow-wrap: anywhere;
}

.detail-model {
  margin: -2px 0 8px;
  color: var(--cw-muted) !important;
  font-weight: 650;
}

.spec-chip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr));
  gap: 10px;
  margin: 16px 0;
}

.unit-hints {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 12px 0;
  padding: 10px 12px;
  border: 1px solid #bae6fd;
  border-radius: var(--component-radius);
  background: #f0f9ff;
}

.unit-hints strong {
  flex: 0 0 auto;
  color: #075985;
  font-size: 13px;
  white-space: nowrap;
}

.unit-hints span {
  flex: 0 1 auto;
  max-width: 100%;
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 9px;
  border: 1px solid #7dd3fc;
  border-radius: 999px;
  background: #fff;
  color: #0f172a;
  font-weight: 650;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.spec-chip {
  display: flex;
  min-width: 0;
  min-height: 66px;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  padding: 10px 12px;
  border: 1px solid #e6ebf2;
  border-radius: var(--component-radius);
  background: #fff;
}

.spec-chip small,
.mini-specs small {
  color: #667085;
  font-size: 12px;
}

.spec-chip strong,
.mini-specs b {
  color: #111827;
  font-size: 16px;
  line-height: 1.25;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.detail-summary .tag-row,
.detail-links {
  align-items: flex-start;
  margin-top: 14px;
}

.detail-summary :deep(.el-tag) {
  max-width: 100%;
  height: auto;
  min-height: 28px;
  overflow-wrap: anywhere;
}

.drawer-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(128px, max-content));
  gap: 8px;
  margin: 14px 0;
}

.drawer-actions .el-button {
  margin-left: 0;
}

.ai-section,
.edit-form {
  margin-top: 14px;
}

.ai-section h3 {
  margin: 0 0 10px;
}

.knowledge-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 10px;
}

.ai-usage-text {
  margin: 0 0 12px;
  padding: 16px 18px;
  border: 1px solid #dbeafe;
  border-radius: var(--component-radius);
  background: linear-gradient(135deg, #eff6ff, #ffffff 68%);
  color: #1f2937;
  line-height: 1.65;
}

.knowledge-box {
  position: relative;
  overflow: hidden;
  padding: 16px 18px;
  border: 1px solid #e6ebf2;
  border-radius: var(--component-radius);
  background: #fbfcfe;
}

.knowledge-box::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 5px;
  background: var(--tone, #3b82f6);
}

.knowledge-box strong {
  display: block;
  margin-bottom: 8px;
  color: #111827;
  font-size: 16px;
}

.knowledge-box ul {
  margin: 0;
  padding-left: 18px;
}

.knowledge-box li {
  margin: 6px 0;
  color: #344054;
  line-height: 1.6;
}

.knowledge-box li::marker {
  color: var(--tone, #3b82f6);
}

.mini-specs {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
}

.mini-specs span {
  display: flex;
  min-height: 58px;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 9px 11px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: var(--component-radius);
  background: rgba(255, 255, 255, 0.75);
}

.tone-blue {
  --tone: #2563eb;
  background: linear-gradient(135deg, #eff6ff, #ffffff 70%);
  border-color: #bfdbfe;
}

.tone-green {
  --tone: #16a34a;
  background: linear-gradient(135deg, #ecfdf3, #ffffff 70%);
  border-color: #bbf7d0;
}

.tone-indigo {
  --tone: #4f46e5;
  background: linear-gradient(135deg, #eef2ff, #ffffff 70%);
  border-color: #c7d2fe;
}

.tone-red {
  --tone: #dc2626;
  background: linear-gradient(135deg, #fff1f2, #ffffff 72%);
  border-color: #fecdd3;
}

.tone-amber {
  --tone: #d97706;
  background: linear-gradient(135deg, #fffbeb, #ffffff 72%);
  border-color: #fde68a;
}

.tone-purple {
  --tone: #9333ea;
  background: linear-gradient(135deg, #faf5ff, #ffffff 72%);
  border-color: #e9d5ff;
}

.tone-cyan {
  --tone: #0891b2;
  background: linear-gradient(135deg, #ecfeff, #ffffff 72%);
  border-color: #a5f3fc;
}

.tone-slate {
  --tone: #475569;
  background: linear-gradient(135deg, #f8fafc, #ffffff 72%);
  border-color: #cbd5e1;
}

.tone-stone {
  --tone: #78716c;
  background: linear-gradient(135deg, #fafaf9, #ffffff 72%);
  border-color: #e7e5e4;
}

pre {
  margin: 8px 0 0;
  padding: 10px;
  white-space: pre-wrap;
  border-radius: 12px;
  background: #f8fafc;
  color: #344054;
}

.import-alert {
  margin-bottom: 12px;
}

:deep(.el-drawer__body) {
  overflow-x: hidden;
}

@media (max-width: 980px) {
  .filter-panel {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 620px) {
  .filter-panel {
    grid-template-columns: 1fr;
  }

  .filter-panel > * {
    width: 100%;
  }

  .component-grid {
    grid-template-columns: 1fr;
  }

  .component-card {
    min-height: auto;
  }

  .detail-summary {
    padding: 14px;
  }

  .spec-chip-grid,
  .knowledge-grid,
  .mini-specs {
    grid-template-columns: 1fr;
  }

  .unit-hints strong {
    flex-basis: 100%;
  }

  .drawer-actions {
    grid-template-columns: 1fr 1fr;
  }

  .drawer-actions .el-button {
    width: 100%;
  }

  .card-top {
    align-items: flex-start;
  }

  .card-badges {
    justify-content: flex-start;
  }

  .stock-row {
    gap: 10px;
  }
}

@media (max-width: 420px) {
  .drawer-actions {
    grid-template-columns: 1fr;
  }
}
</style>
