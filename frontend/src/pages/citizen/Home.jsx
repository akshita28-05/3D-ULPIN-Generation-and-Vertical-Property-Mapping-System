import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import api from '../../api/client'
import {
  Search, Boxes, ArrowRight, Layers, ShieldCheck, Cable, TrendingUp,
  Building2, MapPin, Users, CheckCircle2,
} from 'lucide-react'

function StatCard({ icon: Icon, value, label }) {
  return (
    <div className="card p-5 text-center">
      <Icon className="mx-auto mb-2 text-brand-400" size={22} />
      <div className="text-2xl font-display font-bold text-white">{value}</div>
      <div className="text-xs text-slate-500 mt-1">{label}</div>
    </div>
  )
}

export default function Home() {
  const [stats, setStats] = useState(null)

  useEffect(() => {
    api.get('/parcels', { params: { limit: 5000 } }).then((res) => {
      const parcels = res.data
      const buildings = parcels.reduce((a, p) => a + p.buildings.length, 0)
      const units = parcels.reduce((a, p) => a + p.buildings.reduce((b, bd) => b + bd.floors.reduce((c, f) => c + f.units.length, 0), 0), 0)
      setStats({ parcels: parcels.length, buildings, units })
    }).catch(() => {})
  }, [])

  return (
    <div>
      <section className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pt-16 sm:pt-24 pb-16 sm:pb-20 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-brand-500/20 bg-brand-500/5 text-brand-400 text-xs font-medium mb-6">
            <Boxes size={14} /> Smart India Hackathon 2026 · SIH26011
          </div>
          <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl font-bold text-white leading-tight max-w-4xl mx-auto">
            India's Next Generation <span className="text-brand-400">3D Property Identity</span>
          </h1>
          <p className="mt-6 text-base sm:text-lg text-slate-400 max-w-2xl mx-auto">
            Extending the existing 2D land parcel system into a verified, volumetric cadastre —
            one unique 3D ULPIN for every floor, unit, and underground asset.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link to="/viewer" className="btn-primary !px-7 !py-3 text-sm w-full sm:w-auto">
              Explore 3D Map <ArrowRight size={16} />
            </Link>
            <Link to="/search" className="btn-secondary !px-7 !py-3 text-sm w-full sm:w-auto">
              <Search size={16} /> Search Property
            </Link>
          </div>

          <div className="mt-16 flex items-center justify-center gap-3 sm:gap-6 flex-wrap">
            {[
              { label: '2D Land Parcel', icon: MapPin },
              { label: '3D Property', icon: Boxes },
              { label: 'Verified 3D ULPIN', icon: ShieldCheck },
            ].map((step, i, arr) => (
              <div key={step.label} className="flex items-center gap-3 sm:gap-6">
                <div className="card px-5 py-4 flex flex-col items-center gap-2 w-32 sm:w-40">
                  <step.icon size={20} className="text-brand-400" />
                  <span className="text-xs font-medium text-slate-300 text-center">{step.label}</span>
                </div>
                {i < arr.length - 1 && <ArrowRight className="text-slate-600 flex-shrink-0" size={18} />}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 sm:px-6 -mt-4 mb-20">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard icon={MapPin} value={stats?.parcels ?? '—'} label="Parcels Mapped" />
          <StatCard icon={Building2} value={stats?.buildings ?? '—'} label="Buildings" />
          <StatCard icon={Layers} value={stats?.units ?? '—'} label="3D Property Units" />
          <StatCard icon={Users} value="3" label="Verification Roles" />
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-16 border-t border-white/5">
        <h2 className="font-display text-2xl sm:text-3xl font-bold text-white mb-4">The Problem</h2>
        <p className="text-slate-400 max-w-3xl leading-relaxed">
          Conventional 2D land record systems identify surface-level parcels only. They cannot
          uniquely represent ownership in multi-storey apartments, underground infrastructure,
          elevated transport corridors, parking spaces, air-rights, or subsurface utility networks —
          leading to ownership ambiguity and planning conflicts as cities grow vertically.
        </p>
      </section>

      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-16 border-t border-white/5">
        <h2 className="font-display text-2xl sm:text-3xl font-bold text-white mb-8">How 3D Cadastral Mapping Works</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { n: '01', t: 'Data Capture', d: 'Drone imagery, LiDAR, GNSS, floor plans, and DEM/DSM are collected for the parcel.' },
            { n: '02', t: 'AI Processing', d: 'Building extraction, floor segmentation, and vertical parcel delineation generate 3D geometry.' },
            { n: '03', t: '3D ULPIN Generation', d: 'Each unit receives a unique ID extending the existing 14-digit ULPIN format.' },
            { n: '04', t: 'Human Verification', d: 'A trained verifier reviews and approves every AI-generated record before it goes public.' },
          ].map((s) => (
            <div key={s.n} className="card p-5">
              <div className="text-brand-500/40 font-display font-bold text-2xl mb-2">{s.n}</div>
              <div className="font-semibold text-white text-sm mb-1.5">{s.t}</div>
              <div className="text-xs text-slate-500 leading-relaxed">{s.d}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-16 border-t border-white/5">
        <div className="card p-6 sm:p-8 grid sm:grid-cols-2 gap-8 items-center">
          <div>
            <div className="inline-flex items-center gap-2 text-violet-400 text-xs font-medium mb-3">
              <Cable size={14} /> Differentiator
            </div>
            <h3 className="font-display text-xl sm:text-2xl font-bold text-white mb-3">Underground Infrastructure Mapping</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Water, electricity, sewer, telecom, and gas networks are mapped as a dedicated 3D
              layer beneath every parcel, with automated conflict detection against building
              foundations — flagging clashes like a water pipeline intersecting a basement volume
              before construction disputes happen.
            </p>
          </div>
          <div className="flex flex-col gap-2">
            {['Water Network', 'Electricity', 'Sewer', 'Telecom', 'Gas'].map((t) => (
              <div key={t} className="flex items-center gap-2 text-sm text-slate-300 bg-white/5 rounded-lg px-3 py-2">
                <CheckCircle2 size={14} className="text-brand-400" /> {t}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-16 border-t border-white/5">
        <h2 className="font-display text-2xl sm:text-3xl font-bold text-white mb-8">Benefits</h2>
        <div className="grid sm:grid-cols-3 gap-4">
          {[
            { icon: ShieldCheck, t: 'Fewer Ownership Conflicts', d: 'Precise volumetric boundaries eliminate ambiguity between neighboring units.' },
            { icon: TrendingUp, t: 'Better Infrastructure Planning', d: 'Underground and aerial layers inform utility and transit corridor decisions.' },
            { icon: Layers, t: 'Backward Compatible', d: 'Extends the existing 14-digit ULPIN rather than replacing it.' },
          ].map((b) => (
            <div key={b.t} className="card p-5 card-hover">
              <b.icon className="text-brand-400 mb-3" size={22} />
              <div className="font-semibold text-white text-sm mb-1.5">{b.t}</div>
              <div className="text-xs text-slate-500 leading-relaxed">{b.d}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-16 border-t border-white/5 pb-24">
        <div className="card p-6 sm:p-8 text-center">
          <ShieldCheck className="mx-auto text-brand-400 mb-3" size={28} />
          <h3 className="font-display text-xl font-bold text-white mb-2">Every Record is Human-Verified</h3>
          <p className="text-sm text-slate-400 max-w-xl mx-auto">
            AI-generated results never publish directly. A trained verifier reviews the 3D
            geometry, checks validation flags, and approves or corrects every record before it
            becomes a public 3D ULPIN.
          </p>
        </div>
      </section>
    </div>
  )
}
