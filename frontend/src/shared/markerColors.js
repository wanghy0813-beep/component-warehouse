export const TEAM_MARKER_COLORS = Object.freeze([
  { label: '橙色', value: '#F97316' },
  { label: '红色', value: '#EF4444' },
  { label: '黄色', value: '#EAB308' },
  { label: '绿色', value: '#22C55E' },
  { label: '青色', value: '#14B8A6' },
  { label: '蓝色', value: '#3B82F6' },
  { label: '紫色', value: '#8B5CF6' },
  { label: '粉色', value: '#EC4899' }
])

export const DEFAULT_TEAM_MARKER_COLOR = TEAM_MARKER_COLORS[0].value

export function normalizeTeamMarkerColor(color) {
  const normalized = String(color || '').toUpperCase()
  return TEAM_MARKER_COLORS.some((item) => item.value === normalized)
    ? normalized
    : DEFAULT_TEAM_MARKER_COLOR
}
