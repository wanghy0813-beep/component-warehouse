<template>
  <div v-if="!IS_DESKTOP" class="install-actions">
    <el-button class="install-app-button" size="small" type="primary" :icon="Download" @click="downloadWindows">
      下载 Windows 离线版
    </el-button>
    <el-button
      v-if="canShowPwaInstall"
      class="install-app-button"
      size="small"
      :loading="installing"
      @click="install"
    >安装网页版</el-button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Download } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from '../elementApi'
import { canShowPwaInstall, requestPwaInstall } from '../pwaInstall'
import { IS_DESKTOP } from '../desktopBridge'

const installing = ref(false)

function downloadWindows() {
  window.location.assign('/hardware/downloads/WXY-LAB-Hardware-Setup-x64.exe')
}

async function install() {
  if (installing.value) return
  installing.value = true
  try {
    const result = await requestPwaInstall()
    if (result?.outcome === 'accepted') {
      ElMessage.success('应用安装请求已提交')
    } else if (result?.outcome === 'dismissed') {
      ElMessage.info('已取消安装')
    } else if (result?.outcome === 'installed') {
      ElMessage.success('应用已安装')
    } else {
      await ElMessageBox.alert(
        '当前浏览器没有开放直接安装弹窗。请点击浏览器右上角菜单，选择“安装应用”或“添加到主屏幕”。如果菜单里暂时没有安装入口，请刷新一次本页面后再试。',
        '安装应用',
        { confirmButtonText: '知道了', type: 'info' }
      )
    }
  } finally {
    installing.value = false
  }
}
</script>

<style scoped>
.install-actions { display: flex; flex-wrap: wrap; gap: 8px; }.install-app-button { flex: 0 0 auto; }
</style>
