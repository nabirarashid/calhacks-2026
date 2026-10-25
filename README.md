# Darwin

**Cursor for Onshape, for aerodynamic design.**

Darwin turns a plain-English request into a sequence of small, testable design
experiments. It reads the parameters of an existing Onshape model, states a
physics-backed hypothesis, predicts what will change, runs an aerodynamic
simulation, compares prediction with result, and either accepts or rejects the
change. Accepted changes are written back to the parametric model; every step
leaves an auditable reason and updates a lab notebook.

The simulator is a tool Darwin uses. The product is the reasoning loop between
simulations.

## The demo

The hero object is an FSAE-style rear wing. A representative request is:

> More downforce without going over 15 N of drag at 25 m/s. You can change the
> angle, span, flap, and endplates. Keep the chord, mounts, and airfoil fixed.

For each step Darwin shows:

1. the lever it wants to test and the aerodynamic principle behind it;
2. predicted ranges for downforce, drag, and relevant diagnostics;
3. measured results from the solver, including induced/profile drag, stall
   margin, span efficiency, Reynolds number, and the binding constraint;
4. an accept, reject, or pivot decision made by deterministic code; and
5. the lesson carried into the next step.

The rear wing is the headline. The existing rocket-fin model is a second aero
part and the project's origin story, not the primary demo.

## Run the finished mock session

The fixture-backed path needs no credentials or network. Use Python 3.9 and
Node 20.19 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd dashboard
npm ci
```

Then, from the repository root, start the two processes in separate terminals:

```bash
make mock
```

```bash
cd dashboard
npm run dev
```

Open [http://localhost:5173/panel](http://localhost:5173/panel), then choose or
load the preloaded finished session `session_fixture_wing`.

That session is a deterministic **mock fixture** for panel development and
rehearsal. It contains six steps, including rejection and pivot behavior, and
finishes at +35% downforce, 14.87 N drag under a 15 N limit, and 0.89 running
prediction accuracy. Those values demonstrate the interface contract; they are
not proof-bench or live-solver results.

To run the real backend, source the local secrets described in `.env.example`
and use `make dev` instead of `make mock`. Never commit credentials or Onshape
document IDs.

## What is real, and what still needs final evidence

- The v1.2 investigation contracts, event stream, rear-wing mock scorer, and
  six-step fixture are in `shared/` and validate offline.
- A live Onshape spike proved that updating a Variable feature changes an open
  tab without refresh. The observed write took 0.47 seconds on a disposable fin
  copy. This proves the write mechanism, not yet a complete rear-wing session.
- Configured STL export is separately proven on the rocket-fin Part Studio.
- The final rear-wing solver validation, end-to-end wing session, named
  before/after versions, and production recording must be reported only after
  their checked-in evidence lands.
- `demo/bench_wing.json` is the required source for Darwin/CMA-ES/random/
  no-knowledge comparisons. **TODO before submission:** replace this line with
  the actual matched-budget result, or say the proof bench was not completed.

## Architecture

```text
Onshape model + user request
          |
          v
Chrome side panel  <---- REST + WebSocket ---->  FastAPI investigator
                                                    |
                           principles + notebook ---+--- aero solver
                                                    |
                                      guarded Variable-feature writes
                                                    |
                                                    v
                                             Onshape versions
```

- `extension/` — Chrome Manifest V3 side-panel shell for `cad.onshape.com`.
- `dashboard/` — compact `/panel` investigation UI and proof views.
- `backend/` — prompt parsing, investigator loop, budgets, replay, and reports.
- `sim/` — deterministic screening solvers and matched-budget baselines.
- `domains/aero/` — cited aerodynamic principles used by the investigator.
- `cad/` — guarded Onshape reads, writes, versioning, export, and call ledger.
- `shared/` — Python/TypeScript contracts, fixtures, and the mock server.
- `demo/` — recordings and benchmark outputs used as presentation evidence.
- `docs/` — direction, physics notes, pitch, Devpost copy, and demo script.

## Knowledge layer

The investigator plans from 34 cited aerodynamic principles in `domains/aero/principles.md`.
Each principle's claimed effects are also checked against the solver by
`sim/tests/test_principles.py`. See [`domains/aero/README.md`](domains/aero/README.md).

## Verification

```bash
make contracts
make test

cd dashboard
npm test
npm run build

cd ..
make secrets-check
```

See `sim/PHYSICS.md` for the applicable model's assumptions and validation.
Darwin produces screening-level design guidance, not CFD, wind-tunnel evidence,
or safety certification. Final hardware decisions still require appropriate
high-fidelity analysis and physical validation.
