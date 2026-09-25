import assert from 'node:assert/strict'
import { planBuilding, triangulate, signedArea, cleanRing } from './buildingPlan.js'

const floors = (n, { h = 3, activeIdx = -1, lift = 0 } = {}) => Array.from({ length: n }, (_, i) => ({
  y0: i * h + (activeIdx >= 0 && i > activeIdx ? lift : 0), y1: (i + 1) * h + (activeIdx >= 0 && i > activeIdx ? lift : 0),
  kind: i === 0 ? 'commercial' : 'residential', accent: i > 0 && (i + 1) % 3 === 0, active: i === activeIdx,
}))

function assertSound(res, label) {
  for (const buf of [res.solid, res.ghost]) {
    for (let i = 0; i < buf.pos.length; i += 9) {
      const p = buf.pos.slice(i, i + 9)
      assert.ok(p.every(Number.isFinite), `${label}: non-finite vertex`)
      const [ux, uy, uz, vx, vy, vz] = [p[3] - p[0], p[4] - p[1], p[5] - p[2], p[6] - p[0], p[7] - p[1], p[8] - p[2]]
      const g = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx]
      const n = buf.nor.slice(i, i + 3)
      assert.ok(g[0] * n[0] + g[1] * n[1] + g[2] * n[2] > 0, `${label}: triangle winding disagrees with its normal`)
    }
  }
}

const rect = [[-15, -11.25], [15, -11.25], [15, 11.25], [-15, 11.25]]
const lShape = [[-15, -10], [15, -10], [15, 0], [0, 0], [0, 10], [-15, 10]]

assertSound(planBuilding({ ring: rect, floors: floors(6) }), 'rect CCW')
assertSound(planBuilding({ ring: [...rect].reverse(), floors: floors(6) }), 'rect CW')
assertSound(planBuilding({ ring: lShape, floors: floors(7) }), 'L-shape')
const withActive = planBuilding({ ring: rect, floors: floors(6, { activeIdx: 3, lift: 3.4 }) })
assertSound(withActive, 'active floor')
assert.ok(withActive.ghost.vertexCount > 0, 'active floor should land in the ghost buffer')
assert.ok(planBuilding({ ring: rect, floors: floors(6) }).roofItems.entrance, 'front entrance canopy expected on a 30 m edge')

for (const ring of [rect, lShape]) {
  const t = triangulate(ring)
  const area = t.reduce((s, [i, j, k]) => s + Math.abs(((ring[j][0] - ring[i][0]) * (ring[k][1] - ring[i][1]) - (ring[k][0] - ring[i][0]) * (ring[j][1] - ring[i][1])) / 2), 0)
  assert.ok(Math.abs(area - Math.abs(signedArea(ring))) < 1e-6, 'triangulation must cover the polygon exactly')
}

assert.throws(() => planBuilding({ ring: [[0, 0], [1, 0], [2, 0]], floors: floors(2) }), /area/)
assert.throws(() => planBuilding({ ring: rect, floors: [] }), /no above-ground floors/)
assert.deepEqual(cleanRing([[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]]), [[0, 0], [5, 0], [5, 5], [0, 5]])

console.log('buildingPlan self-test: all checks passed')
