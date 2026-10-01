import { useEffect, useState, useRef } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import api from '../../api/client'
import ThreeScene from '../../components/ThreeScene.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import ParcelInfoCard from '../../components/ParcelInfoCard.jsx'
import BeforeAfterAIPanel from '../../components/BeforeAfterAIPanel.jsx'
import InfraLegend from '../../components/InfraLegend.jsx'
import { rangeText, infraStyle } from '../../components/building3d/infra3d.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { polygonArea, safeParseGeojson } from '../../utils/geometry.js'
import { estimateBuildingDimensions } from '../../utils/buildingEstimate.js'
import {
  Layers, Building2, Cable, Plane, Map as MapIcon, Boxes, X,
  RotateCcw, Loader2, FileDown, Flag, ChevronRight, Maximize2,
  ChevronUp, ChevronDown, ChevronLeft, Triangle, Box, Search, Eye, EyeOff,
  CheckCircle2, AlertTriangle, ShieldAlert, GripVertical, Trash2, Pencil, Save, Moon, Sun,
  Info, Hash, Users, MapPin,
} from 'lucide-react'

const LAYER_DEFS = [
  { key: 'parcel', label: 'Parcels', icon: MapIcon },
  { key: 'buildings', label: 'Buildings', icon: Building2 },
  { key: 'units', label: 'Units', icon: Layers },
  { key: 'underground', label: 'Underground', icon: Cable },
  { key: 'airRights', label: 'Air-rights', icon: Plane },
]

// One look for every toolbar button: quiet by default, brass when active.
const toolBtn = (active) =>
  `flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
    active ? 'bg-brand-500 text-ink-950' : 'text-slate-300 hover:text-white hover:bg-white/5'
  }`

// Default landing parcel when nobody arrived via a ?focus= link (e.g. a bare /viewer visit). Picked
// by ULPIN rather than database id, since ulpin_2d is what's actually stable/recognizable across a
// reseed -- this is "56848459665529 (Karnataka Rural Infrastructure)". Only a *preferred* default:
// if this ULPIN isn't present in the current list (different environment, not yet seeded), the
// newest-parcel fallback below still applies, so the page never breaks over a missing record.
const DEFAULT_ULPIN = '56848459665529'

export default function Viewer3D() {
  const [allParcels, setAllParcels] = useState([])
  const [selectedParcelId, setSelectedParcelId] = useState(null)
  const [parcel, setParcel] = useState(null)
  const [loading, setLoading] = useState(true)
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [mode, setMode] = useState('3d')
  const [exploded, setExploded] = useState(false)
  // 'detailed' = window/balcony/roof-tank facade model (BHU-3D look); 'volumes' = the plain translucent floor slabs.
  const [buildingStyle, setBuildingStyle] = useState('detailed')
  const [sceneTheme, setSceneTheme] = useState('dark') // 'dark' (navy + cyan grid) | 'light' (original cream)
  // Underground + air-rights start ON: they are the point of the vertical-cadastre view, and with none
  // found the legend says so instead of leaving an unexplained empty scene.
  const [layers, setLayers] = useState({ parcel: true, buildings: true, units: true, underground: true, airRights: true })
  // Nearby underground / air-right structures come from their own request (an open-data scan can take
  // a while the first time an area is opened), so the building never waits for it.
  const [infraState, setInfraState] = useState('idle')   // idle | loading | done | error
  const [infraScan, setInfraScan] = useState(null)
  const [selected, setSelected] = useState(null)
  const [selectedDetail, setSelectedDetail] = useState(null)
  const [showAddressSearch, setShowAddressSearch] = useState(false)
  const [showPropertyInfo, setShowPropertyInfo] = useState(false)
  const [addressQuery, setAddressQuery] = useState('')
  const [addressResults, setAddressResults] = useState([])
  const [addressSearching, setAddressSearching] = useState(false)
  // Toolbar/Layers/parcel-info are overlays on top of the 3D canvas, but
  // on a small building or a narrow window they can end up covering most
  // of what little the scene shows -- these let the person collapse them
  // instead of them being permanently "static" fixtures on the screen.
  const [uiHidden, setUiHidden] = useState(false)
  const [layersCollapsed, setLayersCollapsed] = useState(false)
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const sceneRef = useRef(null)
  // "Open Full Inspector" from the bulk area view can ask to land directly
  // on one specific building (not just its parcel) via ?building=<id> --
  // applied once, the first time the matching parcel finishes loading, so
  // it doesn't keep overriding whatever the person has since clicked on.
  const focusBuildingId = params.get('building')
  const appliedBuildingFocusRef = useRef(false)

  // Load the list of every parcel that exists (newest first, per the
  // backend ordering) so nothing created after the page first loaded is
  // ever hidden behind a hardcoded "first parcel" assumption.
  useEffect(() => {
    async function loadParcelList() {
      setLoading(true)
      try {
        const { data } = await api.get('/parcels/summary', { params: { limit: 5000 } })
        setAllParcels(data)
        const focusParam = params.get('focus')
        // App-wide convention (see Search.jsx / GisMap.jsx): "type:id",
        // e.g. "parcel:abc123". This page only ever focuses a parcel, so
        // only the parcel: prefix is resolved here -- a unit/building/floor
        // focus falls back to the newest-parcel default below rather than
        // silently mis-selecting the wrong parcel.
        const focusId = focusParam?.startsWith('parcel:') ? focusParam.slice('parcel:'.length) : focusParam
        if (focusId) {
          // Trust the id directly rather than requiring it to appear in
          // `data` above -- GET /parcels defaults to the newest 100 rows
          // (see list_parcels()'s default limit in parcels_router.py), so
          // a parcel that legitimately exists but isn't in that newest-100
          // slice (e.g. one of 223 parcels from a bulk-import job, sitting
          // behind other more-recently-created parcels) used to fail this
          // membership check and silently fall back to some unrelated
          // parcel below -- landing "Open Full Inspector" on the wrong
          // building even though the link itself was correct. The detail
          // fetch below (GET /parcels/{id}) looks this id up directly by
          // primary key, uncapped, so membership in this list was never
          // actually required -- and if the id turns out not to exist at
          // all, that fetch's own catch block falls back to the newest
          // parcel instead.
          setSelectedParcelId(focusId)
        } else if (data.length > 0) {
          // Prefer the designated default parcel (DEFAULT_ULPIN) if it exists in this environment;
          // otherwise fall back to the most recently created one (data is newest-first).
          const byDefault = data.find((p) => p.ulpin_2d === DEFAULT_ULPIN)
          setSelectedParcelId(byDefault ? byDefault.id : data[0].id)
        }
      } finally {
        setLoading(false)
      }
    }
    loadParcelList()
  }, [])

  // Load full detail (buildings/floors/units + underground/air-rights) for
  // a given parcel id. Hoisted out of the effect below (rather than
  // defined inline inside it) so it can also be called again after a
  // building delete, to refresh the panel without a full page reload.
  async function loadParcelDetail(parcelId) {
    setLoading(true)
    try {
      const [parcelRes, underground, airRights, conflictsRes] = await Promise.all([
        api.get(`/parcels/${parcelId}`),
        // Filtered server-side now (parcel_id=) -- this used to fetch EVERY underground asset and
        // air-right corridor in the whole database on every single parcel view, then throw away
        // every row that wasn't this parcel's. Harmless with a handful of parcels; got slower with
        // every bulk import since.
        api.get('/underground-assets', { params: { parcel_id: parcelId } }),
        api.get('/air-rights', { params: { parcel_id: parcelId } }),
        // Topology/AI-vs-manual conflict checks (GET /api/review/conflicts)
        // require sign-in -- an anonymous citizen viewer gets a 401, which
        // is caught here instead of surfacing as an error, so the public
        // page still loads normally, just without conflict data.
        api.get('/review/conflicts').catch((err) => ({
          data: [], restricted: err?.response?.status === 401 || err?.response?.status === 403,
        })),
      ])
      const p = parcelRes.data
      p.undergroundAssets = underground.data.filter((a) => a.parcel_id === p.id)
      p.airRights = airRights.data.filter((a) => a.parcel_id === p.id)
      // Scope the (otherwise global) unresolved-conflicts list down to
      // just this parcel's buildings/units, so building/floor/unit
      // panels only ever show conflicts that are actually theirs.
      const buildingIds = new Set(p.buildings.map((b) => b.id))
      const unitIds = new Set(p.buildings.flatMap((b) => b.floors.flatMap((f) => f.units.map((u) => u.id))))
      p.conflicts = (conflictsRes.data || []).filter(
        (c) => (c.building_id && buildingIds.has(c.building_id)) || (c.unit_id && unitIds.has(c.unit_id)),
      )
      p.conflictsRestricted = !!conflictsRes.restricted
      setParcel(p)
      setSelectedDetail(null)
      setSelected(null)
      loadInfra(p.id)

      // A directly-focused parcel (see loadParcelList's focusId handling
      // above) may not be among the newest-100 GET /parcels returned, so
      // the selector dropdown wouldn't otherwise list it -- add it in so
      // the dropdown's displayed value actually matches what's on screen.
      setAllParcels((prev) => (prev.some((ap) => ap.id === p.id) ? prev : [{ id: p.id, ulpin: p.ulpin, address: p.address }, ...prev]))

      // Bulk-imported/newly-created parcels routinely have no `address`
      // column set at all -- but their real centroid_lat/lon is enough to
      // resolve a real street address via the same reverse-geocode the
      // ParcelInfoCard already uses for Village/Tehsil/District. Without
      // this, the parcel selector and building panels showed a bare
      // "No address"/"Not on record" even when a real address was one
      // lookup away. This is real Nominatim output (same honesty rule as
      // the rest of the geocode integration) -- never a fabricated
      // string -- and it's display-only here (not written back to the
      // Parcel row); an officer can still enter/correct it manually.
      if (!p.address && p.centroid_lat != null && p.centroid_lon != null) {
        api.get('/geocode/reverse', { params: { lat: p.centroid_lat, lon: p.centroid_lon } })
          .then(({ data }) => {
            if (!data?.display_name) return
            setParcel((prev) => (prev && prev.id === p.id ? { ...prev, address: data.display_name } : prev))
            setAllParcels((prev) => prev.map((ap) => (ap.id === p.id ? { ...ap, address: data.display_name } : ap)))
          })
          .catch(() => { /* lookup unavailable -- leave address blank rather than guess */ })
      }
    } catch (err) {
      // A stale/bad focus= link (parcel id that plain doesn't exist,
      // e.g. deleted or from a reseeded database) 404s here -- fall back
      // to the newest known parcel instead of leaving the page stuck with
      // no parcel loaded at all. Guarded against re-triggering itself if
      // even that fallback somehow fails.
      const fallbackId = allParcels[0]?.id
      if (fallbackId && fallbackId !== parcelId) {
        setSelectedParcelId(fallbackId)
      } else {
        console.error('Failed to load parcel', parcelId, err)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!selectedParcelId) return
    loadParcelDetail(selectedParcelId)
  }, [selectedParcelId])

  // Real underground structures + air-right corridors around this parcel (OpenStreetMap-derived, the
  // same store the map layers draw), returned in the parcel's own frame -- including ones that run
  // beside the parcel rather than through it. Step 1 is instant (already-scanned data); step 2 scans
  // any not-yet-scanned open-data cells and only re-renders the scene if that actually added something,
  // so the camera doesn't jump for nothing.
  async function loadInfra(parcelId) {
    setInfraState('loading')
    setInfraScan(null)
    const apply = (data) => setParcel((prev) => (prev && prev.id === parcelId ? { ...prev, infra: data } : prev))
    try {
      const first = await api.get(`/infra/parcel/${parcelId}`, { params: { scan: false } })
      apply(first.data)
      const second = await api.get(`/infra/parcel/${parcelId}`, { params: { scan: true } })
      setInfraScan(second.data.scan || null)
      if ((second.data.scan?.added || 0) > 0) apply(second.data)
      setInfraState('done')
    } catch (err) {
      console.warn('Nearby underground / air-right lookup failed', err)
      setInfraState('error')
    }
  }

  // Once the focused parcel's real detail (with its buildings) has loaded,
  // select the specific building requested via ?building=<id> so the 3D
  // view frames tightly on it (see ThreeScene's computeFrame) and its
  // floors/units panel opens immediately -- same experience as clicking
  // that building's card by hand, just automatic on arrival.
  useEffect(() => {
    if (!parcel || !focusBuildingId || appliedBuildingFocusRef.current) return
    const b = parcel.buildings?.find((x) => x.id === focusBuildingId)
    if (b) {
      appliedBuildingFocusRef.current = true
      setSelected({ type: 'building', id: b.id })
      setSelectedDetail({ kind: 'building', data: b })
    }
  }, [parcel, focusBuildingId])

  // After deleting the whole parcel (not just a building within it), there
  // is no parcel left to reload -- drop it from the list and select
  // whatever's next, same "pick the newest remaining one" default as the
  // initial load.
  // Applies a just-saved building/parcel edit straight to local state
  // (both the loaded `parcel` and, if it's the open panel, `selectedDetail`)
  // instead of a full reload -- a reload would call loadParcelDetail's own
  // setSelectedDetail(null)/setSelected(null) reset and close the panel
  // right after the person just saved something in it.
  function applyLocalEdits({ buildingId, buildingPatch, parcelPatch }) {
    setParcel((prev) => {
      if (!prev) return prev
      const updated = parcelPatch ? { ...prev, ...parcelPatch } : prev
      if (buildingId && buildingPatch) {
        return { ...updated, buildings: updated.buildings.map((b) => (b.id === buildingId ? { ...b, ...buildingPatch } : b)) }
      }
      return updated
    })
    if (buildingId && buildingPatch) {
      setSelectedDetail((prev) => (
        prev?.kind === 'building' && prev.data.id === buildingId ? { kind: 'building', data: { ...prev.data, ...buildingPatch } } : prev
      ))
    }
  }

  async function handleParcelDeleted(deletedId) {
    const remaining = allParcels.filter((p) => p.id !== deletedId)
    setAllParcels(remaining)
    setSelectedDetail(null)
    setSelected(null)
    if (remaining.length > 0) {
      setSelectedParcelId(remaining[0].id)
    } else {
      setParcel(null)
      setSelectedParcelId(null)
    }
  }

  async function handleSelect(hit) {
    setSelected(hit)
    if (hit.type === 'unit') {
      if (hit.seeded) {
        // Estimated unit -- no server record exists for a seed-unit-* id
        // (GET /units/{id} would 404), so the estimated object bundled
        // onto the mesh's userData in ThreeScene.jsx is used directly.
        setSelectedDetail({ kind: 'unit', data: { ...hit.unitData, buildingId: hit.buildingId, seeded: true } })
        return
      }
      const { data } = await api.get(`/units/${hit.id}`)
      let buildingId = null
      parcel?.buildings?.forEach((b) => b.floors?.forEach((f) => f.units?.forEach((u) => { if (u.id === hit.id) buildingId = b.id })))
      setSelectedDetail({ kind: 'unit', data: { ...data, buildingId } })
    } else if (hit.type === 'building') {
      const b = parcel?.buildings?.find((x) => x.id === hit.id)
      setSelectedDetail({ kind: 'building', data: b })
    } else if (hit.type === 'floor') {
      if (hit.seeded) {
        // Same reasoning as the seeded-unit branch above -- seed-floor-*
        // ids only ever existed client-side in ThreeScene.jsx's
        // seedFloors(), so parcel.buildings[].floors[] has no matching
        // row to find. Build the detail straight from what was bundled
        // onto the mesh.
        setSelectedDetail({
          kind: 'floor',
          data: {
            ...hit.floorData,
            buildingCode: hit.buildingCode,
            buildingId: hit.buildingId,
            buildingFootprintGeojson: hit.buildingFootprintGeojson,
            seeded: true,
          },
        })
        return
      }
      let found = null
      parcel?.buildings?.forEach((b) => b.floors?.forEach((f) => {
        if (f.id === hit.id) {
          found = {
            ...f,
            buildingCode: b.building_code,
            buildingId: b.id,
            buildingFootprintGeojson: b.footprint_geojson,
          }
        }
      }))
      setSelectedDetail({ kind: 'floor', data: found })
    } else if (hit.type === 'parcel') {
      setSelectedDetail({ kind: 'parcel', data: parcel })
    } else if (hit.type === 'infra') {
      const f = parcel?.infra?.features?.find((x) => x.id === hit.id)
      if (f) setSelectedDetail({ kind: 'infra', data: f })
    }
  }

  function toggleLayer(key) {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  // Real address search-as-you-type against GET /api/geocode/search
  // (OpenStreetMap Nominatim) -- debounced so it isn't fired on every
  // keystroke. This looks up REAL places; it does not search seeded
  // parcel data, since the person may be looking for an address that
  // doesn't have a parcel in the system yet.
  useEffect(() => {
    if (addressQuery.trim().length < 3) {
      setAddressResults([])
      return
    }
    const handle = setTimeout(async () => {
      setAddressSearching(true)
      try {
        const { data } = await api.get('/geocode/search', { params: { q: addressQuery } })
        setAddressResults(data)
      } catch {
        setAddressResults([])
      } finally {
        setAddressSearching(false)
      }
    }, 400)
    return () => clearTimeout(handle)
  }, [addressQuery])

  // If the searched address matches an existing parcel closely enough,
  // jump to it; otherwise just recenter the map view on the real
  // coordinates Nominatim returned (still real data, just not one of
  // ours yet).
  function handleAddressResultClick(result) {
    const nearest = allParcels.find((p) => {
      if (p.centroid_lat == null || p.centroid_lon == null) return false
      const dLat = Math.abs(p.centroid_lat - result.lat)
      const dLon = Math.abs(p.centroid_lon - result.lon)
      return dLat < 0.0015 && dLon < 0.0015 // ~150m
    })
    if (nearest) {
      setSelectedParcelId(nearest.id)
    }
    setShowAddressSearch(false)
    setAddressQuery('')
    setAddressResults([])
  }

  return (
    <div className="relative h-[calc(100vh-4rem)] w-full overflow-hidden">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-ink-950 z-20">
          <Loader2 className="animate-spin text-brand-400" size={32} />
        </div>
      )}

      {!loading && !parcel && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500 text-sm z-20 gap-3">
          <span>No parcels exist yet.</span>
          <button onClick={() => navigate('/admin/login')} className="btn-secondary text-xs">Sign in to create one</button>
        </div>
      )}

      {/* An empty parcel (real record, just nothing built on it yet --
          e.g. straight off a bulk import) still renders its faint ground
          plate/grid underneath this, which reads as a plain blank canvas
          at a glance. This makes that distinction explicit instead of
          leaving it looking like the 3D view itself failed to load. */}
      {!loading && parcel && parcel.buildings?.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500 text-sm z-10 gap-3 pointer-events-none">
          <span>No buildings recorded on this parcel yet.</span>
          {!isAdmin && (
            <button onClick={() => navigate('/admin/login')} className="btn-secondary text-xs pointer-events-auto">
              Sign in as an officer to add one
            </button>
          )}
        </div>
      )}

      {/* ThreeScene fills in an estimated floor-by-floor breakdown (see
          seedFloors() there) for any building with no real Floor rows yet,
          so the view isn't just one flat shell -- flagged here rather than
          silently, so it's never mistaken for a completed survey. */}
      {!loading && parcel?.buildings?.some((b) => !b.floors?.length) && (
        <div className="absolute bottom-4 left-4 z-10 pointer-events-none">
          <div className="card px-3 py-2 text-[11px] text-slate-400 bg-ink-900/85 max-w-[240px] leading-relaxed">
            Floor breakdown shown for an unsurveyed building is an estimate (1 floor / 3m), not a real survey result.
          </div>
        </div>
      )}

      {/* Always-on hint for a first-time visitor: nothing else on screen says
          outright that floors/units are themselves clickable, not just the
          building shell. Hidden once something is actually selected, so it
          doesn't sit there stating the obvious once the person has already
          found it. */}
      {!loading && !selectedDetail && parcel?.buildings?.length > 0 && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 pointer-events-none">
          <div className="card px-3.5 py-2 text-[11px] text-slate-300 bg-ink-900/85 whitespace-nowrap">
            Click on a floor or unit in the 3D view to see its property information
          </div>
        </div>
      )}

      <ThreeScene
        ref={sceneRef} parcel={parcel} layers={layers} mode={mode} exploded={exploded} onSelect={handleSelect}
        selectedId={selectedDetail?.kind === 'unit' || selectedDetail?.kind === 'infra' ? selectedDetail.data.id : null}
        isolatedFloorId={selectedDetail?.kind === 'floor' ? selectedDetail.data.id : null}
        focusedBuildingId={
          selectedDetail?.kind === 'building' ? selectedDetail.data.id :
          selectedDetail?.kind === 'floor' ? selectedDetail.data.buildingId :
          selectedDetail?.kind === 'unit' ? selectedDetail.data.buildingId :
          null
        }
        buildingStyle={buildingStyle}
        sceneTheme={sceneTheme}
      />

      {/* Top bar: parcel picker + view tools on the left, view mode + search on the right */}
      {!uiHidden && (
      <div className="absolute top-4 left-4 right-4 z-10 flex items-center gap-2 pointer-events-none">
        <div className="flex items-center gap-2 min-w-0 pointer-events-auto">
          {allParcels.length > 0 && (
            <select
              value={selectedParcelId || ''}
              onChange={(e) => setSelectedParcelId(e.target.value)}
              className="card !rounded-xl px-3 py-2 text-xs font-medium text-white bg-ink-900/90 border-none w-[180px] lg:w-[230px] truncate"
            >
              {allParcels.map((p) => (
                <option key={p.id} value={p.id}>{p.ulpin_2d} — {p.address?.slice(0, 30) || 'No address'}</option>
              ))}
            </select>
          )}
          {parcel && (
            <button
              onClick={() => setShowPropertyInfo(true)}
              title="View full property information for this parcel"
              className="card !rounded-xl p-2.5 text-brand-400 hover:text-brand-300 bg-ink-900/90 border-none flex-shrink-0 animate-[pulse_3s_ease-in-out_infinite] hover:animate-none"
            >
              <Info size={16} />
            </button>
          )}
          <div className="card p-1 flex items-center gap-0.5">
            <button onClick={() => sceneRef.current?.resetView()} title="Reset camera" className={toolBtn(false)}>
              <RotateCcw size={14} /><span className="hidden xl:inline">Reset</span>
            </button>
            <button onClick={() => sceneRef.current?.topView()} title="Top-down view" className={toolBtn(false)}>
              <Triangle size={14} /><span className="hidden xl:inline">Top</span>
            </button>
            <span className="w-px h-5 bg-white/10 mx-1" />
            <button onClick={() => setExploded((e) => !e)} title="Pull the floors apart" className={toolBtn(exploded)}>
              <Boxes size={14} /><span className="hidden lg:inline">Exploded</span>
            </button>
            <button
              onClick={() => setBuildingStyle((st) => (st === 'detailed' ? 'volumes' : 'detailed'))}
              title="Detailed facade (windows, balconies, roof) vs plain volumes"
              className={toolBtn(buildingStyle === 'detailed')}
            >
              <Building2 size={14} /><span className="hidden lg:inline">Facade</span>
            </button>
            <span className="w-px h-5 bg-white/10 mx-1" />
            <button
              onClick={() => setSceneTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
              title="Switch the 3D scene between dark and light"
              aria-label="Toggle 3D scene theme"
              className={toolBtn(false)}
            >
              {sceneTheme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            </button>
          </div>
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-2 pointer-events-auto">
          <div className="card p-1 flex items-center gap-0.5">
            <button onClick={() => setMode('3d')} className={toolBtn(mode === '3d')}><Box size={14} /> 3D</button>
            <button onClick={() => setMode('2d')} className={toolBtn(mode === '2d')}><MapIcon size={14} /> 2D</button>
          </div>

          {/* Everything known about the currently selected parcel, gathered from the exact same
              data already loaded for this view (parcel/buildings/floors/units, undergroundAssets,
              airRights, conflicts) into one single screen, instead of having to open each building,
              each underground layer item, etc. one at a time. */}
          {parcel && (
            <button
              onClick={() => setShowPropertyInfo(true)}
              className="card w-10 h-10 flex items-center justify-center text-slate-300 hover:text-brand-400 transition-colors"
              aria-label="Full property details"
              title="Full property details"
            >
              <Info size={16} />
            </button>
          )}

          {/* Real-time address search (OpenStreetMap Nominatim, not seeded data) */}
          <div className="relative">
            <button
              onClick={() => setShowAddressSearch((v) => !v)}
              className={`card w-10 h-10 flex items-center justify-center transition-colors ${showAddressSearch ? 'text-brand-400' : 'text-slate-300 hover:text-white'}`}
              aria-label="Search address"
            >
              <Search size={16} />
            </button>
            {showAddressSearch && (
              <div className="absolute top-12 right-0 card w-72 p-2 z-30">
                <input
                  autoFocus
                  value={addressQuery}
                  onChange={(e) => setAddressQuery(e.target.value)}
                  placeholder="Search a real address…"
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500/50"
                />
                {addressSearching && (
                  <div className="flex items-center gap-2 text-xs text-slate-500 px-2 py-2">
                    <Loader2 size={12} className="animate-spin" /> Searching…
                  </div>
                )}
                {!addressSearching && addressResults.length > 0 && (
                  <div className="mt-1 max-h-64 overflow-y-auto space-y-0.5">
                    {addressResults.map((r, i) => (
                      <button
                        key={i}
                        onClick={() => handleAddressResultClick(r)}
                        className="w-full text-left px-2 py-2 rounded-lg text-xs text-slate-300 hover:bg-white/5 hover:text-white transition-colors"
                      >
                        {r.display_name}
                      </button>
                    ))}
                  </div>
                )}
                {!addressSearching && addressQuery.length >= 3 && addressResults.length === 0 && (
                  <div className="text-xs text-slate-600 px-2 py-2">No matches found.</div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      )}

      {/* Parcel details: one slim strip along the top instead of a floating card on the right */}
      {!uiHidden && parcel && !selectedDetail && (
        <div className="absolute top-[4.25rem] left-4 right-4 z-10 hidden md:block pointer-events-none">
          <ParcelInfoCard variant="strip" parcel={parcel} onViewFullDetails={() => handleSelect({ type: 'parcel', id: parcel.id })} />
        </div>
      )}

      {/* Left column: layers, then what the underground / air-right layers are showing */}
      {!uiHidden && (
      <div className="absolute top-[7.5rem] left-4 bottom-20 z-10 w-60 hidden sm:flex flex-col gap-2 pointer-events-none">
        <div className="card p-2 pointer-events-auto flex-shrink-0">
          <button
            onClick={() => setLayersCollapsed((c) => !c)}
            className="w-full flex items-center justify-between px-1 text-[11px] font-semibold text-slate-400 tracking-wide"
          >
            <span className="flex items-center gap-1.5"><Layers size={12} /> LAYERS</span>
            {layersCollapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
          </button>
          {!layersCollapsed && (
            <div className="mt-1 space-y-0.5">
              {LAYER_DEFS.map((l) => (
                <button
                  key={l.key}
                  onClick={() => toggleLayer(l.key)}
                  className={`w-full flex items-center gap-2 px-2 py-1 rounded-md text-[11px] transition-colors ${
                    layers[l.key] ? 'text-white bg-white/5' : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  <l.icon size={12} />
                  <span className="flex-1 text-left">{l.label}</span>
                  <span className={`w-1.5 h-1.5 rounded-full ${layers[l.key] ? 'bg-brand-400' : 'bg-slate-700'}`} />
                </button>
              ))}
            </div>
          )}
        </div>

        {!loading && mode === '3d' && (
          <InfraLegend
            parcel={parcel} layers={layers} state={infraState} scan={infraScan} onSelect={handleSelect}
            selectedId={selectedDetail?.kind === 'infra' ? selectedDetail.data.id : null}
          />
        )}
      </div>
      )}

      {/* Mobile layer toggle strip */}
      {!uiHidden && (
      <div className="absolute bottom-4 left-4 right-20 sm:hidden flex gap-2 overflow-x-auto pointer-events-auto pb-1">
        {LAYER_DEFS.map((l) => (
          <button
            key={l.key}
            onClick={() => toggleLayer(l.key)}
            className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-medium border ${
              layers[l.key] ? 'bg-brand-500/15 text-brand-400 border-brand-500/30' : 'bg-ink-900/80 text-slate-500 border-white/10'
            }`}
          >
            <l.icon size={12} /> {l.label}
          </button>
        ))}
      </div>
      )}

      {/* Zoom / camera controls */}
      <div className="absolute bottom-4 right-4 flex items-end gap-2 pointer-events-auto z-10">
        {/* Directional pad — full free rotation up/down/left/right */}
        <div className="card p-1.5 grid grid-cols-3 grid-rows-3 gap-0.5 w-[108px] h-[108px]">
          <div />
          <button onClick={() => sceneRef.current?.rotate('vertical', -0.28)} aria-label="Rotate up" className="flex items-center justify-center rounded-lg text-slate-300 hover:text-brand-400 hover:bg-white/5"><ChevronUp size={16} /></button>
          <div />
          <button onClick={() => sceneRef.current?.rotate('horizontal', -0.28)} aria-label="Rotate left" className="flex items-center justify-center rounded-lg text-slate-300 hover:text-brand-400 hover:bg-white/5"><ChevronLeft size={16} /></button>
          <button onClick={() => sceneRef.current?.resetView()} aria-label="Reset view" className="flex items-center justify-center rounded-lg text-slate-500 hover:text-brand-400 hover:bg-white/5"><Maximize2 size={13} /></button>
          <button onClick={() => sceneRef.current?.rotate('horizontal', 0.28)} aria-label="Rotate right" className="flex items-center justify-center rounded-lg text-slate-300 hover:text-brand-400 hover:bg-white/5"><ChevronRight size={16} /></button>
          <div />
          <button onClick={() => sceneRef.current?.rotate('vertical', 0.28)} aria-label="Rotate down" className="flex items-center justify-center rounded-lg text-slate-300 hover:text-brand-400 hover:bg-white/5"><ChevronDown size={16} /></button>
          <div />
        </div>

        <div className="flex flex-col gap-1.5">
          <button
            onClick={() => setUiHidden((h) => !h)}
            aria-label={uiHidden ? 'Show panels' : 'Hide panels'}
            title={uiHidden ? 'Show panels' : 'Hide panels'}
            className="card w-10 h-10 flex items-center justify-center text-slate-300 hover:text-brand-400 transition-colors"
          >
            {uiHidden ? <Eye size={17} /> : <EyeOff size={17} />}
          </button>
        </div>
      </div>

      {/* Selection panel */}
      {selectedDetail && (
        <div className="absolute top-0 right-0 h-full w-full sm:w-96 bg-ink-900/95 backdrop-blur-lg border-l border-white/10 overflow-y-auto animate-fade-in z-10">
          <SelectionPanel
            detail={selectedDetail} parcel={parcel} onClose={() => { setSelectedDetail(null); setSelected(null) }}
            navigate={navigate} isAdmin={isAdmin} onSelect={handleSelect}
            onBuildingDeleted={() => loadParcelDetail(selectedParcelId)}
            onParcelDeleted={() => handleParcelDeleted(parcel.id)}
            onApplyEdits={applyLocalEdits}
          />
        </div>
      )}

      {showPropertyInfo && parcel && (
        <PropertyInfoModal
          parcel={parcel}
          onClose={() => setShowPropertyInfo(false)}
          onSelectBuilding={(buildingId) => { setShowPropertyInfo(false); handleSelect({ type: 'building', id: buildingId }) }}
          navigate={navigate}
        />
      )}
    </div>
  )
}

function SelectionPanel({ detail, parcel, onClose, navigate, isAdmin, onSelect, onBuildingDeleted, onParcelDeleted, onApplyEdits }) {
  const { kind, data } = detail
  const conflicts = parcel?.conflicts || []
  const conflictsRestricted = !!parcel?.conflictsRestricted
  const [deleting, setDeleting] = useState(false)

  // Real, persisted edit -- not a placeholder overlay. Saves straight to
  // the database (PATCH /buildings/{id} for the name, PATCH
  // /parcels/{id} for the address, both existing endpoints), so once
  // saved it shows up everywhere else that reads the same records too
  // (search, the admin dashboard/All Records, etc), not just here.
  const [editingBuilding, setEditingBuilding] = useState(false)
  const [editName, setEditName] = useState('')
  const [editAddress, setEditAddress] = useState('')
  const [savingBuilding, setSavingBuilding] = useState(false)
  const [saveError, setSaveError] = useState(null)

  function startEditBuilding() {
    setEditName(data.name || '')
    setEditAddress(parcel?.address || '')
    setSaveError(null)
    setEditingBuilding(true)
  }

  async function saveBuildingEdit() {
    setSavingBuilding(true)
    setSaveError(null)
    try {
      const nameChanged = editName.trim() !== (data.name || '')
      const addressChanged = !!parcel && editAddress.trim() !== (parcel.address || '')
      const tasks = []
      if (nameChanged) tasks.push(api.patch(`/buildings/${data.id}`, { name: editName.trim() || null }))
      if (addressChanged) tasks.push(api.patch(`/parcels/${parcel.id}`, { address: editAddress.trim() || null }))
      await Promise.all(tasks)
      onApplyEdits?.({
        buildingId: data.id,
        buildingPatch: nameChanged ? { name: editName.trim() || null } : null,
        parcelPatch: addressChanged ? { address: editAddress.trim() || null } : null,
      })
      setEditingBuilding(false)
    } catch (err) {
      setSaveError(err.response?.data?.detail || 'Could not save changes.')
    } finally {
      setSavingBuilding(false)
    }
  }

  async function handleDeleteBuilding() {
    if (!window.confirm(`Delete building "${data.name || data.building_code}" and everything under it (floors, units)? This cannot be undone.`)) {
      return
    }
    setDeleting(true)
    try {
      await api.delete(`/buildings/${data.id}`)
      onBuildingDeleted?.()
    } catch (err) {
      window.alert(err.response?.data?.detail || 'Delete failed.')
      setDeleting(false)
    }
  }

  async function handleDeleteParcel() {
    if (!window.confirm(`Delete parcel ${data.ulpin_2d} and everything under it (${data.buildings?.length || 0} building(s))? This cannot be undone.`)) {
      return
    }
    setDeleting(true)
    try {
      await api.delete(`/parcels/${data.id}`)
      onParcelDeleted?.()
    } catch (err) {
      window.alert(err.response?.data?.detail || 'Delete failed.')
      setDeleting(false)
    }
  }

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-5">
        <span className="badge bg-white/5 text-slate-400 border border-white/10 capitalize">{kind}</span>
        <button onClick={onClose} className="text-slate-500 hover:text-white"><X size={18} /></button>
      </div>

      {kind === 'unit' && (() => {
        const unitConflicts = conflicts.filter(
          (c) => c.unit_id === data.id || (c.message && data.ulpin_3d && c.message.includes(data.ulpin_3d)),
        )
        const estArea = data.seeded ? polygonArea(safeParseGeojson(data.footprint_geojson)) : null
        const estDepth = data.seeded && data.z_min != null && data.z_max != null ? data.z_max - data.z_min : null
        return (
          <>
            {data.seeded ? (
              <>
                <h2 className="font-display text-lg font-bold text-white mb-1">Estimated Unit</h2>
                <div className="mb-4 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                  Not yet surveyed. There's no real ULPIN, owner record, or verification status for this unit yet — everything below is a modeling estimate from the building's footprint, not measured data.
                </div>
                <div className="space-y-3">
                  <Row label="Property Type (estimated)" value={data.parcel_type?.replace('_', ' ')} />
                  {estArea != null && <Row label="Area (est.)" value={`~${estArea.toFixed(1)} sqm`} />}
                  {estDepth != null && <Row label="Volume (est.)" value={`~${(estArea * estDepth).toFixed(1)} m³`} />}
                  {data.z_min != null && <Row label="Z-Min (est.)" value={`${data.z_min.toFixed(1)} m`} />}
                  {data.z_max != null && <Row label="Z-Max (est.)" value={`${data.z_max.toFixed(1)} m`} />}
                </div>
                <div className="mt-6">
                  {!isAdmin && (
                    <button onClick={() => navigate('/admin/login')} className="btn-secondary w-full text-sm">
                      Sign in as an officer to survey this unit
                    </button>
                  )}
                </div>
              </>
            ) : (
              <>
                <h2 className="font-display text-lg font-bold text-white mb-1 break-all">{data.ulpin_3d}</h2>
                <div className="mb-4"><StatusBadge status={data.verification_status} /></div>

                <div className="space-y-3">
                  <Row label="Property Type" value={data.parcel_type?.replace('_', ' ')} />
                  <Row label="Area" value={`${data.area_sqm} sqm`} />
                  <Row label="Volume" value={`${data.volume_cum} m³`} />
                  <Row label="Z-Min" value={`${data.z_min} m`} />
                  <Row label="Z-Max" value={`${data.z_max} m`} />
                  <Row label="Owner Reference" value={data.owner_reference} />
                  {data.ai_confidence && <Row label="AI Confidence" value={`${(data.ai_confidence * 100).toFixed(0)}%`} />}
                </div>

                <div className="mt-5">
                  <SectionLabel icon={ShieldAlert} text="Conflicts" />
                  <ConflictList conflicts={unitConflicts} restricted={conflictsRestricted} emptyLabel="No conflicts detected for this unit" />
                </div>

                <div className="mt-6 flex flex-col gap-2">
                  <button onClick={() => navigate(`/property/${data.id}`)} className="btn-primary w-full text-sm">
                    View Full Record <ChevronRight size={15} />
                  </button>
                  <button onClick={() => navigate(`/report/${data.id}`)} className="btn-secondary w-full text-sm">
                    <Flag size={14} /> Report an Issue
                  </button>
                  <button onClick={() => navigate('/track')} className="btn-secondary w-full text-sm">
                    <Search size={14} /> Track a Grievance
                  </button>
                </div>
              </>
            )}
          </>
        )
      })()}

      {kind === 'building' && (() => {
        const footprintPts = safeParseGeojson(data.footprint_geojson)
        const footprintArea = polygonArea(footprintPts)
        // A freshly ML-detected building genuinely has no surveyed
        // num_floors/height_m yet (0 / null on the record -- see the
        // "never invent data" rule that runs through the backend's
        // footprint/floor pipeline). Rather than a bare "0" or blank,
        // fall back to a per-building estimate (see buildingEstimate.js --
        // varies with this building's own real footprint area/id, not a
        // flat number every unsurveyed building shares) -- clearly
        // labeled as an estimate, never written back to the record, so
        // it can't be mistaken for a real survey result anywhere else.
        const estimate = estimateBuildingDimensions(data)
        const isUnsurveyed = estimate.estimated
        const displayFloors = estimate.floors
        const displayHeight = estimate.height
        const totalUnitArea = data.floors?.reduce(
          (sum, f) => sum + (f.units?.reduce((s, u) => s + (u.area_sqm || 0), 0) || 0), 0,
        )
        const buildingConflicts = conflicts.filter((c) => c.building_id === data.id)
        return (
          <>
            {editingBuilding ? (
              <div className="mb-4 space-y-2">
                <input
                  autoFocus
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  placeholder="Building name"
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500/50"
                />
                <input
                  value={editAddress}
                  onChange={(e) => setEditAddress(e.target.value)}
                  placeholder="Address"
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-brand-500/50"
                />
                {saveError && <div className="text-[11px] text-rose-400">{saveError}</div>}
                <div className="flex gap-2">
                  <button
                    onClick={saveBuildingEdit}
                    disabled={savingBuilding}
                    className="btn-primary flex-1 !py-1.5 text-xs justify-center flex items-center gap-1.5"
                  >
                    {savingBuilding ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save
                  </button>
                  <button
                    onClick={() => setEditingBuilding(false)}
                    disabled={savingBuilding}
                    className="btn-secondary flex-1 !py-1.5 text-xs justify-center"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-start justify-between gap-2 mb-4">
                <h2 className="font-display text-lg font-bold text-white">{data.name || data.building_code}</h2>
                {isAdmin && (
                  <button onClick={startEditBuilding} className="text-slate-500 hover:text-white flex-shrink-0 mt-1" aria-label="Edit building">
                    <Pencil size={14} />
                  </button>
                )}
              </div>
            )}
            <div className="space-y-3">
              <Row label="Building ID" value={data.building_code} />
              <Row
                label="Type"
                value={`${data.building_type || 'Unspecified'}${data.building_type_source === 'unsurveyed' ? ' (estimated — not surveyed)' : ''}`}
              />
              <Row label="Number of Floors" value={isUnsurveyed ? `${displayFloors} (estimated — pending survey)` : displayFloors} />
              <Row label="Height" value={isUnsurveyed ? `~${displayHeight} m (estimated — pending survey)` : `${displayHeight} m`} />
              {isUnsurveyed && estimate.unitsPerFloor != null && (
                <Row label="Units per Floor" value={`~${estimate.unitsPerFloor} (estimated — pending survey)`} />
              )}
              {(() => {
                if (!footprintPts || footprintPts.length < 3) return null
                const xs = footprintPts.map((p) => p[0]), zs = footprintPts.map((p) => p[1])
                const lengthM = Math.max(...xs) - Math.min(...xs)
                const breadthM = Math.max(...zs) - Math.min(...zs)
                return (
                  <>
                    <Row label="Length (bounding box)" value={`${lengthM.toFixed(1)}m`} />
                    <Row label="Breadth (bounding box)" value={`${breadthM.toFixed(1)}m`} />
                  </>
                )
              })()}
              <Row label="Address" value={parcel?.address || 'Not on record'} />
              {footprintArea != null && <Row label="Footprint Area" value={`${footprintArea.toFixed(1)} sqm`} />}
              {footprintArea != null && (
                <Row
                  label="Total Built-Up Area"
                  value={`${(footprintArea * displayFloors).toFixed(1)} sqm${isUnsurveyed ? ' (estimated)' : ''}`}
                />
              )}
              {totalUnitArea > 0 && <Row label="Total Unit Area (verified layout)" value={`${totalUnitArea.toFixed(1)} sqm`} />}
              {data.ai_confidence && <Row label="Extraction Confidence" value={`${(data.ai_confidence * 100).toFixed(0)}%`} />}
              {data.ms_confidence && <Row label="Detection Confidence" value={`${(data.ms_confidence * 100).toFixed(0)}%`} />}
            </div>

            <div className="mt-5">
              <SectionLabel icon={Building2} text="Identifiers" />
              <div className="space-y-3">
                <Row label="Building DB ID" value={data.id} mono />
                {parcel?.ulpin_2d && <Row label="Parcel ULPIN" value={parcel.ulpin_2d} mono />}
                {data.osm_id && <Row label="OSM ID" value={data.osm_id} mono />}
                {data.ms_footprint_id && <Row label="MS Footprint ID" value={data.ms_footprint_id} mono />}
              </div>
            </div>

            {data.floors?.length > 0 ? (
              <div className="mt-5">
                <SectionLabel icon={Layers} text="Floor IDs" />
                <div className="space-y-1">
                  {data.floors
                    .slice()
                    .sort((a, b) => a.floor_number - b.floor_number)
                    .map((f) => (
                      <div key={f.floor_code} className="flex items-center justify-between py-1 text-xs">
                        <span className="text-slate-500">Floor {f.floor_number}</span>
                        <span className="text-slate-300 font-mono">{f.floor_code}</span>
                      </div>
                    ))}
                </div>
              </div>
            ) : (
              <div className="mt-5">
                <SectionLabel icon={Layers} text="Floor IDs" />
                <div className="text-xs text-slate-500">
                  No floor survey on record for this building yet.
                  {!isAdmin && (
                    <>
                      {' '}
                      <button onClick={() => navigate('/admin/login')} className="text-brand-400 hover:underline">
                        Sign in as an officer
                      </button> to add one.
                    </>
                  )}
                </div>
              </div>
            )}

            <div className="mt-5">
              <SectionLabel icon={ShieldAlert} text="Conflicts" />
              <ConflictList conflicts={buildingConflicts} restricted={conflictsRestricted} emptyLabel="No conflicts detected for this building" />
            </div>

            <div className="mt-5">
              <SectionLabel icon={AlertTriangle} text="Manual vs AI Comparison" />
              <ManualVsAI building={data} />
            </div>

            <BeforeAfterAIPanel buildingId={data.id} />

            <div className="flex flex-col gap-2 mt-5">
              <button
                onClick={() => navigate(`/report/building/${data.id}`)}
                className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5"
              >
                <Flag size={13} /> Report an Issue with This Building
              </button>
              <button
                onClick={() => navigate('/track')}
                className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5"
              >
                <Search size={13} /> Track a Grievance
              </button>
            </div>

            {isAdmin && (
              <button
                onClick={handleDeleteBuilding}
                disabled={deleting}
                className="w-full mt-5 flex items-center justify-center gap-1.5 text-xs text-rose-400 border border-rose-500/25 bg-rose-500/5 hover:bg-rose-500/10 rounded-lg px-3 py-2.5 transition-colors"
              >
                {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                Delete This Building
              </button>
            )}
          </>
        )
      })()}

      {kind === 'floor' && (() => {
        const footprintPts = safeParseGeojson(data.buildingFootprintGeojson)
        const floorArea = polygonArea(footprintPts)
        const totalUnitArea = data.units?.reduce((s, u) => s + (u.area_sqm || 0), 0)
        const building = parcel?.buildings?.find((b) => b.id === data.buildingId)
        const floorLevelConflicts = conflicts.filter(
          (c) => c.building_id === data.buildingId
            && (c.check_type === 'floor_overlap' || c.check_type === 'invalid_z_range')
            && c.message?.includes(data.floor_code),
        )
        const unitLevelConflicts = conflicts.filter(
          (c) => c.check_type === 'unit_overlap'
            && data.units?.some((u) => c.unit_id === u.id || c.message?.includes(u.ulpin_3d)),
        )
        // Length/breadth: the footprint's own bounding box -- the same
        // real geometry floorArea above is computed from, not a separate
        // guess. A rotated/irregular footprint's bounding box is larger
        // than its true width/depth, so this is labeled "(bounding box)"
        // rather than implied to be exact building dimensions.
        let lengthM = null, breadthM = null
        if (footprintPts && footprintPts.length >= 3) {
          const xs = footprintPts.map((p) => p[0]), zs = footprintPts.map((p) => p[1])
          lengthM = Math.max(...xs) - Math.min(...xs)
          breadthM = Math.max(...zs) - Math.min(...zs)
        }
        const floorDepthM = data.z_max - data.z_min
        const dims = building ? estimateBuildingDimensions(building) : null
        return (
          <>
            <h2 className="font-display text-lg font-bold text-white mb-4">Floor {data.floor_number}</h2>
            {data.seeded && (
              <div className="mb-4 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                Estimated floor — this building hasn't been surveyed yet. Floor count, boundaries, and unit layout below are a modeling estimate, not measured data. A real Floor ID/ULPIN only exists once an officer surveys this building.
              </div>
            )}
            <div className="space-y-3">
              <Row label="Floor ID" value={data.seeded ? 'Not yet assigned (estimated floor)' : data.id} mono={!data.seeded} />
              <Row label="Building ID" value={data.buildingId} mono />
              <Row label="Floor Code" value={data.seeded ? 'Not yet assigned' : data.floor_code} />
              <Row label="Building" value={data.buildingCode} />
              <Row label="Z Min" value={`${data.z_min.toFixed(1)}m${data.seeded ? ' (est.)' : ''}`} />
              <Row label="Z Range" value={`${data.z_min.toFixed(1)}m – ${data.z_max.toFixed(1)}m${data.seeded ? ' (est.)' : ''}`} />
              <Row label="Floor Depth (Z Max − Z Min)" value={`${floorDepthM.toFixed(1)}m${data.seeded ? ' (est.)' : ''}`} />
              {lengthM != null && <Row label="Length (bounding box)" value={`${lengthM.toFixed(1)}m`} />}
              {breadthM != null && <Row label="Breadth (bounding box)" value={`${breadthM.toFixed(1)}m`} />}
              {dims && (
                <Row
                  label="Building Height"
                  value={`${dims.height.toFixed(1)}m${dims.estimated ? ' (estimated)' : ''}`}
                />
              )}
              {floorArea != null && <Row label="Floor Area" value={`${floorArea.toFixed(1)} sqm`} />}
              {totalUnitArea > 0 && <Row label="Total Unit Area" value={`${totalUnitArea.toFixed(1)} sqm${data.seeded ? ' (est.)' : ''}`} />}
            </div>

            <div className="mt-5">
              <SectionLabel icon={Boxes} text={`Units on This Floor (${data.units?.length ?? 0})`} />
              {data.units?.length ? (
                <div className="space-y-1.5">
                  {data.units.slice().sort((a, c) => (a.unit_code || '').localeCompare(c.unit_code || '')).map((u, i) => {
                    const estArea = data.seeded ? polygonArea(safeParseGeojson(u.footprint_geojson)) : null
                    return (
                      <button
                        key={u.id}
                        onClick={() => onSelect?.({ type: 'unit', id: u.id, seeded: data.seeded, unitData: { ...u, z_min: data.z_min, z_max: data.z_max }, buildingId: data.buildingId })}
                        className="w-full flex items-center justify-between gap-2 text-xs bg-white/5 rounded-lg px-3 py-2 hover:bg-white/10 text-left"
                      >
                        <div className="min-w-0">
                          <div className="text-slate-300 font-mono">{data.seeded ? `Est. unit ${i + 1}` : u.unit_code}</div>
                          <div className="text-slate-500 font-mono truncate">{data.seeded ? 'Not surveyed' : u.ulpin_3d}</div>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {data.seeded
                            ? (estArea != null && <span className="text-slate-500">~{estArea.toFixed(1)} sqm (est.)</span>)
                            : (u.area_sqm != null && <span className="text-slate-500">{u.area_sqm} sqm</span>)}
                          {!data.seeded && <StatusBadge status={u.verification_status} />}
                        </div>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="text-xs text-slate-500">No units surveyed on this floor yet.</div>
              )}
            </div>

            {building && (
              <div className="mt-5">
                <SectionLabel icon={Building2} text="Building Info" />
                <div className="space-y-3">
                  <Row
                    label="Building Type"
                    value={`${building.building_type || 'Unspecified'}${
                      building.building_type_source === 'unsurveyed' ? ' (estimated, not surveyed)' : ''
                    }`}
                  />
                  <Row label="Consistency Check" value={building.consistency_flag ? 'Flagged' : 'OK'} />
                </div>
              </div>
            )}

            <div className="mt-5">
              <SectionLabel icon={ShieldAlert} text="Floor Conflicts" />
              <ConflictList conflicts={floorLevelConflicts} restricted={conflictsRestricted} emptyLabel="No floor-level conflicts (overlap / elevation) detected" />
            </div>

            <div className="mt-5">
              <SectionLabel icon={ShieldAlert} text="Unit Conflicts (this floor)" />
              <ConflictList conflicts={unitLevelConflicts} restricted={conflictsRestricted} emptyLabel="No unit-overlap conflicts detected on this floor" />
            </div>

            {building && (
              <div className="mt-5">
                <SectionLabel icon={AlertTriangle} text="Building Manual vs AI" />
                <BuildingSourceNote building={building} />
              </div>
            )}

            <div className="flex flex-col gap-2 mt-5">
              <button
                onClick={() => navigate(`/report/building/${data.buildingId}`, { state: { prefill: `Floor ${data.floor_number} (${data.floor_code}): ` } })}
                className="btn-primary w-full text-sm flex items-center justify-center gap-1.5"
              >
                <Flag size={13} /> Report an Issue with This Floor
              </button>
              <button
                onClick={() => navigate('/track')}
                className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5"
              >
                <Search size={13} /> Track a Grievance
              </button>
            </div>

            <p className="text-[11px] text-slate-600 mt-4 leading-relaxed">
              This floor is now isolated in full detail — every other floor in this building is
              collapsed to a thin slab to keep the view readable on tall buildings.
            </p>
            <button onClick={onClose} className="btn-secondary w-full text-sm mt-4">Show All Floors</button>
          </>
        )
      })()}

      {kind === 'infra' && (() => {
        const f = data
        const air = f.kind === 'air'
        const assumed = f.z_source !== 'osm_tag'
        const conflictTone = f.conflict_status === 'confirmed' ? 'bg-red-500/10 text-red-400 border-red-500/20'
          : f.conflict_status === 'potential' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
          : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
        return (
          <>
            <h2 className="font-display text-lg font-bold text-white mb-1">{f.label}{f.name ? ` · ${f.name}` : ''}</h2>
            <p className="text-xs text-slate-500 mb-3">
              {air ? 'Air-right corridor' : 'Underground structure'} · OpenStreetMap <span className="font-mono">{f.osm_id}</span>
            </p>
            <span className={`badge border ${conflictTone}`}>
              {f.conflict_status === 'confirmed' ? 'Conflict with a building' : f.conflict_status === 'potential' ? 'Potential conflict' : 'No conflict found'}
            </span>
            <div className="mt-3">
              <Row label={air ? 'Height above ground' : 'Depth below ground'} value={rangeText(f) || null} mono />
              {air && f.deck_top_m != null && <Row label="Deck top" value={`${Number(f.deck_top_m.toFixed(1))} m`} mono />}
              <Row label="Extent source" value={assumed ? 'Typical value for this type (not surveyed)' : 'Tagged in OpenStreetMap'} />
              <Row label="Confidence" value={f.confidence != null ? `${Math.round(f.confidence * 100)}%` : null} mono />
              <Row label="Width" value={f.width_m != null ? `${f.width_m} m` : null} mono />
              <Row label="Relation to parcel" value={f.on_parcel ? 'Crosses this parcel' : `${Math.round(f.distance_m)} m from this parcel`} />
            </div>
            {(f.conflict_reasons?.length > 0 || f.notes?.length > 0) && (
              <div className="mt-3 space-y-1.5">
                {f.conflict_reasons?.map((n, i) => <p key={`c${i}`} className="text-xs text-amber-300/90 leading-relaxed">· {n}</p>)}
                {f.notes?.map((n, i) => <p key={`n${i}`} className="text-xs text-slate-400 leading-relaxed">· {n}</p>)}
              </div>
            )}
            <p className="text-[11px] text-slate-500 mt-4 leading-relaxed">
              Detected from open data as a proposal for officer verification — not an official record of rights or a survey.
            </p>
            <button onClick={onClose} className="btn-secondary w-full text-sm mt-4">Close</button>
          </>
        )
      })()}

      {kind === 'parcel' && (
        <>
          <h2 className="font-display text-lg font-bold text-white mb-1 break-all">{data.ulpin_2d}</h2>
          <p className="text-xs text-slate-500 mb-4">Representative 2D ULPIN (sample format)</p>
          <div className="space-y-3">
            <Row label="Address" value={data.address} />
            <Row label="Area" value={`${data.area_sqm} sqm`} />
            <Row label="Buildings" value={data.buildings?.length} />
          </div>

          <div className="flex flex-col gap-2 mt-5">
            {data.buildings?.length > 0 && (
              <button
                onClick={() => navigate(`/report/building/${data.buildings[0].id}`)}
                className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5"
              >
                <Flag size={13} /> Report an Issue with This Parcel
              </button>
            )}
            <button
              onClick={() => navigate('/track')}
              className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5"
            >
              <Search size={13} /> Track a Grievance
            </button>
          </div>

          {isAdmin && (
            <button
              onClick={handleDeleteParcel}
              disabled={deleting}
              className="w-full mt-5 flex items-center justify-center gap-1.5 text-xs text-rose-400 border border-rose-500/25 bg-rose-500/5 hover:bg-rose-500/10 rounded-lg px-3 py-2.5 transition-colors"
            >
              {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
              Delete This Parcel (and all its buildings)
            </button>
          )}
        </>
      )}
    </div>
  )
}

// Everything already loaded for the selected parcel (buildings/floors/units, underground assets,
// air-rights corridors, conflicts), gathered into one screen instead of split across the per-item
// side panel -- a single place to answer "what's going on with this property", opened from the
// Info button in the top toolbar. Reads only parcel.* that loadParcelDetail() already fetched;
// makes no API calls of its own and invents nothing not already on the record.
function PropertyInfoModal({ parcel, onClose, onSelectBuilding, navigate }) {
  const buildings = parcel.buildings || []
  const underground = parcel.undergroundAssets || []
  const airRights = parcel.airRights || []
  const conflicts = parcel.conflicts || []
  const conflictsRestricted = !!parcel.conflictsRestricted
  // Which building's row is expanded inline, right here in the list --
  // NOT which building the whole modal is about (that's `parcel` -- one
  // modal per parcel, same as before). Clicking a building used to close
  // this modal and jump to the big full-page inspector; now it opens
  // in place and that full inspector is one extra, clearly optional click
  // away via "Open Full Inspector" inside the expanded row.
  const [expandedBuildingId, setExpandedBuildingId] = useState(null)
  // Which building's floor row is expanded to show its unit list + ULPINs -- scoped to
  // {buildingId, floorId} so expanding a floor in one building never leaks into another.
  const [expandedFloor, setExpandedFloor] = useState(null)

  // Same per-building estimate the building panel itself uses, so an unsurveyed building's floor
  // count here always matches what that building's own detail view shows -- never a second, diverging
  // guess for the same building.
  const buildingStats = buildings.map((b) => ({ building: b, estimate: estimateBuildingDimensions(b) }))
  const totalFloors = buildingStats.reduce((sum, { estimate }) => sum + (estimate.floors || 0), 0)
  const totalUnits = buildings.reduce((sum, b) => sum + (b.floors?.reduce((s, f) => s + (f.units?.length || 0), 0) || 0), 0)
  const anyUnsurveyed = buildingStats.some(({ estimate }) => estimate.estimated)

  // Two different sources feed the underground / air-right numbers:
  // - parcel.undergroundAssets / parcel.airRights: officially recorded rows tied to this
  //   parcel_id (officer / GPR / AI pipeline).
  // - parcel.infra.features: the open-data (OSM) nearby-structures scan, which is what the 3D
  //   view's Underground/Air-rights layers actually draw in addition to the official rows (see
  //   ThreeScene.jsx). Counting only the first set here used to make this modal say "0 air-right
  //   corridors" even while the 3D scene clearly showed one found via the open-data scan -- so
  //   both sources are counted and listed below, clearly labelled, instead of only the official one.
  const infra = parcel.infra?.available ? parcel.infra : null
  const nearbyUnderground = infra ? infra.features.filter((f) => f.kind === 'underground') : []
  const nearbyAir = infra ? infra.features.filter((f) => f.kind === 'air') : []
  const undergroundTotal = underground.length + nearbyUnderground.length
  const airRightsTotal = airRights.length + nearbyAir.length

  const stats = [
    { icon: Building2, label: 'Buildings', value: buildings.length },
    { icon: Layers, label: 'Total Floors', value: totalFloors, estimated: anyUnsurveyed },
    { icon: Users, label: 'Total Units', value: totalUnits },
    { icon: Cable, label: 'Underground Assets', value: undergroundTotal },
    { icon: Plane, label: 'Air-Right Corridors', value: airRightsTotal },
    { icon: ShieldAlert, label: 'Conflicts', value: conflictsRestricted ? '—' : conflicts.length },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="card max-w-2xl w-full p-0 max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-ink-900/95 backdrop-blur-lg border-b border-white/10 p-5 flex items-start justify-between gap-3 z-10">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-brand-400 mb-1">
              <Info size={15} />
              <span className="text-[11px] font-semibold uppercase tracking-wide">Full Property Details</span>
            </div>
            <h2 className="font-display text-lg font-bold text-white break-all flex items-center gap-2">
              <Hash size={15} className="text-slate-500 flex-shrink-0" /> {parcel.ulpin_2d}
            </h2>
            {parcel.address && (
              <p className="text-xs text-slate-400 mt-1 flex items-center gap-1.5">
                <MapPin size={12} className="flex-shrink-0" /> {parcel.address}
              </p>
            )}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white flex-shrink-0" aria-label="Close"><X size={18} /></button>
        </div>

        <div className="p-5">
          {/* Quick stats grid -- same visual language as the 3D City Map's stats strip, so the two
              pages feel like one product rather than two differently-designed screens. */}
          <div className="grid grid-cols-3 gap-2 mb-6">
            {stats.map((s) => (
              <div key={s.label} className="bg-white/5 border border-white/10 rounded-lg p-3">
                <div className="flex items-center gap-1.5 text-slate-500 mb-1">
                  <s.icon size={12} /> <span className="text-[10px] uppercase tracking-wide">{s.label}</span>
                </div>
                <div className="text-xl font-bold text-white">
                  {s.value}{s.estimated && <span className="text-xs font-normal text-amber-400 ml-1">est.</span>}
                </div>
              </div>
            ))}
          </div>

          <Row label="Area" value={parcel.area_sqm != null ? `${parcel.area_sqm} sqm` : null} />

          {/* Buildings -- click any one to expand its details right here in the
              list (floor/unit breakdown, type, height, data source). "Open
              Full Inspector" inside the expanded row is the only thing that
              still closes this modal and jumps to the dedicated building
              page, for someone who explicitly wants that. */}
          <div className="mt-5">
            <SectionLabel icon={Building2} text={`Buildings (${buildings.length})`} />
            {buildings.length === 0 ? (
              <div className="text-xs text-slate-500">No buildings registered on this parcel yet.</div>
            ) : (
              <div className="space-y-1.5">
                {buildingStats.map(({ building: b, estimate }) => {
                  const unitCount = b.floors?.reduce((s, f) => s + (f.units?.length || 0), 0) || 0
                  const isOpen = expandedBuildingId === b.id
                  return (
                    <div key={b.id} className="bg-white/5 border border-white/10 rounded-lg overflow-hidden">
                      <button
                        onClick={() => setExpandedBuildingId(isOpen ? null : b.id)}
                        className="w-full text-left hover:bg-white/10 px-3 py-2.5 flex items-center justify-between gap-3 transition-colors"
                      >
                        <div className="min-w-0">
                          <div className="text-sm text-white font-medium truncate">{b.name || b.building_code}</div>
                          <div className="text-xs text-slate-500">
                            {estimate.floors} floor{estimate.floors === 1 ? '' : 's'}{estimate.estimated ? ' (est.)' : ''} · {unitCount} unit{unitCount === 1 ? '' : 's'}
                          </div>
                        </div>
                        <ChevronRight size={15} className={`text-slate-500 flex-shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                      </button>

                      {isOpen && (
                        <div className="px-3 pb-3 pt-1 border-t border-white/10 space-y-2">
                          {/* One column, top to bottom -- a 2-column layout here used to put
                              "Height"/"Data source" over on the right edge of the card where they
                              read as a second, disconnected block of information instead of part
                              of the same list as "Type"/"Floors" on the left. */}
                          <div className="space-y-1 text-xs">
                            <Row label="Building ID" value={b.building_code} mono />
                            <Row label="Type" value={b.building_type || 'Not recorded'} />
                            <Row label="Height" value={b.height_m != null ? `${b.height_m} m` : estimate.estimated ? `~${estimate.floors * 3} m (est.)` : null} />
                            <Row label="Floors" value={b.num_floors != null ? b.num_floors : `${estimate.floors} (est.)`} />
                            {b.num_basement_levels > 0 && <Row label="Basement Levels" value={b.num_basement_levels} />}
                            <Row label="Data source" value={b.floor_source === 'ml_model' ? 'AI model' : b.floor_source === 'manual' ? 'Surveyed' : 'Unsurveyed estimate'} />
                          </div>

                          {b.floors?.length > 0 && (
                            <div className="pt-1">
                              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Floors &amp; Units</div>
                              <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
                                {b.floors.map((f) => {
                                  const floorLabel = f.floor_number < 0 ? `Basement ${-f.floor_number}` : f.floor_number === 0 ? 'Ground' : `Floor ${f.floor_number}`
                                  const floorHeight = f.z_min != null && f.z_max != null ? `${(f.z_max - f.z_min).toFixed(1)} m` : null
                                  const floorOpen = expandedFloor?.buildingId === b.id && expandedFloor?.floorId === f.id
                                  return (
                                    <div key={f.id} className="bg-white/5 rounded">
                                      <button
                                        onClick={() => setExpandedFloor(floorOpen ? null : { buildingId: b.id, floorId: f.id })}
                                        className="w-full flex items-center justify-between text-xs px-2 py-1 hover:bg-white/5 rounded"
                                      >
                                        <span className="text-slate-300 flex items-center gap-1.5">
                                          {floorLabel}
                                          <span className="text-slate-600 font-mono text-[10px]">{f.floor_code}</span>
                                        </span>
                                        <span className="text-slate-500 flex items-center gap-2">
                                          {floorHeight && <span className="font-mono text-[10px]">{floorHeight}</span>}
                                          {f.units?.length || 0} unit{(f.units?.length || 0) === 1 ? '' : 's'}
                                          {f.units?.length > 0 && <ChevronRight size={11} className={`transition-transform ${floorOpen ? 'rotate-90' : ''}`} />}
                                        </span>
                                      </button>
                                      {floorOpen && f.units?.length > 0 && (
                                        <div className="px-2 pb-1.5 space-y-1">
                                          {f.units.map((u) => (
                                            <div key={u.id} className="flex items-center justify-between gap-2 text-[10px] bg-ink-950/40 rounded px-2 py-1">
                                              <span className="text-slate-400 font-mono break-all">{u.ulpin_3d}</span>
                                              <span className="text-slate-500 flex-shrink-0">{u.area_sqm != null ? `${u.area_sqm} sqm` : '—'}</span>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  )
                                })}
                              </div>
                            </div>
                          )}

                          <button
                            onClick={() => onSelectBuilding(b.id)}
                            className="mt-1 text-[11px] font-medium text-brand-400 hover:text-brand-300 flex items-center gap-1"
                          >
                            Open Full Inspector <ChevronRight size={12} />
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Underground assets -- official records (officer / GPR / AI) PLUS anything the
              open-data nearby-structures scan found, since that scan is what the Underground
              layer in the 3D view also draws (see ThreeScene.jsx) -- listing only the official
              rows here used to under-count against what the 3D scene actually showed. */}
          <div className="mt-5">
            <SectionLabel icon={Cable} text={`Underground Assets (${undergroundTotal})`} />
            {undergroundTotal === 0 ? (
              <div className="text-xs text-slate-500">No underground assets found on or near this parcel.</div>
            ) : (
              <div className="space-y-1.5">
                {underground.map((a) => (
                  <div key={a.id} className="flex items-center justify-between gap-3 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs">
                    <span className="text-slate-300 capitalize">{(a.asset_type || 'other').replace('_', ' ')}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-500 font-mono">
                        {a.depth_min_m != null && a.depth_max_m != null ? `${a.depth_min_m}–${a.depth_max_m} m deep` : '—'}
                      </span>
                      <span className="badge bg-white/5 text-slate-400 border border-white/10">on record</span>
                    </div>
                  </div>
                ))}
                {nearbyUnderground.map((f) => (
                  <div key={f.id} className="flex items-center justify-between gap-3 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs">
                    <span className="text-slate-300 capitalize">{infraStyle(f).short}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-500 font-mono">{rangeText(f) || '—'}</span>
                      <span className="badge bg-white/5 text-slate-400 border border-white/10">
                        {f.on_parcel ? 'open data · on parcel' : `open data · ${Math.round(f.distance_m)} m away`}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {nearbyUnderground.length > 0 && (
              <p className="text-[10px] text-slate-500 mt-1.5 leading-relaxed">
                "Open data" rows come from an OpenStreetMap nearby-structures scan, not a survey or officer entry.
              </p>
            )}
          </div>

          {/* Air-right corridors -- same combined official + open-data logic as Underground Assets
              above, so a corridor the 3D view draws from the nearby-structures scan (e.g. a
              power line or elevated road within the scan radius) is never missing here just
              because no officer has formally recorded it against this parcel yet. */}
          <div className="mt-5">
            <SectionLabel icon={Plane} text={`Air-Right Corridors (${airRightsTotal})`} />
            {airRightsTotal === 0 ? (
              <div className="text-xs text-slate-500">No air-right corridors found on or near this parcel.</div>
            ) : (
              <div className="space-y-1.5">
                {airRights.map((c) => (
                  <div key={c.id} className="flex items-center justify-between gap-3 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs">
                    <span className="text-slate-300 capitalize">{(c.corridor_type || 'elevated transport').replace('_', ' ')}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-500 font-mono">
                        {c.height_min_m != null && c.height_max_m != null ? `${c.height_min_m}–${c.height_max_m} m` : '—'}
                      </span>
                      {c.conflict_status && c.conflict_status !== 'none' && (
                        <span className={`badge ${c.conflict_status === 'confirmed' ? 'bg-red-500/10 text-red-400 border border-red-500/25' : 'bg-amber-500/10 text-amber-400 border border-amber-500/25'}`}>
                          {c.conflict_status}
                        </span>
                      )}
                      <span className="badge bg-white/5 text-slate-400 border border-white/10">on record</span>
                    </div>
                  </div>
                ))}
                {nearbyAir.map((f) => (
                  <div key={f.id} className="flex items-center justify-between gap-3 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs">
                    <span className="text-slate-300 capitalize">{infraStyle(f).short}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-500 font-mono">{rangeText(f) || '—'}</span>
                      {f.conflict_status && f.conflict_status !== 'none' && (
                        <span className={`badge ${f.conflict_status === 'confirmed' ? 'bg-red-500/10 text-red-400 border border-red-500/25' : 'bg-amber-500/10 text-amber-400 border border-amber-500/25'}`}>
                          {f.conflict_status}
                        </span>
                      )}
                      <span className="badge bg-white/5 text-slate-400 border border-white/10">
                        {f.on_parcel ? 'open data · on parcel' : `open data · ${Math.round(f.distance_m)} m away`}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {nearbyAir.length > 0 && (
              <p className="text-[10px] text-slate-500 mt-1.5 leading-relaxed">
                "Open data" rows come from an OpenStreetMap nearby-structures scan, not a survey or officer entry.
              </p>
            )}
          </div>

          {/* Conflicts -- reuses the exact same ConflictList the per-building/unit panels use, here
              showing every conflict on the parcel rather than one item's slice of them. */}
          <div className="mt-5">
            <SectionLabel icon={ShieldAlert} text="Conflicts" />
            <ConflictList conflicts={conflicts} restricted={conflictsRestricted} emptyLabel="No conflicts detected for this parcel" />
          </div>

          <div className="flex flex-col gap-2 mt-6">
            {buildings.length > 0 && (
              <button
                onClick={() => navigate(`/report/building/${buildings[0].id}`)}
                className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5"
              >
                <Flag size={13} /> Report an Issue with This Parcel
              </button>
            )}
            <button onClick={() => navigate('/track')} className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5">
              <Search size={13} /> Track a Grievance
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Row({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/5">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-sm text-white font-medium text-right ${mono ? 'font-mono break-all' : 'capitalize'}`}>{value ?? '—'}</span>
    </div>
  )
}

function SectionLabel({ icon: Icon, text }) {
  return (
    <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide flex items-center gap-1.5 mb-1.5">
      <Icon size={12} /> {text}
    </div>
  )
}

function severityStyle(severity) {
  const s = (severity || '').toUpperCase()
  if (s === 'HIGH') return { text: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/25', dot: 'bg-red-400' }
  if (s === 'MEDIUM') return { text: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/25', dot: 'bg-amber-400' }
  return { text: 'text-sky-400', bg: 'bg-sky-500/10', border: 'border-sky-500/25', dot: 'bg-sky-400' }
}

// Real conflicts, sourced from GET /api/review/conflicts (topology
// validation: floor overlaps, unit overlaps, invalid elevation ranges,
// underground-utility intersections) -- never a placeholder "looks fine"
// state when the check genuinely couldn't be run (restricted=true for an
// anonymous viewer who isn't signed in to see conflict data).
function ConflictList({ conflicts, restricted, emptyLabel }) {
  if (restricted) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 bg-white/[0.03] border border-white/10 rounded-lg px-3 py-2">
        <ShieldAlert size={13} className="flex-shrink-0" /> Sign in to view conflict status.
      </div>
    )
  }
  if (!conflicts || conflicts.length === 0) {
    return (
      <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
        <CheckCircle2 size={13} className="flex-shrink-0" /> {emptyLabel || 'No conflicts detected'}
      </div>
    )
  }
  return (
    <div className="space-y-1.5">
      {conflicts.map((c) => {
        const s = severityStyle(c.severity)
        return (
          <div key={c.id} className={`rounded-lg px-3 py-2 border ${s.bg} ${s.border}`}>
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.dot}`} />
              <span className={`text-[10px] font-semibold uppercase tracking-wide ${s.text}`}>
                {c.severity} · {c.check_type?.replace(/_/g, ' ')}
              </span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">{c.message}</p>
          </div>
        )
      })}
    </div>
  )
}

// Side-by-side comparison of a building's pre-AI manually entered
// floors/height (manual_num_floors/manual_height_m, snapshotted the
// moment the model overwrote them) against the AI model's own current
// output (num_floors/height_m) -- real stored values on both sides, no
// invented "estimated" numbers.
function ManualVsAI({ building }) {
  if (!building) return null
  const hasManualSnapshot = building.manual_num_floors != null || building.manual_height_m != null
  if (!hasManualSnapshot) {
    return (
      <div className="text-xs text-slate-500 bg-white/[0.03] border border-white/10 rounded-lg px-3 py-2 leading-relaxed">
        {building.footprint_source === 'ml_model'
          ? 'This building was generated directly by the AI model — no prior manual entry exists to compare against.'
          : 'This building is still on manually entered values — no AI extraction has run yet.'}
      </div>
    )
  }
  const floorsDiffer = building.manual_num_floors != null && building.manual_num_floors !== building.num_floors
  const heightDiffer = building.manual_height_m != null && Math.abs(building.manual_height_m - (building.height_m || 0)) > 0.05
  const anyDiffer = floorsDiffer || heightDiffer
  return (
    <div className="space-y-2">
      <div className={`flex items-center gap-1.5 text-[11px] font-semibold ${anyDiffer ? 'text-amber-400' : 'text-emerald-400'}`}>
        {anyDiffer ? <AlertTriangle size={12} className="flex-shrink-0" /> : <CheckCircle2 size={12} className="flex-shrink-0" />}
        {anyDiffer ? 'Manual entry and AI extraction disagree' : 'Manual entry and AI extraction agree'}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2">
          <div className="text-[10px] text-slate-500 mb-1">Manually Entered</div>
          <div className="text-xs text-slate-300">{building.manual_num_floors ?? '—'} floors</div>
          <div className="text-xs text-slate-300">{building.manual_height_m != null ? `${building.manual_height_m} m` : '—'}</div>
        </div>
        <div className={`rounded-lg border px-2.5 py-2 ${anyDiffer ? 'border-amber-500/30 bg-amber-500/5' : 'border-white/10 bg-white/[0.03]'}`}>
          <div className="text-[10px] text-slate-500 mb-1">
            AI Generated{building.ai_confidence != null ? ` · ${(building.ai_confidence * 100).toFixed(0)}%` : ''}
          </div>
          <div className={`text-xs ${floorsDiffer ? 'text-amber-400 font-medium' : 'text-slate-300'}`}>{building.num_floors ?? '—'} floors</div>
          <div className={`text-xs ${heightDiffer ? 'text-amber-400 font-medium' : 'text-slate-300'}`}>{building.height_m != null ? `${building.height_m} m` : '—'}</div>
        </div>
      </div>
    </div>
  )
}

// Compact one-line version of the same manual-vs-AI comparison, used in
// the Floor panel to surface the parent building's status without
// duplicating the full breakdown shown on the Building panel.
function BuildingSourceNote({ building }) {
  const hasManualSnapshot = building.manual_num_floors != null || building.manual_height_m != null
  if (!hasManualSnapshot) {
    return <div className="text-xs text-slate-500">Building {building.building_code}: no manual/AI comparison available yet.</div>
  }
  const floorsDiffer = building.manual_num_floors != null && building.manual_num_floors !== building.num_floors
  const heightDiffer = building.manual_height_m != null && Math.abs(building.manual_height_m - (building.height_m || 0)) > 0.05
  const anyDiffer = floorsDiffer || heightDiffer
  return (
    <div className={`flex items-center gap-1.5 text-xs ${anyDiffer ? 'text-amber-400' : 'text-emerald-400'}`}>
      {anyDiffer ? <AlertTriangle size={12} className="flex-shrink-0" /> : <CheckCircle2 size={12} className="flex-shrink-0" />}
      Building {building.building_code}: manual vs AI {anyDiffer ? 'mismatch' : 'match'}
    </div>
  )
}