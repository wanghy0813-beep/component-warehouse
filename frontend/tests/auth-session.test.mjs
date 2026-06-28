import test from 'node:test'
import assert from 'node:assert/strict'
import { shouldRefreshAccess } from '../src/shared/authSession.js'

test('access token refreshes before expiry and when missing', () => {
  const now = Date.parse('2026-06-19T12:00:00Z')
  assert.equal(shouldRefreshAccess('2026-06-19T12:10:00Z', true, now), false)
  assert.equal(shouldRefreshAccess('2026-06-19T12:00:30Z', true, now), true)
  assert.equal(shouldRefreshAccess('', false, now), true)
})
