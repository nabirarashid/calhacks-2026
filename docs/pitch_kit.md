# Darwin — pitch kit: run of show, Canva plan, judge Q&A (PLAN.md D4; complements Shaun's docs/pitch.md)

Every number here was measured on Sat Oct 24. Sources are in brackets. Don't round them up,
and don't add claims that aren't here.

## The numbers to say out loud

| Claim | Number | Source |
|---|---|---|
| Live wing session, real Onshape | Downforce **98 → 139 N (+41%)**, drag 13.9 N (limit 15) | `demo/recordings/session_1925_d20d.jsonl` |
| Its speed and cost | 7 steps in **128 s**, **$0.019** of LLM | same |
| Its writes | 5 accepted steps written to Onshape; versions "Before Darwin" and "Darwin: downforce +41%" | same |
| Proof bench, same 20-simulation budget | Darwin beats CMA-ES and random search **on all 3 goals** (median) | `demo/bench_wing.json`, chart `demo/bench_wing_*.png` |
| Reaching 95% of the best known design | Darwin **8 of 9 runs**, CMA-ES **1 of 9**, random **0 of 9** | same |
| Speed to 95% | Darwin median **4–11 simulations**; CMA-ES 19 (the one run that made it) | same |
| Knowledge layer | 34 aero principles, 29 checked against the solver | `domains/aero/` |
| Principles ablation | Same agent without principles: ties on the easy goal, falls behind on the two harder ones (span locked 94.9% vs 99.3%; min drag 90.2% vs 97.0%) | bench |

Be honest about one thing if asked: the bench used Claude **Sonnet** 5.5. The live demo runs Claude
**Haiku** 5.5, which is cheaper and was fast enough for every step.

## Feedback on the outline

1. **Lead with the customer, not with "temporal exigence."** Microsoft scores customer
   understanding first. Say who it's for and what hurts in one sentence. A student aero team
   (FSAE) iterates a rear wing through CAD edit → simulation → judgment by hand, for weeks. Give
   the research-papers collage 10 seconds at most, or cut it. Judges have seen "AI is topical."
2. **Start the live session in the first 15 seconds.** A full session takes about 2 minutes, which
   is your whole demo. Have the prompt typed in advance, click Run early, and narrate over it. If it
   finishes before you do, the after state in Onshape is your closing visual.
3. **Don't say "we're better than Leo."** Some judges may know Leo, and a comparison invites a fight
   you can't win in 2 minutes. Say what's different. CAD copilots generate or edit geometry. Darwin
   tests every change against physics *before* it touches your model. It predicts the result, the
   solver checks the prediction, code accepts or rejects, and every number it tells you came from
   the solver. Keep it one sentence.
4. **Point at a rejected step during the demo.** It's the most convincing moment. Darwin predicted
   something, the solver disagreed, code rejected the change, and the notebook learned from it.
   In the recorded session: "Raising angle from 6 to 7.5° cut downforce 1.2%, the opposite of the
   prediction… rejected." That's the "it's not just guessing" proof.
5. **The engineering cycle is your best visual.** Put the loop diagram on the slide that stays up
   during the demo: *hypothesize (cite a principle) → predict → simulate → score the prediction →
   explain from solver numbers → accept or reject → learn.*
6. **Tech stack: one slide, one diagram, 10 seconds.** Detail goes in Q&A.
7. **End with the proof chart and one sentence on production.** Don't end on the tech stack.

## Run of show (2:00)

| Time | Screen 1 (Onshape + panel) | Screen 2 (Canva) | Say |
|---|---|---|---|
| 0:00 | Wing at baseline, prompt typed | Title | "Student aero teams spend weeks hand-iterating a rear wing: change the CAD, run a simulation, decide what to try next." |
| 0:12 | **Click Run** | The loop | "Darwin does that loop inside Onshape. I asked for max downforce under 15 newtons of drag." |
| 0:20 | First hypothesis appears | The loop | "Each step is a hypothesis that cites an aero principle and predicts the result before simulating." |
| 0:40 | First morph in Onshape | The loop | "The solver confirms it, code accepts it, and the wing in Onshape changes. That's a real write, versioned." |
| 1:00 | A rejected step | The loop | "Here it predicted more downforce, the solver said less, so code rejected it and it learned. Every number it says comes from the solver." |
| 1:20 | Session finishing | Proof chart | "Same 20-simulation budget against CMA-ES and random search: Darwin wins all three goals and reached 95% of the best design in 8 of 9 runs. CMA-ES did once." |
| 1:40 | Final wing, versions | Production | "It never invents numbers, never writes without a version, and refuses what it can't measure. Next: Onshape App Store, a CFD adapter, more physics domains." |
| 1:55 | — | Title | "Darwin. Thanks." |

Rehearse twice with a timer. Each rehearsal on the live wing costs ~31 Onshape calls and ~$0.02.
Run `make reset-wing PY=~/.venvs/darwin/bin/python` between runs.

## Canva deck (6 slides + backups)

1. **Title.** Darwin: an engineering agent inside Onshape. Tagline: "It tests every change against
   physics before it touches your model."
2. **Problem and customer.** A student aero team's week, as one line of icons:
   CAD edit → simulation → judgment → repeat. Who: FSAE/Formula Student aero subteams.
3. **The loop** (stays up during the demo). A seven-step circle. Highlight "predict" and
   "score" in a different color, because that's what makes it not a guesser.
4. **Proof.** Use `demo/bench_wing_dark.png` or `_light.png`, whichever matches the deck. Add one big
   callout: "8/9 vs 1/9 runs reach 95% of the best design."
5. **Responsible by design.** Five short lines, each a feature you can show:
   - Numbers only from the solver (claims are checked against its output)
   - Code, not the LLM, accepts or rejects
   - Every write is a named Onshape version you can roll back
   - Refuses goals it can't measure, and holds what you say to keep
   - Hard caps on LLM spend and Onshape calls
6. **Path to production.** Onshape App Store app (it's already a Chrome side panel); CFD
   adapter for final verification (the solver interface is pluggable); more domains as packs
   (rocket fin built first, now retired from the demo); team notebooks that keep what worked.

**Backup slides** (only if asked): the tech-stack diagram; the solver validation table
(`sim/PHYSICS.md`); a panel screenshot with one step expanded.

**Design tips**
- Match the panel: a dark deck with one accent color reads as one product. The panel's blue is
  close to the chart's Darwin blue.
- One idea per slide, 12 words at most of body text. The demo is the star, and the slides are
  scenery on screen 2.
- Use real screenshots of the panel and Onshape side by side, not mockups.
- Make the big numbers big: "+41%", "128 s", "$0.02", "8/9 vs 1/9".
- Decide who drives screen 1 and who talks, and rehearse the hand-off.

## Tech stack (for the backup slide and Q&A)

Chrome MV3 side panel → React + Vite + TypeScript panel → FastAPI (Python 3.9), events over
WebSocket → investigator loop → Claude Haiku 5.5 via OpenRouter (any model, one setting) →
`rear_wing_v1` solver: AeroSandbox vortex lattice + NeuralFoil sections → Onshape REST: Variable
features written by id, read back through the Variables API, named versions before and after.

## Judge questions (answers from what actually happened)

**Why not just use an optimizer?**
We benchmarked one. With the same 20 simulations, CMA-ES reached 95% of the best design in 1 of
9 runs and Darwin in 8 of 9. Darwin also tells you *why* each change helped, and it follows
constraints you state in plain English.

**How do you know the LLM isn't making it up?**
It has to predict each result before simulating, and code scores the prediction. Explanations may
only use numbers that appear in the solver output, and anything else is stripped. Code, not the
LLM, decides accept or reject. Wrong predictions are visible in the panel, and the notebook
learns from them.

**How accurate is the physics?**
It's screening-level: AeroSandbox vortex lattice with NeuralFoil airfoil sections, validated
against textbook cases in `sim/PHYSICS.md`. It's the right tool for fast iteration, not for final
sign-off. That's why a CFD adapter is the production step. The solver is a plug-in.

**Why Onshape?**
That's where student teams already build, and it has a full API. We didn't want to compete with
CAD. We work inside it, so every change lands in your real model, versioned.

**What was the hardest part?**
- Making Onshape morph live. Configuration changes don't update open tabs; Variable feature writes
  do, in about 0.5 s. We proved that with a spike before building.
- Onshape's API limits are per endpoint. We exhausted the feature-list read in testing, so we
  rebuilt the write path to never need it.
- Keeping the LLM honest: scored predictions, numeric-claim checks, refusing unmeasurable goals.

**What did you change during the hackathon?**
We started as a rocket-fin optimizer and realized it was brute-forcing parameters. That's
optimization with an AI label, not intelligence. We pivoted to a hypothesis-driven loop grounded
in cited aero principles, on a part where the physics is rich (an FSAE rear wing).

**How is this different from Leo or other CAD copilots?**
They generate or edit geometry. Darwin closes the loop with physics: every change is a tested
hypothesis, measured by a solver before and after, and explained with the solver's numbers.

**What happens when it fails?**
- It refuses goals it can't measure: "lighter and stiffer" gets a list of what it *can* measure.
- If Onshape is unreachable, it won't start a session from stale values.
- A failed write is reported, and the session continues in simulation only.
- Every session has a "Before Darwin" version to roll back to.

**What does a session cost?**
About 2 minutes, $0.02 of LLM, and ~31 Onshape API calls.

**Who would pay?**
Collegiate aero teams first (Onshape gives education accounts). Then small hardware teams that
can't afford a simulation engineer for every iteration.

## Tracks

- **Overall / Most Technically Complex:** in.
- **Microsoft, Built for the Real World (primary).** Map each criterion to something you can show:
  - Customer understanding: FSAE aero teams' weekly loop
  - Measurable usefulness: the bench chart, plus the live +41% in 128 s for $0.02
  - Path to production: App Store app, CFD adapter, domain packs
  - Responsible design: slide 5
  - End-to-end: the live demo itself
- **Anthropic vs Factory: pick Anthropic.**
  - Claude (Haiku 5.5, through OpenRouter) now does every reasoning step: parsing the request,
    planning hypotheses, explaining results. "Know where it could go wrong" is our strongest
    answer: scored predictions, numbers only from the solver, code decides.
  - What's missing is a **named community with a real conversation**. Message one real person on
    an FSAE or aero team (CMU Racing, for example). Ask how they iterate a wing today, and use
    their actual words, with permission. Don't invent a quote.
  - Factory requires the Droid SDK doing real work in the running product. We have none, and
    bolting it on at 1 am risks the demo. "Demos that only work in slides" is a listed negative.
