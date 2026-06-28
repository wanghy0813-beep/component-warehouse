<template>
  <div class="auth-panel-page">
    <section class="auth-brand">
      <img v-if="BRAND_SHOW_LOGO" :src="logo" :alt="BRAND_SHORT" />
      <p>{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <span>{{ subtitle }}</span>
    </section>

    <el-card class="auth-card" shadow="never">
      <div v-if="serviceError" class="service-error">
        <el-alert :title="serviceError" type="error" :closable="false" show-icon />
        <el-button :loading="serviceChecking" @click="checkService">重新连接</el-button>
      </div>
      <el-tabs v-model="activeTab" stretch>
        <el-tab-pane :label="localPasswordMode ? '本地登录' : '密码登录'" name="password">
          <el-form label-position="top" @submit.prevent="submitPasswordLogin">
            <el-form-item :label="accountLabel">
              <el-input v-model="passwordForm.phone" :maxlength="localPasswordMode ? 20 : 11" autocomplete="username" :placeholder="localPasswordMode ? '请输入本地账号' : '请输入手机号'" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="passwordForm.password" type="password" show-password autocomplete="current-password" placeholder="请输入密码" />
            </el-form-item>
            <el-button type="primary" class="wide" :loading="busy" :disabled="!serviceAvailable || !termsAccepted" @click="submitPasswordLogin">登录</el-button>
          </el-form>
        </el-tab-pane>

        <el-tab-pane v-if="!localPasswordMode" label="短信登录" name="sms" lazy>
          <sms-code-form
            v-model:phone="smsForm.phone"
            v-model:code="smsForm.code"
            purpose="login"
            :busy="busy"
            :service-available="serviceAvailable"
            :terms-accepted="termsAccepted"
            @submit="submitSmsLogin"
          />
          <p class="hint">短信登录仅适用于已注册账号；新用户请先完成注册。</p>
        </el-tab-pane>

        <el-tab-pane v-if="registrationEnabled" label="注册" name="register" lazy>
          <el-form v-if="localPasswordMode" label-position="top" @submit.prevent="submitRegister">
            <el-form-item label="本地账号">
              <el-input v-model="registerForm.phone" maxlength="20" autocomplete="username" placeholder="3-20 位账号" />
            </el-form-item>
            <el-form-item label="昵称">
              <el-input v-model="registerForm.nickname" maxlength="30" placeholder="可选" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="registerForm.password" type="password" show-password autocomplete="new-password" placeholder="8-64 位" />
            </el-form-item>
            <el-button type="primary" class="wide" :loading="busy" :disabled="!serviceAvailable || !termsAccepted" @click="submitRegister">注册</el-button>
          </el-form>
          <sms-code-form
            v-else
            v-model:phone="registerForm.phone"
            v-model:code="registerForm.code"
            purpose="register"
            :busy="busy"
            :service-available="serviceAvailable"
            :terms-accepted="termsAccepted"
            @submit="submitRegister"
          >
            <el-form-item label="昵称">
              <el-input v-model="registerForm.nickname" maxlength="30" placeholder="可选" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="registerForm.password" type="password" show-password autocomplete="new-password" placeholder="8-64 位" />
            </el-form-item>
          </sms-code-form>
        </el-tab-pane>

        <el-tab-pane v-if="!localPasswordMode" label="重置密码" name="reset" lazy>
          <sms-code-form
            v-model:phone="resetForm.phone"
            v-model:code="resetForm.code"
            purpose="reset_password"
            submit-label="重置密码"
            :busy="busy"
            :service-available="serviceAvailable"
            :terms-accepted="termsAccepted"
            @submit="submitReset"
          >
            <el-form-item label="新密码">
              <el-input v-model="resetForm.newPassword" type="password" show-password autocomplete="new-password" placeholder="8-64 位" />
            </el-form-item>
          </sms-code-form>
        </el-tab-pane>
      </el-tabs>
      <div class="terms-box">
        <el-checkbox v-model="termsAccepted">
          我已阅读并同意
          <button type="button" @click.stop="termsDialog = true">使用条款</button>
          和
          <button type="button" @click.stop="privacyDialog = true">隐私协议</button>
        </el-checkbox>
        <small>系统会记录必要的登录、操作和功能使用埋点，用于安全审计和改进界面，不记录密码、令牌或敏感工程文件内容。</small>
      </div>
    </el-card>

    <el-dialog v-model="termsDialog" :title="`${BRAND_NAME} 使用条款`" width="min(620px, 94vw)" append-to-body>
      <div class="policy-text">
        <p>本系统用于个人和团队元器件库存、项目 BOM、标签打印和工程记录管理。请仅上传你有权保存和使用的资料。</p>
        <p>你需要对录入的元器件参数、封装、BOM 匹配和替代料选择进行人工确认；系统和 AI 只提供辅助建议，不自动替代工程判断。</p>
        <p>禁止上传恶意文件、侵犯他人权益的资料，或使用系统进行未授权访问、批量攻击和数据抓取。</p>
      </div>
    </el-dialog>

    <el-dialog v-model="privacyDialog" :title="`${BRAND_NAME} 隐私协议`" width="min(620px, 94vw)" append-to-body>
      <div class="policy-text">
        <p>系统会保存账号手机号、昵称、头像、登录时间、元器件数据、项目数据、上传文件路径和必要的操作日志。</p>
        <p>界面埋点仅用于统计常用功能、定位故障和优化体验，默认记录页面、入口、功能名、目标 ID、时间和设备宽度等非敏感信息。</p>
        <p>密码和令牌由统一账号系统管理，本系统不保存明文密码；你可以通过账号设置退出登录或修改资料。</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { ElAlert, ElButton, ElInput, ElMessage } from '../shared/elementApi'
import logo from '../assets/brand-logo.png'
import {
  checkAccountHealth,
  fetchCaptcha,
  getAuthRuntimeConfig,
  isLocalPasswordAuth,
  loginWithPassword,
  loginWithSms,
  registerWithPassword,
  resetAuthPassword,
  sendSmsCode
} from '../api/authSessionApi'
import { accountErrorMessage, isAccountServiceUnavailable } from '../shared/accountErrors'
import { notifyAccountError } from '../shared/accountFeedback'
import { BRAND_NAME, BRAND_SHORT, BRAND_SHOW_LOGO } from '../shared/branding'

defineProps({
  title: { type: String, default: BRAND_NAME },
  eyebrow: { type: String, default: BRAND_SHORT },
  subtitle: { type: String, default: '使用账号登录' }
})

const emit = defineEmits(['authenticated'])
const activeTab = ref('password')
const busy = ref(false)
const serviceChecking = ref(false)
const serviceAvailable = ref(true)
const serviceError = ref('')
const passwordForm = reactive({ phone: '', password: '' })
const smsForm = reactive({ phone: '', code: '' })
const registerForm = reactive({ phone: '', code: '', nickname: '', password: '' })
const resetForm = reactive({ phone: '', code: '', newPassword: '' })
const termsAccepted = ref(localStorage.getItem('cw_terms_accepted') === '1')
const termsDialog = ref(false)
const privacyDialog = ref(false)
const localPasswordMode = computed(() => isLocalPasswordAuth())
const registrationEnabled = computed(() => getAuthRuntimeConfig().registrationEnabled)
const accountLabel = computed(() => localPasswordMode.value ? '本地账号' : '手机号')

async function checkService() {
  if (serviceChecking.value) return
  serviceChecking.value = true
  try {
    await checkAccountHealth()
    serviceAvailable.value = true
    serviceError.value = ''
  } catch (error) {
    serviceAvailable.value = false
    serviceError.value = accountErrorMessage(error, '统一账号服务暂时不可用，请稍后重试')
  } finally {
    serviceChecking.value = false
  }
}

onMounted(checkService)

const SmsCodeForm = defineComponent({
  name: 'SmsCodeForm',
  props: {
    phone: { type: String, default: '' },
    code: { type: String, default: '' },
    purpose: { type: String, required: true },
    busy: Boolean,
    serviceAvailable: { type: Boolean, default: true },
    termsAccepted: { type: Boolean, default: false },
    submitLabel: { type: String, default: '验证并继续' }
  },
  emits: ['update:phone', 'update:code', 'submit'],
  setup(props, { emit: childEmit, slots }) {
    const captcha = reactive({ id: '', image: '', answer: '' })
    const sending = ref(false)
    const captchaLoading = ref(false)
    const captchaError = ref('')
    const countdown = ref(0)
    let timer = null

    async function refreshCaptcha() {
      if (!props.serviceAvailable || captchaLoading.value) return
      captchaLoading.value = true
      try {
        const data = await fetchCaptcha()
        captcha.id = data.captchaId || ''
        captcha.image = data.imageDataUrl || ''
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

    async function sendCode() {
      if (!/^1\d{10}$/.test(props.phone)) {
        ElMessage.warning('请输入正确的 11 位手机号')
        return
      }
      if (!props.termsAccepted) {
        ElMessage.warning('请先阅读并同意使用条款和隐私协议')
        return
      }
      if (!captcha.id || !captcha.answer.trim()) {
        ElMessage.warning('请先填写图片验证码')
        return
      }
      sending.value = true
      try {
        await sendSmsCode({
          phone: props.phone,
          purpose: props.purpose,
          captchaId: captcha.id,
          captchaAnswer: captcha.answer.trim()
        })
        ElMessage.success('短信验证码已发送')
        countdown.value = 60
        clearInterval(timer)
        timer = setInterval(() => {
          countdown.value -= 1
          if (countdown.value <= 0) clearInterval(timer)
        }, 1000)
      } catch (error) {
        notifyAccountError(error, '验证码发送失败，请重试')
      } finally {
        sending.value = false
        await refreshCaptcha()
      }
    }

    refreshCaptcha()

    return () =>
      h('form', { onSubmit: (event) => { event.preventDefault(); childEmit('submit') } }, [
        h('div', { class: 'el-form-item is-required asterisk-left' }, [
          h('label', { class: 'el-form-item__label' }, '手机号'),
          h('div', { class: 'el-form-item__content' }, [
            h(ElInput, {
              modelValue: props.phone,
              maxlength: 11,
              placeholder: '请输入手机号',
              'onUpdate:modelValue': (value) => childEmit('update:phone', value)
            })
          ])
        ]),
        captchaError.value
          ? h('div', { class: 'captcha-error' }, [
              h(ElAlert, { title: captchaError.value, type: 'error', closable: false, showIcon: true }),
              h(ElButton, { loading: captchaLoading.value, onClick: refreshCaptcha }, () => '重试')
            ])
          : null,
        h('div', { class: 'captcha-row' }, [
          h(ElInput, {
            modelValue: captcha.answer,
            maxlength: 4,
            placeholder: '图片验证码',
            'onUpdate:modelValue': (value) => { captcha.answer = value }
          }),
          captcha.image
            ? h('img', { src: captcha.image, alt: '图片验证码', onClick: refreshCaptcha })
            : h(ElButton, { loading: captchaLoading.value, disabled: !props.serviceAvailable, onClick: refreshCaptcha }, () => '刷新')
        ]),
        h('div', { class: 'code-row' }, [
          h(ElInput, {
            modelValue: props.code,
            maxlength: 6,
            placeholder: '短信验证码',
            'onUpdate:modelValue': (value) => childEmit('update:code', value)
          }),
          h(ElButton, {
            loading: sending.value,
            disabled: !props.serviceAvailable || !props.termsAccepted || countdown.value > 0,
            onClick: sendCode
          }, () => countdown.value > 0 ? `${countdown.value}s` : '发送验证码')
        ]),
        slots.default?.(),
        h(ElButton, {
          type: 'primary',
          class: 'wide',
          loading: props.busy,
          disabled: !props.serviceAvailable || !props.termsAccepted,
          onClick: () => childEmit('submit')
        }, () => props.submitLabel)
      ])
  }
})

async function runAuth(action, successText = '登录成功') {
  if (busy.value || !serviceAvailable.value) return null
  if (!termsAccepted.value) {
    ElMessage.warning('请先阅读并同意使用条款和隐私协议')
    return null
  }
  busy.value = true
  try {
    const data = await action()
    localStorage.setItem('cw_terms_accepted', '1')
    ElMessage.success(successText)
    if (data?.token) emit('authenticated', data)
    return data
  } catch (error) {
    if (isAccountServiceUnavailable(error)) {
      serviceAvailable.value = false
      serviceError.value = accountErrorMessage(error)
    }
    notifyAccountError(error, '账号操作失败，请稍后重试')
    return null
  } finally {
    busy.value = false
  }
}

function submitPasswordLogin() {
  if (!passwordForm.phone || !passwordForm.password) return ElMessage.warning(`请填写${accountLabel.value}和密码`)
  runAuth(() => loginWithPassword(passwordForm.phone.trim(), passwordForm.password))
}

function submitSmsLogin() {
  if (!smsForm.phone || !smsForm.code) return ElMessage.warning('请填写手机号和短信验证码')
  runAuth(() => loginWithSms(smsForm.phone.trim(), smsForm.code.trim()))
}

function submitRegister() {
  if (localPasswordMode.value && (!registerForm.phone || registerForm.password.length < 8)) {
    return ElMessage.warning('请填写本地账号和至少 8 位密码')
  }
  if (!localPasswordMode.value && (!registerForm.phone || !registerForm.code || registerForm.password.length < 8)) {
    return ElMessage.warning('请填写手机号、短信验证码和至少 8 位密码')
  }
  runAuth(() => registerWithPassword({
    phone: registerForm.phone.trim(),
    code: registerForm.code.trim(),
    nickname: registerForm.nickname.trim(),
    password: registerForm.password
  }), '注册成功')
}

async function submitReset() {
  if (!resetForm.phone || !resetForm.code || resetForm.newPassword.length < 8) {
    return ElMessage.warning('请填写手机号、短信验证码和至少 8 位新密码')
  }
  const data = await runAuth(() => resetAuthPassword({
    phone: resetForm.phone.trim(),
    code: resetForm.code.trim(),
    newPassword: resetForm.newPassword
  }), '密码已重置，请重新登录')
  if (data) {
    passwordForm.phone = resetForm.phone
    activeTab.value = 'password'
  }
}
</script>

<style scoped>
.auth-panel-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(280px, 420px) minmax(320px, 480px);
  place-content: center;
  gap: 24px;
  padding: 24px;
  background: radial-gradient(circle at top left, #ffedd5, transparent 42%), #fffaf5;
}

.auth-brand,
.auth-card {
  border-radius: 16px;
}

.auth-brand {
  padding: 52px 42px;
  color: #7c2d12;
  background: linear-gradient(145deg, rgba(255, 255, 255, .96), rgba(255, 247, 237, .96));
  border: 1px solid #fed7aa;
}

.auth-brand img {
  width: min(280px, 100%);
  height: 112px;
  object-fit: contain;
  filter: drop-shadow(0 12px 20px rgba(20, 132, 116, .16));
}

.auth-brand p {
  margin: 18px 0 0;
  letter-spacing: .18em;
  font-weight: 800;
  color: #f97316;
  font-size: 13px;
}

.auth-brand h1 {
  margin: 14px 0 10px;
  font-size: clamp(28px, 4vw, 44px);
}

.auth-brand span,
.hint {
  color: #64748b;
}

.auth-card {
  padding: 10px;
}

.wide {
  width: 100%;
}

.service-error,
.captcha-error {
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
}

.captcha-row,
.code-row {
  display: grid;
  grid-template-columns: 1fr 126px;
  gap: 10px;
  margin-bottom: 18px;
}

.captcha-row img {
  width: 126px;
  height: 40px;
  object-fit: cover;
  border: 1px solid #dcdfe6;
  border-radius: var(--cw-radius-control);
  cursor: pointer;
}

.hint {
  margin: 12px 0 0;
  font-size: 13px;
}

.terms-box {
  display: grid;
  gap: 6px;
  margin-top: 14px;
  padding: 12px;
  border: 1px solid #fed7aa;
  border-radius: var(--cw-radius-control);
  background: #fff7ed;
}

.terms-box button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #ea580c;
  font: inherit;
  font-weight: 800;
  cursor: pointer;
}

.terms-box small,
.policy-text {
  color: #64748b;
  line-height: 1.65;
}

.policy-text p {
  margin: 0 0 10px;
}

@media (max-width: 760px) {
  .auth-panel-page {
    display: block;
    padding: 14px;
  }

  .auth-brand {
    padding: 22px;
    margin-bottom: 14px;
  }

  .auth-brand img {
    width: 190px;
    height: 78px;
  }

  .auth-brand h1 {
    margin: 10px 0 4px;
  }

  .auth-brand p {
    margin-top: 10px;
  }
}
</style>
