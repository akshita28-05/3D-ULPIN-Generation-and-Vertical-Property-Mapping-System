import { useEffect, useState } from 'react'
import api from '../../api/client'
import { Loader2, Settings as SettingsIcon, CheckCircle2, XCircle, Database, Mail, Zap } from 'lucide-react'

export default function Settings() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/system/status').then((res) => setStatus(res.data)).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>

  return (
    <div className="animate-fade-in max-w-2xl">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <SettingsIcon size={22} className="text-brand-400" /> Settings
      </h1>
      <p className="text-sm text-slate-500 mb-8">Live system configuration — reflects the actual running backend, not static text.</p>

      <div className="card p-6 space-y-5">
        <StatusRow
          icon={Zap} label="Redis Caching & Rate Limiting"
          ok={status.redis_backed}
          okText="Connected — caching and rate limiting are Redis-backed"
          badText="Not connected — falling back to in-process store (fine for single-instance local dev only)"
        />
        <StatusRow
          icon={Mail} label="Email (SMTP)"
          ok={status.smtp_configured}
          okText="Configured — notifications will attempt real delivery"
          badText="Not configured — notifications are logged to the database instead of sent (see Notifications page)"
        />
        <div className="flex items-start gap-3 py-2">
          <div className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0">
            <Database size={15} className="text-slate-400" />
          </div>
          <div>
            <div className="text-sm font-medium text-white">Database</div>
            <div className="text-xs text-slate-500 mt-0.5 capitalize">{status.database_type} — {status.database_url_masked}</div>
          </div>
        </div>
      </div>

      <div className="card p-5 mt-4 text-xs text-slate-500 leading-relaxed">
        These values come from environment variables set when the backend starts (<code className="px-1 py-0.5 bg-white/10 rounded">REDIS_URL</code>,{' '}
        <code className="px-1 py-0.5 bg-white/10 rounded">SMTP_HOST</code>/<code className="px-1 py-0.5 bg-white/10 rounded">SMTP_USER</code>/<code className="px-1 py-0.5 bg-white/10 rounded">SMTP_PASSWORD</code>,{' '}
        <code className="px-1 py-0.5 bg-white/10 rounded">DATABASE_URL</code>) — this page is read-only and reports live status, it does not let you edit configuration at runtime. Change environment variables and restart the backend to update these.
      </div>
    </div>
  )
}

function StatusRow({ icon: Icon, label, ok, okText, badText }) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-white/5 last:border-0">
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${ok ? 'bg-emerald-500/10' : 'bg-amber-500/10'}`}>
        <Icon size={15} className={ok ? 'text-emerald-400' : 'text-amber-400'} />
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-white">{label}</span>
          {ok ? <CheckCircle2 size={14} className="text-emerald-400" /> : <XCircle size={14} className="text-amber-400" />}
        </div>
        <div className="text-xs text-slate-500 mt-0.5">{ok ? okText : badText}</div>
      </div>
    </div>
  )
}
