# Darwin: build plan (Cal Hacks 13.0) — v4, locked Sat Oct 24 14:55

> **Read me first.** This is the single source of truth for four people and four Claude Code
> agents. The direction is **locked**: no more pivots. History (original plan, Roadmap v2,
> Weekend plan v3) is in `docs/archive/PLAN_v1-v3.md`. The longer rationale and sources are
> in `docs/DIRECTION.md`.
> - **Agents read:** Parts A and B, **your own section of Part C**, Parts D and E. Skip the
>   other sections of Part C.
> - **Part B is the contract.** The v1.2 additions freeze at **CP-B (Sat 16:00)**. After
>   that, write requests in your folder's `CONTRACT_REQUESTS.md`; W-C decides.
> - **Times are Pacific.** Hard new-feature cutoff **Sun 05:00**. Devpost by **08:45** (hard
>   deadline 09:00). Judging **10:30**.

---

## Part A: What we're building

### A.1 One line
**Darwin is Cursor for Onshape, for aerodynamic design.** You tell it in plain English what
you want and what it may change. It works the problem like an aerodynamicist: it states a
hypothesis and why, predicts the effect, runs a real simulation, explains the result from
the data, keeps or rejects the change, learns, and tries the next idea. Every accepted change
is written into your Onshape model, so you watch the part morph.

### A.2 The product is the whole workflow
1. **Side panel in Onshape** (Chrome extension) next to the user's part.
2. **Plain-English request.** The user names what may change; everything else is held fixed.
3. **Hypothesis-driven loop** (Part B.3): hypothesize → predict → simulate → analyze →
   accept or reject → learn → next.
4. **Live edits in Onshape.** Each accepted step updates the model's Variable features, so
   the open tab regenerates in about 0.5 s (proven Sat 14:48, `cad/SPIKE.md`).
5. **Result.** A named version "after Darwin", a before/after, and an auditable reasoning
   trail (step cards plus a lab notebook).

The simulator is a tool Darwin uses. The product is the reasoning and the workflow.

### A.3 What "smart" means: the judges must see all five
1. Every step states **one hypothesis**, the **aero principle** behind it, and a **prediction**
   (direction + range per metric), recorded *before* the simulation runs.
2. The **solver** returns the result plus a **physics breakdown**: drag split (induced vs
   profile), stall margin, span efficiency, Reynolds number, binding constraint.
3. The agent **explains** the result from those numbers only (numeric-claim checked).
   **Prediction accuracy is scored by code**, not self-reported.
4. **Accept** → Onshape morphs. **Reject** → a logged lesson. Either way the **lab notebook**
   updates, and the next hypothesis must use it.
5. **Prediction accuracy over the run** is on screen: measurable learning.

### A.4 Scope
- **Hero (what we demo): an FSAE-style race-car rear wing.** Example prompt: *"More downforce
  without going over 20 N of drag at 25 m/s. You can change the angle, span and flap. Keep
  the mounts and endplates."*
- **Second part: the rocket fin.** Same agent, no code changes: one 10-second beat, plus our
  origin story (CMU Rocket Command).
- **Solver:** AeroSandbox AeroBuildup (+ VLM as the high-fidelity check) with NeuralFoil
  airfoil polars. About 30 ms per evaluation on the demo laptop (prototype, Sat 14:20).
- **Why not a whole car body:** that needs CFD (minutes to hours per run). The loop is
  solver-agnostic, and the more each simulation costs, the more Darwin's sample efficiency
  is worth. That's a pitch point, not a gap.
- **Parked (keep the code, no more work, not in the demo):** structural/FEA
  (`sim/adapters/structural_analytic_v1.py`, `sim/fea*`), bracket/heat-sink/duct fixtures,
  maturity-ladder UI, onboarding wizard, capability reports, Factory Droid (stretch only),
  SpacetimeDB.

### A.5 Why it wins (summary; details and sources in `docs/DIRECTION.md`)
- **Problem:** the slow part of aero design is the *judgment between simulations*, not the
  simulations. Teams (FSAE, rocketry, Design/Build/Fly) iterate by hand for weeks.
- **Why now:**
  - SimScale launched an AI agent inside Onshape on Sep 15, 2026. It runs a simulation from
    a prompt and reports back; it doesn't change the design, and its own post calls
    autonomous iteration a future direction.
  - Onshape AI Advisor (Oct 2025) lists agent workflows and design optimization on its roadmap.
  - Adam edits feature trees, without physics.
  - Simulation keeps getting cheaper (NeuralFoil is 8–1,000× faster than XFoil), so judgment
    becomes the bottleneck.
- **Proof:** on the same simulation budget, Darwin vs CMA-ES vs random vs **Darwin without the
  knowledge layer** (the ablation shows the physics knowledge is what helps).

### A.6 Verified starting point (Sat 14:51)
- `main` passes 170 Python tests. Contracts v1.0/v1.1/v2 are in place (`shared/`).
- **Onshape:**
  - Auth, reading configuration and **configured STL export: work live.**
  - **Feature updates morph an open tab live** (0.47 s).
  - Configuration updates change the document but not open tabs.
  - Element IDs change when a document is copied.
- **Backend:**
  - The population run loop works (fin bench: agent beats CMA-ES 6/9).
  - Goal parser, evidence and approval, replay, project registry, adapter bridge
    (`backend/adapters.py`).
- **Budgets:**
  - Claude: $0.31 of the $4.50 local cap.
  - Onshape prod: 85 calls logged on this laptop, against about 2,400 for the year. Re-sync
    with the usage page.

---

## Part B: Architecture and contracts

### B.1 System diagram
```
 Onshape tab (cad.onshape.com) ──── Chrome side panel (extension/, W-D)
        ▲  live regen                    │ loads http://localhost:5173/panel?doc=<tab url>
        │                                ▼
        │                     dashboard /panel route (W-D) ── REST + /ws ──┐
        │                                                                  ▼
        │                                          backend (W-C)
        │                    POST /api/sessions → investigator.py (the loop)
        │                        │            │                 │
        │      cad.variables (W-A)      sim rear_wing_v1 / fin_v1 (W-B)   domains/aero/principles.md
        └── feature updates ◄────┘      (AeroSandbox + NeuralFoil)      (knowledge layer, W-B + W-C)
```

### B.2 Repo layout and ownership (new or changed in v4)
```
extension/                     W-D  Chrome MV3 side panel (manifest, panel.html → iframe of /panel)
dashboard/src/panel/*          W-D  compact panel route: prompt, change/keep list, step cards, notebook
backend/investigator.py        W-C  the hypothesis loop (B.3)
backend/server.py, sessions    W-C  B.6 routes
shared/investigation.py (+.ts) W-C  B.4 models
shared/mocks/fake_wing.py      W-C  closed-form wing (lifting line), so nobody waits for W-B
sim/plugins/rear_wing_v1.py    W-B  the wing solver (ScorerPlugin), registered as scorer "rear_wing_v1"
domains/aero/principles.md     W-B  content; W-C owns the parser (domains/aero/pack.py)
cad/variables.py               W-A  list_variables / apply_values / create_version (B.7)
projects/rear_wing/r1.json     W-C  manifest; doc_ref "DARWIN_DOC_WING"
```
Everything else keeps its current owner (sim W-B, cad W-A, backend + shared W-C, dashboard W-D).

**Git rules:**
- Commit only inside your folders. `git pull --rebase` before every push. Never `git add -A`
  at the root.
- Tags: `contracts-v1.2` (CP-B), `loop` (CP-C), `onshape-live` (CP-D), `proof` (CP-E), `freeze`.

### B.3 The loop (what every section builds toward)
One **step** = one small experiment:
1. **Plan** (LLM, Sonnet 5.5). Input: goal, editable params with bounds and current values,
   the fixed list, the current design's metrics and breakdown, the notebook, the principles
   file, the last step's result. Output: a `Hypothesis` (B.4). Validated by code:
   - levers ⊆ editable
   - ≤ 2 levers
   - 1–4 candidates, all in bounds
   - principle ids exist (or `[]` = "exploratory")
2. **Run** (code). Evaluate every candidate with the solver (about 30 ms each).
3. **Score** (code). Compare each prediction with the actual % change → a `PredictionCheck`.
4. **Analyze** (LLM). Input: the hypothesis, the checks, and the before/after breakdown.
   Output: an explanation (≤ 60 words) and a one-sentence lesson. The numeric-claim check
   strips any number that isn't in the input.
5. **Decide** (code).
   - **accepted:** the best candidate is feasible and better on the goal.
   - **rejected:** otherwise.
   - **pivot:** two rejections on the same lever. The LLM never decides acceptance.
6. **Apply** (code). If accepted, `cad.apply_values` → the Onshape tab morphs → `design_applied`.
7. **Learn** (code + LLM lesson). Update the `Notebook`: beliefs, measured lever effects,
   ruled-out ideas, running prediction accuracy.

**Stop** when the goal is met, no lever has a predicted gain, the step budget (8) or the
simulation budget (default 20) is spent, or the user presses stop. Then create the version
"Darwin: <goal>, +<headline>%" and send `run_complete`.

**Fallback** (no LLM, or over budget): a rules step, a one-factor sweep on the lever with the
largest measured effect, labeled "rules". The demo never dies.

### B.4 Contracts v1.2 (additive; owner W-C; freeze at CP-B 16:00)

**`Goal.editable`** (`shared/contracts.py`):
- `editable: Optional[List[str]] = None` — the parameters the user allowed to change.
- `None` = every parameter not in `fixed_params`.
- The loop and the baselines **never** change a parameter outside `editable`.

**`shared/investigation.py`:**
```python
class Prediction(BaseModel):
    metric: str
    direction: Literal["up", "down", "flat"]
    pct_low: float                       # expected % change vs the current design
    pct_high: float

class Hypothesis(BaseModel):
    step: int
    levers: List[str]                    # 1-2 editable params
    candidates: List[Dict[str, ParamValue]]   # 1-4 full param dicts
    principle_ids: List[str]             # ids in domains/aero/principles.md; [] = exploratory
    rationale: str                       # <= 40 words, no numbers that aren't in the input
    predictions: List[Prediction]
    source: Literal["llm", "rules"] = "llm"

class PredictionCheck(BaseModel):
    metric: str
    predicted: Prediction
    actual_pct: float
    direction_ok: bool
    in_range: bool
    score: float                         # 1.0 in range, 0.5 direction only, 0.0 wrong

class StepResult(BaseModel):
    step: int
    tested: List[str]                    # design_ids (each also sent as design_evaluated)
    best_id: str
    deltas: Dict[str, float]             # % change per goal/diagnostic metric vs current
    checks: List[PredictionCheck]
    verdict: Literal["accepted", "rejected", "pivot"]   # decided by code
    explanation: str                     # LLM, numeric-claim checked
    lesson: str

class Belief(BaseModel):
    text: str
    evidence_steps: List[int]
    principle_id: Optional[str] = None

class Notebook(BaseModel):
    beliefs: List[Belief] = []
    lever_effects: Dict[str, Dict[str, float]] = {}   # measured %-per-unit: param -> metric
    ruled_out: List[str] = []
    accuracy: List[float] = []           # running mean prediction score after each step
```

**New events** (`shared/events.py`, `EventType += …`; W-D adds the reducer cases):

| Event | Payload | When |
|---|---|---|
| `step_planned` | `Hypothesis` | Before the step's first simulation |
| `step_result` | `StepResult` | After analysis and the decision |
| `notebook_updated` | `Notebook` | After every step |
| `design_applied` | `{design_id, geometry: GeometryRef, version: Optional[str]}` | After an Onshape write, and for the final version |

`run_started`, `design_evaluated`, `champion_updated`, `agent_message`, `budget_update` and
`run_complete` are reused unchanged. `champion_updated` means "the design currently in Onshape".

### B.5 `rear_wing_v1` (owner W-B; names frozen at CP-B)

**Editable params.** Each name is also the Onshape Variable feature name.

| Param | Unit | Range | Default |
|---|---|---|---|
| `aoa_deg` | deg | 0–16 | 6 |
| `span_mm` | mm | 700–1000 (rule width) | 850 |
| `chord_mm` | mm | 200–350 | 280 |
| `flap_angle_deg` | deg | 0–35 | 15 |
| `flap_chord_frac` | – | 0.20–0.40 | 0.30 |
| `endplate_height_mm` | mm | 100–300 | 200 |

- **Fixed:** airfoil (inverted NACA 4412), mount positions, ride height. The flap gap is
  **not modelled** (see the modelling note below).
- **Context:** `velocity_mps` = 25, `rho` = 1.225 kg/m³.

**Metrics:**
- `downforce_n`, `drag_n`, `l_over_d`
- `drag_induced_n`, `drag_profile_n`
- `cl`, `stall_margin_deg`, `span_efficiency`, `aspect_ratio_eff`, `reynolds`

**FROZEN Sat 15:01 by W-B (B1).** Names, units and ranges above are final; changes now go
through `sim/CONTRACT_REQUESTS.md`. **The demo goal uses `downforce_n` (maximize) and
`drag_n` (≤ limit).**

**The model (`sim/plugins/rear_wing_v1.py`, W-B B2; full numbers in `sim/PHYSICS.md`).**
The plan's fast path was AeroBuildup; it was measured and replaced for lift, because each
step below was checked against an independent reference first:

| Quantity | Source | Checked against |
|---|---|---|
| Lift (camber + flap) | **VLM**, one full-chord lattice with the flap deflected in the airfoil geometry | Helmbold low-AR theory ~4 %; Glauert flap theory 2–4 % to 20° |
| Viscous lift loss | **NeuralFoil** viscous/inviscid ratio of the flapped section | turns the flap over: ratio 1.0 at 10°, 0.78 at 20°, 0.54 at 35° |
| Span efficiency | **Prandtl lifting line** (Glauert) | Anderson's rectangular-wing curve; converged in stations |
| Endplates | **Hoerner** `AR_eff = AR(1 + 1.9 h/b)` | lift slope and induced drag both corrected |
| Profile drag, stall | **NeuralFoil**, deflected section, effective angle | Abbott & von Doenhoff NACA 4412 bands |

Why AeroBuildup lost the lift job, and two traps found on the way:
- **AeroBuildup over-predicts camber lift on this AR-3 wing by 27–74 %** (worst at low AoA,
  where it reports nearly the 2D section value; theory and VLM agree with each other). Its
  slope is right; the offset is not. The flap is extra camber, so flap effectiveness was
  inflated ~50 % at small angles.
- **AeroSandbox 4.2.8's VLM ignores `ControlSurface` deflection** (identical CL at 0/15/30°).
  Deflecting the flap in the airfoil coordinates avoids it.
- **Two lattices, each with its own 4412 camber, is a double-humped section**, −25 % lift at
  flap 0. One lattice with the true camber line fixes it.

Behaviour the agent will meet (all in the golden tests, `sim/tests/test_rear_wing.py`):
- **Flap has an interior optimum near 20°** (the plain-flap ceiling: no slot is modelled, so
  maximum downforce is conservative). Past it, downforce falls while drag keeps rising.
- **AoA raises downforce until stall, then it falls.** `stall_margin_deg` = NeuralFoil
  section stall angle − `aoa_deg` (13.5° clean, 9.5° at 15° flap); the default has **+3.5°**.
- **Span cuts induced drag per newton of downforce**, not raw induced drag (with chord fixed,
  area and AR grow together and cancel at fixed CL).
- **Headroom:** under a 20 N drag cap the best design in a 300-sample LHS makes **146 N vs
  105 N at the default (+39 %)**.
- 64/64 range corners evaluate; ~18 ms per fast evaluation; `hifi` is the same model at a
  converged VLM resolution, so it doubles as a mesh-refinement check (−1.7 %).
- **Inverted wing:** solved upright and reported as downforce; exact within the model, since
  no ground effect is modelled.

### B.6 Session API (owner W-C)

| Route | Contract |
|---|---|
| `POST /api/inspect` | `{doc_url}` → `{project_id, params: [{name, unit, value, min, max}], fixed: [...]}`. Resolves the document to a project by document id (`DARWIN_DOC_WING`, `DARWIN_DOC_FIN`) and reads the live Variable values (W-A). Unknown document → `404` with "Darwin supports the rear wing and fin projects". |
| `POST /api/sessions` | `{doc_url, prompt, max_sims?: 20, max_steps?: 8}` → `{run_id, project_id, goal, editable, fixed}`. Parses the prompt (goal + editable), creates the version "before Darwin", starts the investigator. Events stream on `/ws?run_id=`. |
| `GET /api/sessions/{run_id}/notebook` | → `Notebook` |
| `POST /api/sessions/{run_id}/stop` | Stops after the current step, then versions what's in Onshape |
| Existing routes | `/api/runs/{id}`, `/events`, `/api/replay`, `/api/geometry/*`, evidence and report work for sessions too (a session is a run) |

### B.7 Onshape write mechanism (owner W-A; proven by the morph spike)
- **Morph = feature update of a Variable feature:**
  1. `GET /partstudios/d/{did}/w/{wid}/e/{eid}/features`
  2. Find the `assignVariable` feature whose name == param.
  3. Set its value expression (`"8 deg"`, `"850 mm"`, `"0.3"`).
  4. `POST …/features/featureid/{fid}` with `BTFeatureDefinitionCall-1406`, the fresh
     `serializationVersion`/`sourceMicroversion`, and `rejectMicroversionSkew: false`.
  5. Check that `featureStatus` == OK.

  About 0.5 s and 1 call per changed variable.
- **Never** use configuration updates for the morph: open tabs keep their own configuration.
- **Look up the element per document** (`GET /documents/d/{did}/w/{wid}/elements?elementType=PARTSTUDIO`);
  copies get new element IDs.
- `cad.variables` API:
  - `list_variables(doc_url) -> Dict[name, {expression, value, unit}]`
  - `apply_values(doc_url, params) -> GeometryRef` — writes only the changed variables, then
    re-GETs to verify, exports the default STL for the 3D view and evidence
  - `create_version(doc_url, name) -> str`
- **Guards:**
  - Every call is ledgered.
  - Writes are refused below the budget reserve.
  - Writes go only to documents whose env var name is listed in `DARWIN_ONSHAPE_WRITE_DOCS`
    (e.g. `DARWIN_DOC_WING,DARWIN_DOC_FIN`).
  - A "before Darwin" version precedes the first write of a session.

### B.8 Knowledge layer (`domains/aero/principles.md`; content W-B, parser W-C)
25–35 principles, each in this exact block format so code can parse them:
```
### P-INDUCED-AR
statement: Induced drag scales with CL^2 / (pi * e * AR); raising effective aspect ratio cuts induced drag at fixed lift.
applies_when: wings and lifting surfaces below stall
effects: drag_induced_n: down (strong); drag_n: down (moderate); downforce_n: flat
levers: span_mm, endplate_height_mm, chord_mm
source: Anderson, Fundamentals of Aerodynamics, ch. 5 (lifting-line theory)
```
- The whole file goes in the plan prompt (~3k tokens). No vector database.
- The rocket-fin principles live in the same file.
- **Ablation:** `DARWIN_KNOWLEDGE=off` drops the file from the prompt (used by the proof bench).

### B.9 Models and budgets
- **Models:** plan and analyze use **Sonnet 5.5**; prompt parsing uses **Haiku 5.5**.
  - About 2 Sonnet calls per step, 8 steps → **about $0.40 per session**.
  - Caps: $0.60 per session, $4.50 total (local ledger).
  - Rehearse in replay. Ask the organizers about sponsor credits.
- **Onshape (prod):** a session costs about 2 calls per accepted step, plus 2 versions and
  2 reads, so about 20 calls. Simulations cost **zero** Onshape calls (analytic geometry).
  The 400-call reserve stays locked until the judging table (`DARWIN_ALLOW_RESERVE=1`).
- **Simulations:** 20 per session by default (about 0.6 s of solver time in total).

### B.10 Mocks and fixtures (written by W-C at CP-B)

| File | Behavior |
|---|---|
| `shared/mocks/fake_wing.py` | Closed-form wing: lifting line + flat-plate polar with a stall cap; B.5 names; deterministic; zero dependencies |
| `shared/fixtures/v2/sample_investigation.jsonl` | A full recorded session: 6 steps, including one rejected step and one pivot, accuracy rising. W-D builds the panel against it |
| `shared/mocks/mock_server.py` (extended) | `/api/inspect`, `/api/sessions` (streams the sample), `/notebook`, `/stop` |
| `cad/tests/fixtures/features_wing.json` | Sanitized feature list with Variable features (W-A), for mocked write tests |

---

## Part C: The four sections

**Progress (Sat 15:50):** done: A1, A3, B1, B2, B3, B4, C1, C2, C3. The investigator runs end to end on the
real rear-wing solver (CP-C's terminal criterion is met). **Not yet visible in git:** anything from
W-A (A2 wing Part Studio) or W-D (D1 extension). W-C did A3 (`cad/variables.py`).

### W-A: Onshape (`cad/`, Part Studios, write path)

**Owns:**
- `cad/` (`variables.py` new)
- the rear-wing Part Studio
- adding Variable features to the fin Part Studio
- prod document copies

**Verified facts you build on:** B.7, and `cad/SPIKE.md` "Morph spike". The disposable copy
"Darwin morph test (disposable)" is in the prod account; use it freely for experiments.

**Checklist:**
- [x] **A1 Morph spike** — done 14:49 (W-C): feature updates morph live; configuration updates don't.
- [ ] **A2 (by 18:00) Rear-wing Part Studio**, built on a dev account:
  - one **Variable feature per B.5 param** at the top of the feature list, named exactly as in B.5
  - main element: airfoil profile from imported points or a spline, inverted, rotated by `#aoa_deg`
    about the mount axis, extruded symmetric to `#span_mm`, chord `#chord_mm`
  - flap: same profile, chord `#flap_chord_frac × #chord_mm`, rotated by `#flap_angle_deg` about
    its hinge, with a fixed gap
  - endplates: height `#endplate_height_mm`, fixed thickness
  - uprights/mounts: fixed
  - Check every corner of the B.5 ranges regenerates; narrow a range and tell W-B before CP-C
    if one doesn't.
- [x] **A3 (by 19:30) `cad/variables.py`** (B.7). ✅ *done 15:50 by W-C: live-verified on the disposable copy (a Variable drove the extrude 3 → 12 mm in 0.8 s); 8 mocked tests; see `cad/SPIKE.md`*
  - `list_variables`, `apply_values`, `create_version`
  - mocked tests from a sanitized feature-list fixture
  - then live on the wing: write → re-GET → value matches → default STL bbox changes
- [ ] **A4 (by 20:30)** Variable features on the fin Part Studio (same names as the fin params)
  so the fin beat morphs too. If that's hard, the fin beat runs from replay.
- [ ] **A5 (by 21:30, with W-C)** Full session on the wing: each accepted step morphs the open
  tab; "before"/"after" versions exist; zero failed writes.
- [ ] **A6 (by 01:00)** Prod copies of the wing and fin documents; set `DARWIN_DOC_WING`,
  `DARWIN_DOC_FIN` and `DARWIN_ONSHAPE_WRITE_DOCS` on the demo laptop; re-sync
  `ONSHAPE_CALLS_REMAINING`.

**Standalone acceptance (zero network):** `pytest cad/tests` covers: variable lookup by name;
the expression format per unit; refusal for documents not in the write allowlist; refusal below
the reserve; stale-microversion handling; element lookup per document.

**Integration:** at CP-D, a live session morphs the wing in an open tab, and you watch it.

**Risks:**
- *Airfoil sketch is fiddly* → use a fixed spline from a NACA 4412 point list (no airfoil
  parameterization needed).
- *A flap rotation fails at extreme angles* → narrow `flap_angle_deg` and tell W-B.
- *Per-variable writes look jumpy* → that's fine; one write per lever per step.

### W-B: Aero (`sim/`, `domains/aero/` content)

**Owns:** `sim/` (`plugins/rear_wing_v1.py` new), `domains/aero/principles.md`, `sim/PHYSICS.md`.
The structural/FEA work is parked: leave the files, stop work.

**Verified facts you build on:**
- Prototype (Sat 14:20): `asb.AeroBuildup` on an inverted NACA 4412 rectangular wing,
  1.0 m span, 0.30 m chord, 25 m/s. About 30 ms per run, sensible trends, and the result dict
  includes `D_induced` and `D_profile`.
- NeuralFoil 0.3.2 and AeroSandbox 4.2.8 are installed.

**Checklist:**
- [x] **B1 (by 16:00)** ✅ *done 15:15 (W-B, `96fb424`)* Freeze the B.5 names and ranges (edit B.5 here, or tell W-C before 16:00).
- [x] **B2 (by 18:00) `sim/plugins/rear_wing_v1.py`** ✅ *done 15:20 (W-B, `5441e1b`)* as a ScorerPlugin (`metric_catalog`,
  `metrics`, `evaluate_metrics`, `hifi`), registered as scorer `rear_wing_v1`:
  - main + flap as **one section with a hinged trailing-edge flap** (`asb.ControlSurface`);
    two isolated surfaces stall the flap and were rejected, see B.5
  - NeuralFoil polars
  - endplate effective aspect ratio: `AR_eff = AR·(1 + 1.9·h/b)`, cited (Hoerner)
  - every B.5 metric
  - `hifi` = VLM
  - under 100 ms per fast evaluation; deterministic; `process_safe`
- [x] **B3 (by 19:00) Golden tests:** ✅ *done 15:20 (W-B, `5441e1b`)*
  - induced drag vs `CL²/(π·e·AR)` within 10 %
  - monotonic trends: AoA → downforce up until stall; span → induced drag down; flap → CL up
  - NeuralFoil section CL/CD vs the published XFoil comparison for 4412 at one Re
- [x] **B4 (by 20:00) `domains/aero/principles.md`:** ✅ *done 15:30: 29 principles, each checked against the solver (W-B, `1bf97a2`)* 25–35 principles in the B.8 format,
  covering:
  - induced drag/AR, endplates, the lift-curve slope and stall, Reynolds effects
  - camber vs profile drag, flap angle and chord, the downforce/drag tradeoff, q scaling
  - the fin set: stability vs span/sweep, flutter vs thickness
  - Cite real sources (Anderson, Katz *Race Car Aerodynamics*, McBeath, Hoerner, the NeuralFoil
    paper); no invented numbers.
- [ ] **B5 (by 01:00)** Validation table for `PHYSICS.md` and the pitch: what's validated
  against what, the error, and the validity envelope (subsonic, no ground effect, below stall
  for linear predictions).

**Standalone acceptance:** `pytest sim/tests` (golden tests green, no network).

**Integration:** at CP-C the investigator runs on your solver end to end.

**Risks:**
- *Multi-element VLM is slow* → fast path AeroBuildup, VLM only for `hifi`.
- *NeuralFoil post-stall noise* → report `stall_margin_deg` and let the loop treat negative
  margin as infeasible.

### W-C: Agent (`shared/`, `backend/`, contract owner)

**Owns:**
- `shared/` (contracts and mocks)
- `backend/` (`investigator.py`, sessions)
- `projects/`
- the parser in `domains/aero/pack.py`
- `demo/recordings/`, `demo/bench*.json`

**Checklist:**
- [x] **C1 (by 16:00) Contracts v1.2** ✅ *done 15:02 (W-C, `c1f264e`, tag `contracts-v1.2`)* (B.4):
  - models, events, TS mirror
  - `fake_wing.py`, the sample investigation fixture, mock-server routes (B.10)
  - `projects/rear_wing/r1.json`
  - tag `contracts-v1.2`
- [x] **C2 (by 18:00) `backend/investigator.py`** ✅ *done 15:13, live-tested 15:25 on the real solver: +27% downforce inside the drag limit, 16 sims (W-C, `80b9e91`, `22871ef`)* end to end in the terminal on `fake_wing`,
  then on `rear_wing_v1` when W-B lands it:
  - plan / run / score / analyze / decide / learn (B.3)
  - validation of LLM output; rules fallback; stop rules
  - every event in B.4
- [x] **C3 (by 19:00) Goal parser** ✅ *done 15:45 (W-C): explicit phrases decide, the LLM only fills unusual wording, invented pins dropped* emits `editable` ("you can change the angle, span and flap"
  → `aoa_deg`, `span_mm`, `flap_angle_deg`, `flap_chord_frac`) and holds everything else
  fixed. Assumptions are listed for the user.
- [ ] **C4 (by 21:30) Session API** (B.6), with `cad.variables` on each accepted step, the
  before/after versions, and evidence/report for sessions.
- [ ] **C5 (by 01:00) Proof bench** on the wing, same simulation budget (20), 3 goals × 3 seeds:
  - Darwin, CMA-ES, random, Darwin with `DARWIN_KNOWLEDGE=off`
  - sims-to-target and the final result
  - output `demo/bench_wing.json`
- [ ] **C6 (by 02:00)** Recordings: a wing session and a fin session, both replayable with no
  keys. The old population loop stays as the baseline engine.

**Standalone acceptance:** `make test` with fakes. This covers:
- LLM-output validation (bad lever, out of bounds, unknown principle)
- prediction scoring
- the accept/reject rule
- the notebook update
- the rules fallback
- the numeric-claim check on explanations
- the session API on the mock CAD

**Integration:** CP-C (terminal loop on the real solver), CP-D (live in Onshape), CP-E (bench).

**Risks:**
- *LLM proposes junk* → validated or replaced by the rules step.
- *Explanations sound right but are wrong* → numbers only from the input; predictions scored.
- *Cost* → Sonnet only for plan and analyze; cache and replay for rehearsal.

### W-D: Panel and story (`extension/`, `dashboard/`, `docs/`)

**Owns:**
- `extension/`
- `dashboard/` (the new `/panel` route)
- `docs/pitch.md`, `docs/devpost.md`, `README.md`
- slides, the video

**Checklist:**
- [ ] **D1 (by 17:00) `extension/`:** Chrome MV3, `sidePanel` permission, panel enabled only on
  `cad.onshape.com` tabs (`sidePanel.setOptions` + `tabs.onUpdated`). It reads the active tab
  URL and loads `http://localhost:5173/panel?doc=<encoded url>` in an iframe. Load it unpacked.
- [ ] **D2 (by 19:00) `/panel` route** (~400 px wide), built against `sample_investigation.jsonl`
  on the mock server:
  1. prompt box + "will change / will keep" chips (`/api/inspect`)
  2. **step cards**: hypothesis, principle tag, prediction ranges → actual values, verdict
     badge, explanation, lesson
  3. prediction-accuracy sparkline
  4. notebook drawer (beliefs, lever effects, ruled out)
  5. final summary with before/after
  6. stop button
- [ ] **D3 (by 21:30)** Live against the backend during a real session, next to the morphing
  Onshape tab.
- [ ] **D4 (by 23:30) Pitch and Devpost** from Part F and `docs/DIRECTION.md`. Slides: problem,
  the loop, live demo, proof bench, path to production (Onshape App Store app, CFD adapter).
- [ ] **D5 (by 01:00)** Hide the old population panels from the main path; keep them on a
  `/proof` page for the bench.
- [ ] **D6 (by 04:30)** Fallback video from the final recording, kept on two laptops.

**Standalone acceptance:** `npm test` and the build pass against the mock server; the panel
renders the full sample session.

**Integration:** at CP-D the panel drives a live session.

**Risks:**
- *An iframe to localhost is blocked* → the extension panel calls the backend directly with
  `fetch` (`host_permissions: http://localhost:8000/*`) and renders a minimal native panel.
- *Too much text on cards* → collapse the explanation by default; show prediction vs actual
  as two bars.

---

## Part D: Checkpoints and cut lines

| Checkpoint | Time | Pass | Tag |
|---|---|---|---|
| **CP-B** | Sat 16:00 | Contracts v1.2 + fixtures + mocks; B.5 names frozen; extension skeleton loads | `contracts-v1.2` |
| **CP-C** | Sat 18:00 | Investigator runs end to end in the terminal on the rear-wing solver; wing Part Studio regenerates | `loop` |
| **CP-D** | Sat 21:30 | Full loop in Onshape: panel → session → step cards → the part morphs → versions | `onshape-live` |
| **CP-E** | Sun 01:00 | Proof bench + ablation; validation table; recordings | `proof` |
| **Rehearsal** | Sun 02:30 | Two full 2-minute runs, one live and one replay | |
| **Cutoff** | Sun 05:00 | Bug list only after this | `freeze` |

**Cut lines, in order:**
1. **The wing Part Studio isn't ready by 19:30** → the solver and loop still run on the wing;
   the Onshape morph uses the fin (Variable features added) for the live beat.
2. **CP-C slips past 19:30** → drop the flap (4 params); `fake_wing` keeps the panel moving.
3. **CP-D slips past 23:00** → demo from the dashboard in a browser window next to the
   Onshape tab, without the extension.
4. **CP-E slips** → drop the no-knowledge ablation; keep Darwin vs CMA-ES.

**Never cut:** step cards with prediction vs actual, the live Onshape morph (or its replay),
the replay fallback, rehearsal, Devpost.

---

## Part E: Schedule (Pacific)

| Time | W-A | W-B | W-C | W-D |
|---|---|---|---|---|
| 14:55–16:00 | A2 wing Part Studio | B1 names, start B2 | **C1 contracts** | **D1 extension** |
| **16:00** | **CP-B** (all, 10 min) | | | |
| 16:00–18:00 | A2 | B2 solver | C2 investigator | D2 panel on fixtures |
| **18:00** | **CP-C**; dinner until 18:45 | | | |
| 18:45–21:30 | A3, A4, A5 | B3 tests, B4 principles | C3, C4 | D2, D3 |
| **21:30** | **CP-D** | | | |
| 21:30–01:00 | A6 prod copies, help C6 | B5 validation | C5 bench | D4 pitch/Devpost, D5 |
| **01:00** | **CP-E** | | | |
| 01:00–02:30 | C6 recordings, fixes, video v1 | | | |
| **02:30** | **Rehearsal ×2** | | | |
| 02:30–05:00 | Fix list only; D6 video; Devpost final | | | |
| **05:00** | **Cutoff.** Sleep until 08:00 | | | |
| 08:00–08:15 | Smoke test, live and replay | | | |
| 08:15–08:45 | **Submit Devpost** (hard deadline 09:00) | | | |
| 08:45–10:00 | Rehearsal ×3, Q&A drill, charge laptops | | | |
| 10:00–10:30 | Table: demo laptop, the Onshape tab with the wing, second laptop on replay + video. `DARWIN_ALLOW_RESERVE=1` | | | |
| **10:30–12:30** | **Judging.** W-C drives, W-D narrates, W-B takes aero questions, W-A takes Onshape questions | | | |

---

## Part F: Demo, pitch, tracks

### F.1 Two-minute demo
| Time | Beat |
|---|---|
| 0:00 | **Problem.** "Improving an aero part is a loop: change CAD, simulate, interpret, decide. The slow part is the judgment between runs." |
| 0:15 | **Onshape, rear wing open, Darwin panel.** Type the prompt (A.4). Darwin shows what it will change and what stays fixed, then the baseline breakdown. |
| 0:35 | **Step 1:** "Raise angle 6°→10°: downforce ∝ CL and there's stall margin. Predict +25–35% downforce, +20–30% drag." Simulates, the wing tilts in Onshape. "+34% downforce but +41% drag: induced drag grows with CL². Over budget, rejected. Lesson: drag is binding, and it's mostly induced." |
| 0:55 | **Step 2:** "Attack induced drag: widen span to the limit (∝ 1/AR)." Accepted; the wing widens. The accuracy sparkline ticks up. |
| 1:15 | **Steps 3–5** fast-forwarded. Final result at equal drag. Before/after. Version "after Darwin" in Onshape. |
| 1:35 | **Proof slide:** same 20-simulation budget. Darwin vs CMA-ES vs random vs Darwin without the knowledge layer. |
| 1:50 | **Close:** "Same agent on our rocket fin, no code changes. Swap in CFD and it gets *more* valuable. Darwin reasons like an aerodynamicist, inside your CAD." |

The numbers above are illustrative. **Say only the numbers from the actual run.**

### F.2 Likely judge questions
| Question | Answer |
|---|---|
| Isn't this just an optimizer with an LLM? | An optimizer needs hundreds of runs and gives no reasons. Here's the ablation, and here's the reasoning trail with scored predictions. |
| How accurate is the aero? | AeroBuildup/VLM with NeuralFoil, validated against XFoil within a few percent (NeuralFoil paper, our validation table). Right for ranking design moves; final sign-off is CFD or a wind tunnel, which the loop can call. |
| What if the LLM's physics is wrong? | It predicts before every simulation, and the solver checks it. Accuracy is on screen; when it's wrong, it says so and changes course. Acceptance is decided by code. |
| Why only aero? | Depth over breadth. The loop is domain-agnostic; aero is where we could make it genuinely smart this weekend. |
| SimScale already has an Onshape agent. | It runs a simulation and tells you the answer. Darwin decides what to change, changes your model, and learns. |
| Does it break my CAD? | It writes only the variables you allowed, versions before and after, and every step is one click to restore. |

### F.3 Tracks
- **Overall / Most Technically Complex:** in.
- **Microsoft: Built for the Real World (primary):**
  - customer: student aero teams
  - measurable usefulness: sims-to-target vs CMA-ES, the ablation
  - path to production: Onshape App Store app, CFD adapter
  - responsible design: numbers only from solvers, versioned writes, code decides acceptance
- **Anthropic:** named community: collegiate aero teams, starting with CMU Rocket Command (our
  lived problem, in our own words; never invent quotes). Claude is the reasoning, and we show
  where it fails and how predictions catch it.
- **Factory Droid:** stretch only, after 01:00, if Droid does real work in the running loop.
- **SpacetimeDB:** dropped.

---

## Part G: Risks

| # | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| 1 | Wing Part Studio takes too long | Medium | High | Fixed spline airfoil; cut line 1 (fin morphs instead) | W-A |
| 2 | LLM steps are slow or expensive | Medium | Medium | Two Sonnet calls per step; cache; replay for rehearsal; rules fallback | W-C |
| 3 | Explanations sound right but are wrong | Medium | High | Numbers only from inputs; predictions scored by code; principles cited | W-C |
| 4 | The extension can't iframe localhost | Low | Medium | Native panel with direct fetch; cut line 3 | W-D |
| 5 | Onshape writes fail mid-demo | Low | High | Version before writes; read-back verify; replay fallback; reserve unlocked at the table | W-A |
| 6 | Agent doesn't beat CMA-ES on the wing | Medium | Medium | Report honestly; the ablation and the reasoning trail are the story; small budgets favor priors | W-C |
| 7 | Scope creep | High | High | This plan is locked. Anything not in F.1 waits until after CP-E | All |
| 8 | Sleep debt | High | Medium | 05:00 cutoff, 3 h sleep, rehearsal in the morning | All |
