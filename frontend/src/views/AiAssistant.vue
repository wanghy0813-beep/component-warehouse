<template>
  <section class="page">
    <div class="page-header">
      <h1 class="page-title">AI 助手</h1>
    </div>

    <div class="ai-grid">
      <div class="panel">
        <el-tabs v-model="mode">
          <el-tab-pane label="需求找料" name="search">
            <el-input
              v-model="requirement"
              type="textarea"
              :rows="8"
              placeholder="输入功能需求，例如：5V 转 3.3V 供电，或 USB-C 供电的 ESP32 温湿度采集板"
            />
          </el-tab-pane>
          <el-tab-pane label="器件说明" name="info">
            <el-form label-width="86px">
              <el-form-item label="器件">
                <el-input v-model="infoQuery" placeholder="输入名称或型号，例如：MP1584EN、CH340C、AO3400" />
              </el-form-item>
              <el-form-item label="已有规格">
                <el-input v-model="knownSpecs" type="textarea" :rows="4" placeholder="可选：输入你已知的封装、电压、电流、用途等信息" />
              </el-form-item>
              <el-form-item label="联网搜索">
                <el-segmented v-model="webSearch" :options="webSearchOptions" />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="自动分类" name="classify">
            <el-form label-width="82px">
              <el-form-item label="名称">
                <el-input v-model="component.name" />
              </el-form-item>
              <el-form-item label="型号">
                <el-input v-model="component.model" />
              </el-form-item>
              <el-form-item label="参数">
                <el-input v-model="component.parameters" type="textarea" :rows="3" />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="用途说明" name="explain">
            <el-form label-width="82px">
              <el-form-item label="名称">
                <el-input v-model="component.name" />
              </el-form-item>
              <el-form-item label="型号">
                <el-input v-model="component.model" />
              </el-form-item>
              <el-form-item label="封装">
                <el-input v-model="component.package" />
              </el-form-item>
              <el-form-item label="参数">
                <el-input v-model="component.parameters" type="textarea" :rows="3" />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="项目规划" name="project">
            <el-input v-model="goal" type="textarea" :rows="8" placeholder="输入项目目标，例如：做一个 USB-C 供电的 ESP32 温湿度采集板" />
          </el-tab-pane>
        </el-tabs>
        <el-button type="primary" :icon="MagicStick" :loading="loading" @click="run">生成建议</el-button>
      </div>

      <div class="panel result-panel">
        <h2>建议结果</h2>
        <el-alert type="warning" show-icon :closable="false" title="AI 建议不会自动写入数据库，需要人工确认后再应用。" />
        <template v-if="result && mode === 'search'">
          <div class="result-section">
            <h3>库存候选</h3>
            <el-table :data="result.inventory_candidates || []" size="small" empty-text="未命中库存候选">
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column prop="model" label="型号" min-width="130" />
              <el-table-column prop="package" label="封装" width="110" />
              <el-table-column prop="quantity" label="数量" width="80" />
              <el-table-column prop="location" label="位置" min-width="110" />
            </el-table>
          </div>
          <div class="result-section">
            <h3>匹配建议</h3>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="库存命中">
                <pre>{{ JSON.stringify(result.matched_components || [], null, 2) }}</pre>
              </el-descriptions-item>
              <el-descriptions-item label="可替代库存">
                <pre>{{ JSON.stringify(result.alternative_components || [], null, 2) }}</pre>
              </el-descriptions-item>
              <el-descriptions-item label="缺失建议">
                <pre>{{ JSON.stringify(result.missing_suggestions || [], null, 2) }}</pre>
              </el-descriptions-item>
              <el-descriptions-item label="风险提示">
                <pre>{{ JSON.stringify(result.risks || [], null, 2) }}</pre>
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </template>
        <template v-else-if="result && mode === 'info'">
          <div class="result-section">
            <h3>{{ result.normalized_name || result.query }}</h3>
            <p class="summary-text">{{ result.summary }}</p>
          </div>
          <div class="result-section">
            <h3>关键规格</h3>
            <el-table :data="result.key_specs || []" size="small" empty-text="暂无规格">
              <el-table-column prop="name" label="规格" min-width="120" />
              <el-table-column prop="value" label="值" min-width="180" />
              <el-table-column prop="confidence" label="可信度" width="90" />
            </el-table>
          </div>
          <el-descriptions class="result-section" :column="1" border>
            <el-descriptions-item label="典型用途">
              <pre>{{ JSON.stringify(result.applications || [], null, 2) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="PCB 注意">
              <pre>{{ JSON.stringify(result.pcb_notes || [], null, 2) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="替代注意">
              <pre>{{ JSON.stringify(result.substitution_notes || [], null, 2) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="补全建议">
              <pre>{{ JSON.stringify(result.completion_suggestions || [], null, 2) }}</pre>
            </el-descriptions-item>
          </el-descriptions>
          <div v-if="result.sources?.length" class="result-section">
            <h3>搜索来源</h3>
            <el-table :data="result.sources" size="small">
              <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
              <el-table-column prop="site_name" label="来源" width="120" />
              <el-table-column label="链接" width="90">
                <template #default="{ row }">
                  <el-link :href="row.url" target="_blank" type="primary">打开</el-link>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
        <pre v-else-if="result">{{ formattedResult }}</pre>
        <el-empty v-else description="暂无结果" />
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick } from '@element-plus/icons-vue'
import { aiClassify, aiComponentInfo, aiComponentSearch, aiExplain, aiProjectPlan } from '../api/client'

const mode = ref('search')
const loading = ref(false)
const result = ref(null)
const goal = ref('')
const requirement = ref('')
const infoQuery = ref('')
const knownSpecs = ref('')
const webSearch = ref('auto')
const webSearchOptions = [
  { label: '自动', value: 'auto' },
  { label: '关闭', value: 'off' },
  { label: '强制', value: 'force' }
]
const component = reactive({
  name: '',
  model: '',
  parameters: '',
  package: ''
})

const formattedResult = computed(() => JSON.stringify(result.value, null, 2))

async function run() {
  if (mode.value === 'search' && !requirement.value.trim()) {
    ElMessage.warning('请输入需求')
    return
  }
  if (mode.value === 'info' && !infoQuery.value.trim()) {
    ElMessage.warning('请输入器件名称或型号')
    return
  }
  loading.value = true
  try {
    if (mode.value === 'search') {
      result.value = await aiComponentSearch({ requirement: requirement.value, limit: 20 })
    } else if (mode.value === 'info') {
      result.value = await aiComponentInfo({
        query: infoQuery.value,
        known_specs: knownSpecs.value,
        web_search: webSearch.value
      })
    } else if (mode.value === 'classify') {
      result.value = await aiClassify(component)
    } else if (mode.value === 'explain') {
      result.value = await aiExplain(component)
    } else {
      result.value = await aiProjectPlan({ goal: goal.value })
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '生成失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.ai-grid {
  display: grid;
  grid-template-columns: minmax(320px, 420px) 1fr;
  gap: 16px;
}

.result-panel {
  min-height: 420px;
}

.result-panel h2 {
  margin: 0 0 12px;
  font-size: 16px;
}

.result-section {
  margin-top: 14px;
}

.result-section h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.summary-text {
  margin: 0;
  color: #344054;
  line-height: 1.6;
}

pre {
  margin: 14px 0 0;
  padding: 14px;
  overflow: auto;
  border-radius: 8px;
  background: #111827;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .ai-grid {
    grid-template-columns: 1fr;
  }
}
</style>
