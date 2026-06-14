<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">项目 BOM</h1>
        <p class="page-subtitle">按分类检查完整度、库存满足率和参数风险</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openProject()">新建项目</el-button>
    </div>

    <div class="bom-layout">
      <aside class="panel project-sidebar" :class="{ folded: projectSidebarFolded }">
        <div class="sidebar-head">
          <h2 v-if="!projectSidebarFolded">项目</h2>
          <el-button size="small" text @click="projectSidebarFolded = !projectSidebarFolded">{{ projectSidebarFolded ? '展开' : '收起' }}</el-button>
        </div>
        <button v-for="project in projects" :key="project.id" class="project-item" :class="{ active: current?.id === project.id }" @click="selectProject(project)">
          <span>{{ projectSidebarFolded ? project.name.slice(0, 1) : project.name }}</span>
          <el-tag v-if="!projectSidebarFolded" :type="shortageCount(project) ? 'danger' : 'success'" size="small">{{ shortageCount(project) ? `缺 ${shortageCount(project)}` : '满足' }}</el-tag>
        </button>
        <el-empty v-if="!projects.length && !projectSidebarFolded" description="暂无项目" :image-size="72" />

        <template v-if="current">
          <h2 v-if="!projectSidebarFolded" class="nav-title">分类</h2>
          <button v-for="group in bomGroups" :key="group.name" class="category-nav" @click="activeCategory = group.name">
            <span>{{ group.name }}</span>
            <small v-if="!projectSidebarFolded">{{ group.satisfied }}/{{ group.items.length }} 满足</small>
          </button>
        </template>
      </aside>

      <main class="bom-main">
        <template v-if="current">
          <div class="panel project-head">
            <div>
              <h2>{{ current.name }}</h2>
              <p>{{ current.description || '无描述' }}</p>
            </div>
            <div class="toolbar">
              <el-button v-if="current.status !== 'completed'" type="success" plain @click="completeProject">完成项目</el-button>
              <el-upload :show-file-list="false" accept=".xlsx,.xls" :http-request="handleBomMatchUpload">
                <el-button :icon="Upload" :loading="matchingBom">导入 BOM</el-button>
              </el-upload>
              <el-button :icon="Download" @click="downloadBom">导出</el-button>
              <el-button type="primary" :icon="Plus" @click="openBom()">添加物料</el-button>
            </div>
          </div>

          <el-alert type="info" show-icon :closable="false" class="bom-help">
            预占会锁定库存但不扣库存；取料会扣减库存并解除预占；整个项目都取完后再点击“完成项目”。
          </el-alert>

          <section class="panel match-progress-panel">
            <div class="match-progress-main">
              <div>
                <span class="eyebrow">BOM 匹配进度</span>
                <h3>{{ projectMatchStats.total ? `${projectMatchStats.rate}% 库内已匹配` : '导入 BOM 后生成匹配进度' }}</h3>
                <p>
                  <template v-if="projectMatchStats.total">
                    共 {{ projectMatchStats.total }} 行，{{ projectMatchStats.matched }} 行可直接使用库存，{{ projectMatchStats.review }} 行需确认，{{ projectMatchStats.missing }} 行待采购
                  </template>
                  <template v-else>上传 BOM 表后，系统会把库内匹配、需确认和待采购项自动拆开。</template>
                </p>
              </div>
              <div class="match-rate">{{ projectMatchStats.rate }}<small>%</small></div>
            </div>
            <div class="segmented-progress">
              <span class="segment matched" :style="{ width: `${projectMatchStats.matchedPercent}%` }"></span>
              <span class="segment review" :style="{ width: `${projectMatchStats.reviewPercent}%` }"></span>
              <span class="segment missing" :style="{ width: `${projectMatchStats.missingPercent}%` }"></span>
            </div>
            <div class="match-kpi-grid">
              <div class="match-kpi tone-green"><span>库内已匹配</span><strong>{{ projectMatchStats.matched }}</strong><small>{{ projectMatchStats.matchedPercent }}%</small></div>
              <div class="match-kpi tone-amber"><span>需确认</span><strong>{{ projectMatchStats.review }}</strong><small>{{ projectMatchStats.reviewPercent }}%</small></div>
              <div class="match-kpi tone-red"><span>待采购</span><strong>{{ projectMatchStats.missing }}</strong><small>{{ projectMatchStats.missingPercent }}%</small></div>
            </div>
            <div v-if="projectMissingItems.length" class="missing-preview">
              <strong>待采购清单</strong>
              <span v-for="item in projectMissingItems.slice(0, 4)" :key="`${item.source_row}-${item.manufacturer_part || item.description}`">
                {{ item.manufacturer_part || item.description || item.value || '未命名物料' }}
              </span>
            </div>
            <div v-if="hasStoredBomMatchBatch" class="match-resume">
              <el-button size="small" plain @click="openStoredBomMatch">继续确认最近导入</el-button>
            </div>
          </section>

          <div class="metric-grid bom-metrics">
            <div class="metric"><div class="metric-label">总物料</div><div class="metric-value">{{ bomStats.total }}</div></div>
            <div class="metric"><div class="metric-label">已满足</div><div class="metric-value">{{ bomStats.satisfied }}</div></div>
            <div class="metric"><div class="metric-label">缺料</div><div class="metric-value">{{ bomStats.shortage }}</div></div>
            <div class="metric"><div class="metric-label">参数风险</div><div class="metric-value">{{ bomStats.risk }}</div></div>
          </div>

          <section v-for="group in visibleBomGroups" :key="group.name" class="panel bom-group">
            <div class="group-head">
              <h3>{{ group.name }}</h3>
              <el-tag :type="group.shortage ? 'danger' : 'success'">{{ group.shortage ? `缺 ${group.shortage} 项` : '全部满足' }}</el-tag>
            </div>
            <div class="bom-card-list">
              <article v-for="item in group.items" :key="item.id" class="bom-card">
                <div>
                  <button class="link-title" @click="openComponentDetail(item.component)">{{ item.component.model || item.component.name }}</button>
                  <p>{{ item.component.name }}</p>
                  <p class="bom-role">{{ bomRole(item) }}</p>
                  <div class="tag-row">
                    <el-tag v-if="item.component.package" size="small">{{ item.component.package }}</el-tag>
                    <el-tag v-if="bomMatchSourceLabel(item)" size="small" :type="bomMatchSourceType(item)">{{ bomMatchSourceLabel(item) }}</el-tag>
                    <el-tag size="small" :type="bomStatusType(item.status)">{{ bomStatusLabel(item.status) }}</el-tag>
                    <el-tag v-if="item.component.ai_confidence === 'low'" size="small" type="warning">参数待核对</el-tag>
                  </div>
                </div>
                <div class="bom-stock">
                  <span>需求 {{ item.required_quantity }}</span>
                  <span>可用 {{ item.available_quantity }}</span>
                  <strong :class="{ danger: !item.enough }">{{ item.enough ? '库存充足' : `缺 ${item.shortage_quantity}` }}</strong>
                </div>
                <div class="bom-actions">
                  <el-button size="small" :disabled="item.status !== 'reserved'" @click="markPicked(item)">取料</el-button>
                  <el-button v-if="item.status === 'done'" size="small" type="warning" @click="convertDoneToPicked(item)">改为已取料</el-button>
                  <el-button size="small" @click="openBom(item)">编辑</el-button>
                  <el-button size="small" type="warning" @click="releaseBom(item)">释放</el-button>
                </div>
              </article>
            </div>
          </section>
        </template>
        <el-empty v-else class="panel" description="请选择或创建项目" />
      </main>

      <aside class="panel ai-bom-panel">
        <h2>AI BOM 助手</h2>
        <template v-if="current">
          <el-input v-model="projectRequirement" type="textarea" :rows="4" placeholder="输入项目目标，例如 USB-C PD 12V 风扇控制板，ESP32 PWM 控制" />
          <div class="toolbar ai-actions">
            <el-button type="primary" :loading="projectAiLoading" @click="runProjectPlan">项目规划</el-button>
            <el-button :loading="bomAiLoading" @click="runBomAnalysis(true)">分析 BOM</el-button>
            <el-button :loading="projectAiLoading" @click="runConsult">咨询优化</el-button>
          </div>
          <div v-if="bomAiResult" class="ai-result">
            <h3>完整度 {{ bomAiResult.completeness || '-' }}%</h3>
            <div class="markdown-body" v-html="renderedMarkdown(bomAiResult)"></div>
            <div class="recommendation-list">
              <article v-for="item in bomAiResult.recommended_existing || []" :key="`bom-${item.component_id}-${item.role}`" class="recommendation-card">
                <strong>{{ componentName(item.component_id) }}</strong>
                <p>{{ item.role }}：{{ item.reason }}</p>
                <el-button size="small" type="primary" @click="addRecommendation(item)">加入 BOM</el-button>
              </article>
              <article v-for="item in bomAiResult.missing_materials || []" :key="`bom-miss-${item.description || item}`" class="recommendation-card missing">
                <strong>{{ item.description || item }}</strong>
                <p>{{ item.reason || '库存中未找到合适物料。' }}</p>
                <el-button size="small" @click="openLcscMissing(item)">立创搜索</el-button>
              </article>
            </div>
            <el-collapse>
              <el-collapse-item title="缺料建议">
                <div class="missing-list">
                  <div v-for="item in bomAiResult.missing_materials || []" :key="item.description || item">
                    <strong>{{ item.description || item }}</strong>
                    <el-button size="small" text @click="openLcscMissing(item)">立创搜索</el-button>
                  </div>
                </div>
              </el-collapse-item>
              <el-collapse-item title="风险提示">
                <pre>{{ pretty(bomAiResult.risk_notes) }}</pre>
              </el-collapse-item>
              <el-collapse-item title="替代与采购">
                <pre>{{ pretty([...(bomAiResult.substitutes || []), ...(bomAiResult.purchase_suggestions || [])]) }}</pre>
              </el-collapse-item>
              <el-collapse-item title="PCB 注意">
                <pre>{{ pretty(bomAiResult.pcb_notes) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div v-if="projectAiResult" class="ai-result">
            <h3>项目规划</h3>
            <div class="markdown-body" v-html="renderedMarkdown(projectAiResult)"></div>
            <div class="recommendation-list">
              <article v-for="item in projectAiResult.recommended_existing || []" :key="`plan-${item.component_id}-${item.role}`" class="recommendation-card">
                <strong>{{ componentName(item.component_id) }}</strong>
                <p>{{ item.role }}：{{ item.reason }}</p>
                <el-button size="small" type="primary" @click="addRecommendation(item)">加入 BOM</el-button>
              </article>
              <article v-for="item in projectAiResult.missing_materials || []" :key="`plan-miss-${item.description || item}`" class="recommendation-card missing">
                <strong>{{ item.description || item }}</strong>
                <p>{{ item.reason || '需要外部采购或进一步确认。' }}</p>
                <el-button size="small" @click="openLcscMissing(item)">立创搜索</el-button>
              </article>
            </div>
          </div>
          <div v-if="consultResult" class="ai-result">
            <h3>AI 咨询</h3>
            <div class="markdown-body" v-html="renderedMarkdown(consultResult)"></div>
            <div class="recommendation-list">
              <article v-for="item in consultResult.recommended_existing || []" :key="`consult-${item.component_id}-${item.role}`" class="recommendation-card">
                <strong>{{ componentName(item.component_id) }}</strong>
                <p>{{ item.role }}：{{ item.reason }}</p>
                <el-button size="small" type="primary" @click="addRecommendation(item)">加入 BOM</el-button>
              </article>
              <article v-for="item in consultResult.missing_materials || []" :key="`consult-miss-${item.description || item}`" class="recommendation-card missing">
                <strong>{{ item.description || item }}</strong>
                <p>{{ item.reason || '需要外部采购或进一步确认。' }}</p>
                <el-button size="small" @click="openLcscMissing(item)">立创搜索</el-button>
              </article>
            </div>
          </div>
        </template>
        <el-empty v-else description="选择项目后可分析" :image-size="72" />
      </aside>
    </div>

    <el-dialog v-model="projectDialog" :title="projectForm.id ? '编辑项目' : '新建项目'" width="480px">
      <el-form label-width="72px" :model="projectForm">
        <el-form-item label="名称" required><el-input v-model="projectForm.name" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="projectForm.status" style="width: 100%">
            <el-option label="进行中" value="active" />
            <el-option label="已完成" value="completed" />
            <el-option label="归档" value="archived" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述"><el-input v-model="projectForm.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="projectDialog = false">取消</el-button>
        <el-button type="primary" @click="submitProject">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bomDialog" :title="bomForm.id ? '编辑 BOM 物料' : '添加 BOM 物料'" width="560px">
      <el-form label-width="86px" :model="bomForm">
        <el-form-item label="快速搜索">
          <el-input v-model="componentKeyword" clearable placeholder="100nF、CH224K、Type-C..." @input="searchComponents" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="componentCategory" clearable style="width: 100%" @change="searchComponents(componentKeyword)">
            <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="元器件" required>
          <el-select v-model="bomForm.component_id" filterable style="width: 100%" :disabled="!!bomForm.id">
            <el-option
              v-for="item in componentOptions"
              :key="item.id"
              :label="`${item.name} ${item.model || ''} / 可用 ${item.available_quantity} / ${item.package || '-'}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="需求数量"><el-input-number v-model="bomForm.required_quantity" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="bomForm.remark" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bomDialog = false">取消</el-button>
        <el-button type="primary" @click="submitBom">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bomMatchDialog" title="BOM AI 库存分拣" width="min(1180px, 96vw)" append-to-body align-center destroy-on-close class="bom-match-dialog">
      <div class="match-summary-grid">
        <div class="match-summary-card"><span>总行数</span><strong>{{ bomMatchStats.total }}</strong></div>
        <div class="match-summary-card tone-green"><span>库内已匹配</span><strong>{{ bomMatchStats.matched }}</strong></div>
        <div class="match-summary-card tone-amber"><span>需确认</span><strong>{{ bomMatchStats.review }}</strong></div>
        <div class="match-summary-card tone-red"><span>待采购</span><strong>{{ bomMatchStats.missing }}</strong></div>
        <div class="match-summary-card tone-blue"><span>待确认导入</span><strong>{{ pendingSelectedBomRows.length }}</strong></div>
      </div>
      <div class="dialog-progress">
        <div class="segmented-progress">
          <span class="segment matched" :style="{ width: `${bomMatchStats.matchedPercent}%` }"></span>
          <span class="segment review" :style="{ width: `${bomMatchStats.reviewPercent}%` }"></span>
          <span class="segment missing" :style="{ width: `${bomMatchStats.missingPercent}%` }"></span>
        </div>
        <span>{{ bomMatchStats.rate }}% 可直接使用库存</span>
      </div>
      <el-alert v-if="bomMatchRows.some((row) => row.ai_error)" type="warning" show-icon :closable="false" class="bom-match-alert">
        部分行 AI 辅助失败，已保留库存预匹配结果；可以继续手动确认或导入已选择项。
      </el-alert>
      <el-tabs v-model="bomMatchTab" class="bom-match-tabs">
        <el-tab-pane :label="`库内已匹配 ${bomMatchBuckets.matched.length}`" name="matched" />
        <el-tab-pane :label="`需确认 ${bomMatchBuckets.review.length}`" name="review" />
        <el-tab-pane :label="`待采购 ${bomMatchBuckets.missing.length}`" name="missing" />
      </el-tabs>
      <el-table :data="activeBomMatchRows" row-key="id" max-height="520" empty-text="当前分栏没有 BOM 行" class="bom-match-table">
        <el-table-column prop="designator" label="位号" min-width="120" />
        <el-table-column prop="required_quantity" label="数量" width="80" />
        <el-table-column label="BOM 指定" min-width="220">
          <template #default="{ row }">
            <strong>{{ row.value || row.manufacturer_part || row.supplier_part || '-' }}</strong>
            <div class="muted compact-meta">
              <span v-if="row.manufacturer_part">型号 {{ row.manufacturer_part }}</span>
              <span v-if="row.footprint">封装 {{ row.footprint }}</span>
              <span v-if="row.supplier_part">立创 {{ row.supplier_part }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="AI 判断 / 采购建议" min-width="280">
          <template #default="{ row }">
            <div class="match-role">{{ row.role }}</div>
            <el-tag size="small" :type="matchStatusType(row.status)">{{ matchStatusLabel(row.status) }}</el-tag>
            <el-tag v-if="row.auto_imported" size="small" type="success" effect="plain">已自动导入</el-tag>
            <el-tag v-if="row.ai_confidence" size="small" effect="plain">{{ row.ai_confidence }}</el-tag>
            <div v-if="row.matches?.[0]?.flags?.length" class="match-flags">
              <el-tag v-for="flag in row.matches[0].flags" :key="flag" size="small" effect="plain" :type="flag.includes('不一致') ? 'danger' : 'success'">{{ flag }}</el-tag>
            </div>
            <div v-if="row.ai_reason" class="match-reason">{{ row.ai_reason }}</div>
            <div v-if="row.auto_import_note" class="match-reason">{{ row.auto_import_note }}</div>
            <div v-if="row.ai_error" class="match-error">{{ row.ai_error }}</div>
            <div v-if="row.missing_suggestion?.alternatives?.length" class="match-alternatives">
              <span v-for="item in row.missing_suggestion.alternatives" :key="item.description">{{ item.description }}</span>
            </div>
            <div class="match-row-actions">
              <el-button v-if="row.missing_suggestion?.lcsc_search_url" size="small" text @click="openUrl(row.missing_suggestion.lcsc_search_url)">缺料搜索</el-button>
              <el-button v-if="canCreatePendingComponent(row)" size="small" text type="primary" @click="createPendingPurchase(row)">加入待采购库</el-button>
              <el-button v-if="canIgnoreBomRow(row)" size="small" text type="warning" @click="ignoreImportRow(row)">忽略此项</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="匹配" min-width="320">
          <template #default="{ row }">
            <el-select
              v-model="row.selected_component_id"
              clearable
              filterable
              remote
              reserve-keyword
              style="width: 100%"
              placeholder="搜索库存或选择推荐"
              :loading="bomMatchOptionLoading[rowKey(row)]"
              :remote-method="(keyword) => searchBomMatchComponents(row, keyword)"
              @visible-change="(visible) => visible && ensureBomMatchOptions(row)"
              @change="(value) => handleBomRowSelection(row, value)"
            >
              <el-option v-for="match in matchSelectOptions(row)" :key="match.component.id" :value="match.component.id" :label="matchOptionLabel(match)" />
            </el-select>
            <div v-if="row.matches?.length" class="match-candidates">
              <span v-for="match in row.matches.slice(0, 3)" :key="match.component.id">{{ match.score }}% · {{ match.reason }}</span>
            </div>
            <div v-else class="missing-text">{{ row.missing_suggestion?.description || '暂无库存候选' }}</div>
            <div class="match-row-actions">
              <el-button size="small" text @click="openStockPicker(row)">更多库存</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button :disabled="!purchaseKeywords.length" :icon="CopyDocument" @click="copyPurchaseKeywords">复制采购关键词</el-button>
        <el-button @click="bomMatchDialog = false">取消</el-button>
        <el-button type="primary" :loading="importingMatchedBom" @click="confirmImportMatches">导入待确认项 {{ pendingSelectedBomRows.length }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="stockPickerDialog" title="从库存选择元器件" width="min(780px, 94vw)" append-to-body destroy-on-close @closed="clearStockPicker">
      <div class="stock-picker-head">
        <el-input v-model="stockPickerKeyword" clearable placeholder="搜索名称、型号、参数、封装、立创编号" @keyup.enter="searchStockPicker" />
        <el-button type="primary" :loading="stockPickerLoading" @click="searchStockPicker">搜索</el-button>
      </div>
      <el-table :data="stockPickerOptions" row-key="id" height="420" empty-text="输入关键词搜索库存">
        <el-table-column label="元器件" min-width="260">
          <template #default="{ row }">
            <strong>{{ row.name }}</strong>
            <div class="muted compact-meta">
              <span v-if="row.model">型号 {{ row.model }}</span>
              <span v-if="row.lcsc_number">立创 {{ row.lcsc_number }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="package" label="封装" width="130" />
        <el-table-column label="库存" width="120">
          <template #default="{ row }">总 {{ row.quantity }} / 可用 {{ row.available_quantity }}</template>
        </el-table-column>
        <el-table-column width="100">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="pickStockComponent(row)">选择</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Download, Plus, Upload } from '@element-plus/icons-vue'
import {
  addBomItem,
  analyzeProjectBom,
  consultProject,
  createPendingComponentFromBomRow,
  deleteBomItem,
  deleteProject,
  exportBom,
  getCategories,
  getComponents,
  getLatestBomImportBatch,
  getProjects,
  ignoreBomImportRow,
  importMatchedBomItems,
  planProject,
  previewBomMatch,
  saveProject,
  updateBomItem,
  updateBomItemStatus
} from '../api/client'
import { componentOneLineUsage, makeLcscSearchUrl, renderAiMarkdown } from '../utils/componentUi'

const loading = ref(false)
const projects = ref([])
const current = ref(null)
const categories = ref([])
const componentOptions = ref([])
const projectDialog = ref(false)
const bomDialog = ref(false)
const bomMatchDialog = ref(false)
const matchingBom = ref(false)
const importingMatchedBom = ref(false)
const bomAiLoading = ref(false)
const projectAiLoading = ref(false)
const bomMatchRows = ref([])
const bomMatchTab = ref('matched')
const latestBomImportBatch = ref(null)
const bomMatchExtraOptions = ref({})
const bomMatchOptionLoading = ref({})
const stockPickerDialog = ref(false)
const stockPickerRow = ref(null)
const stockPickerKeyword = ref('')
const stockPickerLoading = ref(false)
const stockPickerOptions = ref([])
const activeCategory = ref('')
const projectRequirement = ref('')
const projectAiResult = ref(null)
const bomAiResult = ref(null)
const consultResult = ref(null)
const componentKeyword = ref('')
const componentCategory = ref(null)
const router = useRouter()
const projectSidebarFolded = ref(localStorage.getItem('cw_project_sidebar_folded') === '1')

const projectEmpty = { id: null, name: '', description: '', status: 'active' }
const bomEmpty = { id: null, component_id: null, required_quantity: 1, remark: '' }
const projectForm = reactive({ ...projectEmpty })
const bomForm = reactive({ ...bomEmpty })

const bomGroups = computed(() => {
  const map = new Map()
  for (const item of current.value?.bom_items || []) {
    const name = item.component.category?.name || '未分类'
    if (!map.has(name)) map.set(name, { name, items: [], satisfied: 0, shortage: 0 })
    const group = map.get(name)
    group.items.push(item)
    if (item.enough) group.satisfied += 1
    else group.shortage += 1
  }
  return Array.from(map.values())
})

const visibleBomGroups = computed(() => (activeCategory.value ? bomGroups.value.filter((group) => group.name === activeCategory.value) : bomGroups.value))
const bomStats = computed(() => {
  const items = current.value?.bom_items || []
  return {
    total: items.length,
    satisfied: items.filter((item) => item.enough).length,
    shortage: items.filter((item) => !item.enough).length,
    risk: items.filter((item) => item.component.ai_confidence === 'low' || item.component.ai_status === 'failed').length
  }
})

function matchBreakdown(total, matched, review, missing) {
  const safeTotal = Math.max(0, Number(total) || 0)
  const safeMatched = Math.max(0, Number(matched) || 0)
  const safeReview = Math.max(0, Number(review) || 0)
  const safeMissing = Math.max(0, Number(missing) || 0)
  const percent = (value) => (safeTotal ? Math.round((value / safeTotal) * 100) : 0)
  return {
    total: safeTotal,
    matched: safeMatched,
    review: safeReview,
    missing: safeMissing,
    rate: percent(safeMatched),
    matchedPercent: percent(safeMatched),
    reviewPercent: percent(safeReview),
    missingPercent: percent(safeMissing)
  }
}

const projectMatchStats = computed(() =>
  matchBreakdown(
    current.value?.bom_match_total,
    current.value?.bom_match_matched,
    current.value?.bom_match_review,
    current.value?.bom_match_missing
  )
)

const projectMissingItems = computed(() => {
  const rows = latestBomImportBatch.value?.rows?.length ? latestBomImportBatch.value.rows : bomMatchRows.value
  return rows.filter((row) => bomMatchBucket(row) === 'missing')
})

function bomMatchBucket(row) {
  if (row.status === 'ignored') return 'ignored'
  if (row.selected_component_id) return 'matched'
  if (row.status === 'supplier_missing') return 'missing'
  if (row.matches?.length) return 'review'
  return 'missing'
}

const bomMatchBuckets = computed(() => {
  const buckets = { matched: [], review: [], missing: [] }
  for (const row of bomMatchRows.value) {
    const bucket = bomMatchBucket(row)
    if (bucket in buckets) buckets[bucket].push(row)
  }
  return buckets
})

const activeBomMatchRows = computed(() => bomMatchBuckets.value[bomMatchTab.value] || [])
const selectedBomRows = computed(() => bomMatchRows.value.filter((row) => row.selected_component_id))
const pendingSelectedBomRows = computed(() => selectedBomRows.value.filter((row) => !row.auto_imported))
const bomMatchStats = computed(() =>
  matchBreakdown(
    bomMatchBuckets.value.matched.length + bomMatchBuckets.value.review.length + bomMatchBuckets.value.missing.length,
    bomMatchBuckets.value.matched.length,
    bomMatchBuckets.value.review.length,
    bomMatchBuckets.value.missing.length
  )
)

const purchaseKeywords = computed(() => {
  const values = bomMatchBuckets.value.missing
    .map((row) => row.missing_suggestion?.lcsc_search_keyword || row.supplier_part || row.manufacturer_part || row.value || row.comment)
    .map((value) => String(value || '').trim())
    .filter(Boolean)
  return [...new Set(values)]
})

const hasStoredBomMatchBatch = computed(() => Number(current.value?.bom_match_total || 0) > 0)

function rowKey(row) {
  return String(row?.id || row?.source_row || row?.designator || '')
}

function matchSelectOptions(row) {
  const map = new Map()
  for (const match of row?.matches || []) {
    if (match?.component?.id) map.set(match.component.id, match)
  }
  for (const match of bomMatchExtraOptions.value[rowKey(row)] || []) {
    if (match?.component?.id) map.set(match.component.id, match)
  }
  return Array.from(map.values())
}

function matchOptionLabel(match) {
  const component = match.component || {}
  const score = Number.isFinite(Number(match.score)) ? `${match.score}%` : match.score || '手动'
  return `${component.name || component.model || '库存物料'} ${component.model || ''} / ${score}`
}

function bomMatchSearchKeyword(row) {
  return [row?.value, row?.manufacturer_part, row?.supplier_part, row?.footprint]
    .map((value) => String(value || '').trim())
    .filter(Boolean)
    .join(' ')
}

async function searchBomMatchComponents(row, keyword = '') {
  const key = rowKey(row)
  if (!key) return
  bomMatchOptionLoading.value = { ...bomMatchOptionLoading.value, [key]: true }
  try {
    const data = await getComponents({ page: 1, page_size: 80, keyword: String(keyword || '').trim() || bomMatchSearchKeyword(row) })
    bomMatchExtraOptions.value = {
      ...bomMatchExtraOptions.value,
      [key]: (data.items || []).map((component) => ({
        component,
        score: '手动',
        match_type: 'manual',
        reason: '手动从库存选择',
        flags: [],
        available_quantity: component.available_quantity,
        shortage_quantity: 0,
        enough: component.available_quantity >= (row.required_quantity || 1)
      }))
    }
  } finally {
    bomMatchOptionLoading.value = { ...bomMatchOptionLoading.value, [key]: false }
  }
}

function ensureBomMatchOptions(row) {
  if (!matchSelectOptions(row).length) searchBomMatchComponents(row, bomMatchSearchKeyword(row))
}

async function openStockPicker(row) {
  stockPickerRow.value = row
  stockPickerKeyword.value = bomMatchSearchKeyword(row)
  stockPickerDialog.value = true
  await searchStockPicker()
}

async function searchStockPicker() {
  stockPickerLoading.value = true
  try {
    const data = await getComponents({ page: 1, page_size: 80, keyword: stockPickerKeyword.value })
    stockPickerOptions.value = data.items || []
  } finally {
    stockPickerLoading.value = false
  }
}

function pickStockComponent(component) {
  const row = stockPickerRow.value
  if (!row || !component?.id) return
  const key = rowKey(row)
  const match = {
    component,
    score: '手动',
    match_type: 'manual',
    reason: '手动从库存选择',
    flags: [],
    available_quantity: component.available_quantity,
    shortage_quantity: Math.max(0, (row.required_quantity || 1) - (component.available_quantity || 0)),
    enough: (component.available_quantity || 0) >= (row.required_quantity || 1)
  }
  bomMatchExtraOptions.value = {
    ...bomMatchExtraOptions.value,
    [key]: [match, ...(bomMatchExtraOptions.value[key] || [])]
  }
  row.selected_component_id = component.id
  handleBomRowSelection(row, component.id)
  stockPickerDialog.value = false
  ElMessage.success('已选择库存物料')
}

function handleBomRowSelection(row, value) {
  if (!row) return
  if (value) {
    row.status = row.status === 'exact_lcsc' ? 'exact_lcsc' : 'manual_selected'
    row.ai_reason = row.status === 'exact_lcsc' ? row.ai_reason : '已手动选择库内元器件，等待导入确认。'
    return
  }
  row.selected_component_id = null
  if (row.status === 'manual_selected') {
    row.status = row.supplier_part ? 'supplier_missing' : row.matches?.length ? 'low_confidence' : 'missing'
    row.ai_reason = row.supplier_part
      ? 'BOM 指定立创编号未入库，候选库存仅作为同值/相似替换提醒。'
      : '已清空手动匹配，请重新选择库存或加入待采购库。'
  }
}

function clearStockPicker() {
  stockPickerRow.value = null
  stockPickerKeyword.value = ''
  stockPickerOptions.value = []
}

watch(current, (project) => {
  activeCategory.value = ''
  bomAiResult.value = project?.ai_bom_analysis ? JSON.parse(project.ai_bom_analysis) : null
  consultResult.value = null
  latestBomImportBatch.value = null
  if (project?.id && Number(project.bom_match_total || 0) > 0) loadLatestBomImportBatch(project.id)
})

watch(projectSidebarFolded, (value) => {
  localStorage.setItem('cw_project_sidebar_folded', value ? '1' : '0')
})

function shortageCount(project) {
  return (project.bom_items || []).filter((item) => !item.enough).length
}

async function load() {
  loading.value = true
  try {
    projects.value = await getProjects()
    current.value = current.value ? projects.value.find((item) => item.id === current.value.id) || null : projects.value[0] || null
  } catch {
    ElMessage.error('读取项目失败')
  } finally {
    loading.value = false
  }
}

let latestBomBatchRequest = 0

async function loadLatestBomImportBatch(projectId = current.value?.id) {
  if (!projectId) return null
  const requestId = ++latestBomBatchRequest
  try {
    const batch = await getLatestBomImportBatch(projectId)
    if (requestId === latestBomBatchRequest && current.value?.id === projectId) {
      latestBomImportBatch.value = batch
    }
    return batch
  } catch {
    return null
  }
}

async function loadCategories() {
  categories.value = await getCategories()
}

function selectProject(project) {
  current.value = project
}

function openProject(row) {
  Object.assign(projectForm, projectEmpty, row || {})
  projectDialog.value = true
}

async function submitProject() {
  if (!projectForm.name) return ElMessage.warning('请填写项目名称')
  await saveProject(projectForm)
  projectDialog.value = false
  ElMessage.success('已保存')
  load()
}

async function removeProject(row) {
  await ElMessageBox.confirm(`删除项目 ${row.name}？`, '确认删除', { type: 'warning' })
  await deleteProject(row.id)
  ElMessage.success('已删除')
  if (current.value?.id === row.id) current.value = null
  load()
}

async function searchComponents(keyword = '') {
  const data = await getComponents({ page: 1, page_size: 60, keyword, category_id: componentCategory.value })
  componentOptions.value = data.items
}

async function openBom(row) {
  componentKeyword.value = row?.component?.model || row?.component?.name || ''
  componentCategory.value = row?.component?.category_id || null
  await searchComponents(componentKeyword.value)
  Object.assign(bomForm, bomEmpty, row ? { id: row.id, component_id: row.component_id, required_quantity: row.required_quantity, remark: row.remark } : {})
  bomDialog.value = true
}

async function submitBom() {
  if (!current.value || !bomForm.component_id) return ElMessage.warning('请选择元器件')
  if (bomForm.id) {
    await updateBomItem(current.value.id, bomForm.id, { required_quantity: bomForm.required_quantity, remark: bomForm.remark })
  } else {
    await addBomItem(current.value.id, bomForm)
  }
  bomDialog.value = false
  ElMessage.success('已保存')
  load()
}

async function releaseBom(row) {
  await deleteBomItem(current.value.id, row.id)
  ElMessage.success('已释放占用')
  load()
}

async function markPicked(row) {
  await ElMessageBox.confirm(`确认已取料并扣减库存：${row.component.name} x ${row.required_quantity}？`, '确认取料', { type: 'warning' })
  await updateBomItemStatus(current.value.id, row.id, { status: 'picked', consume_stock: true })
  ElMessage.success('已取料并扣减库存')
  load()
}

async function markDone(row) {
  await updateBomItemStatus(current.value.id, row.id, { status: 'done', consume_stock: false })
  ElMessage.success('已标记完成')
  load()
}

async function convertDoneToPicked(row) {
  await ElMessageBox.confirm(`确认将旧完成状态改为已取料并扣减库存：${row.component.name} x ${row.required_quantity}？`, '确认转换', { type: 'warning' })
  await updateBomItemStatus(current.value.id, row.id, { status: 'picked', consume_stock: true, remark: '旧完成状态转换为已取料' })
  ElMessage.success('已转换为取料状态')
  load()
}

async function completeProject() {
  if (!current.value) return
  await saveProject({ ...current.value, status: 'completed' })
  ElMessage.success('项目已标记完成')
  load()
}

function downloadBom() {
  if (current.value) exportBom(current.value.id, current.value.name)
}

function bomStatusLabel(status) {
  return { reserved: '预占/待取料', picked: '已取料', done: '旧状态：已完成', released: '已释放' }[status || 'reserved'] || status
}

function bomStatusType(status) {
  return { reserved: 'primary', picked: 'warning', done: 'success', released: 'info' }[status || 'reserved'] || 'info'
}

function bomMatchSourceLabel(item) {
  const remark = String(item?.remark || '')
  if (/编号一致|BOM自动导入行/.test(remark)) return '编号一致'
  if (/手动匹配|BOM 位号|AI 判断/.test(remark)) return '手动匹配'
  return ''
}

function bomMatchSourceType(item) {
  return bomMatchSourceLabel(item) === '编号一致' ? 'success' : 'warning'
}

async function runBomAnalysis(force = false) {
  if (!current.value) return
  bomAiLoading.value = true
  try {
    bomAiResult.value = await analyzeProjectBom(current.value.id, force)
    ElMessage.success('BOM 分析已生成')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'BOM 分析失败')
  } finally {
    bomAiLoading.value = false
  }
}

async function runProjectPlan() {
  if (!current.value || !projectRequirement.value.trim()) return ElMessage.warning('请输入项目目标')
  projectAiLoading.value = true
  try {
    projectAiResult.value = await planProject(current.value.id, { goal: projectRequirement.value, force: true })
    ElMessage.success('项目规划已生成')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '项目规划失败')
  } finally {
    projectAiLoading.value = false
  }
}

async function runConsult() {
  if (!current.value || !projectRequirement.value.trim()) return ElMessage.warning('请输入要咨询的问题')
  projectAiLoading.value = true
  try {
    consultResult.value = await consultProject(current.value.id, { question: projectRequirement.value, force: true })
    ElMessage.success('AI 咨询已生成')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'AI 咨询失败')
  } finally {
    projectAiLoading.value = false
  }
}

function renderedMarkdown(result) {
  return renderAiMarkdown(result?.markdown || result?.summary || pretty(result))
}

function componentName(id) {
  const found = componentOptions.value.find((item) => item.id === id) || current.value?.bom_items?.find((item) => item.component_id === id)?.component
  return found?.model || found?.name || `库存 #${id}`
}

async function addRecommendation(item) {
  if (!current.value || !item.component_id) return
  await addBomItem(current.value.id, {
    component_id: item.component_id,
    required_quantity: item.required_quantity || 1,
    remark: `AI 推荐：${item.role || ''} ${item.reason || ''}`.trim()
  })
  ElMessage.success('已加入 BOM')
  load()
}

function openLcscMissing(item) {
  const keyword = item?.lcsc_search_keyword || item?.suggested_models?.[0] || item?.description || item
  const url = item?.lcsc_search_url || makeLcscSearchUrl(keyword)
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

function openUrl(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

async function copyText(text, successPrefix = '已复制') {
  const value = String(text || '').trim()
  if (!value) return ElMessage.warning('没有可复制的内容')
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = value
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
  ElMessage.success(`${successPrefix}：${value.length > 40 ? `${value.slice(0, 40)}...` : value}`)
}

function copyPurchaseKeywords() {
  copyText(purchaseKeywords.value.join('\n'), '已复制采购关键词')
}

function canIgnoreBomRow(row) {
  return row?.id && !row.auto_imported && row.status !== 'ignored'
}

function canCreatePendingComponent(row) {
  return row?.id && !row.auto_imported && ['supplier_missing', 'missing', 'low_confidence'].includes(row.status) && (row.supplier_part || row.manufacturer_part)
}

async function createPendingPurchase(row) {
  if (!current.value || !canCreatePendingComponent(row)) return
  const batch = await createPendingComponentFromBomRow(current.value.id, row.id)
  latestBomImportBatch.value = batch
  bomMatchRows.value = batch.rows || []
  current.value = {
    ...current.value,
    bom_match_total: batch.total_count || 0,
    bom_match_matched: batch.matched_count || 0,
    bom_match_review: batch.review_count || 0,
    bom_match_missing: batch.missing_count || 0,
    bom_match_updated_at: batch.updated_at || new Date().toISOString()
  }
  if (!activeBomMatchRows.value.length) {
    if (bomMatchBuckets.value.missing.length) bomMatchTab.value = 'missing'
    else if (bomMatchBuckets.value.review.length) bomMatchTab.value = 'review'
    else bomMatchTab.value = 'matched'
  }
  await load()
  ElMessage.success('已加入待采购库并匹配到项目 BOM')
}

async function ignoreImportRow(row) {
  if (!current.value || !canIgnoreBomRow(row)) return
  await ElMessageBox.confirm(`忽略 ${row.designator || row.manufacturer_part || row.value || '该 BOM 行'}？它将不再计入待采购和匹配进度。`, '忽略 BOM 行', {
    type: 'warning',
    confirmButtonText: '忽略',
    cancelButtonText: '取消'
  })
  const batch = await ignoreBomImportRow(current.value.id, row.id)
  latestBomImportBatch.value = batch
  bomMatchRows.value = batch.rows || []
  current.value = {
    ...current.value,
    bom_match_total: batch.total_count || 0,
    bom_match_matched: batch.matched_count || 0,
    bom_match_review: batch.review_count || 0,
    bom_match_missing: batch.missing_count || 0,
    bom_match_updated_at: batch.updated_at || new Date().toISOString()
  }
  if (!activeBomMatchRows.value.length) {
    if (bomMatchBuckets.value.missing.length) bomMatchTab.value = 'missing'
    else if (bomMatchBuckets.value.review.length) bomMatchTab.value = 'review'
    else bomMatchTab.value = 'matched'
  }
  ElMessage.success('已忽略，不再计入待采购')
}

async function openStoredBomMatch() {
  if (!current.value) return
  const batch = await loadLatestBomImportBatch(current.value.id)
  bomMatchRows.value = batch.rows || []
  if (bomMatchBuckets.value.review.length) bomMatchTab.value = 'review'
  else if (bomMatchBuckets.value.missing.length) bomMatchTab.value = 'missing'
  else bomMatchTab.value = 'matched'
  bomMatchDialog.value = true
}

function openComponentDetail(component) {
  const keyword = component?.lcsc_number || component?.model || component?.name
  router.push({ name: 'components', query: { keyword } })
}

function matchStatusLabel(status) {
  return { exact_lcsc: '编号一致', manual_selected: '手动匹配', supplier_missing: '编号未入库', exact: '精确', approximate: '已建议', low_confidence: '低置信候选', missing: '缺料', ignored: '已忽略' }[status] || status || '待确认'
}

function matchStatusType(status) {
  return { exact_lcsc: 'success', manual_selected: 'success', supplier_missing: 'danger', exact: 'success', approximate: 'warning', low_confidence: 'warning', missing: 'danger', ignored: 'info' }[status] || 'info'
}

function bomRole(item) {
  const remarkRole = String(item.remark || '')
    .split(/[；;\n]/)
    .find((part) => /作用|用途|BOM 位号|位号/.test(part))
  if (remarkRole) return remarkRole
  return componentOneLineUsage(item.component)
}

async function handleBomMatchUpload({ file }) {
  matchingBom.value = true
  try {
    bomMatchRows.value = await previewBomMatch(file, current.value?.id)
    if (bomMatchBuckets.value.matched.length) bomMatchTab.value = 'matched'
    else if (bomMatchBuckets.value.review.length) bomMatchTab.value = 'review'
    else bomMatchTab.value = 'missing'
    if (current.value) {
      current.value = {
        ...current.value,
        bom_match_total: bomMatchStats.value.total,
        bom_match_matched: bomMatchStats.value.matched,
        bom_match_review: bomMatchStats.value.review,
        bom_match_missing: bomMatchStats.value.missing,
        bom_match_updated_at: new Date().toISOString()
      }
      latestBomImportBatch.value = {
        rows: bomMatchRows.value,
        total_count: bomMatchStats.value.total,
        matched_count: bomMatchStats.value.matched,
        review_count: bomMatchStats.value.review,
        missing_count: bomMatchStats.value.missing
      }
    }
    bomMatchDialog.value = true
    await load()
    await loadLatestBomImportBatch(current.value?.id)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'BOM 解析或匹配失败')
  } finally {
    matchingBom.value = false
  }
}

async function confirmImportMatches() {
  if (!current.value) return
  const items = pendingSelectedBomRows.value
    .map((row) => ({
      component_id: row.selected_component_id,
      required_quantity: row.required_quantity,
      remark: [
        `BOM 位号: ${row.designator || '-'}`,
        `BOM 型号: ${row.manufacturer_part || '-'}`,
        `BOM 封装: ${row.footprint || '-'}`,
        row.status === 'exact_lcsc' ? '编号一致' : '',
        row.status !== 'exact_lcsc' ? '手动匹配' : '',
        row.ai_reason ? `AI 判断: ${row.ai_reason}` : ''
      ]
        .filter(Boolean)
        .join('；')
    }))
  if (!items.length) return ElMessage.warning('没有选择可导入的库存物料')
  importingMatchedBom.value = true
  try {
    const result = await importMatchedBomItems(current.value.id, items)
    ElMessage.success(`新增 ${result.added}，更新 ${result.updated}，跳过 ${result.skipped}`)
    bomMatchDialog.value = false
    await load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '导入项目 BOM 失败')
  } finally {
    importingMatchedBom.value = false
  }
}

function pretty(value) {
  if (!value) return '暂无'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

onMounted(async () => {
  await Promise.all([loadCategories(), load()])
})
</script>

<style scoped>
.bom-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 340px;
  gap: 14px;
  align-items: start;
}

h2,
h3,
h4 {
  margin: 0;
}

.project-sidebar {
  position: sticky;
  top: 76px;
  max-height: calc(100vh - 92px);
  overflow: auto;
}

.project-sidebar.folded {
  padding: 10px;
}

.bom-layout:has(.project-sidebar.folded) {
  grid-template-columns: 86px minmax(0, 1fr) 340px;
}

.sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.nav-title {
  margin-top: 18px;
}

.project-item,
.category-nav {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 14px;
  background: #fff;
  color: var(--cw-text);
  cursor: pointer;
}

.project-item.active {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.category-nav small {
  color: var(--cw-muted);
}

.project-sidebar.folded .project-item,
.project-sidebar.folded .category-nav {
  justify-content: center;
  padding: 10px 6px;
}

.project-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.bom-help {
  margin-bottom: 14px;
}

.project-head p {
  margin: 6px 0 0;
  color: var(--cw-muted);
}

.bom-metrics {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 14px;
}

.match-progress-panel {
  display: grid;
  gap: 14px;
  margin-bottom: 14px;
  border-color: #dbeafe;
  background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
}

.match-progress-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.eyebrow {
  display: inline-flex;
  margin-bottom: 6px;
  color: #3b82f6;
  font-size: 12px;
  font-weight: 760;
}

.match-progress-main h3 {
  margin: 0;
  font-size: 22px;
}

.match-progress-main p {
  margin: 6px 0 0;
  color: var(--cw-muted);
  line-height: 1.55;
}

.match-rate {
  min-width: 96px;
  color: #14532d;
  font-size: 40px;
  font-weight: 820;
  line-height: 1;
  text-align: right;
}

.match-rate small {
  font-size: 18px;
}

.segmented-progress {
  display: flex;
  overflow: hidden;
  height: 12px;
  border-radius: 999px;
  background: #eef2f7;
}

.segment {
  min-width: 0;
  transition: width 0.2s ease;
}

.segment.matched {
  background: #22c55e;
}

.segment.review {
  background: #f59e0b;
}

.segment.missing {
  background: #ef4444;
}

.match-kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.match-kpi {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 10px;
  align-items: end;
  padding: 12px;
  border: 1px solid var(--cw-border);
  border-radius: 14px;
  background: #fff;
}

.match-kpi span,
.match-kpi small {
  color: var(--cw-muted);
}

.match-kpi strong {
  color: var(--cw-text);
  font-size: 24px;
  line-height: 1;
}

.match-kpi.tone-green {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.match-kpi.tone-amber {
  border-color: #fde68a;
  background: #fffbeb;
}

.match-kpi.tone-red {
  border-color: #fecdd3;
  background: #fff1f2;
}

.missing-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding-top: 2px;
}

.missing-preview strong {
  color: var(--cw-text);
}

.missing-preview span {
  display: inline-flex;
  max-width: 220px;
  padding: 5px 9px;
  border: 1px solid #fecdd3;
  border-radius: 999px;
  background: #fff7f7;
  color: #991b1b;
  font-size: 12px;
}

.match-resume {
  display: flex;
  justify-content: flex-end;
}

.bom-group {
  margin-bottom: 14px;
}

.group-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}

.bom-card-list {
  display: grid;
  gap: 10px;
}

.bom-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px auto;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border-radius: 16px;
  background: #fff;
}

.bom-card p {
  margin: 5px 0 8px;
  color: var(--cw-muted);
}

.bom-role {
  line-height: 1.5;
  color: #344054;
}

.link-title {
  display: inline;
  border: 0;
  background: transparent;
  padding: 0;
  color: #101828;
  font: inherit;
  font-weight: 760;
  text-align: left;
  cursor: pointer;
}

.link-title:hover {
  color: var(--cw-accent);
  text-decoration: underline;
}

.bom-stock {
  display: grid;
  gap: 4px;
  color: var(--cw-muted);
}

.bom-stock strong {
  color: var(--cw-green);
}

.bom-stock strong.danger {
  color: var(--cw-red);
}

.bom-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.ai-bom-panel {
  position: sticky;
  top: 16px;
}

.ai-actions {
  margin: 10px 0;
}

.ai-result {
  margin-top: 14px;
  padding: 12px;
  border-radius: 16px;
  background: #fff;
}

.ai-result p {
  color: var(--cw-muted);
  line-height: 1.6;
}

.markdown-body {
  overflow-wrap: anywhere;
  color: #344054;
  line-height: 1.7;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin: 12px 0 8px;
  font-size: 16px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 20px;
}

.recommendation-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.recommendation-card {
  padding: 10px;
  border: 1px solid #dbeafe;
  border-radius: 14px;
  background: #eff6ff;
}

.recommendation-card.missing {
  border-color: #fde68a;
  background: #fffbeb;
}

.recommendation-card p {
  margin: 6px 0 8px;
}

.match-summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.match-summary-card {
  display: grid;
  gap: 4px;
  min-height: 76px;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  background: #fff;
}

.match-summary-card span {
  color: var(--cw-muted);
}

.match-summary-card strong {
  color: var(--cw-text);
  font-size: 24px;
  line-height: 1;
}

.match-summary-card.tone-green {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.match-summary-card.tone-amber {
  background: #fffbeb;
  border-color: #fde68a;
}

.match-summary-card.tone-red {
  background: #fff1f2;
  border-color: #fecdd3;
}

.match-summary-card.tone-blue {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.bom-match-alert,
.bom-match-tabs {
  margin-bottom: 10px;
}

.dialog-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
  color: var(--cw-muted);
  font-size: 13px;
}

:global(.bom-match-dialog) {
  max-height: calc(100vh - 48px);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 18px;
}

:global(.bom-match-dialog .el-dialog__header) {
  flex: 0 0 auto;
  padding: 18px 18px 10px;
  border-bottom: 1px solid #eef2f7;
}

:global(.bom-match-dialog .el-dialog__body) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 14px 18px;
}

:global(.bom-match-dialog .el-dialog__footer) {
  flex: 0 0 auto;
  padding: 12px 18px 16px;
  border-top: 1px solid #eef2f7;
  background: rgba(255, 255, 255, 0.96);
}

.bom-match-table {
  border-radius: 14px;
  overflow: hidden;
}

.missing-list {
  display: grid;
  gap: 8px;
}

.missing-list div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.match-role {
  margin-bottom: 6px;
  color: #344054;
  line-height: 1.45;
}

.compact-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 5px;
  font-size: 12px;
}

.match-flags,
.match-alternatives {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.match-alternatives span {
  display: inline-flex;
  padding: 4px 8px;
  border: 1px solid #fde68a;
  border-radius: 999px;
  background: #fffbeb;
  color: #92400e;
  font-size: 12px;
}

.match-row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 6px;
}

.match-reason,
.match-error {
  margin-top: 6px;
  color: var(--cw-muted);
  font-size: 12px;
  line-height: 1.45;
}

.match-error {
  color: #b42318;
}

.match-candidates {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.match-candidates span,
.missing-text {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  background: #eff6ff;
  color: #475467;
  font-size: 12px;
}

pre {
  white-space: pre-wrap;
  margin: 0;
  padding: 10px;
  border-radius: 12px;
  background: #f8fafc;
}

@media (max-width: 1180px) {
  .bom-layout {
    grid-template-columns: 220px minmax(0, 1fr);
  }

  .ai-bom-panel {
    grid-column: 1 / -1;
    position: static;
  }
}

@media (max-width: 820px) {
  .bom-layout {
    grid-template-columns: 1fr;
  }

  .project-sidebar {
    position: static;
  }

  .project-head,
  .bom-card {
    grid-template-columns: 1fr;
  }

  .bom-actions {
    justify-content: flex-start;
  }

  .bom-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .match-progress-main,
  .dialog-progress {
    grid-template-columns: 1fr;
    display: grid;
  }

  .match-rate {
    text-align: left;
  }

  .match-kpi-grid {
    grid-template-columns: 1fr;
  }

  .match-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
