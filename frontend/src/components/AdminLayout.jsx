import { useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import {
  LayoutDashboard, UploadCloud, ClipboardCheck, AlertTriangle, Cable,
  MessageSquareWarning, History, Menu, X, LogOut, Landmark, PlusCircle, TrendingUp,
  ListTree, Mail, MapPin, Users, Settings as SettingsIcon, Box, ScanSearch, GitPullRequest,
} from 'lucide-react'
import ThemeToggle from './ThemeToggle.jsx'

const links = [
  { to: '/admin', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { to: '/admin/create', label: 'Create Parcel / Building', icon: PlusCircle, roles: ['surveyor', 'admin'] },
  { to: '/admin/records', label: 'All ULPIN Records', icon: ListTree },
  { to: '/admin/gis-map', label: 'GIS Map (3D)', icon: MapPin },
  { to: '/admin/viewer', label: '3D Viewer', icon: Box, roles: ['admin', 'verifier', 'surveyor'] },
  { to: '/admin/ingestion', label: 'Data Ingestion', icon: UploadCloud, roles: ['surveyor', 'admin'] },
  { to: '/admin/pending-model-run', label: 'Pending Model Runs', icon: ScanSearch, roles: ['surveyor', 'verifier', 'admin'] },
  { to: '/admin/review', label: 'Review Queue', icon: ClipboardCheck, roles: ['verifier', 'admin'] },
  { to: '/admin/conflicts', label: 'Conflicts', icon: AlertTriangle, roles: ['verifier', 'admin'] },
  { to: '/admin/change-requests', label: 'Change Requests', icon: GitPullRequest, roles: ['surveyor', 'verifier', 'admin'] },
  { to: '/admin/underground', label: 'Underground & Air-Rights', icon: Cable },
  { to: '/admin/change-detection', label: 'Change Detection', icon: TrendingUp },
  { to: '/admin/grievances', label: 'Grievances', icon: MessageSquareWarning },
  { to: '/admin/notifications', label: 'Notifications', icon: Mail, roles: ['admin'] },
  { to: '/admin/users', label: 'Users', icon: Users, roles: ['admin'] },
  { to: '/admin/audit', label: 'Audit Log', icon: History, roles: ['admin'] },
  { to: '/admin/settings', label: 'Settings', icon: SettingsIcon, roles: ['admin'] },
]

export default function AdminLayout() {
  const [open, setOpen] = useState(false)
  const { user, logout } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  const visibleLinks = links.filter((l) => !l.roles || l.roles.includes(user?.role))

  function handleLogout() {
    logout()
    navigate('/admin/login')
  }

  const SidebarContent = (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-white/5">
        <div className="w-9 h-9 rounded-full bg-brand-500 border-2 border-brand-400/40 flex items-center justify-center">
          <Landmark size={17} className="text-[#1E251C]" strokeWidth={2.25} />
        </div>
        <div className="leading-tight">
          <div className="font-display font-semibold text-sm text-white">Vasudha 3D</div>
          <div className="text-[10px] text-slate-500">Admin Console</div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {visibleLinks.map((l) => {
          const active = l.exact ? location.pathname === l.to : location.pathname.startsWith(l.to)
          const Icon = l.icon
          return (
            <Link
              key={l.to}
              to={l.to}
              onClick={() => setOpen(false)}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                active ? 'bg-brand-500/15 text-brand-400' : 'text-slate-400 hover:bg-white/5 hover:text-white'
              }`}
            >
              <Icon size={17} />
              {l.label}
            </Link>
          )
        })}
      </nav>

      <div className="p-4 border-t border-white/5">
        <div className="flex items-center justify-between px-1 mb-3">
          <div>
            <div className="text-sm font-medium text-white">{user?.name}</div>
            <div className="text-[11px] text-slate-500 capitalize">{user?.role}</div>
          </div>
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <span className="badge bg-brand-500/10 text-brand-400 border border-brand-500/20 capitalize">{user?.role}</span>
          </div>
        </div>
        <button onClick={handleLogout} className="btn-secondary w-full !py-2 text-xs">
          <LogOut size={14} /> Sign Out
        </button>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen flex flex-col">
      <div className="flex h-[3px] w-full flex-shrink-0">
        <div className="flex-1 bg-brand-400" />
        <div className="flex-1 bg-[#F0EBD9]" />
        <div className="flex-1 bg-gold-500" />
      </div>
      <div className="flex flex-1 min-h-0">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex lg:w-64 flex-shrink-0 border-r border-white/5 bg-ink-900/60">
        {SidebarContent}
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside className="relative w-72 bg-ink-900 border-r border-white/10 animate-fade-in">
            {SidebarContent}
          </aside>
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <header className="lg:hidden sticky top-0 z-30 h-14 flex items-center justify-between px-4 bg-ink-950/90 backdrop-blur border-b border-white/5">
          <button onClick={() => setOpen(true)} className="text-slate-300"><Menu size={22} /></button>
          <span className="font-display font-semibold text-sm text-white">Vasudha 3D</span>
          <div className="w-[22px]" />
        </header>
        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-[1400px] w-full mx-auto">
          <Outlet />
        </main>
      </div>
      </div>
    </div>
  )
}
