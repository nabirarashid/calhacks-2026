# Demo recordings (replay fallback)

## `session_1925_d20d.jsonl` — THE WING, live (current — use this one)

`make replay`, then open `http://localhost:5173/panel?session=session_1925_d20d` to see the finished
session, or open `http://localhost:5173/panel` and press **Run**: in replay mode Run plays this recording
with its original timing (~2 min, same 138.7 N every time) and never computes anything new. The typed
prompt is ignored, so type the recorded one. No keys, no network, no Onshape. Say it's a recording if
you use it.

Recorded Sat Oct 24 19:25 from the panel API on the real wing Part Studio: **Claude Haiku 5.5 via
OpenRouter** for every role, real `rear_wing_v1` solver, real Onshape writes. Prompt: "Maximize
downforce while keeping drag under 15 N. You can change the angle of attack, span, flap angle, flap
size and endplates." 7 steps, each citing aero principles; 5 accepted and morphed in Onshape;
versions "Before Darwin" / "Darwin: downforce +41%". Downforce 98.1 → 138.7 N, drag 13.9 N (limit 15),
chord held (not wired in CAD yet). 128 s, $0.019. Verified to replay with every key unset (C6).

Each `.jsonl` here is a real run's full event stream. Replaying one needs **no
network, no API keys and no Onshape**: the backend re-emits the events with their
original timing, and the champion's STL is served from `demo/geometry/`.

This is the Wi-Fi-failure fallback (PLAN.md degradation ladder, L3).

## Running it

```bash
# no keys needed
DARWIN_CAD=off DARWIN_LLM_PROVIDER=mock DARWIN_MODE=replay python -m backend.server
```

Then in the dashboard pick the recording, or:

```bash
curl -X POST localhost:8000/api/replay \
  -H 'Content-Type: application/json' \
  -d '{"recording": "demo_pitch_goal.jsonl", "speed": 1.0}'
```

`speed` scales the original timing (`8.0` replays a 76-second run in 9.5 s).

## `demo_pitch_goal_square.jsonl` (older: the fin)

Recorded Sat 12:32 with **real Claude (Haiku 5.5 + one Sonnet report) and real
Onshape**, after the AeroSandbox race fix, the drag-normalization fix and the
goal-parser fix. Square edges, exactly what the live Part Studio builds.
12 Onshape calls, $0.029 of Claude.

Goal: the pitch goal, parsed live by Claude into flutter margin >= 1.5,
stability >= 1.0 cal, total fin mass <= 40 g, and no aft overhang (the
3-inch body tube read deterministically as the rocket body).

| | aggregate |
|---|---|
| agent champion | **0.582** |
| CMA-ES, same budget | 0.585 |
| random search, same budget | −0.006 (infeasible) |

**This run is a tie with CMA-ES. Say so.** The honest claim comes from
`demo/bench.json` (3 goals × 3 seeds, square edges): the agent beats CMA-ES in
6 of 9 runs (all 3 on "Min drag", 2 of 3 on this goal, 1 of 3 on "Flutter-safe"),
and only the agent explains why its winner wins. The seed was not re-rolled to
get a win.

## `demo_pitch_goal.jsonl` (superseded)

Recorded Fri 23:31 with **real Claude (Haiku 5.5 + one Sonnet report) and real
Onshape**. 153 events, 76 s, 20 model calls for $0.029, 18 Onshape calls.

Goal: the pitch goal — *"Maximize this rocket fin's stability, keep drag low,
keep it under 40 g, must fit a 3-inch body tube."*

| | aggregate |
|---|---|
| agent champion `g07-a01` | **0.700** |
| CMA-ES, same 64-eval budget | 0.689 |
| random search, same budget | −0.003 (infeasible) |

Champion: root_chord 61.0, taper_ratio 0.75, semi_span 69.5, sweep_deg 22.0,
thickness 2.9, rounded edges, 3 fins → stability 2.12 cal, drag 1.32 N,
39.6 g total, flutter margin 1.57. All five geometry builds verified against the
analytic formulas (`regen_status: OK`).

**Caveat:** this run pins `edge_profile` to `rounded` via `goal.fixed_params`,
because the Part Studio's `edge_profile` configuration input does not exist yet
(see `cad/PARTSTUDIO.md` "Later"). Both baselines were pinned the same way, so
the comparison is fair. Re-record without the pin once the input exists — the
agent prefers beveled edges (lower drag) and scored 0.804 unpinned.

**The margin over CMA-ES here is thin (1.6 %).** One seed on one goal proves
nothing. `backend/bench.py` (6 goals × 3 seeds) is what decides whether the
claim holds; don't quote this single run as evidence.

## Scrubbing

Recordings carry no secrets: `doc_url` is stripped before anything leaves the
process, and a scrub check over this file finds no keys, Onshape host names,
24-hex document ids or email addresses. Re-check after adding one:

```bash
make secrets-check
```
