const STYLES = {
  OBSERVED: { cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20', label: 'Observed' },
  PREDICTED: { cls: 'bg-amber-500/10 text-amber-400 border-amber-500/20', label: 'Predicted' },
  NOT_DETERMINABLE: { cls: 'bg-slate-500/10 text-slate-400 border-slate-500/20', label: 'Not determinable' },
}

export default function EvidenceBadge({ state, method, small = false }) {
  const s = STYLES[state] || STYLES.NOT_DETERMINABLE
  return (
    <span
      title={method ? `Floor count: ${method}` : undefined}
      className={`inline-flex items-center rounded-full border font-medium ${small ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs'} ${s.cls}`}
    >
      {s.label}
    </span>
  )
}
