import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../api/client'
import { Search as SearchIcon, MapPin, Building2, Layers, Home as HomeIcon, Loader2 } from 'lucide-react'

const iconFor = { parcel: MapPin, building: Building2, unit: Layers }

export default function Search() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [touched, setTouched] = useState(false)
  const navigate = useNavigate()
  const debounceRef = useRef(null)

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      return
    }
    setLoading(true)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await api.get('/search', { params: { q: query } })
        setResults(data)
      } catch {
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [query])

  function handleSelect(r) {
    if (r.result_type === 'unit') navigate(`/property/${r.id}`)
    else navigate(`/viewer?focus=${r.result_type}:${r.id}`)
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12 sm:py-16">
      <h1 className="font-display text-3xl font-bold text-white mb-2">Search Property Records</h1>
      <p className="text-sm text-slate-400 mb-8">
        Search by 2D ULPIN, 3D ULPIN, Parcel ID, Building ID, Unit number, or address.
      </p>

      <div className="relative">
        <SearchIcon className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" size={18} />
        <input
          autoFocus
          value={query}
          onChange={(e) => { setQuery(e.target.value); setTouched(true) }}
          placeholder="e.g. 20010030450231 or B01-F03-U01"
          className="input-field !pl-12 !py-4 text-base"
        />
        {loading && <Loader2 className="absolute right-4 top-1/2 -translate-y-1/2 text-brand-400 animate-spin" size={18} />}
      </div>

      <div className="mt-6 space-y-2">
        {!touched && (
          <div className="text-center py-16 text-slate-500 text-sm">
            <SearchIcon className="mx-auto mb-3 opacity-30" size={32} />
            Start typing to search across all verified and pending records.
          </div>
        )}

        {touched && !loading && query && results.length === 0 && (
          <div className="text-center py-16 text-slate-500 text-sm">
            No records match "<span className="text-slate-300">{query}</span>". Try a different ULPIN, address, or unit code.
          </div>
        )}

        {results.map((r) => {
          const Icon = iconFor[r.result_type] || HomeIcon
          return (
            <button
              key={`${r.result_type}-${r.id}`}
              onClick={() => handleSelect(r)}
              className="w-full text-left card card-hover p-4 flex items-center gap-4"
            >
              <div className="w-10 h-10 rounded-lg bg-brand-500/10 flex items-center justify-center flex-shrink-0">
                <Icon size={18} className="text-brand-400" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-white truncate">{r.label}</div>
                <div className="text-xs text-slate-500 flex items-center gap-2 mt-0.5">
                  <span className="capitalize">{r.result_type}</span>
                  {r.parent_label && <><span>·</span><span className="truncate">{r.parent_label}</span></>}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
