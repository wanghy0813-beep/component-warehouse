const clamp = (value, min, max) => Math.max(min, Math.min(max, value))

function finiteValues(values, { includeZero = false } = {}) {
  return values
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && (includeZero ? value >= 0 : value > 0))
}

function createEmptyAxis() {
  return {
    kind: 'empty',
    ticks: [],
    buckets: [],
    position: () => 0,
    bucketIndex: () => -1,
  }
}

function createLogAxis(values) {
  const positive = finiteValues(values)
  if (!positive.length) return createEmptyAxis()

  const min = Math.log10(Math.min(...positive))
  const max = Math.log10(Math.max(...positive))
  const spread = Math.max(max - min, 0.0001)
  const tickCount = Math.min(6, Math.max(3, Math.ceil(max - min) + 2))
  const bucketCount = Math.min(8, Math.max(4, Math.ceil(spread * 1.4)))
  const ticks = Array.from({ length: tickCount }, (_, index) => {
    const ratio = tickCount === 1 ? 0 : index / (tickCount - 1)
    return {
      left: Math.round(ratio * 10000) / 100,
      value: Math.pow(10, min + (max - min) * ratio),
      guide: index > 0 && index < tickCount - 1,
    }
  })
  const buckets = Array.from({ length: bucketCount }, (_, index) => ({
    start: Math.pow(10, min + spread * (index / bucketCount)),
    end: Math.pow(10, min + spread * ((index + 1) / bucketCount)),
  }))

  return {
    kind: 'logarithmic',
    ticks,
    buckets,
    position(value) {
      const numeric = Number(value)
      if (!Number.isFinite(numeric) || numeric <= 0) return 0
      return clamp(((Math.log10(numeric) - min) / spread) * 100, 0, 100)
    },
    bucketIndex(value) {
      const numeric = Number(value)
      if (!Number.isFinite(numeric) || numeric <= 0) return -1
      return clamp(Math.floor(((Math.log10(numeric) - min) / spread) * bucketCount), 0, bucketCount - 1)
    },
  }
}

function createResistanceAxis(values) {
  const resistances = finiteValues(values, { includeZero: true })
  if (!resistances.length) return createEmptyAxis()

  const hasZero = resistances.some((value) => value === 0)
  const subOhm = resistances.filter((value) => value > 0 && value < 1)
  const positive = resistances.filter((value) => value > 0)
  const maximum = Math.max(1, ...positive)
  const maxExponent = Math.max(1, Math.ceil(Math.log10(maximum)))
  const minSubExponent = subOhm.length
    ? Math.min(-1, Math.floor(Math.log10(Math.min(...subOhm))))
    : -1
  const mainStart = 12
  const mainEnd = 98
  const mainSpan = mainEnd - mainStart
  const buckets = []

  if (hasZero) buckets.push({ kind: 'zero', label: '0Ω' })
  if (subOhm.length) buckets.push({ kind: 'sub-ohm', label: '<1Ω' })
  for (let exponent = 0; exponent < maxExponent; exponent += 1) {
    buckets.push({
      kind: 'range',
      start: Math.pow(10, exponent),
      end: Math.pow(10, exponent + 1),
      includeEnd: exponent === maxExponent - 1,
    })
  }

  const ticks = []
  if (hasZero) ticks.push({ left: 2, label: '0Ω', guide: false })
  if (subOhm.length) ticks.push({ left: 7, label: '<1Ω', guide: true })
  for (let exponent = 0; exponent <= maxExponent; exponent += 1) {
    ticks.push({
      left: mainStart + (exponent / maxExponent) * mainSpan,
      value: Math.pow(10, exponent),
      guide: exponent < maxExponent,
    })
  }

  return {
    kind: 'resistance-decades',
    ticks,
    buckets,
    position(value) {
      const numeric = Number(value)
      if (!Number.isFinite(numeric) || numeric < 0) return 0
      if (numeric === 0) return 2
      if (numeric < 1) {
        const ratio = (Math.log10(numeric) - minSubExponent) / -minSubExponent
        return clamp(4 + ratio * 6, 4, 10)
      }
      return clamp(mainStart + (Math.log10(numeric) / maxExponent) * mainSpan, mainStart, mainEnd)
    },
    bucketIndex(value) {
      const numeric = Number(value)
      if (!Number.isFinite(numeric) || numeric < 0) return -1
      return buckets.findIndex((bucket) => {
        if (bucket.kind === 'zero') return numeric === 0
        if (bucket.kind === 'sub-ohm') return numeric > 0 && numeric < 1
        if (bucket.kind !== 'range') return false
        return numeric >= bucket.start && (numeric < bucket.end || (bucket.includeEnd && numeric <= bucket.end))
      })
    },
  }
}

export function createCoverageAxis(values, category) {
  return ['电阻', '贴片电阻', '直插/采样电阻'].includes(category) ? createResistanceAxis(values) : createLogAxis(values)
}

export function layoutCoveragePointLabels(points, { minimumGap = 4, maximumRows = 4 } = {}) {
  const rowEnds = Array.from({ length: maximumRows }, () => Number.NEGATIVE_INFINITY)
  let usedRows = 1
  const laidOut = [...points]
    .sort((left, right) => left.left - right.left)
    .map((point) => {
      const row = rowEnds.findIndex((lastLeft) => point.left - lastLeft >= minimumGap)
      if (row < 0) return { ...point, showLabel: false, labelRow: maximumRows - 1 }
      rowEnds[row] = point.left
      usedRows = Math.max(usedRows, row + 1)
      return { ...point, showLabel: true, labelRow: row }
    })

  return {
    points: laidOut,
    rows: usedRows,
    trackHeight: 34 + usedRows * 12,
  }
}
