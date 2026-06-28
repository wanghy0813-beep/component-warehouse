<template>
  <button v-show="visible" class="back-to-top" type="button" aria-label="返回顶部" @click="backToTop">
    ↑
  </button>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const emit = defineEmits(['click'])
const props = defineProps({
  threshold: { type: Number, default: 900 }
})

const visible = ref(false)

function updateVisible() {
  visible.value = (window.scrollY || document.documentElement.scrollTop || 0) > props.threshold
}

function backToTop() {
  emit('click')
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(() => {
  updateVisible()
  window.addEventListener('scroll', updateVisible, { passive: true })
  window.addEventListener('resize', updateVisible, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', updateVisible)
  window.removeEventListener('resize', updateVisible)
})
</script>

<style scoped>
.back-to-top {
  position: fixed;
  right: max(18px, env(safe-area-inset-right));
  bottom: max(22px, env(safe-area-inset-bottom));
  z-index: 40;
  width: 46px;
  height: 46px;
  border: 1px solid rgba(148, 163, 184, .45);
  border-radius: var(--cw-radius-control);
  background: rgba(255, 255, 255, .96);
  box-shadow: 0 12px 28px rgba(15, 23, 42, .16);
  color: #0f172a;
  font-size: 22px;
  font-weight: 800;
  cursor: pointer;
  backdrop-filter: blur(12px);
}

.back-to-top:hover {
  border-color: #93c5fd;
  color: #2563eb;
}

@media (max-width: 760px) {
  .back-to-top {
    right: max(14px, env(safe-area-inset-right));
    bottom: calc(76px + env(safe-area-inset-bottom));
    width: 44px;
    height: 44px;
  }
}
</style>
