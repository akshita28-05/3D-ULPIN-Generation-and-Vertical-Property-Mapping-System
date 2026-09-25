import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { estimateBuildingDimensions } from '../utils/buildingEstimate.js'
import { createDetailedBuilding, footprintToRing, createLabelSprite, createNorthMarker, createContactShadow } from './building3d/DetailedBuilding.js'
import {
  infraHex, labelText, createInfraLabel, makeCurtain, makePolyline, makeGlowEdges,
  ringCentroid, lineMidpoint, niceStep, infraBounds,
} from './building3d/infra3d.js'

const TYPE_COLORS = {
  residential_unit: 0x5C8A6B,
  commercial_unit: 0xC9A24E,
  parking_unit: 0x9C9484,
  default: 0x5C8A6B,
}

const textureLoader = new THREE.TextureLoader()

const FLOOR_DETAIL_THRESHOLD = 6

const DEFAULT_CAMERA_POS = { x: 45, y: 38, z: 45 }
const DEFAULT_TARGET = { x: 15, y: 6, z: 11 }

const EXPLODE_GAP = 2.5

const ACTIVE_LIFT = 3.4

function floorKind(f) {
  const counts = { residential: 0, commercial: 0, parking: 0 }
  f.units?.forEach((u) => {
    if (u.parcel_type === 'commercial_unit') counts.commercial++
    else if (u.parcel_type === 'parking_unit') counts.parking++
    else counts.residential++
  })
  if (counts.commercial > counts.residential && counts.commercial >= counts.parking) return 'commercial'
  if (counts.parking > counts.residential && counts.parking > counts.commercial) return 'parking'
  return 'residential'
}

function polygonShape(points) {
  const shape = new THREE.Shape()
  points.forEach(([x, y], i) => (i === 0 ? shape.moveTo(x, y) : shape.lineTo(x, y)))
  return shape
}

function seedFloors(building, footprintPts) {
  const { floors: floorCount, height: totalHeight, unitsPerFloor } = estimateBuildingDimensions(building)
  const floorHeight = totalHeight / floorCount

  const xs = footprintPts.map((p) => p[0])
  const ys = footprintPts.map((p) => p[1])
  const x0 = Math.min(...xs), y0 = Math.min(...ys)
  const w = Math.max(...xs) - x0, d = Math.max(...ys) - y0

  const targetUnits = unitsPerFloor || 1
  const cols = targetUnits >= 4 ? 2 : 1
  const rows = Math.max(1, Math.round(targetUnits / cols))
  const cellW = w / cols, cellD = d / rows

  return Array.from({ length: floorCount }, (_, i) => {
    const floorNumber = i + 1
    const units = []
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const ux0 = x0 + c * cellW, uy0 = y0 + r * cellD
        const ux1 = ux0 + cellW * 0.9, uy1 = uy0 + cellD * 0.9
        units.push({
          id: `seed-unit-${building.id}-${i}-${r}-${c}`,
          footprint_geojson: JSON.stringify([[ux0, uy0], [ux1, uy0], [ux1, uy1], [ux0, uy1], [ux0, uy0]]),
          parcel_type: floorNumber === 1 ? 'commercial_unit' : 'residential_unit',
        })
      }
    }
    return {
      id: `seed-floor-${building.id}-${i}`,
      floor_number: floorNumber,
      z_min: i * floorHeight,
      z_max: (i + 1) * floorHeight,
      units,
      seeded: true,
    }
  })
}

const UNSURVEYED_HEIGHT_M = 6

function computeFrame(parcel, focusedBuildingId) {
  if (!parcel) return { cameraPos: DEFAULT_CAMERA_POS, target: DEFAULT_TARGET, center: { x: DEFAULT_TARGET.x, z: DEFAULT_TARGET.z }, extent: 30 }

  let maxHeight = 0
  let extent = 30
  let centerX = 15
  let centerZ = 11

  const focusedBuilding = focusedBuildingId
    ? parcel.buildings?.find((b) => b.id === focusedBuildingId)
    : null

  const buildingPts = []
  if (focusedBuilding) {
    const pts = safeParse(focusedBuilding.footprint_geojson)
    if (pts && pts.length >= 3) buildingPts.push(...pts)
  } else {
    parcel.buildings?.forEach((b) => {
      const pts = safeParse(b.footprint_geojson)
      if (pts && pts.length >= 3) buildingPts.push(...pts)
    })
  }

  const framePts = buildingPts.length >= 3 ? buildingPts : safeParse(parcel.footprint_geojson)
  if (framePts && framePts.length >= 3) {
    let minX = Math.min(...framePts.map((p) => p[0])), maxX = Math.max(...framePts.map((p) => p[0]))
    let minY = Math.min(...framePts.map((p) => p[1])), maxY = Math.max(...framePts.map((p) => p[1]))
    if (!focusedBuilding && parcel.infra?.available) {
      const near = (parcel.infra.features || []).filter((f) => f.on_parcel || f.distance_m <= 60)
      const b = infraBounds(near)
      if (b) {
        minX = Math.min(minX, b.minX); maxX = Math.max(maxX, b.maxX)
        minY = Math.min(minY, b.minY); maxY = Math.max(maxY, b.maxY)
      }
    }
    centerX = (minX + maxX) / 2
    centerZ = (minY + maxY) / 2
    extent = Math.max(maxX - minX, maxY - minY)
  }

  if (focusedBuilding) {
    const h = focusedBuilding.height_m || (focusedBuilding.num_floors ? focusedBuilding.num_floors * 3 : UNSURVEYED_HEIGHT_M)
    if (h > maxHeight) maxHeight = h
  } else {
    parcel.buildings?.forEach((b) => {
      const h = b.height_m || (b.num_floors ? b.num_floors * 3 : UNSURVEYED_HEIGHT_M)
      if (h > maxHeight) maxHeight = h
    })
  }
  maxHeight = Math.max(maxHeight, UNSURVEYED_HEIGHT_M)

  const span = Math.max(extent, maxHeight)
  const distance = Math.max(span * 1.0 + 3, 9)
  const cameraHeightBasis = Math.max(maxHeight, 6)

  return {
    cameraPos: {
      x: centerX + distance * 0.6,
      y: cameraHeightBasis * 0.85 + distance * 0.35,
      z: centerZ + distance * 0.6,
    },
    target: { x: centerX, y: maxHeight / 3, z: centerZ },
    center: { x: centerX, z: centerZ },
    extent,
  }
}

const ThreeScene = forwardRef(function ThreeScene({ parcel, layers, mode, onSelect, selectedId, isolatedFloorId, focusedBuildingId, exploded, sectionEnabled, sectionHeight, buildingStyle = 'detailed', sceneTheme = 'dark' }, ref) {
  const mountRef = useRef(null)
  const stateRef = useRef({})

  useImperativeHandle(ref, () => ({
    zoomIn() {
      const { camera, controls } = stateRef.current
      if (!camera || !controls) return
      const dir = new THREE.Vector3().subVectors(camera.position, controls.target).multiplyScalar(0.8)
      camera.position.copy(controls.target).add(dir)
    },
    zoomOut() {
      const { camera, controls } = stateRef.current
      if (!camera || !controls) return
      const dir = new THREE.Vector3().subVectors(camera.position, controls.target).multiplyScalar(1.25)
      camera.position.copy(controls.target).add(dir)
    },
    resetView() {
      const { camera, controls } = stateRef.current
      if (!camera || !controls) return
      const frame = computeFrame(parcel, focusedBuildingId)
      const center = frame.center || { x: 0, z: 0 }
      camera.position.set(frame.cameraPos.x - center.x, frame.cameraPos.y, frame.cameraPos.z - center.z)
      controls.target.set(frame.target.x - center.x, frame.target.y, frame.target.z - center.z)
      controls.update()
    },
    topView() {
      const { camera, controls } = stateRef.current
      if (!camera || !controls) return
      const distance = camera.position.distanceTo(controls.target) || 60
      camera.position.set(controls.target.x, controls.target.y + distance, controls.target.z + 0.01)
      controls.update()
    },
    rotate(axis, deltaRad) {
      const { camera, controls } = stateRef.current
      if (!camera || !controls) return
      const offset = new THREE.Vector3().subVectors(camera.position, controls.target)
      const spherical = new THREE.Spherical().setFromVector3(offset)
      if (axis === 'horizontal') {
        spherical.theta += deltaRad
      } else {
        spherical.phi = Math.max(0.001, Math.min(Math.PI - 0.001, spherical.phi + deltaRad))
      }
      offset.setFromSpherical(spherical)
      camera.position.copy(controls.target).add(offset)
      controls.update()
    },
  }))

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    const scene = new THREE.Scene()
    const isDark = sceneTheme === 'dark'
    const bgColor = isDark ? 0x0E1420 : 0xEDEAE0
    scene.background = new THREE.Color(bgColor)
    scene.fog = new THREE.Fog(bgColor, 140, 700)

    const camera = new THREE.PerspectiveCamera(45, mount.clientWidth / mount.clientHeight, 0.1, 2000)
    const initialFrame = computeFrame(parcel, focusedBuildingId)
    const frameCenter = initialFrame.center || { x: 0, z: 0 }
    const originX = frameCenter.x
    const originZ = frameCenter.z
    function shiftPts(pts) {
      return pts ? pts.map(([x, y]) => [x - originX, y - originZ]) : pts
    }
    camera.position.set(
      initialFrame.cameraPos.x - originX,
      initialFrame.cameraPos.y,
      initialFrame.cameraPos.z - originZ,
    )

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(mount.clientWidth, mount.clientHeight)
    mount.appendChild(renderer.domElement)

    renderer.localClippingEnabled = true
    const sectionPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), sectionHeight ?? 9999)
    renderer.clippingPlanes = sectionEnabled ? [sectionPlane] : []

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.minDistance = 5
    controls.maxDistance = 600
    controls.minPolarAngle = 0
    controls.maxPolarAngle = Math.PI
    controls.enableRotate = true
    controls.enablePan = true
    controls.screenSpacePanning = true
    controls.rotateSpeed = 0.9
    controls.target.set(initialFrame.target.x - originX, initialFrame.target.y, initialFrame.target.z - originZ)
    controls.update()

    scene.add(new THREE.AmbientLight(0xffffff, 0.55))
    const sun = new THREE.DirectionalLight(0xffffff, 1.1)
    sun.position.set(40, 60, 20)
    scene.add(sun)
    const rim = new THREE.DirectionalLight(0x5C8A6B, 0.3)
    rim.position.set(-30, 20, -30)
    scene.add(rim)
    if (isDark) scene.add(new THREE.HemisphereLight(0xBFD8FF, 0x1A2230, 0.6))

    const gridSize = Math.min(2000, Math.max(60, (initialFrame.extent ?? 30) * 4))
    const grid = new THREE.GridHelper(gridSize, 40, isDark ? 0x1F7A96 : 0xB6AF98, isDark ? 0x152A3D : 0xDAD5C3)
    grid.position.set(0, -0.05, 0)
    scene.add(grid)

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const selectableMeshes = []

    function addExtrusion(points, zBottom, zTop, color, opacity, userData, outlineOnly = false) {
      const validPoints = Array.isArray(points)
        ? points.filter((p) => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]))
        : []
      if (validPoints.length < 3 || !Number.isFinite(zBottom) || !Number.isFinite(zTop)) {
        console.warn('Skipping degenerate shape in 3D view', { userData, pointCount: validPoints.length, zBottom, zTop })
        return null
      }
      const shape = polygonShape(validPoints)
      const depth = Math.max(zTop - zBottom, 0.1)
      const geometry = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false })
      geometry.rotateX(-Math.PI / 2)
      const material = new THREE.MeshStandardMaterial({
        color, transparent: true, opacity, roughness: 0.5, metalness: 0.05,
        side: THREE.DoubleSide,
      })
      const mesh = new THREE.Mesh(geometry, material)
      mesh.position.y = zBottom
      mesh.userData = userData
      scene.add(mesh)

      const edges = new THREE.EdgesGeometry(geometry)
      const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x16241F, opacity: 0.5, transparent: true }))
      line.position.y = zBottom
      scene.add(line)

      if (userData?.selectable) selectableMeshes.push(mesh)
      return mesh
    }

    function addPickProxy(points, zBottom, zTop, userData) {
      const validPoints = Array.isArray(points)
        ? points.filter((p) => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]))
        : []
      if (validPoints.length < 3 || !Number.isFinite(zBottom) || !Number.isFinite(zTop)) return null
      const geometry = new THREE.ExtrudeGeometry(polygonShape(validPoints), { depth: Math.max(zTop - zBottom, 0.1), bevelEnabled: false })
      geometry.rotateX(-Math.PI / 2)
      const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false, side: THREE.DoubleSide }))
      mesh.position.y = zBottom
      mesh.userData = userData
      scene.add(mesh)
      selectableMeshes.push(mesh)
      return mesh
    }

    try {
    if (parcel) {
      const parcelPts = shiftPts(safeParse(parcel.footprint_geojson)) || [[0, 0], [30, 0], [30, 22.5], [0, 22.5]]

      if (layers.parcel && mode === '2d') {
        addExtrusion(parcelPts, 0, 0.15, 0xC9C2AE, 0.55, { type: 'parcel', id: parcel.id, selectable: true })
      }

      if (mode === '3d') {
        if (layers.parcel) {
          addExtrusion(parcelPts, -0.1, 0.05, 0xC9C2AE, 0.25, { type: 'parcel', id: parcel.id, selectable: false })
        }

        let detailedExtent = 0
        parcel.buildings?.forEach((b) => {
          try {
          const bPts = shiftPts(safeParse(b.footprint_geojson)) || parcelPts
          const isFocused = !focusedBuildingId || focusedBuildingId === b.id
          const buildingHeight = b.height_m || (b.num_floors ? b.num_floors * 3 : UNSURVEYED_HEIGHT_M)

          if (!isFocused) {
            addExtrusion(bPts, 0, buildingHeight, 0x4A6B5D, 0.32, { type: 'building', id: b.id, selectable: true })
            return
          }

          const sortedFloors = [...(b.floors?.length ? b.floors : seedFloors(b, bPts))].sort((a, c) => a.floor_number - c.floor_number)

          let activeFloor = isolatedFloorId ? (sortedFloors.find((f) => f.id === isolatedFloorId) || null) : null
          if (!activeFloor && selectedId) activeFloor = sortedFloors.find((f) => f.units?.some((u) => u.id === selectedId)) || null

          const offsetFor = (f, floorIdx, detailed) =>
            (exploded ? floorIdx * EXPLODE_GAP : 0) +
            (detailed && activeFloor && !exploded && f.floor_number > activeFloor.floor_number ? ACTIVE_LIFT : 0)

          let detailedOK = false
          if (buildingStyle === 'detailed' && layers.buildings) {
            try {
              const ring = footprintToRing(bPts)
              const planFloors = []
              sortedFloors.forEach((f, floorIdx) => {
                if (!(f.z_max > 0.01)) return
                const off = offsetFor(f, floorIdx, true)
                const kind = floorKind(f)
                planFloors.push({
                  y0: Math.max(f.z_min, 0) + off, y1: f.z_max + off, kind,
                  accent: kind === 'residential' && f.floor_number % 3 === 0,
                  active: !!activeFloor && activeFloor.id === f.id,
                })
              })
              const nBuildings = parcel.buildings?.length || 1
              const detail = nBuildings > 12 ? 0 : nBuildings > 5 ? 1 : 2
              const model = createDetailedBuilding({ ring, floors: planFloors, detail })
              scene.add(model.group)
              detailedOK = true
              detailedExtent = Math.max(detailedExtent, model.meta.extent)

              try {
                const [mcx, mcz] = model.meta.centroid
                const shadowSize = model.meta.extent * 1.7
                const shadow = createContactShadow(shadowSize, shadowSize, isDark ? 0.7 : 0.35)
                shadow.position.set(mcx, 0.07, mcz)
                scene.add(shadow)

                if (activeFloor) {
                  const aIdx = sortedFloors.indexOf(activeFloor)
                  const pad2 = (n) => String(Math.abs(n)).padStart(2, '0')
                  const fCode = activeFloor.floor_code || `F${pad2(activeFloor.floor_number)}`
                  const selUnit = selectedId ? activeFloor.units?.find((u) => u.id === selectedId) : null
                  const uCode = selUnit ? (selUnit.unit_code || `U${pad2(activeFloor.units.indexOf(selUnit) + 1)}`) : null
                  const label = createLabelSprite(uCode ? `${fCode}-${uCode}` : fCode, Math.max(5, model.meta.extent * 0.3))
                  label.position.set(mcx, activeFloor.z_max + offsetFor(activeFloor, aIdx, true) + 1.8, mcz)
                  scene.add(label)
                }
              } catch (err) {
                console.warn('3D view: facade extras (shadow/label) failed', err)
              }
            } catch (err) {
              console.warn(`3D view: detailed facade unavailable for building ${b.id}, using plain volumes`, err)
              detailedOK = false
            }
          }

          if (layers.buildings && !exploded && !detailedOK) {
            const shellMesh = addExtrusion(bPts, 0, buildingHeight, 0x8FBFAE, 0.22, { type: 'building', id: b.id, selectable: false })

            if (b.drone_image_path) {
              textureLoader.load(
                `/api/processing/buildings/${b.id}/imagery/file`,
                (texture) => {
                  texture.colorSpace = THREE.SRGBColorSpace
                  texture.wrapS = THREE.ClampToEdgeWrapping
                  texture.wrapT = THREE.ClampToEdgeWrapping
                  shellMesh.material.map = texture
                  shellMesh.material.color.set(0xffffff)
                  shellMesh.material.opacity = 0.92
                  shellMesh.material.needsUpdate = true
                },
                undefined,
                () => {   },
              )
            }
          }

          const useFullDetail = b.num_floors <= FLOOR_DETAIL_THRESHOLD || isolatedFloorId

          const drawFloorUnits = (f, zMin, zMax) => {
            f.units?.forEach((u) => {
              const uPts = shiftPts(safeParse(u.footprint_geojson))
              if (!uPts) return
              const color = TYPE_COLORS[u.parcel_type] || TYPE_COLORS.default
              const isSelected = u.id === selectedId
              const statusOpacity = u.verification_status === 'approved' ? 0.55 : 0.3
              addExtrusion(
                uPts, zMin, zMax,
                isSelected ? 0xC9A24E : color,
                isSelected ? 0.85 : statusOpacity,
                {
                  type: 'unit', id: u.id, selectable: true,
                  seeded: f.seeded, unitData: f.seeded ? { ...u, z_min: f.z_min, z_max: f.z_max } : undefined,
                  buildingId: b.id, floorNumber: f.floor_number,
                }
              )
            })
          }

          sortedFloors.forEach((f, floorIdx) => {
            const isIsolatedFloor = isolatedFloorId === f.id
            const showFullFloorDetail = layers.units && (useFullDetail ? (isolatedFloorId ? isIsolatedFloor : true) : false)
            const explodeOffset = offsetFor(f, floorIdx, detailedOK)
            const zMin = f.z_min + explodeOffset
            const zMax = f.z_max + explodeOffset

            if (detailedOK && f.z_max > 0.01) {
              const floorHit = {
                type: 'floor', id: f.id, selectable: true,
                seeded: f.seeded, floorData: f.seeded ? f : undefined,
                buildingId: b.id, buildingCode: b.building_code, buildingFootprintGeojson: b.footprint_geojson,
              }
              if (activeFloor && activeFloor.id === f.id) {
                addExtrusion(bPts, zMin, zMax, 0x22D3EE, 0.12, { type: 'floor', id: f.id, selectable: false })
                if (layers.units && f.units?.length) drawFloorUnits(f, zMin, zMax)
                else addPickProxy(bPts, zMin, zMax, floorHit)
              } else {
                addPickProxy(bPts, zMin, zMax, floorHit)
              }
              return
            }

            if (showFullFloorDetail) {
              if (exploded) {
                const dimmed = isolatedFloorId && !isIsolatedFloor
                addExtrusion(bPts, zMin, zMax, 0x3E8E7E, dimmed ? 0.08 : 0.32, {
                  type: 'floor', id: f.id, selectable: true,
                  seeded: f.seeded, floorData: f.seeded ? f : undefined,
                  buildingId: b.id, buildingCode: b.building_code, buildingFootprintGeojson: b.footprint_geojson,
                })
              }
              drawFloorUnits(f, zMin, zMax)
            } else if (layers.buildings || layers.units) {
              const dimmed = isolatedFloorId && !isIsolatedFloor
              addExtrusion(bPts, zMin, zMax, 0x3E8E7E, dimmed ? 0.10 : (exploded ? 0.32 : 0.24), {
                type: 'floor', id: f.id, selectable: true,
                seeded: f.seeded, floorData: f.seeded ? f : undefined,
                buildingId: b.id, buildingCode: b.building_code, buildingFootprintGeojson: b.footprint_geojson,
              })
            }
          })
          } catch (err) {
            console.error(`3D view: failed to render building ${b.id} -- skipping just this one`, err)
          }
        })

        if (detailedExtent > 0) {
          const north = createNorthMarker(Math.max(3, detailedExtent * 0.16), isDark ? '#22D3EE' : '#2C5B53')
          north.position.set(0, Math.max(3, detailedExtent * 0.08), -(detailedExtent * 0.85 + 4))
          scene.add(north)
        }

        const infraFeatures = parcel.infra?.available ? (parcel.infra.features || []) : []
        const infraUg = infraFeatures.filter((f) => f.kind === 'underground')
        const infraAir = infraFeatures.filter((f) => f.kind === 'air')
        const hasInfra = infraFeatures.length > 0
        const labelW = Math.min(46, Math.max(9, (initialFrame.extent ?? 30) * 0.32))
        let labelBudget = 8
        const placeLabel = (text, hex, x, y, z, width = labelW) => {
          const sprite = createInfraLabel(text, hex, width)
          sprite.position.set(x, y, z)
          scene.add(sprite)
        }

        if (layers.underground) {
          const rows = (parcel.undergroundAssets || []).filter((a) => !(hasInfra && a.source === 'osm_auto'))
          const maxDepth = Math.max(
            0,
            ...infraUg.map((f) => Math.abs(f.z_max_m || 0)),
            ...rows.map((a) => Math.abs(a.depth_max_m || 0)),
          )
          if (maxDepth > 0) {
            const step = niceStep(maxDepth)
            const D = Math.min(45, Math.max(step * 2, Math.ceil(maxDepth / step) * step))
            const env = addExtrusion(parcelPts, -D, 0, 0xA88B62, 0.06, { type: 'ug-envelope', selectable: false })
            if (env) scene.add(makeGlowEdges(env, 0xC9A24E, 0.28))
            const [rx, ry] = parcelPts[0]
            for (let d = step; d <= D; d += step) placeLabel(`−${d} m`, 0xC9A24E, rx, -d, -ry, Math.max(3, labelW * 0.3))
          }

          rows.forEach((a) => {
            const pts = shiftPts(safeParse(a.geometry_geojson))
            if (!pts) return
            const zTop = -Math.abs(a.depth_min_m)
            const zBottom = -Math.abs(a.depth_max_m)
            addExtrusion(pts, zBottom, zTop, 0xB24A34, 0.5, { type: 'underground', id: a.id, selectable: false })
          })

          infraUg.forEach((f) => {
            const hex = infraHex(f)
            const picked = f.id === selectedId
            const zTop = -Math.abs(f.z_min_m || 0)
            const zBottom = -Math.abs(f.z_max_m || 0)
            const isVolume = f.subtype === 'basement' || f.subtype === 'underground_parking'
            const userData = { type: 'infra', id: f.id, selectable: true }
            ;(f.polygons || []).forEach((ring) => {
              const mesh = addExtrusion(shiftPts(ring), zBottom, zTop, hex, picked ? 0.85 : (isVolume ? 0.34 : 0.55), userData)
              if (mesh) scene.add(makeGlowEdges(mesh, picked ? 0xFFFFFF : hex, 0.9))
            })
            const midY = (zTop + zBottom) / 2
            let anchor = null
            ;(f.centerlines || []).forEach((line) => {
              const pts = shiftPts(line)
              if (zTop < -0.2) {
                const curtain = makeCurtain(pts, 0, zTop, hex, 0.12)
                if (curtain) scene.add(curtain)
              }
              scene.add(makePolyline(pts, midY, hex))
              if (!anchor) anchor = lineMidpoint(pts)
            })
            if (!anchor && f.polygons?.length) anchor = ringCentroid(shiftPts(f.polygons[0]))
            if (anchor && labelBudget-- > 0) placeLabel(labelText(f), hex, anchor[0], midY, -anchor[1])
          })
        }

        if (layers.airRights) {
          const rows = (parcel.airRights || []).filter((c) => !(hasInfra && c.source === 'osm_auto'))
          rows.forEach((c) => {
            const pts = shiftPts(safeParse(c.geometry_geojson))
            if (!pts) return
            addExtrusion(pts, c.height_min_m, c.height_max_m, 0x8b5cf6, 0.35, { type: 'airright', id: c.id, selectable: false })
          })

          infraAir.forEach((f) => {
            const hex = infraHex(f)
            const picked = f.id === selectedId
            const zMin = f.z_min_m ?? 0
            const zMax = Math.max(f.z_max_m ?? (zMin + 1), zMin + 0.5)
            const userData = { type: 'infra', id: f.id, selectable: true }
            ;(f.polygons || []).forEach((ring) => {
              const pts = shiftPts(ring)
              const mesh = addExtrusion(pts, zMin, zMax, hex, picked ? 0.6 : 0.26, userData)
              if (mesh) scene.add(makeGlowEdges(mesh, picked ? 0xFFFFFF : hex, 0.9))
              if (f.deck_top_m != null && f.deck_top_m > zMin + 0.1) {
                addExtrusion(pts, zMin, Math.min(f.deck_top_m, zMax), hex, 0.7, { type: 'infra', id: f.id, selectable: false })
              }
              addExtrusion(pts, 0.02, 0.07, hex, 0.16, { type: 'infra-ground', selectable: false })
            })
            const anchor = f.polygons?.length ? ringCentroid(shiftPts(f.polygons[0])) : null
            if (anchor && labelBudget-- > 0) placeLabel(labelText(f), hex, anchor[0], zMax + 1.6, -anchor[1])
          })
        }
      }
    }
    } catch (err) {
      console.error('3D view: failed to build scene geometry for this parcel -- showing ground/grid only', err)
    }

    function onPointerDown(event) {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(pointer, camera)
      const intersects = raycaster.intersectObjects(selectableMeshes)
      if (intersects.length > 0) {
        const hit = intersects[0].object.userData
        onSelect?.(hit)
      }
    }
    renderer.domElement.addEventListener('pointerdown', onPointerDown)

    function handleResize() {
      if (!mount) return
      camera.aspect = mount.clientWidth / mount.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(mount.clientWidth, mount.clientHeight)
    }
    const resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(mount)

    let raf
    function animate() {
      raf = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    stateRef.current = { renderer, controls, camera, sectionPlane }

    return () => {
      cancelAnimationFrame(raf)
      resizeObserver.disconnect()
      renderer.domElement.removeEventListener('pointerdown', onPointerDown)
      controls.dispose()
      scene.traverse((obj) => {
        obj.geometry?.dispose()
        const materials = Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : []
        materials.forEach((m) => { m.map?.dispose(); m.dispose() })
      })
      mount.removeChild(renderer.domElement)
      renderer.dispose()
      renderer.forceContextLoss()
    }
  }, [parcel, layers, mode, selectedId, isolatedFloorId, focusedBuildingId, exploded, buildingStyle, sceneTheme])

  useEffect(() => {
    const { renderer, sectionPlane } = stateRef.current
    if (!renderer || !sectionPlane) return
    sectionPlane.constant = sectionHeight ?? 9999
    renderer.clippingPlanes = sectionEnabled ? [sectionPlane] : []
  }, [sectionEnabled, sectionHeight])

  return <div ref={mountRef} className="w-full h-full touch-none" />
})

export default ThreeScene

function safeParse(str) {
  if (!str) return null
  try {
    const parsed = JSON.parse(str)
    return Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}
