import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../api/client'
import { UploadCloud, Crosshair, Loader2, CheckCircle2, XCircle, RotateCcw } from 'lucide-react'

export default function FootprintDetector({ buildingId, currentNumFloors, currentHeightM, onFootprintSaved }) {
  const [dronePath, setDronePath] = useState(null)
  const [imageUrl, setImageUrl] = useState(null)
  const [naturalSize, setNaturalSize] = useState({ w: 0, h: 0 })
  const [displaySize, setDisplaySize] = useState({ w: 0, h: 0 })

  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)

  const [cropBox, setCropBox] = useState(null)
  const dragStart = useRef(null)

  const [detecting, setDetecting] = useState(false)
  const [detectError, setDetectError] = useState(null)
  const [candidates, setCandidates] = useState(null)
  const [aiModelsEnabled, setAiModelsEnabled] = useState(true)

  const [selecting, setSelecting] = useState(null)
  const [selectedIndex, setSelectedIndex] = useState(null)

  const [floorDetecting, setFloorDetecting] = useState(false)
  const [floorDetectError, setFloorDetectError] = useState(null)
  const [floorEstimate, setFloorEstimate] = useState(null)
  const [floorAiEnabled, setFloorAiEnabled] = useState(true)
  const [floorSelecting, setFloorSelecting] = useState(false)
  const [floorApplied, setFloorApplied] = useState(false)

  const imgRef = useRef(null)

  const scale = naturalSize.w ? displaySize.w / naturalSize.w : 1

  async function handleUpload(e) {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    setUploadError(null)
    setCandidates(null)
    setCropBox(null)
    setSelectedIndex(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const { data } = await api.post(`/processing/buildings/${buildingId}/imagery`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setDronePath(data.drone_image_path)
      setAiModelsEnabled(data.ai_models_enabled)
      setImageUrl(URL.createObjectURL(file))
    } catch (err) {
      setUploadError(err.response?.data?.detail || 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  function handleImageLoad() {
    const img = imgRef.current
    if (!img) return
    setNaturalSize({ w: img.naturalWidth, h: img.naturalHeight })
    setDisplaySize({ w: img.clientWidth, h: img.clientHeight })
  }

  function handleMouseDown(e) {
    const rect = e.currentTarget.getBoundingClientRect()
    dragStart.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
    setCropBox({ x0: dragStart.current.x, y0: dragStart.current.y, x1: dragStart.current.x, y1: dragStart.current.y })
  }
  function handleMouseMove(e) {
    if (!dragStart.current) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    setCropBox({
      x0: Math.min(dragStart.current.x, x), y0: Math.min(dragStart.current.y, y),
      x1: Math.max(dragStart.current.x, x), y1: Math.max(dragStart.current.y, y),
    })
  }
  function handleMouseUp() {
    dragStart.current = null
    if (cropBox && (cropBox.x1 - cropBox.x0 < 6 || cropBox.y1 - cropBox.y0 < 6)) {
      setCropBox(null)
    }
  }
  function clearCropBox() {
    setCropBox(null)
  }

  function displayToNaturalBox(box) {
    if (!box || !scale) return null
    return [box.x0 / scale, box.y0 / scale, box.x1 / scale, box.y1 / scale]
  }

  async function handleDetect() {
    setDetecting(true)
    setDetectError(null)
    setCandidates(null)
    setSelectedIndex(null)
    try {
      const crop_box = displayToNaturalBox(cropBox)
      const { data } = await api.post(`/processing/buildings/${buildingId}/imagery/detect`, { crop_box })
      setAiModelsEnabled(data.ai_models_enabled)
      setCandidates(data.candidates)
    } catch (err) {
      setDetectError(err.response?.data?.detail || 'Detection failed.')
    } finally {
      setDetecting(false)
    }
  }

  async function handleSelect(index) {
    setSelecting(index)
    try {
      const { data: building } = await api.post(`/processing/buildings/${buildingId}/imagery/select`, {
        candidate_index: index,
      })
      setSelectedIndex(index)
      onFootprintSaved?.(building)
    } catch (err) {
      setDetectError(err.response?.data?.detail || 'Could not save this candidate -- try running detection again.')
    } finally {
      setSelecting(null)
    }
  }

  async function handleDetectFloors() {
    setFloorDetecting(true)
    setFloorDetectError(null)
    setFloorEstimate(null)
    setFloorApplied(false)
    try {
      const crop_box = displayToNaturalBox(cropBox)
      const { data } = await api.post(`/processing/buildings/${buildingId}/imagery/detect-floors`, { crop_box })
      setFloorAiEnabled(data.ai_models_enabled)
      setFloorEstimate(data)
    } catch (err) {
      setFloorDetectError(err.response?.data?.detail || 'Floor count detection failed.')
    } finally {
      setFloorDetecting(false)
    }
  }

  async function handleApplyFloors() {
    setFloorSelecting(true)
    try {
      const { data: building } = await api.post(`/processing/buildings/${buildingId}/imagery/select-floors`, {})
      setFloorApplied(true)
      onFootprintSaved?.(building)
    } catch (err) {
      setFloorDetectError(err.response?.data?.detail || 'Could not apply this floor count -- try detecting again.')
    } finally {
      setFloorSelecting(false)
    }
  }

  const naturalCropBox = displayToNaturalBox(cropBox)

  return (
    <div className="card p-6">
      <h2 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
        <Crosshair size={16} /> Multi-Building Footprint Detection
      </h2>
      <p className="text-xs text-slate-500 mb-4 leading-relaxed">
        For orthophotos that may contain more than one building: optionally drag a box around the
        target building, run detection, then pick the correct result from the list below. Nothing is
        saved to the building until you choose one.
      </p>

      {!dronePath && (
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-2">Drone / Orthophoto Image</label>
          <input
            type="file" onChange={handleUpload} accept=".jpg,.jpeg,.png,.tif,.tiff"
            disabled={uploading}
            className="block w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-brand-500/15 file:text-brand-400 file:text-xs file:font-medium hover:file:bg-brand-500/25"
          />
          {uploading && <div className="flex items-center gap-2 text-xs text-slate-500 mt-2"><Loader2 size={13} className="animate-spin" /> Uploading…</div>}
          {uploadError && (
            <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5 mt-2">
              <XCircle size={14} /> {uploadError}
            </div>
          )}
        </div>
      )}

      {dronePath && imageUrl && (
        <div>
          <div
            className="relative inline-block select-none border border-white/10 rounded-lg overflow-hidden max-w-full"
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={() => (dragStart.current = null)}
          >
            <img
              ref={imgRef} src={imageUrl} alt="Uploaded orthophoto" onLoad={handleImageLoad}
              className="block max-w-full h-auto cursor-crosshair"
              draggable={false}
            />
            {cropBox && (
              <div
                className="absolute border-2 border-brand-400 bg-brand-400/10 pointer-events-none"
                style={{
                  left: cropBox.x0, top: cropBox.y0,
                  width: cropBox.x1 - cropBox.x0, height: cropBox.y1 - cropBox.y0,
                }}
              />
            )}
            {candidates && candidates.map((c) => (
              <div
                key={c.index}
                className={`absolute border-2 pointer-events-none ${selectedIndex === c.index ? 'border-emerald-400' : 'border-amber-400'}`}
                style={{
                  left: c.bbox_px[0] * scale, top: c.bbox_px[1] * scale,
                  width: (c.bbox_px[2] - c.bbox_px[0]) * scale, height: (c.bbox_px[3] - c.bbox_px[1]) * scale,
                }}
              >
                <span className={`absolute -top-5 left-0 text-[10px] font-medium px-1 rounded ${selectedIndex === c.index ? 'bg-emerald-400 text-black' : 'bg-amber-400 text-black'}`}>
                  #{c.index} · {(c.confidence * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-2 mt-3">
            <button onClick={handleDetect} disabled={detecting} className="btn-primary flex-1">
              {detecting ? <Loader2 className="animate-spin" size={16} /> : cropBox ? 'Detect in Selected Area' : 'Detect Buildings (Full Image)'}
            </button>
            {cropBox && (
              <button onClick={clearCropBox} disabled={detecting} title="Clear crop box" className="btn-secondary px-3">
                <RotateCcw size={14} />
              </button>
            )}
          </div>
          <p className="text-[11px] text-slate-600 mt-1.5">
            {cropBox ? 'A crop box is set -- detection will only look inside it.' : 'Drag on the image to focus detection on one building, or run on the full image.'}
          </p>

          {!aiModelsEnabled && (
            <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-500/5 border border-amber-500/15 rounded-lg px-3 py-2.5 mt-3">
              <XCircle size={14} /> AI_MODELS_ENABLED is false on the server -- detection can't run until real weights are configured.
            </div>
          )}
          {detectError && (
            <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5 mt-3">
              <XCircle size={14} /> {detectError}
            </div>
          )}

          {candidates && candidates.length === 0 && !detectError && (
            <p className="text-xs text-slate-500 mt-3">No buildings detected in {cropBox ? 'the selected area' : 'this image'}.</p>
          )}

          {candidates && candidates.length > 0 && (
            <div className="mt-4 pt-4 border-t border-white/5 space-y-2">
              <h3 className="text-xs font-semibold text-slate-400 mb-2">
                {candidates.length} detection{candidates.length > 1 ? 's' : ''} found -- pick the correct building
              </h3>
              {candidates.map((c) => (
                <div key={c.index} className={`flex items-center justify-between text-xs rounded-lg px-3 py-2.5 ${selectedIndex === c.index ? 'bg-emerald-500/10 border border-emerald-500/20' : 'bg-white/5'}`}>
                  <div>
                    <span className="text-white font-medium">Candidate #{c.index}</span>
                    <span className="text-slate-500 ml-2">confidence {(c.confidence * 100).toFixed(0)}%</span>
                  </div>
                  {selectedIndex === c.index ? (
                    <span className="flex items-center gap-1.5 text-emerald-400 font-medium"><CheckCircle2 size={14} /> Saved as footprint</span>
                  ) : (
                    <button onClick={() => handleSelect(c.index)} disabled={selecting !== null} className="btn-secondary text-xs px-3 py-1.5">
                      {selecting === c.index ? <Loader2 className="animate-spin" size={13} /> : 'Use this footprint'}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="mt-6 pt-5 border-t border-white/10">
            <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
              <Crosshair size={14} /> Floor Count / Height Detection
            </h3>
            <p className="text-xs text-slate-500 mb-3 leading-relaxed">
              Counts distinct facade window-bands stacked vertically in this same image (using the crop box above,
              if set) as a real estimate of how many floors this building actually shows — separate from whatever
              num_floors was entered manually at creation. Nothing is applied until you confirm below.
            </p>

            <button onClick={handleDetectFloors} disabled={floorDetecting} className="btn-secondary w-full">
              {floorDetecting ? <Loader2 className="animate-spin" size={16} /> : 'Detect Floor Count'}
            </button>

            {!floorAiEnabled && (
              <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-500/5 border border-amber-500/15 rounded-lg px-3 py-2.5 mt-3">
                <XCircle size={14} /> AI_MODELS_ENABLED is false on the server -- detection can't run until real weights are configured.
              </div>
            )}
            {floorDetectError && (
              <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5 mt-3">
                <XCircle size={14} /> {floorDetectError}
              </div>
            )}

            {floorEstimate && !floorEstimate.estimate && !floorDetectError && (
              <p className="text-xs text-slate-500 mt-3">
                Model ran but couldn't find any distinct floor bands in {cropBox ? 'the selected area' : 'this image'} --
                current values are unchanged (still {currentNumFloors ?? '—'} floors).
              </p>
            )}

            {floorEstimate?.estimate && (
              <div className="mt-3">
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5">
                    <div className="text-[10px] text-slate-500 mb-1">Currently Entered</div>
                    <div className="text-sm text-slate-300">{currentNumFloors ?? floorEstimate.current_num_floors} floors</div>
                    <div className="text-sm text-slate-300">
                      {(currentHeightM ?? floorEstimate.current_height_m) != null ? `${currentHeightM ?? floorEstimate.current_height_m} m` : '—'}
                    </div>
                  </div>
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5">
                    <div className="text-[10px] text-slate-500 mb-1">Detected from Facade · {(floorEstimate.estimate.confidence * 100).toFixed(0)}%</div>
                    <div className="text-sm text-amber-400 font-medium">{floorEstimate.estimate.floor_count} floors</div>
                    <div className="text-sm text-amber-400 font-medium">{floorEstimate.estimate.height_m} m</div>
                  </div>
                </div>
                {floorApplied ? (
                  <span className="flex items-center gap-1.5 text-emerald-400 font-medium text-xs mt-3"><CheckCircle2 size={14} /> Applied to this building</span>
                ) : (
                  <button onClick={handleApplyFloors} disabled={floorSelecting} className="btn-primary w-full mt-3">
                    {floorSelecting ? <Loader2 className="animate-spin" size={16} /> : `Use ${floorEstimate.estimate.floor_count} Floors / ${floorEstimate.estimate.height_m}m`}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
