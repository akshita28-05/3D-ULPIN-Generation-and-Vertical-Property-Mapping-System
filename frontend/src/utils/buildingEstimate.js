import { polygonArea, safeParseGeojson } from './geometry.js'

const TARGET_UNIT_AREA_SQM = 45.0

function hashString(str) {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export function estimateBuildingDimensions(building) {
  if (building.num_floors || building.height_m != null) {
    const floors = building.num_floors || 1
    const height = building.height_m != null ? building.height_m : floors * 3
    return { floors, height, floorHeight: height / floors, unitsPerFloor: null, estimated: false }
  }

  const pts = safeParseGeojson(building.footprint_geojson)
  const area = polygonArea(pts) || 40

  const hash = hashString(building.id || building.building_code || '')
  const sizeBucket = area > 600 ? 3 : area > 250 ? 2 : area > 80 ? 1 : 0
  const variety = hash % 3
  const floors = Math.max(1, 1 + sizeBucket + variety)

  const floorHeight = Math.round((2.8 + ((hash >> 3) % 9) / 10) * 10) / 10
  const height = Math.round(floors * floorHeight * 10) / 10

  const unitsPerFloor = Math.max(2, Math.min(12, Math.round(area / TARGET_UNIT_AREA_SQM)))

  return { floors, height, floorHeight, unitsPerFloor, estimated: true }
}
