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
