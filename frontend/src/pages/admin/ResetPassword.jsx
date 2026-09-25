import { useState } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import api from '../../api/client'
import { Landmark, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'

export default function ResetPassword() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    if (password !== confirm) { setError('Passwords do not match.'); return }
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }

    setSubmitting(true)
    try {
      await api.post('/auth/reset-password', { token, new_password: password })
      setDone(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not reset password. The link may have expired.')
    } finally {
      setSubmitting(false)
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="card p-6 max-w-sm text-center">
          <AlertCircle className="mx-auto text-rose-400 mb-3" size={28} />
          <p className="text-sm text-slate-300 mb-4">No reset token found. Use the link from your reset email.</p>
          <Link to="/admin/forgot-password" className="btn-secondary text-sm">Request a New Link</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-full bg-brand-500 border-2 border-brand-400/40 flex items-center justify-center mx-auto mb-4 shadow-glow">
            <Landmark size={24} className="text-[#1E251C]" strokeWidth={2.25} />
          </div>
          <h1 className="font-display text-xl font-bold text-white">Set New Password</h1>
        </div>

        {done ? (
          <div className="card p-6 text-center">
            <CheckCircle2 className="mx-auto text-emerald-400 mb-3" size={28} />
            <p className="text-sm text-slate-300 mb-4">Password reset successfully.</p>
            <button onClick={() => navigate('/admin/login')} className="btn-primary text-sm">Sign In</button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="card p-6 space-y-4">
            {error && (
              <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
                <AlertCircle size={14} /> {error}
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2">New Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="input-field" required minLength={8} />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2">Confirm Password</label>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className="input-field" required />
            </div>
            <button type="submit" disabled={submitting} className="btn-primary w-full">
              {submitting ? <Loader2 className="animate-spin" size={16} /> : 'Reset Password'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
