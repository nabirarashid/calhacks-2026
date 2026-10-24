## all
The part is a model-rocket fin set for a collegiate rocketry team. Designs are evaluated by a fast physics simulation: AeroSandbox drag, Barrowman stability (fin mass shifts the CG aft), a NACA TN 4197 flutter estimate, and mass from solid PLA.

## goal_parser
- "Maximize stability" means a `target` of about 2.5 calibers (tolerance about 1.0). A rocket with more than about 3 calibers weathercocks, so never "maximize" stability_margin_cal.
- Always include these hard constraints unless the user overrides them: flutter_margin >= 1.5 and stability_margin_cal >= 1.0.
- Mass limits: if the user doesn't say "per fin", assume the limit is for all fins (fin_mass_total_g) and say so in assumptions.
- A body tube ("must fit a 3-inch body tube") is the rocket body the fins mount on. It is NOT a limit on any fin dimension: never turn it into a param constraint. Code handles it (body diameter and no aft overhang).
- design_velocity_mps: set it only if the user states a speed (convert units to m/s). Otherwise null.
- fixed_params example: "3 fins" -> fin_count = "3".

## critic
Example of the plain engineering language wanted: "sweep moves the center of pressure aft, which buys stability without span, so mass and drag stay low".

## reporter
The report is for a collegiate rocketry team. Caveats should cover the fast physics model's limits: subsonic, low incidence, a fixed reference rocket, and a screening-level flutter estimate.
