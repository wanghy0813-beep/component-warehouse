import test from 'node:test'
import assert from 'node:assert/strict'
import {
  clearAccountSnapshots,
  readSnapshot,
  writeSnapshot
} from '../src/team/cache.js'

test('team cache degrades safely when IndexedDB is unavailable', async () => {
  assert.equal(globalThis.indexedDB, undefined)
  assert.equal(await writeSnapshot('user', 'library', 'components', []), false)
  assert.equal(await readSnapshot('user', 'library', 'components'), null)
  assert.equal(await clearAccountSnapshots('user'), false)
})
