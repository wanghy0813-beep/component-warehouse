<template>
  <el-popover
    v-model:visible="popoverVisible"
    placement="bottom-end"
    :width="310"
    trigger="click"
    popper-class="cw-account-popover"
    @show="refreshProfile"
  >
    <template #reference>
      <el-button class="account-trigger" text>
        <span class="account-avatar account-avatar-sm">
          <img v-if="showAvatarImage" :src="avatarSrc" :alt="displayName" @error="markAvatarFailed" />
          <span v-else>{{ initials }}</span>
        </span>
        <span>{{ displayName }}</span>
      </el-button>
    </template>
    <div class="profile-card">
      <span class="account-avatar profile-avatar">
        <img v-if="showAvatarImage" :src="avatarSrc" :alt="displayName" @error="markAvatarFailed" />
        <span v-else>{{ initials }}</span>
      </span>
      <div><strong>{{ displayName }}</strong><small>{{ displayUser?.phone || '未读取手机号' }}</small></div>
    </div>
    <div class="account-center-card">
      <strong>统一账号中心</strong>
      <small>个人资料、密码、手机号和登录会话已统一由 WXY LAB 账号中心管理。</small>
    </div>
    <div class="profile-actions">
      <el-button type="primary" @click="openSettings">账号管理</el-button>
      <el-button type="danger" plain @click="$emit('logout')">退出登录</el-button>
    </div>
  </el-popover>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { fetchAccountProfile, openAccountProfile, resolveAccountAvatarUrl } from '../../api/authSessionApi'

const props = defineProps({ user: { type: Object, default: null } })
const emit = defineEmits(['logout', 'user-updated'])
const popoverVisible = ref(false)
const accountUser = ref(null)
const avatarFailed = ref(false)
const displayUser = computed(() => ({ ...(props.user || {}), ...(accountUser.value || {}) }))
const displayName = computed(() => displayUser.value?.displayName || displayUser.value?.nickname || '用户')
const initials = computed(() => displayName.value.slice(0, 1).toUpperCase())
const avatarSrc = computed(() => resolveAccountAvatarUrl(displayUser.value?.avatarUrl || displayUser.value?.avatar_url || ''))
const showAvatarImage = computed(() => Boolean(avatarSrc.value) && !avatarFailed.value)

watch(avatarSrc, () => {
  avatarFailed.value = false
})

async function refreshProfile() {
  try {
    const user = await fetchAccountProfile()
    accountUser.value = user
    emit('user-updated', user)
  } catch {
    // The existing session card remains usable when the account service is briefly unavailable.
  }
}

function openSettings() {
  popoverVisible.value = false
  openAccountProfile()
}

function markAvatarFailed() {
  avatarFailed.value = true
}

onMounted(() => {
  window.addEventListener('cw-open-account-settings', openSettings)
  refreshProfile()
})
onBeforeUnmount(() => window.removeEventListener('cw-open-account-settings', openSettings))
</script>

<style scoped>
.account-trigger { max-width: 190px; display: inline-flex; gap: 8px; align-items: center; overflow: hidden; }
.account-trigger > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-avatar {
  flex: 0 0 auto;
  display: inline-grid;
  place-items: center;
  overflow: hidden;
  border-radius: 8px;
  background: #eef2f7;
  color: #344054;
  font-weight: 800;
  line-height: 1;
}
.account-avatar-sm {
  width: 30px;
  height: 30px;
  font-size: 13px;
}
.profile-avatar {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  font-size: 20px;
}
.account-avatar img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.profile-card { display: flex; gap: 12px; align-items: center; padding-bottom: 14px; }
.profile-card div { display: grid; gap: 4px; }
.profile-card small { color: #667085; }
.account-center-card {
  display: grid;
  gap: 6px;
  margin: 0 0 14px;
  padding: 12px;
  border: 1px solid #fed7aa;
  border-radius: 14px;
  background: linear-gradient(135deg, #fff7ed, #ffffff);
  color: #17202a;
}
.account-center-card small { color: #667085; line-height: 1.65; }
.profile-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
:global(.cw-account-popover.el-popper) { border-radius: 16px; color: #17202a; }
:global(.cw-account-popover .el-button) { border-radius: var(--cw-radius-control); }
@media (max-width: 680px) {
  .account-trigger { max-width: 126px; padding-inline: 6px; }
  .profile-actions { grid-template-columns: 1fr; }
}
</style>
