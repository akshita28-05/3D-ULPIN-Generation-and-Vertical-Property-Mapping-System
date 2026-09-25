import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { MapContainer, TileLayer, Rectangle, useMapEvents, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import api from '../../api/client'
import { Loader2, MapPin, Search, Square, CheckCircle2, AlertTriangle, ChevronRight } from 'lucide-react'

const DEFAULT_CENTER = [22.80, 86.18]

export function FlyToCenter({ center }) {
  const map = useMap()
  useEffect(() => { if (center) map.flyTo(center, map.getZoom(), { duration: 0.6 }) }, [center])
  return null
}

export function DragToggle({ drawing }) {
  const map = useMap()
  useEffect(() => {
    if (drawing) {
      map.dragging.disable()
      map.doubleClickZoom.disable()
    } else {
      map.dragging.enable()
      map.doubleClickZoom.enable()
    }
  }, [drawing, map])
  return null
}

export function DrawBoxLayer({ drawing, onBoxChange }) {
  const startRef = useRef(null)
  const [liveBox, setLiveBox] = useState(null)

  useMapEvents({
    mousedown(e) {
      if (!drawing) return
      startRef.current = e.latlng
      setLiveBox(null);
    },
    mousemove(e) {
      if (!drawing || !startRef.current) return
      const a = startRef.current, b = e.latlng
      setLiveBox([[Math.min(a.lat, b.lat), Math.min(a.lng, b.lng)], [Math.max(a.lat, b.lat), Math.max(a.lng, b.lng)]])
    },
    mouseup(e) {
      if (!drawing || !startRef.current) return
      const a = startRef.current, b = e.latlng
      const box = [[Math.min(a.lat, b.lat), Math.min(a.lng, b.lng)], [Math.max(a.lat, b.lat), Math.max(a.lng, b.lng)]]
      startRef.current = null
      setLiveBox(null)
      onBoxChange(box)
    },
  })

  return liveBox ? <Rectangle bounds={liveBox} pathOptions={{ color: '#3ECF8E', weight: 2, fillOpacity: 0.08 }} /> : null
}

export default function BulkImportPanel() {
  const [drawing, setDrawing] = useState(false)
  const [box, setBox] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [mapCenter, setMapCenter] = useState(DEFAULT_CENTER)

  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState(null)

  const [job, setJob] = useState(null)
  const [importing, setImporting] = useState(false)
  const navigate = useNavigate()

  async function handleSearch(e) {
    e.preventDefault()
    if (searchQuery.trim().length < 3) return
    setSearching(true)
    try {
      const { data } = await api.get('/geocode/search', { params: { q: searchQuery } })
      if (data.length) {
        setMapCenter([data[0].lat, data[0].lon])
      }
    } finally {
      setSearching(false)
    }
  }

  async function handlePreview() {
    if (!box) return
    setPreviewLoading(true)
    setPreviewError(null)
    setPreview(null)
    try {
      const [[south, west], [north, east]] = box
      const { data } = await api.post('/bulk-import/preview', { south, west, north, east, search_query: searchQuery || null })
      setPreview(data)
    } catch (err) {
      setPreviewError(err.response?.data?.detail || 'Could not reach OSM Overpass -- check network connectivity and try again.')
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
      const { data: startedJob } = await api.post('/bulk-import/commit', { south, west, north, east, search_query: searchQuery || null })
      setJob(startedJob)

      const poll = setInterval(async () => {
        const { data: current } = await api.get(`/bulk-import/jobs/${startedJob.job_id}`)
        setJob(current)
        if (current.status === 'done' || current.status === 'failed') {
          clearInterval(poll)
          setImporting(false)
          if (current.status === 'done') {
            setTimeout(() => navigate(`/bulk-viewer?jobId=${current.id}`), 900)
          }
        }
      }, 1200)
    } catch {
      setImporting(false)
    }
  }

  const progressPct = job?.total_buildings ? Math.round((job.processed_buildings / job.total_buildings) * 100) : 0

  return (
    <div className="card p-6">
      <h2 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
        <MapPin size={16} /> Bulk Import from Map (OSM)
      </h2>
      <p className="text-xs text-slate-500 mb-4">
        Draw a bounding box to fetch every real OpenStreetMap building in that area — a separate,
        additive pipeline from the single-building upload above. No trained model is used here;
        this is a real Overpass API query plus deterministic ULPIN generation and an automated
        height/floor-count consistency check.
      </p>

      <form onSubmit={handleSearch} className="flex gap-2 mb-3">
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search city, place, or address…"
          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500/50"
        />
        <button type="submit" className="btn-secondary px-3" disabled={searching}>
          {searching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
        </button>
      </form>

      <div className="relative h-72 rounded-lg overflow-hidden border border-white/10 mb-3">
        <MapContainer center={mapCenter} zoom={15} style={{ height: '100%', width: '100%' }}>
          <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <DragToggle drawing={drawing} />
          <FlyToCenter center={mapCenter} />
          <DrawBoxLayer drawing={drawing} onBoxChange={(b) => { setBox(b); setDrawing(false); setPreview(null); setJob(null) }} />
          {box && <Rectangle bounds={box} pathOptions={{ color: '#3ECF8E', weight: 2, fillOpacity: 0.1 }} />}
        </MapContainer>
        <button
          onClick={() => setDrawing((d) => !d)}
          className={`absolute top-2 right-2 z-[1000] flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${drawing ? 'bg-brand-500 text-ink-950' : 'card text-slate-300'}`}
        >
          <Square size={13} /> {drawing ? 'Click-drag to draw…' : 'Draw Area'}
        </button>
      </div>

      {box && (
        <div className="text-[11px] text-slate-500 font-mono mb-3">
          SW: {box[0][0].toFixed(4)}, {box[0][1].toFixed(4)} — NE: {box[1][0].toFixed(4)}, {box[1][1].toFixed(4)}
        </div>
      )}

      <div className="flex gap-2 mb-4">
        <button onClick={handlePreview} disabled={!box || previewLoading} className="btn-secondary text-sm flex-1" >
          {previewLoading ? <Loader2 size={14} className="animate-spin" /> : 'Preview'}
        </button>
        <button onClick={handleCommit} disabled={!preview || importing} className="btn-primary text-sm flex-1">
          {importing ? <Loader2 size={14} className="animate-spin" /> : 'Next Step — Import & View in 3D'}
        </button>
      </div>

      {previewError && (
        <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5 mb-3">
          <AlertTriangle size={14} /> {previewError}
        </div>
      )}

      {preview && !job && (
        <div className="text-xs text-emerald-400 bg-emerald-500/5 border border-emerald-500/15 rounded-lg px-3 py-2.5 mb-3">
          {preview.count} building{preview.count === 1 ? '' : 's'} loaded. Click "Next Step" to import and view in 3D.
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
            <div className="h-full bg-brand-500 transition-all duration-300" style={{ width: `${progressPct}%` }} />
          </div>

          {job.status === 'failed' && (
            <p className="text-xs text-rose-400 mt-3">{job.error_message}</p>
          )}

          {job.status === 'done' && (
            <div className="mt-3 pt-3 border-t border-white/5">
              <div className="flex items-center gap-1.5 text-xs text-brand-400 mb-1">
                <CheckCircle2 size={13} /> {job.total_buildings} buildings imported
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
  )
}
