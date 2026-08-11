const TRANSIT_LOCATION_LABELS = new Set([
  '运输中',
  '在途',
  '快递中',
  '配送中',
  '物流中',
  '物流运输中'
])

export function isDurableEquipment(item) {
  const category = typeof item?.category === 'string' ? item.category : item?.category?.name
  const warehouseCode = String(item?.warehouse_code || item?.warehouse_code_snapshot || '').trim().toUpperCase()
  return category === '设备' || warehouseCode.startsWith('EQP-')
}

export function visibleInventoryLocation(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return TRANSIT_LOCATION_LABELS.has(text.replace(/\s+/g, '')) ? '' : text
}

export function inventoryQuantityCopy(item) {
  if (isDurableEquipment(item)) {
    return {
      totalLabel: '登记',
      availableLabel: '可用',
      unit: '台',
      actionLabel: '占用 1 台'
    }
  }
  return {
    totalLabel: '总量',
    availableLabel: '可用',
    unit: '个',
    actionLabel: '领用 1 个'
  }
}
