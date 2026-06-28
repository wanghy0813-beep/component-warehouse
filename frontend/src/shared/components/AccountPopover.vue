<template>
  <el-popover
    v-model:visible="popoverVisible"
    placement="bottom-end"
    :width="280"
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
    <div class="profile-actions">
      <el-button @click="openSettings">账号设置</el-button>
      <el-button type="danger" plain @click="$emit('logout')">退出登录</el-button>
    </div>
  </el-popover>

  <el-drawer
    v-model="settingsVisible"
    title="个人账号"
    size="min(520px, 96vw)"
    append-to-body
    :z-index="3200"
  >
    <el-tabs v-model="activeTab">
      <el-tab-pane label="个人资料" name="profile">
        <el-form label-position="top">
          <el-form-item label="昵称"><el-input v-model="profile.displayName" maxlength="40" /></el-form-item>
          <el-form-item label="头像 HTTPS 地址"><el-input v-model="profile.avatarUrl" /></el-form-item>
          <el-button type="primary" :loading="busy" @click="saveProfile">保存资料</el-button>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="修改密码" name="password" lazy>
        <el-form label-position="top">
          <el-form-item label="当前密码"><el-input v-model="password.oldPassword" type="password" show-password /></el-form-item>
          <el-form-item label="新密码"><el-input v-model="password.newPassword" type="password" show-password placeholder="8-64 位" /></el-form-item>
          <security-code
            v-if="!localPasswordMode"
            v-model:code="password.code"
            :phone="user?.phone || ''"
            purpose="change_password"
          />
          <el-button type="primary" :loading="busy" @click="savePassword">修改密码</el-button>
        </el-form>
      </el-tab-pane>
      <el-tab-pane v-if="!localPasswordMode" label="更换手机号" name="phone" lazy>
        <el-form label-position="top">
          <el-form-item label="新手机号"><el-input v-model="phone.newPhone" maxlength="11" /></el-form-item>
          <security-code
            v-model:code="phone.code"
            :phone="phone.newPhone"
            purpose="change_phone"
          />
          <el-button type="primary" :loading="busy" @click="savePhone">更换手机号</el-button>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="会话" name="sessions">
        <el-button :loading="sessionsLoading" @click="loadSessions">刷新会话</el-button>
        <div v-for="session in sessions" :key="session.sessionId" class="session-row">
          <div>
            <strong>{{ session.clients?.join('、') || '当前会话' }}</strong>
            <small>{{ session.current ? '当前会话' : session.lastSeenAt || session.createdAt }}</small>
          </div>
          <el-tag v-if="session.current" type="success">当前</el-tag>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElAlert, ElButton, ElInput, ElMessage } from '../elementApi'
import {
  changeAccountPassword,
  changeAccountPhone,
  fetchCaptcha,
  fetchAccountProfile,
  isLocalPasswordAuth,
  listAccountSessions,
  sendSmsCode,
  updateAccountProfile
} from '../../api/authSessionApi'
import { accountErrorMessage } from '../accountErrors'
import { notifyAccountError } from '../accountFeedback'

const props = defineProps({ user: { type: Object, default: null } })
const emit = defineEmits(['logout', 'user-updated'])
const popoverVisible = ref(false)
const settingsVisible = ref(false)
const activeTab = ref('profile')
const busy = ref(false)
const sessionsLoading = ref(false)
const sessions = ref([])
const profile = reactive({ displayName: '', avatarUrl: '' })
const password = reactive({ oldPassword: '', newPassword: '', code: '' })
const phone = reactive({ newPhone: '', code: '' })
const displayName = computed(() => props.user?.displayName || props.user?.nickname || '用户')
const initials = computed(() => displayName.value.slice(0, 1).toUpperCase())
const localPasswordMode = computed(() => isLocalPasswordAuth())

async function refreshProfile() {
  try {
    const user = await fetchAccountProfile()
    emit('user-updated', user)
  } catch {
    // The existing session card remains usable when the account service is briefly unavailable.
  }
}

async function openSettings() {
  profile.displayName = displayName.value
  profile.avatarUrl = props.user?.avatarUrl || props.user?.avatar_url || ''
  popoverVisible.value = false
  await nextTick()
  settingsVisible.value = true
}

onMounted(() => window.addEventListener('cw-open-account-settings', openSettings))
onBeforeUnmount(() => window.removeEventListener('cw-open-account-settings', openSettings))

const SecurityCode = defineComponent({
  props: {
    phone: { type: String, default: '' },
    code: { type: String, default: '' },
    purpose: { type: String, required: true }
  },
  emits: ['update:code'],
  setup(childProps, { emit: childEmit }) {
    const captcha = reactive({ id: '', image: '', answer: '' })
    const sending = ref(false)
    const captchaLoading = ref(false)
    const captchaError = ref('')
    async function refreshCaptcha() {
      if (captchaLoading.value) return
      captchaLoading.value = true
      try {
        const data = await fetchCaptcha()
        captcha.id = data.captchaId
        captcha.image = data.imageDataUrl
        captcha.answer = ''
        captchaError.value = ''
      } catch (error) {
        captcha.id = ''
        captcha.image = ''
        captchaError.value = accountErrorMessage(error, '图片验证码加载失败，请重试')
      } finally {
        captchaLoading.value = false
      }
    }
    async function send() {
      if (!/^1\d{10}$/.test(childProps.phone)) return ElMessage.warning('请输入正确的手机号')
      if (!captcha.id || !captcha.answer) return ElMessage.warning('请填写图片验证码')
      sending.value = true
      try {
        await sendSmsCode({
          phone: childProps.phone,
          purpose: childProps.purpose,
          captchaId: captcha.id,
          captchaAnswer: captcha.answer
        })
        ElMessage.success('短信验证码已发送')
      } catch (error) {
        notifyAccountError(error, '验证码发送失败，请重试')
      } finally {
        sending.value = false
        await refreshCaptcha()
      }
    }
    refreshCaptcha()
    return () => h('div', { class: 'security-code' }, [
      captchaError.value
        ? h('div', { class: 'captcha-error' }, [
            h(ElAlert, { title: captchaError.value, type: 'error', closable: false, showIcon: true }),
            h(ElButton, { loading: captchaLoading.value, onClick: refreshCaptcha }, () => '重试')
          ])
        : null,
      h('div', { class: 'captcha-row' }, [
        h(ElInput, {
          modelValue: captcha.answer,
          placeholder: '图片验证码',
          'onUpdate:modelValue': (value) => { captcha.answer = value }
        }),
        captcha.image
          ? h('img', { src: captcha.image, onClick: refreshCaptcha })
          : h(ElButton, { loading: captchaLoading.value, onClick: refreshCaptcha }, () => '刷新')
      ]),
      h('div', { class: 'captcha-row' }, [
        h(ElInput, {
          modelValue: childProps.code,
          placeholder: '短信验证码',
          'onUpdate:modelValue': (value) => childEmit('update:code', value)
        }),
        h(ElButton, { loading: sending.value, onClick: send }, () => '发送验证码')
      ])
    ])
  }
})

async function saveProfile() {
  if (!profile.displayName.trim()) return ElMessage.warning('昵称不能为空')
  busy.value = true
  try {
    const user = await updateAccountProfile(profile)
    emit('user-updated', user)
    ElMessage.success('个人资料已更新')
  } catch (error) {
    notifyAccountError(error)
  } finally {
    busy.value = false
  }
}

async function savePassword() {
  if (password.newPassword.length < 8 || (!localPasswordMode.value && !password.code)) return ElMessage.warning('请填写必要信息和至少 8 位新密码')
  busy.value = true
  try {
    await changeAccountPassword(password)
    password.oldPassword = ''
    password.newPassword = ''
    password.code = ''
    ElMessage.success('密码已修改')
  } catch (error) {
    notifyAccountError(error)
  } finally {
    busy.value = false
  }
}

async function savePhone() {
  if (!/^1\d{10}$/.test(phone.newPhone) || !phone.code) return ElMessage.warning('请填写新手机号和验证码')
  busy.value = true
  try {
    const user = await changeAccountPhone(phone)
    emit('user-updated', user)
    phone.newPhone = ''
    phone.code = ''
    ElMessage.success('手机号已更换')
  } catch (error) {
    notifyAccountError(error)
  } finally {
    busy.value = false
  }
}

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const data = await listAccountSessions()
    sessions.value = data.sessions || []
  } catch (error) {
    notifyAccountError(error)
  } finally {
    sessionsLoading.value = false
  }
}
</script>

<style scoped>
.account-trigger { max-width: 190px; display: inline-flex; gap: 8px; align-items: center; overflow: hidden; }
.account-trigger > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.profile-card { display: flex; gap: 12px; align-items: center; padding-bottom: 14px; }
.profile-card div, .session-row div { display: grid; gap: 4px; }
.profile-card small, .session-row small { color: #667085; }
.profile-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.security-code { display: grid; gap: 10px; margin-bottom: 16px; }
.captcha-error { display: grid; gap: 8px; }
.captcha-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.captcha-row img { width: 116px; height: 40px; border-radius: var(--cw-radius-control); cursor: pointer; }
.session-row { display: flex; justify-content: space-between; gap: 12px; margin-top: 12px; padding: 12px; border: 1px solid #fed7aa; border-radius: 16px; }
:global(.cw-account-popover.el-popper) { border-radius: 16px; color: #17202a; }
:global(.cw-account-popover .el-button) { border-radius: var(--cw-radius-control); }
@media (max-width: 680px) {
  .account-trigger { max-width: 126px; padding-inline: 6px; }
  .profile-actions { grid-template-columns: 1fr; }
  .captcha-row { grid-template-columns: 1fr; }
  .captcha-row img { width: 100%; max-width: 180px; }
}
</style>
