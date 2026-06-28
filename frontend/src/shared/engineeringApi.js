import { api } from '../api/client'

const TEAM_API_PREFIX = '/team'
const scopeBase = (libraryId, module) =>
  libraryId
    ? `${TEAM_API_PREFIX}/libraries/${encodeURIComponent(libraryId)}/${module}`
    : `/${module}`

export const engineeringSummary = (libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/summary`).then((response) => response.data)

export const listEdaLibraries = (libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/libraries`).then((response) => response.data)

export const createEdaLibrary = (payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/libraries`, payload).then((response) => response.data)

export const ensureEdaWorkspace = (libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/workspace`).then((response) => response.data)

export const listEdaComponentOptions = (query = '', libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/component-options`, { params: { q: query, limit: 30 } }).then((response) => response.data)

export const createQuickEdaBinding = (payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/quick-bindings`, payload).then((response) => response.data)

export const createEdaVersion = (edaLibraryId, payload, libraryId = '') => {
  const base = scopeBase(libraryId, 'eda')
  return api.post(`${base}/libraries/${edaLibraryId}/versions`, payload).then((response) => response.data)
}

export const checkEdaVersionPublish = (versionId, libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/versions/${versionId}/publish-check`).then((response) => response.data)

export const publishEdaVersion = (versionId, libraryId = '', confirmRisks = false) =>
  api.post(`${scopeBase(libraryId, 'eda')}/versions/${versionId}/publish`, null, {
    params: { confirm_risks: confirmRisks }
  }).then((response) => response.data)

export const createEdaObject = (versionId, kind, payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/versions/${versionId}/${kind}`, payload).then((response) => response.data)

export const listEdaObjects = (versionId, libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/versions/${versionId}/objects`).then((response) => response.data)

export const listEdaAssets = (libraryId = '', status = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/assets`, { params: status ? { status } : {} }).then((response) => response.data)

export const listEntityAssets = (entityType, entityId, libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/attachments/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`).then((response) => response.data)

export async function stageEdaUpload(file, libraryId = '') {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`${scopeBase(libraryId, 'eda')}/uploads/stage`, form, {
    timeout: 10 * 60 * 1000
  })
  return data
}

export const stageEdaRemote = (url, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/uploads/download`, { url }, { timeout: 120000 }).then((response) => response.data)

export const publishEdaAsset = (payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/assets`, payload).then((response) => response.data)

export const archiveEdaAsset = (assetId, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/assets/${assetId}/archive`).then((response) => response.data)

export const restoreEdaAsset = (assetId, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/assets/${assetId}/restore`).then((response) => response.data)

export const edaAssetDownloadUrl = (assetId, libraryId = '') =>
  `${api.defaults.baseURL}${scopeBase(libraryId, 'eda')}/assets/${assetId}/download`

export const downloadEdaAsset = (assetId, libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/assets/${assetId}/download`, { responseType: 'blob' }).then((response) => response.data)

export const listEdaBindings = (componentId = null, libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/bindings`, {
    params: componentId ? { component_id: componentId } : {}
  }).then((response) => response.data)

export const createEdaBinding = (payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/bindings`, payload).then((response) => response.data)

export const verifyEdaBinding = (bindingId, payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/bindings/${bindingId}/verify`, payload).then((response) => response.data)

export const listSupplierParts = (componentId = null, libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/supplier-parts`, {
    params: componentId ? { component_id: componentId } : {}
  }).then((response) => response.data)

export const createSupplierPart = (payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/supplier-parts`, payload).then((response) => response.data)

export const createSyncToken = (payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'eda')}/sync-tokens`, payload).then((response) => response.data)

export const listSyncTokens = (libraryId = '') =>
  api.get(`${scopeBase(libraryId, 'eda')}/sync-tokens`).then((response) => response.data)

export const revokeSyncToken = (tokenId, libraryId = '') =>
  api.delete(`${scopeBase(libraryId, 'eda')}/sync-tokens/${tokenId}`).then((response) => response.data)

export const listPurchases = (libraryId = '') =>
  api.get(scopeBase(libraryId, 'purchases')).then((response) => response.data)

export const createPurchase = (payload, libraryId = '') =>
  api.post(scopeBase(libraryId, 'purchases'), payload).then((response) => response.data)

export const generateProjectPurchase = (projectId, payload = {}, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'purchases')}/from-project/${projectId}`, payload).then((response) => response.data)

export const addPurchaseLine = (orderId, payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'purchases')}/${orderId}/lines`, payload).then((response) => response.data)

export const receivePurchaseLine = (lineId, payload, libraryId = '') =>
  api.post(`${scopeBase(libraryId, 'purchases')}/lines/${lineId}/receive`, payload).then((response) => response.data)

export const listRisks = (libraryId = '') =>
  api.get(scopeBase(libraryId, 'risks')).then((response) => response.data)

export const createRiskIssue = (payload, libraryId = '') =>
  api.post(scopeBase(libraryId, 'risks'), payload).then((response) => response.data)

export const updateRiskIssue = (issueId, payload, libraryId = '') =>
  api.patch(`${scopeBase(libraryId, 'risks')}/${issueId}`, payload).then((response) => response.data)

export const listTeamProjects = (libraryId) =>
  api.get(`${TEAM_API_PREFIX}/libraries/${libraryId}/projects`).then((response) => response.data)

export const createTeamProject = (libraryId, payload) =>
  api.post(`${TEAM_API_PREFIX}/libraries/${libraryId}/projects`, payload).then((response) => response.data)

export const addTeamBomItem = (libraryId, projectId, payload) =>
  api.post(`${TEAM_API_PREFIX}/libraries/${libraryId}/projects/${projectId}/bom`, payload).then((response) => response.data)

export const exportTeamProjectBom = (libraryId, projectId, shortageOnly = false) =>
  api.get(
    `${TEAM_API_PREFIX}/libraries/${libraryId}/projects/${projectId}/${shortageOnly ? 'shortage/export' : 'export'}`,
    { responseType: 'blob' }
  ).then((response) => response.data)

export async function inspectTeamBom(libraryId, projectId, file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`${TEAM_API_PREFIX}/libraries/${libraryId}/projects/${projectId}/bom/inspect`, form, {
    timeout: 120000
  })
  return data
}

export async function importTeamBom(libraryId, projectId, file, fieldMapping = null) {
  const form = new FormData()
  form.append('file', file)
  if (fieldMapping) form.append('field_mapping_json', JSON.stringify(fieldMapping))
  const { data } = await api.post(`${TEAM_API_PREFIX}/libraries/${libraryId}/projects/${projectId}/bom/import`, form, {
    timeout: 120000
  })
  return data
}

export const commitTeamBom = (libraryId, projectId, batchId, items) =>
  api.post(
    `${TEAM_API_PREFIX}/libraries/${libraryId}/projects/${projectId}/bom/import/${batchId}/commit`,
    { items }
  ).then((response) => response.data)
