const styles = {
  approved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  pending_review: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  ai_generated: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  rejected: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  reprocessing: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
  HIGH: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  MEDIUM: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  LOW: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  submitted: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  under_review: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  assigned: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
  resolved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  closed: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
}

const labels = {
  approved: 'Verified', pending_review: 'Pending Review', ai_generated: 'AI Generated',
  rejected: 'Rejected', reprocessing: 'Reprocessing',
}

export default function StatusBadge({ status }) {
  const cls = styles[status] || 'bg-slate-500/10 text-slate-400 border-slate-500/20'
  const label = labels[status] || status?.replace(/_/g, ' ')
  return <span className={`badge border capitalize ${cls}`}>{label}</span>
}
