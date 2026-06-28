<template>
  <div class="engineering-page">
    <header class="page-head">
      <div><span class="eyebrow">工程检查</span><h1>风险检查</h1><p>集中查看缺少原理图符号、PCB 封装、数据手册、采购料号和库存不足等问题。</p></div>
      <div class="head-actions"><el-button @click="issueDialog = true">记录问题</el-button><el-button @click="load">重新检查</el-button></div>
    </header>
    <section class="summary-grid">
      <article class="danger"><span>高风险</span><strong>{{ result.counts?.danger || 0 }}</strong></article>
      <article class="warning"><span>警告</span><strong>{{ result.counts?.warning || 0 }}</strong></article>
      <article><span>全部问题</span><strong>{{ result.total || 0 }}</strong></article>
    </section>
    <section class="panel">
      <div class="filters">
        <el-select v-model="severity" clearable placeholder="全部级别"><el-option label="高风险" value="danger" /><el-option label="警告" value="warning" /></el-select>
        <el-select v-model="riskType" clearable placeholder="全部类型"><el-option v-for="type in riskTypes" :key="type" :label="typeLabel(type)" :value="type" /></el-select>
      </div>
      <el-empty v-if="!filtered.length" description="当前没有工程风险" />
      <div v-else class="risk-list">
        <article v-for="item in filtered" :key="item.id" :class="item.severity">
          <div>
            <el-tag :type="item.severity === 'danger' ? 'danger' : 'warning'">{{ typeLabel(item.risk_type) }}</el-tag>
            <h3>{{ item.title }}</h3>
            <p>{{ item.component_name || item.project_name }}<span v-if="item.warehouse_code"> · {{ item.warehouse_code }}</span></p>
          </div>
          <div><p>{{ item.detail }}</p><el-button v-if="item.source === 'manual'" size="small" type="success" plain @click="resolveIssue(item)">标记已解决</el-button></div>
        </article>
      </div>
    </section>
    <el-dialog v-model="issueDialog" title="记录封装或采购问题" width="540px">
      <el-form label-width="90px">
        <el-form-item label="问题类型"><el-select v-model="issueForm.risk_type"><el-option label="封装问题" value="footprint_issue" /><el-option label="采购问题" value="purchase_issue" /></el-select></el-form-item>
        <el-form-item label="元件 ID"><el-input-number v-model="issueForm.component_id" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="项目 ID"><el-input-number v-model="issueForm.project_id" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="级别"><el-select v-model="issueForm.severity"><el-option label="高风险" value="danger" /><el-option label="警告" value="warning" /><el-option label="提示" value="info" /></el-select></el-form-item>
        <el-form-item label="标题"><el-input v-model="issueForm.title" /></el-form-item>
        <el-form-item label="详情"><el-input v-model="issueForm.detail" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="issueDialog = false">取消</el-button><el-button type="primary" @click="saveIssue">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from '../elementApi'
import { createRiskIssue, listRisks, updateRiskIssue } from '../engineeringApi'
const route = useRoute()
const libraryId = computed(() => String(route.params.libraryId || ''))
const result = ref({ items: [], counts: {} })
const severity = ref('')
const riskType = ref('')
const issueDialog = ref(false)
const issueForm = reactive({ risk_type: 'footprint_issue', component_id: null, project_id: null, severity: 'warning', title: '', detail: '' })
const riskTypes = computed(() => [...new Set((result.value.items || []).map((item) => item.risk_type))])
const filtered = computed(() => (result.value.items || []).filter((item) => (!severity.value || item.severity === severity.value) && (!riskType.value || item.risk_type === riskType.value)))
const typeLabel = (type) => ({ missing_footprint: '缺少 PCB 封装', missing_symbol: '缺少原理图符号', unverified_footprint: 'PCB 封装未验证', missing_datasheet: '缺少数据手册', missing_supplier_part: '缺少采购料号', low_stock: '库存不足', bom_unmatched: 'BOM 未找到库存元件', footprint_issue: 'PCB 封装问题', purchase_issue: '采购问题' })[type] || type
onMounted(load)
async function load() {
  try { result.value = await listRisks(libraryId.value) }
  catch (error) { ElMessage.error(error.response?.data?.detail || '风险检查失败') }
}
async function saveIssue() {
  if (!issueForm.component_id && !issueForm.project_id) return ElMessage.warning('请关联元件或项目')
  if (!issueForm.title.trim()) return ElMessage.warning('请填写问题标题')
  await createRiskIssue(issueForm, libraryId.value)
  issueDialog.value = false
  Object.assign(issueForm, { risk_type: 'footprint_issue', component_id: null, project_id: null, severity: 'warning', title: '', detail: '' })
  await load()
}
async function resolveIssue(item) {
  await updateRiskIssue(item.id, { status: 'resolved' }, libraryId.value)
  await load()
}
</script>
<style scoped>
.engineering-page { display: grid; gap: 16px; }.page-head { display: flex; justify-content: space-between; gap: 16px; }.head-actions { display: flex; gap: 8px; }.page-head h1 { margin: 5px 0; }.page-head p { margin: 0; color: #667085; }.eyebrow { color: #f97316; font-size: 12px; font-weight: 800; letter-spacing: .12em; }
.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }.summary-grid article { padding: 15px; border: 1px solid #e4eaf2; border-radius: 16px; background: #fff; display: grid; }.summary-grid span { color: #667085; }.summary-grid strong { font-size: 26px; }.summary-grid .danger strong { color: #dc2626; }.summary-grid .warning strong { color: #d97706; }
.panel { padding: 16px; border: 1px solid #e4eaf2; border-radius: 16px; background: #fff; }.filters { display: flex; gap: 10px; margin-bottom: 14px; }.risk-list { display: grid; gap: 10px; }.risk-list article { display: grid; grid-template-columns: minmax(240px, 1fr) 2fr; gap: 16px; padding: 14px; border-left: 4px solid #f59e0b; border-radius: 16px; background: #fffbeb; }.risk-list article.danger { border-color: #ef4444; background: #fff5f5; }.risk-list h3 { margin: 8px 0 3px; }.risk-list p { margin: 0; color: #667085; }
@media (max-width: 700px) { .risk-list article { grid-template-columns: 1fr; }.summary-grid { grid-template-columns: 1fr; } }
</style>
