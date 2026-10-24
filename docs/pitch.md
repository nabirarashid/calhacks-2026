# Darwin: two-minute pitch

## The one-line story

**Darwin is Cursor for Onshape, for aerodynamic design. Engineers do not
grid-search; they reason. Darwin makes that reasoning loop visible, testable,
and connected to the parametric model.**

## Spoken pitch

### 0:00–0:15 — The problem

“Improving an aerodynamic part is a loop: change CAD, run a simulation,
interpret the result, and decide what to try next. Simulation is getting
cheaper. The slow part is still the engineering judgment between runs.”

Show one image of the manual CAD → simulation → interpretation loop.

### 0:15–0:35 — Give Darwin the problem

Open the FSAE-style rear wing in Onshape with Darwin beside it. Type:

> More downforce without going over 15 N of drag at 25 m/s. You can change the
> angle, span, flap, and endplates. Keep the chord, mounts, and airfoil fixed.

“Darwin reads the model, confirms exactly what it may change, and simulates the
baseline. It does not hide everything inside one score: it shows induced and
profile drag, stall margin, efficiency, Reynolds number, and the constraint
that binds.”

### 0:35–1:15 — Show the investigator loop

On the first card, read the displayed hypothesis, cited principle, and
prediction before revealing the result.

“One step is one experiment. Darwin chooses a lever, explains the aerodynamic
reason, and commits to a numerical prediction before the solver runs. The
solver checks it. Code—not the language model—decides whether the result is
feasible and better.”

Reveal a rejected step.

“A rejection is useful. Darwin explains the miss from solver quantities, logs
the lesson, and changes course.”

Reveal an accepted step while the Onshape wing changes.

“An accepted step updates the Variable features in the real parametric model.
The wing morphs, the decision is recorded, and the lab notebook carries the
measured effect into the next hypothesis.”

### 1:15–1:35 — Finish the run

Fast-forward the remaining cards, then show the before/after design and the
named Onshape version.

“The result is not a black-box optimum. It is a design plus an audit trail:
what changed, what failed, what Darwin learned, and how accurate its
predictions became.”

Read only the final values visible in the completed run. Do not memorize draft
numbers.

### 1:35–1:50 — Prove the intelligence

Show the proof slide.

“We gave Darwin, CMA-ES, random search, and Darwin without its aerodynamic
knowledge the same 20-simulation budget. Here are simulations to target and the
final feasible result.”

Point to the actual result, including a loss or tie if that is what the bench
shows. The important comparison is sample efficiency; the no-knowledge
ablation tests whether the principles help rather than merely decorate the UI.

**TODO:** populate this beat only from `demo/bench_wing.json`. If that file is
not ready, compare only the available methods and say the ablation is pending.

### 1:50–2:00 — Close

“We started with aero because depth matters. The same investigator contract can
target our existing rocket-fin scorer; we will show that beat only from a
checked run. The production path is an Onshape App Store panel and a CFD adapter
for final verification. The more expensive each simulation becomes, the more
valuable a reasoned experiment is. Darwin reasons like an aerodynamicist,
inside your CAD.”

## Slide outline

1. **The bottleneck:** judgment between CAD and simulation runs.
2. **The product:** Onshape side panel plus hypothesis → prediction → test →
   analyze → decide → learn.
3. **Live demo:** rear wing, one rejection, one accepted morph, lab notebook.
4. **Proof:** matched 20-simulation budget and knowledge-layer ablation.
5. **Trust:** solver-only numbers, code-owned constraints, explicit screening
   limits, versioned and reversible writes.
6. **Path to production:** OAuth-based Onshape App Store extension, CFD/wind-
   tunnel verification adapters, team-specific rules and design templates.

## Claims discipline

- Say **screening-level aerodynamic model**, not CFD or certification.
- Say the live spike proved Variable-feature writes on a disposable fin copy;
  claim an end-to-end wing morph only after the final recording proves it.
- The checked-in `session_fixture_wing` result is synthetic rehearsal data.
- Quote benchmark results only from the checked-in `demo/bench_wing.json`.
- Read demo metrics from the screen. The values in `PLAN.md` Part F are
  illustrative, not evidence.
- If the LLM is wrong, say so: predictions are scored and acceptance is owned
  by deterministic code.

## Short judge answers

**Isn't this just an optimizer with an LLM?**  A conventional optimizer returns
points. Darwin performs explicit, physics-backed experiments, predicts before
each run, learns from misses, and leaves an auditable chain of decisions. The
matched-budget bench and no-knowledge ablation test whether that changes sample
efficiency.

**How accurate is the aero?**  It is a fast, reduced-order screening model for
ranking design moves. We expose its validity envelope and use higher-fidelity
simulation or a wind tunnel for sign-off.

**What if the model invents physics?**  Principles are cited, every prediction
is checked against solver output, numeric claims are restricted to inputs, and
code controls feasibility and acceptance.

**Why only aero?**  We chose one domain and built the reasoning loop deeply.
The investigator/solver boundary is reusable, but breadth is not the claim.

**Does it break the CAD model?**  Darwin changes only user-approved Variable
features. Writes are read back, ledgered, and bracketed by named versions so the
user can restore the earlier state.

**How is this different from an analysis agent?**  Analysis agents answer “what
happens?” Darwin decides what to try next, changes the parametric model, tests
the result, and learns from it.
