import test from 'node:test'
import assert from 'node:assert/strict'
import { matchesTeamMarkerFilters } from '../src/shared/teamFilters.js'

const row = {
  markers: [
    { category: '需复核', color: '#F97316', flagged: true },
    { category: '常用', color: '#22C55E', flagged: false }
  ]
}

test('team marker filters combine category, color and flag state', () => {
  assert.equal(matchesTeamMarkerFilters(row, { category: '需复核', color: '#F97316', flagged: 'yes' }), true)
  assert.equal(matchesTeamMarkerFilters(row, { category: '常用', color: '#F97316', flagged: '' }), false)
  assert.equal(matchesTeamMarkerFilters(row, { category: '', color: '', flagged: 'no' }), false)
  assert.equal(matchesTeamMarkerFilters({ markers: [] }, { category: '', color: '', flagged: 'no' }), true)
})
