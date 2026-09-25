import * as THREE from 'three'
import { planBuilding, cleanRing } from './buildingPlan.js'

const colorCache = new Map()
function linearRgb(hex) {
  let c = colorCache.get(hex)
  if (!c) {
    const col = new THREE.Color(hex)
    c = [col.r, col.g, col.b]
    colorCache.set(hex, c)
  }
  return c
}

function toGeometry(buf) {
  const g = new THREE.BufferGeometry()
  const n = buf.hex.length
  const colors = new Float32Array(n * 3)
  for (let i = 0; i < n; i++) {
    const [r, gg, b] = linearRgb(buf.hex[i])
    colors[i * 3] = r; colors[i * 3 + 1] = gg; colors[i * 3 + 2] = b
  }
  g.setAttribute('position', new THREE.Float32BufferAttribute(buf.pos, 3))
  g.setAttribute('normal', new THREE.Float32BufferAttribute(buf.nor, 3))
  g.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  g.computeBoundingSphere()
  return g
}

export function footprintToRing(points) {
  const cleaned = cleanRing(points)
  return cleaned ? cleaned.map(([x, y]) => [x, -y]) : null
}

export function createDetailedBuilding({ ring, floors, detail = 2, roofDetails = true }) {
  const plan = planBuilding({ ring, floors, detail, roofDetails })
  const group = new THREE.Group()
  group.name = 'detailed-building'

  if (plan.solid.vertexCount) {
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.88, metalness: 0.02 })
    const mesh = new THREE.Mesh(toGeometry(plan.solid), mat)
    mesh.name = 'facade'
    group.add(mesh)
  }
  if (plan.ghost.vertexCount) {
    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: 0.55, metalness: 0.05,
      transparent: true, opacity: 0.6, depthWrite: false,
      emissive: 0x0E7490, emissiveIntensity: 0.4,
    })
    const mesh = new THREE.Mesh(toGeometry(plan.ghost), mat)
    mesh.name = 'facade-active-floor'
    mesh.renderOrder = 2
    group.add(mesh)
  }
  return { group, meta: plan }
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

export function createLabelSprite(text, worldWidth = 6) {
  const canvas = document.createElement('canvas')
  canvas.width = 320; canvas.height = 96
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = 'rgba(11, 25, 23, 0.92)'
  roundRect(ctx, 4, 4, 312, 88, 14); ctx.fill()
  ctx.lineWidth = 4; ctx.strokeStyle = '#22D3EE'
  roundRect(ctx, 4, 4, 312, 88, 14); ctx.stroke()
  ctx.fillStyle = '#22D3EE'
  ctx.font = '600 44px "IBM Plex Mono", ui-monospace, monospace'
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(text, 160, 50)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }))
  sprite.scale.set(worldWidth, worldWidth * (96 / 320), 1)
  sprite.renderOrder = 20
  sprite.name = 'floor-label'
  return sprite
}

export function createNorthMarker(size = 4, color = '#22D3EE') {
  const canvas = document.createElement('canvas')
  canvas.width = 128; canvas.height = 160
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = color
  ctx.font = '700 84px "IBM Plex Sans", system-ui, sans-serif'
  ctx.textAlign = 'center'; ctx.textBaseline = 'top'
  ctx.fillText('N', 64, 0)
  ctx.strokeStyle = color; ctx.lineWidth = 6; ctx.lineCap = 'round'
  ctx.beginPath(); ctx.moveTo(64, 150); ctx.lineTo(64, 106); ctx.moveTo(48, 122); ctx.lineTo(64, 104); ctx.lineTo(80, 122); ctx.stroke()
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }))
  sprite.scale.set(size * 0.8, size, 1)
  sprite.renderOrder = 19
  sprite.name = 'north-marker'
  return sprite
}

export function createContactShadow(width, depth, strength = 0.55) {
  const canvas = document.createElement('canvas')
  canvas.width = 128; canvas.height = 128
  const ctx = canvas.getContext('2d')
  const grad = ctx.createRadialGradient(64, 64, 8, 64, 64, 62)
  grad.addColorStop(0, `rgba(0,0,0,${strength})`)
  grad.addColorStop(0.65, `rgba(0,0,0,${strength * 0.55})`)
  grad.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = grad; ctx.fillRect(0, 0, 128, 128)
  const tex = new THREE.CanvasTexture(canvas)
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(width, depth),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }),
  )
  mesh.rotation.x = -Math.PI / 2
  mesh.position.y = 0.07
  mesh.renderOrder = 1
  mesh.name = 'contact-shadow'
  return mesh
}
