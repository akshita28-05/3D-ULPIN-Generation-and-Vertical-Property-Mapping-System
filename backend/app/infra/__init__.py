"""Automatic discovery of the two spatial-unit kinds a 2D cadastre cannot see --
underground structures and elevated / air-right corridors -- from open data.

The problem statement (SIH26011) is a software problem: no GPR rig, no LiDAR
flight, no survey crew. So this package never needs a sensor or a manual form.
It reads what the public map already knows (OpenStreetMap tunnels, metro
alignments, basements, underground parking, buried cables/pipelines, viaducts,
flyovers, overhead transmission lines), turns it into typed 3D volumes with a
depth / height range, and stamps every number with where it came from.

  osm_infra.py   Overpass query + the tag -> structure-type rules (pure functions)
  service.py     grid-cell scan with cache, persistence, and linking to parcels
"""
