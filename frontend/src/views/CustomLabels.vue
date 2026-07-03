<template>
  <section class="custom-label-route">
    <custom-label-dialog
      standalone
      :model-value="true"
      :templates="customLabels"
      :category-summaries="categorySummaries"
      :saving="customLabelSaving"
      :save-template="savePersonalCustomLabel"
      :archive-template="archivePersonalCustomLabel"
      :upload-asset="uploadPersonalCustomLabelAsset"
      :load-asset="loadPersonalCustomLabelAsset"
      :export-sheet="exportPersonalCustomLabelSheet"
      @refresh="loadCustomLabels"
    />
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import CustomLabelDialog from '../shared/components/CustomLabelDialog.vue'
import {
  createCustomLabel,
  deleteCustomLabel,
  exportCustomLabelSheet,
  getCustomLabelCategorySummary,
  getCustomLabelAssetBlob,
  listCustomLabels,
  updateCustomLabel,
  uploadCustomLabelAsset
} from '../api/client'

const customLabels = ref([])
const categorySummaries = ref([])
const customLabelSaving = ref(false)

onMounted(() => {
  loadCustomLabels()
  loadCategorySummaries()
})

async function loadCustomLabels() {
  try {
    customLabels.value = await listCustomLabels()
  } catch {
    customLabels.value = []
  }
}

async function loadCategorySummaries() {
  try {
    categorySummaries.value = await getCustomLabelCategorySummary()
  } catch {
    categorySummaries.value = []
  }
}

async function savePersonalCustomLabel(payload) {
  customLabelSaving.value = true
  try {
    const body = { name: payload.name || '自定义标签', content: payload.content || {} }
    const saved = payload.id ? await updateCustomLabel(payload.id, body) : await createCustomLabel(body)
    await loadCustomLabels()
    await loadCategorySummaries()
    return saved
  } finally {
    customLabelSaving.value = false
  }
}

async function archivePersonalCustomLabel(id) {
  await deleteCustomLabel(id)
  await loadCustomLabels()
  await loadCategorySummaries()
}

async function uploadPersonalCustomLabelAsset(id, file) {
  const asset = await uploadCustomLabelAsset(id, file)
  await loadCustomLabels()
  return asset
}

function loadPersonalCustomLabelAsset(assetId) {
  return getCustomLabelAssetBlob(assetId)
}

function exportPersonalCustomLabelSheet(payload) {
  return exportCustomLabelSheet(payload)
}
</script>

<style scoped>
.custom-label-route {
  padding: 20px;
}
</style>
