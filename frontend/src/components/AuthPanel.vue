<template>
  <div class="auth-panel-page notranslate" lang="zh-CN" translate="no">
    <div class="auth-ambient" aria-hidden="true"></div>
    <section class="auth-brand">
      <div class="auth-brand-top">
        <img class="auth-project-icon" :src="appIcon" alt="" />
        <img v-if="BRAND_SHOW_LOGO" class="auth-logo" :src="logo" :alt="BRAND_SHORT" />
      </div>
      <p>{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <span>{{ subtitle }}</span>
      <div class="auth-workbench" aria-label="工作台预览">
        <div class="workbench-toolbar">
          <i></i><i></i><i></i>
        </div>
        <div class="workbench-grid">
          <article>
            <small>RES-00000024</small>
            <strong>10kΩ</strong>
            <span>0805 · C17414</span>
          </article>
          <article>
            <small>CAP-00000017</small>
            <strong>100nF</strong>
            <span>X7R · 50V</span>
          </article>
          <article>
            <small>BOM 匹配</small>
            <strong>18 / 20</strong>
            <span>2 项待确认</span>
          </article>
        </div>
        <div class="label-strip">
          <div class="qr-mark"></div>
          <div><b>UNC-00000078</b><span>扫码定位 · 标签打印</span></div>
        </div>
      </div>
    </section>

    <el-card class="auth-card" shadow="never">
      <div class="auth-card-head">
        <strong>统一登录</strong>
        <small>使用 WXY LAB 统一账号进入当前工作台</small>
      </div>

      <div v-if="serviceError" class="service-error">
        <el-alert :title="serviceError" type="error" :closable="false" show-icon />
        <el-button :loading="serviceChecking" @click="checkService">重新连接</el-button>
      </div>

      <div class="sso-login-block">
        <el-button
          type="primary"
          class="sso-button"
          :loading="busy"
          :disabled="!canStartSso"
          @click="submitSsoLogin"
        >
          <span>使用 WXY LAB 统一登录</span>
        </el-button>
        <small>{{ ssoHint }}</small>
      </div>

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
        <p>密码、手机号、资料和登录会话由 WXY LAB 统一账号中心管理，本系统只保存完成业务所需的账号映射和会话状态。</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElAlert, ElButton, ElMessage } from '../shared/elementApi'
import logo from '../assets/brand-logo.png'
import appIcon from '../assets/generated/cw-app-icon.png'
import {
  checkAccountHealth,
  getAuthRuntimeConfig,
  startSsoLogin
} from '../api/authSessionApi'
import { accountErrorMessage, isAccountServiceUnavailable } from '../shared/accountErrors'
import { notifyAccountError } from '../shared/accountFeedback'
import { BRAND_NAME, BRAND_SHORT, BRAND_SHOW_LOGO } from '../shared/branding'

defineProps({
  title: { type: String, default: BRAND_NAME },
  eyebrow: { type: String, default: BRAND_SHORT },
  subtitle: { type: String, default: '使用统一账号登录' }
})

const busy = ref(false)
const serviceChecking = ref(false)
const serviceAvailable = ref(true)
const serviceError = ref('')
const termsAccepted = ref(localStorage.getItem('cw_terms_accepted') === '1')
const termsDialog = ref(false)
const privacyDialog = ref(false)
const ssoReady = ref(Boolean(getAuthRuntimeConfig().ssoEnabled))
const canStartSso = computed(() => serviceAvailable.value && ssoReady.value && termsAccepted.value)
const ssoHint = computed(() => {
  if (!ssoReady.value) return '统一账号 SSO 暂未配置，请联系管理员检查部署配置。'
  if (!serviceAvailable.value) return '统一账号中心暂时不可用，请稍后重试。'
  if (!termsAccepted.value) return '请先阅读并同意使用条款和隐私协议。'
  return '将跳转到 WXY LAB 统一账号中心完成安全登录。'
})

async function checkService() {
  if (serviceChecking.value) return
  serviceChecking.value = true
  try {
    await checkAccountHealth()
    ssoReady.value = Boolean(getAuthRuntimeConfig().ssoEnabled)
    serviceAvailable.value = true
    serviceError.value = ssoReady.value ? '' : '统一账号 SSO 暂未配置，请联系管理员检查部署配置'
  } catch (error) {
    serviceAvailable.value = false
    serviceError.value = accountErrorMessage(error, '统一账号服务暂时不可用，请稍后重试')
  } finally {
    serviceChecking.value = false
  }
}

onMounted(checkService)

async function submitSsoLogin() {
  if (busy.value) return
  if (!termsAccepted.value) {
    ElMessage.warning('请先阅读并同意使用条款和隐私协议')
    return
  }
  ssoReady.value = Boolean(getAuthRuntimeConfig().ssoEnabled)
  if (!ssoReady.value) {
    ElMessage.error('统一账号 SSO 暂未配置')
    return
  }
  if (!serviceAvailable.value) return
  busy.value = true
  try {
    localStorage.setItem('cw_terms_accepted', '1')
    await startSsoLogin(window.location.href)
  } catch (error) {
    busy.value = false
    if (isAccountServiceUnavailable(error)) {
      serviceAvailable.value = false
      serviceError.value = accountErrorMessage(error)
    }
    notifyAccountError(error, '统一账号登录暂时不可用，请稍后重试')
  }
}
</script>

<style scoped>
.auth-panel-page {
  position: relative;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  margin: 0 auto;
  min-height: 100%;
  display: grid;
  grid-template-columns: minmax(0, 560px) minmax(0, 510px);
  justify-content: center;
  align-content: center;
  gap: 18px;
  padding: clamp(22px, 4vh, 54px) max(24px, calc((100vw - 1180px) / 2));
  overflow: hidden;
  isolation: isolate;
  background:
    linear-gradient(115deg, rgba(255, 247, 237, .90) 0%, rgba(255, 255, 255, .96) 44%, rgba(239, 246, 255, .92) 100%),
    #f8fafc;
}

.auth-ambient {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
  opacity: .78;
  background:
    linear-gradient(90deg, rgba(249, 115, 22, .08) 1px, transparent 1px),
    linear-gradient(0deg, rgba(37, 99, 235, .07) 1px, transparent 1px),
    linear-gradient(116deg, transparent 0 46%, rgba(249, 115, 22, .08) 47% 48%, transparent 49%),
    linear-gradient(296deg, transparent 0 54%, rgba(37, 99, 235, .07) 55% 56%, transparent 57%);
  background-size: 64px 64px, 64px 64px, 420px 420px, 520px 520px;
}

.auth-ambient::before,
.auth-ambient::after {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(118deg, transparent 0 15%, rgba(249, 115, 22, .09) 15.4% 16.2%, transparent 16.8% 52%, rgba(37, 99, 235, .07) 52.4% 53.2%, transparent 54%),
    linear-gradient(118deg, transparent 0 66%, rgba(249, 115, 22, .07) 66.4% 67.1%, transparent 68%);
  opacity: .74;
}

.auth-ambient::after {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, .45), transparent 18%, transparent 82%, rgba(255, 255, 255, .50)),
    linear-gradient(90deg, rgba(255, 255, 255, .52), transparent 20%, transparent 80%, rgba(255, 255, 255, .58));
  opacity: 1;
}

.auth-brand,
.auth-card {
  position: relative;
  z-index: 1;
  min-width: 0;
  border-radius: var(--cw-radius-card);
  box-shadow: 0 18px 48px rgba(15, 23, 42, .08);
  animation: auth-card-enter .42s ease-out both;
  animation-iteration-count: 1;
}

.auth-card {
  animation-delay: .08s;
}

@keyframes auth-card-enter {
  from {
    opacity: 0;
    transform: translate3d(0, 10px, 0);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0);
  }
}

.auth-brand {
  display: grid;
  align-content: start;
  gap: clamp(12px, 2vh, 22px);
  min-height: clamp(420px, 58vh, 520px);
  padding: clamp(24px, 3vh, 34px);
  color: #0f172a;
  background: #fff;
  border: 1px solid #dbeafe;
}

.auth-brand-top {
  display: flex;
  align-items: center;
  gap: 16px;
}

.auth-logo {
  width: min(250px, calc(100% - 92px));
  height: 76px;
  object-fit: contain;
  filter: drop-shadow(0 12px 20px rgba(14, 116, 255, .12));
}

.auth-brand .auth-project-icon {
  width: 62px;
  height: 62px;
  border-radius: var(--cw-radius-card);
  display: block;
  flex: 0 0 auto;
}

.auth-brand p {
  margin: clamp(10px, 2.2vh, 28px) 0 0;
  letter-spacing: .12em;
  font-weight: 800;
  color: #2563eb;
  font-size: 13px;
}

.auth-brand h1 {
  margin: 14px 0 10px;
  color: #020617;
  font-size: clamp(30px, 4vw, 46px);
  line-height: 1.05;
  letter-spacing: 0;
}

.auth-brand span {
  color: #64748b;
}

.auth-workbench {
  display: grid;
  gap: 10px;
  margin-top: auto;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: var(--cw-radius-card);
  background:
    linear-gradient(180deg, rgba(248, 250, 252, .94), rgba(255, 255, 255, .98)),
    #fff;
}

.workbench-toolbar {
  display: flex;
  gap: 6px;
}

.workbench-toolbar i {
  width: 34px;
  height: 6px;
  border-radius: 999px;
  background: linear-gradient(90deg, #fb923c, #2563eb);
  opacity: .45;
}

.workbench-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.workbench-grid article,
.label-strip {
  min-width: 0;
  border: 1px solid #dbeafe;
  border-radius: var(--cw-radius-control);
  background: #fff;
}

.workbench-grid article {
  display: grid;
  gap: 3px;
  padding: 10px;
  transition: transform .18s ease, border-color .18s ease;
}

.workbench-grid article:hover {
  border-color: #bfdbfe;
  transform: translateY(-1px);
}

.workbench-grid small,
.label-strip span {
  color: #64748b;
  font-size: 11px;
}

.workbench-grid strong {
  color: #0f172a;
  font-size: 18px;
}

.workbench-grid span,
.label-strip b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-grid span {
  color: #475569;
  font-size: 12px;
}

.label-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
}

.qr-mark {
  position: relative;
  overflow: hidden;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  border: 5px solid #0f172a;
  border-radius: 6px;
  background:
    linear-gradient(90deg, #0f172a 20%, transparent 0 40%, #0f172a 0 60%, transparent 0),
    linear-gradient(0deg, #0f172a 20%, transparent 0 40%, #0f172a 0 60%, transparent 0),
    #fff;
  background-size: 12px 12px;
}

.qr-mark::after {
  content: "";
  position: absolute;
  left: 4px;
  right: 4px;
  top: 7px;
  height: 2px;
  border-radius: 999px;
  background: rgba(251, 146, 60, .85);
  opacity: 0;
  animation: qr-scan-blip 4.8s ease-in-out infinite;
}

@keyframes qr-scan-blip {
  0%, 72%, 100% {
    opacity: 0;
    transform: translateY(0);
  }
  78% {
    opacity: .9;
  }
  92% {
    opacity: .9;
    transform: translateY(18px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .auth-brand,
  .auth-card,
  .qr-mark::after {
    animation: none;
  }
}

.label-strip > div:last-child {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.auth-card {
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, .94);
}

.auth-card :deep(.el-card__body) {
  min-width: 0;
  min-height: 100%;
  display: grid;
  align-content: center;
  gap: clamp(16px, 2.2vh, 24px);
  padding: clamp(30px, 4vh, 48px);
}

.auth-card-head {
  display: grid;
  gap: 10px;
}

.auth-card-head strong {
  color: #0f172a;
  font-size: 28px;
  line-height: 1.12;
}

.auth-card-head small {
  color: #64748b;
  line-height: 1.55;
}

.service-error {
  display: grid;
  gap: 10px;
}

.sso-login-block {
  display: grid;
  gap: 12px;
  padding: 0;
}

.sso-button {
  width: 100%;
  min-height: 60px;
  font-weight: 850;
  overflow: hidden;
  border: 0;
  background: linear-gradient(135deg, #fb923c, #ea580c);
  box-shadow: 0 16px 30px rgba(234, 88, 12, .22);
}

.sso-button:hover,
.sso-button:focus {
  background: linear-gradient(135deg, #f97316, #c2410c);
}

.sso-button :deep(span) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
}

.sso-login-block small {
  color: #64748b;
  text-align: center;
  line-height: 1.6;
}

.terms-box {
  display: grid;
  gap: 10px;
  padding: 18px 2px 0;
  border-top: 1px solid #fed7aa;
  background: transparent;
}

.terms-box :deep(.el-checkbox) {
  align-items: flex-start;
  color: #475569;
  font-weight: 700;
  line-height: 1.5;
  white-space: normal;
}

.terms-box :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: #f97316;
  border-color: #f97316;
}

.terms-box :deep(.el-checkbox__input.is-checked + .el-checkbox__label) {
  color: #475569;
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
    width: 100%;
    min-width: 0;
    grid-template-columns: minmax(0, 1fr);
    display: grid;
    align-content: start;
    place-content: start stretch;
    gap: 12px;
    padding: max(12px, env(safe-area-inset-top)) max(12px, env(safe-area-inset-right)) max(14px, env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left));
    overflow-x: hidden;
  }

  .auth-brand {
    min-width: 0;
    padding: 18px;
    min-height: 0;
  }

  .auth-brand,
  .auth-card {
    width: 100%;
    box-sizing: border-box;
  }

  .auth-card {
    min-width: 0;
  }

  .auth-card :deep(.el-card__body) {
    padding: 18px;
    gap: 16px;
  }

  .auth-brand-top {
    gap: 10px;
    min-width: 0;
  }

  .auth-logo {
    width: min(156px, calc(100% - 64px));
    height: 48px;
  }

  .auth-brand .auth-project-icon {
    width: 48px;
    height: 48px;
  }

  .auth-brand h1 {
    margin: 10px 0 4px;
  }

  .auth-brand p {
    margin-top: 10px;
  }

  .auth-brand span,
  .auth-card-head small,
  .sso-login-block small,
  .terms-box small {
    overflow-wrap: anywhere;
  }

  .auth-workbench {
    margin-top: 8px;
    padding: 10px;
  }

  .workbench-grid {
    grid-template-columns: 1fr;
  }

  .workbench-grid article {
    grid-template-columns: 1fr auto;
    align-items: center;
  }

  .sso-login-block,
  .terms-box {
    min-width: 0;
  }

  .sso-button {
    min-height: 50px;
  }

  .sso-button :deep(span) {
    gap: 7px;
  }
}
</style>
