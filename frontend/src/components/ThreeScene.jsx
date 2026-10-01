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

// Reused across every texture load in this component instead of a new
// loader per building.
const textureLoader = new THREE.TextureLoader()

// Above this many floors, a building defaults to simplified per-floor
// slabs (no individual unit walls/edges) instead of full unit-level
// detail — this is what actually caused the "messy/noisy" look on a
// 20-floor building: every unit was rendering both a fill mesh AND an
// edge-line mesh, so 240 units meant 480 overlapping objects with every
// internal wall visible at once. Clicking a floor "isolates" it (full
// detail for that floor only, every other floor collapses to a slab),
// which keeps total mesh count low regardless of building size.
const FLOOR_DETAIL_THRESHOLD = 6

const DEFAULT_CAMERA_POS = { x: 45, y: 38, z: 45 }
const DEFAULT_TARGET = { x: 15, y: 6, z: 11 }

// "Exploded Floors" view: each floor above the ground floor is lifted by an
// extra fixed offset (on top of its real z_min/z_max), pulling the stack
// apart into evenly-spaced slabs so every floor is visible at once without
// overlapping neighbours. Real floor heights/areas are untouched — this is
// purely a display offset, same idea as an exploded-view diagram.
const EXPLODE_GAP = 2.5

// Detailed-facade view: when a floor (or a unit on it) is selected, every
// floor ABOVE it is lifted by this much so the selected floor is opened up
// and highlighted cyan instead of staying buried inside the stack. Display
// offset only -- real z_min/z_max are untouched.
const ACTIVE_LIFT = 3.4

// Dominant unit type on a floor -> which facade treatment it gets
// (brick = commercial, concrete = parking, sand = residential).
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

// A building that hasn't been surveyed yet has no real Floor rows at all
// (num_floors=0/height_m=null on the record, per the backend's
// "never invent data" rule -- see processing_router.py) -- so, until now,
// the 3D view had nothing to loop over and fell back to drawing just the
// single translucent outer shell (addExtrusion(bPts, 0, buildingHeight...)
// a bit further down), which is what read as "no 3D view" even once the
// camera-framing bug was fixed. This generates the SAME floors/units a
// real survey would produce -- using estimateBuildingDimensions()'s
// per-building estimate (varies with this building's own footprint area
// and id -- see that file -- not a flat number every unsurveyed building
// shares) -- so there's something floor- and unit-shaped to render and
// explode, and it looks different from one unsurveyed building to the
// next instead of all reading as the same placeholder box. Units are
// laid out with the same grid-subdivision approach the backend's real
// delineate_units() uses on an actual survey (see that function) -- not a
// different invented layout. Every generated floor/unit is tagged
// `seeded: true` and never selectable (no real per-floor/unit data
// exists to show if one were clicked), so none of this can be mistaken
// for -- or accidentally treated as -- a real survey result anywhere
// else in the app. This function only ever returns throwaway client-side
// geometry; nothing here is written back to the building record.
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

/**
 * Placeholder extrusion height for a building with NO real height_m or
 * num_floors on record at all (bumped from a flat 3m to read as more than
 * a paving slab on screen). Shared between computeFrame's camera framing
 * and the actual mesh below so the two always stay consistent -- a real
 * height_m value is NEVER run through this, so a verified survey height
 * is never visually inflated, only the "nothing on record" case.
 */
const UNSURVEYED_HEIGHT_M = 6

/**
 * Auto-frames the camera based on the ACTUAL building size in this parcel,
 * instead of a fixed position tuned for one demo building. Without this, a
 * tall building (e.g. 20 floors / 60m) would load mostly out of frame above
 * a camera positioned for a ~15m building, and a very small building would
 * be a tiny speck in a wide-open view. Computed from real footprint extent
 * and the tallest building's real height_m -- not guessed.
 */
function computeFrame(parcel, focusedBuildingId, aspect = 1) {
  if (!parcel) return { cameraPos: DEFAULT_CAMERA_POS, target: DEFAULT_TARGET, center: { x: DEFAULT_TARGET.x, z: DEFAULT_TARGET.z }, extent: 30 }

  let maxHeight = 0
  let extent = 30
  let centerX = 15
  let centerZ = 11

  // When a specific building is focused (e.g. opened from "Open Full
  // Inspector" on a specific building), frame tightly on just THAT
  // building's own footprint + height instead of the whole parcel's
  // building set -- otherwise a single building on a multi-building
  // parcel still looked small because the camera was fit to every
  // other building on the lot too.
  const focusedBuilding = focusedBuildingId
    ? parcel.buildings?.find((b) => b.id === focusedBuildingId)
    : null

  // Frame around the BUILDINGS' own footprint(s), not the parcel's --
  // a parcel is routinely far larger than what sits on it (e.g. a
  // 67m x 67m parcel holding one 8m x 8m building), so framing on the
  // parcel's extent left every building looking like a tiny speck no
  // matter how close the camera actually was. Falls back to the
  // parcel's own extent only when there's no building yet to frame on.
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

  let buildingOnlyExtent = extent
  const framePts = buildingPts.length >= 3 ? buildingPts : safeParse(parcel.footprint_geojson)
  if (framePts && framePts.length >= 3) {
    let minX = Math.min(...framePts.map((p) => p[0])), maxX = Math.max(...framePts.map((p) => p[0]))
    let minY = Math.min(...framePts.map((p) => p[1])), maxY = Math.max(...framePts.map((p) => p[1]))
    buildingOnlyExtent = Math.max(maxX - minX, maxY - minY)
    centerX = (minX + maxX) / 2
    centerZ = (minY + maxY) / 2
    // Underground structures / corridors that cross or run right beside the parcel (real open-data
    // features from GET /api/infra/parcel/{id}) belong in the default frame too -- otherwise a metro
    // line 30 m from the building is off-screen and the layers look empty. Distant ones (beyond 60 m)
    // stay reachable by orbiting/zooming but don't shrink the building. `buildingOnlyExtent` above is
    // kept from BEFORE this union specifically so a portrait/mobile canvas can cap how much a
    // far-reaching corridor (e.g. a cable running the length of the plot) is allowed to shrink the
    // building on first view -- see the mobile-only distance cap below.
    if (!focusedBuilding && parcel.infra?.available) {
      const near = (parcel.infra.features || []).filter((f) => f.on_parcel || f.distance_m <= 60)
      const b = infraBounds(near)
      if (b) {
        minX = Math.min(minX, b.minX); maxX = Math.max(maxX, b.maxX)
        minY = Math.min(minY, b.minY); maxY = Math.max(maxY, b.maxY)
        centerX = (minX + maxX) / 2
        centerZ = (minY + maxY) / 2
      }
    }
    extent = Math.max(maxX - minX, maxY - minY)
  }

  // Same height fallback the actual mesh uses below -- b.height_m if a
  // real survey value exists, else a flat placeholder for buildings with
  // NO real height data at all (bumped from 3m to UNSURVEYED_HEIGHT_M so
  // an unsurveyed building reads as more than a paving slab on screen;
  // this only ever changes the placeholder, never a real height_m value,
  // so verified survey data is never visually inflated). This used to
  // default to a phantom 15m for ANY building missing real height data,
  // even though the mesh itself only ever rendered the placeholder height
  // for that building -- exactly the "small building lost in a lot of
  // empty space" mismatch, on precisely the buildings most likely to have
  // no real height (auto-generated/ML-detected, unsurveyed).
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
  // Padding scales with span instead of being a large fixed offset, and a
  // floor keeps the camera from clipping through a tiny building, so a
  // small building fills a reasonable portion of the frame instead of
  // defaulting to "far away and tiny" regardless of its real size.
  // Tightened further still (1.0x + 3, was 1.25x + 5, originally 1.8x + 8)
  // so the default view sits close to the building rather than a wide
  // establishing shot.
  let distance = Math.max(span * 1.0 + 3, 9)
  // Desktop/landscape (aspect >= 1): UNCHANGED from before -- distance is still based on the full
  // span (building + any nearby infra unioned in above).
  //
  // Mobile/portrait (aspect < 1), two corrections, both scoped to this branch only:
  //  1. Cap how far nearby infra alone is allowed to pull the camera back. A corridor/cable running
  //     well beyond the building's own footprint (even though within the 60m "include it" radius
  //     above) could otherwise make distance -- and so the building's on-screen size -- dominated by
  //     the infra's extent rather than the building's, shrinking the building to a speck on a small
  //     screen even though the exact same scene reads fine on a spacious desktop canvas. Clamping to
  //     at most MOBILE_INFRA_DISTANCE_CAP x the building-only distance keeps the building the clear
  //     visual focus on first view; the full infra extent is still fully reachable by pinch-zooming
  //     or orbiting out, exactly as it always was.
  //  2. THEN apply the same horizontal/vertical FOV correction as before: the camera's `fov` (set
  //     where it's constructed, below) is the VERTICAL field of view, and the HORIZONTAL one it
  //     actually shows shrinks with the canvas's aspect ratio. `distance` was tuned to fit span in
  //     the vertical FOV alone, which is the tighter (binding) constraint on a landscape canvas --
  //     on a portrait phone canvas the horizontal FOV is tighter instead, so without this the
  //     building's width overflowed the narrower horizontal FOV (the close-up/cropped bug). Scaling
  //     by 1/aspect compensates for that.
  if (aspect < 1) {
    const MOBILE_INFRA_DISTANCE_CAP = 1.8
    const buildingOnlySpan = Math.max(buildingOnlyExtent, maxHeight)
    const buildingOnlyDistance = Math.max(buildingOnlySpan * 1.0 + 3, 9)
    distance = Math.min(distance, buildingOnlyDistance * MOBILE_INFRA_DISTANCE_CAP)
    distance /= aspect
  }
  const cameraHeightBasis = Math.max(maxHeight, 6) // keeps a real 3/4-view angle even for a single-storey building instead of a near-flat, side-on view

  return {
    // Both offset from the building's real centre (centerX/centerZ), not
    // an absolute world position -- a building whose footprint isn't near
    // local-frame (0,0) (e.g. a freshly ML-detected footprint, positioned
    // wherever its source imagery's pixel coordinates happened to land)
    // used to get a camera parked near world-origin while `target` was set
    // to the real (far-away) centre. OrbitControls' distance clamp
    // (min/maxDistance, applied on every controls.update()) then snapped
    // the camera along whatever direction that near-origin position
    // happened to be from the target -- essentially a coin flip, and on a
    // building whose centre sat behind the near clip plane or outside the
    // frustum from that angle, the canvas rendered nothing but the empty
    // background. Every other layer (grid, parcel plate) also lives at/near
    // world-origin, so this only ever showed up on off-origin buildings --
    // exactly the ML-detected case, never the origin-centred seed data.
    cameraPos: {
      x: centerX + distance * 0.6,
      y: cameraHeightBasis * 0.85 + distance * 0.35,
      z: centerZ + distance * 0.6,
    },
    target: { x: centerX, y: maxHeight / 3, z: centerZ },
    // Exposed so the caller can put the ground grid where the camera
    // actually is, rather than always at world-origin -- see the grid
    // setup in the main effect below.
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
      const mount = mountRef.current
      if (!camera || !controls) return
      const frame = computeFrame(parcel, focusedBuildingId, mount ? mount.clientWidth / mount.clientHeight : 1)
      // Must reapply the SAME floating-origin shift the scene's geometry
      // was actually built with (see the main effect below) -- parcel/
      // focusedBuildingId haven't changed here, so computeFrame's own
      // center is identical to what was baked into the scene, but the
      // camera/target values coming straight out of computeFrame are
      // still in absolute (potentially huge) coordinates and need the
      // same subtraction before being applied.
      const center = frame.center || { x: 0, z: 0 }
      camera.position.set(frame.cameraPos.x - center.x, frame.cameraPos.y, frame.cameraPos.z - center.z)
      controls.target.set(frame.target.x - center.x, frame.target.y, frame.target.z - center.z)
      controls.update()
    },
    topView() {
      // Straight top-down orthographic-feeling view: keep the current
      // look-at target and distance, just move the camera directly above
      // it (tiny z nudge so OrbitControls doesn't hit the polar-angle
      // singularity looking straight down).
      const { camera, controls } = stateRef.current
      if (!camera || !controls) return
      const distance = camera.position.distanceTo(controls.target) || 60
      camera.position.set(controls.target.x, controls.target.y + distance, controls.target.z + 0.01)
      controls.update()
    },
    rotate(axis, deltaRad) {
      // axis: 'horizontal' (left/right, orbits around vertical axis) or
      // 'vertical' (up/down, orbits around the camera's local horizontal axis).
      // Full range is allowed — including flipping past the top/bottom of
      // the model, matching a real free-orbit camera.
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
    // Light neutral background (was a dark green 0x0F211D) so building
    // materials -- sage green / gold / grey unit colors -- read clearly
    // against it instead of blending into a dark void, matching the
    // app's own light UI theme rather than fighting it.
    // sceneTheme 'dark' = the BHU-3D reference look (navy void + cyan grid);
    // 'light' = the original cream scene.
    const isDark = sceneTheme === 'dark'
    const bgColor = isDark ? 0x0E1420 : 0xEDEAE0
    scene.background = new THREE.Color(bgColor)
    scene.fog = new THREE.Fog(bgColor, 140, 700)

    const camera = new THREE.PerspectiveCamera(45, mount.clientWidth / mount.clientHeight, 0.1, 2000)
    const initialFrame = computeFrame(parcel, focusedBuildingId, mount.clientWidth / mount.clientHeight)
    // FLOATING ORIGIN: a bulk-imported building's footprint is stored in
    // local metres offset from its whole import job's bbox corner (see
    // bulk_import_router.py's origin_lat/origin_lon), which can place a
    // single building tens of thousands of metres from world-origin if
    // the job covered a large area. The grid-position fix below (moving
    // the grid to `frameCenter`) only fixed the grid -- it's positioned
    // via an object-level transform, which Three.js/WebGL handle fine at
    // large magnitudes. The actual BUILDING geometry is different: its
    // vertex coordinates are baked directly from the raw footprint
    // points into the ExtrudeGeometry's vertex buffer, which gets
    // truncated to 32-bit floats for the GPU. At a magnitude of
    // 10,000-100,000+ that leaves roughly 1 unit of precision -- far too
    // coarse for a building a few metres across, so the mesh comes out
    // degenerate/invisible even though every camera/target number
    // computed in JS looks completely correct and the grid renders fine.
    // Fix: shift EVERY coordinate fed to Three.js (camera, target, grid,
    // and every footprint/geometry point below) by the same amount --
    // the building's own real centre -- so the numbers Three.js actually
    // builds geometry from always stay small/near-origin, regardless of
    // where the backend anchored them. The visual result is identical to
    // what the unshifted math intended; only the raw magnitudes change.
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

    // Vertical section/slice tool: a real Three.js clipping plane (not a
    // visual trick) that discards geometry above the slice height, so
    // dragging the slider genuinely reveals what's underneath -- floors,
    // basements, underground assets -- for inspecting vertical overlaps.
    // Global renderer.clippingPlanes applies to every material without
    // needing per-mesh wiring. Updated by a separate lightweight effect
    // below (not this one) so scrubbing the slider never triggers a full
    // scene rebuild.
    renderer.localClippingEnabled = true
    const sectionPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), sectionHeight ?? 9999)
    renderer.clippingPlanes = sectionEnabled ? [sectionPlane] : []

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.minDistance = 5
    controls.maxDistance = 600
    // Full free rotation in every direction (up/down/left/right), including
    // looking from underneath the model — no polar-angle clamp.
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
    if (isDark) scene.add(new THREE.HemisphereLight(0xBFD8FF, 0x1A2230, 0.6)) // lifts the shaded facade faces off the dark background

    // ground grid -- darker/lighter tan pair tuned for the light
    // background above (the old dark-green pair was tuned for a dark
    // scene and was nearly invisible against it).
    //
    // Sized and CENTERED on the same point computeFrame() targets, not a
    // fixed world-origin (0,0) -- a bulk-imported building's footprint is
    // stored in local meters offset from its whole import job's bbox
    // corner (see bulk_import_router.py's origin_lat/origin_lon), which
    // routinely places a single building thousands of meters from
    // world-origin. The camera already correctly follows the building's
    // real position; a grid fixed at (0,0) was simply nowhere near it, so
    // the view read as entirely blank even when the building itself was
    // rendering fine, just with no visible ground reference anywhere close
    // to the camera. Sized to the actual extent (with a floor/ceiling) so
    // it reads sensibly at both a single small building and a whole-parcel
    // view, instead of a fixed 200 that could be either way too small or
    // (irrelevantly) huge for the building actually on screen.
    const gridSize = Math.min(2000, Math.max(60, (initialFrame.extent ?? 30) * 4))
    const grid = new THREE.GridHelper(gridSize, 40, isDark ? 0x1F7A96 : 0xB6AF98, isDark ? 0x152A3D : 0xDAD5C3)
    grid.position.set(0, -0.05, 0) // frameCenter is now the scene's local origin -- everything (camera, target, grid, geometry below) is shifted by it consistently
    scene.add(grid)

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const selectableMeshes = []

    function addExtrusion(points, zBottom, zTop, color, opacity, userData, outlineOnly = false) {
      // A polygon with fewer than 3 usable points, or any non-finite
      // coordinate (NaN/Infinity -- e.g. from a corrupted footprint or a
      // divide-by-zero somewhere upstream), produces degenerate geometry
      // that either renders as nothing or throws inside ExtrudeGeometry.
      // Either way, letting that exception propagate used to abort this
      // entire effect mid-way through -- skipping the animate() call at
      // the bottom of it, which meant the canvas never rendered a single
      // frame and looked completely blank, not just missing one building.
      // Skipping just this one shape (and logging why) keeps every other
      // real, valid shape in the scene rendering normally.
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

    // Invisible-but-raycastable prism: lets a click on the detailed facade
    // (which is one merged, non-selectable mesh) resolve to the right floor.
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

    // --- Build geometry from real parcel/building/floor/unit data ---
    // The whole block is wrapped in try/catch: this used to run
    // unguarded, so any single building whose data tripped up
    // estimateBuildingDimensions()/seedFloors() (e.g. a footprint with
    // too few points, or a genuinely 0-area shape) threw an uncaught
    // exception that aborted this entire effect BEFORE it ever reached
    // animate() at the bottom -- meaning renderer.render() was never
    // called even once, so the canvas showed nothing but its own
    // background color (looking totally blank) instead of just that one
    // building failing to appear. Catching it here means the rest of the
    // scene (grid, other buildings, lights) still renders, and the
    // specific failure is visible in the console instead of silently
    // blanking the whole view.
    try {
    if (parcel) {
      const parcelPts = shiftPts(safeParse(parcel.footprint_geojson)) || [[0, 0], [30, 0], [30, 22.5], [0, 22.5]]

      if (layers.parcel && mode === '2d') {
        addExtrusion(parcelPts, 0, 0.15, 0xC9C2AE, 0.55, { type: 'parcel', id: parcel.id, selectable: true })
      }

      if (mode === '3d') {
        if (layers.parcel) {
          // Was a near-black plate (0x1A2E28 @ 0.6 opacity) -- lightened
          // and made more transparent so it reads as a faint ground
          // reference under the building instead of a dark slab that
          // visually competes with the building sitting on it.
          addExtrusion(parcelPts, -0.1, 0.05, 0xC9C2AE, 0.25, { type: 'parcel', id: parcel.id, selectable: false })
        }

        let detailedExtent = 0
        parcel.buildings?.forEach((b) => {
          try {
          const bPts = shiftPts(safeParse(b.footprint_geojson)) || parcelPts
          const isFocused = !focusedBuildingId || focusedBuildingId === b.id
          const buildingHeight = b.height_m || (b.num_floors ? b.num_floors * 3 : UNSURVEYED_HEIGHT_M)

          if (!isFocused) {
            // Non-focused building on a multi-building parcel: cheap
            // footprint-only outline (1 mesh), clickable to bring it into
            // focus -- keeps a 20-building parcel from rendering every
            // building's full floor/unit detail simultaneously. Uses the
            // REAL building height (not a fixed placeholder slab) so it
            // still reads as a true volume, just without floor/unit
            // subdivision.
            addExtrusion(bPts, 0, buildingHeight, 0x4A6B5D, 0.32, { type: 'building', id: b.id, selectable: true })
            return
          }

          // Sorted so the explode offset increases monotonically with real
          // floor order regardless of the order floors arrived from the API.
          // Falls back to seedFloors() when this building has no real Floor
          // rows yet, so an unsurveyed building still renders as a proper
          // stack of floors (with estimated units) instead of one flat shell.
          const sortedFloors = [...(b.floors?.length ? b.floors : seedFloors(b, bPts))].sort((a, c) => a.floor_number - c.floor_number)

          // ---- detailed facade model (BHU-3D reference look) ---------------------
          // "Active" floor = the isolated floor, or the floor that owns the
          // selected unit. It is drawn cyan/see-through with everything above it
          // lifted clear (see ACTIVE_LIFT) and gets a floating F06 / F06-U12 tag.
          let activeFloor = isolatedFloorId ? (sortedFloors.find((f) => f.id === isolatedFloorId) || null) : null
          if (!activeFloor && selectedId) activeFloor = sortedFloors.find((f) => f.units?.some((u) => u.id === selectedId)) || null

          // Display offset per floor: exploded spacing, plus the lift above the active floor.
          const offsetFor = (f, floorIdx, detailed) =>
            (exploded ? floorIdx * EXPLODE_GAP : 0) +
            (detailed && activeFloor && !exploded && f.floor_number > activeFloor.floor_number ? ACTIVE_LIFT : 0)

          let detailedOK = false
          if (buildingStyle === 'detailed' && layers.buildings) {
            try {
              const ring = footprintToRing(bPts)
              const planFloors = []
              sortedFloors.forEach((f, floorIdx) => {
                if (!(f.z_max > 0.01)) return // basements keep the plain translucent slab
                const off = offsetFor(f, floorIdx, true)
                const kind = floorKind(f)
                planFloors.push({
                  y0: Math.max(f.z_min, 0) + off, y1: f.z_max + off, kind,
                  accent: kind === 'residential' && f.floor_number % 3 === 0, // cosmetic banding only
                  active: !!activeFloor && activeFloor.id === f.id,
                })
              })
              // Fewer details when a parcel holds many buildings, to keep the vertex count sane.
              const nBuildings = parcel.buildings?.length || 1
              const detail = nBuildings > 12 ? 0 : nBuildings > 5 ? 1 : 2
              const model = createDetailedBuilding({ ring, floors: planFloors, detail })
              scene.add(model.group)
              detailedOK = true
              detailedExtent = Math.max(detailedExtent, model.meta.extent)

              // Cosmetic extras -- failure here must not undo the facade itself.
              try {
                const [mcx, mcz] = model.meta.centroid
                const shadowSize = model.meta.extent * 1.7
                const shadow = createContactShadow(shadowSize, shadowSize, isDark ? 0.7 : 0.35)
                shadow.position.set(mcx, 0.07, mcz) // just above the translucent parcel plate (top at 0.05) so it isn't depth-culled
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
              // Odd footprint (self-intersecting, ~zero area, ...): fall back to the plain volumes below.
              console.warn(`3D view: detailed facade unavailable for building ${b.id}, using plain volumes`, err)
              detailedOK = false
            }
          }

          // In exploded view the continuous outer shell would hide the very
          // gaps the explode is meant to show, so it's skipped in that mode
          // (and it is replaced entirely by the facade model when that is on).
          if (layers.buildings && !exploded && !detailedOK) {
            // Was a near-black, nearly-invisible plate (0x1A2E28 @ 0.06
            // opacity) -- against the scene's equally dark background this
            // made every building with no floors yet (e.g. straight off a
            // bulk OSM import, before any floor/unit detail exists) render
            // as basically nothing but the ground plate. Lightened to a
            // visible translucent "glass volume" so the real footprint +
            // height is always visible even with zero floors.
            const shellMesh = addExtrusion(bPts, 0, buildingHeight, 0x8FBFAE, 0.22, { type: 'building', id: b.id, selectable: false })

            // If this building has a real uploaded facade/drone photo,
            // texture-map it onto the shell as a visual reference for what
            // the real building looks like -- this is DECORATION on top of
            // the modeled footprint+height (both already real, verified
            // values), never a 3D reconstruction derived from the photo
            // itself. Loaded async; the shell starts (and silently stays,
            // on any failure) as the existing near-invisible flat material
            // above, so a missing/unreachable image never breaks or
            // changes rendering for buildings without a photo.
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
                () => { /* image not reachable -- keep the existing flat shell as-is */ },
              )
            }
          }

          const useFullDetail = b.num_floors <= FLOOR_DETAIL_THRESHOLD || isolatedFloorId

          // Draws one floor's unit prisms -- shared by the plain and detailed paths.
          const drawFloorUnits = (f, zMin, zMax) => {
            f.units?.forEach((u) => {
              const uPts = shiftPts(safeParse(u.footprint_geojson))
              if (!uPts) return
              const color = TYPE_COLORS[u.parcel_type] || TYPE_COLORS.default
              const isSelected = u.id === selectedId
              // Seeded (unsurveyed-estimate) units have no verification_status
              // at all -- shown at the same dim opacity as a real unfinished
              // unit rather than defaulting to "approved" brightness for
              // something that was never actually reviewed.
              const statusOpacity = u.verification_status === 'approved' ? 0.55 : 0.3
              addExtrusion(
                uPts, zMin, zMax,
                isSelected ? 0xC9A24E : color,
                isSelected ? 0.85 : statusOpacity,
                {
                  type: 'unit', id: u.id, selectable: true,
                  // Same reasoning as the floor case above: seed-unit-*
                  // ids don't exist server-side, so the estimated unit
                  // object itself is bundled here for the panel to read
                  // directly instead of calling GET /units/{id} (which
                  // would 404). zMin/zMax included too -- a seeded unit
                  // has no z_min/z_max of its own (seedFloors() only sets
                  // those on the floor), it inherits its floor's range.
                  // zMin/zMax here are f.z_min/f.z_max WITH the exploded-view
                  // display offset added (see explodeOffset above) -- not
                  // the real geometry. The panel needs the real (offset-
                  // free) range, so f.z_min/f.z_max are used instead.
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

            // Detailed facade: the facade is one merged mesh, so floors are
            // picked through invisible proxies. The active floor instead exposes
            // its unit prisms (they sit inside the cyan see-through slab).
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
                // Exploded view reads as one translucent slab per floor
                // (matching the reference "exploded floors" look) rather
                // than individual unit footprints stacked with no gaps.
                const dimmed = isolatedFloorId && !isIsolatedFloor
                addExtrusion(bPts, zMin, zMax, 0x3E8E7E, dimmed ? 0.08 : 0.32, {
                  type: 'floor', id: f.id, selectable: true,
                  // Seeded (estimated, unsurveyed) floors are now clickable
                  // too -- they used to be excluded from selectableMeshes
                  // entirely, which for an unsurveyed building (the common
                  // case right off a bulk import) meant NOTHING on the whole
                  // model responded to a click, floor or otherwise. The
                  // panel needs the full synthetic floor object bundled in
                  // here (not just an id) because seed-floor-* ids don't
                  // exist server-side -- Viewer3D can't look them up via
                  // parcel.buildings[].floors[] or an API call the way it
                  // does for a real floor.
                  seeded: f.seeded, floorData: f.seeded ? f : undefined,
                  buildingId: b.id, buildingCode: b.building_code, buildingFootprintGeojson: b.footprint_geojson,
                })
              }
              drawFloorUnits(f, zMin, zMax)
            } else if (layers.buildings || layers.units) {
              // Simplified LOD: one solid slab per floor (its REAL full
              // height, not a thin sliver) instead of every unit's
              // individual walls -- this is what fixes the clutter on tall
              // buildings while still showing the true volume. A thin
              // sliver here was the main cause of buildings "looking
              // thin/flat" from the side -- every floor above ground
              // rendered as a wafer regardless of its actual height.
              // Dimmer when another floor is isolated, so the isolated
              // floor visually pops.
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
          // North marker on the -Z side of the model (footprint +y = north = world -z).
          const north = createNorthMarker(Math.max(3, detailedExtent * 0.16), isDark ? '#22D3EE' : '#2C5B53')
          north.position.set(0, Math.max(3, detailedExtent * 0.08), -(detailedExtent * 0.85 + 4))
          scene.add(north)
        }

        // ---- Underground + air-right layers -------------------------------------------------
        // Two sources, both real: (1) structures found in open data around this parcel (metro tunnels,
        // basements, buried cables/pipes, elevated metro, flyovers, power-line corridors ...), served by
        // GET /api/infra/parcel/{id} in this parcel's own frame -- the same store the map layers draw,
        // including ones running NEXT to the parcel, not only ones crossing it; (2) rows an officer, a
        // GPR import or the AI pipeline recorded on the parcel. The parcel-level rows the open-data
        // link step wrote itself (source osm_auto) are clipped copies of (1), so they are skipped when
        // (1) is present instead of being drawn twice.
        const infraFeatures = parcel.infra?.available ? (parcel.infra.features || []) : []
        const infraUg = infraFeatures.filter((f) => f.kind === 'underground')
        const infraAir = infraFeatures.filter((f) => f.kind === 'air')
        const hasInfra = infraFeatures.length > 0
        const labelW = Math.min(46, Math.max(9, (initialFrame.extent ?? 30) * 0.32))
        let labelBudget = 8    // nearest / on-parcel features first (the feed is sorted that way)
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
            // faint ground-column under the parcel + a depth ruler, like the reference demo
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
            // depth_min_m/depth_max_m are metres BELOW the ground surface
            // (0 = surface, larger = deeper). Math.abs() also tolerates any
            // older record still stored as negative depth from before this
            // convention was made explicit. Negating places the asset at a
            // genuinely negative Y -- i.e. underground, below the y=0 floor
            // slab -- instead of floating up near/above the building, which
            // is what happened when the raw (positive) depth was passed
            // straight through as a world-space Y coordinate.
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
              // ribbon from the surface down to the top of the structure + a line at its centre depth
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
              // protected envelope (underside -> top), outlined
              const mesh = addExtrusion(pts, zMin, zMax, hex, picked ? 0.6 : 0.26, userData)
              if (mesh) scene.add(makeGlowEdges(mesh, picked ? 0xFFFFFF : hex, 0.9))
              // the physical deck itself, where a deck top is known
              if (f.deck_top_m != null && f.deck_top_m > zMin + 0.1) {
                addExtrusion(pts, zMin, Math.min(f.deck_top_m, zMax), hex, 0.7, { type: 'infra', id: f.id, selectable: false })
              }
              // footprint tint on the ground so the corridor's plan position reads from above
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
      // renderer.dispose() alone frees this renderer's GPU-side resources
      // but does NOT reliably release the WebGL context handle itself --
      // forceContextLoss() is the explicit call for that. This effect
      // tears down and rebuilds the whole scene on every selection change
      // (selectedId/isolatedFloorId/focusedBuildingId are all deps below),
      // so without this, ordinary clicking around a building/floor/unit
      // was leaking one real WebGL context per click -- quickly hitting
      // the browser's hard per-page context cap (Chrome: 16) and showing
      // as "Too many active WebGL contexts. Oldest context will be lost."
      // in the console, with the 3D view sometimes going blank once it did.
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

  // Updates the section-clip plane in place on the existing renderer --
  // deliberately NOT in the big effect above, so dragging the slice slider
  // doesn't tear down and rebuild the entire scene on every frame.
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