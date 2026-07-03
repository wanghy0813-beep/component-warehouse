<template>
  <el-button
    v-if="canShowPwaInstall"
    class="install-app-button"
    size="small"
    :icon="Download"
    :loading="installing"
    @click="install"
  >
    安装应用
  </el-button>
</template>

<script setup>
import { ref } from 'vue'
import { Download } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from '../elementApi'
import { canShowPwaInstall, requestPwaInstall } from '../pwaInstall'

const installing = ref(false)

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
.install-app-button {
  flex: 0 0 auto;
}
</style>
