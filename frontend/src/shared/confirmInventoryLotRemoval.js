import { ElMessageBox } from './elementApi'

const CONFIRMATION_TEXT = '去除库存'

export async function confirmInventoryLotRemoval(lot, displayName) {
  const quantity = Math.max(0, Number(lot?.initial_quantity || 0))
  const label = displayName || lot?.source_reference || lot?.source_type || '库存批次'

  await ElMessageBox.confirm(
    `确认去除库存记录「${label}」？器件总库存将同步减少 ${quantity}，该操作会写入审计流水。`,
    '确认去除库存记录',
    { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' }
  )

  await ElMessageBox.prompt(
    `这是第二次确认。请输入“${CONFIRMATION_TEXT}”后继续；批次将退出有效库存，但原记录与流水仍会保留用于审计。`,
    '二次确认去除库存',
    {
      type: 'warning',
      confirmButtonText: '确认去除',
      cancelButtonText: '取消',
      inputPlaceholder: CONFIRMATION_TEXT,
      inputValidator: (value) => String(value || '').trim() === CONFIRMATION_TEXT || `请输入：${CONFIRMATION_TEXT}`,
    }
  )
}
