import { useState } from 'react'
import api from '../../api/client'
import StatusBadge from '../../components/StatusBadge.jsx'
import { Search, AlertCircle } from 'lucide-react'

const STEPS = ['submitted', 'under_review', 'assigned', 'resolved', 'closed']

export default function GrievanceTrack() {
  const [number, setNumber] = useState('')
  const [grievance, setGrievance] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleSearch(e) {
    e.preventDefault()
    if (!number.trim()) return
    setLoading(true)
    setError(null)
    setGrievance(null)
    try {
      const { data } = await api.get(`/grievances/track/${number.trim()}`)
      setGrievance(data)
    } catch {
      setError('No grievance found with that number. Please check and try again.')
    } finally {
      setLoading(false)
    }
  }

  const currentStepIndex = grievance ? STEPS.indexOf(grievance.status) : -1

  return (
    <div className="max-w-lg mx-auto px-4 sm:px-6 py-12 sm:py-16">
      <h1 className="font-display text-2xl font-bold text-white mb-1">Track Your Grievance</h1>
      <p className="text-sm text-slate-400 mb-8">Enter your grievance number to check its status.</p>

      <form onSubmit={handleSearch} className="flex gap-2 mb-8">
        <input
          value={number} onChange={(e) => setNumber(e.target.value)}
          placeholder="GRV-2026-00001" className="input-field flex-1"
        />
        <button type="submit" className="btn-primary !px-4" disabled={loading}>
          <Search size={16} />
        </button>
      </form>

      {error && (
        <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {grievance && (
        <div className="card p-6 animate-fade-in">
          <div className="flex items-center justify-between mb-5">
            <span className="font-display font-bold text-white">{grievance.grievance_number}</span>
            <StatusBadge status={grievance.status} />
          </div>

          <div className="mb-6">
            <div className="flex justify-between mb-2">
              {STEPS.map((s, i) => (
                <div key={s} className={`flex-1 h-1.5 rounded-full mx-0.5 ${i <= currentStepIndex ? 'bg-brand-500' : 'bg-white/10'}`} />
              ))}
            </div>
            <div className="flex justify-between text-[10px] text-slate-500 capitalize">
              {STEPS.map((s) => <span key={s} className="w-12 text-center -ml-2 first:ml-0">{s.replace('_', ' ')}</span>)}
            </div>
          </div>

          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500 text-xs">Category</span>
              <span className="text-white capitalize">{grievance.category.replace(/_/g, ' ')}</span>
            </div>
            <div className="pt-2 border-t border-white/5">
              <span className="text-slate-500 text-xs block mb-1">Description</span>
              <span className="text-slate-300 text-sm">{grievance.description}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
