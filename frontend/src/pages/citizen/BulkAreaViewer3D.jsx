import { useEffect, useRef, useState } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import api from '../../api/client'
import { useAuth } from '../../context/AuthContext.jsx'
import { Loader2, X, ExternalLink, AlertTriangle, Building2, Scissors, Pencil, Save } from 'lucide-react'

function hashSeed(str) {
  let h = 0
  const s = String(str)
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}
function seededInt(seed, min, max) {
  return min + (hashSeed(seed) % (max - min + 1))
}
const PLACEHOLDER_NAME_POOL = ['Residential Block', 'Commercial Complex', 'Office Structure', 'Mixed-Use Building', 'Community Building', 'Apartment Block']
function seededName(building) {
  const shortId = String(building.id).slice(0, 6)
  const label = PLACEHOLDER_NAME_POOL[seededInt(building.id + 'name', 0, PLACEHOLDER_NAME_POOL.length - 1)]
  return `${label} ${shortId}`
}
function seededHeightM(building) {
  return seededInt(building.id + 'height', 6, 42)
}
function seededFloorCount(heightM) {
  return Math.max(1, Math.round(heightM / 3.2))
}
function seededFloors(building, parcel, floorCount) {
  const floors = []
  for (let i = 0; i < floorCount; i++) {
    const unitCount = seededInt(`${building.id}-floor${i}-units`, 1, 4)
    const units = []
    for (let u = 0; u < unitCount; u++) {
      units.push({
        id: `ph-${building.id}-${i}-${u}`,
        unit_code: `U${u + 1}`,
        area_sqm: seededInt(`${building.id}-${i}-${u}-area`, 25, 120),
        ulpin_3d: `PH-${parcel.ulpin_2d || '?'}-${building.building_code || '?'}-F${i}-U${u + 1}`,
      })
    }
    floors.push({
      id: `ph-${building.id}-${i}`,
      floor_number: i,
      z_min: (i * 3.2).toFixed(1),
      z_max: ((i + 1) * 3.2).toFixed(1),
      floor_code: `F${i}`,
      units,
      __placeholder: true,
    })
  }
  return floors
}

export default function BulkAreaViewer3D() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const jobId = params.get('jobId')
  const { user } = useAuth()
  const isEditor = ['surveyor', 'verifier', 'admin'].includes(user?.role)

  const [status, setStatus] = useState('loading')
  const [parcels, setParcels] = useState([])
  const [roads, setRoads] = useState([])
  const [selected, setSelected] = useState(null)
  const [cutSelected, setCutSelected] = useState(false)
  const [editingInfo, setEditingInfo] = useState(false)
  const [editName, setEditName] = useState('')
  const [editAddress, setEditAddress] = useState('')
  const [savingInfo, setSavingInfo] = useState(false)
  const [saveInfoError, setSaveInfoError] = useState(null)
  const mountRef = useRef(null)
  const sceneRef = useRef({})

  const [roadsError, setRoadsError] = useState(null)
  useEffect(() => {
    if (!jobId) { setStatus('not_found'); return }
    let cancelled = false
    async function load() {
      try {
        const { data: job } = await api.get(`/bulk-import/jobs/${jobId}`)
        if (cancelled) return
        if (job.status !== 'done') { setStatus('not_done'); return }
        if (!job.parcel_ids || job.parcel_ids.length === 0) { setStatus('error'); return }
        const results = await Promise.all(job.parcel_ids.map((id) => api.get(`/parcels/${id}`)))
        if (cancelled) return
        setParcels(results.map((r) => r.data))
        setStatus('ready')
        api.get(`/bulk-import/jobs/${jobId}/roads`)
          .then(({ data }) => { if (!cancelled) { setRoads(data.roads || []); setRoadsError(null) } })
          .catch((err) => {
            if (cancelled) return
            setRoads([])
            setRoadsError(err.response?.data?.detail || err.message || 'Could not fetch road data.')
          })
      } catch {
        if (!cancelled) setStatus('error')
      }
    }
    load()
    return () => { cancelled = true }
  }, [jobId])

  useEffect(() => {
    if (status !== 'ready' || !mountRef.current) return
    const mount = mountRef.current
    const width = mount.clientWidth, height = mount.clientHeight

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0xeef1f5)

    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 5000)
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.localClippingEnabled = true
    mount.innerHTML = ''
    mount.appendChild(renderer.domElement)

    scene.add(new THREE.AmbientLight(0xffffff, 0.7))
    const sun = new THREE.DirectionalLight(0xffffff, 0.8)
    sun.position.set(80, 120, 60)
    scene.add(sun)

    roads.forEach((road) => {
      if (!road.points || road.points.length < 2) return
      const points = road.points.map(([x, y]) => new THREE.Vector3(x, 0.05, y))
      const lineGeometry = new THREE.BufferGeometry().setFromPoints(points)
      const lineMaterial = new THREE.LineBasicMaterial({ color: 0x3ecf8e })
      scene.add(new THREE.Line(lineGeometry, lineMaterial))
    })

    const meshes = []
    const meshByBuildingId = {}
    let totalBuildings = 0

    const parsed = []
    parcels.forEach((parcel) => {
      (parcel.buildings || []).forEach((building) => {
        let footprint
        try { footprint = JSON.parse(building.footprint_geojson || '[]') } catch { footprint = [] }
        if (!footprint || footprint.length < 3) return
        const heightM = building.height_m || (building.num_floors ? building.num_floors * 3.2 : 6)
        const cx = footprint.reduce((s, p) => s + p[0], 0) / footprint.length
        const cz = footprint.reduce((s, p) => s + p[1], 0) / footprint.length
        parsed.push({ parcel, building, footprint, heightM, cx, cz })
      })
    })

    function medianNearestNeighborDist(points) {
      if (points.length < 2) return 50
      const dists = points.map((p, i) => {
        let best = Infinity
        points.forEach((q, j) => {
          if (i === j) return
          const dx = p.cx - q.cx, dz = p.cz - q.cz
          const d = Math.sqrt(dx * dx + dz * dz)
          if (d < best) best = d
        })
        return best
      })
      dists.sort((a, b) => a - b)
      return dists[Math.floor(dists.length / 2)] || 50
    }
    function largestCluster(points, linkDistance) {
      const n = points.length
      const parent = Array.from({ length: n }, (_, i) => i)
      function find(a) { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a] } return a }
      function union(a, b) { const ra = find(a), rb = find(b); if (ra !== rb) parent[ra] = rb }
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const dx = points[i].cx - points[j].cx, dz = points[i].cz - points[j].cz
          if (Math.sqrt(dx * dx + dz * dz) <= linkDistance) union(i, j)
        }
      }
      const groups = {}
      for (let i = 0; i < n; i++) { const r = find(i); (groups[r] ||= []).push(i) }
      let best = []
      Object.values(groups).forEach((g) => { if (g.length > best.length) best = g })
      return new Set(best)
    }
    const linkDistance = medianNearestNeighborDist(parsed) * 4
    const coreIdx = largestCluster(parsed, linkDistance)
    const core = parsed.filter((_, i) => coreIdx.has(i))
    const framing = core.length >= Math.max(3, parsed.length * 0.3) ? core : parsed
    const framingIds = new Set(framing.map((p) => p.building.id))
    const outlierCount = parsed.length - framing.length

    const allXs = [], allZs = []
    framing.forEach((p) => p.footprint.forEach(([x, y]) => { allXs.push(x); allZs.push(y) }))
    const minX = Math.min(...allXs), maxX = Math.max(...allXs)
    const minZ = Math.min(...allZs), maxZ = Math.max(...allZs)

    let minH = Infinity, maxH = -Infinity
    parsed.forEach((p) => { minH = Math.min(minH, p.heightM); maxH = Math.max(maxH, p.heightM) })
    if (!isFinite(minH)) { minH = 0; maxH = 1 }
    if (maxH - minH < 0.01) { maxH = minH + 1 }

    const hasHeightVariance = (maxH - minH) >= 2

    function colorForHeight(h, buildingIndex) {
      if (!hasHeightVariance) {
        const hue = ((buildingIndex * 137.508) % 360) / 360
        const color = new THREE.Color()
        color.setHSL(hue, 0.6, 0.58)
        return color
      }
      const t = Math.max(0, Math.min(1, (h - minH) / (maxH - minH)))
      const hue = 0.62 - 0.62 * t
      const color = new THREE.Color()
      color.setHSL(hue, 0.55, 0.52)
      return color
    }

    const BODY_PALETTE = [0xf3f4f6, 0xe7e9ed, 0xd6dae1, 0xc7ccd4]
    const EDGE_COLOR = 0x30343b
    const SELECTED_COLOR = 0x2dd4bf

    const FOOTPRINT_INSET = 0.82
    function insetFootprint(footprint, cx, cz) {
      return footprint.map(([x, y]) => [
        cx + (x - cx) * FOOTPRINT_INSET,
        cz + (y - cz) * FOOTPRINT_INSET,
      ])
    }

    function paletteIndex(id) {
      const s = String(id)
      let h = 0
      for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
      return h % BODY_PALETTE.length
    }

    const VERTICAL_EXAGGERATION = 3.2
    const coreMeshes = []
    parsed.forEach(({ parcel, building, footprint, heightM, cx, cz }) => {
      const inset = insetFootprint(footprint, cx, cz)
      const shape = new THREE.Shape()
      inset.forEach(([x, y], i) => (i === 0 ? shape.moveTo(x, y) : shape.lineTo(x, y)))

      const visualHeight = heightM * VERTICAL_EXAGGERATION
      const geometry = new THREE.ExtrudeGeometry(shape, { depth: visualHeight, bevelEnabled: false })
      geometry.rotateX(-Math.PI / 2)

      const baseColor = new THREE.Color(
        building.consistency_flag ? 0xf5b95c : BODY_PALETTE[paletteIndex(building.id)]
      )
      const material = new THREE.MeshStandardMaterial({ color: baseColor, metalness: 0.05, roughness: 0.8, side: THREE.DoubleSide })
      const mesh = new THREE.Mesh(geometry, material)
      mesh.geometry.computeBoundingBox()
      mesh.userData = { parcel, building, baseColor }
      meshByBuildingId[building.id] = mesh
      scene.add(mesh)
      meshes.push(mesh)
      if (framingIds.has(building.id)) coreMeshes.push(mesh)
      totalBuildings += 1

      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({ color: EDGE_COLOR }),
      )
      scene.add(edges)
    })

    const fitBox = new THREE.Box3()
    const meshesForFit = coreMeshes.length > 0 ? coreMeshes : meshes
    meshesForFit.forEach((m) => fitBox.expandByObject(m))
    const fitSphere = new THREE.Sphere()
    fitBox.getBoundingSphere(fitSphere)

    const vFov = (camera.fov * Math.PI) / 180
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect)
    const effectiveFov = Math.min(vFov, hFov)
    const distance = (fitSphere.radius / Math.sin(effectiveFov / 2)) * 0.72
    const dir = new THREE.Vector3(1, 0.65, 1).normalize()
    camera.position.set(
      fitSphere.center.x + dir.x * distance,
      fitSphere.center.y + dir.y * distance,
      fitSphere.center.z + dir.z * distance,
    )

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.target.copy(fitSphere.center)
    controls.update()

    const raycaster = new THREE.Raycaster()
    const mousePos = new THREE.Vector2()
    function handleClick(e) {
      const rect = renderer.domElement.getBoundingClientRect()
      mousePos.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      mousePos.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(mousePos, camera)
      const hits = raycaster.intersectObjects(meshes)
      setSelected(hits.length > 0 ? hits[0].object.userData : null)
    }
    renderer.domElement.addEventListener('click', handleClick)

    let frameId
    function animate() {
      controls.update()
      renderer.render(scene, camera)
      frameId = requestAnimationFrame(animate)
    }
    animate()

    sceneRef.current = { totalBuildings, parcelCount: parcels.length, meshByBuildingId, minH, maxH, hasHeightVariance, outlierCount }

    function handleResize() {
      const w = mount.clientWidth, h = mount.clientHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', handleResize)

    return () => {
      cancelAnimationFrame(frameId)
      window.removeEventListener('resize', handleResize)
      renderer.domElement.removeEventListener('click', handleClick)
      controls.dispose()
      scene.traverse((obj) => {
        obj.geometry?.dispose()
        const materials = Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : []
        materials.forEach((m) => { m.map?.dispose(); m.dispose() })
      })
      renderer.dispose()
      renderer.forceContextLoss()
      mount.innerHTML = ''
    }
  }, [status, parcels, roads])

  const cutMeshRef = useRef(null)
  useEffect(() => {
    if (cutMeshRef.current) {
      cutMeshRef.current.material.clippingPlanes = []
      cutMeshRef.current = null
    }
    setCutSelected(false)
    setEditingInfo(false)
    setSaveInfoError(null)
  }, [selected?.building?.id])

  const highlightedMeshRef = useRef(null)
  useEffect(() => {
    if (highlightedMeshRef.current) {
      highlightedMeshRef.current.material.color.copy(highlightedMeshRef.current.userData.baseColor)
      highlightedMeshRef.current = null
    }
    const mesh = selected && sceneRef.current.meshByBuildingId?.[selected.building.id]
    if (mesh) {
      mesh.material.color.set(0x2dd4bf)
      highlightedMeshRef.current = mesh
    }
  }, [selected?.building?.id])

  function startEditInfo() {
    if (!selected) return
    setEditName(selected.building.name || '')
    setEditAddress(selected.parcel.address || '')
    setSaveInfoError(null)
    setEditingInfo(true)
  }

  async function saveInfoEdit() {
    if (!selected) return
    const { building, parcel } = selected
    setSavingInfo(true)
    setSaveInfoError(null)
    try {
      const tasks = []
      const nameChanged = editName.trim() !== (building.name || '')
      const addressChanged = editAddress.trim() !== (parcel.address || '')
      if (nameChanged) tasks.push(api.patch(`/buildings/${building.id}`, { name: editName.trim() || null }))
      if (addressChanged) tasks.push(api.patch(`/parcels/${parcel.id}`, { address: editAddress.trim() || null }))
      await Promise.all(tasks)

      const updatedBuilding = nameChanged ? { ...building, name: editName.trim() || null } : building
      const updatedParcel = addressChanged ? { ...parcel, address: editAddress.trim() || null } : parcel

      setParcels((prev) => prev.map((p) => {
        if (p.id !== parcel.id) return p
        return { ...updatedParcel, buildings: (p.buildings || []).map((b) => (b.id === building.id ? updatedBuilding : b)) }
      }))
      setSelected({ building: updatedBuilding, parcel: updatedParcel })
      setEditingInfo(false)
    } catch (err) {
      setSaveInfoError(err.response?.data?.detail || 'Could not save changes.')
    } finally {
      setSavingInfo(false)
    }
  }

  function handleCutBuilding() {
    const mesh = selected && sceneRef.current.meshByBuildingId?.[selected.building.id]
    if (!mesh) return

    const nextCut = !cutSelected
    setCutSelected(nextCut)

    if (!nextCut) {
      mesh.material.clippingPlanes = []
      cutMeshRef.current = null
      return
    }
    const box = mesh.geometry.boundingBox
    const centerX = (box.min.x + box.max.x) / 2
    const plane = new THREE.Plane(new THREE.Vector3(1, 0, 0), -centerX)
    mesh.material.clippingPlanes = [plane]
    cutMeshRef.current = mesh
  }

  if (status === 'loading') {
    return <div className="flex justify-center items-center h-full py-24"><Loader2 className="animate-spin text-brand-400" size={26} /></div>
  }
  if (status === 'not_found') {
    return <div className="p-8 text-sm text-slate-500">No job specified -- open this page from the bulk import panel's "Next Step" button.</div>
  }
  if (status === 'not_done') {
    return <div className="p-8 text-sm text-slate-500">This import hasn't finished yet -- go back and wait for it to complete.</div>
  }
  if (status === 'error') {
    return <div className="p-8 text-sm text-rose-400">Could not load this job's buildings.</div>
  }

  return (
    <div className="relative w-full h-[calc(100vh-4rem)]">
      <div ref={mountRef} className="w-full h-full" />

      <div className="absolute bottom-4 left-4 card px-4 py-3 text-xs text-slate-500 space-y-0.5">
        <div className="flex items-center gap-1.5 text-slate-300 font-medium"><Building2 size={13} /> {sceneRef.current.totalBuildings ?? 0} buildings</div>
        <div>{sceneRef.current.parcelCount ?? parcels.length} parcels</div>
        {sceneRef.current.outlierCount > 0 && (
          <div className="text-[10px] text-slate-500 max-w-[9rem]">
            {sceneRef.current.outlierCount} building{sceneRef.current.outlierCount === 1 ? '' : 's'} sit far outside this cluster (likely detection noise) and aren't in view -- zoom out to find them.
          </div>
        )}
        {roadsError && (
          <div className="text-[10px] text-rose-400 max-w-[10rem]">
            Roads didn't load: {roadsError}
          </div>
        )}
        {sceneRef.current.minH != null && sceneRef.current.hasHeightVariance && (
          <div className="pt-2 mt-2 border-t border-white/5 text-[10px] text-slate-500">
            Height range: {sceneRef.current.minH.toFixed(0)}m - {sceneRef.current.maxH.toFixed(0)}m
          </div>
        )}
      </div>

      {selected && (
        <div className="absolute top-4 right-4 w-80 card p-5 max-h-[85vh] overflow-y-auto">
          {(() => {
            const b = selected.building
            const p = selected.parcel
            const hasRealName = !!(b.name)
            const displayName = hasRealName ? b.name : seededName(b)
            const hasRealHeight = b.height_m != null
            const displayHeight = hasRealHeight ? b.height_m : seededHeightM(b)
            const hasRealFloorCount = b.num_floors != null && b.num_floors > 0
            const displayFloorCount = hasRealFloorCount ? b.num_floors : seededFloorCount(displayHeight)
            const hasRealFloorRecords = b.floors?.length > 0
            const displayFloors = hasRealFloorRecords ? b.floors : seededFloors(b, p, displayFloorCount)
            return (
              <>
                {editingInfo ? (
                  <div className="mb-3 space-y-2">
                    <input
                      autoFocus
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      placeholder="Building name"
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-brand-500/50"
                    />
                    <input
                      value={editAddress}
                      onChange={(e) => setEditAddress(e.target.value)}
                      placeholder="Address"
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-brand-500/50"
                    />
                    {saveInfoError && <div className="text-[10px] text-rose-400">{saveInfoError}</div>}
                    <div className="flex gap-2">
                      <button
                        onClick={saveInfoEdit}
                        disabled={savingInfo}
                        className="btn-primary flex-1 !py-1.5 text-xs justify-center flex items-center gap-1.5"
                      >
                        {savingInfo ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Save
                      </button>
                      <button
                        onClick={() => setEditingInfo(false)}
                        disabled={savingInfo}
                        className="btn-secondary flex-1 !py-1.5 text-xs justify-center"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-start justify-between mb-1 gap-2">
                    <h3 className="font-display text-sm font-bold text-white break-words pr-2">
                      {displayName}
                    </h3>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {isEditor && (
                        <button onClick={startEditInfo} className="text-slate-500 hover:text-white" aria-label="Edit building info">
                          <Pencil size={14} />
                        </button>
                      )}
                      <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-white"><X size={16} /></button>
                    </div>
                  </div>
                )}
                {!editingInfo && !hasRealName && <div className="text-[10px] text-amber-400/80 mb-3">No name on record -- showing a placeholder</div>}

                {b.consistency_flag && (
                  <div className="flex items-start gap-1.5 text-[11px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-2.5 py-2 mb-3">
                    <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" /> {b.consistency_note}
                  </div>
                )}

                <div className="space-y-2 text-xs">
                  <Row label="Height" value={`${displayHeight} m${hasRealHeight ? '' : ' (placeholder)'}`} />
                  <Row label="Floors" value={`${displayFloorCount}${hasRealFloorCount ? '' : ' (placeholder)'}`} />
                  <Row label="Footprint (bounding box)" value={footprintDims(b.footprint_geojson)} />
                  {p.address ? (
                    <Row label="Address" value={p.address} />
                  ) : b.ms_confidence != null ? (
                    <>
                      <Row label="Address" value="Not on record" />
                      <Row label="Detection confidence" value={`${Math.round(b.ms_confidence * 100)}%`} />
                    </>
                  ) : (
                    <Row label="Address" value="Not on record" />
                  )}
                  {b.osm_id && <Row label="OSM ID" value={b.osm_id} mono />}
                  <Row label="Parcel ID" value={p.id} mono />
                  <Row label="Base ULPIN" value={p.ulpin_2d} mono />
                </div>

                <div className="mt-3 pt-3 border-t border-white/5">
                  <div className="text-[11px] text-slate-500 mb-1.5">
                    Floors &amp; Units {!hasRealFloorRecords && <span className="text-amber-400/80">(placeholder -- not in database)</span>}
                  </div>
                  <div className="space-y-2 max-h-48 overflow-y-auto">
                    {displayFloors.map((f) => (
                      <div key={f.id}>
                        <div className="flex justify-between text-[11px]">
                          <span className="text-slate-500">Floor {f.floor_number} ({f.z_min}m\u2013{f.z_max}m)</span>
                          <span className="text-slate-300 font-mono">
                            {f.__placeholder ? f.floor_code : `${p.ulpin_2d}-${b.building_code}-${f.floor_code}`}
                          </span>
                        </div>
                        {f.units?.length > 0 ? (
                          <div className="pl-3 mt-1 space-y-0.5">
                            {f.units.map((u) => (
                              <div key={u.id} className="flex justify-between text-[10px] text-slate-500">
                                <span>Unit {u.unit_code}{u.area_sqm ? ` \u00b7 ${Math.round(u.area_sqm)} sqm` : ''}</span>
                                <span className="font-mono">{u.ulpin_3d}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="pl-3 mt-1 text-[10px] text-slate-600">No units delineated yet</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <button
                  onClick={handleCutBuilding}
                  className={`w-full !py-2 text-xs mt-4 justify-center flex items-center gap-1.5 rounded-lg font-medium transition-colors ${
                    cutSelected ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' : 'bg-rose-500/10 text-rose-400 hover:bg-rose-500/15 border border-rose-500/20'
                  }`}
                >
                  <Scissors size={13} /> {cutSelected ? 'Restore Building' : 'Cut Building'}
                </button>

                <button
                  onClick={() => navigate(`/viewer?focus=parcel:${p.id}&building=${b.id}`)}
                  className="btn-secondary w-full !py-2 text-xs mt-2 justify-center"
                >
                  Open Full Inspector <ExternalLink size={12} />
                </button>
              </>
            )
          })()}
        </div>
      )}
    </div>
  )
}

function footprintDims(footprintGeojson) {
  try {
    const points = JSON.parse(footprintGeojson || '[]')
    if (!points || points.length < 3) return null
    const xs = points.map((p) => p[0]), ys = points.map((p) => p[1])
    const length = Math.max(...xs) - Math.min(...xs)
    const width = Math.max(...ys) - Math.min(...ys)
    return `${length.toFixed(1)}m \u00d7 ${width.toFixed(1)}m`
  } catch {
    return null
  }
}

function Row({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-white/5">
      <span className="text-slate-500">{label}</span>
      <span className={`text-slate-200 text-right break-all ${mono ? 'font-mono text-[11px]' : ''}`}>{value ?? '\u2014'}</span>
    </div>
  )
}
