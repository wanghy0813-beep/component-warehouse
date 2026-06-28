<template>
  <img v-if="src" :src="src" :alt="alt" />
  <div v-else class="image-placeholder">{{ fallback }}</div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { fetchPcbImage } from '../api'

const props = defineProps({
  libraryId: { type: String, required: true },
  pcbId: { type: String, required: true },
  side: { type: String, required: true },
  enabled: Boolean,
  alt: { type: String, default: 'PCB 图片' },
  fallback: { type: String, default: '暂无图片' }
})

const src = ref('')

async function load() {
  if (src.value) URL.revokeObjectURL(src.value)
  src.value = ''
  if (!props.enabled) return
  try {
    const blob = await fetchPcbImage(props.libraryId, props.pcbId, props.side)
    src.value = URL.createObjectURL(blob)
  } catch {
    src.value = ''
  }
}

watch(() => [props.libraryId, props.pcbId, props.side, props.enabled], load, { immediate: true })
onBeforeUnmount(() => {
  if (src.value) URL.revokeObjectURL(src.value)
})
</script>
