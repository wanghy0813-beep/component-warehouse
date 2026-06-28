<template>
  <main class="public-page" v-loading="loading">
    <section v-if="component" class="public-shell">
      <header class="public-brand">
        <div class="brand-lockup">
          <img v-if="BRAND_SHOW_LOGO" :src="brandLogo" :alt="BRAND_SHORT" />
          <div>
            <span>{{ BRAND_NAME }} · 个人版</span>
            <strong>公开元器件名片</strong>
          </div>
        </div>
        <el-tag v-if="component.warehouse_code" effect="plain" type="info">{{ component.warehouse_code }}</el-tag>
      </header>

      <article class="hero-card">
        <div class="hero-meta">
          <el-tag effect="plain" :style="{ background: component.category_color || '#eef2ff' }">{{ component.category || '未分类' }}</el-tag>
          <el-tag v-if="component.archived" type="info">已归档</el-tag>
        </div>
        <h1>{{ componentDisplayTitle(component) }}</h1>
        <p v-if="componentDisplaySubtitle(component)" class="subtitle">{{ componentDisplaySubtitle(component) }}</p>
        <p class="summary">
          {{ component.archived ? '该器件已归档，器件 ID 将永久保留且不会分配给其他器件。' : '公开页面仅展示安全摘要，不公开库存、位置、人员、团队或备注。' }}
        </p>
        <div v-if="accessContext" class="context-actions">
          <el-button
            v-if="accessContext.owner && accessContext.personal_component_id"
            type="primary"
            @click="openPersonalComponent"
          >在个人版中管理</el-button>
          <el-button
            v-for="team in accessContext.teams || []"
            :key="team.item_id"
            @click="openTeamComponent(team)"
          >进入 {{ team.library_name }}</el-button>
        </div>
      </article>

      <section class="spec-grid">
        <article v-for="item in keySpecs" :key="`${item.name}-${item.value}`" class="spec-card">
          <span>{{ item.name }}</span>
          <strong>{{ item.value }}</strong>
        </article>
      </section>

      <section class="info-grid">
        <article class="info-card">
          <h2>器件标识</h2>
          <dl>
            <div>
              <dt>器件 ID</dt>
              <dd>
                {{ component.warehouse_code || '-' }}
                <el-button v-if="component.warehouse_code" size="small" text @click="copyText(component.warehouse_code, '器件 ID')">复制</el-button>
              </dd>
            </div>
            <div><dt>型号</dt><dd>{{ component.model || '-' }}</dd></div>
            <div>
              <dt>立创 ID</dt>
              <dd>
                {{ component.lcsc_number || '-' }}
                <el-button v-if="component.lcsc_number" size="small" text @click="copyText(component.lcsc_number, '立创 ID')">复制</el-button>
              </dd>
            </div>
            <div><dt>封装</dt><dd>{{ component.package || '-' }}</dd></div>
          </dl>
        </article>
        <article class="info-card">
          <h2>资料</h2>
          <p>分类：{{ component.category || '未分类' }}</p>
          <el-button v-if="component.datasheet_url" plain @click="openDatasheet">打开数据手册</el-button>
          <p v-else>暂无公开数据手册。</p>
        </article>
      </section>

      <footer class="public-footer">
        <div class="footer-brand">
          <img v-if="BRAND_SHOW_LOGO" :src="brandLogo" :alt="BRAND_SHORT" />
          <strong>Powered by {{ BRAND_NAME }}</strong>
        </div>
        <span>{{ accessContext ? '已按当前账号权限提供管理入口。' : '只读公开页面，不提供库存、位置或成员信息。' }}</span>
      </footer>
    </section>

    <el-empty v-else-if="!loading" description="没有找到这个元器件" />
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from '../shared/elementApi'
import { useRoute } from 'vue-router'
import { getComponentAccessContext, getPublicComponent } from '../api/client'
import { getAuthToken } from '../api/authSessionApi'
import { componentDisplaySubtitle, componentDisplayTitle, uniqueDisplayParts } from '../shared/componentDisplay'
import { PERSONAL_BASE, TEAM_BASE } from '../shared/appPaths'
import brandLogo from '../assets/brand-logo.png'
import { BRAND_NAME, BRAND_SHORT, BRAND_SHOW_LOGO } from '../shared/branding'

const route = useRoute()
const loading = ref(false)
const component = ref(null)
const accessContext = ref(null)

const keySpecs = computed(() => {
  const candidates = [
    { name: '规格', value: component.value?.normalized_spec },
    { name: '型号', value: component.value?.model },
    { name: '封装', value: component.value?.package },
    { name: '立创 ID', value: component.value?.lcsc_number }
  ]
  const values = uniqueDisplayParts(candidates.map((item) => item.value))
  return values.map((value) => candidates.find((item) => item.value === value))
})

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(String(text || ''))
    ElMessage.success(`已复制${label}`)
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

async function load() {
  loading.value = true
  try {
    component.value = await getPublicComponent(route.params.code)
    if (getAuthToken()) {
      try {
        accessContext.value = await getComponentAccessContext(route.params.code)
      } catch {
        accessContext.value = null
      }
    }
  } catch (error) {
    ElMessage.error('读取公开元器件失败')
  } finally {
    loading.value = false
  }
}

function openDatasheet() {
  window.open(component.value.datasheet_url, '_blank', 'noopener')
}

function openPersonalComponent() {
  window.location.href = `${PERSONAL_BASE}components?component=${encodeURIComponent(component.value.warehouse_code)}`
}

function openTeamComponent(team) {
  window.location.href = `${TEAM_BASE}library/${encodeURIComponent(team.library_id)}/components?component=${encodeURIComponent(team.item_id)}`
}

onMounted(load)
</script>

<style scoped>
.public-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    linear-gradient(135deg, rgba(37, 99, 235, 0.08), transparent 32%),
    linear-gradient(315deg, rgba(5, 150, 105, 0.08), transparent 28%),
    #f8fafc;
}

.public-shell {
  width: min(980px, 100%);
  min-width: 0;
  display: grid;
  gap: 16px;
}

.public-brand,
.hero-card,
.info-card,
.public-footer {
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 16px;
  background: #fff;
}

.public-brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
}

.brand-lockup,
.footer-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-lockup img {
  width: 154px;
  height: 58px;
  object-fit: contain;
  object-position: center;
}

.footer-brand img {
  width: 118px;
  height: 44px;
  object-fit: contain;
  object-position: center;
}

.public-brand .brand-lockup > div {
  display: grid;
  gap: 2px;
}

.public-brand span,
.public-footer span,
.subtitle,
.summary,
.info-card p,
dt {
  color: #667085;
}

.public-brand strong {
  font-size: 18px;
}

.hero-card {
  padding: clamp(22px, 5vw, 42px);
}

.hero-meta,
.tag-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hero-card h1 {
  margin: 18px 0 8px;
  color: #101828;
  font-size: clamp(36px, 8vw, 72px);
  line-height: 0.96;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.subtitle {
  margin: 0 0 16px;
  font-size: clamp(18px, 3vw, 26px);
  font-weight: 700;
}

.summary {
  max-width: 780px;
  margin: 0;
  font-size: 17px;
  line-height: 1.7;
}

.spec-grid,
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.spec-card {
  display: grid;
  gap: 8px;
  min-height: 104px;
  padding: 16px;
  border: 1px solid #c7d2fe;
  border-radius: 16px;
  background: #f8fbff;
}

.spec-card span {
  color: #53627a;
  font-size: 13px;
}

.spec-card strong {
  color: #111827;
  font-size: 24px;
  line-height: 1.05;
  overflow-wrap: anywhere;
}

.info-card {
  padding: 18px;
}

.info-card h2 {
  margin: 0 0 14px;
  font-size: 17px;
}

dl {
  display: grid;
  gap: 10px;
  margin: 0;
}

dl div {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  gap: 12px;
}

dt,
dd {
  margin: 0;
  min-width: 0;
}

dd {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: #111827;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.info-card p {
  margin: 0 0 14px;
  line-height: 1.7;
}

.tag-line span {
  padding: 5px 10px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12px;
}

.public-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
}

@media (max-width: 640px) {
  .public-page {
    padding: 14px;
    place-items: start center;
  }

  dl div {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .public-brand {
    align-items: flex-start;
    flex-direction: column;
  }

  .brand-lockup {
    width: 100%;
    min-width: 0;
  }

  .brand-lockup img {
    width: 140px;
    height: 54px;
    flex: 0 0 auto;
  }

  .spec-grid,
  .info-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .public-footer {
    display: grid;
  }
}
</style>
