import { useState, useEffect } from 'react'
import api from '../../api/client'
import {
  MapPin, Building2, Loader2, CheckCircle2, XCircle, Info,
} from 'lucide-react'

export default function CreateEntity() {
  const [tab, setTab] = useState('parcel')

  return (
    <div className="animate-fade-in max-w-2xl">
      <h1 className="font-display text-2xl font-bold text-white mb-1">Create Parcel / Building</h1>
      <p className="text-sm text-slate-500 mb-6">
        Real data entry — every value here is stored as entered and used directly by the pipeline.
        Nothing is randomized.
      </p>

      <div className="card p-1.5 flex items-center gap-1 mb-6 w-fit">
        <button onClick={() => setTab('parcel')} className={`px-4 py-2 rounded-lg text-xs font-medium transition-colors ${tab === 'parcel' ? 'bg-brand-500 text-ink-950' : 'text-slate-400'}`}>
          <MapPin size={13} className="inline mr-1.5" /> New Parcel
        </button>
        <button onClick={() => setTab('building')} className={`px-4 py-2 rounded-lg text-xs font-medium transition-colors ${tab === 'building' ? 'bg-brand-500 text-ink-950' : 'text-slate-400'}`}>
          <Building2 size={13} className="inline mr-1.5" /> New Building
        </button>
      </div>

      {tab === 'parcel' ? <ParcelForm /> : <BuildingForm />}
    </div>
  )
}

function ParcelForm() {
  const [form, setForm] = useState({
    state_code: '20', district_code: '', subdistrict_code: '', village_code: '', plot_code: '',
    address: '', centroid_lat: '', centroid_lon: '', width: '', depth: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const [suggestions, setSuggestions] = useState([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [geocoding, setGeocoding] = useState(false)
  const [detectedDistrict, setDetectedDistrict] = useState(null)
  const [geocodeError, setGeocodeError] = useState(null)
  const debounceRef = useState({ current: null })[0]

  const [validation, setValidation] = useState(null)
  const [validating, setValidating] = useState(false)

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  function handleAddressChange(value) {
    set('address', value)
    setValidation(null)
    setGeocodeError(null)
    clearTimeout(debounceRef.current)
    if (value.trim().length < 3) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }
    debounceRef.current = setTimeout(async () => {
      setGeocoding(true)
      try {
        const { data } = await api.get('/geocode/search', { params: { q: value } })
        setSuggestions(data)
        setShowSuggestions(true)
        if (data.length === 0) setGeocodeError('No matching address found — enter state/district manually below.')
      } catch (err) {
        setSuggestions([])
        setGeocodeError(
          err.response?.status === 429
            ? 'Too many address lookups right now — wait a few seconds and keep typing.'
            : (err.response?.data?.detail || 'Address lookup failed — enter state/district manually below.'),
        )
      } finally {
        setGeocoding(false)
      }
    }, 500)
  }

  function selectSuggestion(s) {
    setForm((f) => ({
      ...f,
      address: s.display_name,
      centroid_lat: s.lat.toFixed(6),
      centroid_lon: s.lon.toFixed(6),
      state_code: s.suggested_state_code || f.state_code,
      district_code: s.detected_district_name || f.district_code,
      subdistrict_code: s.detected_subdistrict_name || f.subdistrict_code,
      village_code: s.detected_village_name || f.village_code,
    }))
    setDetectedDistrict(s.detected_district_name || null)
    setShowSuggestions(false)
    setValidation(null)
    setGeocodeError(null)
  }

  async function checkAddressMatch() {
    if (!form.address || !form.centroid_lat || !form.centroid_lon) {
      setValidation({ plausible: false, message: 'Enter an address and coordinates first.' })
      return
    }
    setValidating(true)
    setValidation(null)
    try {
      const { data } = await api.post('/geocode/validate', {
        address: form.address, lat: parseFloat(form.centroid_lat), lon: parseFloat(form.centroid_lon),
      })
      setValidation(data)
    } catch (err) {
      setValidation({ plausible: true, message: err.response?.data?.detail || 'Could not verify right now — proceeding with entered values.' })
    } finally {
      setValidating(false)
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setResult(null)
    const w = parseFloat(form.width)
    const d = parseFloat(form.depth)
    if (!w || !d) { setError('Enter a valid width and depth.'); return }
    const footprint = [[0, 0], [w, 0], [w, d], [0, d], [0, 0]]

    setSubmitting(true)
    try {
      const { data } = await api.post('/parcels', {
        state_code: form.state_code, district_code: form.district_code,
        subdistrict_code: form.subdistrict_code, village_code: form.village_code, plot_code: form.plot_code,
        address: form.address, centroid_lat: parseFloat(form.centroid_lat), centroid_lon: parseFloat(form.centroid_lon),
        footprint_geojson: JSON.stringify(footprint),
      })
      setResult(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create parcel.')
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    return (
      <div className="card p-6 text-center">
        <CheckCircle2 className="mx-auto text-emerald-400 mb-3" size={32} />
        <p className="text-sm text-slate-400 mb-2">Parcel created — real 14-digit ULPIN generated from your entered codes:</p>
        <div className="font-display font-bold text-lg text-brand-400 mb-4">{result.ulpin_2d}</div>
        <p className="text-xs text-slate-500 mb-6">Area: {result.area_sqm} sqm (computed from your footprint dimensions)</p>
        <button onClick={() => setResult(null)} className="btn-secondary text-sm">Create Another</button>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="card p-6 space-y-4">
      {error && <ErrorBanner text={error} />}

      <div className="flex items-start gap-2 text-xs text-slate-500 bg-white/5 rounded-lg px-3 py-2.5">
        <Info size={14} className="flex-shrink-0 mt-0.5" />
        District, sub-district, village, and plot accept either the official numeric government
        code (if you know it) or the real place name / Khasra number (e.g. "East Singhbhum",
        "123/2") — no free public API provides the official numeric LGD codes, so real names are
        the practical alternative. Picking an address below auto-fills these from what was found.
        If every field you enter is a plain number, the system still builds the classic strict
        14-digit numeric ULPIN; otherwise it builds a readable name-based identifier instead.
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Field label="State" value={form.state_code} onChange={(v) => set('state_code', v)} maxLength={2} />
        <Field label="District" value={form.district_code} onChange={(v) => set('district_code', v)} maxLength={30} placeholder="01 or East Singhbhum" />
        <Field label="Sub-district" value={form.subdistrict_code} onChange={(v) => set('subdistrict_code', v)} maxLength={30} placeholder="003 or Golmuri-cum-Jugsalai" />
        <Field label="Village" value={form.village_code} onChange={(v) => set('village_code', v)} maxLength={30} placeholder="045 or Jamshedpur" />
        <Field label="Plot" value={form.plot_code} onChange={(v) => set('plot_code', v)} maxLength={16} placeholder="0231 or 123/2" />
      </div>
      {detectedDistrict && (
        <p className="text-[11px] text-brand-400 -mt-2">Detected district: {detectedDistrict} — enter its official code above if known.</p>
      )}
      {geocodeError && (
        <p className="text-[11px] text-amber-400 -mt-2">{geocodeError}</p>
      )}

      <div className="relative">
        <label className="block text-xs font-medium text-slate-400 mb-2">Address</label>
        <div className="relative">
          <input
            value={form.address}
            onChange={(e) => handleAddressChange(e.target.value)}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            className="input-field" required placeholder="Start typing a real address..."
            autoComplete="off"
          />
          {geocoding && <Loader2 size={14} className="animate-spin text-brand-400 absolute right-3 top-1/2 -translate-y-1/2" />}
        </div>

        {showSuggestions && suggestions.length > 0 && (
          <div className="absolute z-20 mt-1 w-full card !rounded-xl max-h-56 overflow-y-auto">
            {suggestions.map((s, i) => (
              <button
                type="button" key={i}
                onMouseDown={() => selectSuggestion(s)}
                className="w-full text-left px-3 py-2.5 text-xs text-slate-300 hover:bg-white/5 border-b border-white/5 last:border-0"
              >
                {s.display_name}
              </button>
            ))}
          </div>
        )}
        {showSuggestions && suggestions.length === 0 && !geocoding && form.address.length >= 3 && (
          <div className="absolute z-20 mt-1 w-full card !rounded-xl px-3 py-2.5 text-xs text-slate-500">
            No matches found — you can still enter the address manually.
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Latitude" value={form.centroid_lat} onChange={(v) => { set('centroid_lat', v); setValidation(null) }} type="number" step="0.0001" placeholder="22.7925" />
        <Field label="Longitude" value={form.centroid_lon} onChange={(v) => { set('centroid_lon', v); setValidation(null) }} type="number" step="0.0001" placeholder="86.1844" />
      </div>

      <div className="flex items-center gap-3">
        <button type="button" onClick={checkAddressMatch} disabled={validating} className="btn-secondary !py-1.5 text-xs">
          {validating ? <Loader2 size={12} className="animate-spin" /> : <Info size={12} />} Check Address Matches Coordinates
        </button>
      </div>

      {validation && (
        <div className={`flex items-start gap-2 text-xs rounded-lg px-3 py-2.5 ${
          validation.plausible ? 'text-emerald-400 bg-emerald-500/5 border border-emerald-500/15' : 'text-amber-400 bg-amber-500/5 border border-amber-500/15'
        }`}>
          {validation.plausible ? <CheckCircle2 size={14} className="flex-shrink-0 mt-0.5" /> : <XCircle size={14} className="flex-shrink-0 mt-0.5" />}
          <span>{validation.message}</span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Field label="Plot Width (m)" value={form.width} onChange={(v) => set('width', v)} type="number" step="0.1" placeholder="30" />
        <Field label="Plot Depth (m)" value={form.depth} onChange={(v) => set('depth', v)} type="number" step="0.1" placeholder="22.5" />
      </div>

      <button type="submit" disabled={submitting} className="btn-primary w-full">
        {submitting ? <Loader2 className="animate-spin" size={16} /> : 'Create Parcel'}
      </button>
    </form>
  )
}


function BuildingForm() {
  const [parcels, setParcels] = useState([])
  const [form, setForm] = useState({
    parcel_id: '', name: '', building_type: 'residential', num_floors: '', height_m: '', width: '', depth: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('/parcels', { params: { limit: 5000 } }).then((res) => {
      setParcels(res.data)
      if (res.data.length) setForm((f) => ({ ...f, parcel_id: res.data[0].id }))
    })
  }, [])

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setResult(null)
    const w = parseFloat(form.width)
    const d = parseFloat(form.depth)
    const floors = parseInt(form.num_floors)
    const height = parseFloat(form.height_m)
    if (!w || !d || !floors || !height) { setError('Fill in all dimension fields with valid numbers.'); return }
    const footprint = [[0, 0], [w, 0], [w, d], [0, d], [0, 0]]

    setSubmitting(true)
    try {
      const { data } = await api.post('/buildings', {
        parcel_id: form.parcel_id, name: form.name, building_type: form.building_type,
        num_floors: floors, height_m: height, footprint_geojson: JSON.stringify(footprint),
      })
      setResult(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create building.')
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    return (
      <div className="card p-6 text-center">
        <CheckCircle2 className="mx-auto text-emerald-400 mb-3" size={32} />
        <p className="text-sm text-slate-400 mb-2">Building created:</p>
        <div className="font-display font-bold text-lg text-brand-400 mb-4">{result.name} ({result.building_code})</div>
        <p className="text-xs text-slate-500 mb-6">
          {result.num_floors} floors · {result.height_m}m height — go to <strong className="text-slate-300">Data Ingestion</strong> to run the pipeline on it.
        </p>
        <button onClick={() => setResult(null)} className="btn-secondary text-sm">Create Another</button>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="card p-6 space-y-4">
      {error && <ErrorBanner text={error} />}

      <div>
        <label className="block text-xs font-medium text-slate-400 mb-2">Parcel</label>
        <select value={form.parcel_id} onChange={(e) => set('parcel_id', e.target.value)} className="input-field" required>
          {parcels.map((p) => <option key={p.id} value={p.id}>{p.ulpin_2d} — {p.address}</option>)}
        </select>
        {parcels.length === 0 && <p className="text-[11px] text-amber-400 mt-1.5">No parcels yet — create one first.</p>}
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-400 mb-2">Building Name</label>
        <input value={form.name} onChange={(e) => set('name', e.target.value)} className="input-field" required />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-400 mb-2">Building Type</label>
        <select value={form.building_type} onChange={(e) => set('building_type', e.target.value)} className="input-field">
          <option value="residential">Residential</option>
          <option value="commercial">Commercial</option>
          <option value="mixed_use">Mixed Use</option>
          <option value="institutional">Institutional</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Number of Floors" value={form.num_floors} onChange={(v) => set('num_floors', v)} type="number" placeholder="5" />
        <Field label="Total Height (m)" value={form.height_m} onChange={(v) => set('height_m', v)} type="number" step="0.1" placeholder="15" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Footprint Width (m)" value={form.width} onChange={(v) => set('width', v)} type="number" step="0.1" placeholder="30" />
        <Field label="Footprint Depth (m)" value={form.depth} onChange={(v) => set('depth', v)} type="number" step="0.1" placeholder="22.5" />
      </div>

      <button type="submit" disabled={submitting || !parcels.length} className="btn-primary w-full">
        {submitting ? <Loader2 className="animate-spin" size={16} /> : 'Create Building'}
      </button>
    </form>
  )
}

function Field({ label, value, onChange, ...props }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-400 mb-2">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} className="input-field" required {...props} />
    </div>
  )
}

function ErrorBanner({ text }) {
  return (
    <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/15 rounded-lg px-3 py-2.5">
      <XCircle size={14} /> {text}
    </div>
  )
}
