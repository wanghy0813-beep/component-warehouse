<template>
  <div class="engineering-page">
    <header class="page-head">
      <div>
        <span class="eyebrow">ALTIUM DESIGNER</span>
        <h1>AD 元件库与工程资料</h1>
        <p>按“上传资料 → 关联元件 → 检查发布”三步，把元件库安全地同步到电脑。</p>
      </div>
      <div class="head-actions">
        <el-button @click="openGuide">查看详细说明</el-button>
        <el-button type="primary" @click="downloadWindowsClient">下载 Windows 同步工具</el-button>
      </div>
    </header>

    <section class="download-note">
      <div><strong>Windows x64 · v0.7.1</strong><span>双击打开中文向导，也支持命令行和计划任务。</span></div>
      <code>SHA-256 可在下载目录中查看</code>
    </section>

    <section class="eda-metric-grid">
      <article><span>资料文件</span><strong>{{ summary.asset_count || 0 }}</strong></article>
      <article><span>已关联元件</span><strong>{{ summary.binding_count || 0 }}</strong></article>
      <article class="warning"><span>待检查</span><strong>{{ summary.raw_count || 0 }}</strong></article>
      <article><span>可正式使用</span><strong>{{ summary.verified_count || 0 }}</strong></article>
      <article><span>已用空间</span><strong>{{ formatBytes(summary.used_bytes) }}</strong><small>/ {{ formatBytes(summary.quota_bytes) }}</small></article>
    </section>

    <nav class="eda-section-nav" aria-label="EDA 操作步骤">
      <button :class="{ active: activeTab === 'upload' }" @click="activeTab = 'upload'"><b>1</b><span>上传资料</span></button>
      <button :class="{ active: activeTab === 'bind' }" @click="activeTab = 'bind'"><b>2</b><span>关联元件</span></button>
      <button :class="{ active: activeTab === 'publish' }" @click="openPublish"><b>3</b><span>检查并发布</span></button>
      <button :class="{ active: activeTab === 'advanced' }" @click="activeTab = 'advanced'"><b>⋯</b><span>高级管理</span></button>
    </nav>

    <template v-if="activeTab === 'upload'">
      <section class="panel step-panel">
        <div class="step-copy">
          <span>第 1 步</span><h2>上传 AD 库和资料</h2>
          <p>支持 SchLib、PcbLib、IntLib、PDF 数据手册、STEP 3D 模型和图片。文件默认进入“待检查”状态。</p>
        </div>
        <div class="upload-panel">
          <el-upload :show-file-list="false" :http-request="uploadFile" accept=".SchLib,.PcbLib,.IntLib,.STEP,.STP,.PDF,.PNG,.JPG,.JPEG,.WEBP,.CSV,.XLS,.XLSX,.ZIP,.PrjPcb,.SchDoc,.PcbDoc,.OutJob">
            <el-button type="primary" :loading="uploading">选择文件上传</el-button>
          </el-upload>
          <el-input v-model="remoteUrl" placeholder="也可以粘贴公开下载链接">
            <template #append><el-button :loading="uploading" @click="downloadRemote">从链接保存</el-button></template>
          </el-input>
        </div>
      </section>
      <section class="panel">
        <div class="section-head"><h2>已上传资料</h2><span>当前工作版本：{{ workspace.version?.version || '准备中' }}</span></div>
        <el-table class="eda-desktop-table" :data="assets" empty-text="还没有资料文件">
          <el-table-column prop="original_name" label="文件名" min-width="220" />
          <el-table-column label="用途" width="120"><template #default="{ row }">{{ assetTypeLabel(row.asset_type) }}</template></el-table-column>
          <el-table-column label="大小" width="110"><template #default="{ row }">{{ formatBytes(row.byte_size) }}</template></el-table-column>
          <el-table-column label="状态" width="130"><template #default="{ row }"><el-tag :type="verificationType(row.verification_status)">{{ verificationLabel(row.verification_status) }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="180"><template #default="{ row }"><el-button size="small" @click="downloadAsset(row)">下载</el-button><el-button v-if="row.status === 'active'" size="small" type="danger" plain @click="archiveAsset(row)">移到回收站</el-button><el-button v-else size="small" @click="restoreAsset(row)">恢复</el-button></template></el-table-column>
        </el-table>
        <div class="eda-mobile-list">
          <article v-for="asset in assets" :key="asset.id">
            <div><strong>{{ asset.original_name }}</strong><span>{{ assetTypeLabel(asset.asset_type) }} · {{ formatBytes(asset.byte_size) }}</span></div>
            <el-tag :type="verificationType(asset.verification_status)">{{ verificationLabel(asset.verification_status) }}</el-tag>
            <div class="card-actions"><el-button size="small" @click="downloadAsset(asset)">下载</el-button><el-button v-if="asset.status === 'active'" size="small" type="danger" plain @click="archiveAsset(asset)">回收站</el-button><el-button v-else size="small" @click="restoreAsset(asset)">恢复</el-button></div>
          </article>
        </div>
      </section>
    </template>

    <template v-else-if="activeTab === 'bind'">
      <section class="panel step-panel">
        <div class="step-copy"><span>第 2 步</span><h2>把资料关联到库存元件</h2><p>搜索名称、器件 ID、厂商型号或 LCSC 编号，然后填写 AD 中实际使用的符号和封装名称。</p></div>
        <el-form class="quick-binding-form" label-position="top">
          <el-form-item label="选择库存元件">
            <el-select v-model="quickBinding.component_id" filterable remote reserve-keyword :remote-method="searchComponents" :loading="componentSearching" placeholder="输入名称、型号、器件 ID 或 LCSC">
              <el-option v-for="item in componentOptions" :key="item.id" :value="item.id" :label="componentOptionLabel(item)" />
            </el-select>
          </el-form-item>
          <el-form-item label="原理图符号（Symbol）"><el-input v-model="quickBinding.symbol_name" placeholder="必须与 SchLib 内名称一致" /></el-form-item>
          <el-form-item label="PCB 封装（Footprint）"><el-input v-model="quickBinding.footprint_name" placeholder="必须与 PcbLib 内名称一致" /></el-form-item>
          <el-form-item label="数据手册"><el-select v-model="quickBinding.datasheet_asset_id" clearable placeholder="可选"><el-option v-for="item in assets.filter(asset => asset.asset_type === 'datasheet')" :key="item.id" :label="item.original_name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="3D 模型"><el-select v-model="quickBinding.model_asset_id" clearable placeholder="可选"><el-option v-for="item in assets.filter(asset => asset.asset_type === 'model')" :key="item.id" :label="item.original_name" :value="item.id" /></el-select></el-form-item>
          <el-button type="primary" :loading="bindingSaving" @click="saveQuickBinding">保存关联</el-button>
        </el-form>
      </section>
      <section class="panel">
        <div class="section-head"><h2>元件关联与检查状态</h2><span>修改已验证关联后会自动退回待检查</span></div>
        <el-table class="eda-desktop-table" :data="bindings" empty-text="还没有关联元件">
          <el-table-column prop="component_id" label="元件 ID" width="100" />
          <el-table-column label="原理图符号" min-width="160"><template #default="{ row }">{{ row.symbol?.name || '未填写' }}</template></el-table-column>
          <el-table-column label="PCB 封装" min-width="180"><template #default="{ row }">{{ row.footprint?.name || '未填写' }}</template></el-table-column>
          <el-table-column label="状态" width="150"><template #default="{ row }"><el-tag :type="verificationType(row.verification_status)">{{ verificationLabel(row.verification_status) }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="120"><template #default="{ row }"><el-button size="small" @click="openVerify(row)">检查</el-button></template></el-table-column>
        </el-table>
        <div class="eda-mobile-list">
          <article v-for="binding in bindings" :key="binding.id">
            <div><strong>元件 #{{ binding.component_id }}</strong><span>{{ binding.symbol?.name || '未填写符号' }} / {{ binding.footprint?.name || '未填写封装' }}</span></div>
            <el-tag :type="verificationType(binding.verification_status)">{{ verificationLabel(binding.verification_status) }}</el-tag>
            <el-button size="small" @click="openVerify(binding)">检查</el-button>
          </article>
        </div>
      </section>
    </template>

    <template v-else-if="activeTab === 'publish'">
      <section class="panel step-panel">
        <div class="step-copy"><span>第 3 步</span><h2>检查风险并发布给 AD 使用</h2><p>发布后版本不可修改，Windows 同步工具只下载已发布版本。存在风险时仍可确认发布，但系统会保留警告。</p></div>
        <div class="publish-summary">
          <div><span>资料文件</span><strong>{{ publishCheck.asset_count || 0 }}</strong></div>
          <div><span>关联元件</span><strong>{{ publishCheck.binding_count || 0 }}</strong></div>
          <div><span>风险</span><strong>{{ publishCheck.risk_count || 0 }}</strong></div>
        </div>
        <div v-if="publishCheck.risks?.length" class="publish-risks">
          <article v-for="(risk, index) in publishCheck.risks" :key="`${risk.type}-${risk.component_id}-${index}`"><strong>{{ risk.message }}</strong><span v-if="risk.component_id">元件 #{{ risk.component_id }}</span></article>
        </div>
        <el-empty v-else description="当前没有发现发布风险" :image-size="60" />
        <el-button type="primary" :disabled="!publishCheck.can_publish" @click="publishWorkspace">确认发布当前版本</el-button>
      </section>
    </template>

    <template v-else>
      <section class="panel advanced-actions">
        <div><h2>高级管理</h2><p>用于管理多个逻辑库、版本、对象名称、供应商料号和同步令牌。日常使用通常不需要进入这里。</p></div>
        <div class="head-actions"><el-button @click="tokenDialog = true">同步令牌</el-button><el-button @click="supplierDialog = true">供应商料号</el-button><el-button @click="bindingDialog = true">传统关联</el-button><el-button type="primary" @click="libraryDialog = true">新建库</el-button></div>
      </section>
      <section class="panel">
        <el-empty v-if="!libraries.length" description="尚未建立 EDA 库" />
        <div v-else class="library-grid">
          <article v-for="library in libraries" :key="library.id" class="library-card">
            <div class="card-head"><div><span>{{ library.category || '通用库' }}</span><h3>{{ library.name }}</h3></div><el-button size="small" @click="openVersion(library)">新版本</el-button></div>
            <p>{{ library.description || '暂无说明' }}</p>
            <div class="version-list">
              <div v-for="version in library.versions || []" :key="version.id"><strong>{{ version.version }}</strong><el-tag size="small" :type="version.status === 'published' ? 'success' : 'warning'">{{ version.status === 'published' ? '已发布' : '工作版本' }}</el-tag><span>{{ version.change_note || '无修改说明' }}</span><el-button v-if="version.status !== 'published'" size="small" @click="openObject(version)">登记对象</el-button><el-button v-if="version.status !== 'published'" size="small" type="primary" @click="publishVersion(version)">发布</el-button></div>
            </div>
          </article>
        </div>
      </section>
    </template>

    <el-dialog v-model="libraryDialog" title="新建 EDA 库" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="libraryForm.name" /></el-form-item>
        <el-form-item label="分类"><el-input v-model="libraryForm.category" placeholder="RLC / Connector / Power..." /></el-form-item>
        <el-form-item label="说明"><el-input v-model="libraryForm.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="libraryDialog = false">取消</el-button><el-button type="primary" @click="saveLibrary">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="versionDialog" title="新建不可变库版本" width="500px">
      <el-form label-width="100px">
        <el-form-item label="版本号"><el-input v-model="versionForm.version" placeholder="例如 1.0.0" /></el-form-item>
        <el-form-item label="修改说明"><el-input v-model="versionForm.change_note" type="textarea" /></el-form-item>
        <el-form-item label="兼容旧版"><el-switch v-model="versionForm.compatible_with_previous" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="versionDialog = false">取消</el-button><el-button type="primary" @click="saveVersion">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="verifyDialog" title="封装验证" width="560px">
      <el-form label-width="100px">
        <el-form-item label="状态">
          <el-select v-model="verifyForm.status"><el-option v-for="status in verificationStates" :key="status" :label="verificationLabel(status)" :value="status" /></el-select>
        </el-form-item>
        <el-form-item label="检查项">
          <el-checkbox v-model="verifyForm.checklist.datasheet_checked">数据手册</el-checkbox>
          <el-checkbox v-model="verifyForm.checklist.symbol_checked">Symbol</el-checkbox>
          <el-checkbox v-model="verifyForm.checklist.footprint_checked">Footprint</el-checkbox>
        </el-form-item>
        <el-form-item label="复核说明"><el-input v-model="verifyForm.note" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="verifyDialog = false">取消</el-button><el-button type="primary" @click="saveVerification">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="objectDialog" title="登记 Symbol / Footprint" width="500px">
      <el-form label-width="90px">
        <el-form-item label="对象类型"><el-radio-group v-model="objectForm.kind"><el-radio-button value="symbols">Symbol</el-radio-button><el-radio-button value="footprints">Footprint</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="对象名称"><el-input v-model="objectForm.name" placeholder="必须与 AD 库内对象名一致" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="objectForm.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="objectDialog = false">取消</el-button><el-button type="primary" @click="saveObject">登记</el-button></template>
    </el-dialog>

    <el-dialog v-model="bindingDialog" title="绑定元件与 AD 对象" width="600px">
      <el-form label-width="110px">
        <el-form-item label="元件数据库 ID"><el-input-number v-model="bindingForm.component_id" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="库版本"><el-select v-model="bindingForm.library_version_id" filterable style="width: 100%" @change="loadObjects"><el-option v-for="option in versionOptions" :key="option.id" :label="option.label" :value="option.id" /></el-select></el-form-item>
        <el-form-item label="Symbol"><el-select v-model="bindingForm.symbol_id" clearable filterable style="width: 100%"><el-option v-for="item in objectOptions.symbols" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="Footprint"><el-select v-model="bindingForm.footprint_id" clearable filterable style="width: 100%"><el-option v-for="item in objectOptions.footprints" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="数据手册"><el-select v-model="bindingForm.datasheet_asset_id" clearable filterable style="width: 100%"><el-option v-for="item in assets.filter(asset => asset.asset_type === 'datasheet')" :key="item.id" :label="item.original_name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="3D 模型"><el-select v-model="bindingForm.model_asset_id" clearable filterable style="width: 100%"><el-option v-for="item in assets.filter(asset => asset.asset_type === 'model')" :key="item.id" :label="item.original_name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="来源"><el-input v-model="bindingForm.source" placeholder="自建 / LCSC / SnapEDA / 旧项目" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="bindingDialog = false">取消</el-button><el-button type="primary" @click="saveBinding">创建绑定</el-button></template>
    </el-dialog>

    <el-dialog v-model="supplierDialog" title="登记供应商料号" width="560px">
      <el-form label-width="110px">
        <el-form-item label="元件数据库 ID"><el-input-number v-model="supplierForm.component_id" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="供应商"><el-input v-model="supplierForm.supplier" placeholder="LCSC / Mouser / DigiKey..." /></el-form-item>
        <el-form-item label="供应商料号"><el-input v-model="supplierForm.supplier_part_number" placeholder="例如 C123456" /></el-form-item>
        <el-form-item label="采购链接"><el-input v-model="supplierForm.purchase_url" /></el-form-item>
        <el-form-item label="参考单价"><el-input-number v-model="supplierForm.unit_price" :min="0" :precision="4" style="width: 100%" /></el-form-item>
        <el-form-item label="设为首选"><el-switch v-model="supplierForm.is_preferred" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="supplierDialog = false">取消</el-button><el-button type="primary" @click="saveSupplierPart">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="tokenDialog" title="创建 AD 本地同步令牌" width="540px">
      <el-alert type="warning" :closable="false" show-icon>令牌只显示一次。请保存到 Windows Credential Manager，不要写入项目文件。</el-alert>
      <el-input v-model="tokenName" placeholder="例如 工作站 AD 同步" />
      <el-input v-if="createdToken" v-model="createdToken" readonly class="token-output" />
      <el-table :data="syncTokens" size="small" class="token-table" empty-text="暂无同步令牌">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="token_prefix" label="前缀" width="120" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.status === 'active'" size="small" type="danger" text @click="revokeToken(row)">撤销</el-button></template></el-table-column>
      </el-table>
      <template #footer><el-button @click="tokenDialog = false">关闭</el-button><el-button type="primary" @click="makeToken">创建令牌</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from '../elementApi'
import {
  archiveEdaAsset,
  createEdaBinding,
  createEdaLibrary,
  createEdaObject,
  createQuickEdaBinding,
  createEdaVersion,
  createSupplierPart,
  createSyncToken,
  downloadEdaAsset,
  engineeringSummary,
  ensureEdaWorkspace,
  checkEdaVersionPublish,
  listEdaAssets,
  listEdaBindings,
  listEdaComponentOptions,
  listEdaLibraries,
  listEdaObjects,
  listSyncTokens,
  publishEdaAsset,
  publishEdaVersion,
  restoreEdaAsset,
  revokeSyncToken,
  stageEdaRemote,
  stageEdaUpload,
  verifyEdaBinding
} from '../engineeringApi'

const route = useRoute()
const router = useRouter()
const libraryId = computed(() => String(route.params.libraryId || ''))
const activeTab = ref('upload')
const summary = ref({})
const workspace = ref({})
const publishCheck = ref({})
const libraries = ref([])
const assets = ref([])
const bindings = ref([])
const uploading = ref(false)
const componentSearching = ref(false)
const bindingSaving = ref(false)
const componentOptions = ref([])
const selectedVersionId = ref('')
const remoteUrl = ref('')
const libraryDialog = ref(false)
const versionDialog = ref(false)
const verifyDialog = ref(false)
const objectDialog = ref(false)
const bindingDialog = ref(false)
const supplierDialog = ref(false)
const tokenDialog = ref(false)
const selectedLibrary = ref(null)
const selectedBinding = ref(null)
const selectedVersion = ref(null)
const tokenName = ref('')
const createdToken = ref('')
const syncTokens = ref([])
const libraryForm = reactive({ name: '', category: '', description: '' })
const versionForm = reactive({ version: '', change_note: '', compatible_with_previous: true })
const verificationStates = ['raw', 'checked', 'tested', 'verified', 'deprecated']
const verifyForm = reactive({
  status: 'checked',
  checklist: { datasheet_checked: false, symbol_checked: false, footprint_checked: false },
  note: ''
})
const objectForm = reactive({ kind: 'symbols', name: '', description: '' })
const bindingForm = reactive({ component_id: null, library_version_id: '', symbol_id: '', footprint_id: '', datasheet_asset_id: '', model_asset_id: '', source: '' })
const supplierForm = reactive({ component_id: null, supplier: 'LCSC', supplier_part_number: '', purchase_url: '', unit_price: null, currency: 'CNY', is_preferred: true })
const quickBinding = reactive({ component_id: null, symbol_name: '', footprint_name: '', datasheet_asset_id: '', model_asset_id: '', source: '自建' })
const objectOptions = reactive({ symbols: [], footprints: [] })

const versionOptions = computed(() =>
  libraries.value.flatMap((library) =>
    (library.versions || []).map((version) => ({ id: version.id, label: `${library.name} · ${version.version}` }))
  )
)

onMounted(load)

async function load() {
  try {
    let workspaceData = {}
    try {
      workspaceData = await ensureEdaWorkspace(libraryId.value)
    } catch (error) {
      if (error.response?.status !== 403) throw error
    }
    const [summaryData, libraryData, assetData, bindingData, tokenData] = await Promise.all([
      engineeringSummary(libraryId.value),
      listEdaLibraries(libraryId.value),
      listEdaAssets(libraryId.value),
      listEdaBindings(null, libraryId.value),
      listSyncTokens(libraryId.value)
    ])
    summary.value = summaryData
    libraries.value = libraryData
    if (!workspaceData.version) {
      const version = libraryData.flatMap((library) => library.versions || []).find((item) => item.status !== 'published')
      workspaceData = version ? { version } : {}
    }
    workspace.value = workspaceData
    selectedVersionId.value = workspaceData.version?.id || ''
    assets.value = assetData
    bindings.value = bindingData
    syncTokens.value = tokenData
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '读取 EDA 工程数据失败')
  }
}

function verificationLabel(status) {
  return ({ raw: '待检查（Raw）', checked: '已对照资料（Checked）', tested: '已实测（Tested）', verified: '可正式使用（Verified）', deprecated: '不再推荐（Deprecated）' })[status] || status
}
function assetTypeLabel(type) {
  return ({ library: 'AD 库文件', archive: '集成库/压缩包', datasheet: '数据手册', model: '3D 模型', image: '图片', table: '表格', project: 'AD 项目文件' })[type] || type
}
function componentOptionLabel(item) {
  return [item.warehouse_code, item.name, item.model, item.lcsc_number].filter(Boolean).join(' · ')
}
async function searchComponents(query) {
  componentSearching.value = true
  try { componentOptions.value = await listEdaComponentOptions(query, libraryId.value) } finally { componentSearching.value = false }
}
async function saveQuickBinding() {
  if (!quickBinding.component_id) return ElMessage.warning('请先选择库存元件')
  if (!quickBinding.symbol_name.trim() && !quickBinding.footprint_name.trim()) return ElMessage.warning('请至少填写原理图符号或 PCB 封装')
  bindingSaving.value = true
  try {
    await createQuickEdaBinding({
      ...quickBinding,
      library_version_id: workspace.value.version?.id || null,
      datasheet_asset_id: quickBinding.datasheet_asset_id || null,
      model_asset_id: quickBinding.model_asset_id || null
    }, libraryId.value)
    Object.assign(quickBinding, { component_id: null, symbol_name: '', footprint_name: '', datasheet_asset_id: '', model_asset_id: '', source: '自建' })
    ElMessage.success('元件关联已保存，状态为待检查')
    await load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存元件关联失败')
  } finally {
    bindingSaving.value = false
  }
}
async function openPublish() {
  activeTab.value = 'publish'
  if (!workspace.value.version?.id) return
  try { publishCheck.value = await checkEdaVersionPublish(workspace.value.version.id, libraryId.value) } catch (error) { ElMessage.error(error.response?.data?.detail || '发布检查失败') }
}
async function publishWorkspace() {
  const version = workspace.value.version
  if (!version?.id) return
  const riskText = publishCheck.value.risk_count ? `当前还有 ${publishCheck.value.risk_count} 项风险。` : ''
  await ElMessageBox.confirm(`${riskText}发布后该版本不能再修改，确认继续？`, '发布给 AD 使用', { type: publishCheck.value.risk_count ? 'warning' : 'success' })
  await publishEdaVersion(version.id, libraryId.value, Boolean(publishCheck.value.risk_count))
  ElMessage.success('版本已发布，Windows 客户端现在可以同步')
  await load()
  await openPublish()
}
function downloadWindowsClient() {
  window.location.href = '/component-warehouse/downloads/ComponentWarehouse-AD-Sync-latest-win-x64.zip'
}
function openGuide() {
  router.push(libraryId.value ? `/library/${libraryId.value}/eda-guide` : '/eda-guide')
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}
function verificationType(status) {
  return ({ verified: 'success', tested: 'success', checked: 'primary', raw: 'warning', deprecated: 'danger' })[status] || 'info'
}
async function saveLibrary() {
  if (!libraryForm.name.trim()) return ElMessage.warning('请填写库名称')
  await createEdaLibrary(libraryForm, libraryId.value)
  Object.assign(libraryForm, { name: '', category: '', description: '' })
  libraryDialog.value = false
  await load()
}
function openVersion(library) {
  selectedLibrary.value = library
  Object.assign(versionForm, { version: '', change_note: '', compatible_with_previous: true })
  versionDialog.value = true
}
async function saveVersion() {
  if (!versionForm.version.trim()) return ElMessage.warning('请填写版本号')
  await createEdaVersion(selectedLibrary.value.id, versionForm, libraryId.value)
  versionDialog.value = false
  await load()
}
async function publishVersion(version) {
  workspace.value = { ...workspace.value, version }
  await openPublish()
}
function openObject(version) {
  selectedVersion.value = version
  Object.assign(objectForm, { kind: 'symbols', name: '', description: '' })
  objectDialog.value = true
}
async function saveObject() {
  if (!objectForm.name.trim()) return ElMessage.warning('请填写对象名称')
  await createEdaObject(selectedVersion.value.id, objectForm.kind, { name: objectForm.name, description: objectForm.description }, libraryId.value)
  objectDialog.value = false
  ElMessage.success('AD 对象已登记')
}
async function loadObjects(versionId) {
  Object.assign(objectOptions, { symbols: [], footprints: [] })
  bindingForm.symbol_id = ''
  bindingForm.footprint_id = ''
  if (!versionId) return
  Object.assign(objectOptions, await listEdaObjects(versionId, libraryId.value))
}
async function saveBinding() {
  if (!bindingForm.component_id) return ElMessage.warning('请填写元件数据库 ID')
  await createEdaBinding({
    ...bindingForm,
    library_version_id: bindingForm.library_version_id || null,
    symbol_id: bindingForm.symbol_id || null,
    footprint_id: bindingForm.footprint_id || null,
    datasheet_asset_id: bindingForm.datasheet_asset_id || null,
    model_asset_id: bindingForm.model_asset_id || null
  }, libraryId.value)
  bindingDialog.value = false
  Object.assign(bindingForm, { component_id: null, library_version_id: '', symbol_id: '', footprint_id: '', datasheet_asset_id: '', model_asset_id: '', source: '' })
  await load()
}
async function saveSupplierPart() {
  if (!supplierForm.component_id || !supplierForm.supplier.trim() || !supplierForm.supplier_part_number.trim()) {
    return ElMessage.warning('请填写元件 ID、供应商和供应商料号')
  }
  await createSupplierPart({
    ...supplierForm,
    purchase_url: supplierForm.purchase_url.trim() || null
  }, libraryId.value)
  supplierDialog.value = false
  Object.assign(supplierForm, { component_id: null, supplier: 'LCSC', supplier_part_number: '', purchase_url: '', unit_price: null, currency: 'CNY', is_preferred: true })
  ElMessage.success('供应商料号已登记')
}
async function publishStage(stage, sourceUrl = '') {
  await publishEdaAsset({
    upload_token: stage.token,
    library_version_id: selectedVersionId.value || null,
    source_url: sourceUrl || stage.source_url || null,
    verification_status: 'raw'
  }, libraryId.value)
  ElMessage.success('文件已保存为待检查资料')
  await load()
}
async function uploadFile(options) {
  uploading.value = true
  try {
    const stage = await stageEdaUpload(options.file, libraryId.value)
    await publishStage(stage)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'EDA 文件上传失败')
  } finally {
    uploading.value = false
  }
}
async function downloadRemote() {
  if (!remoteUrl.value.trim()) return ElMessage.warning('请填写公开文件 URL')
  uploading.value = true
  try {
    const stage = await stageEdaRemote(remoteUrl.value.trim(), libraryId.value)
    await publishStage(stage, remoteUrl.value.trim())
    remoteUrl.value = ''
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '公开文件下载失败')
  } finally {
    uploading.value = false
  }
}
async function downloadAsset(asset) {
  const blob = await downloadEdaAsset(asset.id, libraryId.value)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = asset.original_name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function archiveAsset(asset) {
  await ElMessageBox.confirm(`把 ${asset.original_name} 放入 30 天回收站？`, '归档文件')
  await archiveEdaAsset(asset.id, libraryId.value)
  await load()
}
async function restoreAsset(asset) {
  await restoreEdaAsset(asset.id, libraryId.value)
  await load()
}
function openVerify(binding) {
  selectedBinding.value = binding
  Object.assign(verifyForm, {
    status: binding.verification_status || 'checked',
    checklist: { datasheet_checked: false, symbol_checked: false, footprint_checked: false },
    note: ''
  })
  verifyDialog.value = true
}
async function saveVerification() {
  await verifyEdaBinding(selectedBinding.value.id, verifyForm, libraryId.value)
  verifyDialog.value = false
  await load()
}
async function makeToken() {
  if (!tokenName.value.trim()) return ElMessage.warning('请填写令牌名称')
  const result = await createSyncToken({ name: tokenName.value, expires_in_days: 365 }, libraryId.value)
  createdToken.value = result.token
  await load()
  try { await navigator.clipboard.writeText(result.token); ElMessage.success('令牌已复制') } catch {}
}
async function revokeToken(row) {
  await ElMessageBox.confirm(`撤销同步令牌“${row.name}”？已配置的客户端会立即失效。`, '撤销令牌')
  await revokeSyncToken(row.id, libraryId.value)
  await load()
}
</script>

<style scoped>
.engineering-page { min-width: 0; display: grid; gap: 16px; }
.page-head { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
.page-head h1 { margin: 4px 0; color: #17202a; }.page-head p { margin: 0; color: #667085; }
.eyebrow { color: #f97316; font-size: 12px; font-weight: 800; letter-spacing: .12em; }
.head-actions, .upload-panel { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.download-note { min-width: 0; display: flex; justify-content: space-between; gap: 14px; align-items: center; padding: 14px 16px; border: 1px solid #fed7aa; border-radius: 16px; background: #fff7ed; }
.download-note div { min-width: 0; display: grid; gap: 3px; }.download-note span { color: #7c2d12; font-size: 13px; }.download-note code { overflow-wrap: anywhere; color: #9a3412; }
.eda-metric-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.eda-metric-grid article { min-width: 0; display: grid; align-content: center; gap: 4px; min-height: 96px; padding: 15px; border: 1px solid #e4eaf2; border-radius: 16px; background: #fff; }
.eda-metric-grid span, .eda-metric-grid small { color: #667085; }.eda-metric-grid strong { overflow-wrap: anywhere; color: #17202a; font-size: 24px; }
.eda-metric-grid .warning strong { color: #d97706; }
.panel { padding: 16px; border: 1px solid #e4eaf2; border-radius: 16px; background: #fff; }
.eda-section-nav { min-width: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.eda-section-nav button { min-width: 0; display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 48px; padding: 9px 12px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-control); background: #fff; color: #475467; cursor: pointer; }
.eda-section-nav button.active { border-color: #fdba74; background: #fff7ed; color: #c2410c; font-weight: 700; }.eda-section-nav b { display: grid; place-items: center; width: 24px; height: 24px; border-radius: var(--cw-radius-control); background: #f1f5f9; }
.step-panel { display: grid; gap: 18px; }.step-copy span { color: #f97316; font-weight: 800; }.step-copy h2, .section-head h2, .advanced-actions h2 { margin: 4px 0; }.step-copy p, .advanced-actions p { margin: 0; color: #667085; line-height: 1.65; }
.section-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 14px; }.section-head span { color: #667085; font-size: 13px; }
.upload-panel .el-input { min-width: 320px; flex: 1; }
.quick-binding-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }.quick-binding-form :deep(.el-select) { width: 100%; }.quick-binding-form > :last-child { align-self: end; margin-bottom: 18px; }
.publish-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.publish-summary div { display: grid; gap: 4px; padding: 14px; border: 1px solid #e4eaf2; border-radius: 16px; }.publish-summary span { color: #667085; }.publish-summary strong { font-size: 24px; }
.publish-risks { display: grid; gap: 8px; }.publish-risks article { display: flex; justify-content: space-between; gap: 10px; padding: 11px 12px; border: 1px solid #fed7aa; border-radius: var(--cw-radius-control); background: #fffbeb; }.publish-risks span { color: #92400e; font-size: 12px; }
.advanced-actions { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
.eda-mobile-list { display: none; }
.library-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.library-card { padding: 16px; border: 1px solid #e4eaf2; border-radius: 16px; }
.card-head { display: flex; justify-content: space-between; gap: 12px; }.card-head span { color: #f97316; font-size: 12px; }.card-head h3 { margin: 4px 0; }
.library-card p { color: #667085; }.version-list { display: grid; gap: 8px; }
.version-list > div { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 9px; border-radius: var(--cw-radius-control); background: #f8fafc; }
.version-list span { flex: 1; min-width: 120px; color: #667085; }
.token-output { margin-top: 12px; }
.token-table { margin-top: 12px; }
@media (max-width: 900px) {
  .page-head { display: grid; }
  .eda-metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .eda-metric-grid article:last-child { grid-column: 1 / -1; }
  .upload-panel { display: grid; }
  .upload-panel .el-input, .upload-panel .el-select { width: 100%; min-width: 0; }
  .advanced-actions { display: grid; }
}
@media (max-width: 680px) {
  .download-note, .section-head { align-items: stretch; flex-direction: column; }
  .eda-section-nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .eda-section-nav button { justify-content: flex-start; }
  .quick-binding-form { grid-template-columns: 1fr; }
  .publish-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .eda-desktop-table { display: none; }
  .eda-mobile-list { display: grid; gap: 10px; }
  .eda-mobile-list article { min-width: 0; display: grid; gap: 10px; padding: 13px; border: 1px solid #e4eaf2; border-radius: 16px; background: #fff; }
  .eda-mobile-list article > div:first-child { min-width: 0; display: grid; gap: 4px; }.eda-mobile-list strong, .eda-mobile-list span { overflow-wrap: anywhere; }.eda-mobile-list span { color: #667085; font-size: 12px; }
  .card-actions { display: flex; flex-wrap: wrap; gap: 8px; }.card-actions :deep(.el-button + .el-button) { margin-left: 0; }
}
@media (max-width: 380px) {
  .eda-metric-grid, .eda-section-nav, .publish-summary { grid-template-columns: 1fr; }
  .eda-metric-grid article:last-child { grid-column: auto; }
}
</style>
