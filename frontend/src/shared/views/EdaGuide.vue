<template>
  <section class="guide-page">
    <header class="guide-hero">
      <div><span>EDA 使用说明</span><h1>从库存元件到 Altium Designer</h1><p>这份说明按实际工作顺序编写，不需要先理解复杂的库版本概念。</p></div>
      <el-button type="primary" @click="backToEda">返回 AD 元件库</el-button>
    </header>

    <section v-for="section in sections" :key="section.title" class="guide-card">
      <h2>{{ section.title }}</h2>
      <p>{{ section.summary }}</p>
      <ol v-if="section.steps">
        <li v-for="step in section.steps" :key="step">{{ step }}</li>
      </ol>
      <ul v-if="section.notes">
        <li v-for="note in section.notes" :key="note">{{ note }}</li>
      </ul>
    </section>

    <section class="guide-card download-card">
      <h2>Windows 同步工具</h2>
      <p>下载 ZIP 后解压，双击 ComponentWarehouse-AD-Sync.exe。第一次使用需要在网页创建同步令牌。</p>
      <div><el-button type="primary" @click="downloadClient">下载 Windows x64 客户端</el-button><a href="/hardware/downloads/WXYLAB-AD-Sync-latest-win-x64.zip.sha256" target="_blank">查看 SHA-256</a></div>
    </section>
  </section>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const sections = [
  { title: '1. 上传资料', summary: '上传 SchLib、PcbLib、IntLib、PDF 数据手册、STEP 3D 模型或封装图片。', steps: ['进入“上传资料”。', '选择本地文件或粘贴公开下载链接。', '上传后文件进入“待检查（Raw）”，不会直接作为正式库使用。'] },
  { title: '2. 关联库存元件', summary: '让库存中的具体元件知道应该使用哪个原理图符号和 PCB 封装。', steps: ['搜索器件 ID、名称、厂商型号或 LCSC 编号。', '填写 AD 库中的原理图符号名称和 PCB 封装名称。', '选择数据手册和 3D 模型后保存。'] },
  { title: '3. 检查封装', summary: '对照数据手册检查引脚、焊盘尺寸、方向和丝印。', notes: ['待检查（Raw）：刚导入，不能默认相信。', '已对照资料（Checked）：已核对数据手册。', '已实测（Tested）：有实际打板或测试记录。', '可正式使用（Verified）：可以复用。'] },
  { title: '4. 发布与同步', summary: '发布后版本保持不变，Windows 工具只下载已发布版本。', steps: ['进入“检查并发布”查看缺资料、缺封装和未验证风险。', '确认风险后发布工作版本。', '在 Windows 工具中点击“立即同步”，再让 AD 使用缓存目录中的库文件。'] },
  { title: '5. 离线与冲突', summary: '断网时继续使用本地缓存；本地和服务器同时修改时不会静默覆盖。', notes: ['本地修改使用“检查本地修改”发现。', '点击“上传为待检查草稿”会建立新的 Raw 工作版本。', '冲突文件会保留带时间戳的本地副本。'] },
  { title: '6. 高级管理', summary: '只有需要多个逻辑库、手工版本号或单独管理 Symbol/Footprint 对象时才使用。', notes: ['已发布版本不能直接修改。', '需要修改时建立新工作版本。', '同步令牌可随时撤销。'] },
]

function backToEda() {
  const libraryId = route.params.libraryId
  router.push(libraryId ? `/library/${libraryId}/eda` : '/eda')
}
function downloadClient() {
  window.location.href = '/hardware/downloads/WXYLAB-AD-Sync-latest-win-x64.zip'
}
</script>

<style scoped>
.guide-page { display: grid; gap: 16px; min-width: 0; }
.guide-hero, .guide-card { padding: 20px; border: 1px solid var(--cw-border, #e4eaf2); border-radius: 16px; background: #fff; }
.guide-hero { display: flex; justify-content: space-between; gap: 18px; align-items: center; background: linear-gradient(135deg, #fff7ed, #fff); }
.guide-hero span { color: #f97316; font-weight: 800; }.guide-hero h1 { margin: 5px 0; }.guide-hero p, .guide-card p { margin: 0; color: #667085; line-height: 1.7; }
.guide-card h2 { margin: 0 0 8px; }.guide-card ol, .guide-card ul { margin: 12px 0 0; padding-left: 22px; color: #344054; line-height: 1.9; }
.download-card div { display: flex; align-items: center; gap: 12px; margin-top: 14px; }.download-card a { color: #c2410c; }
@media (max-width: 680px) { .guide-hero { align-items: stretch; flex-direction: column; }.download-card div { align-items: stretch; flex-direction: column; } }
</style>
