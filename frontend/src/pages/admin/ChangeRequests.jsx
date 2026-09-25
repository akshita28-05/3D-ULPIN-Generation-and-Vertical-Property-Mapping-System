import { useEffect, useState } from 'react'
import { Loader2, Copy, Check, Search } from 'lucide-react'
import api from '../../api/client'
import { useAuth } from '../../context/AuthContext.jsx'

const STATUS_STYLE = {
  pending_owner: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  owner_approved: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  owner_declined: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  applied: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  rejected: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
}
const STATUS_LABEL = {
  pending_owner: 'Waiting for owner', owner_approved: 'Owner approved', owner_declined: 'Owner declined',
  applied: 'Applied', rejected: 'Rejected',
}
const TYPES = ['residential_unit', 'commercial_unit', 'parking_unit']

function summarize(obj) {
  return Object.entries(obj || {})
    .map(([k, v]) => `${k === 'footprint_geojson' ? 'boundary' : k}: ${k === 'footprint_geojson' ? 'new outline' : v}`)
    .join(', ')
}

export default function ChangeRequests() {
  const { user } = useAuth()
  const canDecide = ['verifier', 'admin'].includes(user?.role)
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)

  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [unit, setUnit] = useState(null)
  const [form, setForm] = useState({ z_min: '', z_max: '', parcel_type: '', reason: '' })
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState(null)
  const [copied, setCopied] = useState(false)

  function load() {
    api.get('/lifecycle/change-requests').then((r) => setRows(r.data)).catch(() => setErr('Could not load change requests.'))
  }
  useEffect(load, [])

  async function searchUnits(e) {
    e.preventDefault()
    if (!q.trim()) return
    const { data } = await api.get('/search', { params: { q: q.trim() } })
    setHits(data.filter((r) => r.result_type === 'unit'))
  }

  async function pickUnit(hit) {
    const { data } = await api.get(`/units/${hit.id}`)
    setUnit(data)
    setHits([])
    setForm({ z_min: '', z_max: '', parcel_type: '', reason: '' })
    setCreated(null)
  }

  async function submit(e) {
    e.preventDefault()
    setErr(null)
    const proposed = {}
    if (form.z_min !== '') proposed.z_min = Number(form.z_min)
    if (form.z_max !== '') proposed.z_max = Number(form.z_max)
    if (form.parcel_type) proposed.parcel_type = form.parcel_type
    if (!Object.keys(proposed).length) return setErr('Enter at least one change.')
    setCreating(true)
    try {
      const { data } = await api.post('/lifecycle/change-requests', { unit_id: unit.id, proposed, reason: form.reason || null })
      setCreated(data)
      setUnit(null)
      load()
    } catch (e2) {
      setErr(e2.response?.data?.detail || 'Could not create the request.')
    } finally {
      setCreating(false)
    }
  }

  async function act(id, kind) {
    const note = kind === 'reject' ? window.prompt('Reason for rejecting (optional):') : window.prompt('Note for the record (optional):')
    if (note === null) return
    try {
      await api.post(`/lifecycle/change-requests/${id}/${kind}`, { note: note || null })
      load()
    } catch (e) {
      window.alert(e.response?.data?.detail || 'Action failed.')
    }
  }

  const ownerLink = created ? `${window.location.origin}${created.owner_link_path}` : null

  return (
    <div className="max-w-5xl mx-auto">
      <h1 className="font-display text-2xl font-bold text-white mb-1">Change Requests</h1>
      <p className="text-sm text-slate-500 mb-6">
        A verified unit is a locked baseline. To change it: raise a request → the owner approves with a one-time link → a verifier applies it → the new state is locked.
      </p>

      <div className="card p-5 mb-6">
        <h2 className="text-sm font-semibold text-white mb-3">New request</h2>
        {!unit ? (
          <form onSubmit={searchUnits} className="flex gap-2">
            <input className="input-field" placeholder="Find the unit by its 3D ULPIN" value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="btn-secondary"><Search size={14} /> Find</button>
          </form>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <div className="text-xs text-slate-400">
              Unit <span className="font-mono text-white">{unit.ulpin_3d}</span> — now {unit.z_min}m to {unit.z_max}m, {unit.parcel_type?.replace('_', ' ')}
              {unit.verification_status !== 'approved' && <span className="text-amber-400"> (not verified yet — edit it directly instead)</span>}
            </div>
            <div className="grid sm:grid-cols-3 gap-3">
              <input className="input-field" type="number" step="0.1" placeholder="New bottom height (m)" value={form.z_min} onChange={(e) => setForm({ ...form, z_min: e.target.value })} />
              <input className="input-field" type="number" step="0.1" placeholder="New top height (m)" value={form.z_max} onChange={(e) => setForm({ ...form, z_max: e.target.value })} />
              <select className="input-field" value={form.parcel_type} onChange={(e) => setForm({ ...form, parcel_type: e.target.value })}>
                <option value="">Property type (unchanged)</option>
                {TYPES.map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
              </select>
            </div>
            <input className="input-field" placeholder="Reason (e.g. mezzanine added)" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
            <div className="flex gap-2">
              <button className="btn-primary" disabled={creating}>{creating ? <Loader2 size={14} className="animate-spin" /> : null} Create request</button>
              <button type="button" className="btn-secondary" onClick={() => setUnit(null)}>Cancel</button>
            </div>
          </form>
        )}
        {hits.length > 0 && (
          <div className="mt-3 border border-white/10 rounded-md divide-y divide-white/5">
            {hits.map((h) => (
              <button key={h.id} onClick={() => pickUnit(h)} className="block w-full text-left px-3 py-2 text-xs font-mono text-slate-300 hover:bg-white/5">{h.label}</button>
            ))}
          </div>
        )}
        {err && <p className="text-xs text-rose-400 mt-3">{err}</p>}
        {created && (
          <div className="mt-4 rounded-md border border-brand-500/30 bg-brand-500/5 p-3">
            <div className="text-xs text-brand-400 font-semibold mb-1">Give this one-time link to the owner (shown only now)</div>
            <div className="flex items-center gap-2">
              <code className="text-[11px] text-slate-200 break-all flex-1">{ownerLink}</code>
              <button
                className="btn-secondary !py-1.5 !px-2.5 text-xs"
                onClick={() => { navigator.clipboard?.writeText(ownerLink); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
              >
                {copied ? <Check size={13} /> : <Copy size={13} />}
              </button>
            </div>
          </div>
        )}
      </div>

      {rows === null && !err && <div className="flex justify-center py-10"><Loader2 className="animate-spin text-brand-400" /></div>}
      {rows && rows.length === 0 && <p className="text-sm text-slate-500 text-center py-8">No change requests yet.</p>}
      <div className="space-y-2">
        {(rows || []).map((r) => (
          <div key={r.id} className="card p-4 flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-mono text-xs text-white break-all">{r.ulpin_3d}</div>
              <div className="text-xs text-slate-400 mt-1">
                {summarize(r.current)} <span className="text-slate-600">→</span> <span className="text-brand-400">{summarize(r.proposed)}</span>
              </div>
              {r.reason && <div className="text-[11px] text-slate-500 mt-0.5">Reason: {r.reason}</div>}
            </div>
            <div className="flex items-center gap-2">
              <span className={`badge border ${STATUS_STYLE[r.status]}`}>{STATUS_LABEL[r.status]}</span>
              {canDecide && r.status === 'owner_approved' && <button className="btn-primary !py-1.5 !px-3 text-xs" onClick={() => act(r.id, 'apply')}>Apply</button>}
              {canDecide && ['pending_owner', 'owner_approved'].includes(r.status) && <button className="btn-secondary !py-1.5 !px-3 text-xs" onClick={() => act(r.id, 'reject')}>Reject</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
