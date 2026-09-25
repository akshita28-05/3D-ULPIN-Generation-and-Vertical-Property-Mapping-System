import { useEffect, useState } from 'react'
import api from '../../api/client'
import { useAuth } from '../../context/AuthContext.jsx'
import { Loader2, TrendingUp, Calendar, ArrowRight, RefreshCw } from 'lucide-react'

export default function ChangeDetection() {
  const [changes, setChanges] = useState([])
  const [loading, setLoading] = useState(true)
  const [sweeping, setSweeping] = useState(false)
  const [sweepResult, setSweepResult] = useState(null)
  const { user } = useAuth()

  function load() {
    setLoading(true)
    api.get('/change-detection').then((res) => setChanges(res.data)).finally(() => setLoading(false))
  }

  useEffect(load, [])

  function runSweep() {
    setSweeping(true)
    setSweepResult(null)
    api
      .post('/change-detection/sweep')
      .then((res) => {
        setSweepResult(res.data)
        load()
      })
      .catch((err) => setSweepResult({ error: err.response?.data?.detail || 'Sweep failed.' }))
      .finally(() => setSweeping(false))
  }

  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-1">
        <h1 className="font-display text-2xl font-bold text-white flex items-center gap-2">
          <TrendingUp size={22} className="text-brand-400" /> Change Detection
        </h1>
        {(user?.role === 'admin' || user?.role === 'verifier') && (
          <button
            onClick={runSweep}
            disabled={sweeping}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-white px-3 py-1.5 rounded-lg hover:bg-white/5 disabled:opacity-50"
          >
            {sweeping ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Run sweep now
          </button>
        )}
      </div>
      <p className="text-sm text-slate-500 mb-4">
        Comparing satellite/imagery passes across two dates to flag potential unauthorized
        construction or floor changes.
      </p>

      {sweepResult && !sweepResult.error && (
        <div className="mb-6 text-xs text-slate-400 bg-white/5 rounded-lg px-4 py-2.5">
          Checked {sweepResult.buildings_checked} building(s) with uploaded imagery/point clouds --
          {' '}{sweepResult.flagged} flagged.
        </div>
      )}
      {sweepResult?.error && (
        <div className="mb-6 text-xs text-rose-400 bg-rose-500/10 rounded-lg px-4 py-2.5">{sweepResult.error}</div>
      )}

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}

      {!loading && changes.length === 0 && (
        <div className="card p-12 text-center text-sm text-slate-500">No change-detection records yet.</div>
      )}

      <div className="grid sm:grid-cols-2 gap-4">
        {changes.map((c) => (
          <div key={c.id} className="card p-5">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-4">
              <Calendar size={13} /> {c.date_before}
              <ArrowRight size={13} className="text-slate-600" />
              <Calendar size={13} /> {c.date_after}
            </div>
            <p className="text-sm text-slate-200 mb-4">{c.description}</p>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 rounded-full bg-white/10 overflow-hidden">
                <div className="h-full bg-amber-400" style={{ width: `${(c.confidence * 100).toFixed(0)}%` }} />
              </div>
              <span className="text-xs text-amber-400 font-medium flex-shrink-0">{(c.confidence * 100).toFixed(0)}% confidence</span>
            </div>
          </div>
        ))}
      </div>

      <p className="text-[11px] text-slate-600 mt-6">
        Records above either came from seed data or from a real sweep: re-running footprint/floor
        extraction on a building's current imagery and comparing it against its last recorded
        snapshot (15%+ area drift or an added floor). Automatic sweeps can also run on a schedule
        via CHANGE_DETECTION_ENABLED -- see backend/.env.example.
      </p>
    </div>
  )
}

