import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext.jsx'
import { Landmark, AlertCircle, Loader2 } from 'lucide-react'

export default function AdminLogin() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(email, password)
      navigate('/admin')
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid email or password.')
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
          <h1 className="font-display text-xl font-bold text-white">Officer Sign In</h1>
          <p className="text-xs text-slate-500 mt-1">Surveyor · Verifier · Admin access only</p>
        </div>

        <form onSubmit={handleSubmit} className="card p-6 space-y-4">
          {error && (
            <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
              <AlertCircle size={14} /> {error}
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2">Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="input-field" placeholder="you@sih.demo" required />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2">Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="input-field" required />
          </div>
          <div className="text-right -mt-2">
            <Link to="/admin/forgot-password" className="text-xs text-slate-500 hover:text-brand-400">Forgot password?</Link>
          </div>
          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? <Loader2 className="animate-spin" size={16} /> : 'Sign In'}
          </button>
        </form>

        <div className="card p-4 mt-4 text-[11px] text-slate-500 space-y-1">
          <p className="font-medium text-slate-400 mb-1.5">Demo credentials</p>
          <p>Surveyor: surveyor@sih.demo / Surveyor@123</p>
          <p>Verifier: verifier@sih.demo / Verifier@123</p>
          <p>Admin: admin@sih.demo / Admin@123</p>
        </div>

        <p className="text-center text-xs text-slate-500 mt-6">
          New surveyor? <Link to="/admin/signup" className="text-brand-400 hover:underline">Create an account</Link>
        </p>
        <Link to="/" className="block text-center text-xs text-slate-500 hover:text-white mt-3">← Back to public site</Link>
      </div>
    </div>
  )
}
