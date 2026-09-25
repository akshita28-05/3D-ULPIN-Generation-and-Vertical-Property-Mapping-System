import { useEffect, useState } from 'react'
import api from '../../api/client'
import { Loader2, History, Hash } from 'lucide-react'

export default function AuditLog() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('/audit')
      .then((res) => setLogs(res.data))
      .catch(() => setError('Audit log access requires admin permissions.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <History size={22} className="text-brand-400" /> Audit Log
      </h1>
      <p className="text-sm text-slate-500 mb-8">
        Tamper-evident record of every verification action. Each entry is hashed (SHA-256) from
        its previous value, new value, actor, and timestamp.
      </p>

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}
      {error && <div className="card p-8 text-center text-sm text-rose-400">{error}</div>}

      {!loading && !error && (
        <div className="card divide-y divide-white/5">
          {logs.length === 0 && <div className="p-8 text-center text-sm text-slate-500">No audit entries yet.</div>}
          {logs.map((log) => (
            <div key={log.id} className="p-4 sm:p-5">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <span className="text-sm font-medium text-white capitalize">{log.action.replace(/[._]/g, ' ')}</span>
                <span className="text-[11px] text-slate-600">{new Date(log.created_at).toLocaleString()}</span>
              </div>
              <div className="text-xs text-slate-500 mb-2">
                {log.entity_type} · {log.entity_id.slice(0, 8)}…
              </div>
              <div className="flex items-center gap-1.5 text-[11px] text-slate-600 font-mono">
                <Hash size={11} /> {log.record_hash.slice(0, 32)}…
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
