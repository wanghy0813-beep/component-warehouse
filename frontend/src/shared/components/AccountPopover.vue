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
        <el-avatar :size="30" :src="user?.avatarUrl || user?.avatar_url">
          {{ initials }}
        </el-avatar>
        <span>{{ displayName }}</span>
      </el-button>
    </template>
    <div class="profile-card">
      <el-avatar :size="48" :src="user?.avatarUrl || user?.avatar_url">{{ initials }}</el-avatar>
      <div><strong>{{ displayName }}</strong><small>{{ user?.phone || '未读取手机号' }}</small></div>
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
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fetchAccountProfile, openAccountProfile } from '../../api/authSessionApi'

const props = defineProps({ user: { type: Object, default: null } })
const emit = defineEmits(['logout', 'user-updated'])
const popoverVisible = ref(false)
const displayName = computed(() => props.user?.displayName || props.user?.nickname || '用户')
const initials = computed(() => displayName.value.slice(0, 1).toUpperCase())

async function refreshProfile() {
  try {
    const user = await fetchAccountProfile()
    emit('user-updated', user)
  } catch {
    // The existing session card remains usable when the account service is briefly unavailable.
  }
}

function openSettings() {
  popoverVisible.value = false
  openAccountProfile()
}

onMounted(() => window.addEventListener('cw-open-account-settings', openSettings))
onBeforeUnmount(() => window.removeEventListener('cw-open-account-settings', openSettings))
</script>

<style scoped>
.account-trigger { max-width: 190px; display: inline-flex; gap: 8px; align-items: center; overflow: hidden; }
.account-trigger > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
