import axios from 'axios'
import { clearStoredAuth, getValidAuthToken, refreshAuthSession } from '../api/authSessionApi'
import { markServiceAvailable, markServiceUnavailable } from './store'
import { API_BASE } from '../shared/appPaths'

export const teamApi = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || API_BASE,
  timeout: 20000
})

teamApi.interceptors.request.use(async (config) => {
  const token = await getValidAuthToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

teamApi.interceptors.response.use(
  (response) => {
    if (String(response?.config?.url || '').startsWith(base)) markServiceAvailable()
    return response
  },
  async (error) => {
    const detail = String(error?.response?.data?.detail || '')
    if (error?.response?.status === 503 && detail.includes('统一账号')) markServiceUnavailable()
    const config = error?.config
    if (error?.response?.status === 401 && config && !config._authRetried) {
      config._authRetried = true
      try {
        const session = await refreshAuthSession()
        config.headers.Authorization = `Bearer ${session.token}`
        return teamApi.request(config)
      } catch {
        clearStoredAuth()
      }
    }
    return Promise.reject(error)
  }
)

const base = '/team'

export const teamSession = () => teamApi.get(`${base}/session`).then((r) => r.data)
export const listLibraries = () => teamApi.get(`${base}/libraries`).then((r) => r.data)
export const createLibrary = (payload) => teamApi.post(`${base}/libraries`, payload).then((r) => r.data)
export const getLibrary = (id) => teamApi.get(`${base}/libraries/${id}`).then((r) => r.data)
export const updateLibrary = (id, payload) => teamApi.put(`${base}/libraries/${id}`, payload).then((r) => r.data)

export const previewInvite = (token) => teamApi.get(`${base}/invites/${encodeURIComponent(token)}`).then((r) => r.data)
export const joinInvite = (token) => teamApi.post(`${base}/invites/${encodeURIComponent(token)}/join`).then((r) => r.data)
export const getInvite = (id) => teamApi.get(`${base}/libraries/${id}/invite`).then((r) => r.data)
export const getInviteQr = (id) => teamApi.get(`${base}/libraries/${id}/invite/qr.svg`, { responseType: 'blob' }).then((r) => r.data)
export const resetInvite = (id) => teamApi.post(`${base}/libraries/${id}/invite/reset`).then((r) => r.data)

export const listMembers = (id) => teamApi.get(`${base}/libraries/${id}/members`).then((r) => r.data)
export const updateMemberRole = (id, userId, role) => teamApi.put(`${base}/libraries/${id}/members/${userId}/role`, { role }).then((r) => r.data)
export const removeMember = (id, userId) => teamApi.delete(`${base}/libraries/${id}/members/${userId}`).then((r) => r.data)
export const unblockMember = (id, userId) => teamApi.post(`${base}/libraries/${id}/members/${userId}/unblock`).then((r) => r.data)

export const listComponents = (id, params = {}, config = {}) => teamApi.get(`${base}/libraries/${id}/components`, { ...config, params }).then((r) => r.data)
export const createComponent = (id, payload) => teamApi.post(`${base}/libraries/${id}/components`, payload).then((r) => r.data)
export const updateComponent = (id, itemId, payload) => teamApi.put(`${base}/libraries/${id}/components/${itemId}`, payload).then((r) => r.data)
export const deleteComponent = (id, itemId) => teamApi.delete(`${base}/libraries/${id}/components/${itemId}`).then((r) => r.data)
export const bulkAddComponents = (id, items) => teamApi.post(`${base}/libraries/${id}/components/bulk`, { items }).then((r) => r.data)
export const updateComponentQuantity = (id, itemId, payload) => teamApi.patch(`${base}/libraries/${id}/components/${itemId}/quantity`, payload).then((r) => r.data)
export const listTeamComponentLots = (id, itemId) => teamApi.get(`${base}/libraries/${id}/components/${itemId}/lots`).then((r) => r.data)
export const createTeamComponentLot = (id, itemId, payload) => teamApi.post(`${base}/libraries/${id}/components/${itemId}/lots`, payload).then((r) => r.data)
export const decrementTeamComponentQuantity = (id, itemId, payload) => teamApi.post(`${base}/libraries/${id}/components/${itemId}/quantity/decrement`, payload).then((r) => r.data)
export const askTeamComponentAi = (id, itemId, payload) => teamApi.post(`${base}/libraries/${id}/components/${itemId}/ai/ask`, payload, { timeout: 120000 }).then((r) => r.data)
export const listTeamComponentUsage = (id, itemId, params = {}) => teamApi.get(`${base}/libraries/${id}/components/${itemId}/usage-records`, { params }).then((r) => r.data)
export const listComponentMarkers = (id, itemId) => teamApi.get(`${base}/libraries/${id}/components/${itemId}/markers`).then((r) => r.data)
export const createComponentMarker = (id, itemId, payload) => teamApi.post(`${base}/libraries/${id}/components/${itemId}/markers`, payload).then((r) => r.data)
export const updateComponentMarker = (id, itemId, markerId, payload) => teamApi.put(`${base}/libraries/${id}/components/${itemId}/markers/${markerId}`, payload).then((r) => r.data)
export const deleteComponentMarker = (id, itemId, markerId) => teamApi.delete(`${base}/libraries/${id}/components/${itemId}/markers/${markerId}`).then((r) => r.data)
export const linkComponent = (id, itemId, cwComponentId) => teamApi.post(`${base}/libraries/${id}/components/${itemId}/link`, { cw_component_id: cwComponentId }).then((r) => r.data)
export const rebindComponent = (id, itemId, cwComponentId) => teamApi.post(`${base}/libraries/${id}/components/${itemId}/rebind`, { cw_component_id: cwComponentId }).then((r) => r.data)
export const searchCwComponents = (params = {}) => teamApi.get(`${base}/cw-components`, { params }).then((r) => r.data)
export const resolveCwCode = (code) => teamApi.get(`${base}/resolve-code`, { params: { code } }).then((r) => r.data)
export const resolveTeamScanBatch = (id, values) =>
  teamApi.post(`/mobile/v1/team/libraries/${id}/resolve-batch`, { values }).then((r) => r.data)
export const searchTeamScanCandidates = (id, query) =>
  teamApi.get(`/mobile/v1/team/libraries/${id}/candidates`, { params: { q: query, limit: 12 } }).then((r) => r.data)
export const getTeamScannedComponent = (id, itemId) =>
  teamApi.get(`/mobile/v1/team/libraries/${id}/components/${itemId}`).then((r) => r.data)
export const exportTeamComponentLabels = (id, options = {}) =>
  teamApi.post(`${base}/libraries/${id}/components/export/label-sheet`, { output_format: 'pdf', ...options }, { responseType: 'blob' }).then((r) => r.data)
export const exportTeamComponentInventory = (id) =>
  teamApi.get(`${base}/libraries/${id}/components/export/inventory.xlsx`, { responseType: 'blob' }).then((r) => r.data)
export const listTeamCustomLabels = (id) =>
  teamApi.get(`${base}/libraries/${id}/custom-labels`).then((r) => r.data)
export const getTeamCustomLabelCategorySummary = (id) =>
  teamApi.get(`${base}/libraries/${id}/custom-labels/category-summary`).then((r) => r.data)
export const createTeamCustomLabel = (id, payload) =>
  teamApi.post(`${base}/libraries/${id}/custom-labels`, payload).then((r) => r.data)
export const updateTeamCustomLabel = (id, templateId, payload) =>
  teamApi.put(`${base}/libraries/${id}/custom-labels/${templateId}`, payload).then((r) => r.data)
export const deleteTeamCustomLabel = (id, templateId) =>
  teamApi.delete(`${base}/libraries/${id}/custom-labels/${templateId}`).then((r) => r.data)
export const uploadTeamCustomLabelAsset = (id, templateId, file) => {
  const form = new FormData()
  form.append('file', file)
  return teamApi.post(`${base}/libraries/${id}/custom-labels/${templateId}/assets`, form).then((r) => r.data)
}
export const getTeamCustomLabelAssetBlob = (id, assetId) =>
  teamApi.get(`${base}/libraries/${id}/custom-labels/assets/${assetId}`, { responseType: 'blob' }).then((r) => r.data)
export const exportTeamCustomLabelSheet = (id, payload) =>
  teamApi.post(`${base}/libraries/${id}/custom-labels/export-sheet`, payload, { responseType: 'blob' }).then((r) => r.data)
export const importComponents = (id, file) => {
  const form = new FormData()
  form.append('file', file)
  return teamApi.post(`${base}/libraries/${id}/components/import`, form).then((r) => r.data)
}

export const listPcbs = (id, params = {}, config = {}) => teamApi.get(`${base}/libraries/${id}/pcbs`, { ...config, params }).then((r) => r.data)
export const createPcb = (id, payload) => teamApi.post(`${base}/libraries/${id}/pcbs`, payload).then((r) => r.data)
export const updatePcb = (id, pcbId, payload) => teamApi.put(`${base}/libraries/${id}/pcbs/${pcbId}`, payload).then((r) => r.data)
export const deletePcb = (id, pcbId) => teamApi.delete(`${base}/libraries/${id}/pcbs/${pcbId}`).then((r) => r.data)
export const uploadPcbImage = (id, pcbId, side, file) => {
  const form = new FormData()
  form.append('file', file)
  return teamApi.post(`${base}/libraries/${id}/pcbs/${pcbId}/images/${side}`, form).then((r) => r.data)
}
export const fetchPcbImage = (id, pcbId, side) =>
  teamApi.get(`${base}/libraries/${id}/pcbs/${pcbId}/images/${side}`, { responseType: 'blob' }).then((r) => r.data)

export const listLogs = (id, params = {}) => teamApi.get(`${base}/libraries/${id}/logs`, { params }).then((r) => r.data)
export const recordTeamUsageEvent = (id, payload) => teamApi.post(`${base}/libraries/${id}/usage-events`, payload).then((r) => r.data)
export const runTeamAi = (id, payload) => teamApi.post(`${base}/libraries/${id}/ai`, payload, { timeout: 120000 }).then((r) => r.data)
export const aiComponentInfo = (payload) => teamApi.post('/ai/component-info', payload, { timeout: 120000 }).then((r) => r.data)
export const previewLcscComponent = (rawText, config = {}) =>
  teamApi.post('/components/lcsc/preview', { raw_text: rawText }, { ...config, timeout: 150000 }).then((r) => r.data)

export const teamImportTemplateUrl = `${teamApi.defaults.baseURL}${base}/import-template.csv`
