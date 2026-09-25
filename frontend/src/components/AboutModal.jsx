import { X, ShieldCheck } from 'lucide-react'

// Plain-English "what is this, and what is it not" -- shown from the map page.
export default function AboutModal({ onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="card max-w-lg w-full p-6 max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-3">
          <h2 className="font-display text-lg font-bold text-white flex items-center gap-2">
            <ShieldCheck size={18} className="text-brand-400" /> About this map
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>

        <p className="text-sm text-slate-300 mb-4">
          Vasudha 3D is a <b>prototype</b> that gives every flat, shop or parking bay in a building its own
          3D land ID (3D ULPIN), so ownership can be tied to a real volume of space, not just the ground.
          The IDs are <b>proposed</b> — this is not an official DoLR ULPIN system.
        </p>

        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">How the map is filled — automatically</h3>
        <ol className="text-sm text-slate-300 list-decimal pl-5 space-y-1 mb-4">
          <li>Pick an area and press <b>Auto-map this view</b>. Nothing else to type or upload.</li>
          <li>Building outlines come from the region data already loaded, or live from OpenStreetMap.</li>
          <li>Floors, units and 3D ULPINs are generated for every building.</li>
          <li>Checks flag overlaps and odd shapes. <b>A verifier still approves every unit</b> — nothing is auto-approved.</li>
        </ol>

        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">How sure are we about the floors?</h3>
        <ul className="text-sm text-slate-300 space-y-1 mb-4">
          <li><b className="text-emerald-400">Observed</b> — a real source gave the floor count (OSM tag or survey).</li>
          <li><b className="text-amber-400">Predicted</b> — estimated (satellite elevation, or nearby buildings). Shown with its method.</li>
          <li><b className="text-slate-400">Not determinable</b> — not enough evidence, so nothing was invented.</li>
        </ul>

        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">Good to know</h3>
        <ul className="text-sm text-slate-300 list-disc pl-5 space-y-1">
          <li>Grey buildings are footprints with <b>unknown height</b>, drawn at a placeholder height.</li>
          <li>Once verified, a unit is <b>locked</b>. Changes need the owner's approval.</li>
          <li>Imagery: Esri. Terrain: AWS Terrain Tiles. Buildings: OpenStreetMap via OpenFreeMap.</li>
        </ul>
      </div>
    </div>
  )
}
