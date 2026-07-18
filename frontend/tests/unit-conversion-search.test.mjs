import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'


const cardSource = readFileSync(new URL('../src/components/inventory/InventoryComponentCard.vue', import.meta.url), 'utf8')


test('inventory cards label results matched through equivalent unit conversion', () => {
  assert.match(cardSource, /item\.search_unit_conversion/)
  assert.match(cardSource, /等值换算/)
  assert.match(cardSource, /search_unit_conversion\.label/)
})
