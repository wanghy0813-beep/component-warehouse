<template>
  <section class="oauth-shell">
    <article class="oauth-card">
      <div class="brand-mark">WXY</div>
      <template v-if="loading">
        <h1>正在检查 ChatGPT 授权</h1>
        <p>请稍候，系统正在读取授权范围。</p>
        <el-skeleton :rows="4" animated />
      </template>

      <template v-else-if="errorMessage">
        <h1>无法继续授权</h1>
        <el-alert type="error" show-icon :closable="false" :title="errorMessage" />
        <div class="actions">
          <el-button v-if="requiresLogin" type="primary" @click="login">登录并继续</el-button>
          <el-button v-else @click="load">重新检查</el-button>
        </div>
      </template>

      <template v-else>
        <el-tag effect="plain" type="primary">ChatGPT Work 模式</el-tag>
        <h1>{{ request.client_name }} 请求连接 WXY LAB Hardware</h1>
        <p>授权只绑定当前登录账号的个人库，不会开放团队库或管理员功能。</p>

        <div class="permission-list">
          <section v-for="scope in request.scopes" :key="scope" class="permission-item">
            <span class="permission-icon">✓</span>
            <div>
              <strong>{{ scopeLabel(scope) }}</strong>
              <small>{{ request.permissions?.[scope] || scope }}</small>
            </div>
          </section>
        </div>

        <el-alert
          type="warning"
          show-icon
          :closable="false"
          title="ChatGPT 不能批准写入。任何库存、项目、BOM 或采购变更仍需你在本网站逐单确认。"
        />
        <small class="expiry">本次连接请求有效至 {{ formatTime(request.expires_at) }}</small>

        <div class="actions split">
          <el-button :loading="submitting" @click="decide('reject')">拒绝</el-button>
          <el-button type="primary" :loading="submitting" @click="decide('approve')">允许连接</el-button>
        </div>
      </template>
    </article>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { decideCodexOauthRequest, getCodexOauthRequest } from '../api/client'
import { startSsoLogin } from '../api/authSessionApi'

const route = useRoute()
const loading = ref(true)
const submitting = ref(false)
const requiresLogin = ref(false)
const errorMessage = ref('')
const request = ref({ scopes: [], permissions: {} })

function formatTime(value) {
  if (!value) return '未知'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function scopeLabel(scope) {
  return {
    'inventory:read': '完整读取个人硬件业务库',
    'operations:propose': '生成网页审批草案',
  }[scope] || scope
}

async function load() {
  loading.value = true
  errorMessage.value = ''
  requiresLogin.value = false
  try {
    request.value = await getCodexOauthRequest(route.params.requestId)
    if (request.value.status !== 'pending') {
      errorMessage.value = '该连接请求已经处理或失效，请返回 ChatGPT 重新发起连接。'
    }
  } catch (error) {
    requiresLogin.value = error?.response?.status === 401
    errorMessage.value = requiresLogin.value
      ? '请先登录 WXY LAB Hardware，再确认是否允许 ChatGPT 访问。'
      : (error?.response?.data?.detail || '读取授权请求失败')
  } finally {
    loading.value = false
  }
}

async function login() {
  await startSsoLogin(window.location.href)
}

async function decide(decision) {
  submitting.value = true
  errorMessage.value = ''
  try {
    const result = await decideCodexOauthRequest(route.params.requestId, decision)
    if (!result.redirect_url) throw new Error('服务没有返回 ChatGPT 回调地址')
    window.location.assign(result.redirect_url)
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '处理授权请求失败'
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.oauth-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: radial-gradient(circle at 20% 10%, #dbeafe 0, transparent 32%), #f8fafc;
}
.oauth-card {
  width: min(100%, 620px);
  display: grid;
  gap: 18px;
  padding: clamp(24px, 5vw, 42px);
  border: 1px solid #dbe3ef;
  border-radius: 24px;
  background: rgba(255, 255, 255, .96);
  box-shadow: 0 22px 70px rgba(15, 23, 42, .12);
}
.brand-mark {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  color: #fff;
  font-weight: 800;
  background: linear-gradient(135deg, #2563eb, #0f766e);
}
h1 { margin: 0; color: #0f172a; font-size: clamp(24px, 4vw, 34px); line-height: 1.2; }
p { margin: 0; color: #475569; line-height: 1.7; }
.permission-list { display: grid; gap: 10px; }
.permission-item {
  display: flex;
  gap: 12px;
  padding: 14px;
  border: 1px solid #dbe3ef;
  border-radius: 14px;
  background: #f8fafc;
}
.permission-icon {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 999px;
  color: #fff;
  background: #16a34a;
}
.permission-item strong, .permission-item small { display: block; }
.permission-item small, .expiry { margin-top: 4px; color: #64748b; line-height: 1.5; }
.actions { display: flex; justify-content: flex-end; gap: 10px; }
.actions.split { justify-content: space-between; }
@media (max-width: 560px) {
  .oauth-shell { padding: 12px; }
  .oauth-card { border-radius: 18px; }
}
</style>
