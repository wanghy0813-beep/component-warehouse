export function applyInventoryLotConsumption(lots, lotId, quantity = 1) {
  const consumedQuantity = Math.max(0, Number(quantity || 0))
  const targetId = String(lotId || '')
  return (lots || []).map((lot) => {
    if (String(lot?.id || '') !== targetId) return lot
    return {
      ...lot,
      remaining_quantity: Math.max(0, Number(lot.remaining_quantity || 0) - consumedQuantity),
      can_delete: false,
      delete_block_reason: '该批次已经发生扣减，需保留库存流水'
    }
  })
}
