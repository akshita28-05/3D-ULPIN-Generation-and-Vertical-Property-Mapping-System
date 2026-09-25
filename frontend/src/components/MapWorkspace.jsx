import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Loader2, Search, Info, Layers, Crosshair, Box, Square, Wand2, CheckCircle2, AlertTriangle,
  ExternalLink, Download, Trash2, X, LocateFixed, Building2, Cable, Plane, ScanEye,
} from 'lucide-react'
import api from '../api/client'
import Map3D from './Map3D.jsx'
import EvidenceBadge from './EvidenceBadge.jsx'
import AboutModal from './AboutModal.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import {
  DEFAULT_CENTER, DEFAULT_ZOOM, CITY_PRESETS, AUTO_MAP_MIN_ZOOM, CATEGORY_COLORS, INFRA_COLORS, INFRA_FALLBACK_COLOR, INFRA_MIN_ZOOM,
} from '../config/region.js'

const FILTERS = ['all', 'residential', 'commercial', 'mixed', 'institutional', 'other']

export default function MapWorkspace({ mode = 'public' }) {
  const isAdminMode = mode === 'admin'
  const { user } = useAuth()
  const navigate = useNavigate()
  const mapRef = useRef(null)

  const [features, setFeatures] = useState(null)
  const [stats, setStats] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [filter, setFilter] = useState('all')
  const [view, setView] = useState({ zoom: DEFAULT_ZOOM, pitch: 60, bounds: null })
  const [layers, setLayers] = useState({
    osm: true, region: true, registered: true, underground: true, air: true, xray: false, labels: false, terrain: false,
  })
  const [mapProblem, setMapProblem] = useState(null)
  const [infraData, setInfraData] = useState(null)
  const [infraStatus, setInfraStatus] = useState({ state: 'zoom' })
  const [selectedInfra, setSelectedInfra] = useState(null)
  const [tab, setTab] = useState('buildings')
  const [showAbout, setShowAbout] = useState(false)
  const [imageryDown, setImageryDown] = useState(false)
  const [layersOpen, setLayersOpen] = useState(() => typeof window === 'undefined' || window.innerWidth >= 1024)

  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(null)

  const [coverage, setCoverage] = useState(null)

  const reload = useCallback(async () => {
    try {
      const [b, s] = await Promise.all([
        api.get('/map/buildings', { params: { limit: 5000 } }),
        api.get('/map/stats'),
      ])
      setFeatures(b.data)
      setStats(s.data)
      setLoadError(null)
    } catch {
      setLoadError('Could not load buildings from the server. The map still works; registered buildings will appear once the API is reachable.')
      setFeatures((prev) => prev || { type: 'FeatureCollection', features: [] })
    }
  }, [])

  useEffect(() => {
    reload()
    api.get('/map/coverage').then((r) => setCoverage(r.data)).catch(() => {})
  }, [reload])

  const buildings = useMemo(() => (features?.features || []).map((f) => f.properties), [features])
  const visibleBuildings = useMemo(
    () => buildings.filter((b) => filter === 'all' || b.category === filter),
    [buildings, filter],
  )
  const presentCategories = useMemo(() => new Set(buildings.map((b) => b.category)), [buildings])
  const infraFeatures = useMemo(() => (infraData?.features || []).filter((f) => (
    f.properties.kind === 'underground' ? layers.underground : layers.air
  )), [infraData, layers.underground, layers.air])
  const infraCounts = useMemo(() => ({
    underground: infraFeatures.filter((f) => f.properties.kind === 'underground').length,
    air: infraFeatures.filter((f) => f.properties.kind === 'air').length,
  }), [infraFeatures])
  const presentInfraTypes = useMemo(() => [...new Set(infraFeatures.map((f) => f.properties.subtype))], [infraFeatures])
  const highlight = useMemo(
    () => (selectedInfra ? (infraData?.features || []).find((f) => f.properties.id === selectedInfra.id) || null : null),
    [selectedInfra, infraData],
  )

  function selectInfra(props, fly = false) {
    setSelectedInfra(props)
    setSelected(null)
    if (fly && props?.lat != null) {
      mapRef.current?.flyTo({ lat: props.lat, lon: props.lon, zoom: 17.2, pitch: props.kind === 'air' ? 62 : 45 })
    }
  }

  function selectBuilding(props, fly = true) {
    setSelected(props)
    setSelectedInfra(null)
    if (fly && props?.lat != null) mapRef.current?.flyTo({ lat: props.lat, lon: props.lon, zoom: 18, pitch: 60 })
  }

  async function handleSearch(e) {
    e?.preventDefault()
    if (query.trim().length < 3) return
    setSearching(true)
    setSearchError(null)
    try {
      const { data } = await api.get('/geocode/search', { params: { q: query.trim() } })
      setResults(data)
      if (data.length === 0) setSearchError('No places found. Try a nearby town or landmark.')
    } catch (err) {
      setResults([])
      setSearchError(err.response?.data?.detail || 'Search is unavailable right now.')
    } finally {
      setSearching(false)
    }
  }

  function goToResult(r) {
    setResults([])
    setQuery(r.display_name)
    mapRef.current?.flyTo({ lat: r.lat, lon: r.lon, zoom: 16.5, pitch: 60 })
  }

  function zoomToData() {
    if (coverage?.has_data) mapRef.current?.flyTo({ lat: coverage.lat, lon: coverage.lon, zoom: 16, pitch: 60 })
  }

  async function handleDelete(b) {
    if (!window.confirm(`Delete parcel ${b.ulpin_2d} and everything under it (building, floors, units)? This cannot be undone.`)) return
    try {
      await api.delete(`/parcels/${b.parcel_id}`)
      setSelected(null)
      reload()
    } catch (err) {
      window.alert(err.response?.data?.detail || 'Delete failed.')
    }
  }

  const toggle = (key) => setLayers((l) => ({ ...l, [key]: !l[key] }))

  const canAutoMap = isAdminMode && ['surveyor', 'verifier', 'admin'].includes(user?.role)

  return (
    <div className="px-3 sm:px-6 py-4 max-w-[1500px] mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div>
          <h1 className="font-display text-xl sm:text-2xl font-bold text-white">
            {isAdminMode ? 'GIS Map' : '3D City Map'}
          </h1>
          <p className="text-xs text-slate-500">
            Satellite imagery, 3D buildings, and the underground and air-rights layers found automatically in open data. Drag to pan, right-drag or Ctrl-drag to tilt.
          </p>
        </div>
        <button onClick={() => setShowAbout(true)} className="btn-secondary !py-2 !px-3 text-xs">
          <Info size={14} /> About &amp; disclaimer
        </button>
      </div>

      <StatsBar stats={stats} />

      <div className="grid lg:grid-cols-[minmax(0,1fr)_340px] gap-3 mt-3">
        <div className="card relative overflow-hidden h-[62vh] lg:h-[calc(100vh-17rem)] min-h-[460px]">
          <Map3D
            ref={mapRef}
            registered={features}
            selectedId={selected?.id}
            highlight={highlight}
            onSelect={(p) => selectBuilding(p, false)}
            onSelectInfra={(p) => { selectInfra(p, false); setTab('vertical') }}
            onViewChange={setView}
            onImageryError={() => setImageryDown(true)}
            onMapProblem={setMapProblem}
            onInfraData={setInfraData}
            onInfraStatus={setInfraStatus}
            showOsm={layers.osm}
            showRegion={layers.region}
            showRegistered={layers.registered}
            showUnderground={layers.underground}
            showAir={layers.air}
            xray={layers.xray}
            showLabels={layers.labels}
            showTerrain={layers.terrain}
          />

          <InfraStatusChip status={infraStatus} counts={infraCounts} />
          {mapProblem && (
            <div className="absolute top-14 left-1/2 -translate-x-1/2 z-20 max-w-[90%] px-3 py-2 rounded-md bg-rose-600/90 text-white text-xs shadow-lg flex items-start gap-2">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{mapProblem}</span>
              <button onClick={() => setMapProblem(null)} className="ml-1 opacity-80 hover:opacity-100"><X size={13} /></button>
            </div>
          )}

          { }
          <div className="absolute top-3 left-3 z-10 w-[min(320px,calc(100%-90px))]">
            <form onSubmit={handleSearch} className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                className="input-field !pl-9 !py-2 shadow-lg"
                placeholder="Search a place (e.g. Ashoknagar)"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              {searching && <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-brand-400" />}
            </form>
            {results.length > 0 && (
              <div className="card mt-1 max-h-56 overflow-y-auto shadow-xl">
                {results.map((r, i) => (
                  <button key={i} onClick={() => goToResult(r)} className="block w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-white/5 border-b border-white/5 last:border-0">
                    {r.display_name}
                  </button>
                ))}
              </div>
            )}
            {searchError && <p className="text-[11px] text-amber-400 mt-1 bg-black/50 rounded px-2 py-1">{searchError}</p>}
            <div className="flex flex-wrap gap-1 mt-2 map-overlay">
              {CITY_PRESETS.map((c) => (
                <button
                  key={c.label}
                  onClick={() => mapRef.current?.flyTo({ lat: c.lat, lon: c.lon, zoom: c.zoom, pitch: 60 })}
                  className="px-2 py-1 rounded-full text-[10px] font-medium bg-black/55 text-slate-200 hover:bg-black/75 border border-white/10"
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          <div className="absolute top-28 right-2.5 z-10 flex flex-col gap-1.5">
            <MapButton
              title={view.pitch > 5 ? 'Top-down 2D view' : 'Tilted 3D view'}
              onClick={() => mapRef.current?.setPitch(view.pitch > 5 ? 0 : 60)}
            >
              {view.pitch > 5 ? <Square size={14} /> : <Box size={14} />}
              <span>{view.pitch > 5 ? '2D' : '3D'}</span>
            </MapButton>
            <MapButton title="Back to the default map location" onClick={() => mapRef.current?.flyTo({ lat: DEFAULT_CENTER[0], lon: DEFAULT_CENTER[1], zoom: DEFAULT_ZOOM, pitch: 60 })}>
              <Crosshair size={14} /><span>Reset</span>
            </MapButton>
            {coverage?.has_data && (
              <MapButton title="Fly to where your building data is" onClick={zoomToData}>
                <LocateFixed size={14} /><span>Data</span>
              </MapButton>
            )}
          </div>

          <div className="absolute bottom-8 left-3 z-10 map-overlay">
            <button onClick={() => setLayersOpen((o) => !o)} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-black/65 text-slate-100 text-xs border border-white/10 mb-1">
              <Layers size={13} /> Layers
            </button>
            {layersOpen && (
              <div className="rounded-md bg-black/70 backdrop-blur border border-white/10 p-2.5 text-xs text-slate-200 space-y-1.5 w-52 max-h-[16rem] overflow-y-auto">
                <Check label="OSM buildings" on={layers.osm} onChange={() => toggle('osm')} swatch="#f1f5f9" />
                <Check label="Region footprints" on={layers.region} onChange={() => toggle('region')} swatch="#94a3b8" />
                <Check label="Registered (3D ULPIN)" on={layers.registered} onChange={() => toggle('registered')} swatch={CATEGORY_COLORS.residential} />
                <div className="pt-1 mt-0.5 border-t border-white/10 space-y-1.5">
                  <Check label="Underground (open data)" on={layers.underground} onChange={() => toggle('underground')} swatch={INFRA_COLORS.metro_tunnel} />
                  <Check label="Air-rights corridors" on={layers.air} onChange={() => toggle('air')} swatch={INFRA_COLORS.flyover} />
                  <Check label="X-ray (fade the surface)" on={layers.xray} onChange={() => toggle('xray')} />
                </div>
                <Check label="Place labels" on={layers.labels} onChange={() => toggle('labels')} />
                <Check label="Terrain relief" on={layers.terrain} onChange={() => toggle('terrain')} />
                <div className="pt-1.5 mt-1 border-t border-white/10 grid grid-cols-2 gap-x-2 gap-y-1">
                  {Object.entries(CATEGORY_COLORS).map(([k, c]) => (
                    <span key={k} className="flex items-center gap-1.5 text-[10px] capitalize text-slate-300">
                      <i className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: c }} /> {k}
                    </span>
                  ))}
                </div>
                <p className="text-[10px] text-slate-400 leading-snug">Grey = footprint with unknown height (placeholder height).</p>
                {presentInfraTypes.length > 0 && (
                  <div className="pt-1.5 mt-1 border-t border-white/10 grid grid-cols-2 gap-x-2 gap-y-1">
                    {presentInfraTypes.map((t) => (
                      <span key={t} className="flex items-center gap-1.5 text-[10px] text-slate-300">
                        <i className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: INFRA_COLORS[t] || INFRA_FALLBACK_COLOR }} />
                        {t.replace(/_/g, ' ')}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {imageryDown && (
            <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10 px-3 py-1.5 rounded-md bg-amber-500/90 text-[#1E251C] text-xs font-medium">
              Satellite imagery unreachable — showing an OpenStreetMap basemap instead
            </div>
          )}

          {canAutoMap && <AutoMapPanel view={view} onFinished={reload} />}
        </div>

        <aside className="card flex flex-col overflow-hidden h-[52vh] lg:h-[calc(100vh-17rem)] min-h-[360px]">
          {selected && (
            <SelectedCard
              b={selected}
              canDelete={isAdminMode && user?.role === 'admin'}
              onClose={() => setSelected(null)}
              onDelete={() => handleDelete(selected)}
              onOpen3D={() => navigate(`/viewer?focus=parcel:${selected.parcel_id}`)}
            />
          )}

          {selectedInfra && <SelectedInfraCard p={selectedInfra} onClose={() => setSelectedInfra(null)} />}

          <div className="flex border-b border-white/5 text-xs">
            {[['buildings', 'Buildings', Building2], ['vertical', `Underground & air (${infraCounts.underground + infraCounts.air})`, Cable]].map(([k, label, Icon]) => (
              <button
                key={k} onClick={() => setTab(k)}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 ${tab === k ? 'text-white border-b-2 border-brand-500' : 'text-slate-500 hover:text-slate-300'}`}
              >
                <Icon size={12} /> {label}
              </button>
            ))}
          </div>

          {tab === 'vertical' && (
            <div className="flex-1 overflow-y-auto">
              <InfraList
                features={infraFeatures} status={infraStatus} selectedId={selectedInfra?.id}
                onPick={(p) => selectInfra(p, true)}
                onRescan={() => mapRef.current?.rescan()}
              />
            </div>
          )}

          <div className={`p-3 border-b border-white/5 ${tab === 'vertical' ? 'hidden' : ''}`}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-white flex items-center gap-1.5"><Building2 size={13} className="text-brand-400" /> Registered buildings</span>
              <span className="text-[11px] text-slate-500">{visibleBuildings.length}</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {FILTERS.filter((f) => f === 'all' || presentCategories.has(f)).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-2.5 py-1 rounded-full text-[11px] capitalize ${filter === f ? 'bg-brand-500 text-[#1E251C] font-semibold' : 'bg-white/5 text-slate-300 hover:bg-white/10'}`}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          <div className={`flex-1 overflow-y-auto ${tab === 'vertical' ? 'hidden' : ''}`}>
            {features === null && <div className="flex justify-center py-10"><Loader2 className="animate-spin text-brand-400" size={22} /></div>}
            {loadError && <p className="p-3 text-[11px] text-amber-400">{loadError}</p>}
            {features && !loadError && visibleBuildings.length === 0 && (
              <div className="p-4 text-xs text-slate-500 leading-relaxed">
                No registered buildings yet.
                {isAdminMode
                  ? ' Zoom into an area and press "Auto-map this view" — it does the rest.'
                  : ' Officers add them with one click; they will show up here.'}
                {coverage?.has_data && (
                  <button onClick={zoomToData} className="block mt-3 text-brand-400 hover:underline">Fly to where the region data is →</button>
                )}
              </div>
            )}
            {visibleBuildings.slice(0, 300).map((b) => (
              <button
                key={b.id}
                onClick={() => selectBuilding(b)}
                className={`w-full text-left px-3 py-2.5 border-b border-white/5 hover:bg-white/5 ${selected?.id === b.id ? 'bg-brand-500/10' : ''}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-white truncate">{b.name}</span>
                  <EvidenceBadge small state={b.floor_state} method={b.floor_method} />
                </div>
                <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-500">
                  <i className="w-2 h-2 rounded-sm inline-block" style={{ background: CATEGORY_COLORS[b.category] }} />
                  <span className="capitalize">{b.category}</span>
                  <span>·</span>
                  <span>{b.num_floors ? `${b.num_floors} floor${b.num_floors > 1 ? 's' : ''}` : 'floors unknown'}</span>
                  <span>·</span>
                  <span>{b.units} unit{b.units === 1 ? '' : 's'}</span>
                </div>
              </button>
            ))}
            {visibleBuildings.length > 300 && (
              <p className="p-3 text-[11px] text-slate-500">Showing the 300 tallest. Zoom the map or use the filters to find others.</p>
            )}
          </div>
        </aside>
      </div>

      {showAbout && <AboutModal onClose={() => setShowAbout(false)} />}
    </div>
  )
}


function StatsBar({ stats }) {
  const tiles = [
    ['Buildings', stats?.buildings],
    ['3D units', stats?.units],
    ['Max floors', stats?.max_floors],
    ['Underground', stats?.infra_underground],
    ['Air-rights', stats?.infra_air],
    ['Areas', stats?.areas],
  ]
  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
      {tiles.map(([label, value]) => (
        <div key={label} className="card px-3 py-2.5">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
          <div className="font-display text-xl font-bold text-white">{value ?? '—'}</div>
        </div>
      ))}
    </div>
  )
}

function MapButton({ children, onClick, title }) {
  return (
    <button
      title={title}
      onClick={onClick}
      className="flex items-center justify-center gap-1 w-[58px] py-1.5 rounded-md bg-white text-slate-800 text-[11px] font-semibold shadow hover:bg-slate-100"
    >
      {children}
    </button>
  )
}

function Check({ label, on, onChange, swatch }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <input type="checkbox" checked={on} onChange={onChange} className="accent-[#D4B26A]" />
      {swatch && <i className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: swatch }} />}
      {label}
    </label>
  )
}

function SelectedCard({ b, canDelete, onClose, onDelete, onOpen3D }) {
  return (
    <div className="p-3 border-b border-white/5 bg-brand-500/5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white truncate">{b.name}</div>
          <div className="text-[11px] font-mono text-slate-400 break-all">{b.ulpin_2d}</div>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white"><X size={15} /></button>
      </div>
      {b.address && <div className="text-[11px] text-slate-500 mt-1">{b.address}</div>}

      <div className="grid grid-cols-2 gap-x-3 gap-y-1 mt-2 text-[11px]">
        <span className="text-slate-500">Type</span><span className="text-slate-200 capitalize">{b.building_type}</span>
        <span className="text-slate-500">Floors</span>
        <span className="text-slate-200 flex items-center gap-1.5">
          {b.num_floors || "—"} <EvidenceBadge small state={b.floor_state} method={b.floor_method} />
        </span>
        <span className="text-slate-500">Height</span>
        <span className="text-slate-200">{b.height_known ? `${Number(b.height_m).toFixed(1)} m` : 'unknown'}</span>
        <span className="text-slate-500">Units</span>
        <span className="text-slate-200">{b.units} ({b.approved_units} verified)</span>
      </div>
      {b.floor_state !== 'OBSERVED' && b.num_floors && (
        <p className="text-[10px] text-amber-400/90 mt-2 leading-snug">Floor count is estimated ({b.floor_method}). A verifier confirms it before units are approved.</p>
      )}
      {b.consistency_flag && (
        <p className="text-[10px] text-rose-400 mt-1 flex items-center gap-1"><AlertTriangle size={11} /> Height and floor count don't agree — flagged for review.</p>
      )}

      <div className="flex flex-wrap gap-2 mt-3">
        <button onClick={onOpen3D} className="btn-primary !py-1.5 !px-3 text-xs"><ExternalLink size={12} /> Open units in 3D</button>
        <a href={`/api/interop/cityjson/parcels/${b.parcel_id}`} className="btn-secondary !py-1.5 !px-3 text-xs" title="Open standard 3D city model (CityJSON)">
          <Download size={12} /> CityJSON
        </a>
        {canDelete && (
          <button onClick={onDelete} className="btn-secondary !py-1.5 !px-3 text-xs text-rose-300"><Trash2 size={12} /> Delete</button>
        )}
      </div>
    </div>
  )
}


const STAGE_LABEL = {
  pending: 'Starting…', fetching: 'Fetching building outlines…', processing: 'Creating parcels & buildings…',
  finalizing: 'Generating floors, units & 3D ULPINs…',
  infra: 'Scanning open data: tunnels, basements, viaducts…',
}

function AutoMapPanel({ view, onFinished }) {
  const [job, setJob] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(true)
  const pollRef = useRef(null)
  const zoomOk = (view?.zoom ?? 0) >= AUTO_MAP_MIN_ZOOM

  useEffect(() => () => clearInterval(pollRef.current), [])

  async function start() {
    if (!view?.bounds) return
    setError(null)
    setJob(null)
    setRunning(true)
    try {
      const { data } = await api.post('/auto/run', view.bounds)
      pollRef.current = setInterval(async () => {
        try {
          const { data: current } = await api.get(`/bulk-import/jobs/${data.job_id}`)
          setJob({ ...current, source: data.source })
          if (current.status === 'done' || current.status === 'failed') {
            clearInterval(pollRef.current)
            setRunning(false)
            onFinished?.()
          }
        } catch {
          clearInterval(pollRef.current)
          setRunning(false)
          setError('Lost contact with the server while mapping.')
        }
      }, 1200)
    } catch (err) {
      setRunning(false)
      setError(err.response?.data?.detail || 'Could not start auto-mapping.')
    }
  }

  const pct = job?.total_buildings ? Math.round((job.processed_buildings / job.total_buildings) * 100) : 0
  const s = job?.summary

  return (
    <div className="absolute bottom-8 right-3 z-10 w-[min(300px,calc(100%-24px))] map-overlay">
      {!open ? (
        <button onClick={() => setOpen(true)} className="btn-primary !py-2 !px-3 text-xs ml-auto flex"><Wand2 size={13} /> Auto-map</button>
      ) : (
        <div className="rounded-lg bg-black/75 backdrop-blur border border-white/10 p-3 text-slate-200">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-semibold flex items-center gap-1.5"><Wand2 size={13} className="text-brand-400" /> Auto-map this view</span>
            <button onClick={() => setOpen(false)} className="text-slate-500 hover:text-white"><X size={14} /></button>
          </div>

          {!job && !running && (
            <p className="text-[11px] text-slate-400 leading-snug mb-2">
              One click: outlines → floors → units → 3D ULPINs → checks → review queue. No files, no forms.
            </p>
          )}

          {!running && (
            <button onClick={start} disabled={!zoomOk} className="btn-primary w-full !py-2 text-xs">
              <Wand2 size={13} /> {job ? 'Map this view again' : 'Auto-map this view'}
            </button>
          )}
          {!zoomOk && !running && (
            <p className="text-[10px] text-amber-400 mt-1.5">Zoom in a little more (level {AUTO_MAP_MIN_ZOOM}+, now {view?.zoom?.toFixed(1)}) so the area is small enough.</p>
          )}
          {error && <p className="text-[11px] text-rose-400 mt-2">{error}</p>}

          {running && (
            <div className="mt-1">
              <div className="flex items-center gap-2 text-[11px] text-slate-300">
                <Loader2 size={13} className="animate-spin text-brand-400" />
                {STAGE_LABEL[job?.status] || STAGE_LABEL.pending}
              </div>
              <div className="h-1.5 mt-2 rounded-full bg-white/10 overflow-hidden">
                <div className="h-full bg-brand-500 transition-all" style={{ width: `${job?.status === 'finalizing' || job?.status === 'infra' ? 100 : pct}%` }} />
              </div>
              {job?.source && <p className="text-[10px] text-slate-500 mt-1">Source: {job.source === 'osm' ? 'OpenStreetMap (live)' : 'region footprints (local)'}</p>}
            </div>
          )}

          {job?.status === 'failed' && <p className="text-[11px] text-rose-400 mt-2">{job.error_message || 'Import failed.'}</p>}

          {job?.status === 'done' && (
            <div className="mt-2 text-[11px]">
              <div className="flex items-center gap-1.5 text-emerald-400 font-medium"><CheckCircle2 size={13} /> Done — {s?.buildings ?? 0} buildings, {s?.units ?? 0} units</div>
              {s && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  <span className="text-emerald-400">{s.OBSERVED} observed</span>·
                  <span className="text-amber-400">{s.PREDICTED} predicted</span>·
                  <span className="text-slate-400">{s.NOT_DETERMINABLE} undetermined</span>
                </div>
              )}
              {s?.infra && (
                <div className="mt-2 rounded-md bg-white/5 p-2 leading-snug">
                  <div className="flex items-center gap-1.5 text-slate-200">
                    <Cable size={12} style={{ color: INFRA_COLORS.metro_tunnel }} /> {s.infra.underground} underground
                    <span className="text-slate-600">·</span>
                    <Plane size={12} style={{ color: INFRA_COLORS.flyover }} /> {s.infra.air} air-rights
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5">
                    {s.infra.underground + s.infra.air === 0
                      ? 'None mapped in open data for this view. Try a city chip (metro lines are mapped there).'
                      : `${s.infra.linked_underground + s.infra.linked_air} linked to registered parcels. Depths/heights are typical values unless OpenStreetMap gives them.`}
                  </div>
                </div>
              )}
              {job.flagged_buildings > 0 && <p className="text-amber-400 mt-1">{job.flagged_buildings} flagged for checks</p>}
              {job.error_message && <p className="text-amber-400 mt-1">{job.error_message}</p>}
              <div className="flex flex-wrap gap-2 mt-2.5">
                <Link to="/admin/review" className="btn-secondary !py-1.5 !px-2.5 text-[11px]">Review queue</Link>
                <Link to={`/bulk-viewer?jobId=${job.id}`} className="btn-secondary !py-1.5 !px-2.5 text-[11px]">Explore units in 3D</Link>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


const fmtM = (v) => (v == null ? '—' : `${Number(v).toFixed(v % 1 ? 1 : 0)} m`)

function verticalText(p) {
  return p.kind === 'underground'
    ? `${fmtM(p.z_min_m)} to ${fmtM(p.z_max_m)} below ground`
    : p.subtype === 'power_line'
      ? `wires clear ${fmtM(p.z_min_m)}, right-of-way airspace up to ${fmtM(p.z_max_m)}`
      : `deck underside ${fmtM(p.z_min_m)}, airspace up to ${fmtM(p.z_max_m)}`
}

function EvidenceChip({ p }) {
  const observed = p.evidence === 'OBSERVED'
  return (
    <span
      title={observed ? 'Depth / height came from an OpenStreetMap tag' : 'Position is from OpenStreetMap; depth / height is a typical value for this kind of structure'}
      className={`px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide ${observed ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'}`}
    >
      {observed ? 'FROM TAG' : 'ASSUMED'}
    </span>
  )
}

function InfraStatusChip({ status, counts }) {
  const map = {
    zoom: [`Zoom in to level ${INFRA_MIN_ZOOM} to see underground & air-rights`, 'text-slate-300'],
    scanning: ['Scanning open data for tunnels, basements, viaducts…', 'text-brand-300', true],
    busy: ['Another scan is running — results will appear shortly', 'text-amber-300', true],
    zoom_in: ['Zoom in a little to scan this area', 'text-amber-300'],
    unavailable: [status.message ? `Open-data scan unavailable — ${status.message}` : 'Open-data scan unavailable', 'text-rose-300'],
    partial: ['Part of this area could not be scanned', 'text-amber-300'],
    error: [status.message || 'Could not load underground / air-rights', 'text-rose-300'],
    ok: [
      counts.underground + counts.air === 0
        ? 'Scanned — nothing underground or elevated is mapped in open data here'
        : `${counts.underground} underground · ${counts.air} air-rights in view`,
      'text-emerald-300',
    ],
  }
  const entry = map[status.state]
  if (!entry) return null
  const [text, color, spin] = entry
  return (
    <div className="absolute top-3 right-16 z-10 max-w-[calc(100%-26rem)] hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/70 border border-white/10 text-[10px]">
      {spin ? <Loader2 size={11} className="animate-spin text-brand-400" /> : <ScanEye size={11} className={color} />}
      <span className={`${color} truncate`}>{text}</span>
    </div>
  )
}

function InfraList({ features, status, selectedId, onPick, onRescan }) {
  const rows = [...features].sort((a, b) => (
    a.properties.kind === b.properties.kind ? a.properties.label.localeCompare(b.properties.label) : a.properties.kind === 'underground' ? -1 : 1
  ))
  if (rows.length === 0) {
    return (
      <div className="p-4 text-xs text-slate-500 leading-relaxed space-y-2">
        <p>
          {status.state === 'zoom'
            ? `Zoom the map in to level ${INFRA_MIN_ZOOM} or closer and the app scans OpenStreetMap by itself — no upload, no sensor.`
            : 'Nothing underground or elevated is mapped in open data for this view yet.'}
        </p>
        <p className="text-slate-600">City chips (Mumbai, Hyderabad, Bengaluru, Delhi) open on areas with mapped metro tunnels and viaducts.</p>
        {(status.state === 'unavailable' || status.state === 'error') && (
          <button onClick={onRescan} className="btn-secondary !py-1.5 !px-3 text-xs">Try the scan again</button>
        )}
      </div>
    )
  }
  return (
    <div>
      <p className="px-3 py-2 text-[10px] text-slate-500 leading-snug border-b border-white/5">
        Found automatically in OpenStreetMap. Proposals for verifier review — not an official record.
      </p>
      {rows.slice(0, 300).map((f) => {
        const p = f.properties
        return (
          <button
            key={p.id} onClick={() => onPick(p)}
            className={`w-full text-left px-3 py-2.5 border-b border-white/5 hover:bg-white/5 ${selectedId === p.id ? 'bg-brand-500/10' : ''}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-white truncate flex items-center gap-1.5">
                <i className="w-2.5 h-2.5 rounded-sm inline-block shrink-0" style={{ background: INFRA_COLORS[p.subtype] || INFRA_FALLBACK_COLOR }} />
                {p.name || p.label}
              </span>
              <EvidenceChip p={p} />
            </div>
            <div className="mt-1 text-[11px] text-slate-500">{p.label} · {verticalText(p)}</div>
          </button>
        )
      })}
    </div>
  )
}

function SelectedInfraCard({ p, onClose }) {
  const notes = Array.isArray(p.notes) ? p.notes : []
  const osm = p.osm_id ? `https://www.openstreetmap.org/${p.osm_id}` : null
  return (
    <div className="p-3 border-b border-white/5 bg-brand-500/5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white truncate flex items-center gap-1.5">
            <i className="w-2.5 h-2.5 rounded-sm inline-block shrink-0" style={{ background: INFRA_COLORS[p.subtype] || INFRA_FALLBACK_COLOR }} />
            {p.name || p.label}
          </div>
          <div className="text-[11px] text-slate-400">{p.label} · {p.kind === 'underground' ? 'underground' : 'air-rights'}</div>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white"><X size={15} /></button>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 mt-2 text-[11px]">
        <span className="text-slate-500">{p.kind === 'underground' ? 'Depth' : 'Height'}</span>
        <span className="text-slate-200 flex items-center gap-1.5 flex-wrap">{verticalText(p)} <EvidenceChip p={p} /></span>
        {p.kind === 'air' && p.deck_top_m > 0 && (<><span className="text-slate-500">Deck top</span><span className="text-slate-200">{fmtM(p.deck_top_m)}</span></>)}
        {p.width_m > 0 && (<><span className="text-slate-500">Width</span><span className="text-slate-200">{fmtM(p.width_m)}</span></>)}
        <span className="text-slate-500">Position from</span>
        <span className="text-slate-200">OpenStreetMap {osm && <a href={osm} target="_blank" rel="noreferrer" className="text-brand-400 hover:underline">view</a>}</span>
        {p.confidence != null && (<><span className="text-slate-500">Confidence</span><span className="text-slate-200">{Math.round(p.confidence * 100)}%</span></>)}
      </div>
      {notes.length > 0 && (
        <ul className="mt-2 space-y-1">
          {notes.map((n, i) => <li key={i} className="text-[10px] text-amber-400/90 leading-snug">{n}</li>)}
        </ul>
      )}
      <p className="text-[10px] text-slate-500 mt-2 leading-snug">A proposal for verifier review, not an official record. Where it crosses a registered parcel, open that parcel in 3D to see it at its real depth / height.</p>
    </div>
  )
}
