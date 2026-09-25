import * as THREE from 'three'


const UNDERGROUND = {
  metro_tunnel:        { hex: 0xB794F4, short: 'metro tunnel' },
  rail_tunnel:         { hex: 0x7DD3FC, short: 'rail tunnel' },
  road_tunnel:         { hex: 0x94A3B8, short: 'road tunnel' },
  road_underpass:      { hex: 0x94A3B8, short: 'underpass' },
  pedestrian_subway:   { hex: 0x34D399, short: 'subway' },
  culvert:             { hex: 0x2DD4BF, short: 'culvert' },
  storm_drain:         { hex: 0xB98B5A, short: 'drain' },
  power_cable:         { hex: 0xF5C542, short: 'electricity' },
  underground_parking: { hex: 0xD4A85A, short: 'parking' },
  basement:            { hex: 0xD4A85A, short: 'basement' },
}
const PIPE_BY_SUBSTANCE = {
  water:   { hex: 0x3B9DF8, short: 'water' },
  gas:     { hex: 0xF28C28, short: 'gas' },
  sewage:  { hex: 0xB98B5A, short: 'sewer' },
}
const AIR = {
  metro:         { hex: 0x8B5CF6, short: 'metro' },
  elevated_rail: { hex: 0x818CF8, short: 'elevated rail' },
  flyover:       { hex: 0x38BDF8, short: 'flyover' },
  elevated_road: { hex: 0x38BDF8, short: 'elevated road' },
  power_line:    { hex: 0xF472B6, short: 'power line' },
}
export const CONFLICT_HEX = { potential: 0xE8A23A, confirmed: 0xEF5B5B }

export function infraStyle(f) {
  if (f.kind === 'air') return AIR[f.subtype] || { hex: 0x8B5CF6, short: (f.subtype || 'corridor').replace(/_/g, ' ') }
  if (f.subtype === 'pipeline') return PIPE_BY_SUBSTANCE[f.substance] || { hex: 0xB8C0CC, short: 'pipeline' }
  return UNDERGROUND[f.subtype] || { hex: 0xB98B5A, short: (f.subtype || 'utility').replace(/_/g, ' ') }
}

export function infraHex(f) {
  return CONFLICT_HEX[f.conflict_status] || infraStyle(f).hex
}

export function cssHex(hex) {
  return '#' + hex.toString(16).padStart(6, '0')
}

const num = (v) => Number(Number(v).toFixed(1))

export function rangeText(f) {
  if (f.z_min_m == null || f.z_max_m == null) return ''
  const approx = f.z_source === 'osm_tag' ? '' : '~'
  return `${approx}${num(f.z_min_m)}–${num(f.z_max_m)} m`
}

export function labelText(f) {
  const r = rangeText(f)
  return r ? `${infraStyle(f).short} · ${r}` : infraStyle(f).short
}

export function createInfraLabel(text, hex, worldWidth = 12) {
  const color = cssHex(hex)
  const canvas = document.createElement('canvas')
  canvas.width = 512; canvas.height = 96
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = 'rgba(11, 20, 30, 0.9)'
  roundRect(ctx, 4, 4, 504, 88, 16); ctx.fill()
  ctx.lineWidth = 4; ctx.strokeStyle = color
  roundRect(ctx, 4, 4, 504, 88, 16); ctx.stroke()
  ctx.fillStyle = color
  let size = 44
  ctx.font = `600 ${size}px "IBM Plex Mono", ui-monospace, monospace`
  while (ctx.measureText(text).width > 470 && size > 20) {
    size -= 2
    ctx.font = `600 ${size}px "IBM Plex Mono", ui-monospace, monospace`
  }
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(text, 256, 50)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }))
  sprite.scale.set(worldWidth, worldWidth * (96 / 512), 1)
  sprite.renderOrder = 22
  sprite.name = 'infra-label'
  return sprite
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

export function makeCurtain(pts, yFrom, yTo, hex, opacity = 0.12) {
  const pos = []
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1]
    pos.push(ax, yFrom, -ay, bx, yFrom, -by, bx, yTo, -by)
    pos.push(ax, yFrom, -ay, bx, yTo, -by, ax, yTo, -ay)
  }
  if (!pos.length) return null
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  const material = new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false })
  return new THREE.Mesh(geometry, material)
}

export function makePolyline(pts, y, hex, opacity = 0.95) {
  const v = pts.map(([x, z]) => new THREE.Vector3(x, y, -z))
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(v), new THREE.LineBasicMaterial({ color: hex, transparent: true, opacity }))
  return line
}

export function makeGlowEdges(mesh, hex, opacity = 0.9) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({ color: hex, transparent: true, opacity }),
  )
  edges.position.copy(mesh.position)
  return edges
}

export function ringCentroid(ring) {
  let x = 0, y = 0
  ring.forEach((p) => { x += p[0]; y += p[1] })
  return [x / ring.length, y / ring.length]
}

export function lineMidpoint(line) {
  if (!line || line.length < 2) return null
  const seg = []
  let total = 0
  for (let i = 0; i < line.length - 1; i++) {
    const d = Math.hypot(line[i + 1][0] - line[i][0], line[i + 1][1] - line[i][1])
    seg.push(d); total += d
  }
  let target = total / 2
  for (let i = 0; i < seg.length; i++) {
    if (target <= seg[i] || i === seg.length - 1) {
      const t = seg[i] ? Math.min(1, target / seg[i]) : 0
      return [line[i][0] + (line[i + 1][0] - line[i][0]) * t, line[i][1] + (line[i + 1][1] - line[i][1]) * t]
    }
    target -= seg[i]
  }
  return null
}

export function niceStep(maxDepth) {
  if (maxDepth <= 8) return 2
  if (maxDepth <= 20) return 5
  return 10
}

export function infraBounds(features) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  features.forEach((f) => (f.polygons || []).forEach((ring) => ring.forEach(([x, y]) => {
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  })))
  return Number.isFinite(minX) ? { minX, minY, maxX, maxY } : null
}
