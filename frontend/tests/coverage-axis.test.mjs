import test from 'node:test'
import assert from 'node:assert/strict'
import { createCoverageAxis, layoutCoveragePointLabels } from '../src/shared/coverageAxis.js'

test('resistance coverage compresses zero and sub-ohm values before decade bands', () => {
  const axis = createCoverageAxis([0, 0.01, 1, 10, 100, 1_000, 10_000, 100_000, 1_000_000], '电阻')

  assert.equal(axis.kind, 'resistance-decades')
  assert.equal(axis.position(0), 2)
  assert.ok(axis.position(0.01) >= 4 && axis.position(0.01) <= 10)
  assert.equal(axis.position(1), 12)
  assert.ok(axis.position(1) - axis.position(0) <= 10)
  assert.ok(Math.abs((axis.position(10) - axis.position(1)) - (axis.position(100) - axis.position(10))) < 0.001)
  assert.deepEqual(axis.ticks.slice(0, 2).map((tick) => tick.label), ['0Ω', '<1Ω'])
  assert.deepEqual(axis.buckets.slice(0, 2).map((bucket) => bucket.label), ['0Ω', '<1Ω'])
})

test('capacitor and inductor coverage retain data-range logarithmic scaling', () => {
  const axis = createCoverageAxis([1e-12, 1e-9, 1e-6], '电容')

  assert.equal(axis.kind, 'logarithmic')
  assert.equal(axis.position(1e-12), 0)
  assert.equal(axis.position(1e-6), 100)
  assert.ok(axis.position(1e-9) > 49.9 && axis.position(1e-9) < 50.1)
})

test('dense resistor values receive separate label rows instead of overlapping', () => {
  const axis = createCoverageAxis([22_000, 33_000, 39_000, 47_000, 1_000_000], '电阻')
  const layout = layoutCoveragePointLabels(
    [22_000, 33_000, 39_000, 47_000].map((value) => ({ value, left: axis.position(value) }))
  )

  assert.equal(layout.points.every((point) => point.showLabel), true)
  assert.ok(layout.rows >= 2)
  for (const row of new Set(layout.points.map((point) => point.labelRow))) {
    const positions = layout.points.filter((point) => point.labelRow === row).map((point) => point.left)
    for (let index = 1; index < positions.length; index += 1) {
      assert.ok(positions[index] - positions[index - 1] >= 4)
    }
  }
  assert.ok(layout.trackHeight > 60)
})
