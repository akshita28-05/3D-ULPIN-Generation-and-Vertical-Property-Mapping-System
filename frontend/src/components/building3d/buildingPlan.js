
export const PALETTE = {
  sand: 0xD8BE92,
  blueBand: 0x86A3C6,
  brick: 0xA8462F,
  concrete: 0xB4B0A6,
  pilaster: 0x7C3324,
  slab: 0xE9E4D6,
  plate: 0xB9B4A6,
  balcony: 0x9DB7D0,
  railing: 0x7E9BBA,
  glass: 0x86AAC4,
  parkingOpening: 0x2F3338,
  frame: 0xF3EFE4,
  roofDeck: 0x8F8D87,
  parapet: 0xD0C9B7,
  lift: 0xBEBCB6,
  tank: 0x2A4DB3,
  antenna: 0xE7B824,
  door: 0x2F6FA8,
  canopy: 0xEDE9DE,
  post: 0xD8D3C4,
  step: 0xCFCABB,
}

const CYAN = 0x22D3EE

export function mixHex(a, b, t) {
  const ar = (a >> 16) & 255, ag = (a >> 8) & 255, ab = a & 255
  const br = (b >> 16) & 255, bg = (b >> 8) & 255, bb = b & 255
  const r = Math.round(ar + (br - ar) * t)
  const g = Math.round(ag + (bg - ag) * t)
  const bl = Math.round(ab + (bb - ab) * t)
  return (r << 16) | (g << 8) | bl
}


class Buf {
  constructor(tint = null) {
    this.pos = []
    this.nor = []
    this.hex = []
    this.tint = tint
  }

  get vertexCount() { return this.hex.length }

  _c(hex) { return this.tint == null ? hex : mixHex(hex, CYAN, this.tint) }

  tri(a, b, c, n, hex) {
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2]
    const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2]
    const gx = uy * vz - uz * vy, gy = uz * vx - ux * vz, gz = ux * vy - uy * vx
    if (gx * n[0] + gy * n[1] + gz * n[2] < 0) { const t = b; b = c; c = t }
    const col = this._c(hex)
    for (const p of [a, b, c]) {
      this.pos.push(p[0], p[1], p[2])
      this.nor.push(n[0], n[1], n[2])
      this.hex.push(col)
    }
  }

  quad(p0, p1, p2, p3, n, hex) {
    this.tri(p0, p1, p2, n, hex)
    this.tri(p0, p2, p3, n, hex)
  }

  box(f, u0, u1, v0, v1, y0, y1, hex, bottom = false) {
    if (u1 - u0 <= 1e-4 || v1 - v0 <= 1e-4 || y1 - y0 <= 1e-4) return
    const P = (u, v, y) => [f.ox + f.tx * u + f.nx * v, y, f.oz + f.tz * u + f.nz * v]
    const nOut = [f.nx, 0, f.nz], nIn = [-f.nx, 0, -f.nz]
    const nU1 = [f.tx, 0, f.tz], nU0 = [-f.tx, 0, -f.tz]
    this.quad(P(u0, v1, y0), P(u1, v1, y0), P(u1, v1, y1), P(u0, v1, y1), nOut, hex)
    this.quad(P(u0, v0, y0), P(u1, v0, y0), P(u1, v0, y1), P(u0, v0, y1), nIn, hex)
    this.quad(P(u1, v0, y0), P(u1, v1, y0), P(u1, v1, y1), P(u1, v0, y1), nU1, hex)
    this.quad(P(u0, v0, y0), P(u0, v1, y0), P(u0, v1, y1), P(u0, v0, y1), nU0, hex)
    this.quad(P(u0, v0, y1), P(u1, v0, y1), P(u1, v1, y1), P(u0, v1, y1), [0, 1, 0], hex)
    if (bottom) this.quad(P(u0, v0, y0), P(u1, v0, y0), P(u1, v1, y0), P(u0, v1, y0), [0, -1, 0], hex)
  }

  aabb(cx, cz, sx, sz, y0, y1, hex) {
    this.box({ ox: cx - sx / 2, oz: cz - sz / 2, tx: 1, tz: 0, nx: 0, nz: 1 }, 0, sx, 0, sz, y0, y1, hex, true)
  }

  cylinder(cx, cz, r, y0, y1, hex, seg = 14) {
    for (let i = 0; i < seg; i++) {
      const a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2
      const c0 = Math.cos(a0), s0 = Math.sin(a0), c1 = Math.cos(a1), s1 = Math.sin(a1)
      const nm = [Math.cos((a0 + a1) / 2), 0, Math.sin((a0 + a1) / 2)]
      this.quad(
        [cx + c0 * r, y0, cz + s0 * r], [cx + c1 * r, y0, cz + s1 * r],
        [cx + c1 * r, y1, cz + s1 * r], [cx + c0 * r, y1, cz + s0 * r], nm, hex,
      )
      this.tri([cx, y1, cz], [cx + c0 * r, y1, cz + s0 * r], [cx + c1 * r, y1, cz + s1 * r], [0, 1, 0], hex)
    }
  }

  cap(ring, tris, y, up, hex) {
    const n = [0, up ? 1 : -1, 0]
    for (const [i, j, k] of tris) {
      this.tri([ring[i][0], y, ring[i][1]], [ring[j][0], y, ring[j][1]], [ring[k][0], y, ring[k][1]], n, hex)
    }
  }
}


export function signedArea(ring) {
  let a = 0
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i], q = ring[(i + 1) % ring.length]
    a += p[0] * q[1] - q[0] * p[1]
  }
  return a / 2
}

function pointInTri(p, a, b, c) {
  const d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
  const d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
  const d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
  const neg = d1 < 0 || d2 < 0 || d3 < 0
  const pos = d1 > 0 || d2 > 0 || d3 > 0
  return !(neg && pos)
}

export function pointInPolygon(p, ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], zi = ring[i][1], xj = ring[j][0], zj = ring[j][1]
    if ((zi > p[1]) !== (zj > p[1]) && p[0] < ((xj - xi) * (p[1] - zi)) / (zj - zi) + xi) inside = !inside
  }
  return inside
}

export function triangulate(ring) {
  const idx = ring.map((_, i) => i)
  if (signedArea(ring) < 0) idx.reverse()
  const tris = []
  let guard = 0
  while (idx.length > 3 && guard++ < 5000) {
    let clipped = false
    for (let i = 0; i < idx.length; i++) {
      const i0 = idx[(i + idx.length - 1) % idx.length], i1 = idx[i], i2 = idx[(i + 1) % idx.length]
      const a = ring[i0], b = ring[i1], c = ring[i2]
      const cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
      if (cross <= 1e-9) continue
      let blocked = false
      for (const j of idx) {
        if (j === i0 || j === i1 || j === i2) continue
        if (pointInTri(ring[j], a, b, c)) { blocked = true; break }
      }
      if (blocked) continue
      tris.push([i0, i1, i2])
      idx.splice(i, 1)
      clipped = true
      break
    }
    if (!clipped) {
      let dropped = false
      for (let i = 0; i < idx.length; i++) {
        const a = ring[idx[(i + idx.length - 1) % idx.length]], b = ring[idx[i]], c = ring[idx[(i + 1) % idx.length]]
        if (Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-6) { idx.splice(i, 1); dropped = true; break }
      }
      if (!dropped) throw new Error('footprint is not a simple polygon -- cannot triangulate')
    }
  }
  if (idx.length === 3) tris.push([idx[0], idx[1], idx[2]])
  return tris
}

export function cleanRing(points) {
  if (!Array.isArray(points)) return null
  const out = []
  for (const p of points) {
    if (!Array.isArray(p) || !Number.isFinite(p[0]) || !Number.isFinite(p[1])) continue
    const last = out[out.length - 1]
    if (last && Math.hypot(p[0] - last[0], p[1] - last[1]) < 0.05) continue
    out.push([p[0], p[1]])
  }
  if (out.length > 1 && Math.hypot(out[0][0] - out[out.length - 1][0], out[0][1] - out[out.length - 1][1]) < 0.05) out.pop()
  return out.length >= 3 ? out : null
}


const SLAB_T = 0.22
const WALL_T = 0.3

function wallColorFor(kind, accent) {
  if (kind === 'commercial') return PALETTE.brick
  if (kind === 'parking') return PALETTE.concrete
  return accent ? PALETTE.blueBand : PALETTE.sand
}

export function planBuilding({ ring, floors, detail = 2, roofDetails = true }) {
  if (!ring || ring.length < 3) throw new Error('planBuilding: ring needs >= 3 points')
  if (!floors || !floors.length) throw new Error('planBuilding: no above-ground floors')

  const solid = new Buf()
  const ghost = new Buf(0.5)

  const area = signedArea(ring)
  if (Math.abs(area) < 1) throw new Error('planBuilding: footprint area is ~0')
  const ccw = area > 0

  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
  for (const [x, z] of ring) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z) }
  let cx = 0, cz = 0
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i], q = ring[(i + 1) % ring.length]
    const w = p[0] * q[1] - q[0] * p[1]
    cx += (p[0] + q[0]) * w
    cz += (p[1] + q[1]) * w
  }
  cx /= 6 * area; cz /= 6 * area
  if (!Number.isFinite(cx) || !Number.isFinite(cz)) { cx = (minX + maxX) / 2; cz = (minZ + maxZ) / 2 }
  const ex = maxX - minX, ez = maxZ - minZ

  const edges = []
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i], q = ring[(i + 1) % ring.length]
    const dx = q[0] - p[0], dz = q[1] - p[1]
    const L = Math.hypot(dx, dz)
    if (L < 0.6) continue
    const tx = dx / L, tz = dz / L
    const nx = ccw ? tz : -tz, nz = ccw ? -tx : tx
    edges.push({ ox: p[0], oz: p[1], tx, tz, nx, nz, L })
  }

  let entrance = null
  {
    let best = -Infinity
    edges.forEach((e, i) => {
      if (e.L < 5) return
      const score = e.nz * 10 + e.L * 0.01
      if (score > best) { best = score; entrance = i }
    })
  }

  let targetBay = 3.2
  const above = floors.length
  const estBoxes = () => edges.reduce((s, e) => s + (e.L / targetBay * (detail === 2 ? 5.3 : detail === 1 ? 3.3 : 0.3) + 5), 0) * above
  while (estBoxes() > 30000 && targetBay < 12) targetBay *= 1.4

  const tris = triangulate(ring)

  floors.forEach((fl, fi) => {
    const buf = fl.active ? ghost : solid
    const { y0, y1 } = fl
    const h = y1 - y0
    if (h <= 0.2) return
    const kind = fl.kind || 'residential'
    const wall = wallColorFor(kind, !!fl.accent)
    const spandrel = mixHex(wall, 0x000000, 0.14)
    const isGround = fi === 0

    buf.cap(ring, tris, y0, false, PALETTE.plate)
    buf.cap(ring, tris, y0 + SLAB_T - 0.02, true, PALETTE.plate)

    edges.forEach((e, ei) => {
      buf.box(e, 0, e.L, -WALL_T, 0, y0 + SLAB_T, y1, wall)
      buf.box(e, -0.05, e.L + 0.05, -WALL_T, 0.12, y0, y0 + SLAB_T, PALETTE.slab, true)

      if (kind === 'residential' && !isGround && detail >= 1 && e.L > 2.4) {
        buf.box(e, 0.25, e.L - 0.25, 0, 0.75, y0 + SLAB_T, y0 + SLAB_T + 0.14, PALETTE.balcony, true)
        buf.box(e, 0.25, e.L - 0.25, 0.70, 0.75, y0 + SLAB_T + 0.14, y0 + 1.0, PALETTE.railing)
      }

      if (detail === 0) return

      const nb = Math.max(1, Math.round(e.L / targetBay))
      const bw = e.L / nb
      const doorBay = entrance === ei && isGround ? Math.floor(nb / 2) : -1

      for (let k = 0; k <= nb; k++) {
        buf.box(e, k * bw - 0.09, k * bw + 0.09, 0, 0.10, y0 + SLAB_T, y1, PALETTE.pilaster)
      }

      for (let k = 0; k < nb; k++) {
        const uc = (k + 0.5) * bw

        if (k === doorBay) {
          buf.box(e, uc - 0.85, uc + 0.85, 0, 0.08, y0, y0 + Math.min(2.4, h * 0.8), PALETTE.door)
          continue
        }

        if (kind === 'parking') {
          const w = bw * 0.78
          buf.box(e, uc - w / 2, uc + w / 2, 0, 0.06, y0 + h * 0.22, y0 + h * 0.72, PALETTE.parkingOpening)
          continue
        }

        const ww = Math.min(1.5, bw * 0.5)
        const wh = h * 0.42
        const wy0 = y0 + h * 0.38

        if (k % 3 === 1) buf.box(e, uc - bw * 0.42, uc + bw * 0.42, 0, 0.04, y0 + SLAB_T, wy0 - 0.05, spandrel)

        if (detail === 2) {
          buf.box(e, uc - ww / 2 - 0.08, uc + ww / 2 + 0.08, 0, 0.05, wy0 - 0.08, wy0 + wh + 0.08, PALETTE.frame)
          buf.box(e, uc - ww / 2, uc + ww / 2, 0.05, 0.08, wy0, wy0 + wh, PALETTE.glass)
          buf.box(e, uc - 0.03, uc + 0.03, 0.08, 0.11, wy0, wy0 + wh, PALETTE.frame)
          buf.box(e, uc - ww / 2, uc + ww / 2, 0.08, 0.11, wy0 + wh / 2 - 0.03, wy0 + wh / 2 + 0.03, PALETTE.frame)
        } else {
          buf.box(e, uc - ww / 2, uc + ww / 2, 0, 0.06, wy0, wy0 + wh, PALETTE.glass)
        }
      }
    })
  })

  const top = floors[floors.length - 1]
  const roofY = top.y1
  const roofBuf = top.active ? ghost : solid
  roofBuf.cap(ring, tris, roofY, true, PALETTE.roofDeck)
  edges.forEach((e) => roofBuf.box(e, 0, e.L, -0.25, 0.05, roofY, roofY + 0.9, PALETTE.parapet, true))

  const roofItems = { liftRoom: null, tanks: [], antenna: null, entrance: null }
  if (roofDetails && Math.min(ex, ez) >= 6) {
    const lw = Math.min(ex * 0.32, 9), ld = Math.min(ez * 0.3, 6), lh = 2.6
    const lx = cx, lz = cz - ez * 0.08
    if (pointInPolygon([lx - lw / 2, lz - ld / 2], ring) && pointInPolygon([lx + lw / 2, lz + ld / 2], ring)) {
      roofBuf.aabb(lx, lz, lw, ld, roofY, roofY + lh, PALETTE.lift)
      roofItems.liftRoom = { x: lx, z: lz, w: lw, d: ld, h: lh }
      roofBuf.aabb(lx + lw * 0.32, lz, 0.07, 0.07, roofY + lh, roofY + lh + 3.2, PALETTE.antenna)
      roofItems.antenna = { x: lx + lw * 0.32, z: lz }
      const sx = lx, sz = lz + ld / 2 + 0.9
      if (pointInPolygon([sx, sz], ring)) roofBuf.aabb(sx, sz, 0.8, 0.8, roofY, roofY + 0.6, PALETTE.lift)
    }
    const tr = Math.max(0.55, Math.min(1.1, Math.min(ex, ez) * 0.05))
    for (const sgn of [-1, 1]) {
      const tx = cx + sgn * ex * 0.3, tz = cz + ez * 0.16
      if (pointInPolygon([tx, tz], ring)) {
        roofBuf.cylinder(tx, tz, tr, roofY, roofY + 1.5, PALETTE.tank)
        roofItems.tanks.push({ x: tx, z: tz, r: tr })
      }
    }
  }

  const groundH = floors[0].y1 - floors[0].y0
  if (entrance != null && groundH >= 2.6 && detail >= 1) {
    const e = edges[entrance]
    const nb = Math.max(1, Math.round(e.L / targetBay))
    const uc = (Math.floor(nb / 2) + 0.5) * (e.L / nb)
    const y0 = floors[0].y0
    const b0 = floors[0].active ? ghost : solid
    const cy = Math.min(2.75, groundH - 0.3)
    b0.box(e, uc - 2.2, uc + 2.2, 0, 2.4, y0 + cy, y0 + cy + 0.2, PALETTE.canopy, true)
    b0.box(e, uc - 2.0, uc - 1.85, 2.15, 2.3, y0, y0 + cy, PALETTE.post)
    b0.box(e, uc + 1.85, uc + 2.0, 2.15, 2.3, y0, y0 + cy, PALETTE.post)
    b0.box(e, uc - 2.0, uc + 2.0, 0, 2.9, y0, y0 + 0.14, PALETTE.step, true)
    roofItems.entrance = { edge: entrance, u: uc }
  }

  return {
    solid, ghost, roofY,
    bbox: { minX, maxX, minZ, maxZ }, centroid: [cx, cz], extent: Math.max(ex, ez),
    roofItems, edgeCount: edges.length,
  }
}
