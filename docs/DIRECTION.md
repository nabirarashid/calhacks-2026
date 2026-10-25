# Darwin — direction v4 (accepted Sat Oct 24 14:40)

Status: **accepted and locked.** This file is the rationale (problem, competition, why now,
pitch, sources). **`PLAN.md` is the plan**: scope, contracts, workstreams and schedule live
there. Where they differ (e.g. §12's schedule below, written before the 14:49 morph spike),
PLAN.md wins.

---

## 0. The decision in one paragraph

Darwin is **Cursor for Onshape, for aerodynamic design.** You open your part in Onshape,
tell Darwin in plain English what you want and what it may touch, and it works the
problem the way an aerodynamicist would: it states a hypothesis and *why*, predicts
the effect, runs a real simulation, compares prediction with result, explains what
happened from the data, keeps or rejects the change, and decides what to try next.
Every accepted change is written into your parametric model, so you watch the part
morph in Onshape, and every step leaves an auditable reason. The simulator is a tool
Darwin uses, not the product. The product is the **reasoning loop**, and we prove it
on one domain, done deeply: aerodynamics.

---

## 1. What the repo actually does today

| Area | What it does now | Status |
|---|---|---|
| `shared/` | Data contracts (design space, goal, score, events), contracts v2 (project manifest), fixtures, mocks, a fake mock server | Solid |
| `sim/` | Rocket-fin physics: AeroSandbox drag, Barrowman stability, flutter, mass. Plus Nabira's structural work: analytic bracket solver, STL → tet mesh → FEA | Fin: solid. Structural: new, off-direction now |
| `backend/run_loop.py` | A **population optimizer**: each generation the LLM proposes 8 designs, all get scored, the best survives. Critic and strategist give advice. CMA-ES and random baselines run on the same budget | Works, but it's a GA with an LLM mutation operator. This is what your mentor criticized |
| `backend/agents/` | Goal parser (English → objectives/constraints), proposer, critic, strategist, reporter | Goal parser is useful as-is. The others are built for the population loop |
| `backend/evidence.py`, approval | Deterministic evidence report, exact-design approval | Useful |
| `backend/projects.py`, `domains/` | Project registry, maturity levels, domain packs | Partly over-built for a multi-domain product we're no longer building |
| `cad/` | Onshape client: auth, read configuration, **configured STL export (verified live)**, ledger, cache, guarded write + version (**mocked only, never run live**) | Read path proven. Write path unproven |
| `dashboard/` | React app: agent feed, score chart, Pareto, lineage, parallel coordinates, 3D fin, winner/evidence modal | Good parts, wrong shape for a step-by-step story |
| `demo/` | Recordings, bench (agent beats CMA-ES 6 of 9 on fin goals), print STLs | Useful as evidence |

**Honest summary:** today Darwin is a rocket-fin optimizer whose LLM proposes batches
of numbers. It works, and it's measured, but it doesn't reason step by step,
doesn't learn visibly, and doesn't touch the user's Onshape model.

---

## 2. Problem, user, why now

### The problem
Improving an aerodynamic part is a slow manual loop: change a dimension in CAD →
export → set up a simulation → wait → interpret plots → decide what to change → repeat.
The expensive part isn't the simulation. It's the *judgment between simulations*:
deciding what to try next and why. Experts do it from physics intuition; everyone
else guesses, or hands the problem to a black-box optimizer that burns hundreds of
runs and explains nothing.

### The user
Student engineering teams and small hardware teams designing aero parts in Onshape:
**Formula SAE / Formula Student aero subteams, collegiate rocketry (CMU Rocket
Command, which two of us are on), AIAA Design/Build/Fly.** Onshape is free for
students, and these teams iterate aero parts for weeks against hard rule limits.

### Why now (temporal exigence)
1. **Agents can finally do multi-step tool use reliably.** "Cursor for X" became real
   for software in 2025–26. CAD hasn't had its version yet.
2. **The CAD ecosystem is moving here right now, and nobody has closed the loop:**
   - **SimScale's Engineering AI Agent for Onshape** (launched Sep 15, 2026, IMTS) runs
     CFD/FEA from a prompt and reports in plain language. Its own launch post
     describes the workflow as *one prompt → a result*, and lists autonomously
     testing parameter variations as a future direction. It analyzes the design;
     it doesn't change it.
   - **Onshape AI Advisor** (Oct 2025) gives in-app guidance; PTC lists agent
     workflows and design optimization as roadmap items.
   - **Adam** (Onshape App Store, Mar 2026) agentically cleans up feature trees. No physics.
   - **Luminary Cloud** brings physics-AI surrogates (e.g. SHIFT-SUV, SHIFT-Wing)
     to Onshape, but they require large upfront training runs per product family.
3. **Simulation is getting cheap; judgment isn't.** NeuralFoil runs airfoil analysis
   8–1,000× faster than XFoil at comparable accuracy. As compute stops being the
   bottleneck, *deciding what to try next* becomes the bottleneck, and that's
   what Darwin automates and explains.

### Comparison

| | Changes your design | Uses real simulation | Explains each decision | Works in your parametric model |
|---|---|---|---|---|
| OpenRocket / XFLR5 (manual tools) | You do | Yes | No | No |
| Fusion generative design / nTop / optiSLang | Yes, black-box | Yes, hundreds of runs | No | Mostly new geometry |
| SimScale Onshape agent | No (analysis) | Yes | Results, not design moves | Reads it |
| Adam / Onshape AI Advisor | Adam edits structure; Advisor advises | No | Partly | Yes |
| **Darwin** | **Yes, step by step** | **Yes, every step** | **Yes, hypothesis → prediction → result** | **Yes, edits it live** |

---

## 3. What Darwin is (and isn't)

- **Is:** an agent in a side panel next to your Onshape model that runs a hypothesis-
  driven design loop on your existing parametric part, writes accepted changes into
  the model, and narrates its reasoning with numbers from the solver.
- **Isn't:** a rocket-fin optimizer, a worse OpenRocket, a text-to-CAD generator, or a
  universal multi-physics tool. One domain, deep.
- **The pitch line:** *"Engineers don't grid-search. They reason. Darwin reasons like an
  aerodynamicist inside your CAD, so it needs fewer simulations and shows its work."*
- **The prompt doesn't have to be optimization.** "Make the wing 10% narrower and keep
  the downforce" or "why is this draggy?" use the same loop with a smaller goal.

---

## 4. The smart loop (the core, replaces the population loop as the main mode)

Each **step** is one small experiment, shown as a card:

1. **Understand.** Read the model's parameters from Onshape. Parse the prompt: the goal,
   what may change (the user names it), everything else held fixed. Simulate the
   baseline and show a **physics breakdown**, not just a score: downforce, drag split
   into induced vs profile, stall margin (CL vs CL_max), span efficiency, Reynolds
   number, and which constraint binds.
2. **Hypothesize.** Pick *one* lever and say why, citing a principle from the knowledge
   layer: *"Induced drag is 64% of total drag, and induced drag ∝ CL²/(π·e·AR), so
   widening the span to the rule limit should cut drag ~15% at the same downforce."*
3. **Predict.** A direction and a rough magnitude for each affected metric, recorded
   before the run.
4. **Test.** Run a small designed experiment: 1–4 simulations, e.g. a short sweep of
   that lever. About 30 ms each on our solver, so a sweep is effectively instant.
5. **Analyze.** Compare prediction with result using only solver numbers (the
   numeric-claim check stays). Explain any surprise from the breakdown: *"Drag fell
   less than predicted because profile drag rose with the extra wetted area."*
6. **Decide.** Accept, which writes the change to Onshape so the model morphs and logs
   it. Or reject, which is fine and gets logged as a lesson. Or pivot to a new
   hypothesis.
7. **Learn.** Update the **lab notebook**: beliefs ("this airfoil stalls past ~13° at
   Re 5×10⁵"), levers ranked by measured effect, ideas ruled out. The next
   hypothesis must use it.

**Showing that it learns, measurably:** every prediction is scored against its result.
The panel shows prediction accuracy rising over the run, and the belief list growing.
That's real, checkable learning, not decoration.

**Stopping:** goal met, no lever left that the notebook predicts will help, or the
simulation budget is spent. Then a final summary: what changed, why, what failed, and
a named Onshape version.

**Your mentor's "expand the measurements" point, applied correctly:** expand the
*diagnostic* quantities the agent reasons over (drag breakdown, stall margin,
efficiency, Re, binding constraint). Don't expand the number of objectives being
summed into one score.

---

## 5. Scope and hero object: a race-car rear wing

**Recommendation: the hero is an FSAE-style rear wing.** It gives you the "car with
restrictions" story you described: *keep the mounting points and endplates, stay under
the height and width limits, stay under X N of drag at 25 m/s*. Darwin may change
angle of attack, span, chord, taper, flap angle and gap, and endplate height.

**Why a wing, not a whole car body (yet):** a car body's drag needs real CFD, which is
minutes to hours per run on a laptop and too fragile to build in 15 hours.
Lifting-surface aero has a fast, validated solver we already run (AeroSandbox
AeroBuildup and VLM with NeuralFoil airfoil polars). The prototype above: about
30 ms per evaluation, with the induced/profile drag split. **The pitch turns this into
a strength:** the loop is solver-agnostic, and the more expensive each simulation gets
(CFD, SimScale, Luminary), the more a smart agent's sample efficiency is worth.

**The rocket fin stays as the second aero part:** same agent, different part, no code
changes. That's one 10-second beat proving it isn't hard-coded, plus our origin story
(CMU Rocket Command). It is not the headline.

**Out of scope, parked:** structural (bracket and FEA), thermal (heat sink), the duct,
the maturity-ladder UI, and multi-domain onboarding.

---

## 6. The aero knowledge layer

`domains/aero/principles.md`: about 25–35 curated, cited principles, each with an id,
when it applies, the expected direction of effect on each metric, a typical magnitude,
and a source. Examples:
- induced drag vs aspect ratio and span efficiency
- lift-curve slope and stall vs Reynolds number
- endplates raising effective aspect ratio
- the camber vs profile drag tradeoff
- flap gap and slot effects
- taper and near-elliptic loading
- downforce scaling with dynamic pressure

Sources: Anderson *Fundamentals of Aerodynamics*, Katz *Race Car Aerodynamics*,
McBeath *Competition Car Aerodynamics*, Hoerner, the NeuralFoil paper.

- Small enough to put in the prompt whole. No vector database needed.
- Every hypothesis must cite a principle id, or be marked "exploratory".
- **Ablation for the judges:** the same agent with the knowledge layer removed. If the
  layer matters, the agent without it needs more simulations. That's a slide.

Model choice: the hypothesis and analysis steps are where intelligence matters, so they
use the stronger model; parsing uses the fast one. (Update, Sat evening: the default
provider is now DeepSeek, `deepseek-v4-pro` / `deepseek-flash`, after the Claude budget ran
out; Claude is still supported. See PLAN.md B.9.) Use replay for rehearsals.

---

## 7. Onshape integration: what works, what doesn't, the plan

| Capability | Status |
|---|---|
| API keys, auth, reading configuration inputs | **Works live** (verified today) |
| Configured STL export (regenerate geometry for given values, no write) | **Works live**: 12 calls per run in today's runs |
| Writing values into the document, so the open tab visibly changes | **Never tested live.** Code exists (update configuration → read back → verify → version) under mocks only |
| Named versions | Code exists, mocked |
| UI inside Onshape | None yet |

**Priority 1 (W-A, by 15:00): the morph spike** on a throwaway copy. Does an API write
make an *open* Onshape tab visibly change within about 2 seconds? Try, in order:
(a) the existing configuration update, (b) updating a Variable feature's value via
feature update, (c) the Variable Studio API (forum reports of internal errors make
this the last resort). Record which works, the latency, and the calls per write. This
decides whether the "watch it morph" moment is real or replay-only.

**The UI: a Chrome extension side panel on cad.onshape.com** (Side Panel API, Manifest V3).
- It reads the document/workspace/element IDs from the active tab's URL and loads a
  compact route of our existing dashboard. The backend holds the API keys.
- This is fastest to build: no OAuth app registration.
- The native Onshape App Store extension (right-panel iframe plus OAuth, as SimScale
  and Adam do) is the production path and goes on the "path to production" slide.

**Safety:**
1. Create a version "before Darwin" first.
2. Write only accepted steps.
3. Create a version "after Darwin" at the end.

A restore is one click in Onshape history. Each accepted step costs about 1–2 API
calls, and the 1–4 simulations per step cost **zero** Onshape calls, because the wing
geometry is analytic from the parameters.

---

## 8. The demo (2 minutes)

| Time | Beat |
|---|---|
| 0:00 | **Problem** (one sentence plus one image): the edit → simulate → interpret loop, and the judgment between runs is the slow part. |
| 0:15 | **Onshape, rear wing open, Darwin side panel.** Type: *"More downforce without going over 20 N of drag at 25 m/s. You can change the angle, span and flap. Keep the mounts and endplates."* Darwin lists what it will change and what stays fixed, and runs the baseline breakdown. |
| 0:35 | **Step 1 card:** "Raise angle 6°→10°, because downforce ∝ CL and we have stall margin. Predict +30% downforce, +25% drag." Simulates; the wing tilts in Onshape. "Downforce +34%, drag +41%: more than predicted, because induced drag ∝ CL². Over budget. Rejected, but I learned drag is binding and mostly induced." |
| 0:55 | **Step 2 card:** "Attack induced drag: widen span to the limit (∝ 1/AR)." Accepted; the wing widens in Onshape. Prediction accuracy ticks up. |
| 1:15 | **Steps 3–5** in fast-forward. Final: +22% downforce at equal drag. Before/after morph. Named version created in Onshape. |
| 1:35 | **Proof slide:** same 20-simulation budget. Darwin vs CMA-ES vs random vs *Darwin without the knowledge layer*. Sims-to-target and final result. |
| 1:50 | **Close:** "Same agent on our rocket fin, no code changes. Swap in CFD and it gets *more* valuable. Darwin reasons like an aerodynamicist, inside your CAD." |

Fallback: a recorded run, replayed in the same panel, plus a video.

---

## 9. Pitch: what convinces the judges

- **Worth solving:** every hardware team does this loop. The cost is weeks of an
  engineer's judgment, not compute. The industry leaders shipped agents that
  *analyze* in the last month; none *improve the design* yet.
- **Solved well:**
  1. It edits the real parametric model.
  2. Every decision has a reason, a prediction, and a measured outcome.
  3. It's measurably more sample-efficient than a classic optimizer, and the
     ablation shows *why*: the physics knowledge.
- **Honest about limits:** screening-level aero, labeled. Numbers only from the solver.
  Writes are versioned and reversible.

**Likely judge questions:**
- *"Isn't this just an optimizer with an LLM?"* No. An optimizer needs hundreds of
  runs and gives no reasons. Here's the ablation, and here's the reasoning trail.
- *"How accurate is the aero?"* AeroBuildup/VLM with NeuralFoil, validated against
  XFoil within a few percent (cite the paper). Fine for ranking design moves; final
  sign-off is CFD or a wind tunnel, which the loop can call.
- *"What if the LLM's physics is wrong?"* Its predictions are tested every step, and
  its accuracy is on screen. When it's wrong, it says so and adapts.
- *"Why only aero?"* Depth over breadth. The loop is domain-agnostic; aero is where we
  could make it genuinely smart this weekend.
- *"SimScale already has an Onshape agent."* It runs a simulation and tells you the
  answer. Darwin decides what to change, changes it, and learns.

---

## 10. Sponsor tracks under this direction

| Track | Status | Why |
|---|---|---|
| Overall / Most Technically Complex | In | A reasoning loop + live CAD + solver + measured ablation |
| **Microsoft: Built for the Real World** | **In, primary** | Production-minded agent: customer (aero teams), measurable usefulness (sims-to-target), path to production (Onshape App Store, CFD adapter), responsible design (versioned writes, numbers from the solver) |
| **Anthropic** | **In** | Named community: collegiate aero teams, starting with CMU Rocket Command (lived problem). Claude *is* the reasoning; we show where it fails and how predictions catch it |
| Factory Droid | **Drop** | Its use case was drafting adapters for many domains, which we no longer do |
| SpacetimeDB | **Drop** | Not core |
| Cartesia, Meta, SpaceXAI, Hyphenate | Out | Unchanged |

---

## 11. Keep / change / park

**Keep (core of v4):**
- contracts and events, the bus, recordings and replay
- the server, `llm.py` (budgets, cache, fallback), the numeric-claim check
- goal parser, evidence and approval
- Onshape client, ledger, cache
- AeroSandbox aero code and the fin model
- baselines plus `bench.py` (for the proof slide)
- dashboard pieces: agent feed, charts, evidence modal, 3D viewer

**Change:**
- **New `backend/investigator.py`:** the hypothesis loop above, plus the lab notebook
  and prediction scoring. It becomes the main mode; the population loop stays as a
  baseline engine.
- **New `sim/plugins/rear_wing_v1.py`** with diagnostics.
- **New `domains/aero/principles.md`.**
- **New rear-wing Part Studio** with configuration/variable inputs and fixed mount and
  endplate geometry.
- **Onshape writes per accepted step,** plus before/after versions.
- **Chrome extension side panel,** and a "step card" timeline view in the dashboard.
- **Enforce fixed parameters** in the loop (Nabira flagged that `ParamSemantics.role`
  is currently ignored).

**Park (stop work, don't delete yet; deleting costs time and risks breakage):**
- structural adapter and FEA (`sim/adapters/structural_analytic_v1.py`, `sim/fea*`)
- bracket, heat sink and duct fixtures
- maturity-ladder UI, onboarding wizard, capability reports
- Factory Droid, SpacetimeDB, Phases 4–5

Hard news for Nabira: her FEA work is good, but it's off-direction. Her aero skills
are exactly what the rear-wing solver and the knowledge layer need.

---

## 12. Plan to the 05:00 cutoff (about 15 hours)

| Owner | First (by 15:00) | By 18:00 | By 21:30 | By 01:00 |
|---|---|---|---|---|
| **W-A CAD** | **Onshape morph spike** (§7) | Rear-wing Part Studio; apply-step + version functions | Morphing works end to end from the backend | Fin path on the same functions; recordings |
| **W-B Aero** | Stop FEA. Rear-wing solver skeleton | `rear_wing_v1` with diagnostics and golden tests (lifting-line, NeuralFoil vs XFoil) | Knowledge layer with W-C | Validation table for the pitch |
| **W-C Agent** | Investigator loop design + notebook contract | Investigator end to end in the terminal on the wing (no CAD) | Wired to Onshape writes and the panel | Bench: Darwin vs CMA-ES vs random vs no-knowledge |
| **W-D UI/story** | Extension skeleton showing the dashboard in the side panel | Step-card timeline + prediction-accuracy chart (against a recorded fixture) | Live in the panel | Pitch, Devpost, video |

**Checkpoints:**
- **15:00** — morph spike verdict
- **18:00** — terminal loop works on the wing
- **21:30** — full loop in Onshape
- **01:00** — proof slide data and recordings
- **02:30** — rehearsal
- **05:00** — cutoff

---

## 13. Top risks

| Risk | Mitigation |
|---|---|
| API writes don't visibly update the open tab | Spike first. Fallback: show the configured-export STL morphing in the panel's 3D view, and write once at the end |
| Airfoil shape is hard to parameterize in Onshape | Fixed airfoil profile; vary angle, span, chord, taper, flap angle, endplates |
| LLM cost | DeepSeek by default (cents per run); replay for rehearsals |
| Agent explanations sound right but are wrong | Predictions are scored against the solver every step; numeric-claim check; principles cited |
| Scope creep again | This document is the scope. Anything not in §8 waits until after 01:00 |

---

## 14. Decisions needed now

1. Accept the direction (aero only, the reasoning loop as the product)?
2. Hero object: FSAE-style rear wing (recommended), or something else in aero?
3. OK to park structural/FEA and tell Nabira?
4. OK to drop Factory Droid and SpacetimeDB?
5. Who owns which workstream, now that the work has changed?

---

### Sources
- SimScale, "SimScale's Engineering AI is live inside Onshape" and the launch press release (Sep 2026): simscale.com/blog/simscales-engineering-ai-is-live-inside-onshape/ · simscale.com/press/simscale-launches-engineering-ai-agent-for-onshape/
- PTC, Onshape AI Advisor release (Oct 2025): ptc.com/en/news/2025/ptc-announces-latest-Onshape-AI-advisor-release
- Onshape, "Adam AI tackles feature tree cleanup": onshape.com/en/blog/adam-ai-app-store-cad-co-pilot
- Onshape partner post on SimScale, Luminary Cloud, Leo AI, Adam: onshape.com/en/blog/cloud-native-cad-partners-simscale-luminary-cloud-leo-adam-ai
- Luminary Cloud × Onshape: luminary.ai/resources/luminary-cloud-launches-integration-with-onshape-by-ptc-to-accelerate-physics-ai-workflows/
- Sharpe & Hansman, *NeuralFoil* (2025), arXiv:2503.16323
- Liu et al., *Large Language Models to Enhance Bayesian Optimization* (LLAMBO, ICLR 2024), arXiv:2402.03921
- Chrome Side Panel API: developer.chrome.com, Extensions reference, "chrome.sidePanel"
- Onshape extensions (OAuth app → Extensions tab): cad.onshape.com/help/Content/Plans/my_account_developer.htm
- FSAE aero device limits (2017 T7 text; check the current rulebook): formulastudent.de/uploads/media/Rules2017_T7_V1.01.pdf
