import { useEffect, useState } from 'react'
import api from '../api/client'
import { polygonArea, safeParseGeojson } from '../utils/geometry.js'
import { Loader2, Sparkles } from 'lucide-react'

export default function BeforeAfterAIPanel({ buildingId }) {
  const [comparison, setComparison] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!buildingId) return
    setLoading(true)
    api.get(`/processing/buildings/${buildingId}/comparison`)
      .then(({ data }) => setComparison(data))
      .catch(() => setComparison(null))
      .finally(() => setLoading(false))
  }, [buildingId])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-500 py-3">
        <Loader2 size={13} className="animate-spin" /> Checking AI processing history…
      </div>
    )
  }

  const footprintChanged = comparison?.footprint?.changed_by_ai
  const floorsChanged = comparison?.floors?.changed_by_ai

  if (!footprintChanged && !floorsChanged) return null

  const beforeFootprintArea = footprintChanged ? polygonArea(safeParseGeojson(comparison.footprint.before)) : null
  const afterFootprintArea = footprintChanged ? polygonArea(safeParseGeojson(comparison.footprint.after)) : null

  return (
    <div className="mt-5 pt-4 border-t border-white/10">
      <div className="text-[11px] font-semibold text-slate-400 mb-3 flex items-center gap-1.5">
        <Sparkles size={12} /> AI PROCESSING — BEFORE / AFTER
      </div>

      {footprintChanged && (
        <div className="mb-4">
          <div className="text-xs text-slate-500 mb-1.5">Footprint extraction</div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-white/5 p-2.5">
              <div className="text-[10px] text-slate-500 mb-0.5">Before (manual)</div>
              <div className="text-sm text-white font-medium">
                {beforeFootprintArea != null ? `${beforeFootprintArea.toFixed(1)} m²` : '—'}
              </div>
            </div>
            <div className="rounded-lg bg-brand-500/10 border border-brand-500/20 p-2.5">
              <div className="text-[10px] text-brand-400 mb-0.5">After (YOLOv8-seg)</div>
              <div className="text-sm text-white font-medium">
                {afterFootprintArea != null ? `${afterFootprintArea.toFixed(1)} m²` : '—'}
              </div>
            </div>
          </div>
          <div className="text-[11px] text-slate-500 mt-1.5">
            Model confidence: <span className="text-white font-medium">{(comparison.footprint.confidence * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}

      {floorsChanged && (
        <div>
          <div className="text-xs text-slate-500 mb-1.5">Floor segmentation</div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-white/5 p-2.5">
              <div className="text-[10px] text-slate-500 mb-0.5">Before (surveyed)</div>
              <div className="text-sm text-white font-medium">{comparison.floors.before.num_floors} floors</div>
              <div className="text-[11px] text-slate-500">{comparison.floors.before.height_m} m total</div>
            </div>
            <div className="rounded-lg bg-brand-500/10 border border-brand-500/20 p-2.5">
              <div className="text-[10px] text-brand-400 mb-0.5">After (point-cloud clustering)</div>
              <div className="text-sm text-white font-medium">{comparison.floors.after.num_floors} floors</div>
              <div className="text-[11px] text-slate-500">{comparison.floors.after.height_m} m total</div>
            </div>
          </div>
        </div>
      )}

      <p className="text-[10px] text-slate-600 mt-3 leading-relaxed">
        "Before" is the surveyor-entered value captured the moment the AI model first ran;
        "after" is the model's real output for this building.
      </p>
    </div>
  )
}
