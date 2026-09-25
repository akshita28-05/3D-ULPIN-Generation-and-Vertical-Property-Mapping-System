# Detailed 3D building (BHU-3D look) — what changed

**New**
- `frontend/src/components/building3d/buildingPlan.js` — pure geometry planner (windows + mullions, pilasters, balcony bands, floor-slab lines, parapet, roof lift-room / water tanks / antenna, entrance canopy). No Three.js import.
- `frontend/src/components/building3d/DetailedBuilding.js` — Three.js glue (one merged mesh per material, floor label tag, north marker, contact shadow).
- `frontend/src/components/building3d/buildingPlan.selftest.mjs` — `node src/components/building3d/buildingPlan.selftest.mjs` (from `frontend/`).

**Edited**
- `components/ThreeScene.jsx` — new props `buildingStyle` (`'detailed'` | `'volumes'`, default detailed) and `sceneTheme` (`'dark'` | `'light'`, default dark). Floors are picked through invisible proxies; selecting a floor / unit turns that floor cyan and lifts the floors above it; a floating `F06` / `F06-U12` tag is drawn. Any footprint the planner can't handle falls back to the old translucent volumes automatically.
- `pages/citizen/Viewer3D.jsx` — toolbar: **Facade** toggle, sun/moon theme toggle, **Show/Hide Underground** button (plus a note when a parcel has no registered underground assets).

**Behaviour notes**
- Facade colour by dominant unit type on the floor: brick = commercial, concrete = parking, sand = residential. The blue band on every 3rd residential floor is cosmetic only.
- Basements keep the original translucent slab.
- The optional drone-photo texture on the old glass shell is not used while the detailed facade is on (switch **Facade** off to get it back).
- To keep the original cream scene by default: change `useState('dark')` → `useState('light')` for `sceneTheme` in Viewer3D.jsx.
- `BulkAreaViewer3D.jsx` has its own separate renderer and was not changed.

**Not verified in a browser** — no npm/network in the build environment. Checked instead: planner self-test, JSX syntax parse, and a harness that runs ThreeScene's real scene-building code against a stubbed `three` for 10 states (selection, exploded, fallback, 2D, …). Run `npm install && npm run dev` and look before merging.
