# Darwin

**Cursor for Onshape, for aerodynamic design.**

Darwin is an AI design partner that lives next to your CAD model. You describe what you
want in plain English ("more downforce without going over 15 N of drag"), and Darwin runs
a sequence of small, testable design experiments on the real parametric model in Onshape.
For every step it states a hypothesis, names the aerodynamic principle behind it, predicts
the outcome, runs a physics simulation, and checks itself against the result. Changes that
help are written back to the open Onshape model live. Changes that don't are logged as
lessons and inform the next idea.

You keep the creative part: the shape, and which parameters are worth tuning. Darwin does
the tedious part: tuning them until the part hits your goal, and explaining every change
along the way.

Built at Cal Hacks 13.0 by Daniel, Shaun, Nabira and Hannah.

---

## Contents

- [Why](#why)
- [What it does](#what-it-does)
- [Results](#results)
- [How it works](#how-it-works)
- [The physics](#the-physics)
- [The knowledge layer](#the-knowledge-layer)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Testing](#testing)
- [Safety and budgets](#safety-and-budgets)
- [Limitations](#limitations)

---

## Why

AI tools for CAD already exist, but most of them design from training data rather than from
physical simulation. The ones that do simulate report results back to the engineer and stop
there; they never change the design. Optimizers such as CMA-ES do change the design, but
they are black boxes: they need many evaluations and cannot tell you why a change worked.

Darwin closes the loop between simulation and design, and it shows its reasoning at every
step.

## What it does

The hero demo is an FSAE-style race-car rear wing in Onshape, with Darwin open in a Chrome
side panel beside it. A typical request:

> More downforce without going over 15 N of drag at 25 m/s. You can change the angle,
> span, flap, and endplates. Keep the chord fixed.

For each experiment Darwin shows:

1. **Hypothesis** - the lever it wants to move and the aerodynamic principle behind it.
2. **Prediction** - expected ranges for downforce, drag and the relevant diagnostics.
3. **Measurement** - solver results: induced and profile drag, stall margin, span
   efficiency, Reynolds number, and which constraint is binding.
4. **Decision** - accept, reject or pivot, made by deterministic code, not the language model.
5. **Lesson** - what it learned, carried into the next step's notebook.

Accepted designs morph the open Onshape model in place. Darwin creates named versions before
and after the session, so every result can be reviewed or rolled back inside Onshape.

The wing is the headline part. A rocket fin is the second supported part and the project's
origin.

## Results

**Live session in Onshape** (`demo/recordings/session_1925_d20d.jsonl`, Claude Haiku 5.5):
7 experiments, 5 accepted and written to the open model with zero failed writes. Downforce
went from 98.1 N to 138.7 N (+41%) with drag at 13.9 N against a 15 N limit, in 128 seconds
for $0.019 of model spend.

**Proof bench** (`demo/bench_wing.json`, Claude Sonnet 5.5 planning, real solver): 3 goals,
3 runs each, 20 simulations per run, against CMA-ES and random search on the same editable
parameters and the same simulation budget.

| Goal | Darwin | CMA-ES | Random |
|---|---|---|---|
| Max downforce, drag at most 15 N | 133.1 N | 125.1 N | 106.9 N |
| Max downforce, span locked | 118.0 N | 107.6 N | 106.9 N |
| Min drag, downforce at least 120 N | 9.9 N | 12.9 N | 13.6 N |

Values are medians of three runs. Darwin reached 95% of the best known design in 8 of 9 runs
(median 4 to 11 simulations); CMA-ES did so in 1 of 9 and random search in 0.

**Knowledge ablation:** with the principles turned off, Darwin tied on the easiest goal and
fell behind on the two harder ones. Prediction accuracy was higher with knowledge on for the
main goal (0.80 vs 0.70). With three runs per arm this is evidence, not a statistically
settled result.

The bench is browsable in the dashboard at `/proof`.

## How it works

```text
Onshape model + plain-English request
              |
              v
Chrome side panel  <--- REST + WebSocket --->  FastAPI investigator
                                                  |
                          principles + notebook --+-- aerodynamic solver
                                                  |
                                    guarded Variable-feature writes
                                                  |
                                                  v
                                        Onshape model and versions
```

1. **Read.** The side panel passes the active Onshape document to the backend, which matches
   it to a known project and reads the current parameter values.
2. **Parse.** The request becomes a typed goal: an objective, constraints and the set of
   parameters the user allows Darwin to change. Locked parameters are never touched.
3. **Plan.** The language model proposes the next experiment, grounded in the cited
   principles and in the lab notebook of earlier results. It must commit to a numeric
   prediction before it sees the answer.
4. **Simulate.** The solver scores the candidate design. Bounds, units and constraints are
   enforced in code.
5. **Decide.** Deterministic code accepts or rejects the change and scores the prediction.
6. **Write.** Accepted designs are written to Onshape Variable features, and the model
   regenerates live in the open tab.

The loop is solver-agnostic: a part is a design space plus a scorer, so new physics can be
added as a plugin without changing the investigator.

## The physics

The rear-wing model (`sim/plugins/rear_wing_v1.py`) is a real aerodynamic simulation, not a
lookup table or a guess:

- **Lift** from a vortex-lattice method (AeroSandbox) on the full-chord wing, with the flap
  deflected in airfoil coordinates.
- **Viscous correction** from NeuralFoil section data, iterated to a fixed point with the
  induced angle of attack.
- **Induced drag** from Glauert lifting-line span efficiency, with the Hoerner endplate
  correction to effective aspect ratio.
- **Profile and endplate drag** from NeuralFoil and flat-plate skin friction.
- **Stall margin** from the section's lift-peak angle.

Every model is validated against independent references (Helmbold lifting-line theory,
Glauert thin-airfoil flap theory, Anderson, Abbott and von Doenhoff section data). The table
is regenerated from the code itself with `python -m sim.validation`, so it cannot drift from
the model. See [`sim/PHYSICS.md`](sim/PHYSICS.md) for assumptions, validation and the
approaches we measured and rejected.

The rocket fin uses Barrowman stability and NACA TN 4197 flutter estimates
(`sim/plugins/fin_v1.py`).

## The knowledge layer

Darwin plans from 34 cited aerodynamic principles in
[`domains/aero/principles.md`](domains/aero/principles.md): 18 for wings, 9 for fins and 7
general. Each principle states a lever, its effects and their strength. 29 of them carry a
machine-readable `check:` line, and `sim/tests/test_principles.py` verifies that the solver
actually behaves the way each principle claims, including on neighbouring designs.

Principles inform the plan. Code decides acceptance. See
[`domains/aero/README.md`](domains/aero/README.md).

## Tech stack

| Layer | Technology |
|---|---|
| Browser | Chrome extension (Manifest V3, Side Panel API, vanilla JS), active only on `cad.onshape.com` |
| Frontend | React 18, TypeScript, Vite 7, Tailwind CSS, Zustand, three.js, Recharts, d3 |
| Backend | Python 3.9, FastAPI, Uvicorn, WebSockets, Pydantic v2 contracts mirrored in TypeScript |
| Language model | Claude (Anthropic), behind a swappable provider interface (OpenRouter, DeepSeek, mock and replay also supported) |
| Simulation | AeroSandbox (vortex-lattice method), NeuralFoil, NumPy |
| Baselines | CMA-ES (pycma) and random search |
| CAD | Onshape REST API: Variable-feature writes, versions, configured STL export |
| Testing | pytest, Vitest |

## Repository layout

| Path | Contents |
|---|---|
| `extension/` | Chrome side panel for Onshape |
| `dashboard/` | The `/panel` investigation UI and the `/proof` bench page |
| `backend/` | Request parsing, investigator loop, LLM providers, budgets, replay, benchmarks |
| `sim/` | Solvers, scorer plugins, validation, matched-budget baselines |
| `domains/aero/` | Cited aerodynamic principles used by the investigator |
| `cad/` | Guarded Onshape reads and writes, versioning, STL export, call ledger |
| `shared/` | Python and TypeScript contracts, fixtures, mock server |
| `projects/` | Part definitions: design spaces and Onshape feature mappings |
| `demo/` | Recordings and benchmark results used as evidence |
| `outputs/` | Snapshot of every recording, the Onshape call ledger and LLM spend |
| `docs/` | Direction, pitch, Devpost copy and demo script |
| `scripts/` | Demo, replay, reset and export helpers |

## Getting started

Requirements: Python 3.9, Node 20.19 or newer, Google Chrome.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd dashboard && npm ci && cd ..
```

### Option 1: replay a recorded session (no keys, no network)

```bash
make replay
```

This starts the backend on port 8000 and the dashboard on port 5173 and replays the live
rear-wing session in the panel. Use it for development or as an offline fallback.

### Option 2: mock session for UI work

```bash
make mock                      # fixture-backed API on :8000
cd dashboard && npm run dev    # in a second terminal
```

Open `http://localhost:5173/panel` and load `session_fixture_wing`. That fixture is a
deterministic interface demo, not a solver result.

### Option 3: live session on Onshape

1. Copy the variable names from `.env.example` into a secrets file outside the repository
   (for example `~/.darwin_secrets.sh`) and fill in your Onshape API keys, an LLM provider
   key and the URL of your wing Part Studio (`DARWIN_DOC_WING`).
2. Run `make demo`. It checks that the wing's Darwin variables are adopted, then starts the
   live backend and the dashboard, and prints the panel URL.
3. Load the extension: open `chrome://extensions`, enable Developer mode, choose
   **Load unpacked** and select `extension/`.
4. Open the wing in Onshape, click the Darwin toolbar icon and type a request.

`make reset-wing` puts the demo wing back to its baseline design.

## Testing

```bash
make contracts                 # validate shared fixtures against the contracts
make test                      # Python test suite (offline, deterministic)
python -m sim.validation       # regenerate the physics validation table

cd dashboard && npm test && npm run build
cd ../extension && npm test

make secrets-check             # scan the tree for anything that looks like a key
```

## Safety and budgets

- **No secrets in the repository.** Keys and document URLs live in a local secrets file.
  `make secrets-check` and `make outputs` refuse to pass if anything resembling a key or an
  Onshape document id is present.
- **Onshape call ledger.** Every API request is counted before it is sent, against a hard
  reserve floor, in an append-only ledger that stores endpoint templates only, never ids.
- **LLM spend caps.** Per-run and total caps stop a session before it exceeds its budget.
- **Parameter permissions.** Darwin can only change parameters the user allows. Bounds,
  units and constraints are enforced in code, and acceptance is never left to the model.
- **Geometry checks.** Exported STL is measured against the expected design to catch stale
  geometry or unit-scale errors.

## Limitations

Darwin currently supports aerodynamics: race-car rear wings and rocket fins. Its solvers are
screening-level models (vortex-lattice plus viscous airfoil data), validated against textbook
theory. They are not full CFD, wind-tunnel data or safety certification, and final hardware
decisions still need high-fidelity analysis and physical testing. The wing chord is held
fixed in live sessions because it is not yet wired to the CAD model.
