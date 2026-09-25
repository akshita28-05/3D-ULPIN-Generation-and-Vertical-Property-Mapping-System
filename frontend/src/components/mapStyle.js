import { CATEGORY_COLORS, INFRA_COLORS, INFRA_FALLBACK_COLOR } from '../config/region.js'

export const EMPTY = { type: 'FeatureCollection', features: [] }
export const REGION_MIN_ZOOM = 14
export const INFRA_LAYER_IDS = ['air-deck', 'air-envelope', 'under-line', 'under-fill']

const categoryColor = ['match', ['get', 'category'],
  'residential', CATEGORY_COLORS.residential,
  'commercial', CATEGORY_COLORS.commercial,
  'mixed', CATEGORY_COLORS.mixed,
  'institutional', CATEGORY_COLORS.institutional,
  CATEGORY_COLORS.other]

const infraColor = ['match', ['get', 'subtype'],
  ...Object.entries(INFRA_COLORS).flat(), INFRA_FALLBACK_COLOR]

const lineWidth = (mult = 1) => ['interpolate', ['exponential', 2], ['zoom'],
  12, ['max', 1.5, ['*', ['get', 'display_width'], 0.0577 * mult]],
  22, ['max', 4, ['*', ['get', 'display_width'], 59.1 * mult]]]

export function buildStyle({ terrain = false } = {}) {
  return {
    version: 8,
    sources: {
      satellite: {
        type: 'raster', tileSize: 256, maxzoom: 19,
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics',
      },
      labels: {
        type: 'raster', tileSize: 256, maxzoom: 19,
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'],
      },
      dem: {
        type: 'raster-dem', tileSize: 256, maxzoom: 15, encoding: 'terrarium',
        tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
        attribution: 'Terrain: AWS Terrain Tiles',
      },
      openmaptiles: {
        type: 'vector', url: 'https://tiles.openfreemap.org/planet',
        attribution: '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> &copy; OpenMapTiles, data &copy; OpenStreetMap contributors',
      },
      region: { type: 'geojson', data: EMPTY },
      registered: { type: 'geojson', data: EMPTY },
      'infra-under': { type: 'geojson', data: EMPTY },
      'infra-air': { type: 'geojson', data: EMPTY },
      'infra-hi': { type: 'geojson', data: EMPTY },
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#0b1512' } },
      { id: 'satellite', type: 'raster', source: 'satellite' },
      {
        id: 'osm-buildings', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 13,
        paint: {
          'fill-extrusion-color': '#f1f5f9',
          'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 6],
          'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
          'fill-extrusion-opacity': 0.88,
        },
      },
      {
        id: 'region-buildings', type: 'fill-extrusion', source: 'region', minzoom: REGION_MIN_ZOOM,
        paint: {
          'fill-extrusion-color': ['case', ['get', 'height_known'], '#cbd5e1', '#94a3b8'],
          'fill-extrusion-height': ['get', 'render_height'],
          'fill-extrusion-opacity': 0.9,
        },
      },
      {
        id: 'registered-buildings', type: 'fill-extrusion', source: 'registered',
        paint: {
          'fill-extrusion-color': categoryColor,
          'fill-extrusion-height': ['+', ['get', 'render_height'], 0.2],
          'fill-extrusion-opacity': 0.95,
        },
      },
      {
        id: 'registered-selected', type: 'fill-extrusion', source: 'registered', filter: ['==', ['get', 'id'], ''],
        paint: {
          'fill-extrusion-color': '#FFD166',
          'fill-extrusion-height': ['+', ['get', 'render_height'], 0.5],
          'fill-extrusion-opacity': 1,
        },
      },
      {
        id: 'under-fill', type: 'fill', source: 'infra-under', filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': infraColor, 'fill-opacity': 0.55 },
      },
      {
        id: 'under-fill-outline', type: 'line', source: 'infra-under', filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'line-color': infraColor, 'line-width': 1.6, 'line-dasharray': [2, 1.5] },
      },
      {
        id: 'under-line-casing', type: 'line', source: 'infra-under', filter: ['==', ['geometry-type'], 'LineString'],
        layout: { 'line-cap': 'butt', 'line-join': 'round' },
        paint: { 'line-color': '#0b1512', 'line-opacity': 0.55, 'line-width': lineWidth(1.5) },
      },
      {
        id: 'under-line', type: 'line', source: 'infra-under', filter: ['==', ['geometry-type'], 'LineString'],
        layout: { 'line-cap': 'butt', 'line-join': 'round' },
        paint: { 'line-color': infraColor, 'line-opacity': 0.95, 'line-width': lineWidth(1) },
      },
      {
        id: 'air-ground', type: 'fill', source: 'infra-air',
        paint: { 'fill-color': infraColor, 'fill-opacity': 0.14 },
      },
      {
        id: 'air-ground-outline', type: 'line', source: 'infra-air',
        paint: { 'line-color': infraColor, 'line-width': 1.2, 'line-dasharray': [3, 2] },
      },
      {
        id: 'air-envelope', type: 'fill-extrusion', source: 'infra-air',
        paint: {
          'fill-extrusion-color': infraColor,
          'fill-extrusion-base': ['get', 'base'],
          'fill-extrusion-height': ['get', 'top'],
          'fill-extrusion-opacity': 0.3,
        },
      },
      {
        id: 'air-deck', type: 'fill-extrusion', source: 'infra-air',
        filter: ['>', ['get', 'deck_top'], ['get', 'deck_base']],
        paint: {
          'fill-extrusion-color': infraColor,
          'fill-extrusion-base': ['get', 'deck_base'],
          'fill-extrusion-height': ['get', 'deck_top'],
          'fill-extrusion-opacity': 0.92,
        },
      },
      {
        id: 'infra-hi-fill', type: 'fill', source: 'infra-hi', filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.28 },
      },
      {
        id: 'infra-hi-line', type: 'line', source: 'infra-hi',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': 3.2, 'line-opacity': 0.95 },
      },
      { id: 'labels', type: 'raster', source: 'labels', layout: { visibility: 'none' } },
    ],
    ...(terrain ? { terrain: { source: 'dem', exaggeration: 1.3 } } : {}),
  }
}
