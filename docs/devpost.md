# Devpost copy

> Submission draft: the product description below is the accepted v4 scope.
> Keep the evidence checklist until the final wing recording and proof bench
> have landed; disclose or remove any capability they do not demonstrate.

## Inspiration

Student engineering teams spend weeks in the same loop: change a dimension in
CAD, export the part, configure a simulation, inspect the plots, and decide what
to change next. Faster solvers help, but they do not remove the hardest part:
the judgment between runs.

We know that problem from collegiate rocketry, and it is just as visible on
Formula SAE aero teams. A black-box optimizer can consume hundreds of
evaluations and return a design without explaining why it works. We wanted an
agent that behaves more like an aerodynamicist: form a hypothesis, predict the
effect, test it, learn from the result, and leave the engineer in control.

## What it does

Darwin is **Cursor for Onshape, for aerodynamic design**. The user opens a
parametric part, describes the goal in plain English, and names the parameters
Darwin may change. Darwin reads the current model and runs a sequence of small
experiments:

1. choose one or two editable levers and cite an applicable aero principle;
2. predict a direction and numerical range for each affected metric;
3. simulate one to four candidate settings;
4. compare prediction with measured solver output;
5. let deterministic code accept, reject, or pivot; and
6. update the model and lab notebook before choosing the next experiment.

The side panel shows the full reasoning trail: hypotheses, predictions versus
actuals, induced/profile drag, stall margin, span efficiency, the binding
constraint, accepted and rejected steps, ruled-out ideas, and running
prediction accuracy. Accepted steps update Onshape Variable features, so the
engineer can watch the model change. The run ends with a before/after summary
and versioned CAD state.

Our hero is an FSAE-style rear wing: increase downforce under a drag limit while
preserving the mounts, airfoil, and other fixed geometry. Our existing rocket-
fin scorer is the second aero example and the project's origin story.

## How we built it

- A FastAPI service exposes inspection and session routes and streams an
  ordered event log over WebSockets. The same events drive live sessions and
  deterministic replay.
- The investigator separates language-model judgment from deterministic
  control. The model proposes and explains experiments; code validates editable
  parameters and bounds, scores predictions, checks constraints, and decides
  acceptance.
- A compact aero knowledge pack supplies cited principles such as induced drag
  versus aspect ratio, flap/camber tradeoffs, and stall behavior. Removing that
  pack is an explicit benchmark ablation.
- The rear-wing contract exposes angle of attack, span, chord, flap angle,
  flap-chord fraction, and endplate height, together with diagnostic quantities
  the agent can reason over.
- Guarded Onshape calls find Variable features by name, update only approved
  values, read them back, ledger every request, and create before/after versions.
- React and TypeScript fold live and replay events through the same reducer. The
  Chrome Manifest V3 extension hosts the compact panel beside `cad.onshape.com`.
- A fixture-backed server provides a complete six-step session so the panel and
  demo remain testable without credentials, Wi-Fi, an LLM, or CAD access.

## Challenges

### Making the agent reason instead of narrate

Our first system was a population optimizer with an LLM mutation operator. It
worked, but the model did not visibly learn and the result was hard to
distinguish from a conventional search. We redesigned the product around one
hypothesis per step, a prediction recorded before simulation, and a notebook
that the next hypothesis must use.

### Keeping claims grounded

Engineering prose can sound convincing even when it is wrong. Solver data is
the only source for numerical claims, prediction accuracy is computed by code,
and the language model never decides whether a candidate is feasible. Rejected
steps stay visible because a useful failed experiment is part of the evidence.

### Editing the model the engineer is actually viewing

Changing an Onshape configuration did not update an already-open tab. A live
spike showed that updating the underlying Variable feature does: the disposable
fin model regenerated in the open viewer without refresh, with a 0.47-second
observed write. That result changed our integration design.

### Building a demo that fails honestly

The same event contract supports a real session, backend replay, and a fully
local fixture. The interface labels its source instead of pretending replayed
or mock results are live.

## Accomplishments

- Defined an auditable hypothesis → prediction → simulation → decision →
  learning protocol with mirrored Python and TypeScript contracts.
- Built a deterministic six-step rear-wing fixture containing accepted,
  rejected, and pivoted experiments plus a growing lab notebook.
- Proved the Onshape Variable-feature write mechanism in a live disposable
  document and preserved configured STL export for read-only geometry checks.
- Kept parameter permissions, physical constraints, API-call budgets, and model
  spend explicit rather than hiding them behind the agent.
- Preserved the earlier rocket-fin solver, recordings, and matched-budget
  baselines as a second aero example and comparison infrastructure.
- **TODO before submission:** add the checked-in end-to-end wing recording and
  name whether CAD writes and before/after versions completed successfully.
- **TODO before submission:** summarize `demo/bench_wing.json` exactly—goals,
  seeds, 20-simulation budget, simulations to target, final feasible result, and
  the knowledge-off ablation. Do not turn a tie or loss into a win.

## What we learned

The strongest division of labor is not “AI does everything.” Language models
are useful for choosing the next informative experiment and explaining a
surprise. Deterministic software should own units, bounds, constraints,
simulation, acceptance, and numeric verification.

We also learned that prediction is a powerful interface. Asking the agent to
commit before seeing the answer makes its reasoning falsifiable and gives the
engineer a concrete way to judge whether it is learning.

Finally, CAD integration is more than generating a mesh. Engineers care about
their editable model, feature history, and ability to undo. Updating a small,
approved set of parameters in place is both more useful and safer than
replacing the part with generated geometry.

## What's next

The hackathon build uses a Chrome side panel and local backend. The production
path is an OAuth-based Onshape App Store extension with team accounts,
permissions, durable run history, and review/approval controls.

The current aerodynamic model is for rapid design screening, not certification.
Next we would add adapters for CFD and wind-tunnel data so Darwin can use a fast
model to choose experiments and a higher-fidelity tool to verify finalists. We
would also calibrate models to each team's vehicle and rules, then expand from
rear wings and rocket fins to other aerodynamic components only after the loop
is validated deeply in this domain.

## Evidence to verify before publishing

- [ ] Replace both benchmark TODOs with results from `demo/bench_wing.json`.
- [ ] Link or name the final scrubbed wing recording; label replay footage.
- [ ] Confirm the final run created both Onshape versions and had zero failed
      writes before claiming the complete live loop.
- [ ] Copy validation wording from the final rear-wing section of
      `sim/PHYSICS.md`; never call the screening solver CFD.
- [ ] Remove this checklist from the submitted Devpost after every item is
      either evidenced or explicitly disclosed as incomplete.
