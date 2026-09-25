import { useEffect, useState } from 'react'
import api from '../../api/client'
import { Loader2, Mail, MailWarning, MailCheck, Info } from 'lucide-react'

const STATUS_STYLE = {
  sent: { icon: MailCheck, cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
  dev_logged: { icon: Info, cls: 'text-sky-400 bg-sky-500/10 border-sky-500/20' },
  queued: { icon: Mail, cls: 'text-amber-400 bg-amber-500/10 border-amber-500/20' },
  failed: { icon: MailWarning, cls: 'text-rose-400 bg-rose-500/10 border-rose-500/20' },
}

export default function Notifications() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/notifications').then((res) => setItems(res.data)).finally(() => setLoading(false))
  }, [])

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <Mail size={22} className="text-brand-400" /> Notifications
      </h1>
      <p className="text-sm text-slate-500 mb-2">Email notifications triggered by system events.</p>
      <div className="flex items-start gap-2 text-xs text-slate-500 bg-white/5 rounded-lg px-3 py-2.5 mb-8 max-w-2xl">
        <Info size={14} className="flex-shrink-0 mt-0.5" />
        <span>
          <strong className="text-slate-300">"Dev Logged"</strong> means no SMTP server is configured for
          this environment, so the email was recorded here instead of actually sent. Set
          <code className="mx-1 px-1 py-0.5 bg-white/10 rounded">SMTP_HOST</code>/
          <code className="mx-1 px-1 py-0.5 bg-white/10 rounded">SMTP_USER</code>/
          <code className="mx-1 px-1 py-0.5 bg-white/10 rounded">SMTP_PASSWORD</code> to enable real sending.
        </span>
      </div>

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}

      {!loading && items.length === 0 && (
        <div className="card p-12 text-center text-sm text-slate-500">No notifications yet.</div>
      )}

      <div className="card divide-y divide-white/5">
        {items.map((n) => {
          const style = STATUS_STYLE[n.status] || STATUS_STYLE.queued
          const Icon = style.icon
          return (
            <div key={n.id} className="p-4 sm:p-5 flex items-start gap-3">
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 border ${style.cls}`}>
                <Icon size={15} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
                  <span className="text-sm font-medium text-white truncate">{n.subject}</span>
                  <span className="text-[11px] text-slate-600 flex-shrink-0">{new Date(n.created_at).toLocaleString()}</span>
                </div>
                <div className="text-xs text-slate-500">
                  To: {n.recipient_email} · <span className="capitalize">{n.event_type.replace(/_/g, ' ')}</span>
                </div>
                {n.error_message && <div className="text-xs text-rose-400 mt-1">{n.error_message}</div>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
