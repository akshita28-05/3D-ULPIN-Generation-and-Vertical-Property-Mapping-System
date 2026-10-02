"""
Pre-download (warm the cache for) the map areas you will demo or work in, so "Auto-map this view"
answers instantly and keeps working even if the free OpenStreetMap servers or your internet are down.

Run it once while you have a good connection (e.g. the night before a demo):

    cd backend
    python -m scripts.prefetch_overpass                    # the 4 city chips used by the app
    python -m scripts.prefetch_overpass --only Mumbai      # just one
    python -m scripts.prefetch_overpass --bbox 19.05 72.85 19.09 72.89 --roads
    python -m scripts.prefetch_overpass --refresh          # re-download even if already cached

Then, to prove it works with no internet at all, start the server with  OVERPASS_OFFLINE=true.
Safe to re-run: cells already saved are skipped, so an interrupted run just continues.
"""
import argparse
import sys
import time

from app.ingestion import osm_overpass, overpass_client

# Same centres as frontend/src/config/region.js (Guna is omitted: it uses the local footprints table).
PRESETS = {
    "Delhi (CP)":           (28.6315, 77.2167),
    "Mumbai (BKC)":         (19.0662, 72.8690),
    "Hyderabad (Ameerpet)": (17.4372, 78.4482),
    "Bengaluru (Majestic)": (12.9763, 77.5722),
}
HALF_SPAN_DEG = 0.012   # ~2.6 km square around each centre = a comfortable "Auto-map" view plus margin


def _fetch(label, bbox, roads, refresh):
    cells = osm_overpass._grid_tiles(*bbox)
    print(f"\n== {label}: {len(cells)} map cells")
    ok = failed = cached = 0
    for i, cell in enumerate(cells, 1):
        queries = [osm_overpass._overpass_query_for_bbox(*cell)]
        if roads:
            queries.append(osm_overpass._overpass_query_for_roads_bbox(*cell))
        for q in queries:
            data, info = osm_overpass._race_overpass_query_ex(q, use_cache=not refresh) if not refresh else _refresh_one(q)
            if data is None:
                failed += 1
                print(f"  [{i}/{len(cells)}] FAILED  {info}")
            elif info["source"] == "live":
                ok += 1
                print(f"  [{i}/{len(cells)}] downloaded ({len(data.get('elements', []))} features)")
                time.sleep(osm_overpass.TILE_REQUEST_DELAY_S)
            else:
                cached += 1
    print(f"   -> {ok} downloaded, {cached} already saved, {failed} failed")
    return failed


def _refresh_one(q):
    data, info = overpass_client.run_query(q, use_cache=False)
    if data is not None:
        overpass_client.cache_write(q, data)
    return data, info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="substring of a preset name, e.g. Mumbai")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("S", "W", "N", "E"), help="custom area instead of the presets")
    ap.add_argument("--roads", action="store_true", help="also save road centrelines (used by the city 3D viewer)")
    ap.add_argument("--refresh", action="store_true", help="re-download even if already saved")
    args = ap.parse_args(argv)

    jobs = []
    if args.bbox:
        jobs.append(("custom area", tuple(args.bbox)))
    else:
        for name, (lat, lon) in PRESETS.items():
            if args.only and args.only.lower() not in name.lower():
                continue
            jobs.append((name, (lat - HALF_SPAN_DEG, lon - HALF_SPAN_DEG, lat + HALF_SPAN_DEG, lon + HALF_SPAN_DEG)))
    if not jobs:
        print("No matching preset.")
        return 2

    failures = sum(_fetch(label, bbox, args.roads, args.refresh) for label, bbox in jobs)
    print("\nServer health:")
    for e in overpass_client.status():
        print(f"  {e['state']:<12} {e['endpoint']}  (ok {e['ok']}, failed {e['failed']}, ~{e['avg_latency_s']}s)")
    if failures:
        print(f"\n{failures} cell(s) failed - just run the same command again; finished cells are skipped.")
        return 1
    print("\nAll done. These areas now open instantly and work offline (OVERPASS_OFFLINE=true).")
    return 0


if __name__ == "__main__":
    sys.exit(main())