import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import api from '../../api/client'
import { useAuth } from '../../context/AuthContext.jsx'
import StatusBadge from '../../components/StatusBadge.jsx'
import { estimateBuildingDimensions } from '../../utils/buildingEstimate.js'
import { polygonArea, safeParseGeojson } from '../../utils/geometry.js'
import {
  Loader2, ListTree, Search, MessageSquareWarning, ChevronDown, ChevronRight,
  Building2, MapPin, CheckCircle2, XCircle, Satellite,
} from 'lucide-react'

export default function AllRecords() {
  const [parcels, setParcels] = useState([])
  const [grievances, setGrievances] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [searchParams] = useSearchParams()
  const [statusFilter, setStatusFilter] = useState(searchParams.get('status') || 'all')
  const [expandedParcels, setExpandedParcels] = useState({})
  const [expandedBuildings, setExpandedBuildings] = useState({})
  const [bulkActingId, setBulkActingId] = useState(null)
  const { user } = useAuth()
  const canReview = user?.role === 'verifier' || user?.role === 'admin'

  function reload() {
    setLoading(true)
    Promise.all([api.get('/parcels', { params: { limit: 5000 } }), api.get('/grievances').catch(() => ({ data: [] }))])
      .then(([p, g]) => { setParcels(p.data); setGrievances(g.data) })
      .finally(() => setLoading(false))
  }

  useEffect(() => { reload() }, [])

  function grievanceCountFor(unitId) {
    return grievances.filter((g) => g.unit_id === unitId).length
  }

  function buildingGrievanceCountFor(buildingId) {
    return grievances.filter((g) => g.building_id === buildingId).length
  }

  function buildingStatusCounts(building) {
    const counts = { approved: 0, pending_review: 0, rejected: 0, reprocessing: 0, ai_generated: 0, total: 0 }
    building.floors?.forEach((f) => f.units?.forEach((u) => {
      counts[u.verification_status] = (counts[u.verification_status] || 0) + 1
      counts.total += 1
    }))
    return counts
  }

  function matchesFilters(unit, parcelUlpin) {
    const q = query.trim().toLowerCase()
    const matchesQuery = !q || unit.ulpin_3d.toLowerCase().includes(q) || parcelUlpin.toLowerCase().includes(q)
    const matchesStatus = statusFilter === 'all' || unit.verification_status === statusFilter
    return matchesQuery && matchesStatus
  }

  async function bulkAction(buildingId, action) {
    setBulkActingId(buildingId)
    try {
      const { data } = await api.post(`/review/buildings/${buildingId}/bulk-action`, { action })
      reload()
      return data
    } catch (err) {
      alert(err.response?.data?.detail || 'Bulk action failed.')
    } finally {
      setBulkActingId(null)
    }
  }

  const totalUnits = parcels.reduce((a, p) => a + (p.buildings?.reduce((b, bd) => b + (bd.floors?.reduce((c, f) => c + (f.units?.length || 0), 0) || 0), 0) || 0), 0)
  const totalBuildings = parcels.reduce((a, p) => a + (p.buildings?.length || 0), 0)
  const unsurveyedBuildings = parcels.reduce(
    (a, p) => a + (p.buildings?.filter((b) => !(b.floors?.reduce((c, f) => c + (f.units?.length || 0), 0) > 0)).length || 0), 0,
  )

  function matchesBuildingQuery(building, parcelUlpin) {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return (
      parcelUlpin.toLowerCase().includes(q)
      || building.building_code?.toLowerCase().includes(q)
      || building.name?.toLowerCase().includes(q)
      || building.osm_id?.toLowerCase?.().includes(q)
    )
  }

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <ListTree size={22} className="text-brand-400" /> All ULPIN Records
      </h1>
      <p className="text-sm text-slate-500 mb-1">
        Grouped by parcel → building, so a verifier can approve or reject an entire building's
        floors/units at once instead of clicking through each one individually.
      </p>
      <p className="text-xs text-slate-600 mb-6">
        {totalBuildings} building(s) on record{unsurveyedBuildings > 0 && (
          <> · {unsurveyedBuildings} not yet surveyed to floor/unit level (e.g. straight from a GIS bulk import) — shown below with their estimated footprint, height and floor count</>
        )}
      </p>

      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={15} />
          <input
            value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by ULPIN..." className="input-field !pl-9"
          />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="input-field sm:w-52">
          <option value="all">All statuses</option>
          <option value="approved">Verified</option>
          <option value="pending_review">Pending Review</option>
          <option value="rejected">Rejected</option>
          <option value="reprocessing">Reprocessing</option>
        </select>
      </div>

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}

      {!loading && totalBuildings === 0 && (
        <div className="card p-12 text-center">
          <ListTree className="mx-auto text-slate-700 mb-3" size={32} />
          <p className="text-sm text-slate-500 mb-4">No parcels or buildings on record yet.</p>
          <Link to="/admin/create" className="btn-primary text-sm inline-flex">Create a Parcel / Building</Link>
        </div>
      )}

      <div className="space-y-3">
        {parcels.map((p) => {
          const parcelExpanded = expandedParcels[p.id] ?? true
          const parcelUnitCount = p.buildings?.reduce((a, b) => a + (b.floors?.reduce((c, f) => c + (f.units?.length || 0), 0) || 0), 0) || 0
          if ((p.buildings?.length || 0) === 0) return null

          return (
            <div key={p.id} className="card overflow-hidden">
              <button
                onClick={() => setExpandedParcels((s) => ({ ...s, [p.id]: !parcelExpanded }))}
                className="w-full flex items-center gap-3 px-5 py-4 hover:bg-white/[0.02] text-left"
              >
                {parcelExpanded ? <ChevronDown size={16} className="text-slate-500 flex-shrink-0" /> : <ChevronRight size={16} className="text-slate-500 flex-shrink-0" />}
                <MapPin size={15} className="text-sky-400 flex-shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-mono text-white">{p.ulpin_2d}</div>
                  <div className="text-xs text-slate-500 truncate">{p.address}</div>
                </div>
                <span className="text-xs text-slate-500 flex-shrink-0">{p.buildings?.length || 0} building(s) · {parcelUnitCount} unit(s)</span>
              </button>

              {parcelExpanded && (
                <div className="border-t border-white/5 divide-y divide-white/5">
                  {p.buildings?.filter((b) => matchesBuildingQuery(b, p.ulpin_2d)).map((b) => {
                    const buildingUnitCount = b.floors?.reduce((c, f) => c + (f.units?.length || 0), 0) || 0
                    const key = `${p.id}:${b.id}`
                    const buildingExpanded = expandedBuildings[key] ?? false
                    const counts = buildingStatusCounts(b)

                    if (buildingUnitCount === 0) {
                      const footprintPts = safeParseGeojson(b.footprint_geojson)
                      const footprintArea = polygonArea(footprintPts)
                      const dims = estimateBuildingDimensions(b)
                      const bGrievances = buildingGrievanceCountFor(b.id)
                      const sourceLabel = b.osm_id ? 'OSM bulk import' : b.ms_footprint_id ? 'MS Building Footprints' : b.auto_generated ? 'Address lookup' : null
                      return (
                        <div key={b.id} className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-5 py-3 pl-10 hover:bg-white/[0.02]">
                          <Link to={`/admin/viewer?focus=parcel:${p.id}&building=${b.id}`} className="flex items-center gap-2 flex-1 min-w-[220px] text-left">
                            <Building2 size={14} className="text-violet-400 flex-shrink-0" />
                            <span className="text-sm text-white truncate">{b.name || b.building_code}</span>
                          </Link>
                          <span className="text-[11px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-full px-2 py-0.5 flex-shrink-0">
                            Not yet surveyed
                          </span>
                          {sourceLabel && (
                            <span className="text-[11px] text-sky-400 flex items-center gap-1 flex-shrink-0">
                              <Satellite size={11} /> {sourceLabel}
                            </span>
                          )}
                          <span className="text-xs text-slate-500 flex-shrink-0">
                            ~{dims.floors} floor(s){dims.estimated ? ' (estimated)' : ''} · ~{dims.height}m height{dims.estimated ? ' (estimated)' : ''}
                          </span>
                          {footprintArea != null && (
                            <span className="text-xs text-slate-500 flex-shrink-0">{footprintArea.toFixed(1)} sqm footprint</span>
                          )}
                          {bGrievances > 0 && (
                            <span className="text-[11px] text-orange-400 flex items-center gap-1 flex-shrink-0">
                              <MessageSquareWarning size={11} /> {bGrievances} grievance(s)
                            </span>
                          )}
                        </div>
                      )
                    }

                    return (
                      <div key={b.id}>
                        <div className="flex flex-wrap items-center gap-3 px-5 py-3 pl-10 hover:bg-white/[0.02]">
                          <button onClick={() => setExpandedBuildings((s) => ({ ...s, [key]: !buildingExpanded }))} className="flex items-center gap-2 flex-1 min-w-0 text-left">
                            {buildingExpanded ? <ChevronDown size={14} className="text-slate-500 flex-shrink-0" /> : <ChevronRight size={14} className="text-slate-500 flex-shrink-0" />}
                            <Building2 size={14} className="text-violet-400 flex-shrink-0" />
                            <span className="text-sm text-white truncate">{b.name || b.building_code}</span>
                            <span className="text-xs text-slate-500 flex-shrink-0">{b.num_floors != null ? `${b.num_floors} floors` : 'Not yet surveyed'} · {counts.total} units</span>
                          </button>

                          <div className="flex items-center gap-1.5 flex-shrink-0">
                            {counts.approved > 0 && <span className="text-[10px] text-emerald-400">{counts.approved} verified</span>}
                            {counts.pending_review > 0 && <span className="text-[10px] text-amber-400">{counts.pending_review} pending</span>}
                          </div>

                          {canReview && counts.pending_review > 0 && (
                            <div className="flex items-center gap-1.5 flex-shrink-0">
                              <button
                                onClick={() => bulkAction(b.id, 'approve')}
                                disabled={bulkActingId === b.id}
                                className="btn-secondary !py-1 !px-2.5 text-[11px] !text-emerald-400 !border-emerald-500/20 hover:!bg-emerald-500/10"
                                title={`Approve all ${counts.pending_review} pending units in this building`}
                              >
                                {bulkActingId === b.id ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />} Approve All
                              </button>
                              <button
                                onClick={() => bulkAction(b.id, 'reject')}
                                disabled={bulkActingId === b.id}
                                className="btn-secondary !py-1 !px-2.5 text-[11px] !text-rose-400 !border-rose-500/20 hover:!bg-rose-500/10"
                                title={`Reject all ${counts.pending_review} pending units in this building`}
                              >
                                <XCircle size={11} /> Reject All
                              </button>
                            </div>
                          )}
                        </div>

                        {buildingExpanded && (
                          <div className="bg-black/10">
                            {b.floors?.map((f) => (
                              f.units?.length > 0 && (
                                <div key={f.id} className="px-5 py-2 pl-16">
                                  <div className="text-[11px] text-slate-600 mb-1.5">Floor {f.floor_number}</div>
                                  <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
                                    {f.units.filter((u) => matchesFilters(u, p.ulpin_2d)).map((u) => {
                                      const gCount = grievanceCountFor(u.id)
                                      return (
                                        <Link
                                          key={u.id}
                                          to={canReview ? `/admin/review/${u.id}` : `/property/${u.id}`}
                                          className="flex items-center justify-between text-xs bg-white/5 rounded-lg px-2.5 py-1.5 hover:bg-white/10"
                                        >
                                          <span className="font-mono text-slate-300 truncate">{u.unit_code}</span>
                                          <div className="flex items-center gap-1.5 flex-shrink-0">
                                            {gCount > 0 && <MessageSquareWarning size={10} className="text-orange-400" />}
                                            <StatusBadge status={u.verification_status} />
                                          </div>
                                        </Link>
                                      )
                                    })}
                                  </div>
                                </div>
                              )
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
