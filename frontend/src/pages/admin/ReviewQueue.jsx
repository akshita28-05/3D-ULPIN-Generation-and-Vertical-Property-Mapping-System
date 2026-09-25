import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../api/client'
import StatusBadge from '../../components/StatusBadge.jsx'
import { Loader2, ClipboardCheck, ChevronRight, Inbox } from 'lucide-react'

export default function ReviewQueue() {
  const [units, setUnits] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('/review/queue')
      .then((res) => setUnits(res.data))
      .catch(() => setError('Could not load the review queue. You may not have verifier permissions.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <ClipboardCheck size={22} className="text-brand-400" /> Review Queue
      </h1>
      <p className="text-sm text-slate-500 mb-8">AI-generated units awaiting human verification.</p>

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}

      {error && (
        <div className="card p-8 text-center text-sm text-rose-400">{error}</div>
      )}

      {!loading && !error && units.length === 0 && (
        <div className="card p-12 text-center">
          <Inbox className="mx-auto text-slate-700 mb-3" size={32} />
          <p className="text-sm text-slate-500">No units are currently pending review.</p>
        </div>
      )}

      {!loading && units.length > 0 && (
        <div className="card overflow-hidden">
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/5 text-left text-xs text-slate-500">
                  <th className="px-5 py-3 font-medium">3D ULPIN</th>
                  <th className="px-5 py-3 font-medium">Type</th>
                  <th className="px-5 py-3 font-medium">AI Confidence</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {units.map((u) => (
                  <tr key={u.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                    <td className="px-5 py-3.5 text-white font-mono text-xs">{u.ulpin_3d}</td>
                    <td className="px-5 py-3.5 text-slate-400 capitalize">{u.parcel_type?.replace('_', ' ')}</td>
                    <td className="px-5 py-3.5 text-slate-400">{u.ai_confidence ? `${(u.ai_confidence * 100).toFixed(0)}%` : '—'}</td>
                    <td className="px-5 py-3.5"><StatusBadge status={u.verification_status} /></td>
                    <td className="px-5 py-3.5 text-right">
                      <Link to={`/admin/review/${u.id}`} className="text-brand-400 text-xs font-medium inline-flex items-center gap-1 hover:underline">
                        Review <ChevronRight size={13} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="md:hidden divide-y divide-white/5">
            {units.map((u) => (
              <Link key={u.id} to={`/admin/review/${u.id}`} className="block p-4 hover:bg-white/[0.02]">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-white font-mono text-xs break-all pr-2">{u.ulpin_3d}</span>
                  <ChevronRight size={15} className="text-slate-600 flex-shrink-0" />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500 capitalize">{u.parcel_type?.replace('_', ' ')}</span>
                  <StatusBadge status={u.verification_status} />
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
