# Darwin

Darwin turns an engineering goal into an explainable, simulation-backed, parametric CAD design:

`goal → propose → simulate → explain → regenerate CAD → repeat`

The Cal Hacks demo optimizes a rocket fin against stability, drag, flutter safety, mass, and landing overhang. Every candidate is evaluated against the same physics model and evaluation budget as CMA-ES and random-search baselines. Winning geometry is regenerated from the team's Onshape model and can be exported as a print package.

![Darwin architecture](docs/architecture.svg)

## What the dashboard shows

- Natural-language goal interpretation with editable objectives, constraints, and assumptions.
- A live fixed-topology fin preview that morphs between champions, then cross-fades to verified STL geometry.
- Matched-budget agent, CMA-ES, and random-search curves.
- Pareto landscape, evolutionary lineage, and parameter parallel coordinates.
- An agent feed with proposals, critiques, strategy, fallbacks, timing, and cost.
- Onshape, model-spend, and evaluation budget meters.
- A winner card with before/after metrics, high-fidelity checks, print export, CAD commit, and report viewer.
- Backend replay and a browser-only JSONL kiosk mode for an offline demo.

## Quick start

Use Python 3.9 and Node 20.19 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd dashboard
npm ci
```

In two terminals from the repository root:

```bash
make mock
```

```bash
cd dashboard
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The mock server streams the deterministic `shared/fixtures/sample_run.jsonl` recording and serves cached fixture STLs, so it requires no API keys or network.

For the real backend, source secrets from `~/.darwin_secrets.sh`, select component modes with the `DARWIN_*` environment variables documented in `.env.example`, and run `make dev` instead of `make mock`.

## Verification

```bash
cd dashboard
npm test
npm run build
npm audit
```

The S4 suite checks event ordering/deduplication, identical live/file-replay folding, reconnect behavior, and fin preview geometry against the frozen analytic volume and bounding-box formulas.

## Repository map

- `shared/` — frozen Python and TypeScript contracts, events, fixtures, and fakes.
- `sim/` — deterministic aerodynamic, stability, flutter, mass, Pareto, and sensitivity scoring.
- `backend/` — FastAPI orchestration, agent roles, baselines, recording, replay, and reports.
- `cad/` — Onshape geometry, cache, budget ledger, commit, and print handoff when present.
- `dashboard/` — React/TypeScript mission-control interface.
- `docs/` — physics notes, pitch, demo script, and Devpost copy.

## Honest scope

Darwin is an optimization and trade-study tool, not a flight-safety certification system. Its fin model assumes subsonic, low-incidence flow, a rigid body, isotropic 100%-infill PLA, and a fixed reference rocket. See `sim/PHYSICS.md` for methods, validation, and limitations.

No credentials, Onshape document IDs, or production recordings belong in Git. Run `make secrets-check` before sharing or submitting.
