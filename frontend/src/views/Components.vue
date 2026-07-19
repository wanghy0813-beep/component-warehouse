<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">元器件库</h1>
        <p class="page-subtitle">查看库存、位置、采购来源和 AD 工程资料；订单类别优先，AI 只做严格补充</p>
      </div>
      <div class="toolbar compact-toolbar">
        <el-button type="primary" :icon="Plus" @click="openCreate">新增元器件</el-button>
        <el-button :icon="Camera" @click="openScanner()">扫码查找</el-button>
        <el-popover placement="bottom-end" trigger="click" width="220" popper-class="cw-more-popover">
          <template #reference>
            <el-button :icon="MoreFilled">更多操作</el-button>
          </template>
          <div class="more-action-list">
            <el-button @click="exportCurrentIdTable">导出 ID 表</el-button>
            <el-button @click="exportInventory">导出库存 XLSX</el-button>
            <el-button @click="exportCurrentLabels">导出标签/PDF</el-button>
            <el-button @click="openCustomLabelDialog">自定义标签</el-button>
          </div>
        </el-popover>
      </div>
    </div>

    <div class="panel filter-panel">
      <el-input v-model="filters.keyword" clearable placeholder="搜索器件 ID、名称、型号、参数、封装、立创 ID、AI 摘要" @keyup.enter="reloadFromFirstPage" @clear="reloadFromFirstPage" />
      <el-select v-model="filters.category_id" clearable placeholder="分类" @change="reloadFromFirstPage">
        <el-option v-for="item in categories" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="库存状态" @change="reloadFromFirstPage">
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.ai_status" clearable placeholder="AI 状态" @change="reloadFromFirstPage">
        <el-option label="待整理" value="pending" />
        <el-option label="整理中" value="processing" />
        <el-option label="已整理" value="completed" />
        <el-option label="需更新" value="stale" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-select v-model="filters.stock" clearable placeholder="库存" @change="reloadFromFirstPage">
        <el-option label="有库存" value="available" />
        <el-option label="低库存" value="low" />
        <el-option label="缺货" value="empty" />
      </el-select>
      <el-button type="primary" :icon="Search" @click="reloadFromFirstPage">查询</el-button>
    </div>

    <div v-loading="loading" class="category-stack">
        <div v-if="loading && !groups.length" class="component-skeleton-grid" aria-label="正在加载元器件">
          <el-skeleton v-for="index in 8" :key="index" animated>
            <template #template><el-skeleton-item variant="rect" class="component-skeleton" /></template>
          </el-skeleton>
        </div>
        <section v-for="group in groups" :key="group.category?.id || 'none'" class="category-block">
          <button class="category-head" @click="toggleGroup(group.category?.id || 'none')">
            <span class="category-color" :style="{ background: group.category?.color || '#eef2f7' }"></span>
            <strong>{{ group.category?.name || '未分类' }}</strong>
            <span>{{ group.total }} 个</span>
          </button>
          <div v-show="!collapsedGroups.has(group.category?.id || 'none')" class="component-grid">
            <inventory-component-card v-for="item in group.items" :key="item.id" :item="item" @open="openDetail(item)">
              <template #badges>
                  <el-tag v-if="showSourceBadge(item)" effect="plain" type="info">{{ sourceLabel(item.source) }}</el-tag>
                  <el-tag v-if="showAiBadge(item.ai_status)" :type="aiStatusType(item.ai_status)" effect="plain">{{ aiStatusLabel(item.ai_status) }}</el-tag>
                <el-tag v-if="item.status" size="small" :type="statusType(item.status)">{{ statusLabel(item.status) }}</el-tag>
              </template>
              <template #actions>
                <el-button size="small" plain :icon="CopyDocument" @click.stop="copyComponentName(item)">复制型号</el-button>
                <el-button size="small" plain @click.stop="openComponentLabel(item)">二维码</el-button>
                <el-button size="small" plain @click.stop="openLcsc(item)">立创搜索</el-button>
              </template>
              <template #stock-action>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  title="按先进先出从可用库存扣减 1 个"
                  :loading="quickConsumeIds.has(item.id)"
                  :disabled="Number(item.available_quantity || 0) <= 0"
                  @click.stop="quickConsume(item)"
                >领用 1 个</el-button>
              </template>
            </inventory-component-card>
          </div>
        </section>
        <div ref="autoLoadSentinel" class="auto-load-sentinel" aria-live="polite">
          <span v-if="loading && groups.length">正在加载更多…</span>
          <el-button v-else-if="autoLoadError && categoryPaging.hasMore" class="load-more" @click="loadMoreCategories">重新加载</el-button>
          <span v-else-if="categoryPaging.hasMore">继续下滑自动加载</span>
          <span v-else-if="groups.length">已加载全部类别</span>
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

    <multi-qr-scanner
      v-model="scannerVisible"
      title="扫描二维码查找个人器件"
      :resolve-batch="resolvePersonalScanBatch"
      :search-candidates="searchPersonalScanCandidates"
      :initial-expected-code="scannerTarget?.warehouse_code || ''"
      :initial-expected-label="scannerTarget ? componentDisplayTitle(scannerTarget) : ''"
      @select="openScannedComponent"
    />

    <label-export-dialog
      v-model="labelDialog"
      :loading="labelExporting"
      :show-scope="labelExportMode !== 'single'"
      :category-options="categories"
      :custom-label-templates="customLabels"
      @export="runLabelExport"
    />

    <el-drawer
      v-model="drawerVisible"
      class="component-detail-drawer"
      modal-class="component-detail-overlay"
      append-to-body
      destroy-on-close
      :title="drawerTitle"
      size="min(1040px, calc(100vw - 40px))"
      @opened="resetDetailDrawerScroll"
    >
      <template v-if="selected">
        <inventory-component-detail
          :item="selected"
          :usage-records="usageRecords"
          :usage-loading="usageLoading"
          :eda-bindings="edaBindings"
          :supplier-parts="supplierParts"
          :inventory-lots="inventoryLots"
          :eda-loading="edaLoading"
          :engineering-enabled="FEATURE_EDA_ENABLED"
          :lots-loading="lotsLoading"
          :lot-saving="lotSaving"
          :lot-consume-ids="lotConsumeIds"
          :ai-ask-loading="aiAskLoading"
          :ai-answer="aiAnswer"
          @load-usage="loadUsage"
          @load-lots="loadLots"
          @add-lot="addInventoryLot"
          @consume-lot="consumeInventoryLot"
          @delete-lot="deleteInventoryLot"
          @ask-ai="askSelectedComponentAi"
        >
          <template #actions>
            <div class="detail-links">
              <el-button size="small" type="primary" plain :icon="CopyDocument" @click="copyComponentName(selected)">复制型号</el-button>
              <el-button size="small" type="primary" plain @click="openComponentLabel(selected)">二维码标签</el-button>
              <el-button size="small" type="primary" plain :icon="Camera" @click="openScannerForSelected">扫码定位此器件</el-button>
              <el-button size="small" type="primary" plain @click="openLcsc(selected)">{{ selected.buy_url ? '立创商品' : '立创搜索' }}</el-button>
              <el-button v-if="selected.datasheet_url" size="small" plain @click="windowOpen(selected.datasheet_url)">数据手册</el-button>
              <el-button size="small" type="danger" plain @click="removeSelectedComponent">移除记录</el-button>
            </div>
          </template>
        </inventory-component-detail>

        <div v-if="false" class="detail-summary">
          <div class="detail-tags">
            <el-tag effect="plain" :style="tagStyle(selected.category)">{{ selected.category?.name || '未分类' }}</el-tag>
            <el-tag v-if="selected.warehouse_code" effect="plain" type="info">{{ selected.warehouse_code }}</el-tag>
            <el-tag v-if="showSourceBadge(selected)" effect="plain" type="info">{{ sourceLabel(selected.source) }}</el-tag>
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
            <el-tag v-if="showAiBadge(selected.ai_status)" :type="aiStatusType(selected.ai_status)">{{ aiStatusLabel(selected.ai_status) }}</el-tag>
            <el-tag v-if="selected.first_stocked_at" type="info" effect="plain">入库 {{ formatDate(selected.first_stocked_at) }}</el-tag>
            <el-tag v-if="selected.last_outbound_at" type="info" effect="plain">最近出库 {{ formatDate(selected.last_outbound_at) }}</el-tag>
          </div>
          <div class="detail-links">
            <el-button size="small" type="primary" plain :icon="CopyDocument" @click="copyComponentName(selected)">复制型号</el-button>
            <el-button size="small" type="primary" plain @click="openComponentLabel(selected)">二维码标签</el-button>
            <el-button size="small" type="primary" plain @click="openLcsc(selected)">立创搜索</el-button>
            <el-button v-if="selected.datasheet_url" size="small" plain @click="windowOpen(selected.datasheet_url)">数据手册</el-button>
          </div>
        </div>

        <div class="drawer-actions">
          <el-button :loading="aiRefreshing" @click="refreshAi('full')">刷新 AI 信息</el-button>
          <el-button @click="undoAiChange">撤销最近 AI 修改</el-button>
          <el-button type="primary" @click="editing = !editing">{{ editing ? '收起编辑' : '编辑' }}</el-button>
        </div>

        <div v-if="false" class="ai-section">
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
      </template>

        <component-create-workspace
          v-if="editing && !selected"
          ref="createWorkspace"
          v-model:quick-prompt="quickAddPrompt"
          :form="form"
          :categories="categories"
          :lookup="previewLcscComponent"
          :ai-loading="aiCreateLoading"
          :ai-suggestion="aiCreateSuggestion"
          :saving="saving"
          :importing="importing"
          :importing-images="importingImages"
          :external-parsing="externalParsing"
          :lcsc-order-upload="handleExcelUpload"
          :image-upload="handleImageUpload"
          :external-order-upload="handleExternalOrderUpload"
          :download-template="downloadExternalOrderTemplate"
          @ai-complete="completeFormWithAi"
          @lcsc-draft="applyLcscDraft"
          @lcsc-existing="openExistingLcscComponent"
          @cancel="drawerVisible = false"
          @submit="submitForm"
        />

        <el-form v-else-if="editing" label-position="top" :model="form" class="edit-form">
          <section class="quick-create-card">
            <div>
              <strong>AI 辅助补齐</strong>
              <p>先输入大概信息，例如“AMS1117-3.3 SOT-223 10个”或“0805 10k 1% 电阻”，AI 只生成草稿，保存前可以手动修改。</p>
            </div>
            <el-input
              v-model="quickAddPrompt"
              type="textarea"
              :rows="2"
              maxlength="300"
              show-word-limit
              placeholder="输入型号、参数、封装、立创编号、用途或购买来源"
            />
            <div class="quick-create-actions">
              <el-button type="primary" plain :loading="aiCreateLoading" @click="completeFormWithAi">AI 补齐草稿</el-button>
              <span v-if="aiCreateSuggestion" class="ai-confidence">置信度：{{ confidenceLabel(aiCreateSuggestion.confidence) }}</span>
            </div>
            <div v-if="aiCreateSuggestion" class="ai-draft-summary">
              <span>{{ aiCreateSuggestion.summary || '已生成草稿，请核对关键参数。' }}</span>
              <small v-if="aiCreateSuggestion.need_datasheet_check">需要核对数据手册</small>
            </div>
          </section>

          <p class="required-hint"><span>*</span> 必填：名称或型号、数量。AI 补齐后仍建议核对分类、封装和立创 ID。</p>
          <div class="edit-form-grid">
            <el-form-item label="器件 ID"><el-input v-model="form.warehouse_code" disabled placeholder="保存后自动生成" /></el-form-item>
            <el-form-item label="名称" required><el-input v-model="form.name" placeholder="例如 10kΩ 电阻 / AMS1117-3.3" /></el-form-item>
            <el-form-item label="型号"><el-input v-model="form.model" placeholder="厂商型号 MPN，可空" /></el-form-item>
            <el-form-item label="数量" required><el-input-number v-model="form.quantity" :min="0" style="width: 100%" /></el-form-item>
            <el-form-item label="分类">
            <el-select v-model="form.category_id" clearable filterable style="width: 100%">
              <el-option v-for="item in categories" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
            </el-form-item>
            <el-form-item label="封装"><el-input v-model="form.package" placeholder="例如 0805 / SOT-223 / QFN-32" /></el-form-item>
            <el-form-item label="立创 ID"><el-input v-model="form.lcsc_number" placeholder="Cxxxxxx，可空" /></el-form-item>
            <el-form-item label="厂商"><el-input v-model="form.manufacturer" /></el-form-item>
            <el-form-item label="安全库存"><el-input-number v-model="form.safety_quantity" :min="0" style="width: 100%" /></el-form-item>
            <el-form-item label="来源"><el-input v-model="form.source" placeholder="手动新增 / 立创 / 图片识别导入" /></el-form-item>
            <el-form-item label="参数" class="wide-field"><el-input v-model="form.parameters" type="textarea" :rows="2" /></el-form-item>
            <el-form-item label="描述" class="wide-field"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
            <el-form-item label="标签"><el-input v-model="form.tags" /></el-form-item>
            <el-form-item label="数据手册"><el-input v-model="form.datasheet_url" /></el-form-item>
            <el-form-item label="立创商品"><el-input v-model="form.buy_url" placeholder="立创商品页链接" /></el-form-item>
            <el-form-item label="备注" class="wide-field"><el-input v-model="form.remark" type="textarea" :rows="3" /></el-form-item>
          </div>
          <el-form-item label="AI 标签" class="flag-checks">
            <el-checkbox v-model="form.is_common">常用</el-checkbox>
            <el-checkbox v-model="form.low_stock_exempt">免低库存预警</el-checkbox>
            <el-checkbox v-model="form.is_hand_solder_friendly">适合手焊</el-checkbox>
            <el-checkbox v-model="form.is_power_component">电源</el-checkbox>
            <el-checkbox v-model="form.is_signal_component">信号</el-checkbox>
            <el-checkbox v-model="form.is_high_current">大电流</el-checkbox>
            <el-checkbox v-model="form.is_high_voltage">高压</el-checkbox>
          </el-form-item>
          <div class="drawer-save-bar">
            <el-button @click="editing = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="submitForm">保存元器件</el-button>
          </div>
        </el-form>
    </el-drawer>

    <el-dialog v-model="previewVisible" title="Excel 导入预览" width="90%">
      <el-alert type="info" show-icon :closable="false" class="import-alert">
        系统会按立创 ID 自动判断新增、合并或跳过；待采购库同 ID 到货会自动转为在库。
      </el-alert>
      <el-table :data="previewRows" max-height="480" empty-text="没有可导入数据">
        <el-table-column prop="order_number" label="订单编号" min-width="140" />
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="model" label="型号" min-width="150" />
        <el-table-column prop="package" label="封装" width="100" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column prop="lcsc_number" label="立创 ID" width="130" />
        <el-table-column label="自动处理" width="150">
          <template #default="{ row }">
            <el-tag :type="importActionType(row)">{{ importActionLabel(row) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <section v-if="importBatches.length" class="import-history">
        <div class="import-history-head">
          <strong>最近导入批次</strong>
          <el-button size="small" text @click="loadImportBatches">刷新</el-button>
        </div>
        <div class="import-batch-list">
          <article v-for="batch in importBatches.slice(0, 3)" :key="batch.id" class="import-batch-card">
            <div>
              <strong>#{{ batch.id }} {{ batch.source_file || 'Excel 导入' }}</strong>
              <p>新增 {{ batch.created_count }}，合并 {{ batch.merged_count }}，跳过 {{ batch.skipped_count }}，抵消待采购 {{ batch.resolved_pending_count }}</p>
            </div>
            <el-tag :type="batch.status === 'rolled_back' ? 'info' : 'success'">{{ batch.status === 'rolled_back' ? '已撤销' : '有效' }}</el-tag>
            <el-button size="small" :disabled="batch.status === 'rolled_back'" @click="rollbackImportBatch(batch)">撤销</el-button>
          </article>
        </div>
      </section>
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

    <el-dialog v-model="externalPreviewVisible" title="外部订单导入预览" width="94%">
      <el-alert type="info" show-icon :closable="false" class="import-alert">
        外部订单会先由 AI 解析整张表格，提取真实元器件数量、规范名称、分类、型号和参数；本地只负责去重、合并和入库。
        <el-button size="small" text @click="downloadExternalOrderTemplate">下载样表模板</el-button>
      </el-alert>
      <el-table :data="externalPreviewRows" max-height="520" empty-text="没有可导入数据">
        <el-table-column prop="source_row" label="行" width="70" />
        <el-table-column prop="name" label="规范名称" min-width="220" show-overflow-tooltip />
        <el-table-column prop="model" label="型号" min-width="150" show-overflow-tooltip />
        <el-table-column prop="normalized_spec" label="核心值" min-width="120" show-overflow-tooltip />
        <el-table-column prop="package" label="封装" min-width="110" show-overflow-tooltip />
        <el-table-column prop="parameters" label="参数" min-width="180" show-overflow-tooltip />
        <el-table-column prop="quantity" label="入库数量" width="95" />
        <el-table-column label="AI" min-width="160">
          <template #default="{ row }">
            <el-tag size="small" :type="row.ai_confidence === 'high' ? 'success' : row.ai_confidence === 'low' ? 'warning' : 'info'">
              {{ row.ai_confidence || 'medium' }}
            </el-tag>
            <span class="muted small-text">{{ row.ai_reason }}</span>
          </template>
        </el-table-column>
        <el-table-column label="处理" width="150">
          <template #default="{ row }">
            <el-tag :type="row.already_imported ? 'info' : row.duplicate ? 'warning' : 'success'">
              {{ row.already_imported ? '已导入' : row.duplicate ? '自动合并' : '自动新增' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="externalPreviewVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="confirmExternalOrderImport">确认导入</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElNotification } from '../shared/elementApi'
import { useRoute, useRouter } from 'vue-router'
import { Camera, CopyDocument, MoreFilled, Plus, Search } from '@element-plus/icons-vue'
import InventoryComponentCard from '../components/inventory/InventoryComponentCard.vue'
import InventoryComponentDetail from '../components/inventory/InventoryComponentDetail.vue'
import ComponentCreateWorkspace from '../components/inventory/ComponentCreateWorkspace.vue'
import MultiQrScanner from '../shared/components/MultiQrScanner.vue'
import { applyInventoryLotConsumption } from '../shared/inventoryLotState'
import LabelExportDialog from '../shared/components/LabelExportDialog.vue'
import {
  commitExcel,
  commitExternalOrder,
  askComponentAi,
  aiComponentInfo,
  createComponentLot,
  deleteComponentLot,
  deleteComponent,
  decrementComponentQuantity,
  downloadExternalOrderTemplate,
  exportComponentIdTable,
  exportComponentInventory,
  exportComponentLabelSheet,
  incrementComponentQuantity,
  getCategories,
  getComponentAi,
  getComponentLots,
  getComponentUsageRecords,
  getGroupedComponentsPage,
  getOrderImportBatches,
  getSearchSuggestions,
  listCustomLabels,
  organizeComponent,
  previewImageImport,
  previewLcscComponent,
  previewExcel,
  previewExternalOrder,
  recordUsageEvent,
  refreshComponentAi,
  resolvePersonalScanBatch,
  searchPersonalScanCandidates,
  rollbackOrderImportBatch,
  saveComponent,
  undoLatestComponentAi
} from '../api/client'
import { componentOneLineUsage, componentUnitHints, extractComponentChips, makeLcscSearchUrl, normalizeToken, splitTags } from '../utils/componentUi'
import { componentDisplayTitle, uniqueDisplayParts } from '../shared/componentDisplay'
import { listEdaBindings, listSupplierParts } from '../shared/engineeringApi'
import { trackUsage } from '../shared/usageTracker'
import { FEATURE_EDA_ENABLED } from '../shared/features'

const categories = ref([])
const groups = ref([])
const loading = ref(false)
const autoLoadSentinel = ref(null)
const autoLoadError = ref(false)
let autoLoadObserver = null
const suggestionLoading = ref(false)
const saving = ref(false)
const importing = ref(false)
const importingImages = ref(false)
const externalParsing = ref(false)
const aiRefreshing = ref(false)
const previewVisible = ref(false)
const imagePreviewVisible = ref(false)
const externalPreviewVisible = ref(false)
const previewRows = ref([])
const importBatches = ref([])
const imagePreviewRows = ref([])
const externalPreviewRows = ref([])
const drawerVisible = ref(false)
const scannerVisible = ref(false)
const scannerTarget = ref(null)
const labelDialog = ref(false)
const labelExporting = ref(false)
const labelExportMode = ref('all')
const labelSingleId = ref(null)
const customLabels = ref([])
const selected = ref(null)
const knowledgeCards = ref([])
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
const aiAskLoading = ref(false)
const aiAnswer = ref(null)
const aiCreateLoading = ref(false)
const aiCreateSuggestion = ref(null)
const quickAddPrompt = ref('')
const createWorkspace = ref(null)
const lastLcscDraft = ref({})
const inventoryChannel = 'BroadcastChannel' in window ? new BroadcastChannel('cw-inventory-sync') : null
const editing = ref(false)
const collapsedGroups = ref(new Set())
const route = useRoute()
const router = useRouter()
const searchSuggestion = ref(null)
const pagination = reactive({ page: 1, pageSize: 60, total: 0 })
const categoryPaging = reactive({ page: 1, pageSize: 3, categoryTotal: 0, hasMore: false })
let suggestionRequestId = 0
let autoOpenComponentCode = ''

const filters = reactive({ keyword: '', category_id: null, status: '', ai_status: '', stock: '' })
const emptyForm = {
  id: null,
  warehouse_code: '',
  name: '',
  model: '',
  manufacturer: '',
  description: '',
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
  buy_url: '',
  source_title: '',
  is_hand_solder_friendly: false,
  is_power_component: false,
  is_signal_component: false,
  is_high_current: false,
  is_high_voltage: false,
  is_common: false,
  safety_quantity: 0,
  low_stock_exempt: false
}
const form = reactive({ ...emptyForm })

const drawerTitle = computed(() => (selected.value ? (selected.value.name || selected.value.model || '元器件详情') : '新增元器件'))
const currentPageItems = computed(() => groups.value.flatMap((group) => group.items || []))
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
const unknownSpecWords = ['未知', '未从资料确认', '未确认', '需查手册', '需要手册', '典型值', '推断', '估算', '暂无', '不详']
function looksUnknownSpec(value) {
  const text = String(value || '').toLowerCase()
  return unknownSpecWords.some((word) => text.includes(word.toLowerCase()))
}
const keySpecList = computed(() =>
  (aiUsage.value.key_specs || [])
    .map(normalizeKeySpec)
    .filter((item) => item && !looksUnknownSpec(`${item.name} ${item.value}`))
)
const specChips = computed(() =>
  extractComponentChips(selected.value, 10).filter((chip) => !looksUnknownSpec(`${chip.label} ${chip.value}`))
)
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
  { label: '导入已撤销', value: 'rolled_back' },
  { label: '停用', value: 'obsolete' }
]
const stockLabels = { available: '有库存', low: '低库存', empty: '缺货' }

function statusLabel(value) {
  return statusOptions.find((item) => item.value === value)?.label || value
}

function statusType(value) {
  return { in_stock: 'success', low_stock: 'warning', pending_purchase: 'warning', pending: 'info', rolled_back: 'info', obsolete: 'danger' }[value] || 'info'
}

function aiStatusLabel(value) {
  return { pending: '待整理', processing: '整理中', completed: '已整理', failed: '失败', stale: '需更新' }[value || 'pending'] || value
}

function aiStatusType(value) {
  return { pending: 'info', processing: 'warning', completed: 'success', failed: 'danger', stale: 'warning' }[value || 'pending'] || 'info'
}

function confidenceLabel(value) {
  return { high: '高', medium: '中', low: '低' }[value] || '待确认'
}

function showAiBadge(value) {
  return ['pending', 'processing', 'stale'].includes(value || 'pending')
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString()
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
  电感: ['感值', '电感值', '标称感值', '阻抗', '标称阻抗', '磁珠阻抗'],
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

const passivePackageTokens = new Set([
  '0201',
  '0402',
  '0603',
  '0805',
  '1206',
  '1210',
  '1812',
  '2010',
  '2512',
  'c0201',
  'c0402',
  'c0603',
  'c0805',
  'c1206',
  'r0201',
  'r0402',
  'r0603',
  'r0805',
  'r1206',
  'r1210',
  'r2512'
])

function isPackageLikeSpec(value) {
  const text = comparableToken(value)
  if (!text) return false
  if (passivePackageTokens.has(text)) return true
  if ((text.startsWith('c') || text.startsWith('r')) && passivePackageTokens.has(text.slice(1))) return true
  if (text.includes('08052012') || text.includes('06031608') || text.includes('04021005') || text.includes('12063216')) return true
  if (text.includes('smd') || text.includes('metric')) return true
  const hasElectricalUnit = ['ω', 'ohm', 'pf', 'nf', 'µf', 'uf', 'nh', 'µh', 'uh', 'mh'].some((unit) => text.includes(unit))
  if (text.includes('mm') && !hasElectricalUnit) return true
  return false
}

function ferriteSpecFromItem(item) {
  const specs = keySpecsFor(item)
  const aiSpec = specs.find((spec) => {
    const name = normalizeToken(spec.name)
    return (name.includes('阻抗') || name.includes('磁珠')) && !isPackageLikeSpec(spec.value)
  })
  if (aiSpec?.value) return { name: aiSpec.name || '磁珠阻抗', value: aiSpec.value, confidence: aiSpec.confidence || 'high' }
  const text = [item?.normalized_spec, item?.parameters, item?.name, item?.model, item?.source_title, item?.tags, item?.ai_tags]
    .filter(Boolean)
    .join(' ')
  const match = text.match(/\d+(?:\.\d+)?\s*(?:Ω|ohm)\s*@\s*\d+(?:\.\d+)?\s*(?:hz|khz|mhz|ghz)/i)
  if (match) return { name: '磁珠阻抗', value: match[0].replace(/\s+/g, ''), confidence: 'medium' }
  return null
}

function passiveSpecFromText(item, category) {
  const text = [item?.normalized_spec, item?.parameters, item?.name, item?.model, item?.source_title, item?.tags, item?.ai_tags]
    .filter(Boolean)
    .join(' ')
  const patterns = {
    电阻: /(?:^|[^\w.])(\d+(?:\.\d+)?\s*(?:mΩ|Ω|ohm|kΩ|kohm|MΩ|Mohm|GΩ|Gohm))(?:$|[^\w.])/i,
    电容: /(?:^|[^\w.])(\d+(?:\.\d+)?\s*(?:pF|nF|uF|µF|mF|F))(?:$|[^\w.])/i,
    电感: /(?:^|[^\w.])(\d+(?:\.\d+)?\s*(?:nH|uH|µH|mH|H))(?:$|[^\w.])/i
  }
  const match = text.match(patterns[category])
  const value = match?.[1]?.replace(/\s+/g, '')
  if (!value || isPackageLikeSpec(value)) return null
  return { name: titleSpecNames[category][0], value, confidence: 'medium' }
}

function isFerriteBeadItem(item) {
  const text = [item?.name, item?.normalized_spec, item?.parameters, item?.tags, item?.ai_tags, item?.part_family]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return text.includes('磁珠') || text.includes('ferrite') || Boolean(ferriteSpecFromItem(item))
}

function passiveFallbackSpec(item, category) {
  const value = String(item?.normalized_spec || '').trim()
  if (!value || isPackageLikeSpec(value)) return null
  return { name: titleSpecNames[category][0], value, confidence: 'high' }
}

function titleSpec(item) {
  const category = item?.category?.name || ''
  if (category === '电感' && isFerriteBeadItem(item)) {
    const ferrite = ferriteSpecFromItem(item)
    if (ferrite?.value && !isPackageLikeSpec(ferrite.value)) return ferrite
  }
  const aiSpec = findSpecByNames(item, titleSpecNames[category] || [])
  if (aiSpec && !isPackageLikeSpec(aiSpec.value)) return aiSpec
  if (titleSpecNames[category]) {
    return passiveFallbackSpec(item, category) || passiveSpecFromText(item, category)
  }
  return null
}

function passiveDisplayName(item, category) {
  const name = String(item?.name || '').trim()
  if (name && !isPackageLikeSpec(name)) return name
  const model = String(item?.model || '').trim()
  if (model && !isPackageLikeSpec(model)) return model
  const fallback = String(item?.parameters || '').trim()
  if (fallback && !isPackageLikeSpec(fallback)) return fallback
  return `${category}物料`
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
  if (spec?.value && ['电阻', '电容', '电感', '时钟源'].includes(category)) {
    if (category === '电阻' && comparableToken(spec.value) === '0ω') return '0Ω 跳线电阻'
    if (category === '电感' && isFerriteBeadItem(item)) return `${spec.value} 磁珠`
    if (category === '时钟源') return `${spec.value} ${clockTitleSuffix(item)}`
    return spec.value
  }
  if (['电阻', '电容', '电感'].includes(category)) return passiveDisplayName(item, category)
  if (category === '连接件' && item?.normalized_spec) return item.normalized_spec
  if (descriptiveNameCategories.has(category)) return item?.model || item?.name || item?.normalized_spec || '未命名物料'
  return item?.model || item?.name || item?.normalized_spec || '未命名物料'
}

function secondaryLabel(item) {
  const category = item?.category?.name || ''
  const coreSpec = titleSpec(item)
  const coreValue = comparableToken(coreSpec?.value)
  const values = ['电阻', '电容', '电感'].includes(category)
    ? [item?.model, item?.name, item?.package, item?.normalized_spec]
    : [item?.normalized_spec, item?.name, item?.package, item?.model]
  const parts = uniqueDisplayParts(values, primaryLabel(item))
    .filter((part) => {
      const comparable = comparableToken(part)
      if (coreValue && comparable.includes(coreValue)) return false
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
  if (text === 'BOM 待采购库') return 'BOM 待采购库'
  if (text.includes('立创') || text.toLowerCase().includes('lcsc')) return '立创'
  if (text.includes('图片')) return '图片识别导入'
  return text.length > 12 ? `${text.slice(0, 12)}…` : text
}

function showSourceBadge(item) {
  const source = String(item?.source || '').trim()
  if (!source) return false
  if (source === 'BOM 待采购库') {
    return item?.status === 'pending_purchase' && Number(item?.quantity || 0) <= 0
  }
  return true
}

function oneLineUsage(item) {
  return componentOneLineUsage(item)
}

function windowOpen(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function openBlob(blob) {
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

function openLcsc(item) {
  windowOpen(item?.buy_url || makeLcscSearchUrl(item?.lcsc_number || item?.model || item?.name))
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

function currentExportIds() {
  return currentPageItems.value.map((item) => item.id).filter(Boolean)
}

async function exportCurrentIdTable() {
  const ids = currentExportIds()
  if (!ids.length) return ElMessage.warning('当前页没有可导出的元器件')
  try {
    const blob = await exportComponentIdTable(ids)
    downloadBlob(blob, `component-ids-${new Date().toISOString().slice(0, 10)}.csv`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '导出 ID 表失败')
  }
}

async function exportInventory() {
  try {
    const blob = await exportComponentInventory()
    downloadBlob(blob, `component-inventory-${new Date().toISOString().slice(0, 10)}.xlsx`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '导出库存失败')
  }
}

async function exportCurrentLabels() {
  await loadCustomLabels()
  labelExportMode.value = 'all'
  labelDialog.value = true
}

async function openComponentLabel(item) {
  if (!item?.id) return
  labelExportMode.value = 'single'
  labelSingleId.value = item.id
  labelDialog.value = true
}

async function runLabelExport(options) {
  labelExporting.value = true
  try {
    const scope = labelExportMode.value === 'single' ? 'single' : (options?.scope || labelExportMode.value)
    const exportOptions = { ...(options || {}) }
    if (labelExportMode.value === 'single') {
      exportOptions.imported_from = null
      exportOptions.imported_to = null
    }
    const ids = labelExportMode.value === 'single'
      ? [labelSingleId.value]
      : []
    const blob = await exportComponentLabelSheet(ids, labelExportMode.value !== 'single', exportOptions)
    openBlob(blob)
    trackUsage(recordUsageEvent, 'ui.components.label_export', { entry: scope, detail: { count: ids.length || 'all' } })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '导出标签失败')
  } finally {
    labelExporting.value = false
  }
}

async function openCustomLabelDialog() {
  router.push({ name: 'custom-labels' })
}

async function loadCustomLabels() {
  try {
    customLabels.value = await listCustomLabels()
  } catch {
    customLabels.value = []
  }
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

async function load({ append = false } = {}) {
  loading.value = true
  try {
    const params = { ...filters }
    params.page = categoryPaging.page
    params.page_size = categoryPaging.pageSize
    const data = await getGroupedComponentsPage(params)
    const nextGroups = (data.groups || []).map((group) => ({
      ...group,
      items: (group.items || []).map(decorateComponent)
    }))
    if (append) {
      const merged = new Map(groups.value.map((group) => [group.category?.id || 'none', group]))
      for (const group of nextGroups) {
        const key = group.category?.id || 'none'
        const current = merged.get(key)
        if (!current) {
          merged.set(key, group)
          continue
        }
        const itemsById = new Map(current.items.map((item) => [item.id, item]))
        for (const item of group.items) itemsById.set(item.id, item)
        merged.set(key, { ...current, ...group, items: [...itemsById.values()] })
      }
      groups.value = [...merged.values()]
    } else {
      groups.value = nextGroups
    }
    pagination.total = data.total || 0
    categoryPaging.categoryTotal = data.category_total || 0
    categoryPaging.hasMore = Boolean(data.has_more)
    maybeLoadSearchSuggestions()
    maybeOpenComponentFromRoute()
  } catch (error) {
    ElMessage.error('读取元器件失败')
    if (append) throw error
  } finally {
    loading.value = false
  }
}

function maybeOpenComponentFromRoute() {
  const code = String(route.query.component || autoOpenComponentCode || '').trim()
  if (!code) return
  const target = currentPageItems.value.find((item) => String(item.warehouse_code || '').toLowerCase() === code.toLowerCase())
  if (!target) return
  autoOpenComponentCode = ''
  openDetail(target)
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
  categoryPaging.page = 1
  categoryPaging.hasMore = false
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
    trackUsage(recordUsageEvent, 'ui.components.auto_load', { entry: 'category-sentinel', detail: { page: categoryPaging.page } })
    await load({ append: true })
  } catch {
    categoryPaging.page = Math.max(1, categoryPaging.page - 1)
    autoLoadError.value = true
  } finally {
    await nextTick()
    setupAutoLoadObserver()
  }
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
  trackUsage(recordUsageEvent, 'ui.components.create_open', { entry: 'top-toolbar' })
  selected.value = null
  fillForm()
  editing.value = true
  inventoryLots.value = []
  aiAnswer.value = null
  aiCreateSuggestion.value = null
  quickAddPrompt.value = ''
  lastLcscDraft.value = {}
  drawerVisible.value = true
  resetDetailDrawerScroll()
  nextTick(() => createWorkspace.value?.reset())
}

async function openDetail(row, edit = false) {
  trackUsage(recordUsageEvent, 'ui.components.detail_open', { target_type: 'component', target_id: row?.id, entry: edit ? 'edit' : 'card' })
  selected.value = row
  fillForm(row)
  editing.value = edit
  drawerVisible.value = true
  resetDetailDrawerScroll()
  edaBindings.value = []
  supplierParts.value = []
  inventoryLots.value = []
  aiAnswer.value = null
  aiCreateSuggestion.value = null
  quickAddPrompt.value = [row.model, row.normalized_spec, row.package, row.lcsc_number].filter(Boolean).join(' ')
  edaLoading.value = FEATURE_EDA_ENABLED
  lotsLoading.value = true
  const engineeringRequests = FEATURE_EDA_ENABLED
    ? [listEdaBindings(row.id), listSupplierParts(row.id)]
    : [Promise.resolve([]), Promise.resolve([])]
  const [aiResult, bindingsResult, suppliersResult, lotsResult] = await Promise.allSettled([
    getComponentAi(row.id),
    ...engineeringRequests,
    getComponentLots(row.id)
  ])
  if (selected.value?.id !== row.id) return
  if (aiResult.status === 'fulfilled') {
    selected.value = aiResult.value.component
    fillForm(aiResult.value.component)
    knowledgeCards.value = aiResult.value.knowledge_cards || []
  } else {
    knowledgeCards.value = []
  }
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
  usageRecords.value = []
}

function resetDetailDrawerScroll() {
  nextTick(() => {
    const body = document.querySelector('.component-detail-drawer .el-drawer__body')
    body?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  })
}

function categoryIdFromSuggestion(name) {
  const text = String(name || '').trim()
  if (!text) return null
  const exact = categories.value.find((item) => item.name === text)
  if (exact) return exact.id
  const contained = categories.value.find((item) => text.includes(item.name) || item.name.includes(text))
  return contained?.id || null
}

const lcscAutoFields = [
  'name',
  'model',
  'manufacturer',
  'description',
  'category_id',
  'parameters',
  'package',
  'source',
  'lcsc_number',
  'tags',
  'source_title',
  'datasheet_url',
  'buy_url'
]

function isBlankFormValue(value) {
  return value === null || value === undefined || String(value).trim() === ''
}

function applyLcscDraft(draft) {
  const previous = lastLcscDraft.value || {}
  for (const field of lcscAutoFields) {
    const nextValue = draft?.[field]
    if (nextValue === undefined || nextValue === null || nextValue === '') continue
    if (isBlankFormValue(form[field]) || form[field] === previous[field]) {
      form[field] = nextValue
    }
  }
  form.quantity = Number(form.quantity || 0)
  lastLcscDraft.value = Object.fromEntries(lcscAutoFields.map((field) => [field, draft?.[field]]))
  aiCreateSuggestion.value = null
  ElMessage.success('立创器件草稿已填充，请核对数量和本地信息后保存')
}

function openExistingLcscComponent(component) {
  if (!component?.id) return
  lastLcscDraft.value = {}
  openDetail(decorateComponent(component), false)
}

function aiKeySpecsToParameters(result) {
  const specs = Array.isArray(result?.key_specs) ? result.key_specs : []
  return specs
    .filter((item) => item?.value && item.confidence !== 'low')
    .slice(0, 8)
    .map((item) => `${item.name || '参数'} ${item.value}`)
    .join('；')
}

function aiPackageSuggestion(result) {
  const specs = Array.isArray(result?.key_specs) ? result.key_specs : []
  const hit = specs.find((item) => String(item?.name || '').includes('封装') && item?.value && item.confidence !== 'low')
  return hit?.value || ''
}

function mergeTags(...values) {
  const seen = new Set()
  const tags = []
  for (const value of values) {
    for (const tag of splitTags(Array.isArray(value) ? value.join(',') : value)) {
      const key = normalizeToken(tag)
      if (!key || seen.has(key)) continue
      seen.add(key)
      tags.push(tag)
    }
  }
  return tags.join(', ')
}

function applyAiDraft(result, { overwrite = false } = {}) {
  const categoryId = categoryIdFromSuggestion(result.category_suggestion)
  const aiParams = aiKeySpecsToParameters(result)
  const aiPackage = aiPackageSuggestion(result)
  const prompt = quickAddPrompt.value.trim()
  const fill = (field, value) => {
    if (value === undefined || value === null || value === '') return
    if (overwrite || !String(form[field] ?? '').trim()) form[field] = value
  }
  fill('name', result.normalized_name || prompt)
  fill('model', prompt)
  fill('description', result.summary)
  fill('parameters', aiParams)
  fill('package', aiPackage)
  fill('datasheet_url', result.datasheet_url)
  if (categoryId && (overwrite || !form.category_id)) form.category_id = categoryId
  form.tags = mergeTags(form.tags, result.ai_tags)
  if (!form.source) form.source = '手动新增'
  for (const key of ['is_hand_solder_friendly', 'is_power_component', 'is_signal_component', 'is_high_current', 'is_high_voltage', 'is_common']) {
    if (typeof result[key] === 'boolean') form[key] = Boolean(result[key])
  }
  if (!form.remark && Array.isArray(result.source_notes) && result.source_notes.length) {
    form.remark = `AI 依据：${result.source_notes.slice(0, 3).join('；')}`
  }
}

async function completeFormWithAi() {
  const query = quickAddPrompt.value.trim() || [form.model, form.name, form.parameters, form.package, form.lcsc_number].filter(Boolean).join(' ')
  if (!query) return ElMessage.warning('先输入一个大概的器件信息')
  aiCreateLoading.value = true
  try {
    const result = await aiComponentInfo({
      query,
      known_specs: JSON.stringify({
        name: form.name,
        model: form.model,
        parameters: form.parameters,
        package: form.package,
        lcsc_number: form.lcsc_number
      }),
      web_search: 'auto'
    })
    aiCreateSuggestion.value = result
    applyAiDraft(result, { overwrite: !selected.value })
    trackUsage(recordUsageEvent, 'ui.components.ai_quick_create', { entry: selected.value ? 'edit-drawer' : 'create-drawer', detail: { confidence: result.confidence || '' } })
    ElMessage.success('AI 已生成草稿，请核对后保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'AI 补齐失败，请先手动填写必填项')
  } finally {
    aiCreateLoading.value = false
  }
}

function openScannedComponent(component) {
  scannerVisible.value = false
  openDetail(decorateComponent({
    ...component,
    id: component.component_id
  }))
}

function openScanner(target = null) {
  scannerTarget.value = target
  scannerVisible.value = true
}

function openScannerForSelected() {
  if (!selected.value) return
  openScanner(selected.value)
}

async function loadUsage(limit = 20) {
  if (!selected.value?.id) return
  usageLoading.value = true
  try {
    usageRecords.value = await getComponentUsageRecords(selected.value.id, { limit })
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
    inventoryLots.value = await getComponentLots(selected.value.id)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '库存批次加载失败')
  } finally {
    lotsLoading.value = false
  }
}

async function addInventoryLot(payload) {
  if (!selected.value?.id) return
  lotSaving.value = true
  try {
    await createComponentLot(selected.value.id, payload)
    const data = await getComponentAi(selected.value.id)
    selected.value = data.component
    fillForm(data.component)
    await loadLots()
    await load()
    trackUsage(recordUsageEvent, 'ui.components.lot_create', { target_type: 'component', target_id: selected.value.id, detail: { source_type: payload.source_type } })
    ElMessage.success('库存批次已新增')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '新增库存批次失败')
  } finally {
    lotSaving.value = false
  }
}

async function consumeInventoryLot(lot) {
  if (!selected.value?.id || !lot?.id || lotConsumeIds.has(lot.id)) return
  const componentId = selected.value.id
  lotConsumeIds.add(lot.id)
  try {
    const updated = await decrementComponentQuantity(componentId, { quantity: 1, lot_id: lot.id, remark: `从 ${lot.source_reference || lot.source_type || '指定批次'} 扣减` })
    groups.value = groups.value.map((group) => ({
      ...group,
      items: (group.items || []).map((item) => item.id === updated.id ? decorateComponent({ ...item, ...updated }) : item)
    }))
    if (selected.value?.id === componentId) {
      selected.value = updated
      fillForm(updated)
      inventoryLots.value = applyInventoryLotConsumption(inventoryLots.value, lot.id, 1)
    }
    inventoryChannel?.postMessage({
      type: 'quantity-updated',
      componentId: updated.id,
      quantity: updated.quantity,
      availableQuantity: updated.available_quantity,
      reservedQuantity: updated.reserved_quantity,
      status: updated.status
    })
    trackUsage(recordUsageEvent, 'ui.components.lot_consume', { target_type: 'component', target_id: componentId, detail: { lot_id: lot.id, source_type: lot.source_type } })
    ElMessage.success({ message: '已从指定批次扣减 1', grouping: true, duration: 1400 })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批次扣减失败')
  } finally {
    lotConsumeIds.delete(lot.id)
  }
}

async function deleteInventoryLot(lot) {
  if (!selected.value?.id || !lot?.id) return
  try {
    await ElMessageBox.confirm(
      `确认删除批次「${lot.source_reference || sourceLabel(lot.source_type)}」？总库存将同步减少 ${lot.initial_quantity || 0}。`,
      '删除误添加批次',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
    lotSaving.value = true
    const result = await deleteComponentLot(selected.value.id, lot.id)
    selected.value = result.component
    fillForm(result.component)
    await loadLots()
    await load()
    trackUsage(recordUsageEvent, 'ui.components.lot_delete', { target_type: 'component', target_id: selected.value.id, detail: { lot_id: lot.id, source_type: lot.source_type } })
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
  aiAskLoading.value = true
  try {
    aiAnswer.value = await askComponentAi(selected.value.id, { question })
    trackUsage(recordUsageEvent, 'ui.components.ai_ask', { target_type: 'component', target_id: selected.value.id })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'AI 问答失败')
  } finally {
    aiAskLoading.value = false
  }
}

async function refreshAi(scope) {
  if (!selected.value) return
  aiRefreshing.value = true
  try {
    await organizeComponent(selected.value.id, true)
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

async function undoAiChange() {
  if (!selected.value) return
  try {
    await ElMessageBox.confirm('撤销该元件最近一次尚未撤销的 AI 修改？', '撤销 AI 修改')
    selected.value = await undoLatestComponentAi(selected.value.id)
    fillForm(selected.value)
    ElMessage.success('最近一次 AI 修改已撤销')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.response?.data?.detail || '撤销 AI 修改失败')
  }
}

async function submitForm() {
  if (!form.name && quickAddPrompt.value.trim()) {
    form.name = quickAddPrompt.value.trim()
  }
  if (!form.name && form.model) {
    form.name = form.model
  }
  if (!form.name) {
    ElMessage.warning('请填写名称或先输入大概信息')
    return
  }
  saving.value = true
  try {
    const saved = await saveComponent(form)
    selected.value = saved
    fillForm(saved)
    editing.value = false
    await loadLots()
    ElMessage.success('已保存，AI 状态会按需更新')
    load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function removeSelectedComponent() {
  if (!selected.value?.id) return
  const target = selected.value
  try {
    await ElMessageBox.confirm(
      `确认移除「${target.name || target.model || target.warehouse_code || target.id}」？\n\n移除后它不会再出现在库存列表、搜索和标签导出里；已占用的器件 ID「${target.warehouse_code || target.id}」会永久保留，不会释放或复用。`,
      '移除元器件记录',
      {
        type: 'warning',
        confirmButtonText: '移除记录',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger'
      }
    )
    await deleteComponent(target.id)
    trackUsage(recordUsageEvent, 'ui.components.remove', {
      target_type: 'component',
      target_id: target.id,
      detail: { warehouse_code: target.warehouse_code || '' }
    })
    ElMessage.success('已移除记录，器件 ID 已保留')
    drawerVisible.value = false
    selected.value = null
    await reloadFromFirstPage()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.response?.data?.detail || '移除记录失败')
  }
}

async function quickConsume(row) {
  if (!row?.id || quickConsumeIds.has(row.id) || Number(row.available_quantity || 0) <= 0) return
  quickConsumeIds.add(row.id)
  try {
    const updated = await decrementComponentQuantity(row.id, { quantity: 1, remark: '器件卡片快捷领用 1 个' })
    groups.value = groups.value.map((group) => ({
      ...group,
      items: (group.items || []).map((item) => item.id === updated.id ? decorateComponent({ ...item, ...updated }) : item)
    }))
    if (selected.value?.id === updated.id) {
      selected.value = updated
      fillForm(updated)
    }
    inventoryChannel?.postMessage({
      type: 'quantity-updated',
      componentId: updated.id,
      quantity: updated.quantity,
      availableQuantity: updated.available_quantity,
      reservedQuantity: updated.reserved_quantity,
      status: updated.status
    })
    trackUsage(recordUsageEvent, 'ui.components.quick_consume', {
      target_type: 'component',
      target_id: updated.id,
      entry: 'inventory-card',
      detail: { quantity: 1 }
    })
    ElMessage.success(`${componentDisplayTitle(row)} 已领用 1 个，可用 ${updated.available_quantity || 0}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '领用登记失败')
  } finally {
    quickConsumeIds.delete(row.id)
  }
}

async function handleExcelUpload({ file }) {
  try {
    previewRows.value = await previewExcel(file)
    await loadImportBatches()
    previewVisible.value = true
  } catch {
    ElMessage.error('Excel 解析失败，请检查表头')
  }
}

async function handleExternalOrderUpload({ file }) {
  externalParsing.value = true
  const message = ElMessage({
    type: 'info',
    duration: 0,
    showClose: true,
    message: 'AI 正在解析外部订单表格，复杂淘宝订单可能需要 30-120 秒，请不要重复上传。'
  })
  try {
    externalPreviewRows.value = await previewExternalOrder(file)
    externalPreviewVisible.value = true
    ElMessage.success(`AI 解析完成：识别到 ${externalPreviewRows.value.length} 条可导入物料`)
  } catch (error) {
    const timedOut = error.code === 'ECONNABORTED' || String(error.message || '').includes('timeout')
    ElMessage.error(
      timedOut
        ? '外部订单 AI 解析时间较长，前端已超时。请稍后重试，或减少一次上传的订单行数。'
        : error.response?.data?.detail || '外部订单 AI 解析失败，请确认已配置 AI，或检查表格内容是否为订单明细'
    )
  } finally {
    message.close()
    externalParsing.value = false
  }
}

async function confirmExternalOrderImport() {
  importing.value = true
  try {
    const result = await commitExternalOrder(externalPreviewRows.value)
    ElMessage.success(`外部订单导入：新增 ${result.created}，合并 ${result.merged}，跳过 ${result.skipped}`)
    externalPreviewVisible.value = false
    drawerVisible.value = false
    editing.value = false
    load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '外部订单导入失败')
  } finally {
    importing.value = false
  }
}

function importActionLabel(row) {
  if (row.already_imported) return '已导入，跳过'
  if (row.duplicate) return '自动合并'
  return '自动新增'
}

function importActionType(row) {
  if (row.already_imported) return 'info'
  if (row.duplicate) return 'warning'
  return 'success'
}

async function loadImportBatches() {
  try {
    importBatches.value = await getOrderImportBatches({ limit: 10 })
  } catch {
    importBatches.value = []
  }
}

async function rollbackImportBatch(batch) {
  await ElMessageBox.confirm(`撤销导入批次 #${batch.id}？本次新增会清零标记，合并库存会还原到导入前。`, '撤销导入', {
    type: 'warning',
    confirmButtonText: '撤销',
    cancelButtonText: '取消'
  })
  const result = await rollbackOrderImportBatch(batch.id)
  ElMessage.success(result.rollback_summary || '已撤销导入批次')
  await loadImportBatches()
  await load()
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
    drawerVisible.value = false
    editing.value = false
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
    ElMessage.success(`新增 ${result.created}，合并 ${result.merged}，跳过 ${result.skipped}，抵消待采购 ${result.resolved_pending_purchase || 0}`)
    previewVisible.value = false
    drawerVisible.value = false
    editing.value = false
    await loadImportBatches()
    load()
  } catch {
    ElMessage.error('导入失败')
  } finally {
    importing.value = false
  }
}

onMounted(async () => {
  if (route.query.component) {
    autoOpenComponentCode = String(route.query.component)
    filters.keyword = autoOpenComponentCode
  } else if (route.query.keyword) filters.keyword = String(route.query.keyword)
  await Promise.all([loadCategories(), loadImportBatches(), loadCustomLabels()])
  await load()
  await nextTick()
  setupAutoLoadObserver()
  if (inventoryChannel) {
    inventoryChannel.onmessage = (event) => {
      if (event.data?.type !== 'quantity-updated') return
      const componentId = Number(event.data.componentId)
      if (!componentId || event.data.quantity === undefined) return
      const quantityPatch = {
        quantity: Number(event.data.quantity || 0),
        available_quantity: Number(event.data.availableQuantity || 0),
        reserved_quantity: Number(event.data.reservedQuantity || 0),
        status: event.data.status
      }
      groups.value = groups.value.map((group) => ({
        ...group,
        items: (group.items || []).map((item) => item.id === componentId ? decorateComponent({ ...item, ...quantityPatch }) : item)
      }))
      if (selected.value?.id === componentId) {
        selected.value = { ...selected.value, ...quantityPatch }
        fillForm(selected.value)
        getComponentLots(componentId).then((lots) => {
          if (selected.value?.id === componentId) inventoryLots.value = lots || []
        }).catch(() => {})
      }
    }
  }
})

onBeforeUnmount(() => {
  inventoryChannel?.close()
  stopAutoLoadObserver()
})

watch(
  () => [route.query.keyword, route.query.component],
  async ([keyword, component]) => {
    if (component !== undefined) {
      autoOpenComponentCode = String(component || '')
      filters.keyword = autoOpenComponentCode
      await reloadFromFirstPage()
      return
    }
    if (keyword === undefined) return
    autoOpenComponentCode = ''
    filters.keyword = String(keyword || '')
    await reloadFromFirstPage()
  }
)

watch(
  () => [drawerVisible.value, selected.value?.id || 'create'],
  ([visible]) => {
    if (visible) resetDetailDrawerScroll()
  }
)

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
</script>

<style scoped>
.page {
  --component-radius: 16px;
  --component-section-radius: 16px;
}

.page-header {
  padding: 4px 2px;
}

.filter-panel {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 140px 140px 140px 120px auto auto;
  gap: 10px;
  align-items: center;
  border-color: var(--cw-border);
  border-radius: var(--cw-radius-card);
  background: #fff;
  box-shadow: none;
}

.filter-panel :deep(.el-input__wrapper),
.filter-panel :deep(.el-select__wrapper),
.filter-panel :deep(.el-segmented),
.filter-panel :deep(.el-button) {
  border-radius: var(--cw-radius-control);
}

.toolbar :deep(.el-button) {
  border-radius: var(--cw-radius-control);
  box-shadow: none;
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
  gap: 7px;
}

:global(.cw-more-popover .more-action-list .el-button),
:global(.cw-more-popover .more-action-list .el-upload),
:global(.cw-more-popover .more-action-list .el-upload .el-button) {
  width: 100%;
  margin-left: 0;
  border-radius: var(--cw-radius-control);
}

.category-stack {
  display: grid;
  gap: 14px;
}

.component-skeleton-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.component-skeleton {
  width: 100%;
  height: 280px;
  border-radius: var(--cw-radius-card);
}

.load-more {
  justify-self: center;
  min-width: 180px;
}

.auto-load-sentinel {
  min-height: 44px;
  display: grid;
  place-items: center;
  color: var(--cw-muted);
  font-size: 13px;
}

.category-block {
  padding: 10px;
  border-radius: var(--component-section-radius);
  border: 1px solid var(--cw-border);
  background: #fff;
  box-shadow: none;
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
  border-radius: var(--cw-radius-chip);
}

.component-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(370px, 1fr));
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
  background: #fff;
  cursor: pointer;
}

.component-card:hover {
  border-color: #bfd1ff;
  background: #fbfdff;
}

.card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.card-id-stack {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
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

.small-text {
  display: block;
  margin-top: 4px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
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
  border-radius: var(--cw-radius-chip);
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
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: -4px;
}

.card-links :deep(.el-button) {
  width: 100%;
  min-width: 0;
  margin-left: 0;
  padding: 7px 6px;
  border-color: #d8e1ef;
  border-radius: var(--cw-radius-control);
}

.card-links :deep(.el-button > span) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  background: #fff;
  box-shadow: none;
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
  border-radius: var(--cw-radius-chip);
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

.quick-create-card {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid #bfdbfe;
  border-radius: var(--cw-radius-card);
  background: linear-gradient(135deg, #eff6ff, #ffffff 70%);
}

.quick-create-card strong {
  color: #0f172a;
  font-size: 16px;
}

.quick-create-card p,
.required-hint,
.ai-draft-summary {
  margin: 4px 0 0;
  color: var(--cw-muted);
  line-height: 1.55;
}

.quick-create-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.ai-confidence {
  color: #2563eb;
  font-size: 13px;
  font-weight: 700;
}

.ai-draft-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding-top: 2px;
}

.ai-draft-summary small {
  padding: 3px 8px;
  border: 1px solid #fed7aa;
  border-radius: var(--cw-radius-chip);
  color: #c2410c;
  background: #fff7ed;
}

.required-hint {
  margin-bottom: 12px;
  font-size: 13px;
}

.required-hint span {
  color: #dc2626;
  font-weight: 800;
}

.edit-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px 12px;
}

.edit-form-grid .wide-field {
  grid-column: 1 / -1;
}

.flag-checks :deep(.el-form-item__content) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
}

.flag-checks :deep(.el-checkbox) {
  margin-right: 0;
}

.drawer-save-bar {
  position: sticky;
  bottom: 0;
  z-index: 2;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin: 14px -4px -4px;
  padding: 12px 4px 4px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0), #fff 32%);
}

.drawer-save-bar .el-button {
  margin-left: 0;
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
  border-radius: var(--cw-radius-control);
  background: #f8fafc;
  color: #344054;
}

.import-alert {
  margin-bottom: 12px;
}

.import-history {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #eef2f7;
}

.import-history-head,
.import-batch-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.import-batch-list {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}

.import-batch-card {
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: var(--cw-radius-card);
  background: #f8fafc;
}

.import-batch-card p {
  margin: 4px 0 0;
  color: var(--cw-muted);
}

:deep(.el-drawer__body) {
  overflow-x: hidden;
}

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

@media (max-width: 980px) {
  .component-skeleton-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .filter-panel {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 620px) {
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

  .component-skeleton-grid {
    grid-template-columns: 1fr;
  }
  .filter-panel {
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .filter-panel > :first-child,
  .filter-panel > :last-child {
    grid-column: 1 / -1;
  }

  .filter-panel > *,
  .compact-toolbar > * {
    width: 100%;
  }

  .compact-toolbar {
    grid-template-columns: 1fr 1fr;
    display: grid;
    width: 100%;
  }

  .compact-toolbar > :first-child {
    grid-column: 1 / -1;
  }

  .compact-toolbar :deep(.el-button),
  .compact-toolbar :deep(.el-upload) {
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

  .edit-form {
    --el-form-label-font-size: 13px;
  }

  .edit-form :deep(.el-form-item) {
    margin-bottom: 12px;
  }

  .edit-form :deep(.el-form-item__label) {
    margin-bottom: 4px;
  }

  .edit-form-grid {
    grid-template-columns: 1fr;
  }

  .quick-create-card {
    padding: 12px;
  }

  .quick-create-actions,
  .drawer-save-bar {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .quick-create-actions .el-button,
  .drawer-save-bar .el-button {
    width: 100%;
  }
}

@media (max-width: 420px) {
  .drawer-actions {
    grid-template-columns: 1fr;
  }
}
</style>
