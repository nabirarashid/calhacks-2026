# shared/: frozen contracts (owner: S3)

Every section imports from here, and only S3 edits it. The spec is PLAN.md Part B.

| File | What it is |
|---|---|
| `contracts.py` | pydantic models + `canonicalize`, `param_hash`, `geometry_key`, `make_design_id` (source of truth) |
| `events.py` | websocket and recording `Event` envelope, one payload model per event type, `make_event`, `validate_event` |
| `contracts.ts` | TypeScript mirror (snake_case on the wire), plus `AnyDarwinEvent` discriminated union |
| `fin_geometry.py` / `.md` | fin_v1 analytic geometry: area, volume, bbox, corners, square-edged STL |
| `fixtures/` | example payloads + `sample_run.jsonl` (recorded event stream from the fakes) |
| `mocks/` | `fake_sim`, `fake_cad`, `fake_llm`, `mock_server` (`:8000`), `make_sample_run`, `make_fixtures` |
| `check.py` | `make contracts`: validates every fixture and recording |

## Usage

```bash
python -m shared.check                 # or: make contracts
python -m shared.mocks.mock_server     # fixture-backed REST + WS on :8000 (or: make mock)
python -m shared.mocks.make_sample_run # regenerate fixtures/sample_run.jsonl
```

Run from the repo root with Python 3.9 (`pip install -r requirements.txt`).

## Changing a contract

Don't edit this folder. Write what you need in `<your section>/CONTRACT_REQUESTS.md` and tell S3.
- Only **additive, optional** fields are accepted.
- Each accepted change bumps `CONTRACT_VERSION` and is announced in the team chat.

## Contracts v2 (tag `contracts-v2`, CONTRACT_VERSION 1.1.0)

Projects, onboarding and adapters, per PLAN.md weekend plan v3 Part B. Additive: every v1
model and recording still works. Owner: W-C.

| File | What |
|---|---|
| `manifest.py` / `manifest.ts` | `ProjectManifest`, maturity levels, `CadInventory`, `CapabilityReport`, `ProbeResult`, `GeometryEvidence`, `AdapterCapability`, and the REST bodies for `/api/projects/*` |
| `adapters.py` | `CadAdapter`, `SolverAdapter`, `GeometryVerifier`, `DomainPack` protocols |
| `contracts.py` (v1.1) | `AnalysisArtifact`; `DesignResult.analysis` (optional) |
| `events.py` (v1.1) | `analysis_progress` event (FEA stages) |
| `fixtures/v2/` | fin and bracket manifests (bracket also as a level-1 draft), bracket/heat-sink/duct inventories, duct and heat-sink capability reports, structural metric catalog, bracket goal, `sample_structural_run.jsonl` (a failure, then a verified repair) |
| `mocks/fake_structural.py` | closed-form bracket `SolverAdapter` (blocks until material/load/fixtures are confirmed) |
| `mocks/fake_onboarding.py` | in-memory inspect → questions → activate flow behind the mock server |

```bash
python -m shared.mocks.make_fixtures_v2   # regenerate fixtures/v2 (+ bracket STLs in fixtures/geometry)
```

The mock server now serves every v2 route: `GET /api/projects`, `POST /api/projects/inspect`
(URL containing `bracket`, `heat`/`sink` or `duct` picks the fixture), manifest GET/POST
(stale revision → 409), `probe`, `activate`, `GET /api/runs/{id}/commit/preview`, and
`POST /api/discover` (alias for inspect). `POST /api/runs` with `project_id: "bracket..."`
streams the structural sample. Inventories are synthetic until W-A swaps in sanitized captures
(same file names and shape).

## Contracts v1.2 (tag `contracts-v1.2`, CONTRACT_VERSION 1.2.0) — the investigation loop

PLAN.md Part B.3–B.6 and B.10. Additive: every earlier model, fixture and recording still validates.

| File | What |
|---|---|
| `contracts.py` | `Goal.editable` (params the user allowed to change; `None` = all not fixed) |
| `investigation.py` / `investigation.ts` | `Hypothesis`, `Prediction`, `PredictionCheck`, `StepResult`, `Notebook`, `DesignApplied`, and `score_prediction()` (deterministic scoring) |
| `events.py` | `step_planned`, `step_result`, `notebook_updated`, `design_applied` |
| `mocks/fake_wing.py` | Closed-form rear wing with the `rear_wing_v1` names (lifting line, endplate AR, flap effectiveness, soft stall). Used by wiring only until W-B's solver registers |
| `fixtures/v2/sample_investigation.jsonl` | A recorded 6-step session: angle rejected (drag +50%), span and endplates accepted, a small angle step accepted, the flap rejected twice then ruled out. Downforce +35% at 14.87 N (limit 15). Prediction accuracy 0.75 → 0.89 |
| `fixtures/v2/manifest_wing.json`, `goal_wing.json` | The demo project and goal (same as `projects/rear_wing/r1.json`) |

Mock server: `POST /api/inspect`, `POST /api/sessions` (streams the sample), `GET /api/sessions/{id}/notebook`,
`POST /api/sessions/{id}/stop`. The finished sample is preloaded as run `session_fixture_wing`.
| `fixtures/v2/sample_investigation_live.jsonl` | A **real** session: Sonnet 5.5 planning on `fake_wing` (Sat 15:22), 5 steps, +21% downforce at 14.73 N. Use it for real text lengths on the step cards. Its prediction scores predate the in-range scoring fix, so a few small in-range changes show 0 |

