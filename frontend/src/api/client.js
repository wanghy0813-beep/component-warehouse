import axios from 'axios'
import { clearStoredAuth, getValidAuthToken, refreshAuthSession, setAuthRuntimeConfig } from './authSessionApi'
import { API_BASE } from '../shared/appPaths'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || API_BASE,
  timeout: 20000
})

api.interceptors.request.use(async (config) => {
  if (String(config.url || '').endsWith('/auth/config')) return config
  const token = await getValidAuthToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error?.config
    if (error?.response?.status === 401 && config && !config._authRetried) {
      config._authRetried = true
      try {
        const session = await refreshAuthSession()
        config.headers.Authorization = `Bearer ${session.token}`
        return api.request(config)
      } catch {
        clearStoredAuth()
      }
    }
    return Promise.reject(error)
  }
)

export async function authConfig() {
  const { data } = await api.get('/auth/config')
  setAuthRuntimeConfig(data)
  return data
}

export async function getPublicComponent(code) {
  const { data } = await api.get(`/public/components/${encodeURIComponent(code)}`)
  return data
}

export async function getPublicProject(code) {
  const { data } = await api.get(`/public/projects/${encodeURIComponent(code)}`)
  return data
}

export async function getCurrentUser() {
  const { data } = await api.get('/auth/me')
  return data
}

export async function getComponentAccessContext(code) {
  const { data } = await api.get(`/components/access-context/${encodeURIComponent(code)}`)
  return data
}

export async function resolvePersonalScanBatch(values) {
  const { data } = await api.post('/mobile/v1/personal/resolve-batch', { values })
  return data
}

export async function searchPersonalScanCandidates(query) {
  const { data } = await api.get('/mobile/v1/personal/candidates', { params: { q: query, limit: 12 } })
  return data
}

export async function getCategories() {
  const { data } = await api.get('/categories')
  return data
}

export async function getComponents(params = {}) {
  const { data } = await api.get('/components', { params })
  return data
}

export async function getGroupedComponents(params = {}) {
  const { data } = await api.get('/components/grouped', { params })
  return data
}

export async function getGroupedComponentsPage(params = {}) {
  const { data } = await api.get('/components/grouped-page', { params })
  return data
}

export async function exportComponentIdTable(ids = []) {
  const { data } = await api.post('/components/export/id-table', { ids }, { responseType: 'blob' })
  return data
}

export const exportComponentInventory = () =>
  api.get('/components/export/inventory.xlsx', { responseType: 'blob' }).then((response) => response.data)

export async function exportComponentLabelSheet(ids = [], exportAll = false, options = {}) {
  const { data } = await api.post('/components/export/label-sheet', { ids, all: exportAll, output_format: 'pdf', ...options }, { responseType: 'blob' })
  return data
}

export const listCustomLabels = () =>
  api.get('/custom-labels').then((response) => response.data)

export const getCustomLabelCategorySummary = () =>
  api.get('/custom-labels/category-summary').then((response) => response.data)

export const createCustomLabel = (payload) =>
  api.post('/custom-labels', payload).then((response) => response.data)

export const updateCustomLabel = (id, payload) =>
  api.put(`/custom-labels/${id}`, payload).then((response) => response.data)

export const deleteCustomLabel = (id) =>
  api.delete(`/custom-labels/${id}`).then((response) => response.data)

export const uploadCustomLabelAsset = (id, file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/custom-labels/${id}/assets`, formData).then((response) => response.data)
}

export const getCustomLabelAssetBlob = (assetId) =>
  api.get(`/custom-labels/assets/${assetId}`, { responseType: 'blob' }).then((response) => response.data)

export const exportCustomLabelSheet = (payload) =>
  api.post('/custom-labels/export-sheet', payload, { responseType: 'blob' }).then((response) => response.data)

export async function getComponentCoverage(params = {}) {
  const { data } = await api.get('/components/coverage', { params })
  return data
}

export async function getSearchSuggestions(params = {}) {
  const { data } = await api.get('/ai/search-suggestions', { params, timeout: 45000 })
  return data
}

export async function getComponentAi(id) {
  const { data } = await api.get(`/components/${id}/ai`)
  return data
}

export async function getComponentUsageRecords(id, params = {}) {
  const { data } = await api.get(`/components/${id}/usage-records`, { params })
  return data
}

export async function getComponentLots(id) {
  const { data } = await api.get(`/components/${id}/lots`)
  return data
}

export async function createComponentLot(id, payload) {
  const { data } = await api.post(`/components/${id}/lots`, payload)
  return data
}

export async function askComponentAi(id, payload) {
  const { data } = await api.post(`/components/${id}/ai/ask`, payload, { timeout: 120000 })
  return data
}

export async function refreshComponentAi(id, payload) {
  const { data } = await api.post(`/components/${id}/ai/refresh`, payload, { timeout: 120000 })
  return data
}

export const undoLatestComponentAi = (id) =>
  api.post(`/components/${id}/ai/undo-latest`).then((response) => response.data)

export async function organizeComponent(id, force = true) {
  const { data } = await api.post(`/components/${id}/organize`, null, { params: { force }, timeout: 120000 })
  return data
}

export async function saveComponent(component) {
  if (component.id) {
    const { data } = await api.put(`/components/${component.id}`, component)
    return data
  }
  const { data } = await api.post('/components', component)
  return data
}

export async function decrementComponentQuantity(id, payload = { quantity: 1 }) {
  const { data } = await api.post(`/components/${id}/quantity/decrement`, payload)
  return data
}

export async function incrementComponentQuantity(id, payload = { quantity: 1 }) {
  const { data } = await api.post(`/components/${id}/quantity/increment`, payload)
  return data
}

export async function deleteComponent(id) {
  const { data } = await api.delete(`/components/${id}`)
  return data
}

export async function previewExcel(file) {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post('/import/excel/preview', formData)
  return data
}

export async function commitExcel(rows) {
  const { data } = await api.post('/import/excel/commit', { rows })
  return data
}

export async function previewExternalOrder(file) {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post('/import/external-order/preview', formData, { timeout: 180000 })
  return data
}

export async function commitExternalOrder(rows) {
  const { data } = await api.post('/import/external-order/commit', { rows })
  return data
}

export function downloadExternalOrderTemplate() {
  window.open(`${api.defaults.baseURL}/import/external-order/template`, '_blank')
}

export async function getOrderImportBatches(params = {}) {
  const { data } = await api.get('/import/excel/batches', { params })
  return data
}

export async function rollbackOrderImportBatch(batchId) {
  const { data } = await api.post(`/import/excel/batches/${batchId}/rollback`)
  return data
}

export async function clearDatabase(confirmText) {
  const { data } = await api.post('/admin/clear-database', { confirm_text: confirmText })
  return data
}

export async function exportDataBackup() {
  const { data } = await api.get('/admin/backup', { responseType: 'blob', timeout: 120000 })
  return data
}

export async function getDataBackups() {
  const { data } = await api.get('/admin/backups')
  return data
}

export async function inspectDataBackup(file) {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post('/admin/backup/inspect', formData, { timeout: 120000 })
  return data
}

export async function restoreDataBackup(file, confirmText) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm_text', confirmText)
  const { data } = await api.post('/admin/restore', formData, { timeout: 180000 })
  return data
}

export async function getAdminUsageDashboard() {
  const { data } = await api.get('/admin/usage-dashboard')
  return data
}

export async function previewImageImport(files) {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  const { data } = await api.post('/ai/image-import/preview', formData, { timeout: 60000 })
  return data
}

export async function dashboardSummary() {
  const { data } = await api.get('/dashboard/summary')
  return data
}

export async function getProjects() {
  const { data } = await api.get('/projects')
  return data
}

export async function saveProject(project) {
  if (project.id) {
    const { data } = await api.put(`/projects/${project.id}`, project)
    return data
  }
  const { data } = await api.post('/projects', project)
  return data
}

export async function deleteProject(id) {
  const { data } = await api.delete(`/projects/${id}`)
  return data
}

export async function createProjectBoard(projectId) {
  const { data } = await api.post(`/projects/${projectId}/boards`)
  return data
}

export async function addBomItem(projectId, item) {
  const { data } = await api.post(`/projects/${projectId}/bom`, item)
  return data
}

export async function updateBomItem(projectId, itemId, item) {
  const { data } = await api.put(`/projects/${projectId}/bom/${itemId}`, item)
  return data
}

export async function deleteBomItem(projectId, itemId) {
  const { data } = await api.delete(`/projects/${projectId}/bom/${itemId}`)
  return data
}

export async function updateBomItemStatus(projectId, itemId, payload) {
  const { data } = await api.post(`/projects/${projectId}/bom/${itemId}/status`, payload)
  return data
}

export async function updateBomSolderPoint(projectId, itemId, pointId, payload) {
  const { data } = await api.post(`/projects/${projectId}/bom/${itemId}/solder-points/${pointId}`, payload)
  return data
}

export async function updateBomSolderPointsBulk(projectId, itemId, payload) {
  const { data } = await api.post(`/projects/${projectId}/bom/${itemId}/solder-points/bulk`, payload)
  return data
}

export async function updateBoardBomSolderPoint(projectId, boardId, itemId, pointId, payload) {
  const { data } = await api.post(`/projects/${projectId}/boards/${boardId}/bom/${itemId}/solder-points/${pointId}`, payload)
  return data
}

export async function updateBoardBomSolderPointsBulk(projectId, boardId, itemId, payload) {
  const { data } = await api.post(`/projects/${projectId}/boards/${boardId}/bom/${itemId}/solder-points/bulk`, payload)
  return data
}

export async function updateBoardBomSolderPointLoss(projectId, boardId, itemId, pointId, payload) {
  const { data } = await api.post(`/projects/${projectId}/boards/${boardId}/bom/${itemId}/solder-points/${pointId}/loss`, payload)
  return data
}

export async function inspectBomFields(file) {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post('/ai/bom-match/inspect', formData)
  return data
}

export async function previewBomMatch(file, projectId, fieldMapping = null) {
  const formData = new FormData()
  formData.append('file', file)
  if (projectId) formData.append('project_id', projectId)
  if (fieldMapping) formData.append('field_mapping_json', JSON.stringify(fieldMapping))
  const { data } = await api.post('/ai/bom-match/preview', formData)
  return data
}

export async function getLatestBomImportBatch(projectId) {
  const { data } = await api.get(`/projects/${projectId}/bom/import-batch/latest`)
  return data
}

export async function importMatchedBomItems(projectId, items) {
  const { data } = await api.post(`/projects/${projectId}/bom/import-matches`, { items })
  return data
}

export async function ignoreBomImportRow(projectId, rowId) {
  const { data } = await api.post(`/projects/${projectId}/bom/import-rows/${rowId}/ignore`)
  return data
}

export async function updateBomImportRowSelection(projectId, rowId, payload) {
  const { data } = await api.post(`/projects/${projectId}/bom/import-rows/${rowId}/selection`, payload)
  return data
}

export async function createPendingComponentFromBomRow(projectId, rowId) {
  const { data } = await api.post(`/projects/${projectId}/bom/import-rows/${rowId}/pending-component`)
  return data
}

export async function exportBom(projectId, projectName) {
  const { data } = await api.get(`/projects/${projectId}/export`, { responseType: 'blob' })
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = `${projectName || `project-${projectId}`}-bom.csv`
  link.click()
  URL.revokeObjectURL(url)
}

export async function exportPurchaseBom(projectId, projectName) {
  const { data } = await api.get(`/projects/${projectId}/purchase-bom/export`, { responseType: 'blob' })
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = `${projectName || `project-${projectId}`}-purchase-bom.xlsx`
  link.click()
  URL.revokeObjectURL(url)
}

export async function aiClassify(payload) {
  const { data } = await api.post('/ai/classify', payload)
  return data
}

export async function aiExplain(payload) {
  const { data } = await api.post('/ai/explain', payload)
  return data
}

export async function aiProjectPlan(payload) {
  const { data } = await api.post('/ai/project-plan', payload)
  return data
}

export async function aiComponentSearch(payload) {
  const { data } = await api.post('/ai/component-search', payload)
  return data
}

export async function aiComponentInfo(payload) {
  const { data } = await api.post('/ai/component-info', payload)
  return data
}

export async function getActivityLogs(params = {}) {
  const { data } = await api.get('/activity-logs', { params })
  return data
}

export async function recordUsageEvent(payload) {
  const { data } = await api.post('/usage-events', payload)
  return data
}

export async function getAiTaskSummary() {
  const { data } = await api.get('/ai/tasks/summary')
  return data
}

export async function getAiTasks(params = {}) {
  const { data } = await api.get('/ai/tasks', { params })
  return data
}

export async function enqueueMissingAiTasks() {
  const { data } = await api.post('/ai/tasks/enqueue-missing')
  return data
}

export async function enqueueOrganizeAiTasks(force = false) {
  const { data } = await api.post('/ai/tasks/enqueue-organize', null, { params: { force } })
  return data
}

export async function resetAndReorganize() {
  const { data } = await api.post('/ai/reset-and-reorganize')
  return data
}

export async function startAiTasks() {
  const { data } = await api.post('/ai/tasks/start')
  return data
}

export async function pauseAiTasks() {
  const { data } = await api.post('/ai/tasks/pause')
  return data
}

export async function analyzeProjectBom(projectId, force = false) {
  const { data } = await api.post(`/projects/${projectId}/ai/analyze-bom`, null, { params: { force } })
  return data
}

export async function planProject(projectId, payload) {
  const { data } = await api.post(`/projects/${projectId}/ai/plan`, payload)
  return data
}

export async function consultProject(projectId, payload) {
  const { data } = await api.post(`/projects/${projectId}/ai/consult`, payload, { timeout: 60000 })
  return data
}
