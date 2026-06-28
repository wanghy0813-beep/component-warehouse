<template>
  <div class="join-page">
    <section v-if="loading" class="team-panel join-card">正在读取邀请…</section>
    <section v-else-if="error" class="team-panel join-card">
      <img v-if="BRAND_SHOW_LOGO" :src="logo" :alt="BRAND_SHORT" />
      <h1>无法加入</h1>
      <p>{{ error }}</p>
      <el-button @click="router.replace('/')">返回团队器件库</el-button>
    </section>
    <auth-panel
      v-else-if="!authToken"
      eyebrow="TEAM INVITATION"
      title="加入团队器件库"
      :subtitle="`${invite.library.name} · 队长 ${invite.captain.nickname}`"
      @authenticated="authenticated"
    />
    <section v-else class="team-panel join-card join-ready">
      <img v-if="BRAND_SHOW_LOGO" :src="logo" :alt="BRAND_SHORT" />
      <p class="eyebrow">团队器件库邀请</p>
      <h1>{{ invite.library.name }}</h1>
      <p>队长：{{ invite.captain.nickname }}</p>
      <div class="privacy-note">
        <strong>加入后可查看</strong>
        <span>元器件 · PCB · 成员 · 操作日志</span>
      </div>
      <el-button type="primary" size="large" :loading="joining" @click="join">加入团队器件库</el-button>
      <small>点击按钮才会正式加入；打开链接不会自动入队。</small>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from '../../shared/elementApi'
import { useRoute, useRouter } from 'vue-router'
import logo from '../../assets/brand-logo.png'
import { BRAND_SHORT, BRAND_SHOW_LOGO } from '../../shared/branding'
import AuthPanel from '../../components/AuthPanel.vue'
import { getAuthToken } from '../../api/authSessionApi'
import { joinInvite, previewInvite } from '../api'

const emit = defineEmits(['authenticated'])
const route = useRoute()
const router = useRouter()
const loading = ref(true)
const joining = ref(false)
const error = ref('')
const invite = ref(null)
const authToken = ref(getAuthToken())

async function load() {
  try {
    invite.value = await previewInvite(route.params.token)
  } catch (requestError) {
    error.value = requestError?.response?.data?.detail || '邀请链接无效或已失效'
  } finally {
    loading.value = false
  }
}

async function authenticated(data) {
  authToken.value = data.token
  emit('authenticated', data)
}

async function join() {
  joining.value = true
  try {
    const result = await joinInvite(route.params.token)
    ElMessage.success('已加入团队器件库')
    router.replace(`/library/${result.library.id}/components`)
  } catch (requestError) {
    error.value = requestError?.response?.data?.detail || '暂时无法加入该团队器件库'
  } finally {
    joining.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.join-page { min-height: 100vh; display: grid; place-items: center; padding: 18px; background: radial-gradient(circle at 20% 15%, #d8f7f0, transparent 32%), radial-gradient(circle at 85% 80%, #e4eaff, transparent 34%), #f5f9f8; }
.join-card { width: min(520px, 100%); text-align: center; padding: 42px; border-top: 5px solid #18a58f; }
.join-card img { width: min(220px, 70%); height: 92px; object-fit: contain; }
.join-card h1 { margin: 12px 0; }
.join-card p { color: #70827f; }
.eyebrow { color: #13806f !important; letter-spacing: .12em; font-weight: 800; }
.join-ready { background: linear-gradient(145deg, #fff, #f0fbf8); }
.privacy-note { display: flex; flex-direction: column; gap: 6px; margin: 22px 0; padding: 14px; color: #315f59; background: #e1f6f1; border-radius: 16px; }
.join-card small { display: block; margin-top: 14px; color: #82928f; }
</style>
