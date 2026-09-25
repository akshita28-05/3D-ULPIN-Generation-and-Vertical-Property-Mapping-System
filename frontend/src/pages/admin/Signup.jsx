import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext.jsx'
import api from '../../api/client'
import { Landmark, AlertCircle, Loader2, CheckCircle2 } from 'lucide-react'

export default function Signup() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }

    setLoading(true)
    try {
      const { data } = await api.post('/auth/signup', { name, email, password })
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      localStorage.setItem('role', data.role)
      localStorage.setItem('name', data.name)
      window.location.href = '/admin'
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create account.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-full bg-brand-500 border-2 border-brand-400/40 flex items-center justify-center mx-auto mb-4 shadow-glow">
            <Landmark size={24} className="text-[#1E251C]" strokeWidth={2.25} />
          </div>
          <h1 className="font-display text-xl font-bold text-white">Create Surveyor Account</h1>
          <p className="text-xs text-slate-500 mt-1">Self-registration creates a Surveyor account.</p>
        </div>

        <form onSubmit={handleSubmit} className="card p-6 space-y-4">
          {error && (
            <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
              <AlertCircle size={14} /> {error}
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2">Full Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} className="input-field" required />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2">Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="input-field" required />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2">Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="input-field" required minLength={8} />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2">Confirm Password</label>
            <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className="input-field" required />
          </div>
          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? <Loader2 className="animate-spin" size={16} /> : 'Create Account'}
          </button>
        </form>

        <div className="card p-4 mt-4 text-[11px] text-slate-500 flex items-start gap-2">
          <CheckCircle2 size={14} className="text-brand-400 flex-shrink-0 mt-0.5" />
          <span>
            New accounts are always created as <strong className="text-slate-300">Surveyor</strong>.
            Verifier and Admin roles are granted only by an existing Admin — this is enforced by the
            backend, not just hidden in this form.
          </span>
        </div>

        <p className="text-center text-xs text-slate-500 mt-6">
          Already have an account? <Link to="/admin/login" className="text-brand-400 hover:underline">Sign in</Link>
        </p>
        <Link to="/" className="block text-center text-xs text-slate-500 hover:text-white mt-3">← Back to public site</Link>
      </div>
    </div>
  )
}
