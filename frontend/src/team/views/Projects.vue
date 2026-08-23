<template>
  <div class="team-projects">
    <header class="page-head">
      <div><span class="eyebrow">TEAM PROJECTS</span><h1>项目与 BOM</h1><p>团队项目直接预占来源成员的实时个人库存。</p></div>
      <el-button type="primary" @click="projectDialog = true">新建项目</el-button>
    </header>
    <div class="layout">
      <aside class="project-list panel">
        <button v-for="project in projects" :key="project.id" :class="{ active: current?.id === project.id }" @click="selectProject(project)">
          <strong>{{ project.name }}</strong><span>{{ statusLabel(project.status) }}</span>
        </button>
        <el-empty v-if="!projects.length" description="暂无项目" :image-size="56" />
      </aside>
      <main v-if="current" class="project-main">
        <section class="panel project-head">
          <div><el-tag>{{ statusLabel(current.status) }}</el-tag><h2>{{ current.name }}</h2><p>{{ current.description || '暂无说明' }}</p></div>
          <div class="actions">
            <el-button @click="bomDialog = true">添加物料</el-button>
            <el-button type="warning" plain @click="createPurchasePlan">生成采购计划</el-button>
            <el-upload :show-file-list="false" accept=".csv,.xls,.xlsx" :http-request="uploadBom"><el-button type="primary" :loading="importing">导入 AD BOM</el-button></el-upload>
            <el-upload :show-file-list="false" accept=".PrjPcb,.SchDoc,.PcbDoc,.OutJob,.ZIP,.PDF,.PNG,.JPG,.JPEG" :http-request="uploadProjectFile">
              <el-button :loading="projectFileUploading">项目附件</el-button>
            </el-upload>
            <el-button @click="downloadProjectCsv(false)">导出 BOM</el-button>
            <el-button @click="downloadProjectCsv(true)">导出缺料</el-button>
          </div>
        </section>
        <nav class="workspace-nav" aria-label="团队项目工作区">
          <button v-for="item in workspaceOptions" :key="item.value" type="button" :class="{ active: workspaceTab === item.value }" @click="workspaceTab = item.value">
            <strong>{{ item.label }}</strong><small>{{ item.hint }}</small>
          </button>
        </nav>
        <AssemblyWorkbench
          v-show="workspaceTab === 'assembly' || workspaceTab === 'files'"
          :key="`team-assembly-${current.id}`"
          :project-id="current.id"
          :library-id="libraryId"
          @changed="load"
        />
        <section v-show="workspaceTab === 'bom'" class="metrics">
          <article><span>BOM 种类</span><strong>{{ current.bom_items?.length || 0 }}</strong></article>
          <article><span>总数量</span><strong>{{ totalQuantity }}</strong></article>
          <article><span>缺料</span><strong>{{ current.bom_items?.filter(item => !item.enough).length || 0 }}</strong></article>
          <article><span>工程风险</span><strong>{{ currentProjectRisks.length }}</strong></article>
          <article><span>待确认行</span><strong>{{ current.bom_match_review || 0 }}</strong></article>
          <article><span>未匹配行</span><strong>{{ current.bom_match_missing || 0 }}</strong></article>
        </section>
        <section v-show="workspaceTab === 'bom'" class="panel">
          <el-table :data="current.bom_items" empty-text="暂无 BOM 物料">
            <el-table-column label="物料" min-width="220"><template #default="{ row }"><strong>{{ row.component.model || row.component.name }}</strong><small>{{ row.component.warehouse_code }}</small></template></el-table-column>
            <el-table-column prop="required_quantity" label="需求" width="80" />
            <el-table-column prop="available_quantity" label="可用" width="80" />
            <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.enough ? 'success' : 'danger'">{{ row.enough ? '充足' : `缺 ${row.shortage_quantity}` }}</el-tag></template></el-table-column>
            <el-table-column prop="remark" label="位号/备注" min-width="220" show-overflow-tooltip />
          </el-table>
        </section>
        <section v-show="workspaceTab === 'risk'" class="panel">
          <div class="section-head"><strong>当前项目工程风险</strong><span>{{ currentProjectRisks.length }} 项</span></div>
          <div v-if="currentProjectRisks.length" class="risk-chips">
            <span v-for="risk in currentProjectRisks.slice(0, 12)" :key="risk.id" :class="risk.severity">{{ risk.title }} · {{ risk.component_name || risk.project_name || '项目' }}</span>
          </div>
          <el-empty v-else description="当前 BOM 未发现封装、资料、料号或匹配风险" :image-size="52" />
        </section>
        <section v-show="workspaceTab === 'files'" class="panel">
          <div class="section-head"><strong>项目文件与附件</strong><span>{{ projectAssets.length }} 个</span></div>
          <div v-if="projectAssets.length" class="asset-chips">
            <button v-for="asset in projectAssets" :key="asset.id" type="button" @click="downloadProjectAsset(asset)">
              <strong>{{ asset.original_name }}</strong><small>{{ asset.asset_type }} · {{ formatBytes(asset.byte_size) }}</small>
            </button>
          </div>
          <el-empty v-else description="暂无项目原生文件或附件" :image-size="52" />
        </section>
      </main>
      <el-empty v-else class="panel" description="请选择或创建项目" />
    </div>

    <el-dialog v-model="projectDialog" title="新建团队项目" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="projectForm.name" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="projectForm.status"><el-option v-for="item in statuses" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
        <el-form-item label="说明"><el-input v-model="projectForm.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="projectDialog = false">取消</el-button><el-button type="primary" @click="saveProject">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="bomDialog" title="添加团队库物料" width="520px">
      <el-form label-width="90px">
        <el-form-item label="元器件">
          <el-select v-model="bomForm.component_id" filterable style="width: 100%">
            <el-option v-for="item in components" :key="item.cw_component_id" :label="`${item.model || item.name} · ${item.warehouse_code || ''}`" :value="item.cw_component_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="需求数量"><el-input-number v-model="bomForm.required_quantity" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="备注/位号"><el-input v-model="bomForm.remark" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="bomDialog = false">取消</el-button><el-button type="primary" @click="saveBomItem">添加</el-button></template>
    </el-dialog>

    <el-dialog v-model="matchDialog" title="BOM 精确匹配结果" width="min(1100px, 96vw)">
      <el-alert type="info" :closable="false">只有料号精确命中或“类别+规范值+标准封装”唯一精确命中的行会自动选择；其余必须人工确认。</el-alert>
      <el-table :data="matchResult.rows || []" max-height="560">
        <el-table-column prop="designator" label="位号" width="130" />
        <el-table-column label="BOM" min-width="220"><template #default="{ row }">{{ row.manufacturer_part || row.value || row.comment }} · {{ row.footprint }}</template></el-table-column>
        <el-table-column prop="required_quantity" label="数量" width="70" />
        <el-table-column label="结果" width="130"><template #default="{ row }"><el-tag :type="row.selected_component_id ? 'success' : row.matches?.length ? 'warning' : 'danger'">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column label="候选与人工确认" min-width="300">
          <template #default="{ row }">
            <el-select v-if="row.matches?.length" v-model="row.manual_component_id" clearable filterable placeholder="请选择确定元件" style="width: 100%">
              <el-option
                v-for="candidate in row.matches"
                :key="candidate.component.id"
                :label="`${candidate.component.model || candidate.component.name} · ${candidate.reason}`"
                :value="candidate.component.id"
              />
            </el-select>
            <span v-else>无候选，需先在团队器件库补充元件</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="matchDialog = false">稍后处理</el-button>
        <el-button type="primary" :loading="committing" @click="commitImport">确认并写入项目 BOM</el-button>
      </template>
    </el-dialog>
    <BomFieldMappingDialog
      v-model="mappingDialog"
      :inspection="bomInspection"
      :file-name="pendingBomFile?.name || ''"
      :loading="importing"
      @confirm="confirmBomMapping"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from '../../shared/elementApi'
import BomFieldMappingDialog from '../../shared/components/BomFieldMappingDialog.vue'
import AssemblyWorkbench from '../../shared/components/AssemblyWorkbench.vue'
import {
  addTeamBomItem,
  commitTeamBom,
  createTeamProject,
  downloadEdaAsset,
  exportTeamProjectBom,
  generateProjectPurchase,
  importTeamBom,
  inspectTeamBom,
  listEntityAssets,
  listRisks,
  listTeamProjects,
  publishEdaAsset,
  stageEdaUpload
} from '../../shared/engineeringApi'
import { listComponents } from '../api'

const route = useRoute()
const libraryId = computed(() => String(route.params.libraryId || ''))
const projects = ref([])
const current = ref(null)
const workspaceTab = ref('assembly')
const workspaceOptions = [
  { label: '装配工作台', value: 'assembly', hint: '板图与焊接' },
  { label: 'BOM / 匹配', value: 'bom', hint: '库存与位号' },
  { label: '采购与风险', value: 'risk', hint: '缺料和风险' },
  { label: '文件版本', value: 'files', hint: '制造包与附件' }
]
const components = ref([])
const importing = ref(false)
const committing = ref(false)
const projectAssets = ref([])
const projectFileUploading = ref(false)
const engineeringRisks = ref([])
const projectDialog = ref(false)
const bomDialog = ref(false)
const matchDialog = ref(false)
const mappingDialog = ref(false)
const matchResult = ref({})
const bomInspection = ref({})
const pendingBomFile = ref(null)
const projectForm = reactive({ name: '', description: '', status: 'draft' })
const bomForm = reactive({ component_id: null, required_quantity: 1, remark: '' })
const statuses = [
  { label: '草稿', value: 'draft' }, { label: '设计中', value: 'designing' }, { label: '待采购', value: 'purchasing' },
  { label: '打板中', value: 'fabricating' }, { label: '装配调试', value: 'assembly' }, { label: '已完成', value: 'completed' }, { label: '已归档', value: 'archived' }
]
const totalQuantity = computed(() => (current.value?.bom_items || []).reduce((sum, item) => sum + Number(item.required_quantity || 0), 0))
const currentProjectRisks = computed(() => {
  const componentIds = new Set((current.value?.bom_items || []).map((item) => item.component_id))
  return engineeringRisks.value.filter(
    (item) => item.project_id === current.value?.id || (item.component_id && componentIds.has(item.component_id))
  )
})
const statusLabel = (status) => statuses.find((item) => item.value === status)?.label || status
onMounted(load)
async function load() {
  const [projectRows, componentRows, risks] = await Promise.all([
    listTeamProjects(libraryId.value),
    listComponents(libraryId.value, { page: 1, page_size: 500 }),
    listRisks(libraryId.value)
  ])
  projects.value = projectRows
  components.value = componentRows.items || []
  engineeringRisks.value = risks.items || []
  current.value = projectRows.find((item) => item.id === current.value?.id) || projectRows[0] || null
  await loadProjectAssets()
}
async function selectProject(project) {
  current.value = project
  await loadProjectAssets()
}
async function saveProject() {
  if (!projectForm.name.trim()) return ElMessage.warning('请填写项目名称')
  const project = await createTeamProject(libraryId.value, projectForm)
  projectDialog.value = false
  await load()
  current.value = projects.value.find((item) => item.id === project.id) || project
}
async function saveBomItem() {
  if (!bomForm.component_id) return ElMessage.warning('请选择元器件')
  await addTeamBomItem(libraryId.value, current.value.id, bomForm)
  bomDialog.value = false
  await load()
}
async function uploadBom(options) {
  importing.value = true
  try {
    pendingBomFile.value = options.file
    bomInspection.value = await inspectTeamBom(libraryId.value, current.value.id, options.file)
    if (!bomInspection.value.headers?.length) throw new Error('未找到可识别的 BOM 表头')
    mappingDialog.value = true
  } catch (error) { ElMessage.error(error.response?.data?.detail || error.message || 'BOM 字段读取失败') }
  finally { importing.value = false }
}
async function confirmBomMapping(mapping) {
  importing.value = true
  try {
    const result = await importTeamBom(libraryId.value, current.value.id, pendingBomFile.value, mapping)
    result.rows = (result.rows || []).map((row) => ({
      ...row,
      manual_component_id: row.selected_component_id || null
    }))
    matchResult.value = result
    mappingDialog.value = false
    matchDialog.value = true
    await load()
  } catch (error) { ElMessage.error(error.response?.data?.detail || 'BOM 导入失败') }
  finally { importing.value = false }
}
async function commitImport() {
  const items = (matchResult.value.rows || [])
    .filter((row) => row.id && row.manual_component_id)
    .map((row) => ({ row_id: row.id, component_id: row.manual_component_id }))
  if (!items.length) return ElMessage.warning('至少确认一个 BOM 元件')
  committing.value = true
  try {
    await commitTeamBom(libraryId.value, current.value.id, matchResult.value.batch_id, items)
    matchDialog.value = false
    ElMessage.success('已写入团队项目 BOM')
    await load()
  } catch (error) { ElMessage.error(error.response?.data?.detail || '提交 BOM 失败') }
  finally { committing.value = false }
}
async function loadProjectAssets() {
  if (!current.value?.id) {
    projectAssets.value = []
    return
  }
  try { projectAssets.value = await listEntityAssets('project', String(current.value.id), libraryId.value) }
  catch { projectAssets.value = [] }
}
async function uploadProjectFile(options) {
  if (!current.value?.id) return ElMessage.warning('请先选择项目')
  projectFileUploading.value = true
  try {
    const stage = await stageEdaUpload(options.file, libraryId.value)
    await publishEdaAsset({
      upload_token: stage.token,
      verification_status: 'raw',
      entity_type: 'project',
      entity_id: String(current.value.id),
      relation_type: 'project_attachment'
    }, libraryId.value)
    await loadProjectAssets()
    ElMessage.success('项目附件已上传')
  } catch (error) { ElMessage.error(error.response?.data?.detail || '项目附件上传失败') }
  finally { projectFileUploading.value = false }
}
async function downloadProjectAsset(asset) {
  const blob = await downloadEdaAsset(asset.id, libraryId.value)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = asset.original_name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function createPurchasePlan() {
  if (!current.value?.id) return
  try {
    const order = await generateProjectPurchase(current.value.id, {}, libraryId.value)
    ElMessage.success(`采购计划已生成，共 ${order.lines?.length || 0} 项`)
    await load()
  } catch (error) { ElMessage.error(error.response?.data?.detail || '生成采购计划失败') }
}
async function downloadProjectCsv(shortageOnly) {
  const blob = await exportTeamProjectBom(libraryId.value, current.value.id, shortageOnly)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${current.value.name}-${shortageOnly ? 'shortage' : 'bom'}.csv`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}
</script>

<style scoped>
.team-projects { display: grid; gap: 16px; }.page-head, .project-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }.page-head h1, .project-head h2 { margin: 5px 0; }.page-head p, .project-head p { margin: 0; color: #667085; }.eyebrow { color: #f97316; font-size: 12px; font-weight: 800; letter-spacing: .12em; }
.workspace-nav { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:7px; padding:7px; border:1px solid #e4eaf2; border-radius:var(--cw-radius-card); background:#fff; position:sticky; top:68px; z-index:20; }.workspace-nav button{border:0;background:transparent;border-radius:9px;padding:8px;display:flex;justify-content:center;align-items:baseline;gap:7px;color:#475569;cursor:pointer}.workspace-nav button.active{background:#ea580c;color:#fff;box-shadow:0 5px 14px #ea580c33}.workspace-nav small{color:inherit;opacity:.72}
.layout { display: grid; grid-template-columns: 240px 1fr; gap: 14px; }.panel { padding: 16px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-card); background: #fff; }.project-list { display: grid; align-content: start; gap: 8px; }.project-list button { display: grid; gap: 4px; padding: 12px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-control); background: #fff; text-align: left; cursor: pointer; }.project-list button.active { border-color: #fb923c; background: #fff7ed; }.project-list span, small { color: #667085; }.project-main { display: grid; gap: 12px; }.actions { display: flex; gap: 8px; }.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 9px; }.metrics article { display: grid; gap: 4px; padding: 13px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-control); background: #fff; }.metrics span { color: #667085; }.metrics strong { font-size: 22px; }
.section-head { display: flex; justify-content: space-between; gap: 12px; color: #667085; }.asset-chips { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 9px; margin-top: 12px; }.asset-chips button { display: grid; gap: 4px; padding: 11px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-control); background: #f8fafc; text-align: left; cursor: pointer; }.asset-chips strong { overflow-wrap: anywhere; }.asset-chips small { color: #667085; }.risk-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }.risk-chips span { padding: 6px 9px; border-radius: 999px; background: #fffbeb; color: #92400e; font-size: 12px; }.risk-chips span.danger { background: #fff1f2; color: #b42318; }
@media (max-width: 850px) { .layout { grid-template-columns: 1fr; }.project-list { grid-template-columns: repeat(2, 1fr); }.metrics { grid-template-columns: repeat(2, 1fr); }.page-head, .project-head { display: grid; }.workspace-nav{grid-template-columns:repeat(2,minmax(0,1fr));position:static}.workspace-nav button{flex-direction:column;align-items:center;gap:1px}.actions{flex-wrap:wrap} }
</style>
