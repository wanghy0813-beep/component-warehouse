import test from 'node:test'
import assert from 'node:assert/strict'

import { applyInventoryLotConsumption } from '../src/shared/inventoryLotState.js'

test('inventory lot consumption updates only the target lot without mutating source data', () => {
  const lots = [
    { id: 'lot-1', remaining_quantity: 3, can_delete: true },
    { id: 'lot-2', remaining_quantity: 8, can_delete: true }
  ]

  const updated = applyInventoryLotConsumption(lots, 'lot-1', 1)

  assert.equal(updated[0].remaining_quantity, 2)
  assert.equal(updated[0].can_delete, false)
  assert.match(updated[0].delete_block_reason, /已经发生扣减/)
  assert.equal(updated[1], lots[1])
  assert.equal(lots[0].remaining_quantity, 3)
})

test('inventory lot consumption never shows a negative remaining quantity', () => {
  const updated = applyInventoryLotConsumption([{ id: 'lot-1', remaining_quantity: 1 }], 'lot-1', 3)
  assert.equal(updated[0].remaining_quantity, 0)
})
