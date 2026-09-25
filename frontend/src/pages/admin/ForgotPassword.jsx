import { useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../api/client'
import { Landmark, Loader2, CheckCircle2 } from 'lucide-react'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await api.post('/auth/forgot-password', { email })
    } finally {
      setSubmitting(false)
      setDone(true)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-full bg-brand-500 border-2 border-brand-400/40 flex items-center justify-center mx-auto mb-4 shadow-glow">
            <Landmark size={24} className="text-[#1E251C]" strokeWidth={2.25} />
          </div>
          <h1 className="font-display text-xl font-bold text-white">Reset Password</h1>
          <p className="text-xs text-slate-500 mt-1">Enter your account email to receive a reset link.</p>
        </div>

        {done ? (
          <div className="card p-6 text-center">
            <CheckCircle2 className="mx-auto text-emerald-400 mb-3" size={28} />
            <p className="text-sm text-slate-300">If an account exists for this email, a reset link has been sent.</p>
            <Link to="/admin/login" className="btn-secondary text-sm mt-6 inline-flex">Back to Sign In</Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="card p-6 space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="input-field" required />
            </div>
            <button type="submit" disabled={submitting} className="btn-primary w-full">
              {submitting ? <Loader2 className="animate-spin" size={16} /> : 'Send Reset Link'}
            </button>
          </form>
        )}

        <p className="text-center text-xs text-slate-500 mt-6">
          <Link to="/admin/login" className="text-brand-400 hover:underline">Back to sign in</Link>
        </p>
      </div>
    </div>
  )
}
