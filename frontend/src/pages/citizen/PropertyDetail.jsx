import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../../api/client'
import StatusBadge from '../../components/StatusBadge.jsx'
import { QRCodeSVG } from 'qrcode.react'
import EvidenceBadge from '../../components/EvidenceBadge.jsx'
import { Loader2, FileDown, Flag, ArrowLeft, ShieldCheck, ShieldAlert, Info, Download, Lock } from 'lucide-react'

export default function PropertyDetail() {
  const { unitId } = useParams()
  const [unit, setUnit] = useState(null)
  const [passport, setPassport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    api.get(`/units/${unitId}`)
      .then((res) => setUnit(res.data))
      .catch(() => setError('This property record could not be found.'))
      .finally(() => setLoading(false))
    api.get(`/lifecycle/units/${unitId}/passport`).then((res) => setPassport(res.data)).catch(() => setPassport(null))
  }, [unitId])

  if (loading) {
    return <div className="flex justify-center py-24"><Loader2 className="animate-spin text-brand-400" size={28} /></div>
  }

  if (error) {
    return (
      <div className="max-w-lg mx-auto px-4 py-24 text-center">
        <Info className="mx-auto mb-3 text-slate-600" size={32} />
        <p className="text-slate-400 text-sm">{error}</p>
        <Link to="/search" className="btn-secondary mt-6 inline-flex text-sm">Back to Search</Link>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10">
      <Link to="/viewer" className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-white mb-6">
        <ArrowLeft size={14} /> Back to 3D Map
      </Link>

      <div className="card p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
          <div>
            <h1 className="font-display text-xl sm:text-2xl font-bold text-white break-all">{unit.ulpin_3d}</h1>
            <p className="text-xs text-slate-500 mt-1">3D Unique Land Parcel Identification Number</p>
          </div>
          <StatusBadge status={unit.verification_status} />
        </div>

        {unit.verification_status === 'approved' && (
          <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/5 border border-emerald-500/15 rounded-lg px-3 py-2 mb-6">
            <ShieldCheck size={14} /> This record has been reviewed and verified by a DoLR-authorized officer.
          </div>
        )}

        <div className="grid sm:grid-cols-2 gap-x-8 gap-y-1">
          <DetailRow label="Property Type" value={unit.parcel_type?.replace('_', ' ')} />
          <DetailRow label="Area" value={`${unit.area_sqm} sqm`} />
          <DetailRow label="Volume" value={`${unit.volume_cum} m³`} />
          <DetailRow label="Z-Min / Z-Max" value={`${unit.z_min}m – ${unit.z_max}m`} />
          <DetailRow label="Owner Reference" value={unit.owner_reference} />
          {unit.ai_confidence && <DetailRow label="AI Confidence" value={`${(unit.ai_confidence * 100).toFixed(0)}%`} />}
        </div>

        {passport && <PassportSection passport={passport} unitId={unit.id} />}

        <div className="mt-8 flex flex-col sm:flex-row gap-3">
          <a href={`/api/export/units/${unit.id}.pdf`} className="btn-primary flex-1 text-sm" target="_blank" rel="noreferrer">
            <FileDown size={15} /> Download Record (PDF)
          </a>
          <Link to={`/report/${unit.id}`} className="btn-secondary flex-1 text-sm">
            <Flag size={15} /> Report an Issue
          </Link>
        </div>
      </div>

      <p className="text-[11px] text-slate-600 text-center mt-6">
        Ownership reference is a prototype placeholder — real records never expose personal information here.
      </p>
    </div>
  )
}

function DetailRow({ label, value }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-white/5">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-sm text-white font-medium capitalize">{value ?? '—'}</span>
    </div>
  )
}

function PassportSection({ passport, unitId }) {
  const integ = passport.integrity
  const passportUrl = `${window.location.origin}/property/${unitId}`
  let tone = 'text-slate-400 bg-white/5 border-white/10'
  let label = 'Not locked yet — pending verification'
  let Icon = Info
  if (integ.tampered) {
    tone = 'text-rose-300 bg-rose-500/10 border-rose-500/30'
    label = 'TAMPER WARNING — this record no longer matches its locked baseline'
    Icon = ShieldAlert
  } else if (integ.locked && integ.has_baseline) {
    tone = 'text-emerald-400 bg-emerald-500/5 border-emerald-500/20'
    label = 'Locked baseline — record matches what was verified'
    Icon = Lock
  } else if (integ.locked) {
    tone = 'text-emerald-400 bg-emerald-500/5 border-emerald-500/20'
    label = 'Verified (before baseline locking was added)'
    Icon = ShieldCheck
  }

  return (
    <div className="mt-6 grid sm:grid-cols-[1fr_auto] gap-5 items-start rounded-lg border border-white/5 p-4">
      <div className="space-y-3">
        <div className="text-xs uppercase tracking-wide text-slate-500">Property passport</div>
        <div className={`flex items-start gap-2 text-xs rounded-md border px-3 py-2 ${tone}`}>
          <Icon size={14} className="mt-0.5 shrink-0" /> <span>{label}</span>
        </div>
        {passport.floor_state && (
          <div className="text-xs text-slate-400 flex flex-wrap items-center gap-2">
            Floor count <EvidenceBadge state={passport.floor_state} method={passport.floor_method} />
            <span className="text-slate-500">{passport.floor_method}</span>
          </div>
        )}
        {integ.baseline_hash && (
          <div className="text-[11px] text-slate-500 break-all">Baseline fingerprint (SHA-256): <span className="font-mono">{integ.baseline_hash.slice(0, 24)}…</span></div>
        )}
        {passport.open_change_requests > 0 && (
          <div className="text-[11px] text-amber-400">{passport.open_change_requests} change request(s) in progress</div>
        )}
        {passport.parcel_id && (
          <a href={`/api/interop/cityjson/parcels/${passport.parcel_id}`} className="inline-flex items-center gap-1.5 text-xs text-brand-400 hover:underline">
            <Download size={12} /> Download 3D model (CityJSON standard)
          </a>
        )}
        <p className="text-[10px] text-slate-600">{passport.disclaimer}</p>
      </div>
      <div className="mx-auto sm:mx-0 text-center">
        <div className="bg-white p-2 rounded-md inline-block"><QRCodeSVG value={passportUrl} size={112} /></div>
        <div className="text-[10px] text-slate-500 mt-1">Scan to verify</div>
      </div>
    </div>
  )
}
