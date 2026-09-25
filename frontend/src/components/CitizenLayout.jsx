import { useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { Menu, X, Landmark, Shield } from 'lucide-react'
import ThemeToggle from './ThemeToggle.jsx'

const navLinks = [
  { to: '/', label: 'Home' },
  { to: '/search', label: 'Search' },
  { to: '/map', label: '3D City Map' },
  { to: '/viewer', label: 'Unit Explorer' },
  { to: '/track', label: 'Track Grievance' },
]

export default function CitizenLayout() {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  return (
    <div className="min-h-screen flex flex-col">
      <div className="flex h-[3px] w-full flex-shrink-0 sticky top-0 z-40">
        <div className="flex-1 bg-brand-400" />
        <div className="flex-1 bg-[#F0EBD9]" />
        <div className="flex-1 bg-gold-500" />
      </div>
      <header className="sticky top-[3px] z-40 backdrop-blur-lg bg-ink-950/80 border-b border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2.5 group">
            <div className="w-9 h-9 rounded-full bg-brand-500 border-2 border-brand-400/40 flex items-center justify-center shadow-glow">
              <Landmark size={17} className="text-[#1E251C]" strokeWidth={2.25} />
            </div>
            <div className="leading-tight">
              <div className="font-display font-semibold text-sm text-white">Vasudha 3D</div>
              <div className="text-[10px] text-slate-500 tracking-wide">DoLR · Space Technology</div>
            </div>
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            {navLinks.map((l) => (
              <Link
                key={l.to}
                to={l.to}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  location.pathname === l.to
                    ? 'text-brand-400 bg-brand-500/10'
                    : 'text-slate-400 hover:text-white hover:bg-white/5'
                }`}
              >
                {l.label}
              </Link>
            ))}
            <Link to="/admin/login" className="ml-2 btn-secondary !py-2 !px-4 text-xs">
              <Shield size={14} /> Officer Login
            </Link>
            <ThemeToggle />
          </nav>

          <div className="md:hidden flex items-center gap-1">
            <ThemeToggle />
            <button className="text-slate-300" onClick={() => setOpen(!open)}>
              {open ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </div>

        {open && (
          <div className="md:hidden border-t border-white/5 px-4 py-3 flex flex-col gap-1 animate-fade-in">
            {navLinks.map((l) => (
              <Link
                key={l.to}
                to={l.to}
                onClick={() => setOpen(false)}
                className="px-3 py-2.5 rounded-lg text-sm font-medium text-slate-300 hover:bg-white/5"
              >
                {l.label}
              </Link>
            ))}
            <Link to="/admin/login" onClick={() => setOpen(false)} className="px-3 py-2.5 rounded-lg text-sm font-medium text-brand-400">
              Officer Login
            </Link>
          </div>
        )}
      </header>

      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
