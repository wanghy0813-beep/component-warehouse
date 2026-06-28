<template>
  <section class="manual-page">
    <header class="manual-hero">
      <div>
        <span>使用说明书</span>
        <h1>{{ BRAND_NAME }}</h1>
        <p>覆盖个人版、团队版、BOM、采购、标签和维护流程。</p>
      </div>
      <div class="manual-actions">
        <el-button @click="backHome">返回</el-button>
        <el-button type="primary" @click="printManual">打印 / 保存 PDF</el-button>
      </div>
    </header>

    <article class="manual-card" v-html="renderedManual"></article>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarkdownIt from 'markdown-it'
import manualMarkdown from '../manuals/userManual.md?raw'
import { BRAND_NAME } from '../branding'

const router = useRouter()
const route = useRoute()
const md = new MarkdownIt({ html: false, linkify: true, typographer: true })
const renderedManual = computed(() => md.render(manualMarkdown))

function backHome() {
  const libraryId = route.params.libraryId
  router.push(libraryId ? `/library/${libraryId}/components` : '/about')
}

function printManual() {
  window.print()
}
</script>

<style scoped>
.manual-page {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.manual-hero,
.manual-card {
  border: 1px solid var(--cw-border, #e4eaf2);
  border-radius: var(--cw-radius-card, 16px);
  background: #fff;
}

.manual-hero {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
  padding: 20px;
  background: linear-gradient(135deg, #fff7ed, #fff);
}

.manual-hero span {
  color: #f97316;
  font-weight: 800;
}

.manual-hero h1 {
  margin: 5px 0;
}

.manual-hero p {
  margin: 0;
  color: #667085;
  line-height: 1.7;
}

.manual-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.manual-card {
  min-width: 0;
  padding: clamp(18px, 3vw, 32px);
  color: #243b53;
  line-height: 1.85;
}

.manual-card :deep(h1),
.manual-card :deep(h2),
.manual-card :deep(h3) {
  color: #17202a;
  line-height: 1.35;
}

.manual-card :deep(h1) {
  margin-top: 0;
  font-size: clamp(28px, 4vw, 40px);
}

.manual-card :deep(h2) {
  margin-top: 34px;
  padding-top: 18px;
  border-top: 1px solid #e4eaf2;
}

.manual-card :deep(p),
.manual-card :deep(li) {
  color: #475467;
}

.manual-card :deep(table) {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
  margin: 16px 0;
  border-radius: var(--cw-radius-control, 16px);
}

.manual-card :deep(th),
.manual-card :deep(td) {
  padding: 10px 12px;
  border: 1px solid #e4eaf2;
  text-align: left;
}

.manual-card :deep(th) {
  background: #f8fafc;
}

.manual-card :deep(code) {
  padding: 2px 6px;
  border-radius: var(--cw-radius-control);
  background: #f1f5f9;
  color: #c2410c;
}

.manual-card :deep(a) {
  color: #c2410c;
  text-decoration: none;
  font-weight: 700;
}

@media (max-width: 680px) {
  .manual-hero {
    align-items: stretch;
    flex-direction: column;
  }

  .manual-actions {
    flex-direction: column;
  }
}

@media print {
  .manual-hero,
  :global(.personal-header),
  :global(.team-header),
  :global(.personal-mobile-nav),
  :global(.mobile-nav),
  :global(.app-footer) {
    display: none !important;
  }

  .manual-card {
    border: 0;
    padding: 0;
  }
}
</style>
