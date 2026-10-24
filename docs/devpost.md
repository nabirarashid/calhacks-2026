# Devpost copy v3

> Submission editor: delete this note before posting. This draft distinguishes
> repository-backed functionality from the weekend roadmap. Replace every
> placeholder with verified evidence or remove it.

## Inspiration

CMU Rocket Command and other collegiate rocketry teams face a coupled design
problem: a fin change can improve one objective while worsening drag, mass, or
flutter margin. The difficult part is not producing one feasible shape. It is
making a repeatable trade study, understanding why a candidate won, and keeping
the analysis assumptions attached to the CAD change.

**First-hand community evidence:** [PLACEHOLDER: add 2-4 sentences written or
approved by a named CMU Rocket Command teammate. Do not invent a quote, duration,
or pain metric.]

## What it does

Darwin is an engineering-change prototype for a supported parametric Onshape
project. In the implemented fin workflow, a plain-language goal becomes
reviewable objectives, constraints, and assumptions. Agent roles propose and
critique candidates and change search strategy; deterministic software computes
the engineering metrics and requirement results. The dashboard shows evolving
geometry, matched-evaluation-budget CMA-ES and random baselines, Pareto
tradeoffs, lineage, budget use, degradation state, and evidence for the winning
design.

Darwin is deliberately not “physics for any shape.” The product direction uses
a five-level maturity ladder. A new object may be inventoried before it is
allowed to simulate; simulation requires a validated domain adapter; write
authority additionally requires an isolated workspace, exact-state approval,
read-back, verification, and recovery. Unsupported physics should produce a
capability report instead of a plausible answer.

## What is implemented in this repository

| Area | Status |
|---|---|
| Rocket-fin optimization | Implemented: deterministic fin scorer, agent loop, matched-budget baselines, Pareto/lineage views, high-fidelity aerodynamic cross-check, replay |
| Evidence and approval | Implemented: deterministic parameter/metric diffs, requirement margins, limitations, exact design ID/parameter-hash approval |
| Onshape read path | Implemented with cache, call ledger/reserve, configuration-driven STL export, and geometry sanity checks; live use requires local credentials |
| Onshape write path | Guarded code and tests exist for isolated-workspace apply, read-back, geometry verification, and version creation; **a live successful write is not evidenced in the repository snapshot, so this draft does not claim one** |
| Generic onboarding and capability reports | Dashboard wizard/report components and fixture tests exist; the production backend and end-to-end integration are not complete, and the real discovery method is still a stub |
| Static structures | R&D only: the FEA spike validates quadratic tetrahedra on a cantilever case; no integrated bracket domain adapter or end-to-end bracket result is claimed |
| Heat sink, physical bracket, Factory Droid, SpacetimeDB | Not claimed; include only if a later committed build contains the working integration and demo evidence |

## How we built it

- FastAPI orchestrates runs, streams events over WebSocket, records ordered
  JSONL, and replays the same event format offline.
- Proposer, critic, strategist, goal-parser, and reporter roles share one
  budgeted model adapter with mock/replay degradation paths.
- Deterministic fin code combines Barrowman stability, analytic mass, a
  flutter-screening estimate, and aerodynamic evaluation/cross-checks. The LLM
  does not supply engineering numbers or requirement results.
- The scorer registry, run loop, CAD boundary, and event contracts separate
  search/orchestration from domain physics, although the current application
  still contains fin-specific wiring that the platform-extraction phase is
  intended to remove.
- React folds live WebSocket and offline replay events through one reducer.
  Three.js, Recharts, and custom SVG views render the fin, score history,
  Pareto landscape, lineage, and parallel coordinates.
- Onshape access is cached and metered. CAD regeneration returns explicit
  ready, failed, skipped, or pending state so a missing service cannot silently
  become a successful geometry claim.

## Challenges

The hardest implemented problem was keeping three fin representations
consistent: deterministic physics geometry, the Onshape Part Studio, and a
smooth browser mesh. We froze a geometry contract, added volume and bounding-
box checks, and used a fixed preview topology so UI morphing does not depend on
STL topology.

The deeper product challenge is authority. An optimization score is not
permission to modify CAD, and an LLM description is not engineering evidence.
We separated deterministic results from explanatory prose, bound approval to
the exact candidate, surfaced degradations, and designed the next architecture
around explicit maturity levels.

The structural spike also exposed a useful failure mode: linear tetrahedra can
converge smoothly while remaining too stiff in bending. That result informed the
planned quadratic-tetrahedron adapter, but it is not presented as bracket
verification. See [`sim/FEA_SPIKE.md`](../sim/FEA_SPIKE.md).

## Accomplishments

- A replayable fin optimization flow with agent, CMA-ES, and random search on
  equal evaluation budgets.
- Explainable winner review with parameter changes, deterministic requirement
  margins, geometry status, a correction sequence, and an engineering report.
- Live, backend-replay, and browser-local fixture paths built around the same
  ordered event contract.
- Explicit CAD and model budgets, cache behavior, and visible fallbacks.
- A guarded approval-before-write implementation whose unverified live state is
  stated plainly instead of being hidden in a demo claim.

## Responsible design — Microsoft “Built for the Real World”

Darwin’s production story is controlled authority, not unrestricted autonomy:

1. Solvers and deterministic code own units, arithmetic, metrics, and pass/fail;
   Claude parses intent, proposes strategies, and explains.
2. Materials, loads, fixtures, contacts, safety factors, and operating context
   must come from a source or engineer confirmation in the generic workflow.
3. Missing inputs, stale state, non-convergence, or geometry mismatch block the
   operation rather than fabricate success.
4. Evidence is being expanded from the current run/design/parameter binding to
   include CAD microversion, manifest revision, adapter version/settings, and
   source artifacts.
5. Approval is exact and expires when the approved candidate changes.
6. Write is a separate action, limited to an acknowledged isolated workspace,
   with read-back, geometry verification, and version creation.
7. Fidelity and applicability are labels, and simulation is never presented as
   certification.
8. Generic CAD and document text will be handled as untrusted data, with
   schema validation and prompt-injection regression tests before that input
   reaches an agent.

Existing cost-control patterns include evaluation budgets, a model-spend
ledger/cap, an Onshape call ledger/reserve, geometry caching, and offline replay.
**Measurable-usefulness placeholder:** [insert only committed results from
`demo/bench.json`: evaluations to target, run cost/calls, and—only if an
end-to-end bracket exists—mass at equal safety factor. Otherwise remove.]

## How we use Claude — Anthropic

The headline is one named community and one implemented workflow: CMU Rocket
Command using Darwin to explore a fin design under explicit constraints. Claude
is used where language and strategy help: parsing a request into a reviewable
goal, proposing candidate parameters, critiquing deterministic outcomes,
adjusting search behavior, and summarizing the evidence. Mock and replay modes
keep the system usable and inspectable without presenting cached text as a live
model response.

The failure boundary matters as much as the successful flow. Claude could write
convincing but unsupported physics prose, a user could provide the wrong input,
or imported CAD text could attempt prompt injection. Numeric-claim checking,
deterministic solvers and requirements, visible assumptions/fidelity, evidence-
bound inputs, and the planned untrusted-text boundary address those risks.

**Anthropic evidence placeholder:** [insert the approved CMU Rocket Command
first-hand statement and the measured Claude cost per run, if recorded. Do not
invent a quote or number.]

## What we learned

Agentic engineering works best when the model chooses hypotheses and search
behavior while deterministic software owns units, constraints, scores, and
numeric claims. We also learned that a useful general system must distinguish a
new object from a new physics domain: onboarding can be generic, but physics
requires a validated adapter and a declared applicability envelope.

Fallbacks are product features. A judge and an engineer should always know
whether they are seeing live agents, cached CAD, rule-based proposals, or a
recording—and whether a result is screening evidence, a validated check, or
unsupported.

## What’s next

**Phase 4 — engineering knowledge layer:** versioned and cited domain packs;
approved project-document ingestion; source/version citations and conflict
handling; evals for extraction, clarification, refusal, adapter selection, and
diagnosis; and engineer corrections as evaluation data.

**Phase 5 — production hardening:** durable/resumable jobs; sandboxed solvers;
reproducible artifacts; role-based access and tenant isolation; audit, secrets,
retention, and provider controls; transactional CAD recovery; concurrent-edit
protection; and cost limits for CAD, compute, storage, and models.

New domains will enter only through an adapter validation suite. Onshape remains
the only CAD target until its onboarding and recovery flow is reliable.

## Submission checks

- Opt into Microsoft and Anthropic only with the evidence above completed.
- Opt into Factory only if Droid does real work in the running product and the
  repo shows its sandbox, allowlist, streamed work, tests, and manual promotion.
- Opt into SpacetimeDB only if it is a core live backend in the submitted build.
- Opt into Best Hardware only if a physical bracket pair was printed and
  load-tested against a recorded prediction.
- Never describe the FEA spike as an integrated bracket result.
