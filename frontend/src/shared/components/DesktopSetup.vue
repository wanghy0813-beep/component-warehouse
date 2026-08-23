<template>
  <div class="desktop-setup">
    <section class="setup-card">
      <img :src="appIcon" alt="" />
      <small>WXY LAB Hardware · Windows 离线版</small>
      <h1>首次连接在线账号</h1>
      <p v-if="!authorization">登录一次后，APP 会通过加密 API 自动下载你的全部个人数据与附件。完成后即可断网使用。</p>
      <template v-else>
        <p>请在浏览器中确认本次 Windows 设备登录，并输入下面的用户码。</p>
        <button class="user-code" type="button" @click="copyCode">{{ authorization.userCode }}</button>
        <el-button type="primary" size="large" @click="openAuthorization">打开账号授权页面</el-button>
        <span class="polling">{{ statusText }}</span>
      </template>
      <el-alert v-if="error" type="error" show-icon :closable="false" :title="error" />
      <el-button v-if="!authorization" type="primary" size="large" :loading="loading" @click="start">在线登录并下载个人数据</el-button>
      <div class="setup-notes"><span>本地 SQLite</span><span>附件完整落盘</span><span>联网自动同步</span></div>
    </section>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { ElMessage } from '../elementApi'
import appIcon from '../../assets/generated/cw-app-icon.png'
import { openDesktopUrl, pollDesktopAuthorization, startDesktopAuthorization } from '../desktopBridge'

const emit = defineEmits(['complete'])
const authorization = ref(null)
const loading = ref(false)
const error = ref('')
const statusText = ref('等待账号确认…')
let timer = null

async function start() {
  loading.value = true
  error.value = ''
  try {
    authorization.value = await startDesktopAuthorization()
    await openAuthorization()
    schedulePoll(Number(authorization.value.interval || 5))
  } catch (requestError) {
    error.value = requestError?.message || String(requestError)
  } finally {
    loading.value = false
  }
}

async function openAuthorization() {
  await openDesktopUrl(authorization.value.verificationUriComplete || authorization.value.verificationUri)
}

async function copyCode() {
  await navigator.clipboard.writeText(authorization.value.userCode)
  ElMessage.success('用户码已复制')
}

async function poll() {
  try {
    const result = await pollDesktopAuthorization()
    if (result.status === 'pending') {
      schedulePoll(Number(authorization.value?.interval || 5))
      return
    }
    if (result.status === 'slow_down') {
      statusText.value = '账号服务要求降低轮询频率，正在继续等待…'
      schedulePoll(Number(result.retryAfter || 10))
      return
    }
    if (result.status === 'complete') {
      window.clearTimeout(timer)
      timer = null
      statusText.value = '个人数据已保存到本机'
      emit('complete', result)
    }
  } catch (requestError) {
    window.clearTimeout(timer)
    timer = null
    error.value = requestError?.message || String(requestError)
  }
}

function schedulePoll(seconds) {
  if (timer) window.clearTimeout(timer)
  timer = window.setTimeout(poll, Math.max(3000, Number(seconds || 5) * 1000))
}

onBeforeUnmount(() => timer && window.clearTimeout(timer))
</script>

<style scoped>
.desktop-setup { position: fixed; inset: 0; z-index: 9999; display: grid; place-items: center; padding: 28px; background: radial-gradient(circle at top left, #edf7f8, #f8fafc 48%, #eef2f6); }
.setup-card { width: min(560px, calc(100vw - 40px)); display: grid; justify-items: center; gap: 18px; padding: 44px; border: 1px solid #d8e4e6; border-radius: 24px; background: rgba(255,255,255,.96); box-shadow: 0 24px 70px rgba(35,62,68,.14); text-align: center; }
.setup-card img { width: 72px; height: 72px; border-radius: 18px; }
.setup-card small { color: #48717a; font-weight: 760; letter-spacing: .04em; }
.setup-card h1 { margin: 0; color: #183b43; font-size: 30px; }
.setup-card p { margin: 0; color: #60747a; line-height: 1.75; }
.user-code { padding: 12px 22px; border: 1px dashed #5a969f; border-radius: 14px; color: #285f68; background: #edf7f8; font: 800 28px/1.1 ui-monospace, monospace; letter-spacing: .16em; cursor: pointer; }
.polling { color: #60747a; font-size: 13px; }
.setup-notes { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
.setup-notes span { padding: 7px 10px; border-radius: 999px; color: #3d6870; background: #f0f6f7; font-size: 12px; font-weight: 700; }
</style>
