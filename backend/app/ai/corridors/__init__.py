"""Detection of the "non-surface" spatial units the problem statement lists
next to apartments and underground utilities: elevated transport corridors
(metro / flyover / elevated road / elevated rail), air-right envelopes, and
parking (multi-storey, underground, surface, painted stalls).

Three independent evidence sources, fused, none of them trained-model magic:
  osm_detector.py     -- OpenStreetMap infrastructure tags (bridge / layer /
                         viaduct / parking) -> typed corridor + parking proposals
  lidar_detector.py   -- aerial LiDAR: elevated, flat, elongated structures that
                         are NOT buildings -> MEASURED deck height
  parking_detector.py -- painted-stall detection on an orthophoto (classical
                         Hough), floor-plan stall geometry, OSM parking areas
Every output carries `source`, `height_source` and `confidence`, so a reviewer
can see what was measured, what was tagged and what was assumed.
Nothing here is an official record: these are PROPOSALS for verifier review.
"""
