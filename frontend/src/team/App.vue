<template>
  <el-config-provider>
    <main class="maintenance-shell notranslate" lang="zh-CN" translate="no">
      <section class="maintenance-card" role="status" aria-labelledby="maintenance-title">
        <div class="brand-lockup">
          <img class="brand-icon" :src="appIcon" alt="" />
          <img v-if="BRAND_SHOW_LOGO" class="brand-logo" :src="logo" :alt="BRAND_SHORT" />
          <div><strong>{{ BRAND_NAME }}</strong><small>团队工作区</small></div>
        </div>
        <span class="maintenance-kicker">TEMPORARILY PAUSED</span>
        <h1 id="maintenance-title">团队版暂停维护</h1>
        <p>当前研发能力集中在个人硬件研发工作台。团队数据和服务接口均已保留，团队页面暂不接受新的操作。</p>
        <div class="maintenance-note">
          <strong>现有数据不会删除</strong>
          <span>后续恢复团队版时，可继续沿用已有团队库、成员与记录。</span>
        </div>
        <a href="/component-warehouse/personal/">进入个人硬件研发工作台</a>
      </section>
      <app-footer />
    </main>
  </el-config-provider>
</template>

<script setup>
import logo from '../assets/brand-logo.png'
import appIcon from '../assets/generated/cw-app-icon.png'
import { BRAND_NAME, BRAND_SHORT, BRAND_SHOW_LOGO } from '../shared/branding'
import AppFooter from '../shared/components/AppFooter.vue'
</script>

<style scoped>
.maintenance-shell {
  min-height: 100vh;
  display: grid;
  grid-template-rows: 1fr auto;
  place-items: center;
  gap: 28px;
  padding: 40px 20px 20px;
  color: #102a32;
  background:
    radial-gradient(circle at 16% 10%, rgba(50, 122, 130, .16), transparent 34%),
    radial-gradient(circle at 88% 82%, rgba(174, 94, 43, .12), transparent 32%),
    #edf2f3;
}
.maintenance-card {
  width: min(680px, 100%);
  overflow: hidden;
  border: 1px solid rgba(27, 76, 84, .2);
  border-radius: 28px;
  padding: clamp(28px, 6vw, 58px);
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 24px 70px rgba(21, 53, 60, .14), inset 0 1px 0 #fff;
}
.brand-lockup { min-width: 0; display: flex; align-items: center; gap: 12px; margin-bottom: 48px; }
.brand-icon { width: 42px; height: 42px; border-radius: 12px; }
.brand-logo { width: 108px; max-height: 38px; object-fit: contain; }
.brand-lockup div { min-width: 0; display: grid; gap: 2px; }
.brand-lockup strong, .brand-lockup small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.brand-lockup strong { font-size: 16px; }
.brand-lockup small { color: #5b6e75; }
.maintenance-kicker { color: #1b6974; font-size: 12px; font-weight: 800; letter-spacing: .16em; }
h1 { margin: 12px 0 14px; font-size: clamp(34px, 7vw, 54px); line-height: 1.08; letter-spacing: -.04em; }
p { max-width: 570px; margin: 0; color: #4d626a; font-size: 17px; line-height: 1.75; }
.maintenance-note { display: grid; gap: 5px; margin: 30px 0; border-left: 4px solid #b4632f; border-radius: 0 13px 13px 0; padding: 14px 17px; background: #f8eee6; }
.maintenance-note strong { color: #753d1d; }
.maintenance-note span { color: #5b5149; line-height: 1.55; }
a { display: inline-flex; min-height: 46px; align-items: center; justify-content: center; border-radius: 13px; padding: 0 20px; color: #fff; background: #0f6570; box-shadow: 0 9px 22px rgba(15, 101, 112, .2); font-weight: 750; text-decoration: none; }
a:hover { background: #0b5660; }
@media (max-width: 560px) {
  .maintenance-shell { padding: 14px; }
  .maintenance-card { border-radius: 20px; }
  .brand-lockup { margin-bottom: 34px; flex-wrap: wrap; }
  .brand-lockup div { width: 100%; }
  .brand-lockup strong, .brand-lockup small { white-space: normal; }
  a { width: 100%; box-sizing: border-box; text-align: center; }
}
</style>
