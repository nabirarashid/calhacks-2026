# Darwin: build plan (Cal Hacks 13.0)

> **Read me first.** This file is the single source of truth for four people and four Claude Code agents working in parallel.
> - **Part B is the contract.** After checkpoint CP0 (Fri 20:30), `shared/` is **frozen**. No agent edits `shared/` or another section's folder. If a contract looks wrong, write the request in your own section's `CONTRACT_REQUESTS.md`, and the contract owner (S3) decides.
> - Each Part C section is meant to be read alone together with Part B. Agents: read **A, B, your own section of C, and D**. Skip the rest.
> - Times are Pacific. H0 = **Fri Oct 23, 19:00**. If you start later, shift the Friday blocks; Saturday and Sunday anchors don't move.

---

## Part A: Overview

**Pitch (one line).** Say your engineering goal in plain English, and Darwin's agent team evolves a real parametric Onshape CAD model against physics simulation. It explains why winners win, beats a classic optimizer on the same evaluation budget, and hands you the printed part.

**User.** Collegiate rocketry teams (for example CMU's). Today their fin design loop runs by hand: edit fin dimensions in OpenRocket or CAD, rerun the simulation, eyeball stability margin, drag and flutter, and repeat for weeks. Fins are the part they iterate on most, because fins set stability, drag, flutter safety and mass all at once.

**Problem.** These objectives conflict. Bigger fins add stability but also drag and mass. Thinner fins are lighter but flutter. Sweep moves the center of pressure aft but adds overhang that breaks on landing. Engineers can find a feasible design, but rarely a near-optimal one, and they rarely know why it is good.

**Differentiation.** Zoo (Zookeeper), Leo AI and Onshape's FeatureScript MCP server are *chat-to-CAD*: you describe a part and get a part. Darwin is **closed-loop optimization**:

`goal → propose → simulate → explain → regenerate real CAD → propose again`

It runs on the team's **own parametric Onshape model**, with a fair baseline comparison, an explicit physics assumptions page, and a physical artifact at the end.

### Defaults chosen for questions that are still open

| Topic | Default |
|---|---|
| Python | **Python 3.9 pinned team-wide** (conda env `darwin`, `python=3.9`), because the demo laptop is undecided and Hannah's Mac is 3.9.12. No `X \| Y` types, no `match`, no 3.10+ stdlib. |
| Anthropic SDK | **Pin the latest `anthropic` 0.x** (`anthropic<1`). SDK 1.x requires Python ≥ 3.10. If a request field isn't a kwarg in 0.x, pass it via `extra_body`. |
| Onshape accounts | **Separate dev accounts** for development (each teammate uses their own copy of the fin Part Studio and their own budget). The **prod** account (~2,400 calls left for the year) is used only for integration, pre-runs, rehearsals and judging. See the budget table in B.9. |
| Model spend | **$5 of Claude credit, no sponsor credits yet.** Haiku 5.5 for everything except a single Sonnet 5.5 call per run (the final report). The provider is swappable in one function (B.6). Sponsor credits or another paid provider plug in there when known. |
| Tier 3 second part | **Undecided by design.** Chosen at the Sat 12:00 Tier 3 kickoff from the candidate list in D.3. The architecture supports it through a scorer plugin interface. |
| Teammates | Sections are labeled **S1–S4**; assign people at kickoff. Hannah's 2018 Intel Mac works for any section, but has no `brew`: install Node with `conda install -c conda-forge nodejs=20`. |
| Reference rocket | 3 in (76.2 mm) body, 1,200 mm long, 300 mm ogive nose, 1,500 g without fins, CG 700 mm from the nose tip, design velocity 120 m/s, PLA fins. All values are editable in `DesignSpace.context`. |
| Optional tracks | **Anthropic "Claude for Public Benefit"** is gated on a real conversation with a rocketry-team member by Sat 12:00. **Bitdeer** is excluded unless credits appear (then it's ~30 minutes: one adapter in `call_model`). |
| Printers | Assumes the queue opens Friday night or early Saturday. **S1 asks the organizers at kickoff** for the form link and printer hours. |

---

## Part B: Architecture and frozen shared contracts

### B.1 System diagram

```
             ┌──────────────────────── dashboard/ (S4) ─────────────────────────┐
             │ Vite+React+three.js · state = fold(events) · live WS or JSONL replay│
             └───────────────▲───────────────────────────────┬─────────────────┘
                   WS /ws events                        REST /api/*
             ┌───────────────┴──────────── backend/ (S3) ─────▼─────────────────┐
             │ FastAPI · run loop · agents (goal parser, proposer, critic,      │
             │ strategist) · baselines (CMA-ES, random) · recorder/replay ·     │
             │ call_model() (the ONE LLM function) · budget aggregation          │
             └───────┬──────────────────────────────────────────┬──────────────┘
          python API │ (in-process)                  python API │ (in-process, worker thread)
             ┌───────▼────────── sim/ (S2) ─┐        ┌──────────▼──────── cad/ (S1) ─┐
             │ evaluate / evaluate_batch    │        │ build_geometry (configured    │
             │ AeroSandbox + Barrowman +    │        │ export or feature POST),      │
             │ flutter + mass · Pareto ·    │        │ ledger, cache, discovery,     │
             │ sensitivity · landscape      │        │ print package                 │
             │ NEVER calls Onshape          │        │ ONLY module that calls Onshape│
             └──────────────────────────────┘        └───────────────────────────────┘
                              all four import only from shared/ (frozen)
```

**Rules that keep sections independent:**
1. `sim` imports only `shared` (plus numpy and aerosandbox).
2. `cad` imports only `shared` (plus requests).
3. `backend` imports `shared` and the **public API modules** `sim.api` and `cad.api`. It never imports their internals.
4. `dashboard` talks only over HTTP/WS, using types from `shared/contracts.ts`.

### B.2 Technology choices (one line each)

| Choice | Why |
|---|---|
| Python 3.9 + pydantic v2 | Runs on every laptop, including Hannah's. pydantic gives validation plus JSON Schema for free. |
| FastAPI + uvicorn[standard] | Async REST and websockets in one process. Agents know it well. |
| AeroSandbox 4.2.8 `AeroBuildup` | Verified at 10–20 ms per eval. Its semi-empirical buildup captures planform, thickness and airfoil effects. |
| Barrowman equations (hand-coded) | The standard rocketry CP and stability method (it's what OpenRocket uses), so it's credible with our user. |
| `cma` (pycma) for CMA-ES | The reference CMA-ES implementation. Pure Python, 3.9-compatible. |
| `requests` for Onshape | Verified to work. Manual redirect handling is simple with it. |
| Vite + React 18.3.1 + TypeScript | Fast HMR. TS types mirror the contracts. |
| three.js r16x (plain, plus `STLLoader` and `OrbitControls`) | Verified. Plain three avoids r3f version churn. |
| zustand | A tiny store. The event-sourced reducer works the same for live and replay. |
| Recharts (lines and scatter) + d3-scale/d3-shape (custom SVG lineage, Pareto overlay) | Ships fast, with full control where it matters. |
| Tailwind CSS 3.4 | Quick, consistent polish. Design tokens live in `tailwind.config`. |
| Node 20 via conda-forge `nodejs` (or nvm) | Homebrew is broken on Hannah's Mac. |

### B.3 Repo layout and ownership

```
calhacks-2026/                       (repo root = ~/Desktop/calhacks)
├── PLAN.md                          (this file; edited only by agreement)
├── README.md                        S4 (filled Sat night; Devpost-ready, no secrets)
├── .gitignore  .env.example  requirements.txt  Makefile      written at freeze (S3), then frozen
├── shared/                          FROZEN after CP0 · contract owner: S3
│   ├── __init__.py
│   ├── contracts.py                 pydantic models + canonicalize/param_hash/geometry_key
│   ├── events.py                    event envelope + payload models
│   ├── contracts.ts                 TypeScript mirror (snake_case on the wire)
│   ├── fin_geometry.md              exact geometric definition of fin_v1 (B.5)
│   ├── check.py                     validates every fixture against the models (`make contracts`)
│   ├── fixtures/                    design_space_fin.json, goal_example.json, score_example.json,
│   │                                design_result_example.json, budget_example.json, sample_run.jsonl
│   └── mocks/                       fake_sim.py, fake_cad.py, fake_llm.py, mock_server.py,
│                                    make_sample_run.py   (behavior in B.8)
├── cad/        S1   api.py, onshape_client.py, ledger.py, configured.py, feature_post.py, stl.py,
│                    cache.py, discovery.py, print_export.py, SPIKE.md, tests/, requirements.txt
├── sim/        S2   api.py, plugins/fin_v1.py, barrowman.py, aero.py, flutter.py, mass.py,
│                    aggregate.py, pareto.py, landscape.py, hifi.py, tests/, requirements.txt,
│                    PHYSICS.md
├── backend/    S3   server.py, run_loop.py, agents/{goal_parser,proposer,critic,strategist}.py,
│                    prompts/, llm.py (call_model), baselines.py, recorder.py, replay.py,
│                    wiring.py, bench.py, report.py, tests/, requirements.txt
├── dashboard/  S4   Vite app; src/store, src/components, src/three, src/geometry/finPreview.ts
├── demo/
│   ├── recordings/   S3  curated run JSONL for replay (no secrets, no doc IDs)
│   ├── geometry/     S1  cached STLs referenced by the recordings
│   └── video/        S4  fallback video (gitignored if > 50 MB; keep a copy on two laptops)
├── docs/       pitch.md (S4), physics.md → symlink/copy of sim/PHYSICS.md (S2), devpost.md (S4)
└── .darwin/    runtime only, gitignored: geometry/, ledger/, runs/, llm_cache/, landscape/
```

**Git rules:**
- Everyone commits to `main`, but **only inside your own folder** (`git add cad/`, never `git add -A` at the root).
- Run `git pull --rebase` before every push.
- Tags: `contracts-v1` (CP0), `tier1`, `tier2`, `tier3`, `freeze`.

**Run modes (env vars, read only by `backend/wiring.py`):**
- `DARWIN_SIM=real|fake`
- `DARWIN_CAD=real|fake|off`
- `DARWIN_LLM_PROVIDER=anthropic|mock|replay|<future>`
- `DARWIN_MODE=live|replay`

**Ports:**
- The backend (and the mock server, which uses the same port) runs on `:8000`.
- Vite runs on `:5173`, proxying `/api` and `/ws` to `VITE_BACKEND_URL` (default `http://localhost:8000`).

### B.4 Secrets and environment

Keys live **outside the repo** in `~/.darwin_secrets.sh` (run `source` on it in your shell). `.env.example` lists names only:

```
ONSHAPE_ACCESS_KEY= ONSHAPE_SECRET_KEY= ONSHAPE_ACCOUNT_LABEL=prod|dev-<name>
ONSHAPE_CALLS_REMAINING=        # read off Onshape's usage page; with ..._AT=<ISO time>
ONSHAPE_CALLS_REMAINING_AT=
DARWIN_ONSHAPE_RESERVE=400      # hard floor; refuse calls below it
DARWIN_ALLOW_RESERVE=0          # set to 1 ONLY at the judging table
DARWIN_FIN_DOC_URL=             # Onshape Part Studio URL (per account)
ANTHROPIC_API_KEY=
DARWIN_LLM_PROVIDER=anthropic   DARWIN_MODEL_FAST=claude-haiku-5-5   DARWIN_MODEL_DEEP=claude-sonnet-5-5
DARWIN_SPEND_CAP_TOTAL_USD=4.50 DARWIN_SPEND_CAP_RUN_USD=0.30
```

**`.gitignore` must include:** `.env`, `.env.*` (except `.env.example`), `*.key`, `.darwin/`, `node_modules/`, `dist/`, `__pycache__/`, `*.stl` (outside `demo/geometry/`), `demo/video/*.mp4`, `cad/SPIKE_raw/`. That last folder may hold raw API dumps with account data.

`make secrets-check` greps the tree for `sk-ant-`, `ONSHAPE_SECRET`, and 32+ character base64 runs. Run it before every push and before Devpost.

The dashboard never displays keys or document IDs: it shows the account **label** only. Before screen recording, close every terminal that ran `source` on the secrets file.

### B.5 Fin geometry definition (`shared/fin_geometry.md`, frozen)

This definition is shared by the Onshape Part Studio (S1), the simulation (S2) and the dashboard's preview mesh (S4). All three must agree.

**Frame** (Onshape, sketch on the Front plane):
- **x** is chordwise. x = 0 at the root leading edge, positive aft.
- **z** is spanwise, positive outward. z = 0 at the root, which sits on the body tube.
- **y** is thickness. The plate is extruded **symmetric**, from y = −t/2 to +t/2.
- Onshape is Z-up and three.js is Y-up, so the dashboard rotates −π/2 about x.

**Planform** is a trapezoid, built from these values:
- `c_r = root_chord`
- `c_t = root_chord × taper_ratio`
- `s = semi_span`
- `Λ = sweep_deg`, the leading-edge sweep

**Planform corners:**
- Root leading edge (0, 0)
- Root trailing edge (c_r, 0)
- Tip leading edge (s·tanΛ, s)
- Tip trailing edge (s·tanΛ + c_t, s)

**Edge profile** (`edge_profile`), applied to the LE, TE and tip edges:
- `square`: no treatment.
- `rounded`: full-round fillet with radius t/2 on the LE and tip, square TE.
- `beveled`: symmetric chamfer on the LE and TE, with bevel length `min(3t, 0.25·c_t)`, giving a sharp edge.

**Derived quantities** (used by sim, mocks and the dashboard):
- planform area A = s(c_r + c_t)/2
- volume V ≈ A·t − edge-removal volume (exact formula in `fin_geometry.md`)
- aft overhang = max(0, s·tanΛ + c_t − c_r)

**fin_v1 parameters:**

| name | kind | unit | min | max | step | default | cad_driven | Onshape ref |
|---|---|---|---|---|---|---|---|---|
| root_chord | continuous | mm | 50 | 130 | 0.5 | 90 | ✓ | `root_chord` |
| taper_ratio | continuous | – | 0.2 | 1.0 | 0.01 | 0.5 | ✓ | `taper_ratio` |
| semi_span | continuous | mm | 30 | 90 | 0.5 | 60 | ✓ | `semi_span` |
| sweep_deg | continuous | deg | 0 | 60 | 0.5 | 30 | ✓ | `sweep_deg` |
| thickness | continuous | mm | 2.0 | 5.0 | 0.1 | 3.0 | ✓ | `thickness` |
| edge_profile | choice | – | – | – | – | rounded | ✓ | `edge_profile` (List input) |
| fin_count | integer | – | 3 | 4 | 1 | 4 | ✗ (sim-only) | – |

S1 must confirm that **all corners** of this box regenerate in Onshape. If one doesn't, S1 narrows the bounds in the Part Studio **and** reports the new bounds before CP0. The bounds are part of the frozen contract.

### B.6 Schemas (Python is the source of truth; TS mirrors it)

#### `shared/contracts.py`

```python
# shared/contracts.py — FROZEN at CP0. Python 3.9-compatible.
from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0.0"
ParamValue = Union[float, int, str]

class ParamSpec(BaseModel):
    name: str                                  # snake_case, unique within the space
    kind: Literal["continuous", "integer", "choice"]
    unit: str = ""                             # "mm" | "deg" | "" (dimensionless)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None               # canonical rounding grid
    choices: Optional[List[str]] = None
    default: ParamValue
    cad_driven: bool = True                    # False = sim-only, never sent to Onshape
    cad_ref: Optional[str] = None              # configuration input id / variable name
    description: str = ""

class CadSource(BaseModel):
    kind: Literal["onshape", "mock", "none"]
    doc_url: Optional[str] = None              # runtime only; NEVER in committed fixtures
    mode: Literal["configuration", "custom_feature", "feature_post", "mock"] = "configuration"
    model_revision: str = "r1"                 # bump when the Part Studio changes → new cache keys

class DesignSpace(BaseModel):
    id: str                                    # "fin_v1"
    name: str
    scorer: str                                # sim plugin id
    parameters: List[ParamSpec]
    context: Dict[str, Union[float, str]] = Field(default_factory=dict)  # fixed inputs (reference rocket)
    source: CadSource
    discovered: bool = False
    notes: List[str] = Field(default_factory=list)

class DesignParams(BaseModel):
    values: Dict[str, ParamValue]

class MetricInfo(BaseModel):                   # published by sim.metric_catalog()
    name: str; unit: str; description: str
    better: Literal["higher", "lower", "target", "info"]
    typical_min: float; typical_max: float     # normalization range
    default_tolerance: Optional[float] = None  # for "target" objectives

class Objective(BaseModel):
    metric: str                                # must exist in metric_catalog(space.scorer)
    direction: Literal["minimize", "maximize", "target"]
    target: Optional[float] = None
    tolerance: Optional[float] = None
    weight: float = 1.0

class Constraint(BaseModel):
    ref: str                                   # metric name, or "param:<name>"
    op: Literal["<=", ">=", "=="]
    value: float
    hard: bool = True
    label: str = ""                            # "total fin mass ≤ 40 g"

class Goal(BaseModel):
    source_text: str
    objectives: List[Objective]
    constraints: List[Constraint] = Field(default_factory=list)
    fixed_params: Dict[str, ParamValue] = Field(default_factory=dict)
    context_overrides: Dict[str, Union[float, str]] = Field(default_factory=dict)
    assumptions: List[str] = Field(default_factory=list)   # shown to the user to confirm
    parsed_by: Literal["llm", "preset", "manual", "fallback"] = "llm"

class Violation(BaseModel):
    ref: str; op: str; limit: float; actual: float
    amount: float                              # normalized: |actual-limit| / max(|limit|, 1e-9)
    hard: bool

class Score(BaseModel):
    metrics: Dict[str, float]
    objective_scores: Dict[str, float]         # each in [0,1], 1 = best
    violations: List[Violation] = Field(default_factory=list)
    feasible: bool                             # no hard violations
    aggregate: float                           # see the aggregation rule below
    warnings: List[str] = Field(default_factory=list)  # "sweep_deg at upper bound", "implausible CD"
    fidelity: Literal["fast", "high"] = "fast"
    eval_ms: float = 0.0

class GeometryRef(BaseModel):
    geometry_key: str
    status: Literal["pending", "ready", "failed", "skipped"]
    source: Literal["onshape_config", "onshape_feature", "cache", "mock", "none"]
    stl_url: Optional[str] = None              # "/api/geometry/{geometry_key}.stl"
    bbox_mm: Optional[List[float]] = None      # [xmin,ymin,zmin,xmax,ymax,zmax], Onshape frame
    volume_mm3: Optional[float] = None
    triangles: Optional[int] = None
    onshape_calls: int = 0                     # calls spent on THIS build (0 if cached)
    regen_status: Optional[str] = None         # "OK" | "WARNING" | "ERROR" | "SANITY_FAIL"
    error: Optional[str] = None
    elapsed_ms: float = 0.0

class Proposal(BaseModel):                     # what a proposer returns, before evaluation
    params: Dict[str, ParamValue]
    parent_ids: List[str] = Field(default_factory=list)
    operator: Literal["seed", "novel", "mutate", "crossover", "refine", "repair"]
    rationale: str = ""                        # ≤ 30 words

class DesignResult(BaseModel):
    design_id: str                             # "{run_id}-g{gen:02d}-{a|f|s|c|r}{idx:02d}"
    run_id: str
    generation: int
    origin: Literal["seed", "agent", "fallback", "baseline_cmaes", "baseline_random"]
    params: Dict[str, ParamValue]              # canonicalized
    param_hash: str
    parent_ids: List[str] = Field(default_factory=list)
    operator: str
    rationale: str = ""
    score: Score
    pareto_rank: Optional[int] = None          # 0 = on the front (agent designs only)
    geometry: Optional[GeometryRef] = None
    timings_ms: Dict[str, float] = Field(default_factory=dict)  # propose, eval, geometry

class Directive(BaseModel):                    # strategist output
    mode: Literal["explore", "exploit", "refine"]
    n_explore: int                             # how many of the next N proposals are novel
    focus_params: List[str] = Field(default_factory=list)
    step_scale: float = 0.15                   # mutation radius as a fraction of each range
    reason: str = ""
    source: Literal["llm", "rules"] = "rules"

class Generation(BaseModel):
    run_id: str
    index: int
    design_ids: List[str]
    champion_id: str
    best_aggregate: float
    mean_aggregate: float
    feasible_count: int
    evals_used: int; evals_budget: int
    directive: Optional[Directive] = None
    critic_summary: Optional[str] = None       # one sentence
    elapsed_ms: float = 0.0

class AgentMessage(BaseModel):
    message_id: str
    run_id: str
    generation: Optional[int] = None
    agent: Literal["goal_parser", "proposer", "critic", "strategist", "reporter", "system"]
    kind: Literal["proposal", "insight", "warning", "directive", "report", "status"]
    model: str                                 # "claude-haiku-5-5" | "rules" | "mock" | "replay"
    summary: str                               # one line for the feed
    body: str = ""                             # short markdown; numbers come from data, not the LLM
    refs: List[str] = Field(default_factory=list)   # design_ids mentioned
    tokens_in: int = 0; tokens_out: int = 0
    cost_usd: float = 0.0; latency_ms: float = 0.0

class OnshapeBudget(BaseModel):
    account_label: str                         # "prod" | "dev-<name>" | "mock"
    calls_session: int                         # since this process started
    calls_ledger_total: int                    # since ONSHAPE_CALLS_REMAINING_AT
    remaining_estimate: int
    reserve: int
    reserve_unlocked: bool
    hard_stop: bool                            # remaining_estimate <= reserve and not unlocked
    last_synced_at: Optional[str] = None

class ModelBudget(BaseModel):
    provider: str
    calls_run: int; calls_cap_run: int
    spend_run_usd: float; spend_cap_run_usd: float
    spend_total_usd: float; spend_cap_total_usd: float   # local ledger; Console is ground truth

class BudgetStatus(BaseModel):
    onshape: OnshapeBudget
    model: ModelBudget
    evals_used: int; evals_budget: int

class RunConfig(BaseModel):
    population: int = 8
    generations: int = 8
    elites: int = 3
    eval_budget: Optional[int] = None          # default population*generations; baselines get the same
    seed: int = 7
    baselines: List[Literal["cmaes", "random"]] = Field(default_factory=lambda: ["cmaes", "random"])
    early_stop_patience: int = 3               # generations without ≥ min_improvement
    min_improvement: float = 0.005
    geometry_max_builds: int = 6               # Onshape builds per run (champions only)
    geometry_min_improvement: float = 0.01
    llm_max_calls: int = 40
    llm_max_spend_usd: float = 0.30
    profile: Literal["demo", "full", "bench"] = "demo"

class CurvePoint(BaseModel):
    evals: int; best_aggregate: float

class RunSummary(BaseModel):
    run_id: str
    status: Literal["running", "complete", "stopped", "failed"]
    goal: Goal
    design_space_id: str
    config: RunConfig
    started_at: str; finished_at: Optional[str] = None
    champion: Optional[DesignResult] = None
    seed_design: Optional[DesignResult] = None             # "before" for the winner card
    baseline_best: Dict[str, DesignResult] = Field(default_factory=dict)  # "cmaes", "random"
    curves: Dict[str, List[CurvePoint]] = Field(default_factory=dict)     # "agent", "cmaes", "random"
    pareto_ids: List[str] = Field(default_factory=list)
    hifi_check: Optional[Score] = None                     # champion at fidelity="high"
    budget: Optional[BudgetStatus] = None
    degradations: List[str] = Field(default_factory=list)  # ["llm_fallback@g4", "onshape_cache_only"]
    report_url: Optional[str] = None
    recording: Optional[str] = None                         # recording file name

# ---- shared helpers (frozen; tiny, deterministic) ----
def canonicalize(space: DesignSpace, values: Dict[str, ParamValue]) -> Dict[str, ParamValue]:
    """Fill defaults, clamp to [min,max], round to step, cast integers, validate choices.
    Raises ValueError on an unknown param or an invalid choice."""

def param_hash(space: DesignSpace, values: Dict[str, ParamValue]) -> str:
    """sha1(json.dumps(canonicalize(...), sort_keys=True) + space.id)[:12]"""

def geometry_key(space: DesignSpace, values: Dict[str, ParamValue]) -> str:
    """sha1 over cad_driven params only + space.id + source.model_revision, [:12]"""
```

**Aggregation rule** (implemented by sim, frozen here so the critic and dashboard can explain it):
- **Per objective** `s ∈ [0,1]`:
  - maximize: `clip((x−lo)/(hi−lo))`
  - minimize: `1 − clip((x−lo)/(hi−lo))`
  - target: `max(0, 1 − |x−target|/tol)`

  Here `lo, hi` are `typical_min/max` from the metric catalog, and `tol` is `tolerance` or `default_tolerance`.
- **Feasible design:** `aggregate = Σ wᵢsᵢ / Σ wᵢ − 0.1·Σ(soft violation amounts)`. This lands in about `[0, 1]`.
- **Infeasible design** (any hard violation): `aggregate = −Σ(hard violation amounts) − 0.1·Σ(soft violation amounts)`. This is always below every feasible design.

#### `shared/events.py`

```python
EventType = Literal["run_started", "design_evaluated", "generation_complete", "champion_updated",
                    "geometry_ready", "agent_message", "baseline_progress", "landscape_ready",
                    "budget_update", "run_complete", "error"]

class Event(BaseModel):
    v: int = 1
    type: EventType
    run_id: str
    seq: int          # strictly increasing per run; the dashboard dedupes/orders by seq
    ts: float         # unix seconds; replay preserves the gaps (× speed)
    payload: dict     # validated against the payload model for `type` (below)
```

#### `shared/contracts.ts` (excerpt; the full mirror is written at freeze)

```ts
// FROZEN mirror of contracts.py. Field names are snake_case exactly as on the wire.
export type ParamValue = number | string;
export interface ParamSpec { name: string; kind: 'continuous' | 'integer' | 'choice'; unit: string;
  min?: number | null; max?: number | null; step?: number | null; choices?: string[] | null;
  default: ParamValue; cad_driven: boolean; cad_ref?: string | null; description: string; }
export interface DesignSpace { id: string; name: string; scorer: string; parameters: ParamSpec[];
  context: Record<string, number | string>; source: { kind: 'onshape' | 'mock' | 'none';
  doc_url?: string | null; mode: string; model_revision: string }; discovered: boolean; notes: string[]; }
export interface Objective { metric: string; direction: 'minimize' | 'maximize' | 'target';
  target?: number | null; tolerance?: number | null; weight: number; }
export interface Constraint { ref: string; op: '<=' | '>=' | '=='; value: number; hard: boolean; label: string; }
export interface Goal { source_text: string; objectives: Objective[]; constraints: Constraint[];
  fixed_params: Record<string, ParamValue>; context_overrides: Record<string, number | string>;
  assumptions: string[]; parsed_by: 'llm' | 'preset' | 'manual' | 'fallback'; }
export interface Score { metrics: Record<string, number>; objective_scores: Record<string, number>;
  violations: Violation[]; feasible: boolean; aggregate: number; warnings: string[];
  fidelity: 'fast' | 'high'; eval_ms: number; }
export interface GeometryRef { geometry_key: string; status: 'pending' | 'ready' | 'failed' | 'skipped';
  source: 'onshape_config' | 'onshape_feature' | 'cache' | 'mock' | 'none'; stl_url?: string | null;
  bbox_mm?: number[] | null; volume_mm3?: number | null; triangles?: number | null;
  onshape_calls: number; regen_status?: string | null; error?: string | null; elapsed_ms: number; }
export interface DesignResult { design_id: string; run_id: string; generation: number;
  origin: 'seed' | 'agent' | 'fallback' | 'baseline_cmaes' | 'baseline_random';
  params: Record<string, ParamValue>; param_hash: string; parent_ids: string[]; operator: string;
  rationale: string; score: Score; pareto_rank?: number | null; geometry?: GeometryRef | null;
  timings_ms: Record<string, number>; }
// … Violation, Directive, Generation, AgentMessage, OnshapeBudget, ModelBudget, BudgetStatus,
//   RunConfig, CurvePoint, RunSummary, MetricInfo: field-for-field copies of the Python models.
export type EventType = 'run_started' | 'design_evaluated' | 'generation_complete' | 'champion_updated'
  | 'geometry_ready' | 'agent_message' | 'baseline_progress' | 'landscape_ready' | 'budget_update'
  | 'run_complete' | 'error';
export interface DarwinEvent<P = unknown> { v: 1; type: EventType; run_id: string; seq: number; ts: number; payload: P; }
```

#### JSON examples (these become `shared/fixtures/*.json`)

**DesignSpace** (`design_space_fin.json`; the parameters are the B.5 table):
```json
{ "id": "fin_v1", "name": "Trapezoidal rocket fin", "scorer": "fin_v1",
  "parameters": [
    {"name": "root_chord", "kind": "continuous", "unit": "mm", "min": 50, "max": 130, "step": 0.5,
     "default": 90, "cad_driven": true, "cad_ref": "root_chord", "description": "Chord at the body tube"},
    {"name": "taper_ratio", "kind": "continuous", "unit": "", "min": 0.2, "max": 1.0, "step": 0.01,
     "default": 0.5, "cad_driven": true, "cad_ref": "taper_ratio", "description": "tip/root chord"},
    {"name": "edge_profile", "kind": "choice", "choices": ["square", "rounded", "beveled"],
     "default": "rounded", "cad_driven": true, "cad_ref": "edge_profile", "description": "LE/TE treatment"},
    {"name": "fin_count", "kind": "integer", "unit": "", "min": 3, "max": 4, "step": 1, "default": 4,
     "cad_driven": false, "description": "Fins on the rocket (sim-only)"}
  ],
  "context": {"body_diameter_mm": 76.2, "body_length_mm": 1200, "nose_length_mm": 300,
              "nose_shape": "ogive", "mass_without_fins_g": 1500, "cg_without_fins_mm": 700,
              "design_velocity_mps": 120, "altitude_m": 0, "alpha_deg": 2.0,
              "material": "PLA", "density_g_cm3": 1.24, "shear_modulus_gpa": 1.3},
  "source": {"kind": "onshape", "doc_url": null, "mode": "configuration", "model_revision": "r1"},
  "discovered": false, "notes": [] }
```

**fin_v1 metric catalog** (frozen names; S2 fills in descriptions and normalization ranges):

| metric | unit | better | role |
|---|---|---|---|
| `stability_margin_cal` | cal | target (default 2.0 ± 0.75) | (CP − CG)/D, with fin mass included in CG |
| `cp_mm`, `cg_mm` | mm from the nose tip | info | Barrowman CP; CG including fins |
| `drag_n` | N | lower | Fin-set drag at design velocity (AeroBuildup, all fins) |
| `cd_fins` | – | lower | Fin-set CD referenced to body cross-section area |
| `fin_mass_g` | g | lower | One fin, V × ρ (100 % infill, matching the print) |
| `fin_mass_total_g` | g | lower | `fin_mass_g × fin_count` |
| `flutter_velocity_mps` | m/s | higher | NACA TN 4197–style flutter boundary |
| `flutter_margin` | – | higher | `flutter_velocity / design_velocity`. The goal parser adds `≥ 1.5` by default. |
| `cn_alpha_fins` | 1/rad | info | Barrowman fin normal-force slope with body interference |
| `aft_overhang_mm` | mm | lower | Tip TE behind the root TE (fragile on landing) |
| `planform_area_cm2` | cm² | info | One fin |

**Goal** (`goal_example.json`), for the input *"Maximize this rocket fin's stability, keep drag low, keep it under 40 g, must fit a 3-inch body tube."*:
```json
{ "source_text": "Maximize this rocket fin's stability, keep drag low, keep it under 40 g, must fit a 3-inch body tube.",
  "objectives": [
    {"metric": "stability_margin_cal", "direction": "target", "target": 2.5, "tolerance": 1.0, "weight": 0.5},
    {"metric": "drag_n", "direction": "minimize", "weight": 0.35},
    {"metric": "fin_mass_total_g", "direction": "minimize", "weight": 0.15}],
  "constraints": [
    {"ref": "fin_mass_total_g", "op": "<=", "value": 40, "hard": true, "label": "total fin mass ≤ 40 g"},
    {"ref": "flutter_margin", "op": ">=", "value": 1.5, "hard": true, "label": "flutter-safe (default)"},
    {"ref": "stability_margin_cal", "op": ">=", "value": 1.0, "hard": true, "label": "stable (default)"},
    {"ref": "aft_overhang_mm", "op": "<=", "value": 0, "hard": false, "label": "no aft overhang"}],
  "fixed_params": {},
  "context_overrides": {"body_diameter_mm": 76.2},
  "assumptions": ["'Maximize stability' → target 2.5 cal: beyond ~3 cal a rocket weathercocks",
                  "'under 40 g' read as the TOTAL for all fins", "3-inch tube = 76.2 mm body diameter"],
  "parsed_by": "llm" }
```

**Score** (`score_example.json`):
```json
{ "metrics": {"stability_margin_cal": 2.31, "cp_mm": 1031.0, "cg_mm": 855.0, "drag_n": 1.31,
              "cd_fins": 0.058, "fin_mass_g": 12.3, "fin_mass_total_g": 36.9,
              "flutter_velocity_mps": 205.0, "flutter_margin": 1.71, "cn_alpha_fins": 8.9,
              "aft_overhang_mm": 0.0, "planform_area_cm2": 41.4},
  "objective_scores": {"stability_margin_cal": 0.81, "drag_n": 0.74, "fin_mass_total_g": 0.38},
  "violations": [], "feasible": true, "aggregate": 0.722,
  "warnings": [], "fidelity": "fast", "eval_ms": 14.2 }
```

**DesignResult** (`design_result_example.json`):
```json
{ "design_id": "run_0712_3fa9-g03-a05", "run_id": "run_0712_3fa9", "generation": 3, "origin": "agent",
  "params": {"root_chord": 92.0, "taper_ratio": 0.45, "semi_span": 62.0, "sweep_deg": 38.0,
             "thickness": 2.4, "edge_profile": "beveled", "fin_count": 3},
  "param_hash": "a1b2c3d4e5f6",
  "parent_ids": ["run_0712_3fa9-g02-a01", "run_0712_3fa9-g02-a04"], "operator": "crossover",
  "rationale": "Take g02-a01's sweep (CP aft) with g02-a04's thin beveled section to cut mass; 3 fins keep total < 40 g.",
  "score": {"...": "Score as above"}, "pareto_rank": 0,
  "geometry": {"geometry_key": "9f8e7d6c5b4a", "status": "ready", "source": "onshape_config",
               "stl_url": "/api/geometry/9f8e7d6c5b4a.stl", "bbox_mm": [0, -1.2, 0, 92.0, 1.2, 62.0],
               "volume_mm3": 9790.0, "triangles": 412, "onshape_calls": 1, "regen_status": "OK",
               "error": null, "elapsed_ms": 1710},
  "timings_ms": {"propose": 2900, "eval": 14.2, "geometry": 1710} }
```

**BudgetStatus** (`budget_example.json`):
```json
{ "onshape": {"account_label": "prod", "calls_session": 7, "calls_ledger_total": 212,
              "remaining_estimate": 2188, "reserve": 400, "reserve_unlocked": false,
              "hard_stop": false, "last_synced_at": "2026-10-24T09:05:00-07:00"},
  "model": {"provider": "anthropic", "calls_run": 14, "calls_cap_run": 40, "spend_run_usd": 0.021,
            "spend_cap_run_usd": 0.30, "spend_total_usd": 0.84, "spend_cap_total_usd": 4.50},
  "evals_used": 40, "evals_budget": 64 }
```

### B.7 Section APIs (Python signatures; the only cross-section imports)

**`cad/api.py` (S1)**: synchronous. Every Onshape request goes through the ledger.
```python
def build_geometry(space: DesignSpace, params: Dict[str, ParamValue], *, allow_network: bool = True) -> GeometryRef
    # cache hit (by geometry_key) → status "ready", source "cache", onshape_calls 0, no network.
    # Raises nothing: failures come back as status "failed" with error and regen_status set.
    # Budget exhausted → status "skipped", error "onshape_budget_reserve".
def geometry_file(geometry_key: str) -> Optional[Path]        # local STL path, for the backend to serve
def budget_status() -> OnshapeBudget
def discover_design_space(doc_url: str, *, probe: bool = False) -> DesignSpace   # Tier 3 (≤ 6 calls with probe)
def export_print_package(space: DesignSpace, params: Dict[str, ParamValue], out_dir: Path) -> Path  # zip
def commit_to_document(space: DesignSpace, params: Dict[str, ParamValue]) -> GeometryRef
    # writes the champion INTO the Onshape doc so it is visible in Onshape's UI (demo step 3).
    # Costs 1 call (configuration default update) or N calls (feature POST). Gated by ledger.
```

**`sim/api.py` (S2)**: pure. No network, no Onshape, deterministic.
```python
def metric_catalog(scorer: str) -> List[MetricInfo]
def evaluate(space: DesignSpace, params: Dict[str, ParamValue], goal: Goal, fidelity: str = "fast") -> Score
def evaluate_batch(space, params_list: List[Dict[str, ParamValue]], goal, workers: int = 0) -> List[Score]
    # same order as input; workers=0 → serial (fast enough for ≤ 64); >0 → process pool
def pareto_front(scores: List[Score], goal: Goal) -> List[int]          # indices with rank 0 (over objectives)
def pareto_ranks(scores: List[Score], goal: Goal) -> List[int]
def sensitivity(space, params, goal) -> Dict[str, Dict[str, float]]
    # {param: {metric: d(metric)/d(param) × param_range}} by finite differences (2 evals per param)
def landscape(space, goal, n: int = 2000, seed: int = 0) -> List[Tuple[Dict[str, ParamValue], Score]]
    # dense random sample = "ground truth" cloud; cached on disk by (space.id, goal hash, n, seed)
def validate_high_fidelity(space, params, goal) -> Score               # fidelity="high", slower method
def register_scorer(scorer_id: str, plugin: "ScorerPlugin") -> None    # Tier 3 second part
```

**`backend` (S3)**: internal APIs. Other sections never call these, but they are frozen so mocks match.
```python
def call_model(role: str, system: str, user: str, schema: dict, *, model: Optional[str] = None,
               max_tokens: int = 2000, effort: str = "low", timeout_s: float = 25.0) -> ModelResult
    # THE ONE swappable LLM function. ModelResult = {data, raw_text, model, provider, tokens_in,
    # tokens_out, cost_usd, latency_ms, cached}. Raises BudgetExceeded / LLMUnavailable.
def parse_goal(text: str, space: DesignSpace) -> Goal
def propose(history: RunHistory, goal: Goal, space: DesignSpace, n: int, directive: Directive) -> List[Proposal]
def critique(history: RunHistory, goal: Goal, space: DesignSpace, sens: dict) -> AgentMessage
def strategize(history: RunHistory, goal: Goal) -> Directive
```

### B.8 Backend REST and websocket API

**REST** (JSON, prefix `/api`):

| Method & path | Body → Response |
|---|---|
| `GET /api/health` | → `{"ok": true, "contract": "1.0.0", "modes": {"sim": "real", "cad": "real", "llm": "anthropic", "mode": "live"}}` |
| `GET /api/design-spaces` | → `[DesignSpace]` (doc_url stripped) |
| `GET /api/metrics?scorer=fin_v1` | → `[MetricInfo]` |
| `GET /api/presets` | → `[{"label": "Stable & light", "text": "...", "goal": Goal}]` (3 demo chips) |
| `POST /api/goal/parse` | `{"text": "...", "design_space_id": "fin_v1"}` → `Goal` (1 LLM call; preset fallback) |
| `POST /api/runs` | `{"goal": Goal, "design_space_id": "fin_v1", "config": RunConfig}` → `{"run_id": "run_0712_3fa9"}` |
| `GET /api/runs` | → `[RunSummary]` (most recent first, including recordings) |
| `GET /api/runs/{id}` | → `RunSummary` |
| `POST /api/runs/{id}/stop` | → `RunSummary` |
| `GET /api/runs/{id}/events` | → `application/x-ndjson` (the recording) |
| `POST /api/replay` | `{"recording": "demo_pitch_goal.jsonl", "speed": 1.0}` → `{"run_id": "replay_…"}` |
| `GET /api/geometry/{key}.stl` | → `model/stl` file (from the cad cache or `demo/geometry/`) |
| `POST /api/runs/{id}/commit` | `{"design_id": "..."}` → `GeometryRef` (writes the champion into the Onshape doc) |
| `POST /api/runs/{id}/export` | `{"design_id": "..."}` → zip (print package) |
| `GET /api/runs/{id}/report` | → `text/html` engineering report (Tier 3) |
| `GET /api/budget` | → `BudgetStatus` |
| `POST /api/discover` | `{"doc_url": "...", "probe": false}` → `DesignSpace` (Tier 3) |

**Websocket**: `WS /ws?run_id=<id>`. The server sends the full backlog for that run on connect, then live events. `run_id=*` subscribes to every run.

Every event uses the `Event` envelope `{v, type, run_id, seq, ts, payload}`. Payloads:

| type | payload example |
|---|---|
| `run_started` | `{"summary": RunSummary(status "running", no champion), "design_space": DesignSpace, "metric_catalog": [MetricInfo]}` |
| `design_evaluated` | `{"design": DesignResult}`. Agent, seed and fallback designs only. Baseline designs are summarized in `baseline_progress`. |
| `generation_complete` | `{"generation": Generation, "pareto_ids": ["…-g03-a05", "…-g02-a01"]}` |
| `champion_updated` | `{"design_id": "…-g03-a05", "previous_id": "…-g02-a01", "aggregate": 0.722, "delta": 0.041, "reason": "drag −11 % at equal stability"}` |
| `geometry_ready` | `{"design_id": "…-g03-a05", "geometry": GeometryRef}`. Also sent with `status` "failed" or "skipped". |
| `agent_message` | `{"message": AgentMessage}` |
| `baseline_progress` | `{"method": "cmaes", "evals_used": 24, "best_aggregate": 0.65, "best": DesignResult, "curve_point": {"evals": 24, "best_aggregate": 0.65}}` |
| `landscape_ready` | `{"metrics": ["drag_n", "stability_margin_cal"], "points": [[1.42, 2.1, 0.61, true], …], "n": 2000}`. Points are `[x, y, aggregate, feasible]`, downsampled to ≤ 2,000. |
| `budget_update` | `{"budget": BudgetStatus}` |
| `run_complete` | `{"summary": RunSummary}` (champion, curves, hifi_check, degradations) |
| `error` | `{"component": "llm", "code": "timeout", "message": "proposer timed out at g4", "recoverable": true, "degraded_to": "fallback_proposer"}` |

**Ordering guarantees:**
- `run_started` comes first and `run_complete` comes last.
- Within a generation, the order is: N × `design_evaluated` → `champion_updated`? → `generation_complete` → `budget_update`.
- `agent_message`, `geometry_ready` and `baseline_progress` may interleave anywhere.

### B.9 Budgets (hard numbers)

**Onshape prod account.** About 2,400 calls remain for the year, and we commit at most 1,300 to this event:

| Bucket | Calls | Notes |
|---|---|---|
| Spike | 0 prod | Runs on the S1 **dev** account (≤ 15 calls there). |
| Prod setup + smoke test | 40 | Copy the Part Studio, check the configuration, 3 exports, usage-page check. |
| CP1 integration (Fri 23:15) | 60 | |
| CP2 integration (Sat 09:00) | 80 | |
| Pre-runs for prints #1, #2 + cache warm | 80 | |
| CP3 + benchmark geometry | 60 | Benchmark scoring is sim-only, so geometry comes only from champions. |
| Tier 3 second part (discovery + probes + builds) | 120 | |
| Rehearsals (≈ 3 live) + video | 160 | Every other rehearsal runs in replay or cache-only mode. |
| Buffer | 300 | |
| **Judging reserve (hard floor)** | **400** | Unlocked only at the table with `DARWIN_ALLOW_RESERVE=1`. |
| **Total event ceiling** | **1,300** | The rest (about 1,100) stays untouched for the year. |

**Per-run cap:**
- `geometry_max_builds = 6`. Champions only, and only when the champion improves by ≥ 0.01, plus the final champion.
- Cached designs cost 0 calls.
- With configured exports, a demo run costs about 6–12 calls. About 15 judge visits ≈ 180 calls, which fits inside the reserve.

**Ledger semantics:**
- Every HTTP request to `cad.onshape.com` counts, **including redirect follow-ups**, until the usage-page check (S1 spike step 6) proves redirects are free.
- The ledger lives in `.darwin/ledger/<account_label>.jsonl`, one line per request: timestamp, method, path template (no IDs), status, and the purpose (`spike`, `build`, `discover`, `commit`).
- `remaining_estimate = ONSHAPE_CALLS_REMAINING − calls since ONSHAPE_CALLS_REMAINING_AT`.
- Re-sync with the Onshape usage page at every checkpoint, and update the env var.

**Model spend.** $5 of Claude credit. Set the Anthropic Console spend limit to $5 at kickoff.

| Bucket | USD |
|---|---|
| Development (mostly `mock` provider; real calls only for prompt tuning) | 1.00 |
| Benchmark (`bench.py`, ≈ 18 runs) | 1.00 |
| Pre-runs + rehearsals (LLM cache on) | 0.75 |
| Tier 3 (discovery naming, report tuning) | 0.40 |
| **Judging reserve** | **1.25** (≈ 15 runs at ~$0.08) |
| Slack | 0.60 |

The per-run cost estimate:
- Haiku 5.5 (**$0.10 / $0.50 per MTok**, prompts ≤ 100K tokens; we checked the official table): ≈ 20 calls per run × (~3k tokens in, ~1.5k out, thinking included) ≈ $0.02.
- One Sonnet 5.5 report call (**$2 / $10 per MTok**) ≈ $0.04–0.06.
- **Total ≈ $0.08 per run.**
- Hard caps: 40 calls and $0.30 per run, $4.50 for the event (local ledger). The Console limit is the backstop.

**Evaluation budget (fairness).** The agent and each baseline get **exactly `eval_budget` evaluations** of the same `sim.evaluate` with the same Goal:
- Default: 8 × 8 = 64 evaluations.
- The default design counts as evaluation #1 for everyone.
- Duplicates are rejected *before* evaluation and don't count.
- The landscape cloud is visualization only, and no optimizer sees it.

### B.10 Mocks (written at freeze, in `shared/mocks/`)

Every section must run its own tests with **zero network** using these:

| Mock | Behavior |
|---|---|
| `fake_sim.py` | Same signatures as `sim.api`. Uses the **true geometry formulas** from B.5 for area, volume, mass and overhang, plus smooth closed-form surrogates: stability ∝ planform area × moment arm growing with sweep, drag ∝ area × (1 + 4t/c̄) × profile factor, flutter ∝ (t/c̄)^1.5 / aspect ratio. Plausible magnitudes (matching the Score example), deterministic, ~0.1 ms. `landscape()` returns 500 points. |
| `fake_cad.py` | Same signatures as `cad.api`. Generates a real **ASCII STL** of the trapezoid prism (12 triangles, B.5 frame) into `.darwin/geometry/`. Latency 1.7 s (env `FAKE_CAD_LATENCY`). Fails 5 % of the time (`regen_status "ERROR"`, deterministic by hash). Keeps a fake ledger starting at 2,400 with reserve 400. |
| `fake_llm.py` | A `call_model` provider named `mock`. Returns schema-valid JSON for each role: proposer returns parents' params ± 8 % noise with templated rationales; critic and strategist return canned text. Latency 0.4–1.5 s. **5 % malformed outputs** (prose around the JSON, or a missing field) to exercise retries. Zero cost, but reports token counts. |
| `make_sample_run.py` | Runs a tiny in-process loop with all three fakes (8 gens × 8, baselines on) and writes `fixtures/sample_run.jsonl` with realistic `ts` gaps. Re-run any time; output is deterministic for a seed. |
| `mock_server.py` | FastAPI on `:8000` implementing **every REST route in B.8** with fixture data. `POST /api/runs` and `POST /api/replay` stream `sample_run.jsonl` over `/ws` at real timing (`?speed=`). Serves fake STLs. This lets S4 build the whole UI without the backend. |

### B.11 Integration order and checkpoints

| CP | When | Pass criteria (everyone at one laptop, 10 minutes) |
|---|---|---|
| **CP0** contract freeze | Fri 20:30 | `make contracts` passes (fixtures validate). `python -m shared.mocks.make_sample_run` works. S4's app renders `sample_run.jsonl` from `mock_server`. S1 has posted the spike verdict in `cad/SPIKE.md`. Tag `contracts-v1`. |
| **CP1** Tier 1 | Fri 23:15–00:15 | Real `sim` + real `backend` + Haiku proposer + real `cad` on **prod** + live dashboard: a run completes, at least one champion STL is regenerated in Onshape and shown in 3D, and the score chart climbs. Tag `tier1`. |
| **CP2** Tier 2 core | Sat 09:00–09:45 | Multi-agent feed, NL goal, CMA-ES and random baselines on matched budgets, ledger meter, replay of a recording works with Wi-Fi off. |
| **CP3** Tier 2 complete | Sat 12:00 | Pareto view, lineage tree, morphing, winner card, print package exported; print #1 in hand. Full 2-minute demo dry-run. Tag `tier2`. |
| **CP4** Tier 3 | Sat 19:00–20:00 | Auto-discovery on the second part, high-fidelity check, report export. Tag `tier3`. |
| **Freeze** | Sat 23:00 | Bug fixes only, from a written list. Tag `freeze`. |

**Integration rule:** wiring changes happen only in `backend/wiring.py` (S3). If a real component fails at a checkpoint, flip its env var back to the fake and keep going.

---

## Part C: The four sections

Each section repeats only the contract pieces it needs. Everything referenced as "B.x" is frozen.

---

### S1: CAD and Onshape (`cad/`)

**Mission:** own every byte that goes to or from Onshape: the parametric fin, the cheapest possible geometry path, the call ledger, auto-discovery, and the print handoff.

**Contract pieces you need:**
- B.5 (geometry and parameters)
- `DesignSpace`, `ParamSpec`, `CadSource`, `GeometryRef`, `OnshapeBudget`
- `cad/api.py` signatures (B.7)
- Budget rules (B.9)
- `geometry_key()` from `shared.contracts`

**In scope:**
- The fin Part Studio, built in the Onshape UI with configuration inputs.
- The configuration spike.
- `OnshapeClient` (auth, redirects, retries, ledger).
- Configured STL export (default path).
- Fallback write paths (custom feature, then feature POST).
- Regeneration-failure and sanity detection.
- The geometry cache.
- `commit_to_document`.
- Auto-discovery.
- Print package.
- Second Part Studio for Tier 3.
- Physical printing logistics.

**Out of scope:**
- Any scoring or physics (S2).
- Deciding *which* designs to build (S3 decides; you build what you are asked).
- UI (S4).
- Rendering STLs.

#### Verified facts you build on

- **API base and auth:** `https://cad.onshape.com/api/v10`, HTTP Basic auth with `(ONSHAPE_ACCESS_KEY, ONSHAPE_SECRET_KEY)`.
- **Reading features:** `GET /partstudios/d/{did}/w/{wid}/e/{eid}/features` lists features. Variables are `featureType == "assignVariable"`. The variable's name is in the parameter with `parameterId == "name"`, and the expression is in both `lengthValue` and `value`.
- **Updating a variable:** `POST .../features/featureid/{fid}` with:
  - body `{"btType": "BTFeatureDefinitionCall-1406", "feature": …}`
  - `serializationVersion`, `sourceMicroversion`, `libraryVersion`, `microversionSkew` and `rejectMicroversionSkew`, copied from the GET response

  The response's `featureState.featureStatus` is `"OK"` on success.
- **STL export:** `GET …/stl?units=millimeter` with `Accept: application/vnd.onshape.v1+octet-stream`.
  - It may redirect. Use `allow_redirects=False`, then re-request `Location` with auth.
  - Output is ASCII STL by default. Parse with a regex on `vertex x y z`.
- **Timing:** about 1.6–1.9 s per design for update plus export.

#### Checklist

**Build the Part Studio** (Onshape UI, dev account, 40 min):
- [ ] Sketch on the Front plane: the trapezoid per B.5, with dimensions driven by **configuration variables** `#root_chord`, `#taper_ratio`, `#semi_span`, `#sweep_deg`, `#thickness`.
- [ ] Extrude symmetric by `#thickness`.
- [ ] `edge_profile` is a **List** configuration input that suppresses or unsuppresses the fillet feature (`rounded`) and the chamfer feature (`beveled`).
- [ ] Set ranges on the configuration inputs exactly as in B.5.
- [ ] Regenerate all 2⁵ continuous-parameter corners × 3 profiles in the UI. The UI doesn't consume API calls. Spot-check about 10 corners in practice.
- [ ] If a corner fails, narrow the bounds and tell S3 **before CP0**.
- [ ] Watch for `beveled` at minimum thickness with minimum tip chord. Guard the chamfer length with `min()` in FeatureScript expressions.
- [ ] Make a copy for the **prod** account (or share the doc with it). Record its URL only in `DARWIN_FIN_DOC_URL`.

**Configuration spike** (≤ 60 min, ≤ 15 calls on the **dev** account). Write `cad/SPIKE.md` with the verdict. Keep raw responses in gitignored `cad/SPIKE_raw/`.
1. [ ] `GET /elements/d/{did}/w/{wid}/e/{eid}/configuration` (1 call) to get the configuration parameter ids, types and ranges. Save it: discovery reuses this format.
2. [ ] `POST …/configurationencodings` with two parameter values (1 call) to learn the exact encoding string. Then implement local encoding (`name=value+unit;name2=…`, URL-encoded) so no further encoding calls are needed.
3. [ ] `GET …/partstudios/d/{did}/w/{wid}/e/{eid}/stl?units=millimeter&configuration=<encoded>` for 3 different param sets (3 to 6 calls including redirects). Check that each bbox matches B.5 analytic values within 0.5 mm, and that the document's microversion is **unchanged** (no writes).
4. [ ] Send an out-of-range or failing configuration. Record exactly what comes back (4xx, an empty STL, or a stale body). This defines regeneration-failure detection.
5. [ ] Optional: `GET …/massproperties?configuration=…` (1 call). Compare the volume to the analytic V, for the high-fidelity validation story.
6. [ ] **Usage-page check:** note the dev account's usage-page count, make exactly 5 known requests (including one redirected export), re-check after it updates, and record whether the redirect counted. If the page lags or is unclear, assume redirects count.
7. [ ] Check whether the Onshape **browser URL** can open a specific configuration (UI viewing doesn't consume API calls). Also check whether `POST /elements/…/configuration` can update the configuration's **default values** in 1 call. This decides how `commit_to_document` works.
8. [ ] glTF: check the API explorer for a Part Studio glTF export. Record yes or no. STL stays the default either way.

**Verdict ladder** (decide by 20:30):
- **A (expected): configured export works.** Cost is about 1 call per design (2 if redirects count). `mode = "configuration"`.
- **B: configurations fail for export.** Build one **custom FeatureScript feature** `DarwinFin` holding all parameters. The update is 1 POST, chained by reusing `sourceMicroversion` from the previous POST response (don't GET features each time), plus 1–2 export calls. `mode = "custom_feature"`.
- **C: fall back to the verified per-variable path.** Each `assignVariable` is its own feature, so it costs N POSTs plus export. **POST only the variables that changed**, tracking the document state locally. `mode = "feature_post"`. The per-run build cap drops to 4.

**API client and ledger:**
- [ ] `onshape_client.py`:
  - A `requests.Session` with Basic auth and a 20 s timeout.
  - 1 retry only on connection error, never on 4xx.
  - Manual redirects: `allow_redirects=False`, then follow `Location` with auth.
  - Every request passes through `ledger.charge(purpose)` **before** sending.
- [ ] `ledger.py`:
  - Append-only JSONL per account label, with no doc IDs or keys in lines.
  - `remaining_estimate`, reserve, unlock flag, and `BudgetExceeded` raised when `remaining_estimate − 1 < reserve` and the reserve isn't unlocked.
  - A thread-safe lock.
  - Exposes `budget_status()`.
- [ ] `stl.py`:
  - Parse ASCII STL with the vertex regex, and binary as a fallback in case headers change.
  - Compute bbox, triangle count and signed volume (divergence theorem).
- [ ] **Sanity check (0 calls).** Compare the STL bbox and volume to the B.5 analytic prediction:
  - bbox within 0.5 mm, volume within 6 %.
  - A mismatch gives `regen_status = "SANITY_FAIL"` and `status = "failed"`.
  - This catches silent regeneration failures and stale exports.
- [ ] `cache.py`: `.darwin/geometry/<geometry_key>.stl` plus a `.json` sidecar holding the GeometryRef. Look up `demo/geometry/` as a read-only second tier.
- [ ] `api.build_geometry`, in order:
  1. Cache.
  2. Budget check.
  3. Chosen mode.
  4. Sanity check.
  5. Store and return the GeometryRef with `onshape_calls` counted.
  6. Never raise.
- [ ] Concurrency: a single worker, serialized. The backend calls it from a thread, and Onshape writes must never interleave.
- [ ] `commit_to_document(space, params)`: whichever the spike found cheapest (configuration-default update, or feature POSTs). It returns a GeometryRef, and the Onshape tab in the demo shows the change.

**Print package:**
- [ ] `export_print_package`:
  - Re-orient the STL so the largest face is on the bed. Thickness (y) becomes slicer z: rotate +90° about x and translate to z ≥ 0.
  - Units mm at scale 1:1.
  - Check minimum thickness ≥ 2.0 mm and beveled edge tip ≥ 0.8 mm (two perimeters at a 0.4 mm nozzle). Otherwise warn.
  - Write `fin.stl` plus `print_card.md`: PLA, 0.2 mm layers, **100 % infill** (so sim mass is honest), no supports, predicted mass, design_id and goal.
  - Zip it.
- [ ] Printer logistics:
  - Kickoff: get the queue form and printer hours from the organizers.
  - Submit print #1 after CP1 (Fri ~00:45) or when the queue opens. Submit #2 (agent champion **and** CMA-ES champion, side by side) by Sat 10:30. Submit #3 (Tier 3 part) by about 19:30.
  - Collect prints, and keep the best set in a labeled bag for the table.
  - Try to borrow or buy a 0.01 g pocket scale so judges can weigh the fin against the prediction.

**Auto-discovery (Tier 3):**
- [ ] `discover_design_space(doc_url)`:
  1. Parse `did/wvm/eid` from the URL.
  2. If the Part Studio has configuration inputs (1 call): map quantity inputs to `continuous` with their own ranges and defaults, and List inputs to `choice`.
  3. Otherwise (1 call, `GET features`): take `assignVariable` features, parse the expressions (`"100 mm"`, `"30 deg"`, unitless), and propose bounds of default × [0.6, 1.4], clipped to > 0 for lengths, with a note that `mode = "feature_post"`.
  4. Return a `DesignSpace` with `discovered = true` and `scorer = ""`. The backend or the user binds a scorer.
- [ ] `probe=True`: export up to 4 probe designs (min corner, max corner, 2 random) to detect regeneration failures and shrink failing bounds 20 % toward the default. Cap: 6 calls per discovery.
- [ ] The Tier 3 second Part Studio, built in the UI once the part is chosen at 12:00 (see D.3). Configuration inputs plus ranges, with the same spike-proven export path.

#### Standalone acceptance test (against mocks and recorded fixtures, 0 network)

- `pytest cad/tests`:
  - STL parsing on a stored fixture STL (one recorded during the spike, copied in sanitized form to `cad/tests/fixtures/`).
  - bbox and volume against B.5 formulas.
  - Configuration encoding round-trip against the spike's recorded encoding.
  - Ledger arithmetic: reserve refusal, unlock, thread safety with 8 threads × 50 charges.
  - Cache hit means 0 calls.
  - Sanity failure on a deliberately wrong STL.
  - Discovery parsing on the recorded `configuration` and `features` JSON.
- A `responses`-style fake HTTP layer (monkeypatched `Session.request`) simulates the redirect flow and confirms both hops are charged.

#### Real integration test

`python -m cad.smoke --account dev` builds 3 designs, a cache hit, and a deliberately failing one:
- Expected cost: ≤ 7 calls.
- Each sanity check passes.
- The ledger delta equals the calls made.

Then at CP1, on prod: 3 builds and 1 `commit_to_document`, with the Onshape tab visibly updated.

#### Deliverables per tier

- **T1:**
  - Fin Part Studio (dev and prod) and the spike verdict.
  - `build_geometry` (configured export or fallback) with cache, ledger and sanity check.
  - `budget_status`.
  - Champions regenerate on prod.
- **T2:**
  - Reserve and unlock, the usage-page sync procedure, `commit_to_document`.
  - Print package and prints #1 and #2.
  - `demo/geometry/` bundle for every champion in the demo recordings.
- **T3:** `discover_design_space` (with probe), the second Part Studio, print #3, optional glTF.

#### Risks and fallbacks

| Risk | Fallback |
|---|---|
| Configurations unsupported for export | Verdict ladder B, then C. Cap builds at 4 per run. |
| Silent stale or failed regeneration | Analytic sanity check (0 calls). |
| Budget burn during development | Develop on the dev account and with `fake_cad`. The prod ledger refuses calls below the reserve. |
| Onshape outage or slowness | `build_geometry` returns `skipped` or `failed`. The dashboard shows the preview mesh, and the demo uses `demo/geometry/`. |
| Print queue full | Print #1 Friday night. Ask about the queue at kickoff. A spare fin from the pre-run is the minimum. |

**Time:** Part Studio 0.7 h · spike 1 h · client, ledger, cache and sanity 2.5 h · commit and print 2 h · discovery 2.5 h · second part 2 h · printing logistics, spread over the event, about 1.5 h. **About 12 h of work.**

---

### S2: Simulation and scoring (`sim/`)

**Mission:** a pure, fast, honest physics scorer. Darwin is only as credible as this module.

**Contract pieces you need:**
- B.5 (geometry and parameters, reference-rocket `context`)
- `DesignSpace`, `Goal`, `Objective`, `Constraint`, `Score`, `Violation`, `MetricInfo`
- The fin_v1 **metric catalog** and the **aggregation rule** (B.6)
- `sim/api.py` signatures (B.7)

**In scope:**
- AeroSandbox aerodynamics.
- Barrowman CP and stability, with fin mass in the CG.
- Mass.
- Flutter.
- Constraints and aggregation.
- Pareto.
- Sensitivity.
- Landscape.
- Batch evaluation.
- High-fidelity champion validation.
- The scorer plugin interface and the second-part scorer (Tier 3).
- Validation tests.
- `sim/PHYSICS.md`.

**Out of scope:**
- Any network call, Onshape, or LLM.
- Choosing designs (S3).
- Plotting (S4).
- Trajectory or apogee simulation (stretch only).

#### Verified facts

- AeroSandbox 4.2.8: `asb.Wing` with `WingXSec`s, `asb.Airplane`, `asb.OperatingPoint(velocity, alpha)`, and `asb.AeroBuildup(...).run()` returns `CL`, `CD`, etc.
- About 10–20 ms per evaluation after a ~1.2 s first call. Warm up once at import, behind a function call.
- `float(aero["CL"])` emits a harmless NumPy deprecation warning. Filter it in `aero.py`.
- Bounding-box-only scoring was too crude. Use the full parameter set.

#### Physics model (fin_v1)

1. **Geometry.** Exact B.5 formulas: c_t, A, mean aerodynamic chord c̄, aspect ratio AR = (2s)²/(2A) for the fin pair, V, overhang, and the mid-chord sweep Λ_c/2.
2. **Mass.** `fin_mass_g = V[cm³] × ρ` with ρ = 1.24 g/cm³ (PLA at 100 % infill, which matches the print card). `fin_mass_total_g = fin_mass_g × fin_count`.
3. **Aerodynamics (AeroSandbox).**
   - Model one fin as a half-wing: root `WingXSec` at z = 0 with chord c_r, tip at z = s with x-offset s·tanΛ and chord c_t.
   - Airfoil: NACA 00xx with t/c = thickness / c̄, clipped to ≥ 0.02.
   - `edge_profile` maps to a profile-drag adjustment documented in PHYSICS.md:
     - `square`: add a blunt LE/TE pressure-drag increment (Hoerner-style base drag on the TE thickness).
     - `rounded`: add TE base drag only.
     - `beveled`: no increment.
   - Run AeroBuildup at `design_velocity_mps`, α = 0 (drag) and α = `alpha_deg` (lift slope), at sea-level atmosphere (`asb.Atmosphere(altitude)`).
   - Fin-set drag: `drag_n = CD·q·S_ref_fin × fin_count`, plus an interference factor of 1.1 (stated in PHYSICS.md).
   - `cd_fins` is referenced to the body cross-section area π(D/2)².
4. **Stability (Barrowman).**
   - Fin normal-force slope: `(CNα)_F = K_fb · [4n(s/d)²] / [1 + √(1 + (2l_m/(c_r+c_t))²)]`, where `l_m` is the mid-chord line length and `K_fb = 1 + r/(s + r)`.
   - Fin CP location from the standard Barrowman X_f formula.
   - Nose: ogive `CNα = 2`, `X_n = 0.466·L_n`.
   - Body tube contributes no normal force (Barrowman).
   - `cp_mm` is the CNα-weighted average.
   - `cg_mm` combines the rocket mass at `cg_without_fins_mm` with the fin set at the fin centroid. Fins are flush with the aft end, so the root LE sits at `body_length − c_r`. **Heavier fins pull the CG aft.** This is a real coupling the agent must discover.
   - `stability_margin_cal = (cp − cg)/D`.
   - Cross-check: compare AeroSandbox's lift slope for one fin with the Barrowman fin term, and record the ratio in `warnings` if it falls outside 0.6–1.6.
5. **Flutter.** Use the NACA TN 4197 flutter-boundary form popularized for rocketry:

   `V_f = a·√( G / ( (1.337·AR³·P·(λ+1)) / (2(AR+2)·(t/c_r)³) ) )`

   with sea-level pressure P and speed of sound a, G = `shear_modulus_gpa` (PLA ≈ 1.3 GPa, an isotropic assumption), and λ = taper_ratio. Then `flutter_margin = V_f / design_velocity_mps`. **State in PHYSICS.md that this is a screening estimate, not a guarantee.**
6. **Plausibility guards** add a `warnings` entry and keep the score: CD outside [0.002, 0.2] on fin area, margin outside [−2, 8] cal, mass inconsistent with V·ρ. The critic uses these to flag suspicious designs.

#### Checklist

- [ ] `plugins/fin_v1.py` implements `ScorerPlugin`: `metrics(space, params) → Dict[str, float]`, `metric_catalog() → List[MetricInfo]`, `hifi(space, params) → Dict[str, float]`.
- [ ] `aggregate.py`: objectives, constraints (`param:<name>` refs included), Violation amounts, the frozen aggregation rule, `objective_scores`. Goal `fixed_params` are validated: evaluating a design that disagrees with a fixed param is a hard violation `param:<name> ==`.
- [ ] `api.evaluate` / `evaluate_batch`:
  - `canonicalize` first.
  - `workers > 0` uses `ProcessPoolExecutor` with spawn-safe module-level functions, AeroSandbox warmed up per worker.
  - Target: 64 designs in < 1.5 s serial, and 2,000 landscape designs in < 25 s with 4 workers.
- [ ] `pareto.py`: non-dominated sorting over the goal's objectives. Each is converted to "higher is better" through `objective_scores`. Infeasible designs are ranked after all feasible ones.
- [ ] `sensitivity()`: central differences at ±5 % of each continuous range, plus each alternative choice for discrete params. Output is normalized to the parameter range. It feeds the critic's "why it won" explanation.
- [ ] `landscape()`: Latin-hypercube sampling over continuous params, uniform over discrete ones, cached in `.darwin/landscape/`. The backend downsamples it for `landscape_ready`.
- [ ] `hifi.py` / `validate_high_fidelity`, for the champion only:
  - (a) `asb.VortexLatticeMethod` on the fin at the same operating point, giving CNα and induced drag. Compare with AeroBuildup and Barrowman.
  - (b) Finer α sweep (−4…6°) to check linearity.
  - (c) Report discrepancies as `warnings` with percentages.
  - Return `Score` with `fidelity="high"`.
  - Stretch: OpenRocket through `orhelper` (needs Java and JPype). Only attempt if Java is already installed. Never on the critical path.
- [ ] Validation tests (`sim/tests/test_physics.py`):
  - **Monotonicity:** more span gives more stability, more mass, more drag. More thickness gives more flutter velocity and more mass. More sweep moves CP aft at fixed area. More taper (less tip chord) gives less mass.
  - **Known shapes:** square-plate and delta-fin Barrowman values against hand-calculated numbers for the 1966 Barrowman report example, documented in the test. A rectangular wing's AeroBuildup CLα within 15 % of thin-airfoil and lifting-line theory, `2πAR/(AR+2)`.
  - **Units:** a 90 × 60 mm rectangle, 3 mm thick, weighs 20.1 g ± 0.1.
  - **Determinism:** the same params give a bit-identical Score.
  - **Aggregation:** a hand-computed example matches the frozen rule. Infeasible designs are always below feasible ones.
- [ ] `PHYSICS.md` (feeds the pitch and Devpost; **honest**):
  - What each metric is and its method.
  - The assumptions: subsonic, low incidence, isolated fin plus a body-interference factor, no fin-fin interference, isotropic PLA, 100 % infill, rigid body, fixed reference rocket.
  - What it's good for (ranking designs and exploring tradeoffs) and what it's not (certification, flight safety).
  - A validation table with numbers from the tests.
- [ ] Tier 3: `register_scorer` for the chosen second part, using an analytic model (see D.3) with its own metric catalog, tests and PHYSICS section.

#### Standalone acceptance test

`pytest sim/tests` passes with only `shared/` installed, including:
- `evaluate(space, defaults, goal_example)` returns a Score whose metric keys equal the frozen catalog.
- `aggregate ∈ [−∞, 1]`.
- `evaluate_batch` of 64 designs takes < 1.5 s.
- `landscape(n=2000)` takes < 25 s.
- All monotonicity tests pass.

`python -m sim.demo` prints a table for the default design, the B.6 example design, and one design per corner.

#### Real integration test

At CP1, S3 sets `DARWIN_SIM=real`, and a full run completes with no `warnings` explosion (< 10 % of designs warned). At CP2, S1 compares the analytic V to the Onshape STL volume for 3 champions, which should agree within 3 %.

#### Deliverables per tier

- **T1:** fin_v1 metrics (aero, Barrowman, mass, flutter), aggregation and constraints, `evaluate` / `evaluate_batch`, catalog, core tests.
- **T2:** Pareto, sensitivity, landscape with a process pool, plausibility warnings, the full validation suite, PHYSICS.md v1.
- **T3:**
  - `validate_high_fidelity` (VLM plus α sweep).
  - Second-part scorer plugin.
  - Optional OpenRocket cross-check.
  - Stretch: a 1-DOF apogee estimate (drag × velocity profile) as an extra metric.

#### Risks and fallbacks

| Risk | Fallback |
|---|---|
| AeroBuildup misbehaves on very low-AR fins | Clip inputs. Fall back to a flat-plate skin-friction (Schlichting) plus form-factor drag model, flagged in `warnings`. |
| Barrowman and AeroSandbox disagree badly | Barrowman owns stability, AeroSandbox owns drag. Show the disagreement as a validation finding rather than hiding it. |
| Process pool is fragile on macOS | Run serially (64 evals is still < 1.5 s). Landscape runs once in the background and is cached. |
| Physics looks implausible to a judge | The PHYSICS.md validation table, the high-fidelity check, and the printed fin weighed on a scale. |

**Time:** core physics 3 h · aggregation and Pareto 1.5 h · tests 2 h · sensitivity and landscape 1 h · high-fidelity 1.5 h · PHYSICS.md 1 h · second scorer 2.5 h. **About 12.5 h.**

---

### S3: Agent team and orchestration (`backend/`), and contract owner

**Mission:** the brain and the spine. Run the evolutionary loop with a small, purposeful agent team, run a fair classic baseline, stream everything, record everything, and degrade gracefully. **S3 also writes `shared/` at freeze and owns contract-change decisions.**

**Contract pieces you need:** all of Part B. You write it.

**In scope:**
- `shared/` (freeze block).
- FastAPI REST plus WS (B.8).
- The run loop.
- The four agent roles.
- `call_model`.
- Baselines.
- Budgets and caps.
- Recorder and replay.
- `wiring.py`.
- The benchmark harness.
- The engineering report (Tier 3).
- The `/api/discover` endpoint and scorer binding (Tier 3).

**Out of scope:**
- Physics (S2).
- Onshape HTTP (S1).
- UI (S4).
- Authentication or multi-user features: this is a single-laptop app.

#### Agent team: four roles, each with a purpose

| Role | Model | Calls per run | Why it exists | Fallback when the LLM fails |
|---|---|---|---|---|
| **Goal parser** | Haiku 5.5, effort low | 1 (+1 retry) | Turns plain English into a typed `Goal` using **only** catalog metrics and params. It lists its assumptions so the user can correct them. This is the "describe your goal" UX. | Keyword match to the nearest preset, `parsed_by: "fallback"`. |
| **Proposer** | Haiku 5.5, effort low | 1 per generation | Generates N candidates with parents, operator and a rationale, using physics priors. This is where the LLM beats blind search at small budgets. | A seeded GA (Gaussian mutation at `step_scale` plus uniform crossover of elites), `origin: "fallback"`. **Not CMA-ES**, so the comparison stays clean. |
| **Critic (physicist)** | Haiku 5.5 per generation; **Sonnet 5.5 once** for the final report | 1 per generation, async | Explains why the champion won, using `sim.sensitivity` and metric deltas. Flags suspicious results (warnings, boundary-hugging, score jumps > 0.15). Writes the insights the proposer reads next. **Explanations are the product.** | A templated explanation from the largest sensitivity × delta terms (`model: "rules"`). |
| **Strategist** | Haiku 5.5, effort low | About 3 per run (every 3rd generation, or on stagnation) | Decides explore, exploit or refine, plus focus params and step scale. Without it, the proposer collapses onto one basin. The trigger is rare by design. | Rules: stagnation ≥ 2 gives `explore` with `n_explore = N/2`; improvement gives `exploit`; the last 2 generations give `refine`. |

We don't add a fifth agent. Any "planner" or "reviewer" would duplicate the strategist or critic and add latency to a 60-second demo. The final report is the critic in Sonnet mode with a different prompt, not a new agent.

#### `call_model`: the one swappable function (`backend/llm.py`)

The signature is frozen in B.7. Behavior:
- **Providers:** `anthropic` (default), `mock` (`shared/mocks/fake_llm.py`) and `replay` (serves from `.darwin/llm_cache/` only and errors on a miss). A future provider (sponsor credits, Bitdeer, or another paid API) is **one new branch in this file** and nothing else.
- **Anthropic specifics:**
  - The SDK is pinned to `anthropic<1` (Python 3.9).
  - `client.messages.create(model=…, max_tokens=max_tokens (≥ 1500), system=…, messages=[…])`.
  - **Structured output** via `output_config={"format": {"type": "json_schema", "schema": schema}}`, plus `output_config.effort` (`low` for proposer, strategist and parser). If the pinned SDK doesn't accept `output_config` as a kwarg, pass it via `extra_body`.
  - **Never send `temperature`, `top_p` or `top_k`.** Since 2026-10-21 they return a 400 on every model.
  - Haiku 5.5 thinks by default, so select the **first content block with `type == "text"`**. Never use `content[0].text`.
  - Check `stop_reason` first. On `"refusal"` or `"max_tokens"`, treat the call as a failure, then retry or fall back.
- **JSON extraction:**
  1. Parse the text block as JSON.
  2. Otherwise, use the regex `\{.*\}` with DOTALL.
  3. Validate with pydantic or JSON Schema.
  4. On failure, retry up to 2 times, appending the validation error to the user message.
  5. If retries are exhausted, raise `LLMUnavailable`.
- **Caps:**
  - Checked **before** each call: `llm_max_calls`, `llm_max_spend_usd` (per run) and `DARWIN_SPEND_CAP_TOTAL_USD` (local ledger in `.darwin/spend.json`). Exceeding one raises `BudgetExceeded`, and the caller falls back to rules.
  - The cost of each call is computed from `usage` with a price table in `llm.py`: Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10 per MTok.
  - A 25 s timeout. One retry on 429/5xx with backoff.
- **LLM cache:** keyed by sha1 of (model, system, user, schema). Turn it on for rehearsals (`DARWIN_LLM_CACHE=1`) so repeated runs are free.
- Every call emits an `agent_message` with tokens, cost and latency, plus a `budget_update`.

#### Run loop (`run_loop.py`)

```
start_run(goal, space, config):
  emit run_started(summary, design_space, metric_catalog)
  spawn thread: baselines (cmaes, random) — each gets exactly eval_budget evals of sim.evaluate
                → baseline_progress every 8 evals
  spawn thread: sim.landscape → landscape_ready (cached after first time)
  g0: seed = canonicalize(defaults + goal.fixed_params) as eval #1; proposer(n-1, directive=explore)
  for g in 0..G-1:
     proposals = propose(...)  | on LLMUnavailable/BudgetExceeded → fallback GA (emit error, degraded_to)
     validate: canonicalize (clamp+round = operator "repair" if changed), enforce fixed_params,
               reject duplicates by param_hash (refill from fallback GA, uncounted)
     scores = sim.evaluate_batch(...)          → emit design_evaluated × n
     update elites (top-k feasible-first), pareto ranks (sim.pareto_ranks), champion
     if champion improved ≥ geometry_min_improvement and builds < geometry_max_builds:
         enqueue cad.build_geometry(champion) on the geometry worker → geometry_ready (async)
     emit champion_updated (if changed)
     critic(async, non-blocking; insights feed g+1 or g+2) → agent_message
     if g % 3 == 2 or stagnating: strategist → agent_message(directive)
     emit generation_complete, budget_update
     early stop if stagnation ≥ patience or evals exhausted or caps hit
  final: hifi = sim.validate_high_fidelity(champion); final geometry build (cached if already built)
         reporter (Sonnet, 1 call) → agent_message(kind="report")
  emit run_complete(summary)   ;  recorder flushes .darwin/runs/<run_id>.jsonl
```

**Proposer prompt input** (≤ 4k tokens, compact JSON tables):
- The goal.
- Param specs with bounds.
- The top 8 designs (params, key metrics, aggregate, feasible).
- Every design from the last generation.
- Sensitivities at the champion.
- Critic insights (≤ 5).
- The directive.

The output schema:
```
{proposals: [Proposal × n], hypothesis: str ≤ 40 words}
```

**Critic output schema:**
```
{why_winner_won: str, evidence: [{param, metric, effect}], suspicious: [{design_id, reason}], insights: [str ≤ 5]}
```

**Numeric-claim check** (Tier 2.5): every number in critic text must match a number in its input within 2 %. Otherwise the claim is stripped and a warning is shown. **The LLM never invents numbers.** The dashboard and report take every number from data.

**Demo profile:** `population 8 × generations 8`, proposer and critic in parallel where possible. Target: **a run under 60 s** on venue Wi-Fi. The `full` profile is 12 × 12; the `bench` profile has no landscape and no geometry.

#### Baselines (`baselines.py`)

- **CMA-ES** (`cma`):
  - Continuous params normalized to [0, 1].
  - Integer and choice params encoded as continuous [0, k) and floored.
  - Starts at the default design with σ₀ = 0.25 and popsize = N.
  - Stops at exactly `eval_budget` evals.
  - Fitness = −aggregate.
- **Random search:** uniform over the space, same budget, seeded.
- Both run in threads concurrently with the agent. They use the same Goal and `evaluate`, and are seeded from `config.seed`.
- **`bench.py`** for honesty ("measurable usefulness"):
  - 6 goals × 3 seeds × {agent, CMA-ES, random}, on the demo profile.
  - It writes `demo/bench.json` with median and IQR of best aggregate versus evals, plus *evals to reach 95 % of the oracle*. The oracle is a 3,000-eval CMA-ES run plus the landscape max.
  - Cost ≈ $1.00 of Haiku.
  - If the agent loses on some goals, **we report that honestly** and explain it (for example, smooth unimodal goals favor CMA-ES).

#### Recorder and replay

- The recorder appends every emitted `Event` to `.darwin/runs/<run_id>.jsonl`. Curated recordings are copied to `demo/recordings/` after a scrub: `doc_url` is stripped, and no keys appear (assert in a test).
- Replay mode (`POST /api/replay` or `DARWIN_MODE=replay`):
  - Re-emits a recording with the original `ts` gaps × `1/speed`.
  - The new `run_id` is `replay_…`.
  - Geometry comes from `demo/geometry/`.
  - **Zero network.**
- **Degradation ladder** (shown in the dashboard as a status pill, and listed in `RunSummary.degradations`):
  - **L0** live.
  - **L1** Onshape down or budget hit: cache plus preview mesh.
  - **L2** LLM down or capped: fallback GA plus rules critic, clearly labeled.
  - **L3** Wi-Fi down: replay of the matching recording.
  - **L4** laptop failure: the fallback video on the second laptop or a phone.

#### Checklist

- [ ] **Freeze block (19:20–20:30):** write `shared/` exactly per Part B, including the full `contracts.ts`, fixtures, mocks, `check.py`, root `.gitignore`, `.env.example`, `requirements.txt` (`-r` per section), and a `Makefile` with `dev`, `mock`, `test`, `contracts` and `secrets-check`. Run `make contracts`, generate `sample_run.jsonl`, tag `contracts-v1`.
- [ ] `server.py`: FastAPI with every route in B.8, a WS hub with per-run backlog plus fan-out, CORS for `:5173`, and static STL serving from `cad.geometry_file` or `demo/geometry/`.
- [ ] `wiring.py`: env-driven selection of real or fake sim, cad and LLM. `/api/health` reports the modes.
- [ ] `llm.py` `call_model` with providers, caps, cache, cost ledger and JSON robustness.
- [ ] Agents: `goal_parser.py`, `proposer.py`, `critic.py`, `strategist.py`, with prompts in `prompts/*.md` (versioned, short, with schema in the prompt).
- [ ] `run_loop.py` with elites, dedupe, repair, early stop, geometry worker (a single thread calling `cad.build_geometry`), and async critic.
- [ ] `baselines.py`, `bench.py`.
- [ ] `recorder.py`, `replay.py`, curated recordings: the pitch goal × 2, plus one per preset.
- [ ] `presets`: 3 demo goals (stable and light, minimum drag at stability 1.5 cal, flutter-safe for 200 m/s).
- [ ] Tier 3: `report.py`, an HTML engineering report. Sections: goal and assumptions, champion params, metrics before and after, agent-versus-baseline curves (inline SVG), the critic's explanation, high-fidelity check, physics assumptions (from S2's PHYSICS.md), budget used. One Sonnet call for the narrative; numbers are templated from data.
- [ ] Tier 3: `/api/discover` calls `cad.discover_design_space`, then binds a scorer. The LLM (one Haiku call) maps discovered param names onto a registered scorer's inputs, and the user confirms in the UI. Then runs work on the new space.

#### Standalone acceptance test (all fakes)

Run `DARWIN_SIM=fake DARWIN_CAD=fake DARWIN_LLM_PROVIDER=mock pytest backend/tests`. Cases:
- **Full run:** event order and types are valid per B.8. Every payload validates. Agent and baseline evals equal `eval_budget`.
- **Malformed LLM output:** retries, then falls back. `degradations` is recorded.
- **Caps hit:** the run continues on fallback.
- **Geometry:** `geometry_max_builds` respected, and the cad failure is surfaced as `geometry_ready` with status "failed".
- **Recorder and replay:** replaying a recording reproduces an identical event sequence, ignoring `ts` and `run_id`.
- **Secrets:** the scrub test finds no `doc_url` or key patterns.

#### Real integration test

CP1: real sim, real cad (prod), and Haiku produce a full demo-profile run in < 75 s, costing < $0.05 and < 12 Onshape calls. CP2: baselines and agents on the pitch goal, plus a replay of it with Wi-Fi off.

#### Deliverables per tier

- **T1:** `shared/` frozen, server plus WS, run loop with Haiku proposer, `call_model`, real-component wiring, recording.
- **T2:** critic and strategist, goal parser plus presets, CMA-ES and random baselines, caps and spend ledger, replay, degradation ladder, curated recordings, benchmark.
- **T3:** engineering report, discovery endpoint plus scorer binding, numeric-claim check.

#### Risks and fallbacks

| Risk | Fallback |
|---|---|
| LLM slow on venue Wi-Fi | Async critic, effort low, demo profile. The proposer has a 25 s timeout before falling back to GA. Replay if it stays slow. |
| Agent doesn't beat CMA-ES | Pick budgets honestly (small budgets are where priors matter). Show the benchmark medians, and say so if it ties. Never cherry-pick a single seed. |
| Contract drift | S3 is the only writer of `shared/`. Changes are additive optional fields only, with a bumped `CONTRACT_VERSION`, announced in the team chat. |
| Spend overrun | Mock provider in development, LLM cache in rehearsal, hard caps, Console limit. |

**Time:** freeze 1.2 h · server, WS and wiring 2 h · `call_model` 1.5 h · loop 2.5 h · agents and prompts 3 h · baselines and bench 2 h · replay and recordings 1.5 h · report 2 h · discovery binding 1.5 h. **About 17 h.** This is the heaviest section, so give it the strongest backend person.

---

### S4: Dashboard (`dashboard/`)

**Mission:** what the judges see. A polished, cohesive single screen where the goal goes in, the part morphs, the scores climb, the agents talk, and the winner comes out.

**Contract pieces you need:**
- `shared/contracts.ts` (all types)
- B.8 REST and WS events with ordering guarantees
- B.5 fin geometry (for the preview mesh)
- `shared/fixtures/sample_run.jsonl`
- `shared/mocks/mock_server.py` (run with `make mock`)

**In scope:**
- Vite + React + TS app.
- Event-sourced store.
- Every view below.
- Replay (backend replay and in-browser JSONL replay).
- Visual design system.
- Degraded-mode UI.
- README and Devpost assets, demo video recording and editing.
- The pitch deck, if any (one slide max; the demo *is* the pitch).

**Out of scope:**
- Any Python.
- Computing scores or Pareto fronts. Use `pareto_rank` and `pareto_ids` from events. The only client-side computation is for display: the best-so-far curve and preview mesh generation.
- Onshape calls.

#### Architecture

- **`src/store/`**: a zustand store whose state = `fold(events)`, and a pure reducer per event type with unit tests. **Live and replay use the identical reducer.** Sources:
  - `wsSource(run_id)` with auto-reconnect and dedupe by `seq`.
  - `fileSource(jsonl, speed)` for in-browser replay with no backend at all. This is kiosk mode, the last-resort offline demo.
- **`src/geometry/finPreview.ts`**:
  - Builds a `BufferGeometry` for any `params` from the B.5 definition. Planform plus thickness, with an approximate rounded or beveled edge (a few extra vertices).
  - **Fixed topology** (same vertex count for every design), so morphing is a per-vertex lerp.
  - This makes the 3D view live and smooth with 0 API calls. When `geometry_ready` arrives, cross-fade (opacity 400 ms) to the real Onshape STL with an **"Onshape-verified ✓"** badge, and show the call count.
- **`src/three/`**:
  - Scene: Z-up to Y-up rotation (−π/2 about x), `OrbitControls`, soft studio lighting, a ground shadow, slow auto-rotate.
  - The champion morphs over 600 ms (ease-in-out) when `champion_updated` fires.
  - An optional ghost of the seed design (wireframe) for before and after.
  - Show the fin mounted on a translucent body-tube segment (a 76.2 mm cylinder) so judges read it as a rocket fin.

#### Screen layout (1440 × 900 laptop, also usable at 1280 × 800)

```
┌ Top bar: DARWIN · goal input (+3 preset chips) · [Run] [Replay ▾] · status pill (LIVE / CACHE / FALLBACK / REPLAY)
│          budget meters: Onshape calls left (prod, reserve marker) · model $ (run / total) · evals used
├──────────────────────────────┬────────────────────────────────┬─────────────────────────────┐
│ 3D champion (hero, ~45%)     │ Score vs evaluations           │ Agent feed                  │
│ morphing preview → STL       │ agent vs CMA-ES vs random      │ cards per agent (color +    │
│ badge, gen counter, metrics  │ (+ benchmark median band)      │ icon), refs clickable,      │
│ chips (stability, drag, g)   ├────────────────────────────────┤ warnings in amber           │
│                              │ Pareto: landscape cloud (grey) │                             │
│                              │ + agent points + front line    │                             │
├──────────────────────────────┴────────────────────────────────┴─────────────────────────────┤
│ Lineage tree (gen columns, parent→child edges, champion path highlighted)  │ Parallel coords  │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
  Winner card (modal on run_complete): before/after 3D + metrics table, critic explanation,
  hi-fi check, agent-vs-baseline delta, [Open in Onshape] [Commit to Onshape] [Export print] [Report]
```

#### Checklist

- [ ] Scaffold: Vite + React 18.3.1 + TS strict + Tailwind 3.4 + three + zustand + recharts + d3-scale/d3-shape, with **exact versions pinned** in `package.json` and a committed lockfile. Path alias `@shared` points to `../shared/contracts.ts`.
- [ ] Design system:
  - Dark "mission control" theme with a light variant, an 8 px grid, Inter + JetBrains Mono.
  - One accent color per agent role, plus fixed colors for agent, CMA-ES and random that are consistent across every chart.
  - Large numerals for the key metrics, and motion that is subtle and purposeful.
- [ ] Store plus reducers plus `wsSource` and `fileSource`, with Vitest tests on `sample_run.jsonl` (final state equals `run_complete` summary).
- [ ] Goal input, preset chips and the **interpreted-goal confirmation strip** (objectives, constraints, assumptions as editable chips) from `POST /api/goal/parse`.
- [ ] 3D hero: preview mesh, morph, STL cross-fade, badge, body-tube context, seed ghost toggle.
- [ ] Score-vs-evaluations chart: best-so-far for the agent (from `generation_complete` / `design_evaluated`) and baselines (`baseline_progress`), with a shared x-axis of evaluations (the matched budget), plus the benchmark band from `demo/bench.json` if served.
- [ ] Pareto view:
  - Metric selector, defaulting to the first two objectives.
  - The landscape cloud from `landscape_ready`.
  - Agent designs colored by generation.
  - The front from `pareto_ids`.
  - Optional baseline overlays.
- [ ] Lineage tree:
  - x = generation, y = rank.
  - Node size and color by aggregate and origin. Infeasible nodes hollow.
  - Bezier edges from `parent_ids`, with the champion's ancestry highlighted.
  - Hovering shows params and rationale.
  - Clicking selects the design, which drives the 3D view and the feed highlight.
- [ ] Parallel-coordinates parameter plot of all designs (brushable if time allows).
- [ ] Agent feed: cards per `agent_message`. Show agent, model, latency and cost on hover, collapsed body, clickable refs, a "fallback" or "rules" label when not an LLM, and `error` events as amber system cards.
- [ ] Budget meters: Onshape remaining with a reserve marker (red when `hard_stop`), model spend run and total, evals used/budget.
- [ ] Winner card:
  - Before and after (seed versus champion) metrics with deltas.
  - The critic's explanation, the high-fidelity check, and agent versus baseline.
  - Buttons: Commit to Onshape (`POST /commit`), Export print package (`POST /export`), Report (`GET /report`), Open in Onshape (URL from backend, if the spike found UI configuration URLs work).
- [ ] Replay picker: `GET /api/runs` (recordings), speed control (1×, 2×, 4×), and "Load JSONL file" for kiosk mode.
- [ ] Degraded-mode UI: the status pill and a toast on `error` events. The app must never show a blank or crashed panel. Use error boundaries per panel.
- [ ] Tier 3: discovery page (paste URL, show discovered params and bounds as an editable table, bind scorer, start run), and report viewer.
- [ ] Polish pass (Sat 21:00): loading states, empty states, 60 fps check on the 2018 Intel Mac (cap the pixel ratio to 1.5, disable shadows on low fps), no console errors.
- [ ] Devpost and README:
  - Screenshots and GIFs taken from **replay mode** (no keys on screen).
  - Architecture diagram.
  - Fallback video (≤ 2 min, voiceover from the demo script). Keep it on two laptops plus a phone.

#### Standalone acceptance test

`npm test`: reducers on `sample_run.jsonl`, plus `finPreview` matching the bbox and volume formulas for 5 param sets (within 1 %). Run `make mock` and `npm run dev`: a full run streams in under 70 s with every panel live, no console errors, and kiosk mode works with Wi-Fi off.

#### Real integration test

CP1: the dashboard against the real backend on prod Onshape. The 3D view swaps to the Onshape STL, and the chart climbs. CP2 and CP3: baselines, Pareto, lineage, winner card, replay of a real recording.

#### Deliverables per tier

- **T1:** scaffold, store, goal input, 3D champion with preview mesh plus STL swap, score chart, basic feed, budget pill.
- **T2:** interpreted-goal strip, smooth morphing, agent versus baselines, Pareto, lineage, parallel coordinates, full feed, meters, winner card, replay plus kiosk mode, degraded UI, polish.
- **T3:** discovery UI, report viewer, second-part preview (generic STL-only morph via cross-fade if no parametric preview), Devpost assets, video.

#### Risks and fallbacks

| Risk | Fallback |
|---|---|
| three.js is slow on the Intel Mac | Lower the pixel ratio, drop shadows, pause auto-rotate. |
| Backend not ready | `mock_server` plus kiosk replay. You never block on S3. |
| Morphing between real STLs is impossible (different topology) | Morph the parametric preview, then cross-fade to the STL. That's the design, not a workaround. |
| Too many panels to polish | Hero, chart, feed and winner card are must-polish. The tree and Pareto can be simpler. |

**Time:** scaffold and design system 1.5 h · store and sources 1.5 h · 3D and morph 3 h · charts 2.5 h · lineage 2 h · feed and meters 1.5 h · winner card 1.5 h · replay and kiosk 1 h · Tier 3 UI 2 h · polish 2 h · Devpost and video 2 h. **About 20 h** for an agent-heavy section; parallelize panels across agent sub-sessions in the same folder.

---

## Part D: Tiers (each tier is demoable end to end)

### D.1 Tier matrix

| | **Tier 1** (Fri ~00:15, internal MVP) | **Tier 2** (Sat 12:00, full product) | **Tier 3** (Sat 20:00, generalization and wow) |
|---|---|---|---|
| **S1 CAD** | Fin Part Studio, spike verdict, `build_geometry` + ledger + cache + sanity, champion regenerates on prod | Reserve/unlock, `commit_to_document`, print package, **print #1 and #2 in hand**, demo geometry bundle | Auto-discovery (+ probe) on any Part Studio, second Part Studio, print #3 |
| **S2 Sim** | fin_v1 aero + Barrowman + mass + flutter, aggregation + constraints, batch eval | Pareto, sensitivity, landscape, validation suite, PHYSICS.md | High-fidelity VLM check, second-part scorer, optional OpenRocket |
| **S3 Backend** | Contracts, server + WS, loop with Haiku proposer, recording | Goal parser, critic, strategist, CMA-ES + random on matched budget, caps, replay, degradation ladder, bench | Engineering report, discovery + scorer binding, numeric-claim check |
| **S4 Dashboard** | Goal input, 3D champion, score chart, basic feed | Morphing, agent vs baselines, Pareto, lineage, winner card, meters, replay/kiosk, polish | Discovery UI, report viewer, Devpost assets, video |
| **Demo** | Typed goal → run → champion in Onshape and in 3D, score climbs | The full 2-minute demo script (F.1) | Plus "and it works on *any* Part Studio": paste a URL, discover, optimize |

### D.2 Tier 3 stretch ideas (only if CP4 passes early)

Listed in value order:
1. A 1-DOF apogee metric (drag-aware altitude estimate).
2. An "ask Darwin why" box: the judge asks a question about a design, answered by one Haiku call grounded in that design's data.
3. Multi-goal comparison: two goals side by side, showing different champions.
4. An OpenRocket `.ork` export of the champion fin set for the rocketry team's own tools.
5. A webhook or Onshape App Store packaging story (slides only).

### D.3 Tier 3 second part: decide at Sat 12:00 (15 minutes, all four)

**Criteria:**
1. A judge understands the tradeoff in 5 seconds.
2. An analytic scorer can be built in ≤ 2.5 h with honest assumptions.
3. It has ≥ 3 driving dimensions plus one discrete choice.
4. It prints in ≤ 45 min.
5. The optimum is visibly non-obvious.

**Candidates:**

| Part | Scorer (analytic) | Tradeoff judges get |
|---|---|---|
| Cantilever shelf bracket | Euler–Bernoulli beam with rib second moment, deflection and stress versus mass | Stiff versus light |
| Rocket nose cone | Haack or von Kármán / ogive / conical drag, slender-body CNα, mass | Same domain, so a strong story continuation |
| Compliant flexure or snap-fit | Beam stiffness and max strain versus PLA yield | Springy but not breaking |
| Heat-sink fin array | Fin efficiency plus natural-convection correlations | Cooling versus material |
| Phone stand | Tipping stability (CG geometry) plus beam deflection | Stable versus small |

---

## Part E: Schedule and integration (Pacific time)

Owners: **S1** CAD · **S2** Sim · **S3** Backend and contracts · **S4** Dashboard. "Agent" means that owner's Claude Code session.

**Sleep plan:**
- **Shift A** is S2 + S4. **Shift B** is S1 + S3.
- Before sleeping, each owner queues one long, fully specified, mock-testable task for their agent in auto mode, for example "write and pass the validation suite" or "build the lineage view against `sample_run.jsonl`".
- Never queue Onshape-touching tasks unattended (prod budget).

### Friday Oct 23

| Time | All / S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| 19:00–19:20 | **Kickoff (all):** assign sections, read Parts A–B, create conda env `darwin` (py3.9) and Node 20. S1: ask the organizers for the printer queue form and hours. S3: set the Console spend limit to $5. Everyone: confirm dev Onshape keys in `~/.darwin_secrets.sh`. | | | |
| 19:20–20:30 | S1: build the fin Part Studio in the UI (dev); **20:00 configuration spike** (≤ 15 dev calls) | Agent: fin_v1 physics prototype from B.5 (local stub types until freeze) | **Agent: write `shared/` (freeze)** | Agent: Vite scaffold, design system, `finPreview.ts` from B.5 |
| **20:30** | **CP0: contract freeze**, spike verdict, tag `contracts-v1` | | | |
| 20:30–23:15 | S1: client + ledger + configured export + cache + sanity; copy Part Studio to prod; prod smoke test (≤ 40 calls) | Real `evaluate`/batch, catalog, aggregation, core tests | Server + WS + run loop + `call_model` (mock, then Haiku) + recorder | Store + `wsSource` + goal input + 3D hero + score chart + feed, against `mock_server` |
| **23:15–00:15** | **CP1: Tier 1 integration** on prod (≤ 60 calls). Record a rough screen capture as the first fallback. Tag `tier1`. | | | |

### Saturday Oct 24

| Time | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| 00:15–00:45 | Pre-run #1 champion → print package → **submit print #1** (or queue for opening) | Queue agent: validation suite + Pareto | Pre-run #1 on the pitch goal; queue agent: critic + strategist (mock LLM) | Queue agent: lineage tree + Pareto view against fixtures |
| 00:45–05:30 | Ledger reserve/unlock, `commit_to_document`, print-package checks | **Sleep (Shift A)** | Critic, strategist, goal parser, presets, CMA-ES + random baselines, caps | **Sleep (Shift A)** |
| 05:30–09:00 | **Sleep (Shift B)**; agent: discovery parsing against recorded JSON (no network) | Sensitivity, landscape, flutter checks, PHYSICS.md v1 | **Sleep (Shift B)**; agent: replay + degradation tests (fakes) | Morphing, winner card, budget meters, replay/kiosk, parallel coordinates |
| **09:00–09:45** | **CP2: Tier 2 core integration** (≤ 80 calls). Re-sync the Onshape usage page. Check Console spend. | | | |
| 09:45–10:30 | Pre-run #2 champion **and** CMA-ES champion → **submit print #2** | Tune catalog normalization ranges on real runs | Pre-run #2, curate recordings, start `bench.py` | Wire real recordings, polish hero + chart |
| 10:30–12:00 | Collect print #1, demo geometry bundle, prod usage check | Validation table, high-fidelity prototype | Bench results → `demo/bench.json`; numeric-claim check | Benchmark band, interpreted-goal strip, degraded UI |
| 11:00 | **Rocketry contact call (whoever has the contact, 10 min).** Get the problem statement and a quote, with permission. This gates the Anthropic track. | | | |
| **12:00** | **CP3: Tier 2 complete.** Full 2-minute dry run. Record fallback video v1 from replay. Tag `tier2`. | | | |
| 12:00–12:45 | Lunch + **Tier 3 part decision (D.3)** | | | |
| 12:45–19:00 | Second Part Studio, discovery + probe, print #3 (~19:30) | Second-part scorer + tests, `validate_high_fidelity` | Report, `/api/discover` + scorer binding | Discovery UI, report viewer, polish |
| **19:00–20:00** | **CP4: Tier 3 integration** (≤ 120 calls). Tag `tier3`. | | | |
| 20:00–21:00 | Dinner. **Devpost draft** (S4 leads; each owner writes 3 sentences on their section). | | | |
| 21:00–23:00 | Bug list; prints sorted and labeled | PHYSICS.md final; assumptions slide | Curated recordings re-cut on the final build; LLM cache warm | Polish pass; **22:00 full rehearsal ×2 (all)**; 22:30 record fallback video v2 |
| **23:00** | **FEATURE FREEZE.** Tag `freeze`. Only fixes from the written list after this. | | | |
| 23:15–03:15 | Fix list; rehearse Q&A | **Sleep (Shift A)** | Fix list; replay drills with Wi-Fi off | **Sleep (Shift A)** |

### Sunday Oct 25

| Time | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| 03:15–07:15 | **Sleep (Shift B)** | Devpost technical sections, physics FAQ | **Sleep (Shift B)** | README, video edit, screenshots from replay, `make secrets-check` |
| 07:15–08:15 | **All: rehearsal ×3 with timer**, Q&A drill (G list), budget check: Onshape ≥ 500 left, spend ≤ $3.50 | | | |
| 08:15–08:45 | **Submit Devpost with table number** (target 08:45; hard deadline **09:00**) | | | |
| 08:45–10:00 | Edits allowed until 10:00. Final fixes only from the list. Charge laptops. Second laptop running kiosk replay plus video. | | | |
| 10:00–10:30 | Table setup: demo laptop (live), Onshape tab, printed fins (agent versus CMA-ES), scale, body-tube mock-up if available. Set `DARWIN_ALLOW_RESERVE=1`. | | | |
| **10:30–12:30** | **Judging. All four at the table.** Rotate roles: S3 drives, S4 narrates, S2 takes physics questions, S1 hands over the print and answers CAD questions. | | | |

---

## Part F: Demo, pitch and judging

### F.1 Two-minute demo script

| t | Who / what | Say |
|---|---|---|
| 0:00 | S4, title screen | "Rocketry teams spend weeks hand-tuning fins in simulation. Darwin does it in a minute, on their real CAD, and tells them why." |
| 0:10 | **The judge types a goal** (or taps a preset). The interpreted-goal strip appears. | "It turned your sentence into objectives and hard constraints. Here are the assumptions it made; you can edit any of them." |
| 0:20 | Run starts: 3D fin morphs, agent feed fills, three curves climb | "Four agents: a proposer, a physicist critic, a strategist and the parser. Every candidate is scored by real aerodynamics: AeroSandbox for drag, Barrowman for stability, and a flutter check. On the right is a classic optimizer, CMA-ES, and random search, with the **same 64-evaluation budget**." |
| 0:45 | Critic card highlighted | "This is why: thinner beveled fins cut drag, and sweep moves the center of pressure aft to recover stability without adding mass." |
| 1:00 | Champion updates. "Onshape-verified ✓" badge; Onshape tab regenerates the part (commit) | "That's not a picture. The real parametric model in Onshape just regenerated. One API call per design, cached, and metered, because our API budget is finite." |
| 1:20 | Winner card: before and after, agent versus baseline | "Better than CMA-ES at this budget. Over our benchmark of 6 goals × 3 seeds, the median result is <bench number>." Use the real number, or say "comparable" honestly. |
| 1:35 | **Hand the judge the printed fin** (plus the CMA-ES fin) | "This is this goal's champion from this morning, printed solid PLA. The sim predicted <x> g; put it on the scale." |
| 1:50 | Discovery (Tier 3) or close | "And it's not hard-coded to fins: paste any Onshape Part Studio URL, and Darwin finds its parameters. This morning we did it for a <second part>." |

**Physics limits (say this unprompted, in one breath):**
"It's fast, semi-empirical physics: subsonic, small angles of attack, a fixed reference rocket, and a screening-level flutter estimate. It's built for ranking designs and exploring tradeoffs, not for certifying a flight. The champion gets a slower vortex-lattice check, and the assumptions page lists everything."

### F.2 Likely judge questions

| Q | A |
|---|---|
| Isn't this just an optimizer with an LLM bolted on? | The LLM brings priors and explanations. We measured it against CMA-ES and random on the same evaluation budget (benchmark medians shown). Simulation calls are what's expensive in real engineering, since CFD or FEA takes minutes to hours. The critic's "why" is what engineers actually want. |
| How do you know the physics is right? | Standard rocketry methods (Barrowman, which OpenRocket uses), AeroSandbox's validated buildup, monotonicity and known-shape tests, a vortex-lattice cross-check, STL volume agreeing with sim volume within 3 %, and the printed part weighed against the prediction. |
| What if the LLM hallucinates? | Numbers never come from the LLM. Every candidate is clamped and validated, then simulated. A numeric-claim check strips critic numbers that aren't in the data. The critic flags suspicious results. If the LLM fails, a GA takes over and the UI says so. |
| Why not just run CMA-ES? | At small budgets, priors win. CMA-ES also gives you no explanation and no natural-language goal. We include it, honestly, as the baseline. |
| Does it generalize? | Auto-discovery reads any Part Studio's configuration inputs or variables and proposes bounds. Scoring needs a scorer plugin per physics domain. We showed a second part. |
| Onshape API limits? | Scoring never touches Onshape, there's 1 call per champion through configured exports, a geometry cache, and a ledger with a hard reserve. The dashboard shows calls left. |
| Cost per run? | About $0.08 of Claude: Haiku for the loop, Sonnet once for the report. Hard caps apply per run and per event. |
| Who's the user, and did you talk to them? | Collegiate rocketry teams. <Name/role of the rocketry contact and their quote>. Only claim this if the conversation happened. |
| Production path? | It's an Onshape app. The scorer plugins wrap the team's existing sims (OpenRocket, CFD). The model call is one function, and Claude is also available through Microsoft Foundry for enterprise tenants. The ledger and caps are already production patterns. |
| What's novel technically? | Closed-loop LLM-guided evolution on a live parametric CAD model, a zero-write configured-export geometry path, Pareto plus lineage over agent reasoning, a fair baseline, and replayable runs. |
| What breaks first? | Low-aspect-ratio extremes in AeroBuildup, which we warn about, and the flutter formula's isotropy assumption for printed PLA. |
| Related work? | See F.4: physics-in-the-loop CAD agents (2026), COSMO-Agent (2026) and Design Agents (2025). They validate the direction. We run on the user's own live parametric CAD with a measured baseline and a physical part. |

### F.3 Per-track checklist

**Most Technically Complex / Overall:**
- [ ] Live end-to-end run (NL goal → sim → Onshape → 3D) in under 60 s
- [ ] Agent versus CMA-ES versus random on a matched budget, plus benchmark medians
- [ ] Pareto front over the ground-truth landscape, plus the lineage tree
- [ ] Printed champion and baseline fins, plus the scale
- [ ] Auto-discovery on a second part (Tier 3)
- [ ] Architecture slide or diagram on Devpost

**Microsoft "Built for the Real World":**

| Criterion | Feature | Talking point |
|---|---|---|
| Customer understanding | Rocketry-team workflow and the goal presets they care about: 1.5–2.5 cal stability, flutter, overhang, mass | "We built for fin iteration, the loop teams repeat for weeks." Include the interview quote if we have one. |
| Measurable usefulness | `bench.json`: evals to reach 95 % of the oracle, agent versus CMA-ES and random. Predicted versus weighed mass. | Concrete numbers, medians, no cherry-picking. |
| Path to production | Scorer plugins, auto-discovery, swappable `call_model` (incl. Microsoft Foundry), API ledger and caching, replayable runs | "Monday: point it at your team's Part Studio." |
| Responsible design | No LLM numbers, numeric-claim check, critic flags, physics-assumptions page, human confirms goal and commit, budgets and caps, no secrets in the repo | "It tells you what it doesn't know." |
| End-to-end functionality | Sentence → real CAD → printed part in hand | The print. |

**Anthropic "Claude for Public Benefit"** (only if the 11:00 conversation happened):
- [ ] Named community: collegiate rocketry teams (student and educational STEM)
- [ ] A real problem, from the contact's own words
- [ ] "Usable on Monday": runs locally on any team's Onshape Part Studio
- [ ] Thoughtful use of Claude: roles, why Haiku versus Sonnet, cost per run, and the failure modes (hallucinated physics prevented by design, fallbacks, over-trust risk addressed by the assumptions page)

**Bitdeer:** skip unless credits appear. Then add one provider branch to `call_model`, route the strategist through it, and mention it.

### F.4 Citations (checked on arXiv; cite exactly)

- Berger et al., *Physics-in-the-Loop: A Hybrid Agentic Architecture for Validated CAD Engineering Design*, arXiv:2605.19717 (May 2026). Agents plan, generate, evaluate and revise CAD with engineering tools as feedback. They report more complex, physically verified designs than comparable agentic methods.
- Deng et al., *COSMO-Agent: Tool-Augmented Agent for Closed-loop Optimization, Simulation, and Modeling Orchestration*, arXiv:2604.05547 (Apr 2026). RL-trained LLM agents orchestrate a CAD → CAE → revision loop, with a dataset of 25 component categories.
- Elrefaie et al., *AI Agents in Engineering Design: A Multi-Agent Framework for Aesthetic and Aerodynamic Car Design*, arXiv:2503.23315 (Mar 2025). Multi-agent design workflows including aerodynamic simulation, claiming steps shortened from weeks to minutes.

**Framing:** "Research is converging on simulation-in-the-loop design agents. Darwin brings that loop to a real team's live parametric CAD, with a fair baseline and a physical artifact."

### F.5 README and Devpost checklist (no secrets)

- [ ] What it does, who it's for, and the demo GIF (from replay)
- [ ] Architecture diagram (B.1) and the four-agent table
- [ ] How to run: conda env, `make mock`, `make dev`, env var **names** only
- [ ] Physics assumptions (link to PHYSICS.md) and validation table
- [ ] Benchmark results with method (goals, seeds, budget)
- [ ] Onshape budget strategy (configured exports, cache, ledger)
- [ ] Responsible-design section
- [ ] Track opt-ins: Microsoft, plus Anthropic and Bitdeer if they qualify
- [ ] Citations (F.4)
- [ ] Team, table number, video link
- [ ] `make secrets-check` passes. No doc URLs or IDs, keys, or account emails in screenshots, video, recordings or README.

---

## Part G: Risk register

| # | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| 1 | Onshape prod budget runs out | Low (with the plan) | Critical | Dev accounts for development, sim-only scoring, cache, ≤ 6 builds per run, ledger hard floor of 400, bucket table (B.9), re-sync at each CP | S1 |
| 2 | Onshape slow or down during judging | Medium | High | Async geometry worker, preview mesh, `demo/geometry/` cache, L1 degradation, replay | S1 / S3 |
| 3 | Configured exports don't work | Medium | Medium | Spike in hour 1. Ladder B (custom feature, 1 POST) or C (changed-variable POSTs only). Fewer builds per run. | S1 |
| 4 | Regeneration failures or silent stale geometry | Medium | Medium | UI corner checks, analytic sanity check (bbox and volume), `failed` status surfaced, bounds narrowed before CP0, probe in discovery | S1 |
| 5 | Bad, slow or malformed LLM output | Medium | Medium | Schema plus retries, regex fallback, 25 s timeout, fallback GA and rules critic (labeled), async critic, effort low | S3 |
| 6 | Model spend overruns $5 | Low | High | Mock provider in development, LLM cache in rehearsals, per-run caps ($0.30, 40 calls), event cap $4.50, Console limit $5, spend meter | S3 |
| 7 | Venue Wi-Fi fails or is slow | High | High | Replay of curated recordings (zero network), kiosk JSONL mode, fallback video on two laptops plus a phone, no hotspots (banned) | S3 / S4 |
| 8 | Implausible physics questioned by a judge | Medium | High | PHYSICS.md, validation tests, high-fidelity check, plausibility warnings, weighing the printed part, upfront limits statement | S2 |
| 9 | Printer queue full or a print fails | Medium | High | Book at kickoff, print #1 Friday night, print #2 by 10:30, duplicates, small parts (< 45 min), keep any successful print | S1 |
| 10 | Contract drift between sections | Medium | High | Frozen `shared/`, a single writer (S3), additive-only changes, `make contracts` in each section's tests, mocks match contracts | S3 |
| 11 | Running out of time | High | High | Tiers are each demoable. Hard freeze at 23:00. Panels ranked by must-polish. Tier 3 is optional for the demo, but Tier 2 isn't. | All (S3 tracks) |
| 12 | Agent doesn't beat CMA-ES | Medium | Medium | Honest benchmark, budgets where priors matter, explanation value, never cherry-pick | S3 |
| 13 | Python 3.9 incompatibility (e.g. SDK 1.x, new syntax) | Medium | Medium | Team-wide pin, `anthropic<1`, `python3.9 -m compileall` in `make test` | S3 |
| 14 | Secrets leak (repo, screenshot, video) | Low | Critical | Keys outside the repo, `.gitignore`, `make secrets-check`, replay-mode screenshots, labels instead of IDs | S4 |
| 15 | Dashboard slow on the Intel Mac | Medium | Medium | Pixel-ratio cap, no shadows, test on that Mac at CP2 | S4 |
| 16 | Demo laptop dies | Low | High | Second laptop with kiosk replay plus video, chargers, the repo cloned on every laptop | All |
