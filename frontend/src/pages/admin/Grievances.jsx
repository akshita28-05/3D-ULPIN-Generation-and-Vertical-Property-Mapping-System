import { useEffect, useState } from 'react'
import api from '../../api/client'
import StatusBadge from '../../components/StatusBadge.jsx'
import { Loader2, MessageSquareWarning } from 'lucide-react'

const STATUS_OPTIONS = ['submitted', 'under_review', 'assigned', 'resolved', 'closed', 'rejected']

export default function Grievances() {
  const [grievances, setGrievances] = useState([])
  const [loading, setLoading] = useState(true)
  const [updatingId, setUpdatingId] = useState(null)

  useEffect(() => { load() }, [])

  function load() {
    setLoading(true)
    api.get('/grievances').then((res) => setGrievances(res.data)).finally(() => setLoading(false))
  }

  async function updateStatus(id, status) {
    setUpdatingId(id)
    try {
      const { data } = await api.patch(`/grievances/${id}`, { status })
      setGrievances((prev) => prev.map((g) => (g.id === id ? data : g)))
    } finally {
      setUpdatingId(null)
    }
  }

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <MessageSquareWarning size={22} className="text-orange-400" /> Grievances
      </h1>
      <p className="text-sm text-slate-500 mb-8">Citizen-reported issues requiring officer action.</p>

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}

      {!loading && grievances.length === 0 && (
        <div className="card p-12 text-center text-sm text-slate-500">No grievances submitted yet.</div>
      )}

      <div className="space-y-3">
        {grievances.map((g) => (
          <div key={g.id} className="card p-5">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <span className="font-mono text-sm text-white font-semibold">{g.grievance_number}</span>
              <StatusBadge status={g.status} />
            </div>
            <p className="text-xs text-slate-500 capitalize mb-1">{g.category.replace(/_/g, ' ')}</p>
            <p className="text-sm text-slate-300 mb-4">{g.description}</p>

            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-500">Update status:</label>
              <select
                value={g.status} disabled={updatingId === g.id}
                onChange={(e) => updateStatus(g.id, e.target.value)}
                className="input-field !py-1.5 !w-auto text-xs"
              >
                {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
              </select>
              {updatingId === g.id && <Loader2 size={13} className="animate-spin text-brand-400" />}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
