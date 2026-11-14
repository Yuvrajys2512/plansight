# Codex prompt: P5 3D scene backend (`/api/scene3d`)

Paste everything below the line into Codex, running in `D:\Junction-codex`.

---

Read `AGENTS.md` first and follow its rules. Before you start, bring this worktree up to date with main:
`git merge main` (main is ahead of this branch; resolve nothing by hand without telling me).

## Goal
The web UI is getting a "Lift to 3D" view built with three.js. Build the **backend** that serves 3D geometry for
our demo drawings. Do NOT touch `web/`. Python only. No LLM calls.

## Endpoint
`GET /api/scene3d?path=<drawing path as returned by /api/drawings>` in `plansight/api/app.py`
(add the route next to the others; keep the plain `/scene3d` alias pattern the file already uses).

Return JSON, cached to disk under `cache/scene3d/<sha1(path)>.json` (and `.glb` for IFC) so Modal never recomputes.

### Swiss dwellings (`*.pdf` / `*.png` → use the sibling `.dxf`, same stem)
Use `ezdxf`. The DXF has semantic layers: `WALL` (LWPOLYLINE + HATCH), `ROOM_OUTLINE`, `ROOM_TEXT` (TEXT),
`DOOR` (LWPOLYLINE + ARC), `WINDOW`, `FIXTURE` (LWPOLYLINE + CIRCLE), `UNIT_OUTLINE`.
Response:
```json
{
  "kind": "plan",
  "units": "m",
  "bounds": [minx, miny, maxx, maxy],
  "walls":   [{"id": "w0", "polygon": [[x,y],...], "height": 2.7}],
  "rooms":   [{"id": "r0", "polygon": [[x,y],...], "name": "Küche", "number": "2.02", "area_m2": 12.05}],
  "doors":   [{"id": "d0", "polygon": [[x,y],...]}],
  "windows": [{"id": "n0", "polygon": [[x,y],...]}],
  "fixtures":[{"id": "f0", "polygon": [[x,y],...]}],
  "units":   [{"id": "u0", "polygon": [[x,y],...]}]
}
```
- Coordinates in metres (check the DXF `$INSUNITS` / magnitudes; convert if mm or cm). Recentre so the plan's centre is (0,0).
- Walls: prefer HATCH boundary paths (filled wall polygons); fall back to closed LWPOLYLINEs. Drop degenerate polygons (<3 pts, area ~0).
- Rooms: match each `ROOM_TEXT` to the `ROOM_OUTLINE` polygon containing its insert point (shapely is fine if installed;
  otherwise a point-in-polygon helper). Parse name / number / area out of the text the same way `plansight/solvers/swiss.py` does (reuse its helpers if possible).
- Door ARCs: approximate as a polygon (pie slice), so the frontend only ever deals with polygons.
- Also return `"sheet_transform"`: the affine mapping DXF coords → the pixel coords of the image `/api/render` serves for this
  path (so the frontend can lay the 3D model exactly over the 2D sheet before lifting it). If you can't derive it reliably, return
  `null` and say so in your summary. Do not guess.

### IFC models (`*.ifc`, or an `ifc_models` sheet whose drawing has `model_path`)
Use `ifcopenshell.geom` (installed). Export the model to **GLB** with one mesh per element, mesh name = the element's GlobalId.
Serve it at `GET /api/scene3d/glb?path=...`. The JSON response:
```json
{
  "kind": "ifc",
  "glb_url": "/api/scene3d/glb?path=...",
  "up": "z",
  "elements": [{"guid": "...", "type": "IfcDoor", "name": "...", "storey": "0"}]
}
```
- Include IfcWall*, IfcSlab, IfcDoor, IfcWindow, IfcSpace, IfcStair*, IfcRoof, IfcColumn, IfcBeam. Spaces should be in the GLB too.
- If GLB export via `ifcopenshell.geom.serializers` is awkward, fall back to iterating `ifcopenshell.geom.iterator` and writing
  the GLB with `trimesh` (check it's installed; add to requirements.txt if you need it).

### Linking answers to 3D (small change, important)
In the IFC solver, when an answer counts or reads elements, add `"guids": [...]` (the GlobalIds involved) to the answer
dict. For Swiss counting answers (doors, windows, rooms), add `"scene_kind": "doors" | "windows" | "rooms" | ...` and, for
room questions, the matched room names. The frontend uses these to make exactly those elements glow in 3D.
Do not change any answer values or the eval behaviour.

### Demo bundle
Make `scripts/build_demo_bundle.py` also precompute the scene JSON/GLB for the 6 Swiss + IFC demo drawings into `cache/scene3d/`
(Modal ships `cache/`). Keep the GLB small (<5 MB each).

## Tests and done-criteria
- Add `tests/test_scene3d.py`: one Swiss drawing returns walls>10, doors>5, rooms with names; one IFC drawing returns a GLB that
  loads with `trimesh` and contains at least one IfcDoor guid from `elements`.
- `.venv\Scripts\python.exe -m pytest -q` passes (64 existing + new).
- Log what you built in `CODEX_LOG.md` (Phase 5 section), with timings. Commit on this branch with a clear message.
  No Co-Authored-By trailers.
- In your final summary list: endpoint shapes, whether `sheet_transform` is reliable, GLB sizes, any drawing that failed.
