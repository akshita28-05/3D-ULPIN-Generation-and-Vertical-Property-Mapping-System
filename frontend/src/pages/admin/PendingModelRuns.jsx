import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../api/client'
import { Loader2, ScanSearch, ImageIcon, Layers3, ArrowRight, RefreshCw } from 'lucide-react'

export default function PendingModelRuns() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  function load() {
    setLoading(true)
    api
      .get('/processing/pending-model-run')
      .then((res) => setRows(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load pending model runs.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-1">
        <h1 className="font-display text-2xl font-bold text-white flex items-center gap-2">
          <ScanSearch size={22} className="text-brand-400" /> Pending Model Runs
        </h1>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-white px-3 py-1.5 rounded-lg hover:bg-white/5"
        >
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
      <p className="text-sm text-slate-500 mb-8 max-w-2xl">
        Buildings with drone imagery or a point cloud already uploaded, but whose footprint or floors
        are still the surveyor-entered ("manual") values -- a real model run would change something
        here but hasn't happened yet.
      </p>

      {loading && (
        <div className="flex justify-center py-20">
          <Loader2 className="animate-spin text-brand-400" size={26} />
        </div>
      )}

      {!loading && error && (
        <div className="card p-8 text-center text-sm text-rose-400">{error}</div>
      )}

      {!loading && !error && rows.length === 0 && (
        <div className="card p-12 text-center text-sm text-slate-500">
          Nothing waiting -- every building with uploaded imagery already reflects a real model run
          (or has no imagery to run one on).
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500 uppercase border-b border-white/5">
                <th className="px-5 py-3 font-medium">Building</th>
                <th className="px-5 py-3 font-medium">Parcel</th>
                <th className="px-5 py-3 font-medium">Uploaded</th>
                <th className="px-5 py-3 font-medium">Still manual</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="px-5 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.building_id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                  <td className="px-5 py-3">
                    <div className="text-slate-200 font-medium">{r.building_name || r.building_code}</div>
                    <div className="text-xs text-slate-500">{r.building_code}</div>
                  </td>
                  <td className="px-5 py-3 text-slate-400">
                    <div>{r.parcel_ulpin_2d}</div>
                    {r.parcel_address && <div className="text-xs text-slate-600">{r.parcel_address}</div>}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3 text-xs text-slate-400">
                      {r.has_drone_image && (
                        <span className="flex items-center gap-1"><ImageIcon size={13} /> imagery</span>
                      )}
                      {(r.has_point_cloud || r.has_basement_point_cloud) && (
                        <span className="flex items-center gap-1"><Layers3 size={13} /> point cloud</span>
                      )}
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex flex-col gap-1 text-xs">
                      <span className={r.footprint_source === 'manual' && r.has_drone_image ? 'text-amber-400' : 'text-slate-600'}>
                        footprint: {r.footprint_source}
                      </span>
                      <span className={r.floor_source === 'manual' && (r.has_point_cloud || r.has_basement_point_cloud) ? 'text-amber-400' : 'text-slate-600'}>
                        floors: {r.floor_source}
                      </span>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-xs text-slate-500">
                    {r.already_processed ? 'Processed once (manual)' : 'Never processed'}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <Link
                      to={`/admin/records`}
                      className="inline-flex items-center gap-1 text-xs font-medium text-brand-400 hover:text-brand-300"
                    >
                      Review <ArrowRight size={13} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-slate-600 mt-6">
        A building only appears here if the uploaded file could actually change something: imagery
        only matters while footprint_source is "manual", a point cloud only matters while
        floor_source is "manual". Re-run the pipeline (or use the imagery-detect/select flow) to
        clear an entry.
      </p>
    </div>
  )
}
