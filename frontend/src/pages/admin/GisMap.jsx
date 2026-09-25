import { Link } from 'react-router-dom'
import MapWorkspace from '../../components/MapWorkspace.jsx'

export default function GisMap() {
  return (
    <>
      <MapWorkspace mode="admin" />
      <p className="text-center text-[11px] text-slate-600 pb-6">
        Need to draw a custom box and preview it first?{' '}
        <Link to="/admin/gis-map-classic" className="text-brand-400 hover:underline">Open the classic 2D importer</Link>.
      </p>
    </>
  )
}
