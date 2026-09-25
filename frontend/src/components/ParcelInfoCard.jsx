import { useEffect, useState } from 'react'
import api from '../api/client'
import { ChevronRight, ChevronDown, ChevronUp, Loader2, GripVertical } from 'lucide-react'
import useDraggable from '../hooks/useDraggable.js'

export default function ParcelInfoCard({ parcel, onViewFullDetails, variant = 'card' }) {
  const [addressInfo, setAddressInfo] = useState(null)
  const [addressLoading, setAddressLoading] = useState(false)
  const [addressError, setAddressError] = useState(false)
  const [ownerLabel, setOwnerLabel] = useState(null)
  const [ownerLoading, setOwnerLoading] = useState(false)
  const [ownerRestricted, setOwnerRestricted] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const drag = useDraggable()

  useEffect(() => {
    if (!parcel) return

    if (parcel.centroid_lat != null && parcel.centroid_lon != null) {
      setAddressLoading(true)
      setAddressError(false)
      api.get('/geocode/reverse', { params: { lat: parcel.centroid_lat, lon: parcel.centroid_lon } })
        .then(({ data }) => setAddressInfo(data))
        .catch(() => setAddressError(true))
        .finally(() => setAddressLoading(false))
    } else {
      setAddressInfo(null)
    }

    setOwnerLoading(true)
    setOwnerRestricted(false)
    api.get(`/rrr/parcel/${parcel.id}`)
      .then(({ data }) => {
        const ownershipRight = data.find((r) => r.right_type === 'ownership')
        setOwnerLabel(ownershipRight?.party?.display_label || null)
      })
      .catch((err) => {
        if (err?.response?.status === 401 || err?.response?.status === 403) {
          setOwnerRestricted(true)
        }
        setOwnerLabel(null)
      })
      .finally(() => setOwnerLoading(false))
  }, [parcel?.id])

  if (!parcel) return null

  if (variant === 'strip') {
    const geo = (v) => (addressLoading ? null : (v || (addressError ? 'Lookup unavailable' : null)))
    const items = [
      ['Area', parcel.area_sqm != null ? `${Number(parcel.area_sqm).toFixed(1)} m²` : null],
      ['Khasra', parcel.khasra_number],
      ['Land use', parcel.land_use],
      ['Owner', ownerLoading ? null : (ownerRestricted ? 'Sign in to view' : (ownerLabel || 'Not yet recorded'))],
      ['Village', geo(addressInfo?.village)],
      ['Tehsil', geo(addressInfo?.subdistrict_or_tehsil)],
      ['District', geo(addressInfo?.district)],
    ]
    const stillLoading = addressLoading || ownerLoading
    return (
      <div className="card pointer-events-auto bg-ink-900/90 backdrop-blur-lg border border-white/10 px-4 py-2 flex items-center gap-x-6 gap-y-1 flex-wrap">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Parcel ULPIN</div>
          <div className="text-sm text-white font-semibold font-mono">{parcel.ulpin_2d}</div>
        </div>
        {items.filter(([, v]) => v).map(([label, value]) => (
          <div key={label} className="min-w-0">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
            <div className={`text-xs text-slate-200 font-medium truncate max-w-[170px] ${label === 'Land use' ? 'capitalize' : ''}`}>{value}</div>
          </div>
        ))}
        {stillLoading && <Loader2 size={13} className="animate-spin text-slate-600" />}
        <button onClick={onViewFullDetails} className="btn-primary !px-3 !py-1.5 text-xs ml-auto">
          Details <ChevronRight size={13} />
        </button>
      </div>
    )
  }

  return (
    <div className="card w-72 sm:w-80 p-4 pointer-events-auto bg-ink-900/95 backdrop-blur-lg border border-white/10" style={drag.style}>
      <div className="flex items-center gap-2">
        <span {...drag.handleProps} className="text-slate-500 hover:text-slate-300 flex-shrink-0">
          <GripVertical size={14} />
        </span>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex-1 flex items-center justify-between gap-3 text-left min-w-0"
        >
          <span className="text-sm text-white font-semibold font-mono truncate">{parcel.ulpin_2d}</span>
          {collapsed ? <ChevronDown size={15} className="text-slate-400 flex-shrink-0" /> : <ChevronUp size={15} className="text-slate-400 flex-shrink-0" />}
        </button>
      </div>

      {!collapsed && (
        <>
          <div className="mt-2">
            <Row label="Parcel ID" value={parcel.ulpin_2d} mono />
            <Row label="Khasra No." value={parcel.khasra_number} />
            <Row label="Area" value={parcel.area_sqm != null ? `${parcel.area_sqm.toFixed(2)} m²` : null} />
            <Row label="Land Use" value={parcel.land_use} capitalize />
            <Row
              label="Owner"
              value={ownerLoading ? null : (ownerRestricted ? 'Sign in to view' : (ownerLabel || 'Not yet recorded'))}
              loading={ownerLoading}
            />
            <Row
              label="Village"
              value={addressLoading ? null : (addressInfo?.village || (addressError ? 'Lookup unavailable' : 'Not available'))}
              loading={addressLoading}
            />
            <Row
              label="Tehsil"
              value={addressLoading ? null : (addressInfo?.subdistrict_or_tehsil || (addressError ? 'Lookup unavailable' : 'Not available'))}
              loading={addressLoading}
            />
            <Row
              label="District"
              value={addressLoading ? null : (addressInfo?.district || (addressError ? 'Lookup unavailable' : 'Not available'))}
              loading={addressLoading}
            />
          </div>

          <button
            onClick={onViewFullDetails}
            className="btn-primary w-full text-sm mt-3"
          >
            View Full Details <ChevronRight size={15} />
          </button>
        </>
      )}
    </div>
  )
}

function Row({ label, value, mono, capitalize, loading }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-b-0 gap-3">
      <span className="text-xs text-slate-500 flex-shrink-0">{label}</span>
      {loading ? (
        <Loader2 size={13} className="animate-spin text-slate-600" />
      ) : (
        <span className={`text-sm text-white font-medium text-right truncate ${mono ? 'font-mono' : ''} ${capitalize ? 'capitalize' : ''}`}>
          {value || '—'}
        </span>
      )}
    </div>
  )
}
