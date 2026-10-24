# Onshape configuration spike — verdict

Run: `python -m cad.spike all` (reproducible). Account: dev. Cost: 9 calls.
Raw responses in gitignored `cad/SPIKE_raw/`. No document ids recorded here.

## Verdict: **A — configured export works.** `mode = "configuration"`

Configured STL export returns correct geometry without writing to the document.
The ladder's fallbacks (B custom feature, C per-variable POST) are **not needed**
and stay unimplemented.

### Cost: 2 calls per design, not 1

Every STL export is a **307 redirect followed by a 200**, so it costs two HTTP
requests. The ledger charges both, conservatively, until spike step 6 (the
usage-page check) proves whether Onshape bills the redirect.

Budget consequence: with `geometry_max_builds = 6`, a demo run costs **~12
Onshape calls**, the top of the 6–12 range PLAN.md B.9 assumed. Judging at ~15
visits is ~180 calls, still inside the 400 reserve.

### Speed: much faster than estimated

244–350 ms per export, against the 1.6–1.9 s in PLAN.md's verified facts. That
estimate came from the Oct 21 *update + export* path; configured export skips
the write entirely. Geometry is no longer near the critical path for a
60-second demo.

## Step-by-step results

| Step | Result |
|---|---|
| 0. auth (`GET /users/sessioninfo`) | **200.** Keys valid. |
| 1. `GET .../configuration` | **200.** 5 parameters, all `BTMConfigurationParameterQuantity-1826`, names match the contract's `cad_ref`s. |
| 2. `POST .../configurationencodings` | **404.** Endpoint path as documented in PLAN.md S1 does not exist on `/api/v10`. **Does not matter** — see below. |
| 3. `GET .../stl?configuration=...` | **200** for all 3 param sets. Geometry returned, 12 triangles each. |
| 4–8 | **Deferred past CP1** (failure-mode responses, massproperties, usage-page redirect check, commit path, glTF). |

### The 404 is not a blocker: local encoding is verified

`cad.onshape_client.encode_configuration` builds the string locally
(`name=value+unit;...`, URL-encoded). It is **proven correct** by the exports:
all three param sets produced volumes matching the analytic formula to the
digit.

| Param set | Analytic volume | Exported volume |
|---|---|---|
| default (90 / 0.5 / 60 / 30 / 3) | 12150 mm³ | **12150 mm³** |
| near-min (55 / 0.25 / 35 / 5 / 2.2) | 2647 mm³ | **2647 mm³** |
| near-max (125 / 0.9 / 85 / 55 / 4.8) | 48450 mm³ | **48450 mm³** |

Exact agreement on three different param sets means `root_chord`,
`taper_ratio`, `semi_span` and `thickness` all arrive correctly and the
configuration really is being applied. Local encoding costs 0 calls per design,
so the missing endpoint buys us nothing anyway.

## RESOLVED defect: the sweep angle was complementary

All three exports failed the analytic bbox sanity check on `xmax`, while volume
matched exactly. Planform area is independent of sweep (shearing a trapezoid
preserves area), so a wrong sweep angle is exactly the error that moves the
bounding box without touching the volume.

Solving `s·tan(Λ) + c_t = xmax` for the realised angle:

| `sweep_deg` asked | Λ realised | 90 − asked |
|---|---|---|
| 30.0 | 60.00 | 60.0 |
| 5.0 | 85.00 | 85.0 |
| 55.0 | 35.00 | 35.0 |

The Part Studio measures the leading-edge angle from the **root chord (x axis)**.
B.5 defines Λ from the **spanwise direction (z axis)**: tip LE sits at
`x = s·tan Λ`, so Λ = 0 means an unswept leading edge.

**Fixed** in the Part Studio (the sketch angle now reads `90 deg - #sweep_deg`).
Re-verified with `python -m cad.spike export`:

| Param set | Volume | bbox worst error | Export |
|---|---|---|---|
| default (90 / 0.5 / 60 / 30 / 3) | 12150 mm3 | **0.000 mm** | 383 ms |
| near-min (55 / 0.25 / 35 / 5 / 2.2) | 2647 mm3 | **0.000 mm** | 250 ms |
| near-max (125 / 0.9 / 85 / 55 / 4.8) | 48450 mm3 | **0.000 mm** | 249 ms |

Exact agreement on bounding box and volume across the parameter box. The
configured-export path is verified end to end.

This is a CAD defect, not a contract or code defect. The sanity check caught it
with zero extra calls, which is what it is for — without it, the demo would have
shown fins swept the wrong way with plausible-looking mass and area.

## Sweep bound clarification

The minimum remains **0 deg**. Darwin measures sweep from the spanwise axis, so
0 deg is an unswept, right-angle fin. The earlier report that 0 did not
regenerate came from the pre-fix complementary-angle sketch and is not a reason
to narrow the design-space bound. See `cad/CONTRACT_REQUESTS.md`.

## Morph spike (Plan v4 A1) — Sat Oct 24, 14:40–14:49. Verdict: **feature/variable updates morph live**

Run by W-C on a disposable API copy of the fin document ("Darwin morph test
(disposable)", prod account), with a teammate watching the copy open in a browser.
20 ledgered calls in total. No IDs recorded here.

| Method | Write latency | Document changed? | Open tab changed live? |
|---|---|---|---|
| (a) Configuration update (`update_configuration`: current values + defaults) | 0.2–1.0 s | **Yes**: read-back matches, microversion advances, default-config STL bbox 90×60 → 120×85 → 77×30 mm | **No.** On refresh the new default flashed, then the viewer's own selected configuration re-rendered the old shape. Configuration values are per-viewer session state |
| (b) Feature update (`POST /partstudios/d/{did}/w/{wid}/e/{eid}/features/featureid/{fid}`, `BTFeatureDefinitionCall-1406`, body = fresh GET's feature with one parameter expression changed, plus `serializationVersion` and `sourceMicroversion`) | **0.47 s** | **Yes**: featureStatus OK, STL thickness 3 → 15 mm | **Yes, live, no refresh** |

**Consequences:**
- Darwin's per-step writes edit the **model** (Variable features), never configuration defaults.
- **The rear-wing Part Studio must be driven by Variable features** (`#aoa_deg`, `#span_mm`, …) placed
  at the top of the feature list, with dimensions referencing them. One feature-update POST per
  changed variable (~0.5 s each); a step that changes 1–2 levers costs 1–2 calls.
- The fin Part Studio is configuration-driven, so it can't morph live as built. Either add
  Variable features to it, or show the fin beat from replay.
- **Element IDs change when a document is copied.** Always look up the Part Studio element
  per document (`GET /documents/d/{did}/w/{wid}/elements?elementType=PARTSTUDIO`).
- Copying a document: `POST /documents/{did}/workspaces/{wid}/copy` with
  `{"newName", "isPublic": false}`, 0.9 s, 1 call.
- Configured export still works for read-only what-if geometry, and the default-config export
  reflects feature edits.
