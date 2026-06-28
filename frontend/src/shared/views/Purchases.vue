<template>
  <div class="engineering-page">
    <header class="page-head">
      <div><span class="eyebrow">采购流程</span><h1>采购与到货入库</h1><p>把项目缺料变成采购单，记录分批到货，并自动增加库存。</p></div>
      <div class="head-actions"><el-button @click="exportPurchases">导出采购清单</el-button><el-button type="primary" @click="orderDialog = true">新建采购单</el-button></div>
    </header>

    <section class="summary-grid">
      <article><span>采购单</span><strong>{{ orders.length }}</strong></article>
      <article><span>计划中</span><strong>{{ countStatus('planned') }}</strong></article>
      <article><span>运输/部分到货</span><strong>{{ countStatus('ordered') + countStatus('partial') }}</strong></article>
      <article><span>已完成</span><strong>{{ countStatus('received') }}</strong></article>
    </section>

    <el-empty v-if="!orders.length" class="panel" description="暂无采购单" />
    <section v-for="order in orders" :key="order.id" class="panel order-card">
      <div class="order-head">
        <div>
          <el-tag :type="statusType(order.status)">{{ statusLabel(order.status) }}</el-tag>
          <h2>{{ order.platform || '采购计划' }} · {{ order.order_number || order.id.slice(0, 8) }}</h2>
          <p>{{ order.note || '无备注' }}</p>
        </div>
        <div class="order-total">
          <span>预计总价</span><strong>¥{{ Number(order.total_price || 0).toFixed(2) }}</strong>
          <div class="order-actions">
            <el-upload :show-file-list="false" accept=".PDF,.PNG,.JPG,.JPEG,.ZIP" :http-request="(options) => uploadOrderAttachment(order, options)">
              <el-button size="small" :loading="uploadingOrderId === order.id">订单附件</el-button>
            </el-upload>
            <el-button size="small" @click="openLine(order)">添加物料</el-button>
          </div>
        </div>
      </div>
      <el-table :data="order.lines" empty-text="尚未添加采购物料">
        <el-table-column prop="description" label="物料" min-width="220" />
        <el-table-column prop="component_id" label="元件 ID" width="100" />
        <el-table-column label="进度" width="150"><template #default="{ row }">{{ row.received_quantity }} / {{ row.ordered_quantity }}</template></el-table-column>
        <el-table-column prop="unit_price" label="单价" width="100" />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="120"><template #default="{ row }"><el-button v-if="row.status !== 'received'" size="small" @click="openReceipt(row)">到货入库</el-button></template></el-table-column>
      </el-table>
      <div v-if="orderAssets[order.id]?.length" class="attachment-list">
        <button v-for="asset in orderAssets[order.id]" :key="asset.id" type="button" @click="downloadOrderAsset(asset)">
          {{ asset.original_name }} <small>{{ formatBytes(asset.byte_size) }}</small>
        </button>
      </div>
    </section>

    <el-dialog v-model="orderDialog" title="新建采购计划/订单" width="500px">
      <el-form label-width="90px">
        <el-form-item label="平台"><el-input v-model="orderForm.platform" placeholder="立创商城 / 淘宝 / 1688" /></el-form-item>
        <el-form-item label="订单号"><el-input v-model="orderForm.order_number" placeholder="计划阶段可留空" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="orderForm.status"><el-option label="采购计划" value="planned" /><el-option label="已下单" value="ordered" /></el-select></el-form-item>
        <el-form-item label="备注"><el-input v-model="orderForm.note" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="orderDialog = false">取消</el-button><el-button type="primary" @click="saveOrder">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="lineDialog" title="添加采购物料" width="540px">
      <el-form label-width="100px">
        <el-form-item label="描述"><el-input v-model="lineForm.description" /></el-form-item>
        <el-form-item label="元件 ID"><el-input-number v-model="lineForm.component_id" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item v-if="libraryId" label="收货成员 ID"><el-input-number v-model="lineForm.receiver_user_id" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="采购数量"><el-input-number v-model="lineForm.ordered_quantity" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="单价"><el-input-number v-model="lineForm.unit_price" :min="0" :precision="4" style="width: 100%" /></el-form-item>
        <el-form-item label="采购链接"><el-input v-model="lineForm.purchase_url" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="lineDialog = false">取消</el-button><el-button type="primary" @click="saveLine">添加</el-button></template>
    </el-dialog>

    <el-dialog v-model="receiptDialog" title="到货入库" width="480px">
      <el-alert type="info" :closable="false">到货后会增加元件总库存，并建立可追溯库存批次和流水。</el-alert>
      <el-form label-width="90px">
        <el-form-item label="到货数量"><el-input-number v-model="receiptForm.quantity" :min="1" :max="remainingReceipt" style="width: 100%" /></el-form-item>
        <el-form-item label="位置"><el-input v-model="receiptForm.location" placeholder="可不填写" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="receiptForm.note" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="receiptDialog = false">取消</el-button><el-button type="primary" @click="saveReceipt">确认入库</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from '../elementApi'
import {
  addPurchaseLine,
  createPurchase,
  downloadEdaAsset,
  listEntityAssets,
  listPurchases,
  publishEdaAsset,
  receivePurchaseLine,
  stageEdaUpload
} from '../engineeringApi'

const route = useRoute()
const libraryId = computed(() => String(route.params.libraryId || ''))
const orders = ref([])
const orderAssets = ref({})
const uploadingOrderId = ref('')
const orderDialog = ref(false)
const lineDialog = ref(false)
const receiptDialog = ref(false)
const selectedOrder = ref(null)
const selectedLine = ref(null)
const orderForm = reactive({ platform: '', order_number: '', status: 'planned', currency: 'CNY', note: '' })
const lineForm = reactive({ description: '', component_id: null, receiver_user_id: null, ordered_quantity: 1, unit_price: null, purchase_url: '' })
const receiptForm = reactive({ quantity: 1, location: '', note: '' })
const remainingReceipt = computed(() => Math.max(1, Number(selectedLine.value?.ordered_quantity || 1) - Number(selectedLine.value?.received_quantity || 0)))

onMounted(load)
async function load() {
  try {
    orders.value = await listPurchases(libraryId.value)
    const entries = await Promise.all(orders.value.map(async (order) => {
      try { return [order.id, await listEntityAssets('purchase_order', order.id, libraryId.value)] }
      catch { return [order.id, []] }
    }))
    orderAssets.value = Object.fromEntries(entries)
  }
  catch (error) { ElMessage.error(error.response?.data?.detail || '读取采购数据失败') }
}
const countStatus = (status) => orders.value.filter((item) => item.status === status).length
const statusLabel = (status) => ({ planned: '计划', ordered: '已下单', partial: '部分到货', received: '已到货', cancelled: '已取消' })[status] || status
const statusType = (status) => ({ planned: 'info', ordered: 'primary', partial: 'warning', received: 'success', cancelled: 'danger' })[status] || 'info'
async function saveOrder() {
  await createPurchase(orderForm, libraryId.value)
  Object.assign(orderForm, { platform: '', order_number: '', status: 'planned', currency: 'CNY', note: '' })
  orderDialog.value = false
  await load()
}
function openLine(order) {
  selectedOrder.value = order
  Object.assign(lineForm, { description: '', component_id: null, receiver_user_id: null, ordered_quantity: 1, unit_price: null, purchase_url: '' })
  lineDialog.value = true
}
async function saveLine() {
  if (!lineForm.description.trim()) return ElMessage.warning('请填写物料描述')
  await addPurchaseLine(selectedOrder.value.id, lineForm, libraryId.value)
  lineDialog.value = false
  await load()
}
function openReceipt(line) {
  selectedLine.value = line
  Object.assign(receiptForm, { quantity: 1, location: '', note: '' })
  receiptDialog.value = true
}
async function saveReceipt() {
  await receivePurchaseLine(selectedLine.value.id, receiptForm, libraryId.value)
  receiptDialog.value = false
  ElMessage.success('到货已入库')
  await load()
}
async function uploadOrderAttachment(order, options) {
  uploadingOrderId.value = order.id
  try {
    const stage = await stageEdaUpload(options.file, libraryId.value)
    await publishEdaAsset({
      upload_token: stage.token,
      verification_status: 'raw',
      entity_type: 'purchase_order',
      entity_id: order.id,
      relation_type: 'invoice_or_order'
    }, libraryId.value)
    ElMessage.success('订单附件已上传')
    await load()
  } catch (error) { ElMessage.error(error.response?.data?.detail || '订单附件上传失败') }
  finally { uploadingOrderId.value = '' }
}
async function downloadOrderAsset(asset) {
  const blob = await downloadEdaAsset(asset.id, libraryId.value)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = asset.original_name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}
function exportPurchases() {
  const rows = [['采购单', '平台', '订单号', '物料', '元件 ID', '采购数量', '已到货', '单价', '链接', '状态']]
  for (const order of orders.value) {
    for (const line of order.lines || []) {
      rows.push([order.id, order.platform || '', order.order_number || '', line.description, line.component_id || '', line.ordered_quantity, line.received_quantity, line.unit_price || '', line.purchase_url || '', line.status])
    }
  }
  const csv = rows.map((row) => row.map((value) => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'purchase-list.csv'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<style scoped>
.engineering-page { display: grid; gap: 16px; }.page-head, .order-head { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }.head-actions { display: flex; gap: 8px; }
.page-head h1, .order-head h2 { margin: 5px 0; color: #17202a; }.page-head p, .order-head p { margin: 0; color: #667085; }
.eyebrow { color: #f97316; font-size: 12px; font-weight: 800; letter-spacing: .12em; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }.summary-grid article { padding: 15px; border: 1px solid #e4eaf2; border-radius: 16px; background: #fff; display: grid; gap: 4px; }
.summary-grid span { color: #667085; }.summary-grid strong { font-size: 24px; color: #17202a; }
.panel { padding: 16px; border: 1px solid #e4eaf2; border-radius: 16px; background: #fff; }
.order-total { display: grid; justify-items: end; gap: 6px; }.order-total span { color: #667085; }.order-total strong { font-size: 22px; color: #059669; }
.order-actions { display: flex; gap: 7px; }.attachment-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }.attachment-list button { padding: 7px 10px; border: 1px solid #e4eaf2; border-radius: var(--cw-radius-control); background: #f8fafc; color: #344054; cursor: pointer; }.attachment-list small { color: #667085; }
@media (max-width: 800px) { .page-head, .order-head { display: grid; }.summary-grid { grid-template-columns: repeat(2, 1fr); }.order-total { justify-items: start; } }
</style>
