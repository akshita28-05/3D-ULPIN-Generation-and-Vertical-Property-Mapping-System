import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../api/client'
import { Loader2, Cable, Plane, Plus, X, CheckCircle2, ScanSearch, Radar, Globe2 } from 'lucide-react'

const ASSET_COLORS = {
  water: 'text-sky-400 bg-sky-500/10 border-sky-500/20',
  electricity: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  sewer: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
  telecom: 'text-violet-400 bg-violet-500/10 border-violet-500/20',
  gas: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
  metro_tunnel: 'text-slate-400 bg-slate-500/10 border-slate-500/20',
  manhole: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  valve_box: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
  utility_chamber: 'text-fuchsia-400 bg-fuchsia-500/10 border-fuchsia-500/20',
  fire_hydrant: 'text-red-400 bg-red-500/10 border-red-500/20',
  transformer: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
}

export default function Underground() {
  const [parcels, setParcels] = useState([])
  const [assets, setAssets] = useState([])
  const [corridors, setCorridors] = useState([])
  const [loading, setLoading] = useState(true)
  const [assetPanel, setAssetPanel] = useState(null)
  const [showCorridorForm, setShowCorridorForm] = useState(false)
  const [detecting, setDetecting] = useState(false)
  const [detectMsg, setDetectMsg] = useState(null)

  async function detectFromOpenData() {
    setDetecting(true)
    setDetectMsg(null)
    try {
      const lats = parcels.map((p) => p.centroid_lat).filter((v) => v != null)
      const lons = parcels.map((p) => p.centroid_lon).filter((v) => v != null)
      const pad = 0.003
      const { data } = await api.post('/infra/link', {
        south: Math.min(...lats) - pad, north: Math.max(...lats) + pad,
        west: Math.min(...lons) - pad, east: Math.max(...lons) + pad,
      }, { timeout: 180000 })
      const n = data.linked
      const scan = data.scan
      if (scan.status === 'zoom_in') setDetectMsg({ ok: false, text: 'Your parcels cover too large an area for one scan. Use the GIS Map: zoom in and press Auto-map.' })
      else if (scan.status === 'unavailable') setDetectMsg({ ok: false, text: `Open data is unreachable right now (${scan.message || 'no answer'}). Try again shortly.` })
      else setDetectMsg({ ok: true, text: `Attached ${n.underground} underground structure(s) and ${n.air} air-rights corridor(s) to ${n.parcels} parcel(s), from OpenStreetMap.` })
      reload()
    } catch (err) {
      setDetectMsg({ ok: false, text: err.response?.data?.detail || 'Could not run the scan.' })
    } finally {
      setDetecting(false)
    }
  }

  function reload() {
    setLoading(true)
    Promise.all([api.get('/parcels', { params: { limit: 5000 } }), api.get('/underground-assets'), api.get('/air-rights')])
      .then(([p, a, c]) => { setParcels(p.data); setAssets(a.data); setCorridors(c.data) })
      .finally(() => setLoading(false))
  }

  useEffect(() => { reload() }, [])

  function parcelLabel(parcelId) {
    const p = parcels.find((x) => x.id === parcelId)
    return p ? p.ulpin_2d : parcelId
  }

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>

  if (parcels.length === 0) {
    return (
      <div className="animate-fade-in card p-12 text-center">
        <Cable className="mx-auto text-slate-700 mb-3" size={32} />
        <p className="text-sm text-slate-500 mb-4">No parcels exist yet — create one first before adding underground or air-rights assets.</p>
        <Link to="/admin/create" className="btn-primary text-sm inline-flex">Create a Parcel</Link>
      </div>
    )
  }

  return (
    <div className="animate-fade-in space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
            <Cable size={22} className="text-brand-400" /> Underground & Air-Rights Assets
          </h1>
          <p className="text-sm text-slate-500">Registered subsurface utilities and elevated corridors, checked against building geometry.</p>
        </div>
      </div>

      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <h2 className="text-sm font-semibold text-slate-300">Underground Utilities</h2>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setAssetPanel(assetPanel === 'manual' ? null : 'manual')} className="btn-secondary !py-1.5 text-xs">
              {assetPanel === 'manual' ? <><X size={13} /> Cancel</> : <><Plus size={13} /> Add Asset</>}
            </button>
            <button onClick={() => setAssetPanel(assetPanel === 'surface' ? null : 'surface')} className="btn-secondary !py-1.5 text-xs">
              {assetPanel === 'surface' ? <><X size={13} /> Cancel</> : <><ScanSearch size={13} /> Auto-Detect (Photo)</>}
            </button>
            <button onClick={() => setAssetPanel(assetPanel === 'gpr' ? null : 'gpr')} className="btn-secondary !py-1.5 text-xs">
              {assetPanel === 'gpr' ? <><X size={13} /> Cancel</> : <><Radar size={13} /> GPR Survey</>}
            </button>
          </div>
        </div>

        <div className="card p-3 mb-3 flex flex-wrap items-center gap-3">
          <Globe2 size={16} className="text-brand-400 shrink-0" />
          <p className="text-xs text-slate-400 flex-1 min-w-[220px] leading-snug">
            <span className="text-slate-200 font-medium">Automatic — no sensor, no form.</span> Reads OpenStreetMap for metro and road tunnels, basements,
            underground parking, buried cables, viaducts, flyovers and overhead power lines, and attaches what crosses your parcels.
            Depths and heights are typical values unless OpenStreetMap gives them, and are marked as such.
          </p>
          <button onClick={detectFromOpenData} disabled={detecting} className="btn-secondary !py-1.5 text-xs">
            {detecting ? <><Loader2 size={13} className="animate-spin" /> Scanning…</> : <><Globe2 size={13} /> Detect from open data</>}
          </button>
          {detectMsg && <p className={`basis-full text-xs ${detectMsg.ok ? 'text-emerald-400' : 'text-amber-400'}`}>{detectMsg.text}</p>}
        </div>

        {assetPanel === 'manual' && <AssetForm parcels={parcels} onCreated={() => { setAssetPanel(null); reload() }} />}
        {assetPanel === 'surface' && <SurfaceAssetDetectPanel parcels={parcels} onCreated={reload} />}
        {assetPanel === 'gpr' && <GprSurveyPanel parcels={parcels} onCreated={reload} />}

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-3">
          {assets.map((a) => (
            <div key={a.id} className="card p-4">
              <span className={`badge border capitalize mb-3 ${ASSET_COLORS[a.asset_type] || 'text-slate-400 bg-slate-500/10 border-slate-500/20'}`}>
                {a.asset_type.replace(/_/g, ' ')}
              </span>
              {a.source === 'osm_auto' && <span className="badge border ml-1.5 mb-3 text-sky-400 bg-sky-500/10 border-sky-500/20">open data</span>}
              <div className="text-xs text-slate-500">Depth below ground</div>
              <div className="text-sm text-white font-medium mb-2">{Math.abs(a.depth_min_m)}m to {Math.abs(a.depth_max_m)}m</div>
              <div className="text-[11px] text-slate-600">Parcel: {parcelLabel(a.parcel_id)}</div>
            </div>
          ))}
          {assets.length === 0 && <p className="text-sm text-slate-600 col-span-full">No underground assets yet. Press “Detect from open data” — nothing has to be entered by hand.</p>}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-1.5"><Plane size={14} /> Air-Rights Corridors</h2>
          <button onClick={() => setShowCorridorForm(!showCorridorForm)} className="btn-secondary !py-1.5 text-xs">
            {showCorridorForm ? <><X size={13} /> Cancel</> : <><Plus size={13} /> Add Corridor</>}
          </button>
        </div>

        {showCorridorForm && <CorridorForm parcels={parcels} onCreated={() => { setShowCorridorForm(false); reload() }} />}

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-3">
          {corridors.map((c) => (
            <div key={c.id} className="card p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="badge border capitalize text-violet-400 bg-violet-500/10 border-violet-500/20">{c.corridor_type}</span>
                <span className={`badge border capitalize ${
                  c.conflict_status === 'confirmed' ? 'text-rose-400 bg-rose-500/10 border-rose-500/20' :
                  c.conflict_status === 'potential' ? 'text-amber-400 bg-amber-500/10 border-amber-500/20' :
                  'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
                }`}>
                  {c.conflict_status}
                </span>
              </div>
              <div className="text-xs text-slate-500">Height range</div>
              <div className="text-sm text-white font-medium mb-2">{c.height_min_m}m to {c.height_max_m}m</div>
              <div className="text-[11px] text-slate-600">Parcel: {parcelLabel(c.parcel_id)}</div>
            </div>
          ))}
          {corridors.length === 0 && <p className="text-sm text-slate-600 col-span-full">No air-rights corridors yet. “Detect from open data” finds elevated metro, flyovers and power-line corridors automatically.</p>}
        </div>
      </div>
    </div>
  )
}

function AssetForm({ parcels, onCreated }) {
  const [form, setForm] = useState({
    parcel_id: parcels[0]?.id || '', asset_type: 'water', depth_min: '', depth_max: '',
    x0: '5', y0: '5', x1: '25', y1: '7',
  })
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    const geom = [[+form.x0, +form.y0], [+form.x1, +form.y0], [+form.x1, +form.y1], [+form.x0, +form.y1], [+form.x0, +form.y0]]
    const depthMin = parseFloat(form.depth_min)
    const depthMax = parseFloat(form.depth_max)
    if (depthMin < 0 || depthMax < 0) {
      setError('Enter depths as positive metres below ground (0 = surface, larger = deeper).')
      return
    }
    if (depthMin >= depthMax) {
      setError('Depth Min must be less than Depth Max (Min is the shallower end).')
      return
    }
    setSubmitting(true)
    try {
      await api.post('/underground-assets', {
        parcel_id: form.parcel_id, asset_type: form.asset_type,
        depth_min_m: depthMin, depth_max_m: depthMax,
        geometry_geojson: JSON.stringify(geom),
      })
      onCreated()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create asset.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-4 mb-3 space-y-3">
      {error && <div className="text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2">{error}</div>}
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Parcel</label>
          <select value={form.parcel_id} onChange={(e) => set('parcel_id', e.target.value)} className="input-field !py-2 text-xs">
            {parcels.map((p) => <option key={p.id} value={p.id}>{p.ulpin_2d}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Asset Type</label>
          <select value={form.asset_type} onChange={(e) => set('asset_type', e.target.value)} className="input-field !py-2 text-xs">
            <option value="water">Water</option>
            <option value="electricity">Electricity</option>
            <option value="sewer">Sewer</option>
            <option value="telecom">Telecom</option>
            <option value="gas">Gas</option>
            <option value="metro_tunnel">Metro Tunnel</option>
            <option value="other">Other</option>
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Depth Min — shallower end (m below ground, e.g. 1.5)</label>
          <input type="number" min="0" step="0.1" value={form.depth_min} onChange={(e) => set('depth_min', e.target.value)} className="input-field !py-2 text-xs" required />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Depth Max — deeper end (m below ground, e.g. 3)</label>
          <input type="number" min="0" step="0.1" value={form.depth_max} onChange={(e) => set('depth_max', e.target.value)} className="input-field !py-2 text-xs" required />
        </div>
      </div>
      <button type="submit" disabled={submitting} className="btn-primary w-full !py-2 text-xs">
        {submitting ? <Loader2 size={14} className="animate-spin" /> : 'Create Underground Asset'}
      </button>
    </form>
  )
}

function CorridorForm({ parcels, onCreated }) {
  const [form, setForm] = useState({
    parcel_id: parcels[0]?.id || '', corridor_type: 'metro', height_min: '', height_max: '', conflict_status: 'none',
    x0: '0', y0: '8', x1: '35', y1: '10',
  })
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    const geom = [[+form.x0, +form.y0], [+form.x1, +form.y0], [+form.x1, +form.y1], [+form.x0, +form.y1], [+form.x0, +form.y0]]
    setSubmitting(true)
    try {
      await api.post('/air-rights', {
        parcel_id: form.parcel_id, corridor_type: form.corridor_type,
        height_min_m: parseFloat(form.height_min), height_max_m: parseFloat(form.height_max),
        geometry_geojson: JSON.stringify(geom), conflict_status: form.conflict_status,
      })
      onCreated()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create corridor.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-4 mb-3 space-y-3">
      {error && <div className="text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2">{error}</div>}
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Parcel</label>
          <select value={form.parcel_id} onChange={(e) => set('parcel_id', e.target.value)} className="input-field !py-2 text-xs">
            {parcels.map((p) => <option key={p.id} value={p.id}>{p.ulpin_2d}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Corridor Type</label>
          <select value={form.corridor_type} onChange={(e) => set('corridor_type', e.target.value)} className="input-field !py-2 text-xs">
            <option value="metro">Metro</option>
            <option value="flyover">Flyover</option>
            <option value="elevated_transport">Elevated Transport</option>
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Height Min (m)</label>
          <input type="number" step="0.1" value={form.height_min} onChange={(e) => set('height_min', e.target.value)} className="input-field !py-2 text-xs" required />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Height Max (m)</label>
          <input type="number" step="0.1" value={form.height_max} onChange={(e) => set('height_max', e.target.value)} className="input-field !py-2 text-xs" required />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Conflict Status</label>
        <select value={form.conflict_status} onChange={(e) => set('conflict_status', e.target.value)} className="input-field !py-2 text-xs">
          <option value="none">None</option>
          <option value="potential">Potential</option>
          <option value="confirmed">Confirmed</option>
        </select>
      </div>
      <button type="submit" disabled={submitting} className="btn-primary w-full !py-2 text-xs">
        {submitting ? <Loader2 size={14} className="animate-spin" /> : 'Create Air-Rights Corridor'}
      </button>
    </form>
  )
}

function SurfaceAssetDetectPanel({ parcels, onCreated }) {
  const [parcelId, setParcelId] = useState(parcels[0]?.id || '')
  const [imagePath, setImagePath] = useState('')
  const [originX, setOriginX] = useState('0')
  const [originY, setOriginY] = useState('0')
  const [detecting, setDetecting] = useState(false)
  const [detections, setDetections] = useState(null)
  const [error, setError] = useState(null)
  const [savingIndex, setSavingIndex] = useState(null)
  const [savedIndices, setSavedIndices] = useState(new Set())

  const parcel = parcels.find((p) => p.id === parcelId)
  const imageOptions = (parcel?.buildings || []).filter((b) => b.drone_image_path)

  async function runDetection(e) {
    e.preventDefault()
    setError(null)
    setDetections(null)
    setSavedIndices(new Set())
    setDetecting(true)
    try {
      const { data } = await api.post('/underground/detect-surface-assets', {
        image_path: imagePath, origin_x: parseFloat(originX) || 0, origin_y: parseFloat(originY) || 0,
      })
      if (data.detections === null) {
        setError('AI_MODELS_ENABLED/SURFACE_ASSET_MODEL_ENABLED is false, or weights/image are unavailable on the server. Detection did not run.')
      } else {
        setDetections(data.detections)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Detection failed.')
    } finally {
      setDetecting(false)
    }
  }

  async function saveDetection(det, idx) {
    setSavingIndex(idx)
    setError(null)
    try {
      const half = 0.3
      const geom = [
        [det.x - half, det.y - half], [det.x + half, det.y - half],
        [det.x + half, det.y + half], [det.x - half, det.y + half], [det.x - half, det.y - half],
      ]
      await api.post('/underground-assets', {
        parcel_id: parcelId, asset_type: det.asset_type,
        depth_min_m: 0, depth_max_m: 0.3,
        geometry_geojson: JSON.stringify(geom),
      })
      setSavedIndices((prev) => new Set(prev).add(idx))
      onCreated()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save this detection.')
    } finally {
      setSavingIndex(null)
    }
  }

  return (
    <div className="card p-4 mb-3 space-y-3">
      <p className="text-xs text-slate-500 leading-relaxed">
        Runs the surface-asset AI model (manholes / valve boxes / chambers / hydrants / transformers) on
        a drone orthophoto already uploaded for a building. Requires <code>SURFACE_ASSET_MODEL_ENABLED=true</code> and
        <code> SURFACE_ASSET_WEIGHTS_PATH</code> set on the server — if those aren't configured, this
        returns a clear error rather than a fake result.
      </p>
      {error && <div className="text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2">{error}</div>}
      <form onSubmit={runDetection} className="space-y-3">
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Parcel</label>
            <select
              value={parcelId}
              onChange={(e) => { setParcelId(e.target.value); setImagePath(''); setDetections(null) }}
              className="input-field !py-2 text-xs"
            >
              {parcels.map((p) => <option key={p.id} value={p.id}>{p.ulpin_2d}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Drone Image</label>
            {imageOptions.length > 0 ? (
              <select value={imagePath} onChange={(e) => setImagePath(e.target.value)} className="input-field !py-2 text-xs">
                <option value="">Select an uploaded building image…</option>
                {imageOptions.map((b) => (
                  <option key={b.id} value={b.drone_image_path}>{b.building_code} — {b.drone_image_path.split('/').pop()}</option>
                ))}
              </select>
            ) : (
              <input
                value={imagePath} onChange={(e) => setImagePath(e.target.value)}
                placeholder="No uploaded images for this parcel — paste an image path"
                className="input-field !py-2 text-xs"
              />
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Origin X (m) — local coordinate origin of the image</label>
            <input type="number" step="0.1" value={originX} onChange={(e) => setOriginX(e.target.value)} className="input-field !py-2 text-xs" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Origin Y (m)</label>
            <input type="number" step="0.1" value={originY} onChange={(e) => setOriginY(e.target.value)} className="input-field !py-2 text-xs" />
          </div>
        </div>
        <button type="submit" disabled={detecting || !imagePath} className="btn-primary w-full !py-2 text-xs">
          {detecting ? <Loader2 size={14} className="animate-spin" /> : <><ScanSearch size={14} /> Run Surface Asset Detection</>}
        </button>
      </form>

      {detections !== null && (
        <div className="pt-3 border-t border-white/5">
          {detections.length === 0 ? (
            <p className="text-xs text-slate-500">Model ran successfully but found no surface assets in this image.</p>
          ) : (
            <>
              <div className="text-xs text-slate-400 mb-2">{detections.length} detection(s) — review and save the ones you want to keep:</div>
              <div className="space-y-2">
                {detections.map((det, idx) => (
                  <div key={idx} className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
                    <div>
                      <span className={`badge border capitalize mr-2 ${ASSET_COLORS[det.asset_type] || 'text-slate-400 bg-slate-500/10 border-slate-500/20'}`}>
                        {det.asset_type.replace('_', ' ')}
                      </span>
                      <span className="text-[11px] text-slate-500">
                        x={det.x}m, y={det.y}m · {(det.confidence * 100).toFixed(0)}% confidence
                      </span>
                    </div>
                    {savedIndices.has(idx) ? (
                      <span className="flex items-center gap-1 text-xs text-emerald-400 flex-shrink-0"><CheckCircle2 size={13} /> Saved</span>
                    ) : (
                      <button
                        onClick={() => saveDetection(det, idx)}
                        disabled={savingIndex === idx}
                        className="btn-secondary !py-1 !px-2.5 text-[11px] flex-shrink-0"
                      >
                        {savingIndex === idx ? <Loader2 size={12} className="animate-spin" /> : 'Save as Asset'}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function GprSurveyPanel({ parcels, onCreated }) {
  const [parcelId, setParcelId] = useState(parcels[0]?.id || '')
  const [utilityType, setUtilityType] = useState('water')
  const [scanForm, setScanForm] = useState({
    bscan_image_path: '', image_width_px: '800', image_height_px: '400',
    start_lat: '', start_lon: '', end_lat: '', end_lon: '',
    origin_lat: '', origin_lon: '', time_window_ns: '50', dielectric_constant: '',
  })
  const [points, setPoints] = useState([])
  const [scanLinesRun, setScanLinesRun] = useState(0)
  const [detecting, setDetecting] = useState(false)
  const [fusing, setFusing] = useState(false)
  const [error, setError] = useState(null)
  const [fuseResult, setFuseResult] = useState(null)

  function setScan(k, v) { setScanForm((f) => ({ ...f, [k]: v })) }

  async function runScanLine(e) {
    e.preventDefault()
    setError(null)
    setFuseResult(null)
    setDetecting(true)
    try {
      const scan_line = {
        start_lat: parseFloat(scanForm.start_lat), start_lon: parseFloat(scanForm.start_lon),
        end_lat: parseFloat(scanForm.end_lat), end_lon: parseFloat(scanForm.end_lon),
        time_window_ns: parseFloat(scanForm.time_window_ns),
        origin_lat: parseFloat(scanForm.origin_lat), origin_lon: parseFloat(scanForm.origin_lon),
        ...(scanForm.dielectric_constant ? { dielectric_constant: parseFloat(scanForm.dielectric_constant) } : {}),
      }
      const { data } = await api.post('/underground/detect-gpr', {
        bscan_image_path: scanForm.bscan_image_path,
        scan_line,
        image_width_px: parseInt(scanForm.image_width_px, 10),
        image_height_px: parseInt(scanForm.image_height_px, 10),
      })
      if (data.detections === null) {
        setError('GPR_MODEL_ENABLED is false, or weights/image are unavailable on the server. Detection did not run.')
      } else {
        setPoints((prev) => [...prev, ...data.detections])
        setScanLinesRun((n) => n + 1)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'GPR detection failed on this scan line.')
    } finally {
      setDetecting(false)
    }
  }

  async function fuseAndSave() {
    setError(null)
    setFusing(true)
    try {
      const { data } = await api.post('/underground/fuse', {
        parcel_id: parcelId, utility_type: utilityType, gpr_points: points,
      })
      setFuseResult(data)
      setPoints([])
      setScanLinesRun(0)
      onCreated()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not fuse and save the survey.')
    } finally {
      setFusing(false)
    }
  }

  return (
    <div className="card p-4 mb-3 space-y-4">
      <p className="text-xs text-slate-500 leading-relaxed">
        Real GPR (Ground Penetrating Radar) buried-pipe/cable detection — needs actual B-scan radargram
        images from GPR survey hardware, not a drone photo. Requires <code>GPR_MODEL_ENABLED=true</code> and
        <code> GPR_HYPERBOLA_WEIGHTS_PATH</code> set on the server. Run one scan line at a time to
        accumulate detection points, then fuse them into saved underground assets.
      </p>
      {error && <div className="text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2">{error}</div>}

      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Parcel</label>
          <select value={parcelId} onChange={(e) => setParcelId(e.target.value)} className="input-field !py-2 text-xs">
            {parcels.map((p) => <option key={p.id} value={p.id}>{p.ulpin_2d}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Utility Type (what this survey is looking for)</label>
          <select value={utilityType} onChange={(e) => setUtilityType(e.target.value)} className="input-field !py-2 text-xs">
            <option value="water">Water</option>
            <option value="electricity">Electricity</option>
            <option value="sewer">Sewer</option>
            <option value="telecom">Telecom</option>
            <option value="gas">Gas</option>
          </select>
        </div>
      </div>

      <form onSubmit={runScanLine} className="space-y-3 pt-3 border-t border-white/5">
        <div className="text-xs font-semibold text-slate-300">Add a Scan Line</div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">B-Scan Image Path</label>
          <input
            value={scanForm.bscan_image_path} onChange={(e) => setScan('bscan_image_path', e.target.value)}
            placeholder="/uploads/gpr/line_01.png" className="input-field !py-2 text-xs" required
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Image Width (px)</label>
            <input type="number" value={scanForm.image_width_px} onChange={(e) => setScan('image_width_px', e.target.value)} className="input-field !py-2 text-xs" required />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Image Height (px)</label>
            <input type="number" value={scanForm.image_height_px} onChange={(e) => setScan('image_height_px', e.target.value)} className="input-field !py-2 text-xs" required />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Scan Start Lat / Lon</label>
            <div className="flex gap-2">
              <input type="number" step="0.000001" value={scanForm.start_lat} onChange={(e) => setScan('start_lat', e.target.value)} placeholder="Lat" className="input-field !py-2 text-xs" required />
              <input type="number" step="0.000001" value={scanForm.start_lon} onChange={(e) => setScan('start_lon', e.target.value)} placeholder="Lon" className="input-field !py-2 text-xs" required />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Scan End Lat / Lon</label>
            <div className="flex gap-2">
              <input type="number" step="0.000001" value={scanForm.end_lat} onChange={(e) => setScan('end_lat', e.target.value)} placeholder="Lat" className="input-field !py-2 text-xs" required />
              <input type="number" step="0.000001" value={scanForm.end_lon} onChange={(e) => setScan('end_lon', e.target.value)} placeholder="Lon" className="input-field !py-2 text-xs" required />
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Local Origin Lat / Lon</label>
            <div className="flex gap-2">
              <input type="number" step="0.000001" value={scanForm.origin_lat} onChange={(e) => setScan('origin_lat', e.target.value)} placeholder="Lat" className="input-field !py-2 text-xs" required />
              <input type="number" step="0.000001" value={scanForm.origin_lon} onChange={(e) => setScan('origin_lon', e.target.value)} placeholder="Lon" className="input-field !py-2 text-xs" required />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Time Window (ns) / Dielectric (optional)</label>
            <div className="flex gap-2">
              <input type="number" step="0.1" value={scanForm.time_window_ns} onChange={(e) => setScan('time_window_ns', e.target.value)} className="input-field !py-2 text-xs" required />
              <input type="number" step="0.1" value={scanForm.dielectric_constant} onChange={(e) => setScan('dielectric_constant', e.target.value)} placeholder="e.g. 9" className="input-field !py-2 text-xs" />
            </div>
          </div>
        </div>
        <button type="submit" disabled={detecting} className="btn-secondary w-full !py-2 text-xs">
          {detecting ? <Loader2 size={14} className="animate-spin" /> : <><Radar size={14} /> Detect on This Scan Line</>}
        </button>
      </form>

      <div className="pt-3 border-t border-white/5">
        <div className="text-xs text-slate-400 mb-2">
          {points.length} accumulated GPR detection point(s) across {scanLinesRun} scan line(s) run so far.
        </div>
        <button onClick={fuseAndSave} disabled={fusing || points.length < 3} className="btn-primary w-full !py-2 text-xs">
          {fusing ? <Loader2 size={14} className="animate-spin" /> : `Fuse ${points.length} Point(s) & Save as Underground Assets`}
        </button>
        {points.length > 0 && points.length < 3 && (
          <p className="text-[11px] text-slate-600 mt-1.5">Need at least 3 points to form a traceable utility run — run more scan lines.</p>
        )}
        {fuseResult && (
          <div className="mt-3 flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
            <CheckCircle2 size={13} /> Created {fuseResult.traces_created ?? fuseResult.assets_created ?? 'new'} underground asset(s) from this survey.
          </div>
        )}
      </div>
    </div>
  )
}
