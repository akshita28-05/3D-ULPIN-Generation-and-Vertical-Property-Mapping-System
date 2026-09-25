import { useState } from 'react'
import { Loader2, ChevronDown, ChevronUp } from 'lucide-react'
import { infraHex, infraStyle, cssHex } from './building3d/infra3d.js'

export default function InfraLegend({ parcel, layers, state, scan, onSelect, selectedId }) {
  const [collapsed, setCollapsed] = useState(false)
  const wantUg = layers.underground
  const wantAir = layers.airRights
  if (!parcel || (!wantUg && !wantAir)) return null

  const infra = parcel.infra
  const radius = infra?.radius_m ?? 120
  const features = (infra?.available ? infra.features : []).filter(
    (f) => (f.kind === 'underground' && wantUg) || (f.kind === 'air' && wantAir),
  )
  const manualUg = wantUg ? (parcel.undergroundAssets || []).filter((a) => a.source !== 'osm_auto').length : 0
  const manualAir = wantAir ? (parcel.airRights || []).filter((a) => a.source !== 'osm_auto').length : 0
  const scanNote = scan && (scan.status === 'unavailable' || scan.status === 'partial') ? scan.message : null

  const groups = new Map()
  features.forEach((f) => {
    const key = `${f.kind}:${f.subtype}:${f.substance || ''}`
    if (!groups.has(key)) groups.set(key, { key, kind: f.kind, items: [] })
    groups.get(key).items.push(f)
  })
  const rows = [...groups.values()].map((g) => {
    const nearest = [...g.items].sort((a, b) => (a.distance_m ?? 0) - (b.distance_m ?? 0))[0]
    const lo = Math.min(...g.items.map((f) => f.z_min_m ?? 0))
    const hi = Math.max(...g.items.map((f) => f.z_max_m ?? 0))
    const assumed = g.items.some((f) => f.z_source !== 'osm_tag')
    return {
      ...g, nearest, hex: infraHex(nearest),
      name: infraStyle(nearest).short, range: `${assumed ? '~' : ''}${+lo.toFixed(1)}–${+hi.toFixed(1)} m`,
      onParcel: g.items.some((f) => f.on_parcel), conflict: g.items.some((f) => f.conflict_status === 'confirmed'),
      picked: g.items.some((f) => f.id === selectedId),
    }
  }).sort((a, b) => (a.kind === b.kind ? b.items.length - a.items.length : a.kind === 'underground' ? -1 : 1))

  const nUg = features.filter((f) => f.kind === 'underground').length
  const nAir = features.filter((f) => f.kind === 'air').length
  const empty = rows.length === 0 && manualUg === 0 && manualAir === 0

  return (
    <div className="card pointer-events-auto bg-ink-900/90 flex flex-col min-h-0 overflow-hidden">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <span className="text-[11px] font-semibold text-slate-400 tracking-wide">
          NEARBY STRUCTURES
          {rows.length > 0 && <span className="ml-1.5 text-slate-500 font-normal">{[wantUg && `${nUg} below`, wantAir && `${nAir} above`].filter(Boolean).join(' · ')}</span>}
        </span>
        {state === 'loading' ? <Loader2 size={12} className="animate-spin text-slate-500" /> : (collapsed ? <ChevronDown size={12} className="text-slate-500" /> : <ChevronUp size={12} className="text-slate-500" />)}
      </button>

      {!collapsed && (
        <div className="px-2 pb-2 overflow-y-auto min-h-0">
          {rows.map((r) => (
            <button
              key={r.key}
              onClick={() => onSelect?.({ type: 'infra', id: r.nearest.id })}
              className={`w-full flex items-center gap-2 text-left rounded-md px-2 py-1.5 hover:bg-white/5 ${r.picked ? 'bg-white/10' : ''}`}
            >
              <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: cssHex(r.hex) }} />
              <span className="flex-1 min-w-0">
                <span className="block text-[11px] text-slate-200 capitalize truncate">
                  {r.name}{r.items.length > 1 && <span className="text-slate-500"> ×{r.items.length}</span>}
                  {r.conflict && <span className="ml-1 text-red-400">●</span>}
                </span>
                <span className="block text-[10px] text-slate-500 font-mono">
                  {r.range} · {r.onParcel ? 'on parcel' : `${Math.round(r.nearest.distance_m)} m away`}
                </span>
              </span>
            </button>
          ))}

          {(manualUg > 0 || manualAir > 0) && (
            <p className="text-[10px] text-slate-400 px-2 py-1">
              Also on this parcel: {[manualUg > 0 && `${manualUg} underground`, manualAir > 0 && `${manualAir} air-right`].filter(Boolean).join(', ')} (officer / GPR / AI)
            </p>
          )}

          {empty && state !== 'loading' && (
            <p className="text-[11px] text-slate-400 leading-relaxed px-2 py-1">
              {state === 'error'
                ? 'Could not load nearby structures.'
                : `Nothing found in open data within ${radius} m.`}
            </p>
          )}
          {empty && state === 'loading' && <p className="text-[11px] text-slate-400 px-2 py-1">Reading open data…</p>}
          {scanNote && <p className="text-[10px] text-amber-400/90 px-2 py-1 leading-relaxed">{scanNote}</p>}

          <p className="text-[10px] text-slate-600 px-2 pt-1.5 leading-relaxed">
            OpenStreetMap · within {radius} m · “~” = typical value, not surveyed
          </p>
        </div>
      )}
    </div>
  )
}
