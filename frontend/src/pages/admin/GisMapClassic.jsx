import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MapContainer, TileLayer, Popup, Rectangle, Polygon } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import api from '../../api/client'
import { useAuth } from '../../context/AuthContext.jsx'
import { Loader2, MapPin, Square, CheckCircle2, AlertTriangle, ChevronRight, Search, Trash2, ExternalLink } from 'lucide-react'
import { DragToggle, DrawBoxLayer, FlyToCenter } from './BulkImportPanel.jsx'

const MADHYA_PRADESH_DEFAULT = [24.8474, 77.6939]
const MADHYA_PRADESH_DEFAULT_ZOOM = 11

export default function GisMapClassic() {
  const [parcels, setParcels] = useState([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [deletingId, setDeletingId] = useState(null)

  async function handleDeleteParcel(p) {
    if (!window.confirm(`Delete parcel ${p.ulpin_2d} and everything under it (${p.buildings?.length || 0} building(s), their floors/units)? This cannot be undone.`)) {
      return
    }
    setDeletingId(p.id)
    try {
      await api.delete(`/parcels/${p.id}`)
      setParcels((prev) => prev.filter((x) => x.id !== p.id))
    } catch (err) {
      window.alert(err.response?.data?.detail || 'Delete failed.')
    } finally {
      setDeletingId(null)
    }
  }

  const [importMode, setImportMode] = useState(false)
  const [drawing, setDrawing] = useState(false)
  const [box, setBox] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState(null)
  const [job, setJob] = useState(null)
  const [importing, setImporting] = useState(false)
  const [importSource, setImportSource] = useState('osm')

  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(null)
  const [flyTo, setFlyTo] = useState(null)

  function reloadParcels() {
    return api.get('/parcels', { params: { limit: 5000 } }).then((res) => setParcels(res.data))
  }

  useEffect(() => {
    reloadParcels().finally(() => setLoading(false))
  }, [])

  function resetImport() {
    setBox(null); setPreview(null); setPreviewError(null); setJob(null); setDrawing(false)
  }

  async function handlePreview() {
    if (!box) return
    setPreviewLoading(true)
    setPreviewError(null)
    setPreview(null)
    try {
      const [[south, west], [north, east]] = box
      const { data } = await api.post('/bulk-import/preview', { south, west, north, east, search_query: null, source: importSource })
      setPreview(data)    } catch (err) {
      setPreviewError(err.response?.data?.detail || (importSource === 'osm' ? 'Could not reach OSM Overpass -- check network connectivity and try again.' : 'No Microsoft footprints loaded for this area yet -- run scripts/load_ms_footprints.py on the quadkey file(s) covering it first.'))
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleCommit() {
    if (!box) return
    setImporting(true)
    setJob(null)
    try {
      const [[south, west], [north, east]] = box
      const { data: startedJob } = await api.post('/bulk-import/commit', { south, west, north, east, search_query: null, source: importSource })
      setJob(startedJob)
      const poll = setInterval(async () => {
        const { data: current } = await api.get(`/bulk-import/jobs/${startedJob.job_id}`)
        setJob(current)
        if (current.status === 'done' || current.status === 'failed') {
          clearInterval(poll)
          setImporting(false)
          if (current.status === 'done') {
            reloadParcels()
            setTimeout(() => navigate(`/bulk-viewer?jobId=${current.id}`), 900)
          }
        }
      }, 1200)
    } catch {
      setImporting(false)
    }
  }

  const importProgressPct = job?.total_buildings ? Math.round((job.processed_buildings / job.total_buildings) * 100) : 0

  const withCoords = parcels.filter((p) => p.centroid_lat && p.centroid_lon)

  const defaultCenter = MADHYA_PRADESH_DEFAULT
  const defaultZoom = MADHYA_PRADESH_DEFAULT_ZOOM

  async function handleSearch(e) {
    e.preventDefault()
    if (searchQuery.trim().length < 3) return
    setSearching(true)
    setSearchError(null)
    try {
      const { data } = await api.get('/geocode/search', { params: { q: searchQuery } })
      setSearchResults(data)
      if (data.length === 0) setSearchError('No matching place found.')
    } catch (err) {
      setSearchError(err.response?.data?.detail || 'Search failed -- try again.')
    } finally {
      setSearching(false)
    }
  }

  function selectSearchResult(r) {
    setFlyTo([r.lat, r.lon])
    setSearchResults([])
    setSearchQuery(r.display_name)
  }

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <MapPin size={22} className="text-brand-400" /> GIS Map
      </h1>
      <p className="text-sm text-slate-500 mb-4">
        Real-world georeferenced view of every parcel, using its actual stored latitude/longitude —
        OpenStreetMap base layer.
      </p>

      {!loading && (
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          <button
            onClick={() => { setImportMode((v) => !v); if (importMode) resetImport() }}
            className={`ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${importMode ? 'bg-brand-500 text-ink-950' : 'card text-slate-300'}`}
          >
            <Square size={13} /> {importMode ? 'Close Import' : 'Import from OSM'}
          </button>
        </div>
      )}

      <div className="relative mb-4">
        <form onSubmit={handleSearch} className="flex gap-2">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setSearchError(null) }}
            placeholder="Search state, city, district, or address…"
            className="input-field flex-1 !py-2.5 text-sm"
          />
          <button type="submit" disabled={searching} className="btn-primary !py-2.5 px-4">
            {searching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
          </button>
        </form>

        {searchError && <p className="text-xs text-rose-400 mt-1.5">{searchError}</p>}

        {searchResults.length > 0 && (
          <div className="absolute z-[1000] mt-1.5 w-full card divide-y divide-white/5 max-h-64 overflow-y-auto">
            {searchResults.map((r, i) => (
              <button
                key={i}
                onClick={() => selectSearchResult(r)}
                className="w-full text-left px-3 py-2.5 text-xs text-slate-300 hover:bg-white/5"
              >
                {r.display_name}
              </button>
            ))}
          </div>
        )}
      </div>

      {importMode && (
        <div className="card p-4 mb-4 space-y-3">
          <p className="text-xs text-slate-500">
            Click "Draw Area" below, then click-drag directly on the map to select a real-world
            bounding box — pulls every building inside it into a new parcel, right
            alongside what's already on this map. Any size works: areas larger than ~25 sq km are
            automatically split into smaller tiles and fetched one at a time, so a whole city just
            takes longer than a single block.
          </p>

          <div className="flex items-center gap-1 bg-white/5 rounded-lg p-1 w-fit">
            <button
              onClick={() => { setImportSource('osm'); setPreview(null) }}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${importSource === 'osm' ? 'bg-brand-500 text-ink-950' : 'text-slate-400 hover:text-white'}`}
            >
              OSM (live)
            </button>
            <button
              onClick={() => { setImportSource('ms_footprints'); setPreview(null) }}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${importSource === 'ms_footprints' ? 'bg-brand-500 text-ink-950' : 'text-slate-400 hover:text-white'}`}
            >
              Microsoft Footprints (offline)
            </button>
          </div>
          <p className="text-[11px] text-slate-600 -mt-1">
            {importSource === 'osm'
              ? 'Live OpenStreetMap query -- coverage depends entirely on how much of this specific area volunteers have mapped. Dense in city centres like Connaught Place, often sparse or empty elsewhere.'
              : 'Reads a locally pre-loaded Microsoft Global ML Building Footprints file -- consistent AI-detected coverage anywhere, but only for areas you\'ve downloaded and loaded first via scripts/load_ms_footprints.py (no internet call at request time).'}
          </p>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setDrawing((d) => !d)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${drawing ? 'bg-brand-500 text-ink-950' : 'btn-secondary'}`}
            >
              <Square size={13} /> {drawing ? 'Click-drag to draw…' : 'Draw Area'}
            </button>
            {box && (
              <span className="text-[11px] text-slate-500 font-mono">
                SW: {box[0][0].toFixed(4)}, {box[0][1].toFixed(4)} — NE: {box[1][0].toFixed(4)}, {box[1][1].toFixed(4)}
              </span>
            )}
          </div>

          {box && (
            <div className="flex gap-2">
              <button onClick={handlePreview} disabled={previewLoading} className="btn-secondary text-sm flex-1">
                {previewLoading ? <Loader2 size={14} className="animate-spin" /> : 'Preview'}
              </button>
              <button onClick={handleCommit} disabled={!preview || importing} className="btn-primary text-sm flex-1">
                {importing ? <Loader2 size={14} className="animate-spin" /> : 'Import & View in 3D'}
              </button>
            </div>
          )}

          {previewError && (
            <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
              <AlertTriangle size={14} /> {previewError}
            </div>
          )}

          {preview && !job && (
            <div className="text-xs text-emerald-400 bg-emerald-500/5 border border-emerald-500/15 rounded-lg px-3 py-2.5">
              {preview.count} building{preview.count === 1 ? '' : 's'} found — shown as outlines on the map below.
              Click "Import & View in 3D" to bring them in.
            </div>
          )}

          {preview?.warning && (
            <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-500/5 border border-amber-500/15 rounded-lg px-3 py-2.5">
              <AlertTriangle size={14} /> {preview.warning}
            </div>
          )}

          {job && (
            <div className="bg-white/5 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2 text-xs">
                <span className="text-slate-400">
                  {job.status === 'fetching' && 'Accessing building records…'}
                  {job.status === 'processing' && 'Processing spatial topology & building models…'}
                  {job.status === 'done' && 'Import complete'}
                  {job.status === 'failed' && 'Import failed'}
                  {job.status === 'pending' && 'Starting…'}
                </span>
                <span className="text-slate-500">{job.processed_buildings ?? 0} / {job.total_buildings ?? '…'}</span>
              </div>
              <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                <div className="h-full bg-brand-500 transition-all duration-300" style={{ width: `${importProgressPct}%` }} />
              </div>
              {job.status === 'failed' && <p className="text-xs text-rose-400 mt-3">{job.error_message}</p>}
              {job.status === 'done' && job.error_message && (
                <p className="text-xs text-amber-400 mt-3 flex items-center gap-1.5"><AlertTriangle size={12} /> {job.error_message}</p>
              )}
              {job.status === 'done' && (
                <div className="mt-3 pt-3 border-t border-white/5">
                  <div className="flex items-center gap-1.5 text-xs text-brand-400 mb-1">
                    <CheckCircle2 size={13} /> {job.total_buildings} buildings imported — now showing as markers on this map
                  </div>
                  {job.flagged_buildings > 0 && (
                    <div className="flex items-center gap-1.5 text-xs text-amber-400 mb-2">
                      <AlertTriangle size={13} /> {job.flagged_buildings} flagged for height/floor-count review
                    </div>
                  )}
                  <button onClick={() => navigate(`/bulk-viewer?jobId=${job.id}`)} className="text-xs text-brand-400 flex items-center gap-1 hover:underline">
                    View all imported buildings in 3D <ChevronRight size={13} />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}

      {!loading && withCoords.length === 0 && !importMode && (
        <div className="card p-4 mb-4 text-center text-xs text-slate-500">
          No parcels with coordinates yet — showing your loaded Microsoft Footprints coverage area (Ashoknagar/Guna, MP) by default. Search above to browse
          anywhere, create a parcel via Create Parcel / Building, or use "Import from OSM" to pull
          real buildings in from a map area.
        </div>
      )}

      {!loading && (
        <div className="card overflow-hidden" style={{ height: '65vh' }}>
          <MapContainer center={defaultCenter} zoom={defaultZoom} style={{ height: '100%', width: '100%' }}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {flyTo && <FlyToCenter center={flyTo} />}
            {importMode && (
              <>
                <DragToggle drawing={drawing} />
                <DrawBoxLayer drawing={drawing} onBoxChange={(b) => { setBox(b); setDrawing(false); setPreview(null); setJob(null) }} />
                {box && <Rectangle bounds={box} pathOptions={{ color: '#3ECF8E', weight: 2, fillOpacity: 0.1 }} />}
                {preview?.buildings?.map((b) => (
                  <Polygon
                    key={b.osm_id}
                    positions={b.geometry}
                    pathOptions={{ color: '#F5A524', weight: 1.5, fillColor: '#F5A524', fillOpacity: 0.35 }}
                  >
                    <Popup>
                      <div className="text-xs">
                        <div className="font-semibold mb-1">{b.name || `OSM way ${b.osm_id}`}</div>
                        {b.address && <div className="text-slate-600 mb-1">{b.address}</div>}
                        <div className="text-slate-600">
                          {b.num_floors != null ? `${b.num_floors} floor${b.num_floors === 1 ? '' : 's'}${b.floors_estimated ? ' (estimated)' : ''}` : 'Floor count unknown'}
                          {b.height_m != null && ` · ${b.height_m}m`}
                        </div>
                      </div>
                    </Popup>
                  </Polygon>
                ))}
              </>
            )}
          </MapContainer>
        </div>
      )}

      {!loading && withCoords.length > 0 && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
          {withCoords.map((p) => (
            <div key={p.id} className="card p-4">
              <div className="flex items-start justify-between gap-2 mb-1">
                <div className="font-mono text-xs text-white">{p.ulpin_2d}</div>
                {isAdmin && (
                  <button
                    onClick={() => handleDeleteParcel(p)}
                    disabled={deletingId === p.id}
                    title="Delete this parcel and everything under it"
                    className="text-slate-600 hover:text-rose-400 transition-colors flex-shrink-0"
                  >
                    {deletingId === p.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                  </button>
                )}
              </div>
              <div className="text-xs text-slate-500 mb-2 truncate">
                {p.address || <span className="italic text-slate-600">No address on record</span>}
              </div>
              <div className="text-[11px] text-slate-600 mb-2">{p.centroid_lat.toFixed(4)}, {p.centroid_lon.toFixed(4)} · {p.buildings?.length || 0} building(s)</div>
              <button
                onClick={() => navigate(`/admin/viewer?focus=parcel:${p.id}`)}
                className="text-[11px] text-brand-400 hover:underline flex items-center gap-1"
              >
                Full details (height, floors, units) <ExternalLink size={11} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
