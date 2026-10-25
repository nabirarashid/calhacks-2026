# Aero knowledge layer

`principles.md` is Darwin's aerodynamics knowledge. Every planning step pastes the whole file
into the LLM prompt. The model states a hypothesis, cites principle ids and predicts the
percentage change of each metric, and code then scores those predictions against the solver.
So a principle has to do two things: cite a real source, and agree with what our solver
actually does. A principle that is true in a textbook but disagrees with the solver teaches
the agent to predict wrong. In a live pilot, prediction accuracy was 0.93 with the file and
0.77 without it.

Content: W-B (Aero). Parser and wiring: W-C (`pack.py`, `backend/investigator.py`).
Format: PLAN.md B.8.

## What each group covers

There are 34 principles: 18 rear wing, 9 rocket fin, 7 general.

| Group | Principles | Covers |
|---|---|---|
| General lifting surface | `P-Q-SCALING`, `P-CAMBER-ZERO-LIFT`, `P-INDUCED-AR`, `P-INDUCED-QUADRATIC`, `P-SPAN-EFFICIENCY`, `P-SKIN-FRICTION`, `P-PROFILE-LOADING` | Dynamic pressure, camber, induced drag vs aspect ratio and CL, span efficiency, friction and profile drag |
| Rear wing: angle and stall | `P-AOA-LIFT`, `P-SECTION-CLMAX`, `P-STALL`, `P-STALL-MARGIN-LEVERS`, `P-FLAP-STALL-ANGLE` | How AoA strength depends on the stall margin left; the shared AoA and flap lift budget; behaviour at and past stall; which levers spend stall margin |
| Rear wing: flap | `P-FLAP-CAMBER`, `P-FLAP-SATURATION`, `P-FLAP-TRIM`, `P-FLAP-CHORD`, `P-FLAP-CHORD-OPTIMUM`, `P-PLAIN-VS-SLOTTED` | Small vs saturated flap; trimming flap under a drag limit; flap chord fraction and its optimum at large flap; the plain-flap model limit |
| Rear wing: planform and endplates | `P-LOW-AR-SLOPE`, `P-SPAN-AREA-AR`, `P-CHORD-AREA-AR`, `P-ENDPLATE-AR`, `P-REYNOLDS-CHORD` | Span vs chord for added area, endplates and their diminishing returns, Reynolds number |
| Rear wing: strategy and limits | `P-LD-TRADEOFF`, `P-NO-GROUND-EFFECT` | Ranking moves under a drag cap; what the model leaves out |
| Rocket fin | `P-FIN-SPAN-STABILITY`, `P-FIN-SWEEP-OPTIMUM`, `P-FIN-TAPER`, `P-FIN-ROOT-CHORD`, `P-FIN-FLUTTER-THICKNESS`, `P-FIN-MASS-CG`, `P-FIN-COUNT`, `P-FIN-BASE-DRAG`, `P-FIN-STABILITY-TARGET` | Barrowman stability, sweep and root-chord optima, taper, flutter (Martin, NACA TN 4197), fin mass vs CG, fin count, base drag, the stability target |

Every editable lever of `projects/rear_wing/r1.json` and `projects/fin_reference/r1.json` has at
least one principle.

## The rules

- **Lifting surfaces only.** That means the rear wing, the rocket fin, and general
  lifting-surface physics. No ground effect, car bodies, diffusers, bluff bodies or CFD-only
  effects. The solver models none of them (see `sim/PHYSICS.md`), so a principle about them
  would have the agent predict changes the solver can never produce.
- **Budget: 25-35 principles and about 3k planner tokens.** The whole file goes into every
  planning prompt. Estimate the size as `sum(len(id + statement + effects + levers)) / 4` over
  the parsed principles; it is about 3.0k now. When adding a principle, improve coverage or
  tighten wording elsewhere rather than just adding entries.
- **Ids are permanent.** Never rename or delete one: recordings in `demo/` cite them and replays
  would break. Editing statement, effects and check lines is fine.
- **The planner sees only `id`, `statement`, `effects` and `levers`.** `applies_when` and
  `source` never reach it, so any condition the agent needs (for example "only below about 15 deg
  of flap") must go in `statement` or `effects`.
- **Tag part-specific statements** "Rear wing:" or "Rocket fin:". The test checks that the levers
  match the tag.
- **Real sources, no invented numbers.** A number in a statement comes either from the cited
  source or from measuring our solver, and solver-measured numbers are marked "in this model".
- **Principles follow the solver, never the reverse.** If the solver looks wrong, report it to
  the solver owner; don't change the text to hide it, and don't change the solver to fit the text.

## Strength words

These are defined in the file's intro. One modest step (about 1 deg AoA, 3 deg flap, 50 mm
span, 30 mm endplate, 0.03 flap chord fraction; on the fin 10 mm, 0.1 taper, 0.5 mm thickness)
gives:

- **small:** under 2 %
- **moderate:** 2-6 %
- **strong:** over 6 %

The test uses overlapping bands (small 0-3 %, moderate 1.5-7 %, strong over 5 %). It checks only
direction for the absolute metrics `stall_margin_deg`, `stability_margin_cal`, `flutter_margin`
and `aft_overhang_mm`. A `flat` claim means a change under 2 % (under 0.05 for absolute metrics).

## How `check:` works

A check line is read only by `sim/tests/test_principles.py`; the parser ignores it and the
model never sees it:

```
check: flap_angle_deg=20; flap_chord_frac=0.36; step flap_chord_frac +0.03
```

The test:

1. starts from the manifest defaults with the listed overrides applied;
2. steps one lever, staying inside its range;
3. evaluates both designs on the real solver (`rear_wing_v1` or `fin_v1`);
4. asserts every effect in `effects`: the direction, and for percentage metrics the strength band.

Put the start state in the regime the statement describes. For example, `P-FLAP-SATURATION`
starts at 24 deg of flap and `P-AOA-LIFT` at 5 deg. Principles that are strategies or model
limitations have no check line (5 of 34 now; the test allows at most 7).

## Adding or changing a principle safely

1. **Measure first.** Step the lever on the solver in a few regimes before writing. Direct
   calls are free and take about 20 ms each:

   ```python
   import json
   from sim import api
   from shared.manifest import ProjectManifest
   space = ProjectManifest(**json.load(open("projects/rear_wing/r1.json"))).design_space
   api._plugin("rear_wing_v1").evaluate_metrics(space, params).metrics
   ```

   For the fin, use `api.evaluate(fin_space, params, Goal(source_text="", objectives=[], constraints=[])).metrics`.
2. **Write the block** in the B.8 format: `### P-ID`, `statement:`, `applies_when:`,
   `effects:` (`metric: up|down|flat (strong|moderate|small)` joined by `; `), `levers:`,
   `source:`, and an optional `check:`.
3. **Add a check line** unless the principle is a strategy or a limitation.
4. **Run the tests:**
   - `python -m pytest sim/tests/test_principles.py -q`
   - the full suite
   - `make contracts`
5. **Re-estimate the token budget** and stay at about 3k.
