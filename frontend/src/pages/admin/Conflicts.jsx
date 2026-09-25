import { useEffect, useState } from 'react'
import api from '../../api/client'
import StatusBadge from '../../components/StatusBadge.jsx'
import { Loader2, AlertTriangle, CheckCircle2, ShieldCheck } from 'lucide-react'

export default function Conflicts() {
  const [conflicts, setConflicts] = useState([])
  const [loading, setLoading] = useState(true)
  const [resolvingId, setResolvingId] = useState(null)

  useEffect(() => { load() }, [])

  function load() {
    setLoading(true)
    api.get('/review/conflicts').then((res) => setConflicts(res.data)).finally(() => setLoading(false))
  }

  async function resolve(id) {
    setResolvingId(id)
    try {
      await api.post(`/review/conflicts/${id}/resolve`)
      setConflicts((prev) => prev.filter((c) => c.id !== id))
    } finally {
      setResolvingId(null)
    }
  }

  const grouped = conflicts.reduce((acc, c) => {
    acc[c.severity] = acc[c.severity] || []
    acc[c.severity].push(c)
    return acc
  }, {})

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <AlertTriangle size={22} className="text-rose-400" /> Conflict & Topology Dashboard
      </h1>
      <p className="text-sm text-slate-500 mb-8">Unresolved spatial validation flags across all buildings.</p>

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}

      {!loading && conflicts.length === 0 && (
        <div className="card p-12 text-center">
          <ShieldCheck className="mx-auto text-emerald-500/60 mb-3" size={32} />
          <p className="text-sm text-slate-500">No active conflicts. All topology checks pass.</p>
        </div>
      )}

      {!loading && ['HIGH', 'MEDIUM', 'LOW'].map((sev) => (
        grouped[sev] && (
          <div key={sev} className="mb-6">
            <h3 className="text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wide">{sev} severity</h3>
            <div className="space-y-2">
              {grouped[sev].map((c) => (
                <div key={c.id} className="card p-4 flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3 min-w-0">
                    <StatusBadge status={c.severity} />
                    <div className="min-w-0">
                      <p className="text-sm text-slate-200 break-words">{c.message}</p>
                      <p className="text-[11px] text-slate-600 mt-1 capitalize">{c.check_type.replace(/_/g, ' ')}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => resolve(c.id)} disabled={resolvingId === c.id}
                    className="btn-secondary !py-1.5 !px-3 text-xs flex-shrink-0"
                  >
                    {resolvingId === c.id ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />} Resolve
                  </button>
                </div>
              ))}
            </div>
          </div>
        )
      ))}
    </div>
  )
}
