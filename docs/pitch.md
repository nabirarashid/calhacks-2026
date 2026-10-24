# Darwin: two-minute pitch v3

> This script follows `PLAN.md` A.1-A.2. Bracketed lines are gates, not claims:
> use them only after the named flow has been run and recorded. The safe fallback
> is part of the script so the pitch remains true if a checkpoint slips.

## One line

**Target product line from `PLAN.md` A.1 (use only after the onboarding and live-
write gates pass):** Darwin is an engineering-change agent for Onshape. It
onboards a parametric part, asks for the engineering inputs it must not guess,
evolves the design against validated solvers, and writes back a verified,
versioned change once an engineer approves it. And it knows when it cannot help
yet.

**Current-build line:** Darwin turns a reviewed fin-design goal into an
explainable, simulation-backed candidate and an evidence package for human
approval. Its guarded Onshape write path is not presented as live-verified, and
generic onboarding remains an integration target.

## Two-minute talk track

### 0:00-0:15 — The problem

“Changing an engineering design is a loop: edit CAD, run analysis, inspect the
tradeoffs, and repeat. Tools that claim to work on any shape can hide the most
dangerous step—guessing the physics. Darwin makes both the optimization and its
limits visible.”

Show: the title and the fin seed. Do not give a time-per-iteration or customer
quote unless it came from a named CMU Rocket Command member and is recorded
below in the Anthropic variant.

### 0:15-0:45 — Fin: one workflow done deeply

Type: “Maximize stability, keep drag low, keep all fins under 40 grams, and
stay flutter-safe.” Start the curated fin replay.

“For our reference domain, Darwin turns that request into explicit objectives,
constraints, and assumptions. Its proposer, critic, and strategist explore the
design space, while deterministic fin models—not the language model—own every
number and every pass or fail. CMA-ES and random search receive the same
evaluation budget.”

Show: the evolving fin, score curve, agent feed, baseline curves, and Pareto
tradeoff. Describe a win over a baseline only from the run currently on screen;
do not quote an uncommitted benchmark.

### 0:45-1:05 — Evidence, approval, and write authority

“A winner is not just a score. Darwin shows the parameter diff, requirement
margins, geometry status, fidelity, assumptions, limitations, and the exact
design being approved.”

- If a disposable-workspace live write has been verified and recorded, click
  **Create Onshape Version** and say: “The action was previewed, explicitly
  approved, written to an isolated workspace, read back, geometry-checked, and
  versioned.” Then show the new Onshape version.
- Otherwise say: “The write path is guarded behind exact-design approval and an
  acknowledged isolated workspace. We have not verified a live write for this
  build, so it stays out of the demo.” Show the evidence report instead.

Never describe `geometry.status != ready` or a partial write as success.

### 1:05-1:30 — Onboard a new object

- If the production onboarding wizard has passed CP8, paste the bracket URL,
  inventory it, review parameter meanings, and answer sourced material, load,
  fixture, and safety-factor questions. Say the level that the returned evidence
  actually supports.
- Otherwise show the maturity ladder and say: “The fin is the supported product
  today. The next step is a reviewed manifest for a new object. Darwin must ask
  for material, loads, fixtures, and acceptance criteria instead of inferring
  them from geometry.”

Do not present the current `DiscoveryModal` stub as safe generic onboarding.

### 1:30-1:50 — Static-structural transfer

- Only after an end-to-end bracket run and its artifacts exist, show the failed
  lightweight candidate, repair, fidelity label, convergence result, protected
  interfaces, and the exact evidence-backed outcome. Say “FEA verification”
  only if that adapter and the bracket run were actually validated; otherwise
  say “screening-level structural analysis.”
- Current fallback: “We validated a candidate quadratic-tetrahedron FEA kernel
  against a cantilever reference, but the bracket adapter and geometry pipeline
  are not integrated yet. That is solver R&D, not a shipped second domain.”

Reference if asked: [`sim/FEA_SPIKE.md`](../sim/FEA_SPIKE.md).

### 1:50-2:00 — The honesty beat

- If the capability-report flow passed CP8, show the duct at the level the UI
  returns and say: “This object needs a CFD adapter, and we deliberately did not
  build one.”
- Otherwise point to level 1 on the ladder and say: “Our product contract stops
  unsupported physics at inventory-only. The capability-report components are
  not yet connected to a production onboarding backend, so we will not
  substitute a guessed solver.”

Close: “Physics does not generalize. The guarded request-to-evidence workflow
does.”

## Slide: the support maturity ladder

| Level | Meaning | Darwin may do |
|---|---|---|
| 0 — unsupported | CAD or domain cannot be interpreted safely | Explain blockers only |
| 1 — inventory-only | Parameters and features can be inspected | Read-only inventory and draft a manifest |
| 2 — manifest-reviewed | An engineer approved semantics and required inputs | Run read-only probes and plan work |
| 3 — solver-ready | A validated adapter accepts the manifest and baseline checks pass | Simulate and optimize within approved bounds |
| 4 — write-enabled | Isolated workspace, recovery plan, and evidence gates are approved | Preview, apply, read back, verify, and create a version |

Movement is based on recorded evidence, never an LLM confidence score. In the
current repository, only the fin workflow is implemented end to end; a project
registry that assigns these levels is still planned.

## Slide: path to production — Phases 4 and 5

**Phase 4: engineering knowledge layer**

- Versioned, cited domain packs for materials, processes, standards, and solver
  guidance.
- Approved project-document ingestion with tenant isolation, deletion controls,
  and prompt-injection defenses.
- Source/version citations, conflict reporting, and evals for clarification,
  refusal, adapter choice, and failure diagnosis.
- Engineer corrections and outcomes become evaluation data before any
  fine-tuning is considered.

**Phase 5: production hardening and expansion**

- Durable and resumable jobs, retries, idempotency, and cancellation.
- Sandboxed solvers, reproducible environments, artifact validation, and
  resource limits.
- Role-based access, tenant isolation, encrypted secrets, audit export, and
  retention/model-provider controls.
- Transactional CAD recovery and concurrent-edit protection.
- CAD, solver, storage, and model ledgers with caps and cache controls.
- New domains enter only through validated adapters and reference suites; a
  second CAD provider comes only after Onshape onboarding is reliable.

## Microsoft variant: responsible by design

Lead with the fin workflow as the measurable end-to-end slice. Then show the
maturity ladder as the path from a hackathon prototype to controlled production
authority.

| Safety rule | Current evidence | Production work |
|---|---|---|
| Deterministic code owns physical truth | Solver metrics and requirement checks are deterministic; agent numeric prose is checked | Expand reviewed reference suites per adapter |
| Do not infer engineering inputs | The fin uses an explicit fixed context | Generic onboarding must block on sourced/confirmed loads, fixtures, materials, safety factors, and environment |
| Fail closed | CAD failures and missing geometry carry explicit failed/skipped states | Apply the same policy to manifests, probes, convergence, and every adapter |
| Bind evidence to exact state | Reports bind run, design, parameter hash, metrics, geometry, and approval | Add CAD microversion, manifest revision, adapter/settings versions, and source artifacts |
| Approval expires on change | Approval is checked against design ID and parameter hash | Bind the full manifest/CAD/solver state |
| Separate approval from write | Commit requires prior approval and explicit write/isolation flags | Add action preview, recovery drill, RBAC, and audited production writes |
| Simulation is not certification | Fin limitations and fidelity warnings are explicit | Standardize applicability, uncertainty, and validation labels across domains |
| Imported text is untrusted | No generic imported-CAD prompt path is shipped | Treat CAD/document text as data, schema-validate outputs, and keep prompt-injection regression tests |

Cost controls already represented in the prototype include evaluation budgets,
model-spend accounting, an Onshape ledger/reserve, and geometry caching. Do not
quote savings, dollar cost per run, or calls per run without a committed bench
artifact from the exact demo build.

## Anthropic variant: CMU Rocket Command first

Open with one workflow a named community could use, rather than a generic “AI
for engineers” claim:

“Darwin began with CMU Rocket Command’s fin-design problem: turn a reviewed goal
into candidate fins, evaluate every candidate through the same deterministic
models, and make the tradeoff and limitations inspectable. Claude is useful for
parsing intent, proposing candidates, critiquing outcomes, changing search
strategy, and explaining the evidence. Claude does not get to invent a load,
material property, metric, or pass/fail result.”

Then show the fin flow. Close with onboarding and static structures as the route
to growth, not as the headline.

### Required first-hand insert before submission

> **PLACEHOLDER — replace with 2-4 sentences written or approved by a named CMU
> Rocket Command teammate.** Include how the fin loop works today and what goes
> wrong. If using a direct quote from another member, record their permission.
> Do not invent or paraphrase a quote as though it were theirs.

Where Claude could go wrong for this community: an engineer could over-trust a
screening result; generated prose could hallucinate a physical claim; the
engineer could confirm a wrong input; or imported CAD text could contain prompt
injection. The controls are deterministic solvers and requirements, a numeric-
claim check, evidence that records confirmed inputs, explicit fidelity labels,
and—before generic onboarding ships—untrusted-text isolation and tests.

## Claim gate before presenting

- Live write: use only with a recorded disposable-workspace apply/read-back/
  geometry-check/version result.
- Bracket: use only at the maturity level supported by its committed evidence.
- FEA: the kernel spike is not an end-to-end structural adapter.
- Physical bracket: mention only after the printed pair was load-tested against
  the prediction and the result was recorded.
- Heat sink: mention only as a possible future domain unless CP10 artifacts are
  committed.
- SpacetimeDB and Factory Droid: omit unless their running-product integrations
  and fallbacks are committed and demonstrated.
