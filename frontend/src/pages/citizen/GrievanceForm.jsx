import { useState } from 'react'
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom'
import api from '../../api/client'
import { AlertCircle, CheckCircle2, ArrowLeft } from 'lucide-react'

const CATEGORIES = [
  { value: 'boundary_discrepancy', label: 'Boundary Discrepancy' },
  { value: 'ownership_discrepancy', label: 'Ownership Discrepancy' },
  { value: 'wrong_floor', label: 'Wrong Floor' },
  { value: 'wrong_unit', label: 'Wrong Unit' },
  { value: 'incorrect_property_information', label: 'Incorrect Property Information' },
  { value: 'other', label: 'Other' },
]

export default function GrievanceForm() {
  const { unitId, buildingId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const floorPrefill = location.state?.prefill || ''
  const [category, setCategory] = useState('')
  const [description, setDescription] = useState(floorPrefill)
  const [contact, setContact] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!category || !description.trim()) {
      setError('Please select a category and describe the issue.')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      const { data } = await api.post('/grievances', {
        unit_id: unitId || null, building_id: buildingId || null, category, description, reporter_contact: contact || null,
      })
      setResult(data)
    } catch {
      setError('Something went wrong submitting your report. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <CheckCircle2 className="mx-auto text-emerald-400 mb-4" size={40} />
        <h1 className="font-display text-xl font-bold text-white mb-2">Report Submitted</h1>
        <p className="text-sm text-slate-400 mb-6">Your grievance number is:</p>
        <div className="card px-6 py-4 inline-block mb-8">
          <span className="font-display font-bold text-brand-400 text-lg">{result.grievance_number}</span>
        </div>
        <p className="text-xs text-slate-500 mb-8">Save this number to track the status of your report.</p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link to="/track" className="btn-primary text-sm">Track This Grievance</Link>
          <Link to="/" className="btn-secondary text-sm">Back to Home</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-lg mx-auto px-4 sm:px-6 py-10">
      <button onClick={() => navigate(-1)} className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-white mb-6">
        <ArrowLeft size={14} /> Back
      </button>

      <h1 className="font-display text-2xl font-bold text-white mb-1">Report an Issue</h1>
      <p className="text-sm text-slate-400 mb-8">Flag a discrepancy with this property record for officer review.</p>

      <form onSubmit={handleSubmit} className="card p-6 space-y-5">
        {error && (
          <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
            <AlertCircle size={14} /> {error}
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-slate-400 mb-2">Category</label>
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="input-field">
            <option value="">Select an issue type…</option>
            {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-400 mb-2">Description</label>
          <textarea
            value={description} onChange={(e) => setDescription(e.target.value)} rows={5}
            placeholder="Describe the issue in detail…" className="input-field resize-none"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-400 mb-2">Contact (optional)</label>
          <input value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Email or phone for follow-up" className="input-field" />
        </div>

        <button type="submit" disabled={submitting} className="btn-primary w-full">
          {submitting ? 'Submitting…' : 'Submit Report'}
        </button>
      </form>
    </div>
  )
}
