export function matchesTeamMarkerFilters(row, filters) {
  const markers = row?.markers || []
  const candidates = markers.filter((marker) => {
    if (filters.category && marker.category !== filters.category) return false
    if (filters.color && marker.color !== filters.color) return false
    return true
  })
  if ((filters.category || filters.color) && !candidates.length) return false
  if (filters.flagged === 'yes') return candidates.some((marker) => marker.flagged)
  if (filters.flagged === 'no') {
    return filters.category || filters.color
      ? candidates.some((marker) => !marker.flagged)
      : !markers.some((marker) => marker.flagged)
  }
  return true
}
