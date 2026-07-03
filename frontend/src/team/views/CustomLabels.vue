<template>
  <section class="custom-label-route">
    <custom-label-dialog
      standalone
      :model-value="true"
      :templates="customLabels"
      :category-summaries="categorySummaries"
      :saving="customLabelSaving"
      :save-template="saveTeamCustomLabel"
      :archive-template="archiveTeamCustomLabel"
      :upload-asset="uploadTeamCustomLabelFile"
      :load-asset="loadTeamCustomLabelFile"
      :export-sheet="exportTeamCustomLabelFile"
      @refresh="loadCustomLabels"
    />
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import CustomLabelDialog from '../../shared/components/CustomLabelDialog.vue'
import {
  createTeamCustomLabel,
  deleteTeamCustomLabel,
  exportTeamCustomLabelSheet,
  getTeamCustomLabelCategorySummary,
  getTeamCustomLabelAssetBlob,
  listTeamCustomLabels,
  updateTeamCustomLabel,
  uploadTeamCustomLabelAsset
} from '../api'

const route = useRoute()
const libraryId = route.params.libraryId
const customLabels = ref([])
const categorySummaries = ref([])
const customLabelSaving = ref(false)

onMounted(() => {
  loadCustomLabels()
  loadCategorySummaries()
})

async function loadCustomLabels() {
  try {
    customLabels.value = await listTeamCustomLabels(libraryId)
  } catch {
    customLabels.value = []
  }
}

async function loadCategorySummaries() {
  try {
    categorySummaries.value = await getTeamCustomLabelCategorySummary(libraryId)
  } catch {
    categorySummaries.value = []
  }
}

async function saveTeamCustomLabel(payload) {
  customLabelSaving.value = true
  try {
    const body = { name: payload.name || '自定义标签', content: payload.content || {} }
    const saved = payload.id
      ? await updateTeamCustomLabel(libraryId, payload.id, body)
      : await createTeamCustomLabel(libraryId, body)
    await loadCustomLabels()
    await loadCategorySummaries()
    return saved
  } finally {
    customLabelSaving.value = false
  }
}

async function archiveTeamCustomLabel(id) {
  await deleteTeamCustomLabel(libraryId, id)
  await loadCustomLabels()
  await loadCategorySummaries()
}

async function uploadTeamCustomLabelFile(id, file) {
  const asset = await uploadTeamCustomLabelAsset(libraryId, id, file)
  await loadCustomLabels()
  return asset
}

function loadTeamCustomLabelFile(assetId) {
  return getTeamCustomLabelAssetBlob(libraryId, assetId)
}

function exportTeamCustomLabelFile(payload) {
  return exportTeamCustomLabelSheet(libraryId, payload)
}
</script>

<style scoped>
.custom-label-route {
  padding: 20px;
}
</style>
