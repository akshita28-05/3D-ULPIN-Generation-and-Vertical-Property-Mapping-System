export const DEFAULT_CENTER = [24.8474, 77.6939]
export const DEFAULT_ZOOM = 11

export const CITY_PRESETS = [
  { label: 'Guna (default)', lat: DEFAULT_CENTER[0], lon: DEFAULT_CENTER[1], zoom: DEFAULT_ZOOM },
  { label: 'Mumbai (BKC)', lat: 19.0662, lon: 72.8690, zoom: 15.5 },
  { label: 'Hyderabad (Ameerpet)', lat: 17.4372, lon: 78.4482, zoom: 15.5 },
  { label: 'Bengaluru (Majestic)', lat: 12.9763, lon: 77.5722, zoom: 15.5 },
  { label: 'Delhi (CP)', lat: 28.6315, lon: 77.2167, zoom: 15.5 },
]

export const AUTO_MAP_MIN_ZOOM = 15

export const CATEGORY_COLORS = {
  residential: '#4C8DFF',
  commercial: '#F5A524',
  mixed: '#A78BFA',
  institutional: '#34D399',
  other: '#94A3B8',
}

export const INFRA_COLORS = {
  metro_tunnel: '#fb923c', rail_tunnel: '#f97316', road_tunnel: '#facc15', road_underpass: '#fde047',
  pedestrian_subway: '#a3e635', culvert: '#38bdf8', storm_drain: '#0ea5e9', power_cable: '#f43f5e',
  pipeline: '#2dd4bf', underground_parking: '#a78bfa', basement: '#f472b6',
  metro: '#c084fc', elevated_rail: '#a855f7', flyover: '#e879f9', elevated_road: '#f0abfc', power_line: '#fbbf24',
}
export const INFRA_FALLBACK_COLOR = '#94a3b8'

export const INFRA_MIN_ZOOM = 13.5
