# Demo script and fallback-video shot list

Target length: **1:50–2:00**. The hero is always the FSAE-style rear wing. The
rocket fin is a final proof of reuse only if a checked recording is ready.

## Preflight

- Put the live Onshape wing and Darwin panel side by side before the clock
  starts. Keep terminals, keys, and document IDs off screen.
- Have the finished fixture ready: run `make mock`, run `npm run dev` from
  `dashboard/`, open `/panel`, and choose `session_fixture_wing`.
- Keep the final wing replay and silent fallback video on two laptops.
- Open the proof slide from `demo/bench_wing.json`; if the file is absent, remove
  the ablation claim rather than presenting planned numbers.
- Confirm the prompt's drag limit matches the run being shown.
- Confirm whether this take is **live**, **replay**, or **mock fixture**, and say
  so once on screen.

## Two-minute run of show

### 0:00–0:15 — Problem

**Visual:** simple CAD → simulation → interpretation loop, then the rear wing.

**Say:** “Improving an aero part means changing CAD, simulating, interpreting,
and deciding what to try next. Simulation is getting cheap. The bottleneck is
the engineering judgment between runs.”

### 0:15–0:35 — Scope the request

**Visual:** Onshape wing with Darwin's side panel. Enter:

> More downforce without going over 15 N of drag at 25 m/s. You can change the
> angle, span, flap, and endplates. Keep the chord, mounts, and airfoil fixed.

**Say:** “Darwin reads the model and makes the scope explicit: these variables
may change; everything else stays fixed. It simulates the baseline and exposes
the physics breakdown, not just a score.”

**Point to:** will-change/will-keep chips, baseline downforce and drag,
induced/profile drag, stall margin, and the binding constraint.

### 0:35–0:58 — A rejected experiment

**Visual:** first hypothesis card. Pause before revealing its result.

**Say:** “Darwin picks one lever, cites the principle, and predicts a range
before running the solver. Here it expected more downforce, but drag rose more
than expected and crossed the limit. Code rejected the change. The miss becomes
a measured lesson instead of disappearing.”

**Point to:** predicted versus actual bars, rejected badge, explanation, and new
notebook belief. Read the displayed numbers; do not use illustrative values
from the plan.

### 0:58–1:18 — An accepted experiment and CAD morph

**Visual:** next accepted card and the Onshape viewer.

**Say:** “The notebook says induced drag is binding, so Darwin tests a geometry
change aimed at aspect ratio. This result is feasible and better, so the model
accepts it. The approved Variable feature is written to Onshape, and the real
parametric wing changes beside the reasoning trail.”

If this is replay or the wing write is not proven end to end, replace the last
sentence with: “This recording replays the accepted design event; our separate
live spike proved the Variable-feature write mechanism on a disposable fin.”

### 1:18–1:35 — Learning and final result

**Visual:** fast-forward remaining cards, accuracy sparkline, ruled-out lever,
before/after, and final version.

**Say:** “Each result updates measured lever effects and prediction accuracy.
After two flap failures, Darwin rules that idea out instead of repeating it. It
stops with a feasible design, a before/after, and an auditable account of what
worked and what did not.”

Read the completed run's actual headline result and version name.

### 1:35–1:50 — Proof bench

**Visual:** matched-budget comparison.

**Say:** “Each method gets the same 20 simulations. We compare Darwin with
CMA-ES, random search, and Darwin without its aero knowledge. This measures
simulations to target and final feasible performance—and the ablation tells us
whether the physics prior actually helps.”

Then state the checked-in result exactly. If `demo/bench_wing.json` is missing,
say: “The matched-budget wing bench is still running, so we are not claiming a
win from this demo.”

### 1:50–2:00 — Close

**Visual:** wing before/after; optionally one brief rocket-fin frame.

**Say:** “Darwin is Cursor for Onshape, for aero. Today it reasons over a fast
screening solver; next, the same loop becomes an Onshape App Store app that can
call CFD for verification. The more expensive a simulation is, the more
valuable it is to choose the next one intelligently.”

## Fixture-only fallback values

Use these only while showing the preloaded **synthetic mock fixture**
`session_fixture_wing`, and label the source on screen:

- baseline: 104.42 N downforce, 12.03 N drag;
- final: 141.07 N downforce, 14.87 N drag under a 15 N limit;
- headline change: +35% downforce;
- six steps and 13 simulated candidates;
- running prediction accuracy: 0.75 after step 1, 0.89 after step 6;
- final action: flap increases ruled out after two failures;
- mock version label: `Darwin: more downforce, +35%`.

These values test the story and UI contract. Do not present them as live-solver
validation or proof-bench evidence.

## Fallback ladder

1. **Live session:** panel, real rear-wing solver, and verified Onshape writes.
2. **Final wing replay:** same panel and scrubbed real recording; say “replay.”
3. **Fixture session:** `session_fixture_wing`; say “synthetic fixture.”
4. **Video:** a clean 1440×900 capture under 50 MB; narrate live.

Do not improvise a stronger claim when moving down the ladder. Keep the
hypothesis, prediction, rejection, notebook, and path-to-production beats.

## Recording shot list

1. **0:00–0:08:** Darwin title and the rear wing in Onshape.
2. **0:08–0:25:** prompt plus will-change/will-keep chips.
3. **0:25–0:50:** baseline breakdown and a rejected hypothesis card.
4. **0:50–1:15:** accepted card, visible wing morph, and notebook update.
5. **1:15–1:35:** later steps, prediction-accuracy sparkline, before/after,
   named version.
6. **1:35–1:50:** proof bench with equal budgets and knowledge ablation.
7. **1:50–2:00:** production architecture and optional rocket-fin beat.

Capture one narrated take and one silent screen-only take. Before sharing, run
`make secrets-check` and inspect every frame for keys, IDs, emails, terminal
history, and browser notifications.
