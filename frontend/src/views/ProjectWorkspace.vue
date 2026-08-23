<template>
  <section class="project-v2" aria-labelledby="project-page-title">
    <div v-if="loading && !initialized" class="workspace-loader" role="status" aria-live="polite">
      <span class="workspace-loader__mark" aria-hidden="true" />
      <strong>正在加载项目工作区</strong>
      <small>读取项目摘要、版本与成本数据</small>
    </div>

    <template v-else-if="!selectedProject">
      <header class="page-hero material-surface">
        <div class="hero-copy">
          <span class="eyebrow">PROJECT CONTROL</span>
          <h1 id="project-page-title">项目控制台</h1>
          <p>一个入口管理项目阶段、PCB 迭代、装配进度与实际成本。</p>
        </div>
        <div class="hero-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadDashboard">刷新</el-button>
          <el-button type="primary" :icon="Plus" @click="openCreate">新建项目</el-button>
        </div>
      </header>

      <div class="metric-grid" aria-label="项目摘要">
        <article v-for="metric in metricCards" :key="metric.label" class="metric-card material-surface" :class="metric.tone">
          <span class="metric-icon"><component :is="metric.icon" /></span>
          <div class="metric-copy">
            <small>{{ metric.label }}</small>
            <strong :title="metric.value">{{ metric.value }}</strong>
            <p>{{ metric.note }}</p>
          </div>
        </article>
      </div>

      <section class="insight-grid" aria-label="项目数据图表">
        <article class="insight-card material-surface">
          <div class="section-heading">
            <div><span class="section-kicker">FLOW</span><h2>状态分布</h2></div>
            <small>{{ totalStatusProjects }} 个项目</small>
          </div>
          <div v-if="bootstrap.status_distribution.length" class="status-bars">
            <button
              v-for="item in bootstrap.status_distribution"
              :key="item.status"
              type="button"
              class="status-bar-row"
              :title="`${item.label}：${item.count} 个`"
              @click="setStatusFilter(item.status)"
            >
              <span class="bar-label">{{ item.label }}</span>
              <span class="bar-track"><i :style="{ width: `${statusPercent(item.count)}%` }" /></span>
              <strong>{{ item.count }}</strong>
            </button>
          </div>
          <div v-else class="chart-empty">新项目创建后会显示阶段分布</div>
        </article>

        <article class="insight-card material-surface trend-card">
          <div class="section-heading">
            <div><span class="section-kicker">COST</span><h2>周成本趋势</h2></div>
            <small>最近 {{ bootstrap.weekly_cost.length || 0 }} 周</small>
          </div>
          <div v-if="bootstrap.weekly_cost.length" class="line-chart" aria-label="周成本趋势折线图">
            <svg viewBox="0 0 360 132" role="img" aria-label="每周综合成本">
              <line v-for="y in [24, 64, 104]" :key="y" x1="18" :y1="y" x2="344" :y2="y" class="grid-line" />
              <polyline :points="trendPoints" class="trend-line" fill="none" />
              <circle v-for="point in trendDots" :key="point.key" :cx="point.x" :cy="point.y" r="4" class="trend-dot">
                <title>{{ point.key }}：{{ money(point.amount) }}</title>
              </circle>
            </svg>
            <div class="chart-axis"><span>{{ bootstrap.weekly_cost[0]?.week }}</span><span>{{ bootstrap.weekly_cost.at(-1)?.week }}</span></div>
          </div>
          <div v-else class="chart-empty">录入费用或完成焊接后显示成本趋势</div>
        </article>

        <article class="insight-card material-surface">
          <div class="section-heading">
            <div><span class="section-kicker">MIX</span><h2>直接费用构成</h2></div>
            <small>人民币</small>
          </div>
          <div v-if="bootstrap.expense_breakdown.length" class="cost-ranks">
            <div v-for="item in bootstrap.expense_breakdown.slice(0, 6)" :key="item.category" class="cost-rank">
              <div><span :title="item.label">{{ item.label }}</span><strong>{{ money(item.amount) }}</strong></div>
              <span class="rank-track"><i :style="{ width: `${expensePercent(item.amount)}%` }" /></span>
            </div>
          </div>
          <div v-else class="chart-empty">费用台账为空，不会把采购计划重复计入成本</div>
        </article>
      </section>

      <section class="project-list material-surface">
        <div class="list-toolbar">
          <div class="section-heading list-title">
            <div><span class="section-kicker">PORTFOLIO</span><h2>全部项目</h2></div>
            <small>{{ bootstrap.projects.length }} 条</small>
          </div>
          <div class="filters">
            <el-input v-model="filters.search" clearable :prefix-icon="Search" placeholder="搜索编号或名称" @keyup.enter="loadDashboard" />
            <el-select v-model="filters.status" clearable placeholder="全部状态" @change="loadDashboard">
              <el-option v-for="item in options.project_statuses" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-checkbox v-model="filters.include_archived" @change="loadDashboard">显示归档</el-checkbox>
            <el-button @click="loadDashboard">筛选</el-button>
          </div>
        </div>

        <div v-if="bootstrap.projects.length" class="project-table" role="table" aria-label="项目列表">
          <div class="project-row project-row--head" role="row">
            <span role="columnheader">项目</span><span role="columnheader">状态</span><span role="columnheader">当前版本</span>
            <span role="columnheader">周期</span><span role="columnheader">装配</span><span role="columnheader">综合成本</span><span role="columnheader">更新</span>
          </div>
          <button v-for="project in bootstrap.projects" :key="project.id" class="project-row" type="button" role="row" @click="openProject(project)">
            <span class="project-identity" role="cell"><strong :title="project.name">{{ project.name }}</strong><small :title="project.project_code">{{ project.project_code }}</small></span>
            <span role="cell"><i class="status-chip" :data-status="project.status">{{ project.status_label }}</i></span>
            <span role="cell"><strong>{{ project.current_version?.version_code || 'V1' }}</strong><small>{{ project.current_version?.status_label || '设计中' }}</small></span>
            <span role="cell"><strong :title="`${project.period.current_week}（${shortMonthDay(project.period.end_date || localDate())}）`">{{ project.period.current_week }}（{{ shortMonthDay(project.period.end_date || localDate()) }}）</strong><small>{{ project.period.actual_days }} 天 · {{ project.period.actual_weeks }} 周</small></span>
            <span role="cell"><strong>{{ project.current_version?.solder_progress || 0 }}%</strong><small>{{ project.current_version?.soldered_count || 0 }} / {{ project.current_version?.solder_total || 0 }} 焊点</small></span>
            <span role="cell" class="cost-cell"><strong>{{ money(project.cost.comprehensive_cost) }}</strong><small v-if="project.cost.unpriced_count" class="warning-text">{{ project.cost.unpriced_count }} 项未计价</small><small v-else>已计价</small></span>
            <span role="cell"><strong>{{ shortDate(project.updated_at) }}</strong><small>打开工作区 →</small></span>
          </button>
        </div>
        <div v-else class="project-empty">
          <span class="empty-mark"><FolderOpened /></span>
          <h3>{{ filters.search || filters.status ? '没有匹配的项目' : '项目工作区已准备好' }}</h3>
          <p>{{ filters.search || filters.status ? '调整筛选条件后重试。' : '旧项目已清理。新建项目时可先不上传 BOM。' }}</p>
          <el-button v-if="!filters.search && !filters.status" type="primary" :icon="Plus" @click="openCreate">建立第一个项目</el-button>
        </div>
      </section>
    </template>

    <template v-else>
      <header class="workspace-head material-surface">
        <button type="button" class="back-button" @click="closeProject"><ArrowLeft />返回项目总览</button>
        <div class="workspace-title">
          <div class="workspace-title__copy">
            <span class="stable-code">{{ selectedProject.project_code }}</span>
            <h1 :title="selectedProject.name">{{ selectedProject.name }}</h1>
            <p :title="selectedProject.description || '暂无项目描述'">{{ selectedProject.description || '暂无项目描述' }}</p>
          </div>
          <div class="workspace-actions">
            <el-select v-model="statusDraft" aria-label="项目状态" @change="saveStatus">
              <el-option v-for="item in options.project_statuses" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-button :icon="Refresh" :loading="workspaceLoading" @click="refreshProject">刷新</el-button>
            <el-dropdown trigger="click" @command="handleProjectCommand">
              <el-button :icon="MoreFilled">更多</el-button>
              <template #dropdown><el-dropdown-menu><el-dropdown-item command="archive">归档项目</el-dropdown-item></el-dropdown-menu></template>
            </el-dropdown>
          </div>
        </div>
      </header>

      <nav class="workspace-tabs material-surface" aria-label="项目工作区">
        <button v-for="tab in tabs" :key="tab.value" type="button" :class="{ active: activeTab === tab.value }" @click="activeTab = tab.value">
          <component :is="tab.icon" /><span>{{ tab.label }}</span><small>{{ tab.note }}</small>
        </button>
      </nav>

      <div v-if="workspaceLoading" class="workspace-inline-loading"><span class="workspace-loader__mark" />正在更新项目数据</div>

      <template v-if="activeTab === 'overview'">
        <div class="fact-grid">
          <article class="fact-card material-surface"><small>项目状态</small><strong>{{ selectedProject.status_label }}</strong><span>{{ selectedProject.period.current_week }}</span></article>
          <article class="fact-card material-surface"><small>当前 PCB</small><strong>{{ selectedProject.current_version?.version_code || 'V1' }}</strong><span>{{ selectedProject.current_version?.status_label || '设计中' }}</span></article>
          <article class="fact-card material-surface"><small>项目周期</small><strong>{{ selectedProject.period.actual_days }} 天</strong><span :title="periodWeekRange">{{ periodWeekRange }}</span></article>
          <article class="fact-card material-surface"><small>综合实际成本</small><strong>{{ money(selectedProject.cost.comprehensive_cost) }}</strong><span>{{ selectedProject.cost.unpriced_count }} 项未计价</span></article>
        </div>
        <section class="lifecycle-panel material-surface" aria-labelledby="lifecycle-title">
          <div class="panel-head lifecycle-head">
            <div>
              <span class="section-kicker">LIFECYCLE</span>
              <h2 id="lifecycle-title">项目时间线</h2>
              <p>从立项日到当前阶段按真实时间推进；未来节点保持待开始。</p>
            </div>
            <span v-if="selectedProject.lifecycle?.side_state" class="lifecycle-side-state">
              当前{{ selectedProject.lifecycle.current_label }}，主流程节点保持不变
            </span>
            <small v-else>{{ selectedProject.period.start_date }} 至今 · {{ selectedProject.period.actual_days }} 天</small>
          </div>
          <div class="lifecycle-scroll" tabindex="0" aria-label="项目生命周期节点">
            <ol class="lifecycle-track">
              <li v-for="node in lifecycleNodes" :key="node.status" :data-state="node.state">
                <span class="lifecycle-marker"><b>{{ node.position }}</b></span>
                <div class="lifecycle-node-copy">
                  <strong :title="node.label">{{ node.label }}</strong>
                  <time v-if="node.occurred_at" :datetime="node.occurred_at">{{ lifecycleRange(node) }}</time>
                  <span v-else>尚未开始</span>
                  <small>{{ lifecycleWeekRange(node) }}<template v-if="node.occurred_at"> · </template>{{ nodeStateLabel(node.state) }}</small>
                </div>
              </li>
            </ol>
          </div>
        </section>
        <div class="workspace-columns">
          <section class="content-panel material-surface">
            <div class="panel-head"><div><span class="section-kicker">PROFILE</span><h2>项目信息</h2></div><el-button type="primary" :loading="saving" @click="saveInfo">保存信息</el-button></div>
            <el-form label-position="top" class="project-form">
              <div class="form-grid">
                <el-form-item label="项目编号"><el-input :model-value="selectedProject.project_code" disabled /><small class="field-help">稳定编号不可修改，避免链接和引用失效。</small></el-form-item>
                <el-form-item label="项目名称"><el-input v-model="infoForm.name" maxlength="200" show-word-limit /></el-form-item>
                <el-form-item label="开始日期"><div class="date-week-field"><el-date-picker v-model="infoForm.start_date" type="date" value-format="YYYY-MM-DD" /><span>{{ weekBadge(infoForm.start_date) }}</span></div></el-form-item>
                <el-form-item label="结束日期"><div class="date-week-field"><el-date-picker v-model="infoForm.end_date" type="date" value-format="YYYY-MM-DD" clearable /><span :class="{ empty: !infoForm.end_date }">{{ weekBadge(infoForm.end_date) }}</span></div></el-form-item>
              </div>
              <el-form-item label="项目描述（可选）"><el-input v-model="infoForm.description" type="textarea" :rows="5" maxlength="5000" show-word-limit /></el-form-item>
            </el-form>
          </section>
          <section class="content-panel material-surface">
            <div class="panel-head"><div><span class="section-kicker">AUDIT LOG</span><h2>变更记录</h2><p>保留每次状态操作的来源与精确时间。</p></div><small>{{ selectedProject.status_history?.length || 0 }} 条</small></div>
            <ol class="timeline-list">
              <li v-for="event in selectedProject.status_history" :key="event.id"><i /><div><strong>{{ event.to_label }}</strong><p>{{ event.note || '手工更新项目阶段' }}</p><small>{{ eventDateTime(event) }} · {{ sourceLabel(event.source) }}</small></div></li>
              <li v-if="!selectedProject.status_history?.length" class="timeline-empty">暂无状态记录</li>
            </ol>
          </section>
        </div>
      </template>

      <template v-else-if="activeTab === 'versions'">
        <section class="content-panel material-surface">
          <div class="panel-head"><div><span class="section-kicker">REVISION</span><h2>PCB 版本链</h2><p>新版只复制上一版 BOM，不复制实物板和成本流水。</p></div><el-button type="primary" :icon="Plus" @click="versionDialog = true">建立新版</el-button></div>
          <div class="version-grid">
            <article v-for="version in selectedProject.versions" :key="version.id" class="version-card" :class="{ current: version.id === selectedProject.current_version?.id }">
              <div class="version-top"><span>{{ version.version_code }}</span><i class="status-chip">{{ version.status_label }}</i></div>
              <p>{{ version.change_summary || '初始版本' }}</p>
              <div class="version-stats"><span><strong>{{ version.bom_item_count }}</strong>BOM</span><span><strong>{{ version.board_count }}</strong>块板</span><span><strong>{{ version.solder_progress }}%</strong>装配</span></div>
              <div class="version-actions"><el-select :model-value="version.status" @change="value => saveVersionStatus(version, value)"><el-option v-for="item in options.version_statuses" :key="item.value" :label="item.label" :value="item.value" /></el-select><el-button @click="selectVersion(version)">查看版本</el-button></div>
            </article>
          </div>
        </section>
      </template>

      <template v-else-if="activeTab === 'assembly'">
        <section class="content-panel material-surface assembly-panel">
          <div class="panel-head assembly-head">
            <div><span class="section-kicker">BUILD</span><h2>BOM 与装配</h2><p>按版本维护单板 BOM；每块实物板独立记录焊接与报损。</p></div>
            <div class="panel-actions">
              <el-select v-model="selectedVersionId" @change="loadVersionWorkspace"><el-option v-for="item in selectedProject.versions" :key="item.id" :label="item.version_code" :value="item.id" /></el-select>
              <el-upload :show-file-list="false" accept=".csv,.xlsx,.xlsm" :http-request="handleBomImport"><el-button :loading="uploading">导入 BOM</el-button></el-upload>
              <el-button :icon="Plus" @click="bomDialog = true">添加物料</el-button>
              <el-button type="primary" :icon="Plus" @click="createBoard">新增实物板</el-button>
            </div>
          </div>
          <div class="assembly-layout">
            <div class="bom-section">
              <div class="subhead"><h3>版本 BOM</h3><small>{{ versionWorkspace.bom.length }} 种物料 · 单板估算 {{ money(versionWorkspace.cost.bom_estimate) }}</small></div>
              <div v-if="versionWorkspace.bom.length" class="bom-table">
                <div class="bom-row bom-row--head"><span>器件</span><span>单板数量</span><span>位号</span><span>库存</span><span>估算</span><span /></div>
                <div v-for="item in versionWorkspace.bom" :key="item.id" class="bom-row">
                  <span class="bom-name"><strong :title="item.name">{{ item.name }}</strong><small :title="[item.warehouse_code, item.model, item.package].filter(Boolean).join(' · ')">{{ [item.warehouse_code, item.model, item.package].filter(Boolean).join(' · ') }}</small></span>
                  <span><strong>{{ item.quantity_per_board }}</strong></span>
                  <span class="ref-list" :title="item.designators.join(', ')">{{ item.designators.join(', ') }}</span>
                  <span :class="{ 'warning-text': item.inventory_quantity < item.quantity_per_board }">{{ item.inventory_quantity }}</span>
                  <span><strong>{{ item.unpriced ? '未计价' : money(item.estimated_cost) }}</strong></span>
                  <span><el-button link type="danger" @click="removeBom(item)">删除</el-button></span>
                </div>
              </div>
              <div v-else class="inline-empty">当前版本尚未添加 BOM，可稍后手工添加或导入。</div>
            </div>
            <div class="board-section">
              <div class="subhead"><h3>实物板</h3><small>{{ versionWorkspace.boards.length }} 块</small></div>
              <div v-if="versionWorkspace.boards.length" class="board-list">
                <article v-for="board in versionWorkspace.boards" :key="board.id" class="board-card">
                  <button type="button" class="board-summary" @click="toggleBoard(board.id)"><span><strong>{{ board.name }}</strong><small>{{ board.status_label }} · {{ board.soldered_count }}/{{ board.point_count }} 焊点</small></span><b>{{ board.progress }}%</b></button>
                  <div class="progress-track"><i :style="{ width: `${board.progress}%` }" /></div>
                  <div v-if="expandedBoards.has(board.id)" class="point-grid">
                    <div v-for="point in board.points" :key="point.id" class="point-row">
                      <span><strong>{{ point.designator }}</strong><small :title="point.component_name">{{ point.component_name }}</small></span>
                      <i class="point-state" :data-state="point.state">{{ pointStateLabel(point.state) }}</i>
                      <div class="point-actions">
                        <el-button v-if="point.state === 'pending'" size="small" type="primary" @click="runPointAction(board, point, 'solder')">焊接</el-button>
                        <el-button v-if="point.state === 'soldered'" size="small" @click="runPointAction(board, point, 'unsolder')">取消</el-button>
                        <el-button v-if="point.state === 'pending'" size="small" type="danger" plain @click="runPointAction(board, point, 'loss')">报损</el-button>
                        <el-button v-if="point.state === 'lost'" size="small" @click="runPointAction(board, point, 'undo_loss')">撤销报损</el-button>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <div v-else class="inline-empty">建立实物板后，系统会按当前版本 BOM 生成焊点。</div>
            </div>
          </div>
          <div class="fabrication-workspace">
            <AssemblyWorkbench
              v-if="selectedProject?.id && selectedVersionId"
              :key="`${selectedProject.id}:${selectedVersionId}`"
              :project-id="selectedProject.id"
              :workspace-version-id="selectedVersionId"
              compact
              @changed="handleFabricationChanged"
            />
          </div>
        </section>
      </template>

      <template v-else-if="activeTab === 'cost'">
        <div class="cost-metrics">
          <article class="fact-card material-surface"><small>单板 BOM 估算</small><strong>{{ money(selectedProject.cost.bom_estimate) }}</strong><span>按当前均价</span></article>
          <article class="fact-card material-surface"><small>实际材料耗用</small><strong>{{ money(selectedProject.cost.actual_material_cost) }}</strong><span>焊接与报损净额</span></article>
          <article class="fact-card material-surface"><small>直接费用</small><strong>{{ money(selectedProject.cost.direct_expense) }}</strong><span>有效费用台账</span></article>
          <article class="fact-card material-surface"><small>综合实际成本</small><strong>{{ money(selectedProject.cost.comprehensive_cost) }}</strong><span>不含采购计划</span></article>
        </div>
        <section class="content-panel material-surface">
          <div class="panel-head"><div><span class="section-kicker">LEDGER</span><h2>费用台账</h2><p>PCB、装配、运费、结构件和工装统一使用人民币记录。</p></div><div class="panel-actions"><el-button v-if="selectedProject.cost.unpriced_count" @click="fillUnpriced">补齐未计价</el-button><el-button type="primary" :icon="Plus" @click="expenseDialog = true">记录费用</el-button></div></div>
          <div v-if="selectedProject.expenses?.length" class="ledger-list">
            <article v-for="expense in selectedProject.expenses" :key="expense.id"><span class="ledger-date">{{ expense.occurred_on }}</span><div><strong>{{ expense.category_label }}</strong><p>{{ [expense.vendor, expense.note].filter(Boolean).join(' · ') || '无补充说明' }}</p></div><b>{{ money(expense.amount) }}</b><el-button link type="danger" @click="archiveExpense(expense)">归档</el-button></article>
          </div>
          <div v-else class="inline-empty">暂无直接费用，材料焊接成本仍会独立统计。</div>
        </section>
      </template>

      <template v-else>
        <div class="workspace-columns">
          <section class="content-panel material-surface">
            <div class="panel-head"><div><span class="section-kicker">FILES</span><h2>工程文件</h2><p>单文件最大 20 MB，可关联当前 PCB 版本。</p></div><el-upload :show-file-list="false" :http-request="handleProjectFile"><el-button type="primary" :icon="Upload">上传文件</el-button></el-upload></div>
            <div v-if="selectedProject.files?.length" class="file-list"><button v-for="file in selectedProject.files" :key="file.id" type="button" @click="downloadFile(file)"><span><strong :title="file.name">{{ file.name }}</strong><small>{{ file.mime_type }} · {{ fileSize(file.size_bytes) }}</small></span><Download /></button></div>
            <div v-else class="inline-empty">暂无工程文件。</div>
          </section>
          <section class="content-panel material-surface">
            <div class="panel-head"><div><span class="section-kicker">RISKS</span><h2>风险与待办</h2><p>只记录需要你后续处理的问题。</p></div><el-button type="primary" :icon="Plus" @click="riskDialog = true">添加风险</el-button></div>
            <div v-if="selectedProject.risks?.length" class="risk-list"><article v-for="risk in selectedProject.risks" :key="risk.id" :class="risk.severity"><i>{{ risk.severity_label }}</i><div><strong :title="risk.title">{{ risk.title }}</strong><p>{{ risk.detail || '无补充说明' }}</p></div><el-button v-if="risk.status === 'open'" size="small" @click="resolveRisk(risk)">标记已解决</el-button><span v-else class="resolved">已解决</span></article></div>
            <div v-else class="inline-empty">当前没有未记录的项目风险。</div>
          </section>
        </div>
      </template>
    </template>

    <el-dialog v-model="createDialog" title="新建项目" width="620px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="项目编号"><el-input v-model="createForm.project_code" placeholder="例如 WXY-HP26-HCB" maxlength="80" /><small class="field-help">保存时自动转为大写，建立后不可修改。</small></el-form-item>
        <el-form-item label="项目名称"><el-input v-model="createForm.name" maxlength="200" /></el-form-item>
        <div class="dialog-grid">
          <el-form-item label="实际立项日期"><div class="date-week-field"><el-date-picker v-model="createForm.start_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /><span>{{ weekBadge(createForm.start_date) }}</span></div></el-form-item>
          <el-form-item label="创建时所在阶段"><el-select v-model="createForm.status"><el-option v-for="item in options.project_statuses" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
        </div>
        <p class="timeline-create-help">如果项目已经推进，请逐个填写已到达节点的真实日期。系统不会把自动估算时间写成实际记录。</p>
        <div v-if="createReachedStages.length > 1" class="create-timeline-editor" aria-label="已到达节点日期">
          <el-form-item v-for="stage in createReachedStages" :key="stage.status" :label="stage.status === 'planning' ? '方案规划（立项）' : `进入${stage.label}`">
            <div class="date-week-field">
              <el-date-picker
                v-model="createTimelineDates[stage.status]"
                type="date"
                value-format="YYYY-MM-DD"
                :disabled="stage.status === 'planning'"
                :disabled-date="disableFutureDate"
                placeholder="选择实际日期"
              />
              <span :class="{ empty: !createTimelineDates[stage.status] }">{{ weekBadge(createTimelineDates[stage.status]) }}</span>
            </div>
          </el-form-item>
        </div>
        <el-form-item label="项目描述（可选）"><el-input v-model="createForm.description" type="textarea" :rows="4" maxlength="5000" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="createDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="createProject">创建项目</el-button></template>
    </el-dialog>

    <el-dialog v-model="versionDialog" title="建立 PCB 新版本" width="560px" destroy-on-close>
      <el-form label-position="top"><el-form-item label="版本号"><el-input v-model="versionForm.version_code" :placeholder="nextVersionCode" /></el-form-item><el-form-item label="变更说明"><el-input v-model="versionForm.change_summary" type="textarea" :rows="5" maxlength="3000" show-word-limit /><small class="field-help">V2 及后续版本必填；只复制上一版 BOM。</small></el-form-item></el-form>
      <template #footer><el-button @click="versionDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="createVersion">建立版本</el-button></template>
    </el-dialog>

    <el-dialog v-model="bomDialog" title="添加 BOM 物料" width="600px" destroy-on-close>
      <el-form label-position="top"><el-form-item label="库存元器件"><el-select v-model="bomForm.component_id" filterable remote reserve-keyword :remote-method="searchComponents" :loading="componentLoading" placeholder="输入仓库编号、名称或型号"><el-option v-for="item in componentOptions" :key="item.id" :label="`${item.warehouse_code || '未编号'} · ${item.name}${item.model ? ` · ${item.model}` : ''}`" :value="item.id" /></el-select></el-form-item><el-form-item label="单板数量"><el-input-number v-model="bomForm.quantity_per_board" :min="1" :max="10000" /></el-form-item><el-form-item label="位号"><el-input v-model="bomForm.designators" placeholder="例如 R1, R2, R3；不足时自动补位" /></el-form-item><el-form-item label="备注（可选）"><el-input v-model="bomForm.note" type="textarea" :rows="3" /></el-form-item></el-form>
      <template #footer><el-button @click="bomDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="addBom">添加物料</el-button></template>
    </el-dialog>

    <el-dialog v-model="expenseDialog" title="记录项目费用" width="560px" destroy-on-close>
      <el-form label-position="top"><div class="dialog-grid"><el-form-item label="费用分类"><el-select v-model="expenseForm.category"><el-option v-for="item in options.expense_categories" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item><el-form-item label="金额（CNY）"><el-input-number v-model="expenseForm.amount" :min="0.01" :precision="2" /></el-form-item><el-form-item label="发生日期"><el-date-picker v-model="expenseForm.occurred_on" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="关联版本（可选）"><el-select v-model="expenseForm.version_id" clearable><el-option v-for="item in selectedProject?.versions || []" :key="item.id" :label="item.version_code" :value="item.id" /></el-select></el-form-item></div><el-form-item label="商家（可选）"><el-input v-model="expenseForm.vendor" /></el-form-item><el-form-item label="备注（可选）"><el-input v-model="expenseForm.note" type="textarea" :rows="3" /></el-form-item></el-form>
      <template #footer><el-button @click="expenseDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="createExpense">保存费用</el-button></template>
    </el-dialog>

    <el-dialog v-model="riskDialog" title="添加项目风险" width="560px" destroy-on-close>
      <el-form label-position="top"><el-form-item label="风险等级"><el-segmented v-model="riskForm.severity" :options="riskSegmentOptions" /></el-form-item><el-form-item label="风险标题"><el-input v-model="riskForm.title" maxlength="240" /></el-form-item><el-form-item label="详细说明（可选）"><el-input v-model="riskForm.detail" type="textarea" :rows="5" maxlength="5000" /></el-form-item></el-form>
      <template #footer><el-button @click="riskDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="createRisk">保存风险</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Coin, DataAnalysis, Download, Files, FolderOpened, MoreFilled, Plus,
  Refresh, Search, TrendCharts, Upload, WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from '../shared/elementApi'
import AssemblyWorkbench from '../shared/components/AssemblyWorkbench.vue'
import { isoWeekLabel, shortMonthDay, weekBadge } from '../shared/projectDates'
import {
  addWorkspaceBomItem, addWorkspaceExpense, addWorkspaceRisk, archiveWorkspaceExpense,
  archiveWorkspaceProject, changeWorkspaceProjectStatus, changeWorkspaceSolderPoint,
  createWorkspaceBoard, createWorkspaceProject, createWorkspaceVersion, deleteWorkspaceBomItem,
  downloadWorkspaceFile, fillWorkspaceUnpriced, getProjectWorkspaceBootstrap, getWorkspaceProject,
  getWorkspaceVersion, importWorkspaceBom, searchWorkspaceComponents, updateWorkspaceProject,
  updateWorkspaceRisk, updateWorkspaceVersion, uploadWorkspaceFile,
} from '../api/client'

const emptyBootstrap = () => ({ metrics: {}, status_distribution: [], weekly_cost: [], expense_breakdown: [], projects: [], options: {} })
const route = useRoute()
const router = useRouter()
const bootstrap = reactive(emptyBootstrap())
const options = reactive({ project_statuses: [], version_statuses: [], board_statuses: [], expense_categories: [], risk_severities: [] })
const filters = reactive({ search: '', status: '', include_archived: false })
const loading = ref(false)
const initialized = ref(false)
const workspaceLoading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const selectedProject = ref(null)
const selectedVersionId = ref('')
const versionWorkspace = reactive({ version: null, bom: [], boards: [], cost: {} })
const activeTab = ref('overview')
const statusDraft = ref('planning')
const expandedBoards = reactive(new Set())

const createDialog = ref(false)
const versionDialog = ref(false)
const bomDialog = ref(false)
const expenseDialog = ref(false)
const riskDialog = ref(false)
const componentLoading = ref(false)
const componentOptions = ref([])
const createForm = reactive({ project_code: '', name: '', description: '', status: 'planning', start_date: localDate() })
const createTimelineDates = reactive({ planning: localDate() })
const infoForm = reactive({ name: '', description: '', start_date: '', end_date: '' })
const versionForm = reactive({ version_code: '', change_summary: '' })
const bomForm = reactive({ component_id: null, quantity_per_board: 1, designators: '', note: '' })
const expenseForm = reactive({ category: 'pcb_fabrication', amount: 0.01, occurred_on: localDate(), version_id: null, vendor: '', note: '' })
const riskForm = reactive({ severity: 'medium', title: '', detail: '' })

const tabs = [
  { value: 'overview', label: '概览', note: '状态与周期', icon: DataAnalysis },
  { value: 'versions', label: 'PCB 版本', note: '设计迭代', icon: Files },
  { value: 'assembly', label: 'BOM 与装配', note: '库存与焊接', icon: FolderOpened },
  { value: 'cost', label: '成本', note: '材料与费用', icon: Coin },
  { value: 'files', label: '文件与风险', note: '资料与待办', icon: WarningFilled },
]

const metricCards = computed(() => [
  { label: '活跃项目', value: String(bootstrap.metrics.active_count || 0), note: `${bootstrap.metrics.paused_count || 0} 个暂停`, icon: TrendCharts, tone: 'teal' },
  { label: '验证与交付', value: String(bootstrap.metrics.completed_count || 0), note: '已形成可复用成果', icon: DataAnalysis, tone: 'green' },
  { label: '综合实际成本', value: money(bootstrap.metrics.comprehensive_cost), note: '材料耗用 + 直接费用', icon: Coin, tone: 'copper' },
  { label: '未计价项', value: String(bootstrap.metrics.unpriced_count || 0), note: '均价缺失，不按零元计算', icon: WarningFilled, tone: 'amber' },
])
const totalStatusProjects = computed(() => bootstrap.status_distribution.reduce((sum, item) => sum + Number(item.count || 0), 0))
const maxStatus = computed(() => Math.max(1, ...bootstrap.status_distribution.map(item => Number(item.count || 0))))
const maxExpense = computed(() => Math.max(1, ...bootstrap.expense_breakdown.map(item => Number(item.amount || 0))))
const maxTrend = computed(() => Math.max(1, ...bootstrap.weekly_cost.map(item => Number(item.amount || 0))))
const trendDots = computed(() => bootstrap.weekly_cost.map((item, index, rows) => ({
  key: item.week,
  amount: Number(item.amount || 0),
  x: rows.length === 1 ? 180 : 22 + (index * 318 / (rows.length - 1)),
  y: 108 - (Number(item.amount || 0) / maxTrend.value) * 82,
})))
const trendPoints = computed(() => trendDots.value.map(point => `${point.x},${point.y}`).join(' '))
const nextVersionCode = computed(() => `V${(selectedProject.value?.versions?.length || 0) + 1}`)
const riskSegmentOptions = computed(() => options.risk_severities.map(item => ({ label: item.label, value: item.value })))
const lifecycleDefinitions = [
  ['planning', '方案规划'], ['component_selection', '零件选型'], ['schematic', '原理图准备'],
  ['pcb_design', 'PCB 设计'], ['fabricating', '打板中'], ['assembly_testing', '装配调试'],
  ['validated', '验证完成'], ['delivered', '已交付'],
]
const createReachedStages = computed(() => {
  const currentIndex = lifecycleDefinitions.findIndex(([status]) => status === createForm.status)
  if (currentIndex < 0) return []
  return lifecycleDefinitions.slice(0, currentIndex + 1).map(([status, label]) => ({ status, label }))
})
const lifecycleNodes = computed(() => {
  const serverNodes = selectedProject.value?.lifecycle?.nodes
  if (Array.isArray(serverNodes) && serverNodes.length) return serverNodes
  const currentIndex = lifecycleDefinitions.findIndex(([status]) => status === selectedProject.value?.status)
  const events = [...(selectedProject.value?.status_history || [])].reverse()
  return lifecycleDefinitions.map(([status, label], index) => {
    const event = events.find(item => item.to_status === status)
    return {
      status, label, position: index + 1,
      state: index === currentIndex ? 'current' : event ? 'completed' : index < currentIndex ? 'skipped' : 'upcoming',
      occurred_at: event?.created_at || null, iso_week: null,
    }
  })
})
const periodWeekRange = computed(() => {
  const period = selectedProject.value?.period
  if (!period) return '—'
  const start = `${period.start_week || isoWeekLabel(period.start_date)}（${shortMonthDay(period.start_date)}）`
  const endDate = period.end_date || localDate()
  const end = `${period.end_week || period.current_week || isoWeekLabel(endDate)}（${period.end_date ? shortMonthDay(endDate) : '今天'}）`
  return start === end ? start : `${start} → ${end}`
})

watch(() => createForm.start_date, (value) => { createTimelineDates.planning = value || '' })
watch(() => createForm.status, () => {
  const reached = new Set(createReachedStages.value.map(item => item.status))
  for (const [status] of lifecycleDefinitions) {
    if (!reached.has(status)) delete createTimelineDates[status]
  }
  const current = createReachedStages.value.at(-1)?.status
  if (current && current !== 'planning' && !createTimelineDates[current]) createTimelineDates[current] = localDate()
})

onMounted(async () => {
  await loadDashboard()
  await syncProjectFromRoute()
})

watch(() => route.params.projectId, async () => {
  if (initialized.value) await syncProjectFromRoute()
})

async function loadDashboard() {
  loading.value = true
  try {
    const data = await getProjectWorkspaceBootstrap({ search: filters.search || undefined, status: filters.status || undefined, include_archived: filters.include_archived })
    Object.assign(bootstrap, emptyBootstrap(), data)
    Object.assign(options, data.options || {})
    initialized.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error, '读取项目工作区失败'))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(createForm, { project_code: '', name: '', description: '', status: 'planning', start_date: localDate() })
  for (const [status] of lifecycleDefinitions) delete createTimelineDates[status]
  createTimelineDates.planning = createForm.start_date
  createDialog.value = true
}

async function createProject() {
  if (!createForm.project_code.trim() || !createForm.name.trim()) return ElMessage.warning('请填写项目编号和名称')
  if (!createForm.start_date) return ElMessage.warning('请选择实际立项日期')
  const lifecycleDates = {}
  if (createReachedStages.value.length) {
    for (const stage of createReachedStages.value) {
      const occurredOn = createTimelineDates[stage.status]
      if (!occurredOn) return ElMessage.warning(`请填写进入${stage.label}的实际日期`)
      lifecycleDates[stage.status] = occurredOn
    }
    const orderedDates = Object.values(lifecycleDates)
    if (orderedDates.some((value, index) => index && value < orderedDates[index - 1])) return ElMessage.warning('节点日期必须按研发阶段依次递增')
  }
  saving.value = true
  try {
    const created = await createWorkspaceProject({ ...createForm, ...(Object.keys(lifecycleDates).length ? { lifecycle_dates: lifecycleDates } : {}) })
    createDialog.value = false
    await loadDashboard()
    await openProject(created)
    ElMessage.success('项目已建立，V1 可暂时保持空 BOM')
  } catch (error) {
    ElMessage.error(errorMessage(error, '创建项目失败'))
  } finally { saving.value = false }
}

async function openProject(project) {
  if (!project?.id) return
  if (route.name === 'project-detail' && route.params.projectId === project.id) {
    selectedProject.value = project
    activeTab.value = 'overview'
    await refreshProject()
    return
  }
  await router.push({ name: 'project-detail', params: { projectId: project.id } })
}

async function syncProjectFromRoute() {
  const projectId = typeof route.params.projectId === 'string' ? route.params.projectId : ''
  if (!projectId) {
    selectedProject.value = null
    selectedVersionId.value = ''
    expandedBoards.clear()
    return
  }
  selectedProject.value = bootstrap.projects.find(project => project.id === projectId) || { id: projectId }
  activeTab.value = 'overview'
  await refreshProject()
}

async function refreshProject() {
  if (!selectedProject.value?.id) return
  workspaceLoading.value = true
  try {
    const detail = await getWorkspaceProject(selectedProject.value.id)
    selectedProject.value = detail
    statusDraft.value = detail.status
    Object.assign(infoForm, {
      name: detail.name, description: detail.description || '',
      start_date: detail.period.start_date || '', end_date: detail.period.end_date || '',
    })
    const versionId = selectedVersionId.value && detail.versions.some(item => item.id === selectedVersionId.value)
      ? selectedVersionId.value : detail.current_version?.id || detail.versions[0]?.id
    selectedVersionId.value = versionId || ''
    if (selectedVersionId.value) await loadVersionWorkspace()
  } catch (error) {
    ElMessage.error(errorMessage(error, '读取项目详情失败'))
    if (error?.response?.status === 404) await router.replace({ name: 'projects' })
  } finally { workspaceLoading.value = false }
}

async function closeProject() {
  selectedProject.value = null
  selectedVersionId.value = ''
  expandedBoards.clear()
  if (route.name !== 'projects') await router.push({ name: 'projects' })
  await loadDashboard()
}

async function saveStatus(status) {
  if (!selectedProject.value) return
  const prior = selectedProject.value.status
  try {
    let clearEnd = false
    if (selectedProject.value.period.end_date && !['validated', 'delivered'].includes(status)) {
      await ElMessageBox.confirm('项目已有结束日期。退回前置阶段时是否清除结束日期？', '更新项目状态', { confirmButtonText: '清除并更新', cancelButtonText: '保留日期', distinguishCancelAndClose: true }).then(() => { clearEnd = true }).catch(action => { if (action === 'close') throw new Error('__cancel__') })
    }
    await changeWorkspaceProjectStatus(selectedProject.value.id, { status, source: 'web', clear_end_date: clearEnd })
    await refreshProject()
    ElMessage.success('项目状态已更新')
  } catch (error) {
    statusDraft.value = prior
    if (error.message !== '__cancel__') ElMessage.error(errorMessage(error, '状态更新失败'))
  }
}

async function saveInfo() {
  if (!infoForm.name.trim()) return ElMessage.warning('项目名称不能为空')
  saving.value = true
  try {
    await updateWorkspaceProject(selectedProject.value.id, { ...infoForm, end_date: infoForm.end_date || null })
    await refreshProject()
    ElMessage.success('项目信息已保存')
  } catch (error) { ElMessage.error(errorMessage(error, '保存失败')) } finally { saving.value = false }
}

async function createVersion() {
  const code = versionForm.version_code.trim() || nextVersionCode.value
  if ((selectedProject.value.versions?.length || 0) >= 1 && !versionForm.change_summary.trim()) return ElMessage.warning('请填写新版变更说明')
  saving.value = true
  try {
    const version = await createWorkspaceVersion(selectedProject.value.id, { version_code: code, change_summary: versionForm.change_summary })
    versionDialog.value = false
    Object.assign(versionForm, { version_code: '', change_summary: '' })
    selectedVersionId.value = version.id
    await refreshProject()
    ElMessage.success(`${version.version_code} 已建立并复制上一版 BOM`)
  } catch (error) { ElMessage.error(errorMessage(error, '建立版本失败')) } finally { saving.value = false }
}

async function saveVersionStatus(version, status) {
  try {
    await updateWorkspaceVersion(selectedProject.value.id, version.id, { status })
    selectedVersionId.value = version.id
    await refreshProject()
    ElMessage.success('PCB 版本状态已更新')
  } catch (error) { ElMessage.error(errorMessage(error, '更新版本失败')) }
}

async function selectVersion(version) {
  selectedVersionId.value = version.id
  activeTab.value = 'assembly'
  await loadVersionWorkspace()
}

async function loadVersionWorkspace() {
  if (!selectedProject.value?.id || !selectedVersionId.value) return
  try {
    const data = await getWorkspaceVersion(selectedProject.value.id, selectedVersionId.value)
    Object.assign(versionWorkspace, { version: null, bom: [], boards: [], cost: {} }, data)
  } catch (error) { ElMessage.error(errorMessage(error, '读取版本数据失败')) }
}

async function handleFabricationChanged() {
  await loadVersionWorkspace()
  await refreshProject()
}

async function searchComponents(query = '') {
  componentLoading.value = true
  try { componentOptions.value = await searchWorkspaceComponents({ q: query || undefined, limit: 40 }) }
  catch (error) { ElMessage.error(errorMessage(error, '搜索元器件失败')) }
  finally { componentLoading.value = false }
}

async function addBom() {
  if (!bomForm.component_id) return ElMessage.warning('请选择库存元器件')
  saving.value = true
  try {
    await addWorkspaceBomItem(selectedProject.value.id, selectedVersionId.value, { ...bomForm })
    bomDialog.value = false
    Object.assign(bomForm, { component_id: null, quantity_per_board: 1, designators: '', note: '' })
    await loadVersionWorkspace()
    await refreshProject()
    ElMessage.success('BOM 物料已添加')
  } catch (error) { ElMessage.error(errorMessage(error, '添加 BOM 失败')) } finally { saving.value = false }
}

async function removeBom(item) {
  try {
    await ElMessageBox.confirm(`确认从当前版本移除“${item.name}”？`, '移除 BOM', { type: 'warning' })
    await deleteWorkspaceBomItem(selectedProject.value.id, selectedVersionId.value, item.id)
    await loadVersionWorkspace()
    await refreshProject()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error, '删除失败')) }
}

async function handleBomImport({ file }) {
  uploading.value = true
  try {
    const result = await importWorkspaceBom(selectedProject.value.id, selectedVersionId.value, file)
    await loadVersionWorkspace()
    await refreshProject()
    const notes = [`导入 ${result.created} 条`]
    if (result.unmatched.length) notes.push(`${result.unmatched.length} 条未匹配`)
    if (result.skipped.length) notes.push(`${result.skipped.length} 条已存在`)
    ElMessage.success(notes.join('，'))
  } catch (error) { ElMessage.error(errorMessage(error, 'BOM 导入失败')) } finally { uploading.value = false }
}

async function createBoard() {
  try {
    await createWorkspaceBoard(selectedProject.value.id, selectedVersionId.value, {})
    await loadVersionWorkspace()
    await refreshProject()
    ElMessage.success('实物板已建立')
  } catch (error) { ElMessage.error(errorMessage(error, '建立实物板失败')) }
}

function toggleBoard(id) { expandedBoards.has(id) ? expandedBoards.delete(id) : expandedBoards.add(id) }

async function runPointAction(board, point, action) {
  try {
    await changeWorkspaceSolderPoint(selectedProject.value.id, selectedVersionId.value, board.id, point.id, { action, expected_version: point.state_version })
    await loadVersionWorkspace()
    await refreshProject()
  } catch (error) { ElMessage.error(errorMessage(error, '焊点操作失败')) }
}

async function createExpense() {
  saving.value = true
  try {
    await addWorkspaceExpense(selectedProject.value.id, { ...expenseForm, version_id: expenseForm.version_id || null })
    expenseDialog.value = false
    Object.assign(expenseForm, { category: 'pcb_fabrication', amount: 0.01, occurred_on: localDate(), version_id: null, vendor: '', note: '' })
    await refreshProject()
    ElMessage.success('费用已记入台账')
  } catch (error) { ElMessage.error(errorMessage(error, '保存费用失败')) } finally { saving.value = false }
}

async function archiveExpense(expense) {
  try {
    await ElMessageBox.confirm(`归档这笔 ${money(expense.amount)} 的费用？`, '归档费用', { type: 'warning' })
    await archiveWorkspaceExpense(selectedProject.value.id, expense.id)
    await refreshProject()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error, '归档失败')) }
}

async function fillUnpriced() {
  try {
    const result = await fillWorkspaceUnpriced(selectedProject.value.id)
    await refreshProject()
    ElMessage.success(`已补齐 ${result.filled} 条成本快照`)
  } catch (error) { ElMessage.error(errorMessage(error, '补价失败')) }
}

async function createRisk() {
  if (!riskForm.title.trim()) return ElMessage.warning('请填写风险标题')
  saving.value = true
  try {
    await addWorkspaceRisk(selectedProject.value.id, { ...riskForm })
    riskDialog.value = false
    Object.assign(riskForm, { severity: 'medium', title: '', detail: '' })
    await refreshProject()
  } catch (error) { ElMessage.error(errorMessage(error, '保存风险失败')) } finally { saving.value = false }
}

async function resolveRisk(risk) {
  try { await updateWorkspaceRisk(selectedProject.value.id, risk.id, { status: 'resolved' }); await refreshProject() }
  catch (error) { ElMessage.error(errorMessage(error, '更新风险失败')) }
}

async function handleProjectFile({ file }) {
  uploading.value = true
  try {
    await uploadWorkspaceFile(selectedProject.value.id, file, selectedVersionId.value || null)
    await refreshProject()
    ElMessage.success('文件已上传')
  } catch (error) { ElMessage.error(errorMessage(error, '上传文件失败')) } finally { uploading.value = false }
}

async function downloadFile(file) {
  try {
    const blob = await downloadWorkspaceFile(selectedProject.value.id, file.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = file.name; link.click(); URL.revokeObjectURL(url)
  } catch (error) { ElMessage.error(errorMessage(error, '下载失败')) }
}

async function handleProjectCommand(command) {
  if (command !== 'archive') return
  try {
    await ElMessageBox.confirm('归档后项目默认不出现在总览，可通过“显示归档”恢复查看。', '归档项目', { type: 'warning' })
    await archiveWorkspaceProject(selectedProject.value.id)
    await closeProject()
    ElMessage.success('项目已归档')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error, '归档失败')) }
}

function setStatusFilter(status) { filters.status = filters.status === status ? '' : status; loadDashboard() }
function statusPercent(count) { return Math.max(8, Number(count || 0) * 100 / maxStatus.value) }
function expensePercent(amount) { return Math.max(4, Number(amount || 0) * 100 / maxExpense.value) }
function money(value) { return `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }
function shortDate(value) { return value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value)) : '—' }
function dateTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '—' }
function eventDateTime(event) { return event?.occurred_precision === 'date' ? shortDate(event.created_at) : dateTime(event?.created_at) }
function sourceLabel(value) { return ({ create: '创建', timeline_actual: '实际节点', timeline_estimate: '自动估算', timeline_backfill: '旧版估算', chatgpt_approval: 'ChatGPT 审批', web: '网页', board_drag: '看板' })[value] || value || '网页' }
function lifecycleRange(node) {
  if (!node?.occurred_at) return '尚未开始'
  const start = shortMonthDay(node.occurred_on || node.occurred_at)
  if (node.ongoing) return `${start}—今天`
  return node.ended_on ? `${start}—${shortMonthDay(node.ended_on)}` : start
}
function lifecycleWeekRange(node) {
  if (!node?.occurred_at) return ''
  const start = node.iso_week || isoWeekLabel(node.occurred_on || node.occurred_at)
  const end = node.ongoing ? isoWeekLabel(localDate()) : (node.end_iso_week || start)
  return start === end ? start : `${start}—${end}`
}
function nodeStateLabel(value) { return ({ completed: '已完成', current: '当前阶段', skipped: '未记录', upcoming: '待开始' })[value] || '待开始' }
function disableFutureDate(value) { return value.getTime() > new Date(`${localDate()}T23:59:59`).getTime() }
function pointStateLabel(value) { return ({ pending: '待焊', soldered: '已焊', lost: '报损' })[value] || value }
function fileSize(value) { const size = Number(value || 0); return size >= 1048576 ? `${(size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB` }
function localDate() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}` }
function errorMessage(error, fallback) { return error?.response?.data?.detail || error?.message || fallback }
</script>

<style scoped>
.project-v2 {
  --pv2-ink: #102a32;
  --pv2-muted: #52666f;
  --pv2-line: #cedadd;
  --pv2-teal: #006b78;
  --pv2-teal-soft: #d9eef1;
  --pv2-copper: #a9521c;
  width: min(1500px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 76px;
  color: var(--pv2-ink);
}
.material-surface {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(25, 72, 82, .17);
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 16px 40px rgba(23, 55, 63, .10), inset 0 1px 0 rgba(255, 255, 255, .85);
}
.material-surface::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: inherit;
  background-image: radial-gradient(circle at 1px 1px, rgba(16, 42, 50, .032) 1px, transparent 0);
  background-size: 16px 16px;
  mask-image: linear-gradient(to bottom, #000, transparent 46%);
}
.material-surface > * { position: relative; z-index: 1; }
.page-hero, .workspace-head { padding: 30px 32px; display: flex; align-items: center; justify-content: space-between; gap: 28px; }
.page-hero { border-top: 4px solid var(--pv2-teal); }
.eyebrow, .section-kicker { color: var(--pv2-teal); font-size: 11px; font-weight: 800; letter-spacing: .15em; }
h1, h2, h3, p { overflow-wrap: anywhere; }
.hero-copy { min-width: 0; }
.hero-copy h1 { margin: 6px 0 4px; font-size: clamp(27px, 3vw, 40px); line-height: 1.15; letter-spacing: -.035em; }
.hero-copy p, .panel-head p { margin: 0; color: var(--pv2-muted); line-height: 1.65; }
.hero-actions, .panel-actions, .workspace-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; flex: 0 0 auto; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
.metric-card { min-height: 142px; padding: 22px; display: grid; grid-template-columns: 46px minmax(0, 1fr); gap: 16px; align-items: start; }
.metric-icon { display: grid; place-items: center; width: 46px; height: 46px; border-radius: 14px; color: var(--pv2-teal); background: var(--pv2-teal-soft); }
.metric-icon :deep(svg) { width: 22px; }
.metric-copy { min-width: 0; display: grid; gap: 4px; }
.metric-copy small, .fact-card small { color: var(--pv2-muted); font-weight: 650; }
.metric-copy strong { display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: clamp(26px, 2.4vw, 36px); line-height: 1.15; letter-spacing: -.035em; }
.metric-copy p { margin: 2px 0 0; color: var(--pv2-muted); font-size: 13px; line-height: 1.45; }
.metric-card.green .metric-icon { color: #176b59; background: #e0f1eb; }
.metric-card.copper .metric-icon { color: #8f4519; background: #f7e7dc; }
.metric-card.amber .metric-icon { color: #7b5a0e; background: #f6edcf; }
.insight-grid { display: grid; grid-template-columns: 1fr 1.25fr 1fr; gap: 16px; margin-top: 16px; }
.insight-card { min-height: 300px; padding: 22px; }
.section-heading, .panel-head, .subhead { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; }
.section-heading h2, .panel-head h2, .subhead h3 { margin: 4px 0 0; font-size: 20px; line-height: 1.2; }
.section-heading > small, .panel-head > small, .subhead > small { color: var(--pv2-muted); white-space: nowrap; }
.status-bars, .cost-ranks { display: grid; gap: 15px; margin-top: 24px; }
.status-bar-row { width: 100%; display: grid; grid-template-columns: minmax(72px, 110px) minmax(80px, 1fr) 24px; gap: 10px; align-items: center; border: 0; padding: 0; color: inherit; background: none; cursor: pointer; text-align: left; }
.bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: #304a54; }
.bar-track, .rank-track, .progress-track { height: 8px; overflow: hidden; border-radius: 999px; background: #e2eaec; }
.bar-track i, .rank-track i, .progress-track i { display: block; height: 100%; border-radius: inherit; background: var(--pv2-teal); transition: width .25s ease; }
.status-bar-row:nth-child(2n) .bar-track i { background: #3f7165; }
.status-bar-row:nth-child(3n) .bar-track i { background: #a9521c; }
.line-chart { margin-top: 16px; }
.line-chart svg { display: block; width: 100%; height: 188px; }
.grid-line { stroke: #dfe7e9; stroke-width: 1; }
.trend-line { stroke: var(--pv2-teal); stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }
.trend-dot { fill: #fff; stroke: var(--pv2-copper); stroke-width: 3; }
.chart-axis { display: flex; justify-content: space-between; color: var(--pv2-muted); font-size: 12px; }
.cost-rank > div { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px; font-size: 13px; }
.cost-rank > div span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cost-rank strong { white-space: nowrap; }
.cost-rank:nth-child(2n) .rank-track i { background: var(--pv2-copper); }
.chart-empty, .inline-empty { min-height: 170px; display: grid; place-items: center; padding: 24px; color: var(--pv2-muted); text-align: center; border: 1px dashed var(--pv2-line); border-radius: 14px; margin-top: 20px; }
.project-list { margin-top: 16px; padding: 22px; }
.list-toolbar { display: flex; align-items: end; justify-content: space-between; gap: 22px; margin-bottom: 18px; }
.filters { display: grid; grid-template-columns: minmax(210px, 1.5fr) minmax(150px, 1fr) auto auto; gap: 10px; align-items: center; width: min(760px, 100%); }
.filters :deep(.el-input), .filters :deep(.el-select) { width: 100%; }
.project-table { overflow-x: auto; border: 1px solid var(--pv2-line); border-radius: 14px; }
.project-row { min-width: 1050px; width: 100%; display: grid; grid-template-columns: minmax(190px, 1.45fr) minmax(120px, .78fr) minmax(110px, .72fr) minmax(130px, .9fr) minmax(130px, .9fr) minmax(140px, .95fr) minmax(110px, .72fr); align-items: center; gap: 12px; border: 0; border-bottom: 1px solid #e2e9eb; padding: 15px 16px; color: inherit; background: #fff; text-align: left; cursor: pointer; }
.project-row:last-child { border-bottom: 0; }
.project-row:not(.project-row--head):hover { background: #f2f7f7; }
.project-row--head { position: sticky; top: 0; z-index: 2; padding-block: 11px; color: #52666f; background: #eaf1f2; cursor: default; font-size: 12px; font-weight: 750; }
.project-row > span { min-width: 0; display: grid; gap: 3px; }
.project-row strong, .project-row small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-row small { color: var(--pv2-muted); font-size: 12px; }
.status-chip { display: inline-flex; width: fit-content; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-radius: 999px; padding: 5px 9px; color: #075660; background: #d9eef1; font-size: 12px; font-style: normal; font-weight: 750; }
.status-chip[data-status='paused'], .status-chip[data-status='cancelled'] { color: #7c3d2c; background: #f6e2dc; }
.status-chip[data-status='validated'], .status-chip[data-status='delivered'] { color: #145b4d; background: #dceee8; }
.warning-text { color: #8b4a12 !important; }
.project-empty { min-height: 300px; display: grid; place-items: center; align-content: center; gap: 8px; text-align: center; }
.project-empty h3, .project-empty p { margin: 0; }
.project-empty p { color: var(--pv2-muted); }
.empty-mark { display: grid; place-items: center; width: 60px; height: 60px; border-radius: 18px; color: var(--pv2-teal); background: var(--pv2-teal-soft); }
.empty-mark :deep(svg) { width: 28px; }
.workspace-loader { min-height: 62vh; display: grid; place-items: center; align-content: center; gap: 10px; color: var(--pv2-ink); }
.workspace-loader small { color: var(--pv2-muted); }
.workspace-loader__mark { width: 36px; height: 36px; border: 3px solid #c9dadd; border-top-color: var(--pv2-teal); border-radius: 50%; animation: pv2-spin .75s linear infinite; }
@keyframes pv2-spin { to { transform: rotate(360deg); } }
.workspace-head { display: grid; align-items: stretch; padding: 18px 26px 26px; border-top: 4px solid var(--pv2-teal); }
.back-button { width: fit-content; display: inline-flex; align-items: center; gap: 7px; border: 0; padding: 4px 0; color: #31545e; background: none; cursor: pointer; font-weight: 700; }
.back-button :deep(svg) { width: 18px; }
.workspace-title { display: flex; justify-content: space-between; align-items: end; gap: 24px; }
.workspace-title__copy { min-width: 0; }
.stable-code { display: inline-flex; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border: 1px solid #9fb9bf; border-radius: 7px; padding: 4px 8px; color: #31545e; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.workspace-title h1 { max-width: 850px; margin: 10px 0 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: clamp(25px, 3vw, 38px); }
.workspace-title p { max-width: 850px; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--pv2-muted); }
.workspace-actions :deep(.el-select) { width: 170px; }
.workspace-tabs { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; margin-top: 16px; padding: 8px; }
.workspace-tabs button { min-width: 0; display: grid; grid-template-columns: 22px minmax(0, 1fr); grid-template-rows: auto auto; column-gap: 8px; border: 0; border-radius: 12px; padding: 12px 14px; color: #405861; background: transparent; cursor: pointer; text-align: left; }
.workspace-tabs button :deep(svg) { grid-row: 1 / 3; align-self: center; width: 20px; }
.workspace-tabs button span, .workspace-tabs button small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-tabs button span { font-weight: 760; }
.workspace-tabs button small { color: #6a7d84; font-size: 11px; }
.workspace-tabs button.active { color: #fff; background: var(--pv2-teal); box-shadow: 0 8px 18px rgba(0, 107, 120, .2); }
.workspace-tabs button.active small { color: #d8eef0; }
.workspace-inline-loading { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 16px; color: var(--pv2-muted); }
.workspace-inline-loading .workspace-loader__mark { width: 20px; height: 20px; border-width: 2px; }
.fact-grid, .cost-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
.fact-card { min-height: 130px; display: grid; align-content: center; gap: 7px; padding: 22px; border-bottom: 3px solid #79aab1; }
.fact-card:nth-child(2) { border-bottom-color: #7a8751; }
.fact-card:nth-child(3) { border-bottom-color: #b66a37; }
.fact-card:nth-child(4) { border-bottom-color: #285f68; }
.fact-card strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: clamp(22px, 2.2vw, 30px); }
.fact-card span { color: var(--pv2-muted); font-size: 13px; }
.lifecycle-panel { margin-top: 16px; padding: 24px; overflow: hidden; }
.lifecycle-head { align-items: center; margin-bottom: 22px; }
.lifecycle-head p { max-width: 720px; }
.lifecycle-side-state { flex: 0 0 auto; border: 1px solid #e1c19f; border-radius: 999px; padding: 7px 11px; color: #77451f; background: #fbefe3; font-size: 12px; font-weight: 720; }
.lifecycle-scroll { max-width: 100%; overflow-x: auto; padding: 3px 2px 8px; scrollbar-color: #9db6bb transparent; }
.lifecycle-track { min-width: 1120px; display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); margin: 0; padding: 0; list-style: none; }
.lifecycle-track li { position: relative; min-width: 0; display: grid; grid-template-rows: 40px auto; justify-items: center; padding: 0 8px; text-align: center; }
.lifecycle-track li:not(:last-child)::before { content: ''; position: absolute; z-index: 0; top: 18px; left: 50%; width: 100%; height: 4px; border-radius: 999px; background: #d7e1e3; }
.lifecycle-track li[data-state='completed']::before { background: #5d8f87; }
.lifecycle-marker { position: relative; z-index: 1; display: grid; place-items: center; width: 38px; height: 38px; border: 4px solid #edf2f3; border-radius: 50%; color: #687b82; background: #d7e1e3; box-shadow: 0 0 0 1px #cbd8db; }
.lifecycle-marker b { font-size: 12px; line-height: 1; }
.lifecycle-track li[data-state='completed'] .lifecycle-marker { border-color: #dcece8; color: #fff; background: #3e796e; box-shadow: 0 0 0 1px #3e796e; }
.lifecycle-track li[data-state='current'] .lifecycle-marker { border-color: #f8e4d4; color: #fff; background: var(--pv2-copper); box-shadow: 0 0 0 2px #b86732, 0 7px 18px rgba(164, 81, 28, .2); }
.lifecycle-track li[data-state='skipped'] .lifecycle-marker { color: #566a72; background: #edf1f2; box-shadow: 0 0 0 1px #adbdc1; }
.lifecycle-node-copy { min-width: 0; width: 100%; display: grid; gap: 3px; margin-top: 10px; }
.lifecycle-node-copy strong, .lifecycle-node-copy time, .lifecycle-node-copy > span, .lifecycle-node-copy small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lifecycle-node-copy strong { color: #52666f; font-size: 14px; }
.lifecycle-node-copy time, .lifecycle-node-copy > span { color: #6b7f86; font-size: 12px; font-variant-numeric: tabular-nums; }
.lifecycle-node-copy small { color: #82949a; font-size: 11px; }
.lifecycle-track li[data-state='completed'] .lifecycle-node-copy strong { color: #285f57; }
.lifecycle-track li[data-state='current'] .lifecycle-node-copy strong { color: #833e18; font-weight: 820; }
.lifecycle-track li[data-state='skipped'] .lifecycle-node-copy strong { color: #52666f; }
.lifecycle-track li[data-state='upcoming'] .lifecycle-node-copy { opacity: .78; }
.workspace-columns { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(320px, .65fr); gap: 16px; margin-top: 16px; align-items: start; }
.content-panel { padding: 24px; margin-top: 16px; }
.workspace-columns .content-panel { margin-top: 0; }
.panel-head { margin-bottom: 22px; }
.panel-head > div:first-child { min-width: 0; }
.project-form :deep(.el-form-item) { margin-bottom: 20px; }
.project-form :deep(.el-form-item__label) { height: auto; line-height: 1.35; padding: 0 0 8px; color: var(--pv2-ink); font-weight: 700; }
.project-form :deep(.el-input), .project-form :deep(.el-select), .project-form :deep(.el-date-editor) { width: 100%; }
.form-grid, .dialog-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; }
.field-help { display: block; width: 100%; margin-top: 6px; color: var(--pv2-muted); line-height: 1.45; }
.date-week-field { min-width: 0; width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: center; }
.date-week-field :deep(.el-date-editor) { min-width: 0; width: 100%; }
.date-week-field > span { display: inline-flex; align-items: center; min-height: 32px; white-space: nowrap; border-radius: 9px; padding: 0 8px; color: #285f68; background: #e4f0f1; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; font-weight: 730; }
.date-week-field > span.empty { color: #6e7f85; background: #edf1f2; }
.timeline-create-help { margin: -4px 0 20px; border-left: 3px solid #5d8f87; border-radius: 0 10px 10px 0; padding: 10px 12px; color: #405861; background: #edf5f3; font-size: 12px; line-height: 1.6; }
.create-timeline-editor { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; margin: 0 0 4px; border: 1px solid #d5e2e4; border-radius: 14px; padding: 16px; background: #f7fafa; }
.timeline-list { max-height: 560px; overflow: auto; margin: 0; padding: 0; list-style: none; }
.timeline-list li { position: relative; display: grid; grid-template-columns: 14px minmax(0, 1fr); gap: 12px; padding-bottom: 22px; }
.timeline-list li > i { width: 12px; height: 12px; margin-top: 5px; border: 3px solid #d9eef1; border-radius: 50%; background: var(--pv2-teal); }
.timeline-list li:not(:last-child)::after { content: ''; position: absolute; left: 5px; top: 19px; bottom: 5px; width: 2px; background: #d6e2e4; }
.timeline-list strong, .timeline-list p, .timeline-list small { display: block; margin: 0; }
.timeline-list p { margin: 4px 0; color: #405861; line-height: 1.45; }
.timeline-list small { color: var(--pv2-muted); }
.version-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.version-card { min-width: 0; border: 1px solid var(--pv2-line); border-radius: 16px; padding: 18px; background: #f8fbfb; }
.version-card.current { border-color: #70aab1; box-shadow: inset 0 0 0 1px #70aab1; background: #edf6f7; }
.version-top, .version-stats, .version-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.version-top > span { font-size: 24px; font-weight: 820; }
.version-card p { min-height: 44px; color: var(--pv2-muted); line-height: 1.5; }
.version-stats { justify-content: flex-start; padding: 12px 0; border-block: 1px solid #dce6e8; }
.version-stats span { display: grid; gap: 2px; color: var(--pv2-muted); font-size: 11px; }
.version-stats strong { color: var(--pv2-ink); font-size: 16px; }
.version-actions { margin-top: 14px; }
.version-actions :deep(.el-select) { min-width: 0; flex: 1; }
.assembly-head { align-items: center; }
.panel-actions :deep(.el-select) { width: 130px; }
.assembly-layout { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(360px, .85fr); gap: 22px; }
.fabrication-workspace { margin-top: 28px; border-top: 1px solid #d8e3e5; padding-top: 26px; }
.bom-table { overflow-x: auto; border: 1px solid var(--pv2-line); border-radius: 12px; }
.bom-row { min-width: 720px; display: grid; grid-template-columns: minmax(180px, 1.4fr) 82px minmax(140px, 1fr) 70px 100px 50px; gap: 10px; align-items: center; padding: 12px; border-bottom: 1px solid #e1e9eb; }
.bom-row:last-child { border-bottom: 0; }
.bom-row--head { color: var(--pv2-muted); background: #eaf1f2; font-size: 12px; font-weight: 750; }
.bom-row > span { min-width: 0; }
.bom-name { display: grid; gap: 3px; }
.bom-name strong, .bom-name small, .ref-list { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bom-name small { color: var(--pv2-muted); }
.board-list { display: grid; gap: 12px; }
.board-card { border: 1px solid var(--pv2-line); border-radius: 14px; padding: 14px; background: #f8fbfb; }
.board-summary { width: 100%; display: flex; justify-content: space-between; gap: 12px; border: 0; padding: 0 0 10px; color: inherit; background: none; text-align: left; cursor: pointer; }
.board-summary > span { min-width: 0; display: grid; gap: 4px; }
.board-summary strong, .board-summary small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.board-summary small { color: var(--pv2-muted); }
.board-summary b { font-size: 22px; color: var(--pv2-teal); }
.point-grid { display: grid; gap: 7px; margin-top: 14px; }
.point-row { display: grid; grid-template-columns: minmax(120px, 1fr) 64px auto; gap: 8px; align-items: center; padding: 8px; border-radius: 9px; background: #fff; }
.point-row > span { min-width: 0; display: flex; gap: 8px; align-items: baseline; }
.point-row small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--pv2-muted); }
.point-state { width: fit-content; border-radius: 999px; padding: 3px 7px; color: #596d74; background: #e5edef; font-size: 11px; font-style: normal; font-weight: 720; }
.point-state[data-state='soldered'] { color: #145b4d; background: #dceee8; }
.point-state[data-state='lost'] { color: #853b37; background: #f3dfdd; }
.point-actions { display: flex; justify-content: flex-end; gap: 6px; }
.ledger-list, .file-list, .risk-list { display: grid; gap: 9px; }
.ledger-list article { display: grid; grid-template-columns: 90px minmax(0, 1fr) 130px auto; gap: 14px; align-items: center; padding: 13px; border: 1px solid #dde6e8; border-radius: 12px; }
.ledger-list article > div { min-width: 0; }
.ledger-list p, .risk-list p { margin: 4px 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--pv2-muted); }
.ledger-list b { text-align: right; font-size: 18px; }
.ledger-date { color: var(--pv2-muted); font-variant-numeric: tabular-nums; }
.file-list button { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 14px; border: 1px solid #dce6e8; border-radius: 12px; padding: 13px 14px; color: inherit; background: #f8fbfb; text-align: left; cursor: pointer; }
.file-list button > span { min-width: 0; display: grid; gap: 4px; }
.file-list strong, .file-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-list small { color: var(--pv2-muted); }
.file-list :deep(svg) { width: 19px; flex: 0 0 auto; }
.risk-list article { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 12px; align-items: center; border: 1px solid #dce6e8; border-left: 4px solid #8a732b; border-radius: 12px; padding: 12px; }
.risk-list article.low { border-left-color: #4f796e; }
.risk-list article.high { border-left-color: #a63f3b; }
.risk-list article > i { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: #f2ead2; font-size: 12px; font-style: normal; font-weight: 800; }
.risk-list article > div { min-width: 0; }
.resolved { color: #176b59; font-size: 12px; font-weight: 750; }
:deep(.el-dialog__body) .el-form-item { margin-bottom: 20px; }
:deep(.el-dialog__body) .el-form-item__label { height: auto; padding-bottom: 8px; line-height: 1.35; font-weight: 700; }
:deep(.el-dialog__body) .el-input, :deep(.el-dialog__body) .el-select, :deep(.el-dialog__body) .el-input-number, :deep(.el-dialog__body) .el-date-editor { width: 100%; }

@media (max-width: 1180px) {
  .metric-grid, .fact-grid, .cost-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .insight-grid { grid-template-columns: 1fr 1fr; }
  .insight-card:last-child { grid-column: 1 / -1; }
  .version-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .assembly-layout { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .project-v2 { width: min(100% - 22px, 1500px); padding-top: 18px; }
  .page-hero, .workspace-title, .list-toolbar, .panel-head { align-items: stretch; flex-direction: column; }
  .page-hero { padding: 24px; }
  .hero-actions, .workspace-actions, .panel-actions { width: 100%; }
  .hero-actions :deep(.el-button), .workspace-actions :deep(.el-button) { flex: 1; }
  .filters { width: 100%; grid-template-columns: 1fr 1fr; }
  .workspace-columns { grid-template-columns: 1fr; }
  .workspace-tabs { overflow-x: auto; grid-template-columns: repeat(5, minmax(150px, 1fr)); }
  .workspace-title h1, .workspace-title p { white-space: normal; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
}
@media (max-width: 680px) {
  .project-v2 { width: min(100% - 16px, 1500px); padding-bottom: 92px; }
  .metric-grid, .insight-grid, .fact-grid, .cost-metrics, .version-grid, .form-grid, .dialog-grid, .create-timeline-editor { grid-template-columns: 1fr; }
  .insight-card:last-child { grid-column: auto; }
  .metric-card { min-height: 118px; padding: 18px; }
  .filters { grid-template-columns: 1fr; }
  .project-list, .content-panel { padding: 16px; }
  .lifecycle-panel { padding: 18px 16px; }
  .lifecycle-head { align-items: flex-start; }
  .lifecycle-side-state { white-space: normal; }
  .lifecycle-scroll { overflow: visible; padding-left: 2px; }
  .lifecycle-track { min-width: 0; grid-template-columns: 1fr; }
  .lifecycle-track li { min-height: 78px; grid-template-columns: 40px minmax(0, 1fr); grid-template-rows: auto; justify-items: start; gap: 12px; padding: 0; text-align: left; }
  .lifecycle-track li:not(:last-child)::before { top: 19px; left: 18px; width: 4px; height: 100%; }
  .lifecycle-node-copy { margin-top: 1px; padding: 0 0 18px; }
  .lifecycle-node-copy strong, .lifecycle-node-copy time, .lifecycle-node-copy > span, .lifecycle-node-copy small { white-space: normal; }
  .project-table { border: 0; overflow: visible; }
  .project-row--head { display: none; }
  .project-row { min-width: 0; grid-template-columns: 1fr 1fr; gap: 13px; margin-bottom: 10px; border: 1px solid var(--pv2-line); border-radius: 14px; padding: 14px; }
  .project-row .project-identity { grid-column: 1 / -1; padding-bottom: 8px; border-bottom: 1px solid #e2e9eb; }
  .project-row > span:last-child { grid-column: 1 / -1; }
  .workspace-head { padding: 15px 16px 20px; }
  .workspace-actions :deep(.el-select) { width: 100%; }
  .workspace-actions :deep(.el-button) { flex: 1 1 42%; margin-left: 0; }
  .panel-actions :deep(.el-select), .panel-actions :deep(.el-button), .panel-actions :deep(.el-upload) { width: 100%; }
  .panel-actions :deep(.el-upload .el-button) { width: 100%; }
  .ledger-list article { grid-template-columns: 1fr auto; }
  .ledger-date { grid-column: 1 / -1; }
  .point-row { grid-template-columns: minmax(0, 1fr) auto; }
  .point-actions { grid-column: 1 / -1; }
  .point-actions :deep(.el-button) { flex: 1; }
  .risk-list article { grid-template-columns: 32px minmax(0, 1fr); }
  .risk-list article > :last-child { grid-column: 2; justify-self: start; }
}
@media (prefers-reduced-motion: reduce) {
  .workspace-loader__mark { animation-duration: 1.8s; }
  .bar-track i, .rank-track i, .progress-track i { transition: none; }
}
</style>
