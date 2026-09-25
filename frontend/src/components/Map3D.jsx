import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import api from '../api/client'
import { DEFAULT_CENTER, DEFAULT_ZOOM, INFRA_MIN_ZOOM } from '../config/region.js'
import { EMPTY, INFRA_LAYER_IDS, REGION_MIN_ZOOM, buildStyle } from './mapStyle.js'


const FALLBACK_BASEMAP_TILES = ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
const IMAGERY_WATCHDOG_MS = 7000

const UNDER_LAYERS = ['under-fill', 'under-fill-outline', 'under-line-casing', 'under-line']
const AIR_LAYERS = ['air-ground', 'air-ground-outline', 'air-envelope', 'air-deck']

function parseProps(props) {
  const p = { ...props }
  if (typeof p.notes === 'string') {
    try { p.notes = JSON.parse(p.notes) } catch { p.notes = [] }
  }
  return p
}

const countOf = (fc) => {
  const feats = fc?.features || []
  return {
    underground: feats.filter((f) => f.properties.kind === 'underground').length,
    air: feats.filter((f) => f.properties.kind === 'air').length,
  }
}

const Map3D = forwardRef(function Map3D({
  registered, selectedId, highlight,
  onSelect, onSelectInfra, onViewChange, onImageryError, onMapProblem, onInfraData, onInfraStatus,
  showOsm = true, showRegion = true, showRegistered = true, showUnderground = true, showAir = true,
  xray = false, showLabels = false, showTerrain = false,
}, ref) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const loadedRef = useRef(false)
  const regionAbort = useRef(null)
  const regionTimer = useRef(null)
  const infraTimer = useRef(null)
  const infraRetry = useRef(null)
  const infraSeq = useRef(0)
  const imageryErrorSent = useRef(false)
  const terrainOn = useRef(false)
  const latest = useRef({})
  latest.current = {
    registered, selectedId, highlight, onSelect, onSelectInfra, onViewChange, onImageryError, onMapProblem,
    onInfraData, onInfraStatus, showOsm, showRegion, showRegistered, showUnderground, showAir, xray, showLabels, showTerrain,
  }

  useImperativeHandle(ref, () => ({
    flyTo({ lat, lon, zoom = 17, pitch = 60, bearing }) {
      mapRef.current?.flyTo({ center: [lon, lat], zoom, pitch, ...(bearing !== undefined ? { bearing } : {}), duration: 1800, essential: true })
    },
    setPitch(pitch) {
      mapRef.current?.easeTo({ pitch, duration: 700 })
    },
    getPitch() {
      return mapRef.current?.getPitch() ?? 0
    },
    getView() {
      const map = mapRef.current
      if (!map) return null
      const b = map.getBounds()
      return { zoom: map.getZoom(), bounds: { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() } }
    },
    rescan() {
      clearTimeout(infraTimer.current)
      runInfra()
    },
  }))

  function emitView() {
    const map = mapRef.current
    if (!map) return
    const b = map.getBounds()
    latest.current.onViewChange?.({
      zoom: map.getZoom(), pitch: map.getPitch(),
      bounds: { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() },
    })
  }

  function loadRegion() {
    const map = mapRef.current
    if (!map || !loadedRef.current) return
    clearTimeout(regionTimer.current)
    regionTimer.current = setTimeout(async () => {
      regionAbort.current?.abort()
      const src = map.getSource('region')
      if (!src) return
      if (!latest.current.showRegion || map.getZoom() < REGION_MIN_ZOOM) {
        src.setData(EMPTY)
        return
      }
      const b = map.getBounds()
      const controller = new AbortController()
      regionAbort.current = controller
      try {
        const { data } = await api.get('/map/footprints', {
          params: { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() },
          signal: controller.signal,
        })
        src.setData(data)
      } catch {
      }
    }, 350)
  }

  function pushInfra(fc) {
    const map = mapRef.current
    if (!map) return
    const feats = fc?.features || []
    map.getSource('infra-under')?.setData({ type: 'FeatureCollection', features: feats.filter((f) => f.properties.kind === 'underground') })
    map.getSource('infra-air')?.setData({ type: 'FeatureCollection', features: feats.filter((f) => f.properties.kind === 'air') })
    latest.current.onInfraData?.(fc || null)
  }

  async function runInfra() {
    const map = mapRef.current
    if (!map || !loadedRef.current) return
    const p = latest.current
    const seq = ++infraSeq.current
    clearTimeout(infraRetry.current)
    if (!p.showUnderground && !p.showAir) {
      pushInfra(null)
      p.onInfraStatus?.({ state: 'off' })
      return
    }
    if (map.getZoom() < INFRA_MIN_ZOOM) {
      pushInfra(null)
      p.onInfraStatus?.({ state: 'zoom' })
      return
    }
    const c = map.getCenter()
    const cont = map.getContainer()
    const left = map.unproject([0, cont.clientHeight / 2])
    const right = map.unproject([cont.clientWidth, cont.clientHeight / 2])
    const half = Math.min(0.015, Math.max(0.004, (Math.abs(right.lng - left.lng) / 2) * 1.15))
    const box = { south: c.lat - half, north: c.lat + half, west: c.lng - half, east: c.lng + half }
    const getFeatures = async () => (await api.get('/map/infrastructure', { params: box })).data
    try {
      let data = await getFeatures()
      if (seq !== infraSeq.current) return
      pushInfra(data)
      p.onInfraStatus?.({ state: 'scanning', counts: countOf(data) })
      const { data: scan } = await api.post('/infra/scan', box, { timeout: 120000 })
      if (seq !== infraSeq.current) return
      if (scan.added > 0) {
        data = await getFeatures()
        if (seq !== infraSeq.current) return
        pushInfra(data)
      }
      latest.current.onInfraStatus?.({ state: scan.status, message: scan.message, counts: countOf(data) })
      if (scan.status === 'busy') infraRetry.current = setTimeout(runInfra, 3000)
    } catch (err) {
      if (seq !== infraSeq.current) return
      latest.current.onInfraStatus?.({ state: 'error', message: err.response?.data?.detail || 'Could not reach the server.' })
    }
  }

  useEffect(() => {
    let map
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: buildStyle({ terrain: false }),
        center: [DEFAULT_CENTER[1], DEFAULT_CENTER[0]],
        zoom: DEFAULT_ZOOM,
        pitch: 60,
        bearing: -15,
        maxPitch: 80,
        attributionControl: { compact: true },
      })
    } catch (err) {
      console.error('[map] could not start MapLibre', err)
      latest.current.onMapProblem?.('The map could not start (WebGL is unavailable or disabled in this browser).')
      return undefined
    }
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')

    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => map.resize()) : null
    ro?.observe(containerRef.current)

    let satelliteTileSeen = false
    const onSatelliteSourceData = (e) => {
      if (e.sourceId === 'satellite' && e.isSourceLoaded) satelliteTileSeen = true
    }
    map.on('sourcedata', onSatelliteSourceData)

    function fallBackToOsmBasemap() {
      if (imageryErrorSent.current) return
      imageryErrorSent.current = true
      map.getSource('satellite')?.setTiles(FALLBACK_BASEMAP_TILES)
      latest.current.onImageryError?.()
    }

    let started = false
    const start = () => {
      if (started) return
      started = true
      loadedRef.current = true
      map.resize()
      applyProps()
      loadRegion()
      emitView()
      runInfra()
      setTimeout(() => { if (!satelliteTileSeen) fallBackToOsmBasemap() }, IMAGERY_WATCHDOG_MS)
      setTimeout(() => {
        const c = map.getCanvas()
        if (c && c.clientHeight < 40) latest.current.onMapProblem?.('The map area has no height on this screen -- try resizing the window.')
      }, 1200)
    }
    map.on('style.load', start)
    map.on('load', start)
    map.on('moveend', () => {
      loadRegion()
      emitView()
      clearTimeout(infraTimer.current)
      infraTimer.current = setTimeout(runInfra, 700)
    })
    map.on('error', (e) => {
      if (e?.sourceId === 'satellite') { fallBackToOsmBasemap(); return }
      if (e?.sourceId) return
      console.error('[map]', e?.error || e)
      latest.current.onMapProblem?.(e?.error?.message || 'The map hit an error -- see the browser console.')
    })

    map.on('click', (e) => {
      const pad = 5
      const box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]]
      const infraLayers = INFRA_LAYER_IDS.filter((id) => map.getLayer(id))
      const infra = infraLayers.length ? map.queryRenderedFeatures(box, { layers: infraLayers }) : []
      const bld = map.queryRenderedFeatures(e.point, { layers: ['registered-buildings'] })
      if (infra.length && (latest.current.xray || !bld.length)) {
        latest.current.onSelectInfra?.(parseProps(infra[0].properties))
      } else if (bld.length) {
        latest.current.onSelect?.(bld[0].properties)
      }
    })
    const pointerOn = () => { map.getCanvas().style.cursor = 'pointer' }
    const pointerOff = () => { map.getCanvas().style.cursor = '' }
    ;['registered-buildings', ...INFRA_LAYER_IDS].forEach((id) => {
      map.on('mouseenter', id, pointerOn)
      map.on('mouseleave', id, pointerOff)
    })

    return () => {
      clearTimeout(regionTimer.current)
      clearTimeout(infraTimer.current)
      clearTimeout(infraRetry.current)
      infraSeq.current += 1
      regionAbort.current?.abort()
      ro?.disconnect()
      map.remove()
      mapRef.current = null
      loadedRef.current = false
    }
  }, [])

  function applyProps() {
    const map = mapRef.current
    if (!map || !loadedRef.current) return
    const p = latest.current
    const vis = (id, on) => map.getLayer(id) && map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none')
    vis('osm-buildings', p.showOsm)
    vis('region-buildings', p.showRegion)
    vis('registered-buildings', p.showRegistered)
    vis('registered-selected', p.showRegistered)
    vis('labels', p.showLabels)
    UNDER_LAYERS.forEach((id) => vis(id, p.showUnderground))
    AIR_LAYERS.forEach((id) => vis(id, p.showAir))

    const paint = (id, prop, value) => map.getLayer(id) && map.setPaintProperty(id, prop, value)
    paint('satellite', 'raster-opacity', p.xray ? 0.22 : 1)
    paint('bg', 'background-color', p.xray ? '#04090a' : '#0b1512')
    paint('osm-buildings', 'fill-extrusion-opacity', p.xray ? 0.07 : 0.88)
    paint('region-buildings', 'fill-extrusion-opacity', p.xray ? 0.09 : 0.9)
    paint('registered-buildings', 'fill-extrusion-opacity', p.xray ? 0.22 : 0.95)

    if (terrainOn.current !== p.showTerrain) {
      terrainOn.current = p.showTerrain
      map.setTerrain(p.showTerrain ? { source: 'dem', exaggeration: 1.3 } : null)
    }
    map.getSource('registered')?.setData(p.registered || EMPTY)
    map.setFilter('registered-selected', ['==', ['get', 'id'], p.selectedId || ''])
    map.getSource('infra-hi')?.setData(p.highlight ? { type: 'FeatureCollection', features: [p.highlight] } : EMPTY)
  }

  useEffect(() => {
    applyProps()
    loadRegion()
  }, [registered, selectedId, highlight, showOsm, showRegion, showRegistered, showUnderground, showAir, xray, showLabels, showTerrain])

  useEffect(() => {
    clearTimeout(infraTimer.current)
    infraTimer.current = setTimeout(runInfra, 150)
  }, [showUnderground, showAir])

  return (
    <div className="absolute inset-0" style={{ position: 'absolute', top: 0, right: 0, bottom: 0, left: 0 }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  )
})

export default Map3D
