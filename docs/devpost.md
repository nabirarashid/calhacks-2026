# Devpost copy

## Inspiration

Collegiate rocketry teams repeatedly edit fins by hand, rerun simulations, and eyeball whether stability, drag, mass, flutter safety, and durability are “good enough.” Those goals fight each other, and the team rarely knows whether the final design is close to optimal—or why it works.

## What it does

Darwin is a closed-loop engineering optimization team. Give it a plain-English goal and it proposes parametric designs, evaluates them with physics, critiques the result, changes its search strategy, regenerates winning CAD, and repeats. The interface shows the evolving geometry, matched-budget classic baselines, Pareto tradeoffs, lineage, costs, assumptions, fallbacks, and a plain-language explanation of the winner.

## How we built it

- A FastAPI event stream records every run as ordered JSONL.
- Specialized proposer, critic, strategist, and reporter roles share one budgeted model adapter.
- The fin scorer combines AeroSandbox buildup aerodynamics, Barrowman stability, analytic mass, and a flutter-screening estimate.
- The same parametric definition drives scoring, Onshape configuration, and a fixed-topology Three.js preview.
- React folds live WebSocket and offline replay events through one reducer. Recharts and custom SVG render optimization curves, the Pareto landscape, lineage, and parallel coordinates.
- Onshape geometry is cached and budgeted. The analytic preview morphs instantly, then cross-fades to the returned STL.

## Challenges

The hardest part was keeping three independent representations of a fin consistent: physics geometry, the Onshape Part Studio, and a smooth browser mesh. We froze one coordinate system and formula contract, added bounding-box and volume tests, and used a fixed preview topology so morphing never depends on STL topology. We also designed every networked component with an explicit degradation path so the demo stays honest and usable when Wi-Fi, an LLM, or CAD is unavailable.

## Accomplishments

- Fair CMA-ES and random-search comparisons on identical evaluation budgets.
- A real-time 3D champion that morphs before CAD returns and visibly marks verified geometry.
- Event-sourced live, backend-replay, and completely browser-local kiosk modes.
- Explainable winner cards with before/after metrics and high-fidelity checks.
- Hard Onshape and model-spend meters rather than invisible API consumption.
- A print handoff that keeps simulated material assumptions aligned with fabrication.

## What we learned

Agentic engineering works best when language models choose hypotheses and search behavior while deterministic software owns units, constraints, scores, and numeric claims. We also learned that fallbacks should be product features: a judge should always know whether they are seeing live agents, cached CAD, rule-based proposals, or a recording.

## What's next

We want to add trajectory-level objectives, OpenRocket export, team-specific material calibration, and more scorer plugins for brackets, nose cones, flexures, and thermal parts. The long-term goal is to make Darwin a trustworthy optimization layer over any well-parameterized CAD model.
