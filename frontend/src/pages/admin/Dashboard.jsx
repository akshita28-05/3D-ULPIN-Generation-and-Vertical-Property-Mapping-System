import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../api/client'
import { useAuth } from '../../context/AuthContext.jsx'
import {
  MapPin, Building2, Boxes, ShieldCheck, Clock, AlertTriangle,
  MessageSquareWarning, Cpu, Loader2,
} from 'lucide-react'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts'

const CARD_DEFS = [
  { key: 'total_parcels', label: 'Total Parcels', icon: MapPin, color: 'text-sky-400', to: '/admin/gis-map' },
  { key: 'total_buildings', label: 'Total Buildings', icon: Building2, color: 'text-violet-400', to: '/admin/records' },
  { key: 'total_units', label: 'Surveyed 3D Units', icon: Boxes, color: 'text-brand-400', to: '/admin/records' },
  { key: 'verified_units', label: 'Verified Properties', icon: ShieldCheck, color: 'text-emerald-400', to: '/admin/records?status=approved' },
  { key: 'pending_units', label: 'Pending Reviews', icon: Clock, color: 'text-amber-400', to: '/admin/review', roles: ['verifier', 'admin'] },
  { key: 'active_conflicts', label: 'Active Conflicts', icon: AlertTriangle, color: 'text-rose-400', to: '/admin/conflicts', roles: ['verifier', 'admin'] },
  { key: 'open_grievances', label: 'Open Grievances', icon: MessageSquareWarning, color: 'text-orange-400', to: '/admin/grievances' },
  { key: 'processing_jobs_running', label: 'Processing Jobs', icon: Cpu, color: 'text-fuchsia-400', to: '/admin/ingestion', roles: ['surveyor', 'admin'] },
]

const PIE_COLORS = ['#2dd4bf', '#f59e0b', '#f43f5e']

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const navigate = useNavigate()
  const { user } = useAuth()

  useEffect(() => {
    api.get('/analytics')
      .then((res) => setStats(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Could not load dashboard stats.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="flex justify-center py-24"><Loader2 className="animate-spin text-brand-400" size={28} /></div>

  const pieData = stats ? [
    { name: 'Verified', value: stats.verified_units },
    { name: 'Pending', value: stats.pending_units },
    { name: 'Rejected', value: stats.rejected_units },
  ] : []

  const barData = stats ? [
    { name: 'Conflicts', value: stats.active_conflicts },
    { name: 'Grievances', value: stats.open_grievances },
    { name: 'Processing', value: stats.processing_jobs_running },
  ] : []

  function goTo(card) {
    if (card.roles && !card.roles.includes(user?.role) && user?.role !== 'admin') {
      navigate('/admin/records')
      return
    }
    navigate(card.to)
  }

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1">Dashboard</h1>
      <p className="text-sm text-slate-500 mb-8">System-wide overview of the 3D ULPIN pipeline.</p>

      {error && (
        <div className="card p-4 mb-6 text-sm text-rose-400 bg-rose-500/5 border-rose-500/15">{error}</div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {CARD_DEFS.map((c) => (
          <button
            key={c.key}
            onClick={() => goTo(c)}
            className="card p-5 text-left card-hover cursor-pointer"
          >
            <c.icon className={`${c.color} mb-3`} size={20} />
            <div className="text-2xl font-display font-bold text-white">{stats?.[c.key] ?? 0}</div>
            <div className="text-xs text-slate-500 mt-1">{c.label}</div>
          </button>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Verification Status</h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={80} paddingAngle={3}>
                {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: '#0f1830', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex justify-center gap-4 mt-2">
            {pieData.map((d, i) => (
              <div key={d.name} className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="w-2 h-2 rounded-full" style={{ background: PIE_COLORS[i] }} /> {d.name}
              </div>
            ))}
          </div>
        </div>

        <div className="card p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Operational Activity</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={barData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={{ stroke: '#1e293b' }} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={{ stroke: '#1e293b' }} allowDecimals={false} />
              <Tooltip contentStyle={{ background: '#0f1830', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="value" fill="#2dd4bf" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card p-5 mt-4 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">Export Verified Records</h3>
          <p className="text-xs text-slate-500">Download all approved units in a portable format.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a href="/api/export/units.geojson" className="btn-secondary !py-2 text-xs">GeoJSON</a>
          <a href="/api/export/units.csv" className="btn-secondary !py-2 text-xs">CSV</a>
          <a href="/api/export/svamitva-format" className="btn-secondary !py-2 text-xs">SVAMITVA Format</a>
        </div>
      </div>
    </div>
  )
}
