# Darwin: two-minute pitch

## 0:00–0:20 — The problem

“Rocket teams spend weeks editing a fin, rerunning a simulator, and guessing at the tradeoff. Bigger fins improve stability but add drag and mass. Thin fins are light but can flutter. A feasible fin is easy; a near-optimal, explainable one is hard.”

Show the physical seed fin and champion if available.

## 0:20–0:40 — Set the goal

Type: “Maximize stability, keep drag low, keep all fins under 40 grams, and stay flutter-safe.”

Open the interpretation strip briefly: “Darwin turns plain English into explicit objectives, hard constraints, and visible assumptions. Nothing is hidden.”

## 0:40–1:15 — Watch evolution

Start the run. Point to the morphing fin, rising score curve, and agent feed.

“The proposer explores designs, the critic uses actual sensitivities to explain what worked, and the strategist changes how the next generation searches. Every candidate runs through our aerodynamic, Barrowman stability, mass, and flutter models.”

Point to CMA-ES and random: “Those baselines get exactly the same number of evaluations.”

## 1:15–1:40 — Explain the winner

On the winner card, compare seed and champion.

“The result is not just a score. Darwin shows the Pareto tradeoff, the winning lineage, why the design won, and a separate high-fidelity check. If the model or CAD service degrades, the UI says so instead of hiding it.”

## 1:40–2:00 — Make it real

Show the Onshape-verified badge, then the physical print.

“This geometry came from our real parametric Onshape model. We can commit it back to CAD, export a print-ready package, and generate the engineering report. Darwin closes the loop from intent, to physics, to manufactured part.”

If time remains, open Discover: “The same loop can discover parameters from another Part Studio and bind a scorer—this is an optimization system, not a one-off fin generator.”
