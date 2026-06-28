<template>
  <section class="team-page">
    <div class="team-page-head">
      <div>
        <h1>{{ library?.name || 'PCB 库' }} · PCB</h1>
        <p>仅托管两张压缩实物图；Gerber、固件等大文件请放仓库链接。</p>
      </div>
      <el-button type="primary" :disabled="readonly" @click="openForm()">新增 PCB</el-button>
    </div>

    <el-alert v-if="readonly" class="readonly-banner" type="warning" :closable="false" show-icon title="当前为离线只读模式。" />

    <div class="team-panel team-toolbar">
      <el-input v-model="keyword" clearable placeholder="名称、主芯片、功能、题型、位置" style="max-width: 420px" />
      <el-select v-model="statusFilter" clearable placeholder="状态" style="width: 140px">
        <el-option v-for="status in statuses" :key="status" :label="status" :value="status" />
      </el-select>
      <el-button @click="load">刷新</el-button>
    </div>

    <div v-loading="loading" class="pcb-grid">
      <article v-for="row in filtered" :key="row.id" class="team-panel pcb-card">
        <div class="pcb-images">
          <protected-image :library-id="libraryId" :pcb-id="row.id" side="front" :enabled="Boolean(row.front_image_url)" alt="PCB 正面" />
          <protected-image :library-id="libraryId" :pcb-id="row.id" side="back" :enabled="Boolean(row.back_image_url)" alt="PCB 背面" />
        </div>
        <div class="pcb-head">
          <div><h2>{{ row.name }}</h2><p class="muted">{{ row.pcb_version || '无版本号' }} · {{ row.main_chip || '未填写主芯片' }}</p></div>
          <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
        </div>
        <p>{{ row.function_desc || '暂无功能说明' }}</p>
        <p class="muted">{{ row.voltage || '供电未填' }} · {{ row.interface_type || '接口未填' }} · 数量 {{ row.quantity }}</p>
        <p class="muted">适合题型：{{ row.suitable_task || '-' }} · 位置：{{ row.location || '-' }}</p>
        <div class="link-row">
          <a v-if="row.repository_url" :href="row.repository_url" target="_blank">仓库</a>
          <a v-if="row.schematic_url" :href="row.schematic_url" target="_blank">原理图</a>
          <a v-if="row.datasheet_url" :href="row.datasheet_url" target="_blank">数据手册</a>
        </div>
        <div class="team-toolbar">
          <el-button size="small" @click="openForm(row)">详情 / 编辑</el-button>
          <el-button size="small" type="danger" link :disabled="readonly" @click="remove(row)">删除</el-button>
        </div>
      </article>
    </div>
    <div v-if="!loading && !filtered.length" class="team-panel empty-state">暂无 PCB</div>

    <el-dialog v-model="dialog" :title="form.id ? '编辑 PCB' : '新增 PCB'" width="min(820px, 96vw)">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="版本"><el-input v-model="form.pcb_version" /></el-form-item>
          <el-form-item label="主芯片"><el-input v-model="form.main_chip" /></el-form-item>
          <el-form-item label="供电"><el-input v-model="form.voltage" /></el-form-item>
          <el-form-item label="接口"><el-input v-model="form.interface_type" /></el-form-item>
          <el-form-item label="适合题型"><el-input v-model="form.suitable_task" /></el-form-item>
          <el-form-item label="数量"><el-input-number v-model="form.quantity" :min="0" /></el-form-item>
          <el-form-item label="位置"><el-input v-model="form.location" /></el-form-item>
          <el-form-item label="状态"><el-select v-model="form.status"><el-option v-for="status in statuses" :key="status" :label="status" :value="status" /></el-select></el-form-item>
          <el-form-item label="仓库链接"><el-input v-model="form.repository_url" /></el-form-item>
          <el-form-item label="原理图链接"><el-input v-model="form.schematic_url" /></el-form-item>
          <el-form-item label="数据手册链接"><el-input v-model="form.datasheet_url" /></el-form-item>
        </div>
        <el-form-item label="功能"><el-input v-model="form.function_desc" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
        <div v-if="form.id" class="image-upload-grid">
          <label>正面实物图<input type="file" accept="image/jpeg,image/png,image/webp" @change="event => chooseImage(event, 'front')" /></label>
          <label>背面实物图<input type="file" accept="image/jpeg,image/png,image/webp" @change="event => chooseImage(event, 'back')" /></label>
        </div>
        <p v-if="form.id" class="muted">前端会自动压缩，服务端仍会拒绝超过 2MB 的单张图片。</p>
      </el-form>
      <template #footer><el-button type="primary" :loading="saving" :disabled="readonly" @click="save">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/elementApi'
import { onBeforeRouteLeave } from 'vue-router'
import { useRoute } from 'vue-router'
import ProtectedImage from '../components/ProtectedImage.vue'
import { createPcb, deletePcb, getLibrary, listPcbs, updatePcb, uploadPcbImage } from '../api'
import { clearLibrarySnapshots, readSnapshot, writeSnapshot } from '../cache'
import { teamState } from '../store'

const emptyForm = () => ({
  id: null, name: '', pcb_version: '', function_desc: '', main_chip: '', voltage: '',
  interface_type: '', suitable_task: '', quantity: 1, location: '', status: '待确认',
  repository_url: '', schematic_url: '', datasheet_url: '', remark: ''
})

const route = useRoute()
const libraryId = route.params.libraryId
const library = ref(null)
const rows = ref([])
const loading = ref(false)
const saving = ref(false)
const dialog = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const form = reactive(emptyForm())
const pendingImages = reactive({ front: null, back: null })
const statuses = ['可用', '待确认', '停用']
const readonly = computed(() => teamState.offlineReadonly)
let loadController = null
let loadSequence = 0
const filtered = computed(() => {
  const search = keyword.value.trim().toLowerCase()
  return rows.value.filter((row) => {
    if (statusFilter.value && row.status !== statusFilter.value) return false
    if (!search) return true
    return [row.name, row.main_chip, row.function_desc, row.interface_type, row.suitable_task, row.location]
      .some((value) => String(value || '').toLowerCase().includes(search))
  })
})

function statusType(status) {
  return status === '可用' ? 'success' : status === '停用' ? 'danger' : 'warning'
}

async function load() {
  const sequence = ++loadSequence
  loadController?.abort()
  loadController = new AbortController()
  loading.value = true
  try {
    const libraryData = await getLibrary(libraryId)
    if (sequence !== loadSequence) return
    library.value = libraryData
    teamState.activeLibrary = libraryData
    const pcbData = await listPcbs(libraryId, {}, { signal: loadController.signal })
    if (sequence !== loadSequence) return
    rows.value = pcbData.items || []
    await writeSnapshot(teamState.user?.id, libraryId, 'pcbs', rows.value)
  } catch (error) {
    if (error?.code === 'ERR_CANCELED' || sequence !== loadSequence) return
    if (error?.response?.status === 404) {
      await clearLibrarySnapshots(teamState.user?.id, libraryId)
      rows.value = []
      ElMessage.error(error?.response?.data?.detail || '你已不再是该团队器件库成员')
      return
    }
    const cached = await readSnapshot(teamState.user?.id, libraryId, 'pcbs')
    if (cached) {
      rows.value = cached.data
      teamState.offlineReadonly = true
      ElMessage.warning('已显示最近一次 PCB 离线缓存')
    } else if (!library.value) {
      ElMessage.error(error?.response?.data?.detail || 'PCB 加载失败')
    }
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

function openForm(row = null) {
  Object.assign(form, emptyForm(), row || {})
  pendingImages.front = null
  pendingImages.back = null
  dialog.value = true
}

async function imageToCompressedFile(file) {
  if (file.size <= 1.8 * 1024 * 1024 && ['image/jpeg', 'image/webp'].includes(file.type)) return file
  const bitmap = await createImageBitmap(file)
  let width = bitmap.width
  let height = bitmap.height
  const maxEdge = 1800
  if (Math.max(width, height) > maxEdge) {
    const ratio = maxEdge / Math.max(width, height)
    width = Math.round(width * ratio)
    height = Math.round(height * ratio)
  }
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  canvas.getContext('2d').drawImage(bitmap, 0, 0, width, height)
  bitmap.close()
  let quality = .86
  let blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', quality))
  while (blob.size > 2 * 1024 * 1024 && quality > .45) {
    quality -= .1
    blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', quality))
  }
  if (blob.size > 2 * 1024 * 1024) throw new Error('图片压缩后仍超过 2MB')
  return new File([blob], `${file.name.replace(/\.[^.]+$/, '')}.webp`, { type: 'image/webp' })
}

async function chooseImage(event, side) {
  const file = event.target.files?.[0]
  if (!file) return
  try {
    pendingImages[side] = await imageToCompressedFile(file)
    ElMessage.success(`${side === 'front' ? '正面' : '背面'}图片已压缩，保存时上传`)
  } catch (error) {
    ElMessage.error(error.message || '图片处理失败')
  }
}

function payload() {
  const copy = { ...form }
  delete copy.id
  delete copy.front_image_url
  delete copy.back_image_url
  delete copy.front_image_path
  delete copy.back_image_path
  delete copy.created_at
  delete copy.updated_at
  delete copy.created_by_user_id
  delete copy.updated_by_user_id
  delete copy.library_id
  return copy
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写 PCB 名称')
  saving.value = true
  try {
    const saved = form.id
      ? await updatePcb(libraryId, form.id, payload())
      : await createPcb(libraryId, payload())
    for (const side of ['front', 'back']) {
      if (pendingImages[side]) await uploadPcbImage(libraryId, saved.id, side, pendingImages[side])
    }
    dialog.value = false
    ElMessage.success('PCB 已保存')
    await load()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确认删除 PCB“${row.name}”？`, '删除 PCB', { type: 'warning' })
  await deletePcb(libraryId, row.id)
  await load()
}

onMounted(load)
onBeforeRouteLeave(() => loadController?.abort())
onBeforeUnmount(() => loadController?.abort())
</script>

<style scoped>
.pcb-card { display: flex; flex-direction: column; gap: 10px; }
.pcb-card h2 { margin: 0; font-size: 20px; }
.pcb-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.pcb-images { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.pcb-images :deep(img), .pcb-images :deep(.image-placeholder) { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: var(--cw-radius-control); min-height: 0; }
.link-row { display: flex; gap: 14px; }
.link-row a { color: #0b7769; font-weight: 700; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
.image-upload-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.image-upload-grid label { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: var(--cw-radius-control); background: #edf5f3; }
@media (max-width: 680px) {
  .form-grid, .image-upload-grid { grid-template-columns: 1fr; }
}
</style>
