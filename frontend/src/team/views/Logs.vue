<template>
  <section class="team-page">
    <div class="team-page-head">
      <div>
        <h1>操作日志</h1>
        <p>记录新增、修改、删除、导入、关联、成员和邀请变更。</p>
      </div>
      <el-button @click="load">刷新</el-button>
    </div>

    <div class="team-panel">
      <el-timeline v-loading="loading">
        <el-timeline-item v-for="row in logs" :key="row.id" :timestamp="formatTime(row.created_at)" placement="top">
          <el-card shadow="never">
            <strong>{{ row.summary }}</strong>
            <p class="muted">{{ row.actor_nickname }} · 手机尾号 {{ row.actor_phone_last4 || '----' }} · {{ row.action }}</p>
            <el-collapse v-if="row.before_json || row.after_json">
              <el-collapse-item title="查看修改前后内容">
                <div class="diff-grid">
                  <pre>{{ pretty(row.before_json) }}</pre>
                  <pre>{{ pretty(row.after_json) }}</pre>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-card>
        </el-timeline-item>
      </el-timeline>
      <div v-if="!loading && !logs.length" class="empty-state">暂无操作记录</div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from '../../shared/elementApi'
import { useRoute } from 'vue-router'
import { listLogs } from '../api'

const route = useRoute()
const logs = ref([])
const loading = ref(false)

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

function pretty(value) {
  if (!value) return '无'
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

async function load() {
  loading.value = true
  try {
    logs.value = await listLogs(route.params.libraryId, { limit: 200 })
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '日志加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.diff-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
pre { overflow: auto; max-height: 320px; padding: 12px; border-radius: var(--cw-radius-control); background: #f3f7f6; font-size: 12px; }
@media (max-width: 680px) { .diff-grid { grid-template-columns: 1fr; } }
</style>
