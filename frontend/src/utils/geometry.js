export function polygonArea(points) {
  if (!Array.isArray(points) || points.length < 3) return null
  let area = 0
  const n = points.length
  for (let i = 0; i < n; i++) {
    const [x1, y1] = points[i]
    const [x2, y2] = points[(i + 1) % n]
    area += x1 * y2 - x2 * y1
  }
  return Math.abs(area) / 2
}

export function safeParseGeojson(str) {
  if (!str) return null
  try {
    const parsed = JSON.parse(str)
    return Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}
