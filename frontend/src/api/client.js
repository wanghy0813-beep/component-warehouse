import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || `${import.meta.env.BASE_URL}api`,
  timeout: 20000
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('cw_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export async function authConfig() {
  const { data } = await api.get('/auth/config')
  return data
}

export async function login(password) {
  const { data } = await api.post('/auth/login', { password })
  localStorage.setItem('cw_token', data.token)
  return data
}

export function logout() {
  localStorage.removeItem('cw_token')
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

export async function refreshComponentAi(id, payload) {
  const { data } = await api.post(`/components/${id}/ai/refresh`, payload)
  return data
}

export async function organizeComponent(id, force = true) {
  const { data } = await api.post(`/components/${id}/organize`, null, { params: { force } })
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

export async function previewBomMatch(file, projectId) {
  const formData = new FormData()
  formData.append('file', file)
  if (projectId) formData.append('project_id', projectId)
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
