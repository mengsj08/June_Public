# Fictional demo fixture

Everything below `demo/` is invented for product demonstration. Names, projects,
organizations, dates, identifiers, results, and paths do not refer to real people
or institutions.

- `projects/` contains two research projects and eight task cards.
- `projects/literature-review/.canvas/DEMO-001/main.canvas.json` is the editable
  per-card sidecar for the startup entry card. Other cards resolve to their own
  `.canvas/<task_id>/main.canvas.json` path when first saved; card canvases never
  share a project-level fixture.
- `projects/literature-review/DEMO-001.md` is the startup entry card for that canvas.
- `.real-projects/projects.json` registers both fictional projects for the homepage
  Project Canvas; its relative work directories resolve from the repository root.
- `kanban.demo.config.json` is a loopback-only profile with every external integration disabled.

## Demo homepage acceptance rule

Start from a clean demo instance and open the kanban homepage before testing the
canvas. The project area and card list must render, the browser console must have
zero errors, and every local page resource must return without a 4xx or 5xx
response. Both `literature-review` and `data-analysis` must appear in the project
area, and opening `literature-review` must show its linked cards in Project Canvas.

## Demo canvas acceptance rule

Every demo smoke test must exercise a **card canvas**, not only a project map, in
this fixed order: load it, save it, then verify every REF resolves. The response
schema must equal the backend `CANVAS_SCHEMA`, every `source_ref` must be an
object, the save must return HTTP 200, and no REF may finish as `missing`.
AI-only canvas actions must return a readable unavailable result when the demo
profile has no provider; they must not surface a 404 or 5xx error.
