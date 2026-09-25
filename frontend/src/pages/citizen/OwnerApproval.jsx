import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Loader2, ShieldCheck, ShieldX, Info } from 'lucide-react'
import api from '../../api/client'

const FIELD_LABELS = { z_min: 'Bottom height (m)', z_max: 'Top height (m)', parcel_type: 'Property type', footprint_geojson: 'Boundary shape' }

function show(key, value) {
  if (value === null || value === undefined) return '—'
  if (key === 'footprint_geojson') return 'New boundary outline'
  return String(value).replace('_', ' ')
}

export default function OwnerApproval() {
  const { token } = useParams()
  const [req, setReq] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.get(`/lifecycle/owner/${token}`)
      .then((r) => setReq(r.data))
      .catch((e) => setError(e.response?.data?.detail || 'This link is not valid.'))
  }, [token])

  async function decide(approve) {
    setBusy(true)
    try {
      const { data } = await api.post(`/lifecycle/owner/${token}/decision`, { approve })
      setReq(data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not record your decision.')
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return (
      <div className="max-w-md mx-auto px-4 py-24 text-center">
        <Info className="mx-auto mb-3 text-slate-600" size={30} />
        <p className="text-sm text-slate-400">{error}</p>
      </div>
    )
  }
  if (!req) return <div className="flex justify-center py-24"><Loader2 className="animate-spin text-brand-400" size={26} /></div>

  const decided = req.status !== 'pending_owner'

  return (
    <div className="max-w-xl mx-auto px-4 py-10">
      <div className="card p-6">
        <h1 className="font-display text-xl font-bold text-white mb-1">Approve a change to your property record</h1>
        <p className="text-xs text-slate-500 mb-5">Your verified record is locked. It changes only if you agree.</p>

        <div className="text-xs text-slate-500">Property (3D ULPIN)</div>
        <div className="font-mono text-sm text-white break-all mb-4">{req.ulpin_3d}</div>

        <div className="rounded-md border border-white/10 divide-y divide-white/5 mb-4">
          <div className="grid grid-cols-3 px-3 py-2 text-[11px] uppercase tracking-wide text-slate-500">
            <span>What</span><span>Now</span><span>Proposed</span>
          </div>
          {Object.keys(req.proposed).map((k) => (
            <div key={k} className="grid grid-cols-3 px-3 py-2.5 text-sm">
              <span className="text-slate-400">{FIELD_LABELS[k] || k}</span>
              <span className="text-slate-200 capitalize">{show(k, req.current[k])}</span>
              <span className="text-brand-400 font-medium capitalize">{show(k, req.proposed[k])}</span>
            </div>
          ))}
        </div>

        {req.reason && <p className="text-sm text-slate-300 mb-4"><span className="text-slate-500">Reason given: </span>{req.reason}</p>}

        {!decided && (
          <div className="flex gap-3">
            <button disabled={busy} onClick={() => decide(true)} className="btn-primary flex-1"><ShieldCheck size={15} /> I approve</button>
            <button disabled={busy} onClick={() => decide(false)} className="btn-secondary flex-1"><ShieldX size={15} /> I decline</button>
          </div>
        )}
        {decided && (
          <div className="text-sm rounded-md border border-white/10 bg-white/5 px-3 py-3 text-slate-200">
            {req.status === 'owner_declined'
              ? 'You declined this change. Your record stays as it is.'
              : req.status === 'applied'
                ? 'This change was approved and has been applied by an officer.'
                : 'Thank you — your approval is recorded. An officer will now apply the change.'}
          </div>
        )}
        <p className="text-[11px] text-slate-600 mt-5">Prototype: in a live system this step would sit behind a verified identity (for example DigiLocker).</p>
      </div>
    </div>
  )
}
