import test from 'node:test'
import assert from 'node:assert/strict'

import { isoWeekLabel, shortMonthDay, weekBadge } from '../src/shared/projectDates.js'

test('project dates calculate ISO weeks including year boundaries', () => {
  assert.equal(isoWeekLabel('2026-08-10'), '2026W33')
  assert.equal(isoWeekLabel('2026-08-18'), '2026W34')
  assert.equal(isoWeekLabel('2027-01-01'), '2026W53')
  assert.equal(isoWeekLabel('2027-01-04'), '2027W01')
})

test('project date helpers keep date and week labels compact', () => {
  assert.equal(shortMonthDay('2026-08-10'), '08/10')
  assert.equal(weekBadge('2026-08-10'), '（2026W33）')
  assert.equal(weekBadge(''), '（待填写）')
})
