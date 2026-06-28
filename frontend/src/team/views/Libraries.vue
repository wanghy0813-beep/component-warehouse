<template>
  <section class="team-page">
    <div class="team-page-head">
      <div>
        <h1>我的团队器件库</h1>
        <p>团队共享项目、PCB 和器件信息；库存数量仍实时读取来源成员的个人库存。</p>
      </div>
      <el-button type="primary" :disabled="teamState.offlineReadonly" @click="dialog = true">创建团队器件库</el-button>
    </div>

    <el-alert v-if="teamState.offlineReadonly" class="readonly-banner" type="warning" :closable="false" show-icon title="当前为离线只读模式，联网并重新验证账号后可继续编辑。" />

    <div v-loading="loading" class="library-grid">
      <article v-for="(item, index) in libraries" :key="item.id" class="team-panel library-card" :class="`tone-${index % 4}`" @click="openLibrary(item)">
        <el-tag size="small" :type="item.role === 'captain' ? 'success' : item.role === 'editor' ? 'primary' : 'info'">{{ roleLabel(item.role) }}</el-tag>
        <h2>{{ item.name }}</h2>
        <p>{{ item.competition_type || '未填写团队方向' }}</p>
        <p class="muted">{{ item.description || '暂无简介' }}</p>
        <el-divider />
        <div class="team-toolbar muted">
          <span>{{ item.component_count }} 种元器件</span>
          <span>{{ item.pcb_count }} 块 PCB</span>
          <span>{{ item.member_count }} 名成员</span>
        </div>
      </article>
    </div>

    <div v-if="!loading && !libraries.length" class="team-panel empty-state">还没有团队器件库。创建一个，或者扫描队长分享的邀请二维码。</div>

    <el-dialog v-model="dialog" title="创建团队器件库" width="min(520px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="团队器件库名称" required><el-input v-model="form.name" maxlength="120" /></el-form-item>
        <el-form-item label="团队方向"><el-input v-model="form.competition_type" maxlength="120" placeholder="例如：机器人、电源、测量仪器" /></el-form-item>
        <el-form-item label="简介"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="1000" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../../shared/elementApi'
import { useRouter } from 'vue-router'
import { createLibrary, listLibraries } from '../api'
import { readSnapshot, writeSnapshot } from '../cache'
import { teamState } from '../store'

const router = useRouter()
const libraries = ref([])
const roleLabel = (role) => ({ captain: '队长', editor: '编辑者', viewer: '只读者', member: '编辑者' })[role] || role
const loading = ref(false)
const saving = ref(false)
const dialog = ref(false)
const form = reactive({ name: '', competition_type: '', description: '' })

async function load() {
  loading.value = true
  try {
    const onlineLibraries = await listLibraries()
    libraries.value = onlineLibraries
    teamState.offlineReadonly = false
    void writeSnapshot(teamState.user?.id, 'all', 'libraries', onlineLibraries)
  } catch (error) {
    const cached = await readSnapshot(teamState.user?.id, 'all', 'libraries')
    if (cached) {
      libraries.value = cached.data
      teamState.offlineReadonly = true
      ElMessage.warning('已显示最近一次团队器件库离线缓存')
    } else {
      ElMessage.error(error?.response?.data?.detail || '团队器件库加载失败')
    }
  } finally {
    loading.value = false
  }
}

function openLibrary(item) {
  teamState.activeLibrary = item
  router.push(`/library/${item.id}/components`)
}

async function submit() {
  if (!form.name.trim()) return ElMessage.warning('请填写团队器件库名称')
  saving.value = true
  try {
    const created = await createLibrary(form)
    dialog.value = false
    ElMessage.success('团队器件库已创建')
    openLibrary(created)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '创建失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
