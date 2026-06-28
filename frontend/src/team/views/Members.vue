<template>
  <section class="team-page">
    <div class="team-page-head">
      <div>
        <h1>成员管理</h1>
        <p>管理队长、编辑者和只读者权限。被移除成员需要使用新的邀请链接重新加入。</p>
      </div>
      <div class="team-toolbar">
        <el-button v-if="isCaptain" type="primary" plain :disabled="teamState.offlineReadonly" @click="openLibraryEditor">编辑团队器件库</el-button>
        <el-button @click="router.push('/')">切换团队器件库</el-button>
      </div>
    </div>

    <div v-if="isCaptain" class="team-panel invite-panel">
      <div class="invite-copy">
        <p class="invite-eyebrow">两种加入方式</p>
        <h2>扫码或点击链接加入</h2>
        <p class="muted">未登录成员会先完成统一账号登录或注册，随后自动回到本邀请页，手动确认后加入。</p>
        <div class="join-methods">
          <article class="join-method link-method">
            <span>普通链接</span>
            <strong>适合微信、QQ 或浏览器分享</strong>
            <el-input v-model="invite.url" readonly />
            <div class="team-toolbar">
              <el-button type="primary" @click="copyInvite">复制链接</el-button>
              <el-button @click="openInvite">打开邀请页</el-button>
              <el-button v-if="canShare" @click="shareInvite">系统分享</el-button>
            </div>
          </article>
          <article class="join-method qr-method">
            <span>二维码</span>
            <strong>适合现场扫码</strong>
            <p>邀请页只展示团队器件库名称和队长昵称，不泄露手机号和库存。</p>
          </article>
        </div>
        <el-button class="reset-button" type="danger" plain :disabled="teamState.offlineReadonly" @click="resetQr">重置全部邀请入口</el-button>
      </div>
      <div class="qr-frame"><img v-if="qrUrl" :src="qrUrl" alt="邀请二维码" /><span>扫描后进入确认加入页</span></div>
    </div>

    <div class="team-panel">
      <el-table v-loading="loading" :data="members">
        <el-table-column label="成员" min-width="180">
          <template #default="{ row }"><strong>{{ row.nickname }}</strong><div class="muted">手机尾号 {{ row.phone_last4 || '----' }}</div></template>
        </el-table-column>
        <el-table-column label="角色" width="100">
          <template #default="{ row }"><el-tag :type="row.role === 'captain' ? 'success' : row.role === 'editor' ? 'primary' : 'info'">{{ roleLabel(row.role) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'warning'">{{ row.status === 'active' ? '在队' : row.blocked ? '已移除·禁入' : '已移除' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="joined_at" label="加入时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.joined_at) }}</template>
        </el-table-column>
        <el-table-column v-if="isCaptain" label="操作" width="280">
          <template #default="{ row }">
            <el-select
              v-if="row.role !== 'captain' && row.status === 'active'"
              :model-value="row.role"
              size="small"
              style="width: 100px"
              :disabled="teamState.offlineReadonly"
              @change="changeRole(row, $event)"
            >
              <el-option label="编辑者" value="editor" />
              <el-option label="只读者" value="viewer" />
            </el-select>
            <el-button v-if="row.role !== 'captain' && row.status === 'active'" size="small" type="danger" plain :disabled="teamState.offlineReadonly" @click="remove(row)">移除</el-button>
            <el-button v-if="row.role !== 'captain' && row.blocked" size="small" :disabled="teamState.offlineReadonly" @click="unblock(row)">解除禁入</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="libraryDialog" title="编辑团队器件库" width="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="团队器件库名称" required>
          <el-input v-model="libraryForm.name" maxlength="120" />
        </el-form-item>
        <el-form-item label="团队方向">
          <el-input v-model="libraryForm.competition_type" maxlength="120" placeholder="例如：机器人、电源、测量仪器" />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="libraryForm.description" type="textarea" :rows="4" maxlength="1000" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="libraryDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingLibrary" @click="saveLibrary">保存修改</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/elementApi'
import { useRoute, useRouter } from 'vue-router'
import { getInvite, getInviteQr, getLibrary, listMembers, removeMember, resetInvite, unblockMember, updateLibrary, updateMemberRole } from '../api'
import { teamState } from '../store'

const route = useRoute()
const router = useRouter()
const libraryId = route.params.libraryId
const library = ref(null)
const members = ref([])
const loading = ref(false)
const invite = reactive({ url: '' })
const qrUrl = ref('')
const libraryDialog = ref(false)
const savingLibrary = ref(false)
const libraryForm = reactive({ name: '', competition_type: '', description: '' })
const isCaptain = computed(() => library.value?.role === 'captain')
const canShare = Boolean(navigator.share)
const roleLabel = (role) => ({ captain: '队长', editor: '编辑者', viewer: '只读者', member: '编辑者' })[role] || role

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

async function loadQr() {
  if (!isCaptain.value) return
  const [info, blob] = await Promise.all([getInvite(libraryId), getInviteQr(libraryId)])
  invite.url = info.url
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
  qrUrl.value = URL.createObjectURL(blob)
}

async function load() {
  loading.value = true
  try {
    ;[library.value, members.value] = await Promise.all([getLibrary(libraryId), listMembers(libraryId)])
    teamState.activeLibrary = library.value
    await loadQr()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '成员信息加载失败')
  } finally {
    loading.value = false
  }
}

async function copyInvite() {
  await navigator.clipboard.writeText(invite.url)
  ElMessage.success('邀请链接已复制')
}

function openInvite() {
  window.open(invite.url, '_blank', 'noopener')
}

async function shareInvite() {
  await navigator.share({
    title: `${library.value?.name || 'Component Warehouse'} 团队邀请`,
    text: `邀请你加入 ${library.value?.name || '团队器件库'}`,
    url: invite.url
  })
}

function openLibraryEditor() {
  Object.assign(libraryForm, {
    name: library.value?.name || '',
    competition_type: library.value?.competition_type || '',
    description: library.value?.description || ''
  })
  libraryDialog.value = true
}

async function saveLibrary() {
  if (!libraryForm.name.trim()) return ElMessage.warning('请填写团队器件库名称')
  savingLibrary.value = true
  try {
    library.value = await updateLibrary(libraryId, libraryForm)
    teamState.activeLibrary = library.value
    libraryDialog.value = false
    ElMessage.success('团队器件库资料已更新')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '团队器件库更新失败')
  } finally {
    savingLibrary.value = false
  }
}

async function resetQr() {
  await ElMessageBox.confirm('旧二维码会立即失效，确认重置？', '重置邀请')
  await resetInvite(libraryId)
  await loadQr()
  ElMessage.success('邀请二维码已重置')
}

async function remove(row) {
  await ElMessageBox.confirm(`移除 ${row.nickname}？该账号将不能用原二维码重新加入。`, '移除成员', { type: 'warning' })
  await removeMember(libraryId, row.id)
  await load()
}

async function changeRole(row, role) {
  await updateMemberRole(libraryId, row.id, role)
  row.role = role
  ElMessage.success('成员角色已更新')
}

async function unblock(row) {
  await ElMessageBox.confirm(
    `解除 ${row.nickname} 的禁入状态？原邀请仍不可使用，请随后重置并发送新邀请。`,
    '解除禁入'
  )
  await unblockMember(libraryId, row.id)
  await load()
  ElMessage.success('已解除禁入，请重置并发送新邀请')
}

onMounted(load)
onBeforeUnmount(() => {
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
})
</script>

<style scoped>
.invite-panel { display: grid; grid-template-columns: 1fr 250px; gap: 24px; align-items: center; overflow: hidden; background: linear-gradient(135deg, #ffffff 20%, #e9f8f5 100%); }
.invite-eyebrow { color: #0c8b78; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.invite-copy h2 { margin: 4px 0 8px; }
.join-methods { display: grid; grid-template-columns: 1.35fr .65fr; gap: 10px; margin: 18px 0; }
.join-method { display: flex; flex-direction: column; gap: 7px; padding: 14px; border-radius: 16px; }
.join-method span { width: fit-content; padding: 3px 9px; border-radius: 999px; font-size: 12px; font-weight: 800; }
.link-method { background: #eaf2ff; border: 1px solid #cfe0ff; }
.link-method span { color: #245fc6; background: #d7e6ff; }
.qr-method { color: #72501c; background: #fff5dc; border: 1px solid #f6dfa7; }
.qr-method span { color: #9a6614; background: #ffe8ae; }
.qr-method p { margin: 0; font-size: 13px; line-height: 1.6; }
.qr-frame { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 14px; border-radius: 16px; background: #fff; box-shadow: 0 16px 40px rgba(24, 91, 82, .12); }
.qr-frame img { width: 220px; height: 220px; }
.qr-frame span { color: #67817d; font-size: 12px; }
.reset-button { margin-top: 12px; }
@media (max-width: 680px) {
  .invite-panel { grid-template-columns: 1fr; }
  .join-methods { grid-template-columns: 1fr; }
  .qr-frame { justify-self: center; }
  .qr-frame img { width: 190px; height: 190px; }
}
</style>
