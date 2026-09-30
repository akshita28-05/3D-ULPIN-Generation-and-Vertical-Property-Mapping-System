// Default map view for the whole app.
//
// Opens on Connaught Place, Delhi -- unlike the raw Microsoft Building Footprints coverage area
// (Ashoknagar/Guna, MP -- still available below as the "Guna" preset chip, and still where the
// bulk-imported footprints actually live), Delhi CP is a spot OpenStreetMap actually maps real
// underground metro and elevated-road corridors for, so the Underground / Air-rights layers have
// something to show the moment the app opens, with no extra searching or panning needed.
// [lat, lon]
export const DEFAULT_CENTER = [28.6315, 77.2167]
export const DEFAULT_ZOOM = 15.5

// Quick "jump to" chips. Purely navigation shortcuts -- they never change the
// default view above. The pipeline is not tied to any city: it works on
// whatever area is on screen (see backend/app/routers/auto_router.py).
export const CITY_PRESETS = [
  { label: 'Delhi (CP, default)', lat: DEFAULT_CENTER[0], lon: DEFAULT_CENTER[1], zoom: DEFAULT_ZOOM },
  // The city chips open on spots where OpenStreetMap actually maps underground metro and
  // elevated corridors, so the Underground / Air-rights layers have something to show.
  { label: 'Mumbai (BKC)', lat: 19.0662, lon: 72.8690, zoom: 15.5 },
  { label: 'Hyderabad (Ameerpet)', lat: 17.4372, lon: 78.4482, zoom: 15.5 },
  { label: 'Bengaluru (Majestic)', lat: 12.9763, lon: 77.5722, zoom: 15.5 },
  // Guna, MP -- centre of the Microsoft Building Footprints data loaded for this project
  // (Ashoknagar / Guna, MP). No longer the default view, but kept as a preset since it's the one
  // spot guaranteed to already have real bulk-imported buildings to browse.
  { label: 'Guna (MP footprints)', lat: 24.8474, lon: 77.6939, zoom: 11 },
]

// The auto-mapper needs a zoomed-in view so the area is small enough to process.
export const AUTO_MAP_MIN_ZOOM = 15

export const CATEGORY_COLORS = {
  residential: '#4C8DFF',
  commercial: '#F5A524',
  mixed: '#A78BFA',
  institutional: '#34D399',
  other: '#94A3B8',
}

// Open-data infrastructure layers (see backend/app/infra/). Underground = warm / cool hues,
// air-rights = purples / pink / amber, so the two never look alike on the satellite base.
export const INFRA_COLORS = {
  metro_tunnel: '#fb923c', rail_tunnel: '#f97316', road_tunnel: '#facc15', road_underpass: '#fde047',
  pedestrian_subway: '#a3e635', culvert: '#38bdf8', storm_drain: '#0ea5e9', power_cable: '#f43f5e',
  pipeline: '#2dd4bf', underground_parking: '#a78bfa', basement: '#f472b6',
  metro: '#c084fc', elevated_rail: '#a855f7', flyover: '#e879f9', elevated_road: '#f0abfc', power_line: '#fbbf24',
}
export const INFRA_FALLBACK_COLOR = '#94a3b8'

// Minimum zoom for scanning open data (2 km grid cells) and for drawing the layers.
export const INFRA_MIN_ZOOM = 13.5