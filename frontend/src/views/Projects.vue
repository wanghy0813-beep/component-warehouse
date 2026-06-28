<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">项目</h1>
        <p class="page-subtitle">管理项目 BOM、库存占用、采购缺料、焊接进度和封装风险</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openProject()">新建项目</el-button>
    </div>

    <div class="bom-layout">
      <aside class="panel project-sidebar" :class="{ folded: projectSidebarFolded }">
        <div class="sidebar-head">
          <h2 v-if="!projectSidebarFolded">项目</h2>
          <el-button size="small" text @click="projectSidebarFolded = !projectSidebarFolded">{{ projectSidebarFolded ? '展开' : '收起' }}</el-button>
        </div>
        <div v-for="project in projects" :key="project.id" class="project-item" :class="{ active: current?.id === project.id }">
          <button class="project-select" type="button" @click="selectProject(project)">
            <span>{{ projectSidebarFolded ? project.name.slice(0, 1) : project.name }}</span>
            <small v-if="!projectSidebarFolded">{{ project.project_code || `#${project.id}` }}</small>
          </button>
          <template v-if="!projectSidebarFolded">
            <el-tag :type="shortageCount(project) ? 'danger' : 'success'" size="small">{{ shortageCount(project) ? `缺 ${shortageCount(project)}` : '满足' }}</el-tag>
            <el-button size="small" text circle :icon="Delete" @click.stop="removeProject(project)" />
          </template>
        </div>
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
              <div class="project-code-line">
                <el-tag v-if="current.project_code" type="info" effect="plain">{{ current.project_code }}</el-tag>
                <el-button v-if="current.project_code" size="small" text :icon="CopyDocument" @click="copyText(current.project_code, '已复制项目 ID')">复制 ID</el-button>
              </div>
              <p>{{ current.description || '无描述' }}</p>
            </div>
            <div class="toolbar compact-toolbar">
              <el-button type="primary" :icon="Plus" @click="openBom()">添加物料</el-button>
              <el-upload :show-file-list="false" accept=".csv,.xlsx,.xls" :http-request="handleBomMatchUpload">
                <el-button :icon="Upload" :loading="matchingBom">导入 BOM</el-button>
              </el-upload>
              <el-button type="warning" plain @click="createPurchasePlan">生成采购计划</el-button>
              <el-popover placement="bottom-end" trigger="click" width="220" popper-class="cw-more-popover">
                <template #reference>
                  <el-button :icon="MoreFilled">更多操作</el-button>
                </template>
                <div class="more-action-list">
                  <el-button v-if="current.project_code" :icon="Link" @click="openUrl(projectPublicUrl(current))">公开项目</el-button>
                  <el-button :icon="Edit" @click="openProject(current)">编辑项目</el-button>
                  <el-upload :show-file-list="false" accept=".PrjPcb,.SchDoc,.PcbDoc,.OutJob,.ZIP,.PDF,.PNG,.JPG,.JPEG" :http-request="uploadProjectFile">
                    <el-button :icon="Upload" :loading="projectFileUploading">项目附件</el-button>
                  </el-upload>
                  <el-button :icon="Download" @click="downloadPurchaseBom">导出采购 BOM</el-button>
                  <el-button :icon="Download" @click="downloadBom">导出 BOM</el-button>
                  <el-button v-if="current.status !== 'completed'" type="success" plain @click="completeProject">完成项目</el-button>
                  <el-button type="danger" plain :icon="Delete" @click="removeProject(current)">删除项目</el-button>
                </div>
              </el-popover>
            </div>
          </div>

          <section v-if="current.project_code" class="panel public-project-panel">
            <div class="public-qr-box">
              <img v-if="!projectQrBroken" :src="projectQrUrl(current)" alt="项目公开 BOM 二维码" @load="projectQrBroken = false" @error="projectQrBroken = true" />
              <div v-else class="public-qr-fallback">
                <strong>二维码加载失败</strong>
                <small>可先复制链接使用</small>
                <el-button size="small" type="primary" plain @click="retryProjectQr">重试二维码</el-button>
                <el-button size="small" :icon="CopyDocument" @click="copyText(projectPublicUrl(current), '已复制公开链接')">复制链接</el-button>
              </div>
            </div>
            <div>
              <span class="eyebrow">公开项目链接</span>
              <strong>{{ projectPublicUrl(current) }}</strong>
              <small>只读项目页面，可按板子查看位号、型号、参数、封装和焊接状态。</small>
            </div>
            <div class="public-project-actions">
              <el-button size="small" :icon="CopyDocument" @click="copyText(projectPublicUrl(current), '已复制公开链接')">复制链接</el-button>
              <el-button size="small" type="primary" plain :icon="Link" @click="openUrl(projectPublicUrl(current))">打开</el-button>
            </div>
          </section>

          <section class="panel project-assets">
            <div class="section-head"><strong>项目文件与附件</strong><span>{{ projectAssets.length }} 个</span></div>
            <div v-if="projectAssets.length" class="asset-chips">
              <button v-for="asset in projectAssets" :key="asset.id" type="button" @click="downloadProjectAsset(asset)">
                <strong>{{ asset.original_name }}</strong><small>{{ asset.asset_type }} · {{ formatAssetBytes(asset.byte_size) }}</small>
              </button>
            </div>
            <el-empty v-else description="暂无 PrjPcb、SchDoc、PcbDoc、OutJob、ZIP 或项目资料" :image-size="52" />
          </section>

          <section class="panel project-risk-panel">
            <div class="section-head"><strong>当前项目工程风险</strong><span>{{ currentProjectRisks.length }} 项</span></div>
            <div v-if="currentProjectRisks.length" class="project-risk-list">
              <span v-for="risk in visibleProjectRisks" :key="risk.id" :class="risk.severity">
                {{ risk.title }} · {{ risk.component_name || risk.project_name || '项目' }}
              </span>
            </div>
            <div v-if="currentProjectRisks.length > projectRiskPreviewLimit" class="risk-more-row">
              <el-button size="small" text @click="projectRiskExpanded = !projectRiskExpanded">
                {{ projectRiskExpanded ? '收起风险' : `查看全部 ${currentProjectRisks.length} 项风险` }}
              </el-button>
              <small>风险仅作提示，不阻止导入、采购计划、附件和导出。</small>
            </div>
            <el-empty v-else description="当前 BOM 未发现封装、资料、料号或匹配风险" :image-size="52" />
          </section>

          <el-alert type="info" show-icon :closable="false" class="bom-help">
            每块板使用一整份 BOM；标记已焊接或报损时自动扣减库存，取消对应标记时自动返还。
          </el-alert>

          <section v-if="projectBoards.length" class="panel board-panel">
            <div class="board-panel-head">
              <div>
                <span class="eyebrow">板子</span>
                <strong>{{ activeBoard?.name || '第 1 板' }}</strong>
                <small>当前板：已焊 {{ activeBoardStats.soldered }}/{{ activeBoardStats.total }}，报损 {{ activeBoardStats.lost }}，待焊 {{ activeBoardStats.pending }}</small>
              </div>
              <el-button type="primary" plain :icon="Plus" @click="addBoard">再焊一板</el-button>
            </div>
            <div class="board-tabs">
              <button
                v-for="board in projectBoards"
                :key="board.id"
                type="button"
                class="board-tab"
                :class="{ active: board.id === activeBoardId }"
                @click="activeBoardId = board.id"
              >
                <span>{{ board.name }}</span>
                <small>{{ board.soldered_count || 0 }}/{{ board.solder_total || 0 }} · 损 {{ board.lost_count || 0 }}</small>
              </button>
            </div>
          </section>

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
                {{ missingItemDisplay(item) }}
              </span>
            </div>
            <div v-if="hasStoredBomMatchBatch" class="match-resume">
              <el-button size="small" plain @click="openStoredBomMatch">继续确认最近导入</el-button>
            </div>
          </section>

          <div class="metric-grid bom-metrics">
            <div class="metric"><div class="metric-label">总物料</div><div class="metric-value">{{ bomStats.total }}</div></div>
            <div class="metric"><div class="metric-label">总数量</div><div class="metric-value">{{ bomStats.quantity }}</div></div>
            <div class="metric"><div class="metric-label">已满足</div><div class="metric-value">{{ bomStats.satisfied }}</div></div>
            <div class="metric"><div class="metric-label">缺料</div><div class="metric-value">{{ bomStats.shortage }}</div></div>
            <div class="metric"><div class="metric-label">参数风险</div><div class="metric-value">{{ bomStats.risk }}</div></div>
            <div class="metric"><div class="metric-label">工程风险</div><div class="metric-value">{{ currentProjectRisks.length }}</div></div>
            <div class="metric"><div class="metric-label">焊接进度</div><div class="metric-value">{{ solderStats.progress }}%</div></div>
          </div>

          <section class="panel solder-toolbar">
            <div>
              <span class="eyebrow">焊接工作进度</span>
              <strong>{{ solderStats.soldered }}/{{ solderStats.total }} 位号已焊</strong>
              <small>{{ solderStats.pending }} 个待焊，{{ solderStats.lost }} 个报损</small>
            </div>
            <el-segmented v-model="solderFilter" :options="solderFilterOptions" />
            <el-input v-model="solderKeyword" clearable placeholder="搜索位号、型号、参数、封装" />
          </section>

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
                    <el-tag v-if="isSolderComplete(item)" size="small" type="success" effect="dark">当前板已焊</el-tag>
                    <el-tag v-else size="small" :type="bomStatusType(item.status)">{{ bomStatusLabel(item.status) }}</el-tag>
                    <el-tag v-if="componentStatusTag(item.component)" size="small" :type="componentStatusTag(item.component).type" effect="dark">{{ componentStatusTag(item.component).label }}</el-tag>
                    <el-tag v-if="item.component.ai_confidence === 'low'" size="small" type="warning">参数待核对</el-tag>
                    <el-tag v-if="item.component.ai_status === 'pending' || item.component.ai_status === 'stale'" size="small" type="info" effect="plain">待整理</el-tag>
                  </div>
                  <div v-if="substitutionSuggestions(item).length" class="substitution-panel">
                    <div class="substitution-title">
                      <strong>建议替代</strong>
                      <span>仅推荐，不自动替换</span>
                    </div>
                    <button
                      v-for="suggestion in substitutionSuggestions(item)"
                      :key="suggestion.component.id"
                      type="button"
                      class="substitution-card"
                      @click="openComponentDetail(suggestion.component)"
                    >
                      <span>
                        <strong>{{ substitutionTitle(suggestion) }}</strong>
                        <small>{{ substitutionSubtitle(suggestion) }}</small>
                      </span>
                      <em>可用 {{ suggestion.available_quantity }}</em>
                      <small class="substitution-reason">{{ suggestion.reason }}</small>
                      <small v-for="warning in suggestion.warnings" :key="warning" class="substitution-warning">{{ warning }}</small>
                    </button>
                  </div>
                  <template v-if="itemBoardTotal(item)">
                    <div class="solder-meta">{{ solderMeta(item) }}</div>
                    <div class="solder-point-list">
                      <span
                        v-for="point in itemBoardPoints(item)"
                        :key="point.id"
                        class="solder-chip"
                        :class="{ done: point.soldered }"
                        :title="solderPointTitle(point, item)"
                      >
                        <button class="solder-chip-main" type="button" @click="toggleSolderPoint(item, point)">
                          <span>{{ point.designator }}</span>
                          <small>{{ point.soldered ? '已焊' : '待焊' }}</small>
                          <em v-if="point.lost" class="loss-badge">报损</em>
                        </button>
                        <button class="loss-toggle" :class="{ active: point.lost }" type="button" @click="toggleSolderLoss(item, point)">
                          {{ point.lost ? '撤损' : '报损' }}
                        </button>
                      </span>
                    </div>
                  </template>
                  <div v-else class="solder-empty">暂无位号，编辑备注或重新导入 BOM 后可跟踪焊接。</div>
                </div>
                <div class="bom-stock">
                  <span>需求 {{ item.required_quantity }}</span>
                  <span>可用 {{ item.available_quantity }}</span>
                  <strong :class="{ danger: !item.enough }">{{ item.enough ? '库存充足' : `缺 ${item.shortage_quantity}` }}</strong>
                  <em v-if="itemBoardTotal(item)">当前板 {{ itemBoardSoldered(item) }}/{{ itemBoardTotal(item) }} · 损 {{ itemBoardLost(item) }}</em>
                </div>
                <div class="bom-actions">
                  <el-button size="small" :disabled="!itemBoardTotal(item) || itemBoardSoldered(item) >= itemBoardTotal(item)" @click="markBomSolderBulk(item, true)">全焊</el-button>
                  <el-button size="small" :disabled="!itemBoardSoldered(item)" @click="markBomSolderBulk(item, false)">清焊</el-button>
                  <el-button v-if="!itemBoardTotal(item)" size="small" :disabled="item.status !== 'reserved'" @click="markPicked(item)">取料</el-button>
                  <el-button v-if="item.status === 'done'" size="small" type="warning" @click="convertDoneToPicked(item)">改为已取料</el-button>
                  <el-button size="small" @click="openBom(item)">编辑</el-button>
                  <el-button size="small" type="danger" plain @click="deleteBomRow(item)">删除</el-button>
                </div>
              </article>
            </div>
          </section>
          <el-empty v-if="current.bom_items?.length && !visibleBomGroups.length" class="panel" description="没有符合当前焊接筛选的 BOM 项" />
        </template>
        <el-empty v-else class="panel" description="请选择或创建项目" />
      </main>

    </div>

    <el-dialog v-model="projectDialog" :title="projectForm.id ? '编辑项目' : '新建项目'" width="480px">
      <el-form label-width="72px" :model="projectForm">
        <el-form-item label="项目 ID"><el-input v-model="projectForm.project_code" placeholder="自动生成，如 PJ-00000001" /></el-form-item>
        <el-form-item label="名称" required><el-input v-model="projectForm.name" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="projectForm.status" style="width: 100%">
            <el-option label="草稿" value="draft" />
            <el-option label="设计中" value="designing" />
            <el-option label="待采购" value="purchasing" />
            <el-option label="打板中" value="fabricating" />
            <el-option label="装配调试" value="assembly" />
            <el-option label="进行中（旧）" value="active" />
            <el-option label="已完成" value="completed" />
            <el-option label="已归档" value="archived" />
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
          <el-select v-model="bomForm.component_id" filterable style="width: 100%">
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

    <BomMatchDialog
      v-model="bomMatchDialog"
      v-model:bom-match-tab="bomMatchTab"
      :bom-match-rows="bomMatchRows"
      :bom-match-stats="bomMatchStats"
      :bom-match-buckets="bomMatchBuckets"
      :active-bom-match-rows="activeBomMatchRows"
      :pending-selected-count="pendingSelectedBomRows.length"
      :purchase-keywords="purchaseKeywords"
      :importing-matched-bom="importingMatchedBom"
      :bom-match-option-loading="bomMatchOptionLoading"
      :bom-primary-display="bomPrimaryDisplay"
      :bom-secondary-display="bomSecondaryDisplay"
      :match-status-type="matchStatusType"
      :match-status-label="matchStatusLabel"
      :open-url="openUrl"
      :can-create-pending-component="canCreatePendingComponent"
      :create-pending-purchase="createPendingPurchase"
      :can-ignore-bom-row="canIgnoreBomRow"
      :ignore-import-row="ignoreImportRow"
      :row-key="rowKey"
      :search-bom-match-components="searchBomMatchComponents"
      :ensure-bom-match-options="ensureBomMatchOptions"
      :handle-bom-row-selection="handleBomRowSelection"
      :match-select-options="matchSelectOptions"
      :match-option-label="matchOptionLabel"
      :open-stock-picker="openStockPicker"
      :copy-purchase-keywords="copyPurchaseKeywords"
      :confirm-import-matches="confirmImportMatches"
    />
    <BomFieldMappingDialog
      v-model="bomMappingDialog"
      :inspection="bomInspection"
      :file-name="pendingBomFile?.name || ''"
      :loading="matchingBom"
      @confirm="confirmBomMapping"
    />

    <el-dialog v-model="stockPickerDialog" title="从库存选择元器件" width="min(780px, 94vw)" append-to-body destroy-on-close @closed="clearStockPicker">
      <div class="stock-picker-head">
        <el-input v-model="stockPickerKeyword" clearable placeholder="搜索名称、型号、参数、封装、立创 ID" @keyup.enter="searchStockPicker" />
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
import { ElMessage, ElMessageBox } from '../shared/elementApi'
import { useRouter } from 'vue-router'
import { CopyDocument, Delete, Download, Edit, Link, MoreFilled, Plus, Upload } from '@element-plus/icons-vue'
import {
  addBomItem,
  createProjectBoard,
  createPendingComponentFromBomRow,
  deleteBomItem,
  deleteProject,
  exportBom,
  exportPurchaseBom,
  getCategories,
  getComponents,
  getLatestBomImportBatch,
  getProjects,
  ignoreBomImportRow,
  importMatchedBomItems,
  inspectBomFields,
  previewBomMatch,
  saveProject,
  updateBomItem,
  updateBomItemStatus,
  updateBomImportRowSelection,
  updateBoardBomSolderPoint,
  updateBoardBomSolderPointLoss,
  updateBoardBomSolderPointsBulk
} from '../api/client'
import { componentOneLineUsage } from '../utils/componentUi'
import { componentDisplaySubtitle, componentDisplayTitle } from '../shared/componentDisplay'
import { API_BASE, PERSONAL_BASE } from '../shared/appPaths'
import BomMatchDialog from '../components/projects/BomMatchDialog.vue'
import BomFieldMappingDialog from '../shared/components/BomFieldMappingDialog.vue'
import { downloadEdaAsset, generateProjectPurchase, listEntityAssets, listRisks, publishEdaAsset, stageEdaUpload } from '../shared/engineeringApi'

const loading = ref(false)
const projects = ref([])
const current = ref(null)
const categories = ref([])
const componentOptions = ref([])
const projectDialog = ref(false)
const bomDialog = ref(false)
const bomMatchDialog = ref(false)
const matchingBom = ref(false)
const bomMappingDialog = ref(false)
const bomInspection = ref({})
const pendingBomFile = ref(null)
const importingMatchedBom = ref(false)
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
const componentKeyword = ref('')
const componentCategory = ref(null)
const solderFilter = ref('all')
const solderKeyword = ref('')
const activeBoardId = ref(null)
const router = useRouter()
const projectSidebarFolded = ref(localStorage.getItem('cw_project_sidebar_folded') === '1')
const projectAssets = ref([])
const projectFileUploading = ref(false)
const engineeringRisks = ref([])
const projectQrBroken = ref(false)
const projectQrRetry = ref(0)
const projectRiskExpanded = ref(false)
const projectRiskPreviewLimit = 12

const projectEmpty = { id: null, project_code: '', name: '', description: '', status: 'draft' }
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

const solderFilterOptions = [
  { label: '全部', value: 'all' },
  { label: '未焊', value: 'pending' },
  { label: '已焊', value: 'done' },
  { label: '报损', value: 'lost' }
]

const projectBoards = computed(() => current.value?.boards || [])
const activeBoard = computed(() => projectBoards.value.find((board) => board.id === activeBoardId.value) || projectBoards.value[0] || null)
const activeBoardStats = computed(() => ({
  total: activeBoard.value?.solder_total || 0,
  soldered: activeBoard.value?.soldered_count || 0,
  lost: activeBoard.value?.lost_count || 0,
  pending: activeBoard.value?.pending_count || 0,
  progress: activeBoard.value?.solder_progress || 0
}))

function itemBoardPoints(item) {
  const boardId = activeBoard.value?.id
  return (item?.solder_points || []).filter((point) => !boardId || point.board_id === boardId)
}

function itemBoardTotal(item) {
  return itemBoardPoints(item).length || Number(item?.required_quantity || 0)
}

function itemBoardSoldered(item) {
  return itemBoardPoints(item).filter((point) => point.soldered).length
}

function itemBoardLost(item) {
  return itemBoardPoints(item).filter((point) => point.lost).length
}

const solderStats = computed(() => {
  const items = current.value?.bom_items || []
  const total = items.reduce((sum, item) => sum + itemBoardTotal(item), 0)
  const soldered = items.reduce((sum, item) => sum + itemBoardSoldered(item), 0)
  const lost = items.reduce((sum, item) => sum + itemBoardLost(item), 0)
  return {
    total,
    soldered,
    lost,
    pending: Math.max(0, total - soldered),
    progress: total ? Math.round((soldered / total) * 100) : 0
  }
})

function itemSolderState(item) {
  const total = itemBoardTotal(item)
  const done = itemBoardSoldered(item)
  const lost = itemBoardLost(item)
  if (!total) return 'none'
  if (done >= total) return 'done'
  if (done > 0 || lost > 0) return 'partial'
  return 'pending'
}

function itemMatchesSolderFilter(item) {
  if (solderFilter.value === 'done') return itemSolderState(item) === 'done'
  if (solderFilter.value === 'lost') return itemBoardLost(item) > 0
  if (solderFilter.value === 'pending') return ['pending', 'partial'].includes(itemSolderState(item))
  return true
}

function itemMatchesSolderKeyword(item) {
  const keyword = solderKeyword.value.trim().toLowerCase()
  if (!keyword) return true
  const text = [
    item?.component?.name,
    item?.component?.model,
    item?.component?.parameters,
    item?.component?.normalized_spec,
    item?.component?.package,
    item?.remark,
    ...itemBoardPoints(item).flatMap((point) => [point.designator, point.bom_value, point.bom_model, point.bom_footprint, point.loss_note])
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .replace(/µ|μ/g, 'u')
  return text.includes(keyword.replace(/µ|μ/g, 'u'))
}

const visibleBomGroups = computed(() => {
  const groups = activeCategory.value ? bomGroups.value.filter((group) => group.name === activeCategory.value) : bomGroups.value
  return groups
    .map((group) => {
      const items = group.items.filter((item) => itemMatchesSolderFilter(item) && itemMatchesSolderKeyword(item))
      return {
        ...group,
        items,
        satisfied: items.filter((item) => item.enough).length,
        shortage: items.filter((item) => !item.enough).length
      }
    })
    .filter((group) => group.items.length)
})
const bomStats = computed(() => {
  const items = current.value?.bom_items || []
  return {
    total: items.length,
    quantity: items.reduce((sum, item) => sum + Number(item.required_quantity || 0), 0),
    satisfied: items.filter((item) => item.enough).length,
    shortage: items.filter((item) => !item.enough).length,
    risk: items.filter((item) => item.component.ai_confidence === 'low' || item.component.ai_status === 'failed').length
  }
})
const currentProjectRisks = computed(() => {
  const componentIds = new Set((current.value?.bom_items || []).map((item) => item.component_id))
  return (engineeringRisks.value || []).filter(
    (item) => item.project_id === current.value?.id || (item.component_id && componentIds.has(item.component_id))
  )
})
const visibleProjectRisks = computed(() => (
  projectRiskExpanded.value
    ? currentProjectRisks.value
    : currentProjectRisks.value.slice(0, projectRiskPreviewLimit)
))

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
  return rows.filter((row) => !bomImportRowInProject(row) && bomMatchBucket(row) === 'missing')
})

function bomMatchBucket(row) {
  if (row.status === 'ignored') return 'ignored'
  if (row.auto_imported || row.status === 'pending_purchase' || row.status === 'imported') return 'matched'
  if (row.selected_component_id) return 'matched'
  if (row.status === 'supplier_missing') return 'missing'
  if (row.matches?.length) return 'review'
  return 'missing'
}

function bomImportRowInProject(row) {
  const designators = new Set(String(row?.designator || '').split(/[,，、\s]+/).map((item) => item.trim().toUpperCase()).filter(Boolean))
  if (!designators.size) return false
  return (current.value?.bom_items || []).some((item) => {
    const points = item.solder_points || []
    return points.some((point) => designators.has(String(point.designator || '').trim().toUpperCase()))
  })
}

const activeBomMatchSourceRows = computed(() => bomMatchRows.value.filter((row) => !bomImportRowInProject(row)))

const bomMatchBuckets = computed(() => {
  const buckets = { matched: [], review: [], missing: [] }
  for (const row of activeBomMatchSourceRows.value) {
    const bucket = bomMatchBucket(row)
    if (bucket in buckets) buckets[bucket].push(row)
  }
  return buckets
})

const activeBomMatchRows = computed(() => bomMatchBuckets.value[bomMatchTab.value] || [])
const selectedBomRows = computed(() => activeBomMatchSourceRows.value.filter((row) => row.selected_component_id))
const pendingSelectedBomRows = computed(() =>
  selectedBomRows.value.filter((row) => !row.auto_imported && row.status !== 'pending_purchase')
)
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
  if (row?.selected_component?.id) {
    map.set(row.selected_component.id, {
      component: row.selected_component,
      score: row.match_confidence || '已选',
      match_type: row.status || 'selected',
      reason: row.status === 'pending_purchase' ? '待采购库/待入库' : '已选中',
      flags: row.status === 'pending_purchase' ? ['待采购库'] : ['已选中'],
      available_quantity: row.selected_component.available_quantity ?? row.selected_component.quantity ?? 0,
      shortage_quantity: Math.max(0, (row.required_quantity || 1) - (row.selected_component.available_quantity ?? row.selected_component.quantity ?? 0)),
      enough: (row.selected_component.available_quantity ?? row.selected_component.quantity ?? 0) >= (row.required_quantity || 1)
    })
  }
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
    let items = data.items || []
    if (!items.length && stockPickerKeyword.value) {
      const fallback = await getComponents({ page: 1, page_size: 80 })
      items = fallback.items || []
    }
    stockPickerOptions.value = items
  } finally {
    stockPickerLoading.value = false
  }
}

async function pickStockComponent(component) {
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
  await handleBomRowSelection(row, component.id)
  stockPickerDialog.value = false
  ElMessage.success('已选择库存物料')
}

async function handleBomRowSelection(row, value) {
  if (!row) return
  if (value) {
    row.status = row.status === 'exact_lcsc' ? 'exact_lcsc' : 'manual_selected'
    row.ai_reason = row.status === 'exact_lcsc' ? row.ai_reason : '已手动选择库内元器件，等待导入确认。'
  } else {
    row.selected_component_id = null
    if (row.status === 'manual_selected') {
      row.status = row.supplier_part ? 'supplier_missing' : row.matches?.length ? 'review' : 'missing'
      row.ai_reason = row.supplier_part
        ? 'BOM 指定立创 ID 未入库，候选库存只用于人工核对，系统不会自动替换。'
        : '已清空手动匹配，请重新选择库存或加入待采购库。'
    }
  }
  if (!current.value || !row.id) return
  try {
    const batch = await updateBomImportRowSelection(current.value.id, row.id, { component_id: value || null })
    applyBomImportBatch(batch)
    if (!activeBomMatchRows.value.length) selectBestBomMatchTab()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存 BOM 行匹配失败')
  }
}

function clearStockPicker() {
  stockPickerRow.value = null
  stockPickerKeyword.value = ''
  stockPickerOptions.value = []
}

watch(current, (project) => {
  activeCategory.value = ''
  latestBomImportBatch.value = null
  projectQrBroken.value = false
  projectQrRetry.value = 0
  projectRiskExpanded.value = false
  const boards = project?.boards || []
  if (boards.length && !boards.some((board) => board.id === activeBoardId.value)) {
    activeBoardId.value = project?.active_board_id || boards[0].id
  } else if (!boards.length) {
    activeBoardId.value = null
  }
  if (project?.id && Number(project.bom_match_total || 0) > 0) loadLatestBomImportBatch(project.id)
  if (project?.id) loadProjectAssets(project.id)
  else projectAssets.value = []
  if (project?.id) loadProjectRisks()
})

async function loadProjectAssets(projectId) {
  try { projectAssets.value = await listEntityAssets('project', String(projectId)) }
  catch { projectAssets.value = [] }
}

async function uploadProjectFile(options) {
  if (!current.value?.id) return
  projectFileUploading.value = true
  try {
    const stage = await stageEdaUpload(options.file)
    await publishEdaAsset({
      upload_token: stage.token,
      verification_status: 'raw',
      entity_type: 'project',
      entity_id: String(current.value.id),
      relation_type: 'project_file'
    })
    await loadProjectAssets(current.value.id)
    ElMessage.success('项目文件已上传')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '项目文件上传失败')
  } finally {
    projectFileUploading.value = false
  }
}

async function downloadProjectAsset(asset) {
  const blob = await downloadEdaAsset(asset.id)
  downloadBlob(blob, asset.original_name)
}

async function loadProjectRisks() {
  try { engineeringRisks.value = (await listRisks()).items || [] }
  catch { engineeringRisks.value = [] }
}

async function createPurchasePlan() {
  if (!current.value?.id) return
  try {
    const order = await generateProjectPurchase(current.value.id)
    ElMessage.success(`采购计划已生成，共 ${order.lines?.length || 0} 项`)
    await load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '生成采购计划失败')
  }
}

function formatAssetBytes(value) {
  const bytes = Number(value || 0)
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

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

function applyBomImportBatch(batch) {
  latestBomImportBatch.value = batch
  bomMatchRows.value = batch?.rows || []
  if (current.value && batch) {
    current.value = {
      ...current.value,
      bom_match_total: batch.total_count || 0,
      bom_match_matched: batch.matched_count || 0,
      bom_match_review: batch.review_count || 0,
      bom_match_missing: batch.missing_count || 0,
      bom_match_updated_at: batch.updated_at || new Date().toISOString()
    }
  }
}

function selectBestBomMatchTab() {
  if (bomMatchBuckets.value.review.length) bomMatchTab.value = 'review'
  else if (bomMatchBuckets.value.missing.length) bomMatchTab.value = 'missing'
  else bomMatchTab.value = 'matched'
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
  await ElMessageBox.confirm(`删除项目「${row.name}」？项目、导入匹配记录和预占会被清除；由焊接/报损标记自动扣减的库存会返还。`, '确认删除项目', {
    type: 'warning',
    confirmButtonText: '删除项目',
    cancelButtonText: '取消'
  })
  const result = await deleteProject(row.id)
  ElMessage.success(result?.restored_quantity ? `已删除，返还库存 ${result.restored_quantity}` : '已删除')
  if (current.value?.id === row.id) current.value = null
  load()
}

async function addBoard() {
  if (!current.value?.id) return
  try {
    const updated = await createProjectBoard(current.value.id)
    replaceProject(updated)
    activeBoardId.value = updated.active_board_id || updated.boards?.at(-1)?.id || activeBoardId.value
    ElMessage.success('已新增一块板')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '新增板子失败')
  }
}

function replaceProject(updated) {
  if (!updated?.id) return
  projects.value = projects.value.map((project) => (project.id === updated.id ? updated : project))
  current.value = updated
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
    await updateBomItem(current.value.id, bomForm.id, {
      component_id: bomForm.component_id,
      required_quantity: bomForm.required_quantity,
      remark: bomForm.remark
    })
  } else {
    await addBomItem(current.value.id, bomForm)
  }
  bomDialog.value = false
  ElMessage.success('已保存')
  load()
}

async function deleteBomRow(row) {
  await ElMessageBox.confirm(
    `删除 ${row.component.name} 的 BOM 行？已有焊接或报损扣库记录时系统会拒绝删除。`,
    '删除 BOM 行',
    { type: 'warning' }
  )
  await deleteBomItem(current.value.id, row.id)
  ElMessage.success('BOM 行已删除，占用已自动取消')
  load()
}

function replaceBomItem(updated) {
  if (!current.value?.bom_items || !updated?.id) return
  const oldItem = current.value.bom_items.find((item) => item.id === updated.id)
  const changedBoardIds = new Set([...(oldItem?.solder_points || []), ...(updated?.solder_points || [])].map((point) => point.board_id).filter(Boolean))
  current.value = {
    ...current.value,
    bom_items: current.value.bom_items.map((item) => (item.id === updated.id ? updated : item)),
    boards: refreshBoardStats(current.value.boards || [], current.value.bom_items.map((item) => (item.id === updated.id ? updated : item)), changedBoardIds)
  }
}

function refreshBoardStats(boards, items, boardIds = new Set()) {
  return boards.map((board) => {
    if (boardIds.size && !boardIds.has(board.id)) return board
    const points = items.flatMap((item) => (item.solder_points || []).filter((point) => point.board_id === board.id))
    const total = points.length
    const soldered = points.filter((point) => point.soldered).length
    const lost = points.filter((point) => point.lost).length
    return {
      ...board,
      solder_total: total,
      soldered_count: soldered,
      lost_count: lost,
      pending_count: Math.max(0, total - soldered),
      solder_progress: total ? Math.round((soldered / total) * 100) : 0
    }
  })
}

function solderPointTitle(point, item) {
  return [
    point.designator,
    point.bom_value || item?.component?.normalized_spec || item?.component?.parameters,
    point.bom_model || item?.component?.model,
    point.bom_footprint || item?.component?.package
  ]
    .filter(Boolean)
    .join(' / ')
}

function solderMeta(item) {
  const first = itemBoardPoints(item)?.[0] || {}
  return [
    first.bom_model || item?.component?.model,
    first.bom_value || item?.component?.normalized_spec || item?.component?.parameters,
    first.bom_footprint || item?.component?.package
  ]
    .filter(Boolean)
    .join(' / ')
}

async function toggleSolderPoint(item, point) {
  if (!current.value || !item?.id || !point?.id) return
  if (!activeBoard.value?.id) return ElMessage.warning('请先选择板子')
  try {
    const updated = await updateBoardBomSolderPoint(current.value.id, activeBoard.value.id, item.id, point.id, { soldered: !point.soldered })
    replaceBomItem(updated)
    ElMessage.success(point.soldered ? '已取消焊接标记，库存已返还' : '已标记焊接，库存已自动扣减')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '更新焊接位号失败')
  }
}

async function markBomSolderBulk(item, soldered) {
  if (!current.value || !activeBoard.value?.id || !item?.id || !itemBoardTotal(item)) return
  try {
    const boardPoints = itemBoardPoints(item)
    const pointIds = boardPoints.length
      ? boardPoints.filter((point) => Boolean(point.soldered) !== Boolean(soldered)).map((point) => point.id)
      : null
    if (boardPoints.length && !pointIds.length) {
      ElMessage.info(soldered ? '当前板这一行已经全部标记已焊' : '当前板这一行已经没有焊接标记')
      return
    }
    const updated = await updateBoardBomSolderPointsBulk(current.value.id, activeBoard.value.id, item.id, { soldered, point_ids: pointIds })
    replaceBomItem(updated)
    ElMessage.success(soldered ? '已标记整行已焊，库存已自动扣减' : '已清除整行焊接标记，库存已返还')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批量更新焊接位号失败')
  }
}

async function toggleSolderLoss(item, point) {
  if (!current.value || !activeBoard.value?.id || !item?.id || !point?.id) return
  try {
    const updated = await updateBoardBomSolderPointLoss(current.value.id, activeBoard.value.id, item.id, point.id, {
      lost: !point.lost,
      note: point.lost ? null : '焊接报损'
    })
    replaceBomItem(updated)
    ElMessage.success(point.lost ? '已取消报损，库存已返还' : '已标记报损，库存已自动扣减')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '更新报损状态失败')
  }
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

function downloadPurchaseBom() {
  if (current.value) exportPurchaseBom(current.value.id, current.value.name)
}

function isSolderComplete(item) {
  const total = itemBoardTotal(item)
  return total > 0 && itemBoardSoldered(item) >= total
}

function bomStatusLabel(status) {
  return { reserved: '预占/待取料', picked: '已取料', done: '旧状态：已完成' }[status || 'reserved'] || status
}

function bomStatusType(status) {
  return { reserved: 'primary', picked: 'warning', done: 'success' }[status || 'reserved'] || 'info'
}

function bomMatchSourceLabel(item) {
  const remark = String(item?.remark || '')
  if (/待采购库|待入库/.test(remark) || item?.component?.status === 'pending_purchase') return '待采购库'
  if (/编号一致|BOM自动导入行/.test(remark)) return '编号一致'
  if (/手动匹配|BOM 位号|AI 判断/.test(remark)) return '手动匹配'
  return ''
}

function bomMatchSourceType(item) {
  const label = bomMatchSourceLabel(item)
  if (label === '编号一致') return 'success'
  if (label === '待采购库') return 'warning'
  return 'info'
}

function openUrl(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

function appBasePath() {
  return import.meta.env.BASE_URL || PERSONAL_BASE
}

function apiBasePath() {
  return import.meta.env.VITE_API_BASE || API_BASE
}

function projectPublicUrl(project) {
  const code = project?.project_code
  if (!code) return ''
  return new URL(`${appBasePath()}public/projects/${encodeURIComponent(code)}`, window.location.origin).toString()
}

function projectQrUrl(project) {
  const code = project?.project_code
  if (!code) return ''
  const suffix = projectQrRetry.value ? `?retry=${projectQrRetry.value}` : ''
  return new URL(`${apiBasePath().replace(/\/$/, '')}/public/projects/${encodeURIComponent(code)}/qr.svg${suffix}`, window.location.origin).toString()
}

function retryProjectQr() {
  projectQrBroken.value = false
  projectQrRetry.value += 1
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
  return row?.id && !row.auto_imported && !row.selected_component_id && row.status !== 'ignored'
}

function canCreatePendingComponent(row) {
  return row?.id && !row.auto_imported && !row.selected_component_id && ['supplier_missing', 'missing', 'review'].includes(row.status) && (row.supplier_part || row.manufacturer_part)
}

async function createPendingPurchase(row) {
  if (!current.value || !canCreatePendingComponent(row)) return
  const batch = await createPendingComponentFromBomRow(current.value.id, row.id)
  applyBomImportBatch(batch)
  if (!activeBomMatchRows.value.length) selectBestBomMatchTab()
  await load()
  ElMessage.success('已加入待采购库并匹配到项目')
}

async function ignoreImportRow(row) {
  if (!current.value || !canIgnoreBomRow(row)) return
  await ElMessageBox.confirm(`忽略 ${row.designator || row.manufacturer_part || row.value || '该 BOM 行'}？它将不再计入待采购和匹配进度。`, '忽略 BOM 行', {
    type: 'warning',
    confirmButtonText: '忽略',
    cancelButtonText: '取消'
  })
  const batch = await ignoreBomImportRow(current.value.id, row.id)
  applyBomImportBatch(batch)
  if (!activeBomMatchRows.value.length) selectBestBomMatchTab()
  ElMessage.success('已忽略，不再计入待采购')
}

async function openStoredBomMatch() {
  if (!current.value) return
  const batch = await loadLatestBomImportBatch(current.value.id)
  bomMatchRows.value = batch.rows || []
  selectBestBomMatchTab()
  bomMatchDialog.value = true
}

function openComponentDetail(component) {
  const keyword = component?.lcsc_number || component?.model || component?.name
  router.push({ name: 'components', query: { keyword } })
}

function substitutionSuggestions(item) {
  return item?.substitution_suggestions || []
}

function substitutionTitle(suggestion) {
  return componentDisplayTitle(suggestion?.component || {})
}

function substitutionSubtitle(suggestion) {
  const component = suggestion?.component || {}
  return componentDisplaySubtitle(component, substitutionTitle(suggestion))
}

function matchStatusLabel(status) {
  return { exact_lcsc: '编号一致', manual_selected: '手动匹配', pending_purchase: '待采购库/待入库', supplier_missing: '编号未入库', exact: '唯一精确', review: '人工确认', missing: '缺料', ignored: '已忽略' }[status] || status || '待确认'
}

function matchStatusType(status) {
  return { exact_lcsc: 'success', manual_selected: 'success', pending_purchase: 'warning', supplier_missing: 'danger', exact: 'success', review: 'warning', missing: 'danger', ignored: 'info' }[status] || 'info'
}

function bomRole(item) {
  const remarkRole = String(item.remark || '')
    .split(/[；;\n]/)
    .find((part) => /作用|用途|BOM 位号|位号/.test(part))
  if (remarkRole) return remarkRole
  return componentOneLineUsage(item.component)
}

function formatBomValue(row) {
  const raw = String(row?.value || '').trim()
  if (!raw) return ''
  if (/[a-zA-Z]/.test(raw)) return raw
  const num = Number(raw)
  if (!Number.isFinite(num)) return raw
  const fp = String(row?.footprint || row?.comment || '').toLowerCase()
  const comment = String(row?.comment || '').toLowerCase()
  const hint = `${fp} ${comment}`
  if (/capacit|电容|pf|nf|µf|uf|mf/.test(hint)) {
    if (Math.abs(num) >= 1e-3) return `${num * 1e3}mF`
    if (Math.abs(num) >= 1e-6) return `${num * 1e6}µF`
    if (Math.abs(num) >= 1e-9) return `${num * 1e9}nF`
    return `${num * 1e12}pF`
  }
  if (/induc|电感|uh|µh|nh|mh/.test(hint)) {
    if (Math.abs(num) >= 1e-3) return `${num * 1e3}mH`
    if (Math.abs(num) >= 1e-6) return `${num * 1e6}µH`
    return `${num * 1e9}nH`
  }
  if (Math.abs(num) >= 1e6) return `${num / 1e6}MΩ`
  if (Math.abs(num) >= 1e3) return `${num / 1e3}kΩ`
  return `${raw}Ω`
}

function bomPrimaryDisplay(row) {
  if (row?.manufacturer_part) return row.manufacturer_part
  const formatted = formatBomValue(row)
  if (formatted && formatted !== '-') return formatted
  return row?.supplier_part || row?.comment || '-'
}

function bomSecondaryDisplay(row) {
  const parts = []
  if (row?.manufacturer_part && row?.value) parts.push(formatBomValue(row))
  if (row?.footprint) parts.push(row.footprint)
  if (row?.supplier_part) parts.push(`LCSC ${row.supplier_part}`)
  if (row?.comment && !parts.some(p => p === row.comment)) parts.push(row.comment)
  return parts
}

function missingItemDisplay(item) {
  if (item?.manufacturer_part) return item.manufacturer_part
  const formatted = formatBomValue(item)
  if (formatted && formatted !== '-') return formatted
  return item?.description || item?.value || '未命名物料'
}

function componentStatusTag(component) {
  const status = component?.status
  if (status === 'pending_purchase') return { label: '待采购/待入库', type: 'warning' }
  if (status === 'pending') return { label: '待验证', type: 'info' }
  if (status === 'obsolete') return { label: '停用', type: 'info' }
  if ((component?.quantity || 0) <= 0) return { label: '无库存', type: 'danger' }
  if ((component?.quantity || 0) <= 5) return { label: '低库存', type: 'warning' }
  return null
}

async function handleBomMatchUpload({ file }) {
  matchingBom.value = true
  try {
    pendingBomFile.value = file
    bomInspection.value = await inspectBomFields(file)
    if (!bomInspection.value.headers?.length) throw new Error('未找到可识别的 BOM 表头')
    bomMappingDialog.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || 'BOM 字段读取失败')
  } finally {
    matchingBom.value = false
  }
}

async function confirmBomMapping(mapping) {
  if (!pendingBomFile.value) return
  matchingBom.value = true
  try {
    bomMatchRows.value = await previewBomMatch(pendingBomFile.value, current.value?.id, mapping)
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
    bomMappingDialog.value = false
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
      import_row_id: row.id,
      component_id: row.selected_component_id,
      required_quantity: row.required_quantity,
      remark: [
        `BOM 位号: ${row.designator || '-'}`,
        `BOM 型号: ${row.manufacturer_part || '-'}`,
        `BOM 参数: ${formatBomValue(row) || row.value || '-'}`,
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
    ElMessage.error(error.response?.data?.detail || '导入项目失败')
  } finally {
    importingMatchedBom.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadCategories(), load()])
})
</script>

<style scoped>
.bom-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
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
  grid-template-columns: 86px minmax(0, 1fr);
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
  border-radius: 16px;
  background: #fff;
  color: var(--cw-text);
  cursor: pointer;
}

.project-item {
  padding: 6px 8px 6px 12px;
}

.project-select {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 2px;
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.project-select span,
.project-select small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-select small {
  color: var(--cw-muted);
  font-size: 12px;
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

.project-sidebar.folded .project-select {
  place-items: center;
  text-align: center;
}

.project-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.compact-toolbar {
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.compact-toolbar :deep(.el-upload) {
  display: inline-flex;
}

:global(.cw-more-popover .more-action-list) {
  display: grid;
  gap: 8px;
}

:global(.cw-more-popover .more-action-list .el-button),
:global(.cw-more-popover .more-action-list .el-upload),
:global(.cw-more-popover .more-action-list .el-upload .el-button) {
  width: 100%;
  margin-left: 0;
}

.project-code-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.public-project-panel {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  margin-bottom: 14px;
  border-color: #c7d2fe;
  background: #f8fbff;
}

.public-qr-box {
  width: 112px;
  aspect-ratio: 1;
}

.public-project-panel img {
  width: 100%;
  height: 100%;
  padding: 6px;
  border: 1px solid #cbd5e1;
  border-radius: var(--cw-radius-control);
  background: #fff;
}

.public-qr-fallback {
  display: grid;
  place-items: center;
  gap: 5px;
  width: 100%;
  height: 100%;
  padding: 8px;
  border: 1px dashed #cbd5e1;
  border-radius: var(--cw-radius-control);
  background: #fff;
  text-align: center;
}

.public-qr-fallback strong {
  font-size: 13px;
}

.public-qr-fallback small {
  color: var(--cw-muted);
  font-size: 12px;
}

.public-project-panel > div:nth-child(2) {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.public-project-panel strong,
.public-project-panel small {
  overflow-wrap: anywhere;
}

.public-project-panel small {
  color: var(--cw-muted);
}

.public-project-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.project-assets {
  margin-bottom: 14px;
}

.project-risk-panel {
  margin-bottom: 14px;
}

.project-assets .section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--cw-muted);
}

.asset-chips {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 9px;
  margin-top: 12px;
}

.asset-chips button {
  display: grid;
  gap: 4px;
  padding: 11px;
  border: 1px solid #e4eaf2;
  border-radius: var(--cw-radius-control);
  background: #f8fafc;
  color: var(--cw-text);
  text-align: left;
  cursor: pointer;
}

.asset-chips strong {
  overflow-wrap: anywhere;
}

.asset-chips small {
  color: var(--cw-muted);
}

.project-risk-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.project-risk-list span {
  padding: 6px 9px;
  border-radius: 999px;
  background: #fffbeb;
  color: #92400e;
  font-size: 12px;
}

.project-risk-list span.danger {
  background: #fff1f2;
  color: #b42318;
}

.risk-more-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  color: var(--cw-muted);
}

.risk-more-row small {
  font-size: 12px;
}

.bom-help {
  margin-bottom: 14px;
}

.board-panel {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
  border-color: #bbf7d0;
  background: #f8fff9;
}

.board-panel-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.board-panel-head > div {
  display: grid;
  gap: 3px;
}

.board-panel-head strong {
  font-size: 20px;
}

.board-panel-head small {
  color: var(--cw-muted);
}

.board-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.board-tab {
  display: grid;
  gap: 3px;
  min-width: 118px;
  padding: 9px 12px;
  border: 1px solid #d1d5db;
  border-radius: var(--cw-radius-control);
  background: #fff;
  color: var(--cw-text);
  text-align: left;
  cursor: pointer;
}

.board-tab.active {
  border-color: #60a5fa;
  background: #eff6ff;
}

.board-tab span {
  font-weight: 760;
}

.board-tab small {
  color: var(--cw-muted);
}

.project-head p {
  margin: 6px 0 0;
  color: var(--cw-muted);
}

.bom-metrics {
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin-bottom: 14px;
}

.solder-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 320px);
  gap: 12px;
  align-items: center;
  margin-bottom: 14px;
}

.solder-toolbar > div:first-child {
  display: grid;
  gap: 3px;
}

.solder-toolbar strong {
  color: var(--cw-text);
  font-size: 16px;
}

.solder-toolbar small {
  color: var(--cw-muted);
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
  border-radius: 16px;
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

.substitution-panel {
  display: grid;
  gap: 8px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid #bfdbfe;
  border-radius: var(--cw-radius-control);
  background: #eff6ff;
}

.substitution-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #1d4ed8;
  font-size: 13px;
}

.substitution-title span {
  color: #64748b;
  font-size: 12px;
}

.substitution-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 10px;
  align-items: center;
  width: 100%;
  padding: 10px;
  border: 1px solid #dbeafe;
  border-radius: var(--cw-radius-control);
  background: #fff;
  color: var(--cw-text);
  text-align: left;
  cursor: pointer;
}

.substitution-card:hover {
  border-color: #60a5fa;
}

.substitution-card span,
.substitution-card small {
  min-width: 0;
}

.substitution-card strong,
.substitution-card small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.substitution-card em {
  color: #166534;
  font-style: normal;
  font-weight: 760;
}

.substitution-reason,
.substitution-warning {
  grid-column: 1 / -1;
  color: #475569;
  white-space: normal !important;
}

.substitution-warning {
  color: #b45309;
}

.solder-point-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}

.solder-meta {
  margin-top: 8px;
  color: #475467;
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.solder-chip {
  display: inline-flex;
  align-items: stretch;
  overflow: hidden;
  min-height: 30px;
  max-width: 190px;
  padding: 4px 8px;
  border: 1px solid #fecdd3;
  border-radius: var(--cw-radius-control);
  background: #fff1f2;
  color: #991b1b;
}

.solder-chip.done {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #166534;
}

.solder-chip-main,
.loss-toggle {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.solder-chip-main {
  min-width: 0;
  display: inline-flex;
  gap: 5px;
  align-items: center;
  padding: 0;
}

.loss-badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 6px;
  border: 1px solid #fed7aa;
  border-radius: 999px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 11px;
  font-style: normal;
  line-height: 1;
  white-space: nowrap;
}

.solder-chip-main:disabled,
.loss-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.loss-toggle {
  margin-left: 6px;
  padding: 0 0 0 6px;
  border-left: 1px solid currentColor;
  font-size: 11px;
  opacity: 0.76;
  white-space: nowrap;
}

.loss-toggle.active {
  color: #9a3412;
  font-weight: 700;
  opacity: 1;
}

.solder-chip-main span,
.solder-chip-main small,
.loss-badge {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.solder-chip-main span {
  font-weight: 760;
}

.solder-chip-main small {
  color: currentColor;
  opacity: 0.72;
  font-size: 11px;
}

.solder-empty {
  margin-top: 8px;
  color: var(--cw-muted);
  font-size: 12px;
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

.bom-stock em {
  color: #2563eb;
  font-style: normal;
  font-weight: 700;
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
  border-radius: 16px;
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
  border-radius: 16px;
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
  border-radius: 16px;
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

.bom-primary-model {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: #101828;
  line-height: 1.3;
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
  border-radius: var(--cw-radius-control);
  background: #f8fafc;
}

@media (max-width: 1180px) {
  .bom-layout {
    grid-template-columns: 220px minmax(0, 1fr);
  }

  .bom-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .solder-toolbar {
    grid-template-columns: 1fr;
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
  .bom-card,
  .public-project-panel {
    display: grid;
    grid-template-columns: 1fr;
  }

  .public-project-actions {
    justify-content: flex-start;
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
