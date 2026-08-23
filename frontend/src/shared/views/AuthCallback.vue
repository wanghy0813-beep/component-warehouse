<template>
  <section class="auth-callback notranslate" lang="zh-CN" translate="no">
    <strong>{{ statusText }}</strong>
    <small>{{ detailText }}</small>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { finishSsoLogin } from '../../api/authSessionApi'

const statusText = ref('正在完成统一账号登录')
const detailText = ref('请稍候，系统正在校验安全登录状态。')

onMounted(async () => {
  try {
    const result = await finishSsoLogin(window.location.search)
    const target = result.returnTo || new URL('/hardware/', window.location.origin).href
    window.location.replace(target)
  } catch (error) {
    statusText.value = '统一账号登录失败'
    detailText.value = error?.message || '请返回后重新登录。'
  }
})
</script>

<style scoped>
.auth-callback {
  min-height: 100vh;
  display: grid;
  place-content: center;
  gap: 8px;
  padding: 24px;
  color: #0f172a;
  text-align: center;
  background: #f8fafc;
}

.auth-callback strong {
  font-size: 22px;
}

.auth-callback small {
  color: #64748b;
}
</style>
