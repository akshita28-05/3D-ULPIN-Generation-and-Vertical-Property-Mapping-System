import { useState, useEffect } from 'react'
import api from '../../api/client'
import FootprintDetector from '../../components/FootprintDetector'
import {
  UploadCloud, Loader2, CheckCircle2, XCircle, PlayCircle,
  FileStack, ChevronRight, ScanSearch,
} from 'lucide-react'

const DATASET_TYPES = [
  { value: 'gis_parcel', label: 'GIS Parcel Data' },
  { value: 'floor_plan', label: 'Building / Floor Plan' },
  { value: 'drone_imagery', label: 'Drone Imagery' },
  { value: 'point_cloud', label: 'LiDAR / Point Cloud' },
  { value: 'dem', label: 'DEM' },
  { value: 'dsm', label: 'DSM' },
  { value: 'underground', label: 'Underground Utility Data' },
]

const STAGE_LABELS = [
  'uploading', 'preprocessing', 'building_extraction', 'floor_segmentation',
  'vertical_delineation', 'reconstruction_3d', 'ulpin_generation', 'topology_validation', 'ready_for_review',
]

export default function Ingestion() {
  const [datasetType, setDatasetType] = useState('gis_parcel')
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const [datasets, setDatasets] = useState([])

  const [buildings, setBuildings] = useState([])
  const [selectedBuilding, setSelectedBuilding] = useState('')
  const [job, setJob] = useState(null)
  const [processing, setProcessing] = useState(false)

  useEffect(() => {
    api.get('/datasets').then((res) => setDatasets(res.data)).catch(() => {})
    api.get('/parcels', { params: { limit: 5000 } }).then((res) => {
      const allBuildings = res.data.flatMap((p) => p.buildings.map((b) => ({ ...b, parcelUlpin: p.ulpin_2d })))
      setBuildings(allBuildings)
      if (allBuildings.length) setSelectedBuilding(allBuildings[0].id)
    }).catch(() => {})
  }, [])

  async function handleUpload(e) {
    e.preventDefault()
    if (!file) return
    setUploading(true)
    setUploadError(null)
    setUploadResult(null)
    try {
      const formData = new FormData()
      formData.append('dataset_type', datasetType)
      formData.append('file', file)
      const { data } = await api.post('/datasets/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
      setUploadResult(data)
      const list = await api.get('/datasets')
      setDatasets(list.data)
    } catch (err) {
      setUploadError(err.response?.data?.detail || 'Upload failed. Check file type and size.')
    } finally {
      setUploading(false)
    }
  }

  async function handleGenerate() {
    if (!selectedBuilding) return
    setProcessing(true)
    setJob(null)
    try {
      const { data: startedJob } = await api.post('/processing/start', { building_id: selectedBuilding })
      setJob(startedJob)

      let attempts = 0
      const poll = setInterval(async () => {
        attempts += 1
        try {
          const { data: polledJob } = await api.get(`/processing/jobs/${startedJob.id}`)
          setJob(polledJob)
          if (polledJob.progress_pct >= 100 || polledJob.stage === 'failed' || attempts > 60) {
            clearInterval(poll)
            setProcessing(false)
          }
        } catch {
          clearInterval(poll)
          setProcessing(false)
        }
      }, 500)
    } catch (err) {
      setJob({ error: err.response?.data?.detail || 'Processing failed to start.' })
      setProcessing(false)
    }
  }

  const log = job?.log ? JSON.parse(job.log) : []

  return (
    <div className="animate-fade-in space-y-8">
      <div>
        <h1 className="font-display text-2xl font-bold text-white mb-1">Data Ingestion & Processing</h1>
        <p className="text-sm text-slate-500">Upload source datasets and run the 3D ULPIN generation pipeline.</p>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="card p-6">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><UploadCloud size={16} /> Upload Dataset</h2>
          <form onSubmit={handleUpload} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2">Dataset Type</label>
              <select value={datasetType} onChange={(e) => setDatasetType(e.target.value)} className="input-field">
                {DATASET_TYPES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2">File</label>
              <input
                type="file" onChange={(e) => setFile(e.target.files[0])}
                accept=".geojson,.csv,.tif,.tiff,.las,.laz,.json,.png,.jpg,.jpeg,.pdf"
                className="block w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-brand-500/15 file:text-brand-400 file:text-xs file:font-medium hover:file:bg-brand-500/25"
              />
              <p className="text-[11px] text-slate-600 mt-1.5">GeoJSON, CSV, GeoTIFF, LAS/LAZ, JSON, PNG/JPG, PDF — max 50MB</p>
            </div>

            {uploadError && (
              <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
                <XCircle size={14} /> {uploadError}
              </div>
            )}
            {uploadResult && (
              <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/5 border border-emerald-500/15 rounded-lg px-3 py-2.5">
                <CheckCircle2 size={14} /> Uploaded {uploadResult.filename} ({(uploadResult.size_bytes / 1024).toFixed(1)} KB)
              </div>
            )}

            <button type="submit" disabled={!file || uploading} className="btn-primary w-full">
              {uploading ? <Loader2 className="animate-spin" size={16} /> : 'Upload Dataset'}
            </button>
          </form>

          {datasets.length > 0 && (
            <div className="mt-6 pt-6 border-t border-white/5">
              <h3 className="text-xs font-semibold text-slate-400 mb-3 flex items-center gap-1.5"><FileStack size={13} /> Recent Uploads</h3>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {datasets.slice(0, 6).map((d) => (
                  <div key={d.id} className="flex items-center justify-between text-xs bg-white/5 rounded-lg px-3 py-2">
                    <span className="text-slate-300 truncate">{d.filename}</span>
                    <span className="text-slate-500 flex-shrink-0 ml-2">{d.dataset_type}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="card p-6">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><PlayCircle size={16} /> Generate 3D ULPINs</h2>

          <label className="block text-xs font-medium text-slate-400 mb-2">Target Building</label>
          <select value={selectedBuilding} onChange={(e) => setSelectedBuilding(e.target.value)} className="input-field mb-4">
            {buildings.map((b) => (
              <option key={b.id} value={b.id}>{b.name || b.building_code} — {b.parcelUlpin}</option>
            ))}
          </select>

          <button onClick={handleGenerate} disabled={processing || !selectedBuilding} className="btn-primary w-full mb-6">
            {processing ? <Loader2 className="animate-spin" size={16} /> : 'Generate 3D ULPINs'}
          </button>

          {job?.error && (
            <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
              <XCircle size={14} /> {job.error}
            </div>
          )}

          {job && !job.error && (
            <div className="space-y-2 animate-fade-in">
              {STAGE_LABELS.map((stage) => {
                const entry = log.find((l) => l.stage === stage)
                const done = !!entry
                return (
                  <div key={stage} className="flex items-center gap-3 text-xs py-1.5">
                    {done ? <CheckCircle2 size={15} className="text-emerald-400 flex-shrink-0" /> : <div className="w-[15px] h-[15px] rounded-full border border-slate-700 flex-shrink-0" />}
                    <span className={done ? 'text-white' : 'text-slate-600'}>{stage.replace(/_/g, ' ')}</span>
                    {done && <span className="text-slate-500 ml-auto truncate max-w-[45%]">{entry.message}</span>}
                  </div>
                )
              })}
              {job.progress_pct === 100 && (
                <div className="mt-4 pt-4 border-t border-white/5 text-xs text-brand-400 flex items-center gap-1.5">
                  <ChevronRight size={13} /> Units queued in the Review Queue for verification.
                </div>
              )}
            </div>
          )}

          {!job && (
            <p className="text-xs text-slate-600 leading-relaxed">
              This runs the real backend pipeline: building extraction → floor segmentation →
              vertical delineation → 3D reconstruction → ULPIN generation → topology validation.
              Geometric derivation stands in for trained deep-learning models in this prototype —
              see the architecture notes for how a real model would plug in.
            </p>
          )}
        </div>
      </div>

      <div>
        <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <ScanSearch size={16} /> AI Footprint Detection (YOLOv8-seg)
        </h2>
        {selectedBuilding ? (
          <FootprintDetector
            key={selectedBuilding}
            buildingId={selectedBuilding}
            currentNumFloors={buildings.find((b) => b.id === selectedBuilding)?.num_floors}
            currentHeightM={buildings.find((b) => b.id === selectedBuilding)?.height_m}
            onFootprintSaved={() => {
              api.get('/parcels', { params: { limit: 5000 } }).then((res) => {
                const allBuildings = res.data.flatMap((p) => p.buildings.map((b) => ({ ...b, parcelUlpin: p.ulpin_2d })))
                setBuildings(allBuildings)
              }).catch(() => {})
            }}
          />
        ) : (
          <div className="card p-8 text-center text-sm text-slate-500">
            Create a parcel/building first (via Create Parcel / Building, or bulk-import a real area
            from the GIS Map page) — this panel runs AI footprint detection against a specific building's
            uploaded drone imagery.
          </div>
        )}
      </div>
    </div>
  )
}
