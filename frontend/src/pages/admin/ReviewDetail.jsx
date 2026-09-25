import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import api from '../../api/client'
import StatusBadge from '../../components/StatusBadge.jsx'
import {
  Loader2, ArrowLeft, CheckCircle2, XCircle, RotateCw, AlertTriangle, Save,
} from 'lucide-react'

export default function ReviewDetail() {
  const { unitId } = useParams()
  const navigate = useNavigate()
  const [unit, setUnit] = useState(null)
  const [validation, setValidation] = useState([])
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [note, setNote] = useState('')
  const [editMode, setEditMode] = useState(false)
  const [zMin, setZMin] = useState('')
  const [zMax, setZMax] = useState('')
  const [message, setMessage] = useState(null)

  useEffect(() => {
    load()
  }, [unitId])

  async function load() {
    setLoading(true)
    try {
      const [u, v] = await Promise.all([
        api.get(`/units/${unitId}`),
        api.get(`/review/units/${unitId}/validation`),
      ])
      setUnit(u.data)
      setValidation(v.data)
      setZMin(u.data.z_min)
      setZMax(u.data.z_max)
    } finally {
      setLoading(false)
    }
  }

  async function handleAction(action) {
    setActing(true)
    setMessage(null)
    try {
      const payload = { action, note }
      if (editMode) {
        payload.edited_z_min = parseFloat(zMin)
        payload.edited_z_max = parseFloat(zMax)
      }
      const { data } = await api.post(`/review/units/${unitId}/action`, payload)
      setUnit(data)
      setMessage({ type: 'success', text: `Unit ${action === 'approve' ? 'approved' : action === 'reject' ? 'rejected' : 'sent for reprocessing'}.` })
      setEditMode(false)
    } catch (err) {
      setMessage({ type: 'error', text: err.response?.data?.detail || 'Action failed.' })
    } finally {
      setActing(false)
    }
  }

  if (loading) return <div className="flex justify-center py-24"><Loader2 className="animate-spin text-brand-400" size={28} /></div>
  if (!unit) return <div className="text-sm text-slate-500">Unit not found.</div>

  return (
    <div className="animate-fade-in max-w-3xl">
      <Link to="/admin/review" className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-white mb-6">
        <ArrowLeft size={14} /> Back to Queue
      </Link>

      <div className="card p-6 mb-6">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
          <div>
            <h1 className="font-display text-lg font-bold text-white break-all">{unit.ulpin_3d}</h1>
            <p className="text-xs text-slate-500 mt-1">Vertical Property Unit</p>
          </div>
          <StatusBadge status={unit.verification_status} />
        </div>

        <div className="grid sm:grid-cols-2 gap-x-8 gap-y-1 mb-6">
          <Row label="Property Type" value={unit.parcel_type?.replace('_', ' ')} />
          <Row label="Area" value={`${unit.area_sqm} sqm`} />
          <Row label="Volume" value={`${unit.volume_cum} m³`} />
          <Row label="AI Confidence" value={unit.ai_confidence ? `${(unit.ai_confidence * 100).toFixed(0)}%` : '—'} />
        </div>

        {!editMode ? (
          <div className="grid sm:grid-cols-2 gap-x-8 gap-y-1 mb-2">
            <Row label="Z-Min" value={`${unit.z_min} m`} />
            <Row label="Z-Max" value={`${unit.z_max} m`} />
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 gap-4 mb-4 bg-white/5 rounded-xl p-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2">Z-Min (m)</label>
              <input type="number" step="0.1" value={zMin} onChange={(e) => setZMin(e.target.value)} className="input-field" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2">Z-Max (m)</label>
              <input type="number" step="0.1" value={zMax} onChange={(e) => setZMax(e.target.value)} className="input-field" />
            </div>
          </div>
        )}

        <button onClick={() => setEditMode(!editMode)} className="text-xs text-brand-400 hover:underline mt-2">
          {editMode ? 'Cancel geometry edit' : 'Correct boundary / elevation'}
        </button>
      </div>

      {validation.length > 0 && (
        <div className="card p-6 mb-6">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <AlertTriangle size={16} className="text-amber-400" /> Validation Flags ({validation.length})
          </h2>
          <div className="space-y-2">
            {validation.map((v) => (
              <div key={v.id} className="flex items-start gap-3 bg-white/5 rounded-lg px-3 py-2.5">
                <StatusBadge status={v.severity} />
                <span className="text-xs text-slate-300 leading-relaxed">{v.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      { }
      <div className="card p-6">
        <h2 className="text-sm font-semibold text-white mb-4">Verifier Decision</h2>

        {message && (
          <div className={`flex items-center gap-2 text-xs rounded-lg px-3 py-2.5 mb-4 ${
            message.type === 'success' ? 'text-emerald-400 bg-emerald-500/5 border border-emerald-500/15' : 'text-rose-400 bg-rose-500/5 border border-rose-500/15'
          }`}>
            {message.type === 'success' ? <CheckCircle2 size={14} /> : <XCircle size={14} />} {message.text}
          </div>
        )}

        <textarea
          value={note} onChange={(e) => setNote(e.target.value)} rows={2}
          placeholder="Optional verifier note…" className="input-field resize-none mb-4"
        />

        <div className="flex flex-col sm:flex-row gap-2">
          <button onClick={() => handleAction('approve')} disabled={acting} className="btn-primary flex-1 !bg-emerald-500 hover:!bg-emerald-400 !text-ink-950">
            <CheckCircle2 size={15} /> Approve
          </button>
          <button onClick={() => handleAction('reject')} disabled={acting} className="btn-secondary flex-1 !text-rose-400 !border-rose-500/20 hover:!bg-rose-500/10">
            <XCircle size={15} /> Reject
          </button>
          <button onClick={() => handleAction('reprocess')} disabled={acting} className="btn-secondary flex-1">
            <RotateCw size={15} /> Reprocess
          </button>
          {editMode && (
            <button onClick={() => handleAction('approve')} disabled={acting} className="btn-secondary flex-1 !text-brand-400">
              <Save size={15} /> Save & Approve
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-white/5">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-sm text-white font-medium capitalize">{value ?? '—'}</span>
    </div>
  )
}
