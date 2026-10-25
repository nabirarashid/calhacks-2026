## all
The part is an aerodynamic lifting surface: a race-car rear wing (downforce) or a rocket fin set. Designs are evaluated by a fast lifting-surface solver; every number comes from the solver, never from you.
Principles below are tagged "Rear wing:" or "Rocket fin:" by the part they apply to; use only those for the part in front of you, plus the untagged general ones. Strength words describe the typical change from one modest step of a lever (about 1 deg of angle, 3 deg of flap, 50 mm of span, 30 mm of endplate): small is under 2 %, moderate 2-6 %, strong over 6 %. A lever's strength changes with the design's state, and several principles say how.

<!--
Principles: one "### ID" block each, in this exact format (PLAN.md B.8). Content: W-B.
How to add or change one safely: domains/aero/README.md.

Every principle is written to agree with what the solvers actually do, not only with the
textbook, because the agent's predictions are scored against the solver. Where the two
could differ, the statement says which one the model follows ("in this model").

The `check:` line is read by sim/tests/test_principles.py and nowhere else: the parser
ignores unknown keys, and the investigator passes only id/statement/effects/levers to the
model. It names a starting state and one lever step, and the test confirms every claimed
direction in `effects` against the solver at that state. A principle whose effects depend
on several levers at once (a strategy, or a model limitation) has no check line.
Never rename or delete an id: recordings in demo/ cite them.
-->

### P-Q-SCALING
statement: Every aerodynamic force scales with dynamic pressure 0.5 rho V^2: doubling speed quadruples downforce and drag at nearly constant L/D. Speed is fixed by the goal, so geometry levers' percentage changes do not depend on it.
applies_when: any lifting surface in incompressible flow
effects: downforce_n: up (strong); drag_n: up (strong); l_over_d: flat
levers: none (velocity_mps is context, not a lever)
source: Anderson, Fundamentals of Aerodynamics, ch. 1 (dimensional analysis, force coefficients)

### P-AOA-LIFT
statement: Rear wing: below stall, downforce rises about linearly with angle and induced drag with its square, so L/D falls. Strength tracks stall margin: in this model 5-10 % downforce per degree with 6+ deg of margin, but 0-2 % once 10+ deg of flap leaves under about 4.5 deg, as at the default. With 20+ deg of flap and 0-2 deg of angle, angle raises L/D too.
applies_when: angle of attack below stall, lightly loaded section (small flap)
effects: downforce_n: up (strong); drag_n: up (strong); drag_induced_n: up (strong); l_over_d: down (moderate); stall_margin_deg: down (moderate)
levers: aoa_deg
source: Anderson, Fundamentals of Aerodynamics, ch. 4-5 (lift-curve slope, induced drag)
check: flap_angle_deg=5; step aoa_deg +1

### P-SECTION-CLMAX
statement: Rear wing: angle and flap share the section's lift ceiling. At the default (15 deg flap, 6 deg) both are spent: +1 deg of angle gives about +1.4 % downforce for +4 % drag, +3 deg of flap about +1 % for +9.5 %. Spend angle where flap is small, flap where angle is small.
applies_when: section loaded near its maximum lift coefficient
effects: downforce_n: up (small); drag_n: up (moderate); drag_profile_n: up (strong); l_over_d: down (moderate)
levers: aoa_deg, flap_angle_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 7-8 (maximum lift, flapped sections)
check: flap_angle_deg=15; step aoa_deg +1

### P-STALL
statement: Rear wing: stall_margin_deg is section stall angle minus angle of attack; each degree of angle costs a degree, and negative margin is infeasible. In this model downforce goes flat (within about 1 %) past stall while profile drag climbs 10-15 % per degree. Margin moves in 0.5 deg steps.
applies_when: angle of attack at or past the section stall angle
effects: downforce_n: flat; drag_n: up (moderate); drag_profile_n: up (strong); stall_margin_deg: down (moderate)
levers: aoa_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 7 (stall characteristics)
check: aoa_deg=9; step aoa_deg +1

### P-STALL-MARGIN-LEVERS
statement: Rear wing: in this model only angle and flap spend stall margin (flap 0.5-1 deg per 3 deg). Span, chord and endplates leave it unchanged, so when the margin limit binds, add downforce with span and endplates.
applies_when: stall_margin_deg constraint active or nearly so
effects: stall_margin_deg: flat; downforce_n: up (strong)
levers: span_mm, endplate_height_mm, chord_mm
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 7 (stall angle as a section property)
check: aoa_deg=9; step span_mm +50

### P-FLAP-STALL-ANGLE
statement: Rear wing: flap lowers the section's stall angle, so more flap leaves less stall margin at the same angle. In this model the NACA 4412 stalls near 13.5 deg clean, 9.5 deg at 15 deg of flap, 6.5 deg at 30 deg.
applies_when: any flap deflection
effects: stall_margin_deg: down (small); downforce_n: up (moderate)
levers: flap_angle_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 8 (flapped-section lift curves)
check: flap_angle_deg=10; step flap_angle_deg +3

### P-CAMBER-ZERO-LIFT
statement: Camber shifts the zero-lift angle negative (about -4 deg for a NACA 4412), so a cambered section makes downforce even at zero angle of attack. A flap is extra camber on the aft part of the section.
applies_when: cambered sections, attached flow
effects: downforce_n: up (strong); cl: up (strong)
levers: flap_angle_deg, aoa_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 4 and appendix data for NACA 4412
check: aoa_deg=0; flap_angle_deg=0; step flap_angle_deg +3

### P-LOW-AR-SLOPE
statement: Rear wing: at aspect ratio about 3 the lift-curve slope is far below the section's, because tip downwash cuts the effective angle. Raising effective aspect ratio (endplates, span) raises the slope and the downforce at a given angle.
applies_when: wings with aspect ratio below about 6
effects: downforce_n: up (small); cl: up (small); drag_induced_n: down (moderate)
levers: endplate_height_mm, span_mm
source: Raymer, Aircraft Design: A Conceptual Approach, ch. 12 (Helmbold/DATCOM lift-curve slope)
check: step endplate_height_mm +30

### P-FLAP-CAMBER
statement: Rear wing: at small deflection the flap is the strongest lever (about +15 % downforce per 3 deg from 5 deg): extra camber, with effectiveness set by chord fraction (Glauert). It adds induced drag with the square of the lift it creates.
applies_when: flap deflection below about 10 deg
effects: downforce_n: up (strong); drag_n: up (strong); drag_induced_n: up (strong); l_over_d: down (strong); cl: up (strong)
levers: flap_angle_deg
source: Anderson, Fundamentals of Aerodynamics, ch. 4 (thin-airfoil theory, flap effectiveness)
check: flap_angle_deg=5; step flap_angle_deg +3

### P-FLAP-SATURATION
statement: Rear wing: a plain flap separates at large deflection. In this model gains end near 15 deg of flap: to about 22 deg downforce stays within 2 % while drag rises about 9 % per 3 deg, and beyond that downforce falls. Past 15 deg more flap is nearly pure drag.
applies_when: flap deflection above about 15 deg
effects: downforce_n: down (moderate); drag_n: up (moderate); drag_profile_n: up (strong); l_over_d: down (strong)
levers: flap_angle_deg
source: Hoerner and Borst, Fluid-Dynamic Lift, ch. on plain flaps; Abbott & von Doenhoff, ch. 8
check: flap_angle_deg=24; step flap_angle_deg +3

### P-FLAP-TRIM
statement: Rear wing: from the default 15 deg, trimming 3 deg of flap costs about 2.5 % downforce but cuts drag about 9.5 % and returns 0.5 deg of stall margin. Under a drag limit, trim flap and spend the freed drag on span (flap 12 deg + span 900 mm: +3.7 % downforce, -6.5 % drag vs the default).
applies_when: flap at or above about 15 deg, goal with a drag limit or L/D objective
effects: downforce_n: down (small); drag_n: down (strong); drag_profile_n: down (strong); l_over_d: up (strong); stall_margin_deg: up
levers: flap_angle_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 6 and 8 (drag of flapped sections); Katz, Race Car Aerodynamics
check: step flap_angle_deg -3

### P-FLAP-CHORD
statement: Rear wing: a larger flap chord fraction makes the same flap angle more effective (Glauert). In this model it is strongest at the default 15 deg of flap (+6 % downforce, +9 % drag per +0.03), weak at 5 deg (+1 %), with an optimum above 20 deg (P-FLAP-CHORD-OPTIMUM).
applies_when: moderate flap deflection, section not saturated
effects: downforce_n: up (strong); drag_n: up (strong); drag_induced_n: up (strong); cl: up (strong)
levers: flap_chord_frac
source: Glauert, The Elements of Aerofoil and Airscrew Theory, ch. on hinged flaps; Anderson ch. 4
check: step flap_chord_frac +0.03

### P-FLAP-CHORD-OPTIMUM
statement: Rear wing: with 20+ deg of flap, downforce peaks at a flap chord fraction of about 0.32-0.36 and falls beyond, while profile drag rises and stall margin shrinks; at 25-30 deg of flap the larger fractions stall. Below 15 deg of flap, more fraction helps up to 0.40.
applies_when: flap deflection 20 deg or more
effects: downforce_n: down (small); drag_profile_n: up (strong); l_over_d: down (small); stall_margin_deg: down
levers: flap_chord_frac
source: Hoerner and Borst, Fluid-Dynamic Lift, ch. on plain flaps (separation at large chord ratio and deflection); Abbott & von Doenhoff, ch. 8
check: flap_angle_deg=20; flap_chord_frac=0.36; step flap_chord_frac +0.03

### P-PLAIN-VS-SLOTTED
statement: Rear wing: real race-car flaps are slotted, so air through the gap keeps them attached to larger angles. This solver models a plain flap: its maximum downforce is conservative and it saturates earlier than a real wing.
applies_when: interpreting how far flap gains extend
effects: downforce_n: flat
levers: flap_angle_deg
source: A.M.O. Smith, High-Lift Aerodynamics, Journal of Aircraft (1975); Katz, Race Car Aerodynamics

### P-INDUCED-AR
statement: Induced drag coefficient is CL^2 / (pi e AR): at fixed lift, higher effective aspect ratio cuts induced drag. Endplates raise it without adding area; span also adds lift (P-SPAN-AREA-AR).
applies_when: wings and lifting surfaces below stall
effects: drag_induced_n: down (moderate); drag_n: down (small); l_over_d: up (moderate)
levers: endplate_height_mm
source: Anderson, Fundamentals of Aerodynamics, ch. 5 (lifting-line theory)
check: step endplate_height_mm +30

### P-SPAN-AREA-AR
statement: Rear wing: with chord fixed, span raises area and aspect ratio together. Downforce rises about in proportion; raw induced drag rises too but falls per newton of downforce, so L/D improves. Per 50 mm, in every regime tested: about +6.5-7.3 % downforce, +3.5-4.7 % drag, +2.5-2.9 % L/D: usually the most drag-efficient downforce, up to the rule width.
applies_when: chord fixed, below stall
effects: downforce_n: up (strong); drag_n: up (moderate); drag_induced_n: up (moderate); l_over_d: up (moderate)
levers: span_mm
source: Anderson, Fundamentals of Aerodynamics, ch. 5; McBeath, Competition Car Aerodynamics (rule-limited span)
check: step span_mm +50

### P-CHORD-AREA-AR
statement: Rear wing: with span fixed, more chord adds area but lowers aspect ratio, so induced drag grows faster than downforce and L/D falls. Under a drag limit, prefer span to chord for the same added area.
applies_when: span fixed, below stall
effects: downforce_n: up (strong); drag_n: up (strong); drag_induced_n: up (strong); l_over_d: down (moderate)
levers: chord_mm
source: Anderson, Fundamentals of Aerodynamics, ch. 5 (aspect ratio and induced drag)
check: step chord_mm +20

### P-INDUCED-QUADRATIC
statement: Induced drag grows with CL squared, so it rises faster than downforce whenever a lever raises CL (angle, flap); at high CL it is most of the drag.
applies_when: any lift-raising lever, attached flow
effects: drag_induced_n: up (strong); downforce_n: up (strong); l_over_d: down (moderate)
levers: aoa_deg, flap_angle_deg
source: Anderson, Fundamentals of Aerodynamics, ch. 5 (drag polar)
check: flap_angle_deg=5; step aoa_deg +1

### P-SPAN-EFFICIENCY
statement: Span efficiency e of a planar wing cannot exceed 1 (elliptic loading); this untwisted rectangular wing is already at 0.97-0.99 across the design space, so induced-drag gains come from aspect ratio and endplates, not planform.
applies_when: planar, untwisted wings
effects: span_efficiency: flat
levers: span_mm, chord_mm
source: Munk, The Minimum Induced Drag of Aerofoils, NACA Report 121 (1921); Anderson ch. 5
check: step span_mm +50

### P-ENDPLATE-AR
statement: Rear wing: endplates block tip leakage, raising effective aspect ratio to about AR (1 + 1.9 h / b): a small downforce gain and a net drag cut, as induced drag falls more than their friction rises. Returns diminish slowly (L/D +2.7 % per 30 mm at 100 mm, +1.8 % at 270 mm), so 300 mm stays best under a drag limit. On an unloaded wing (no flap, low angle) they add drag.
applies_when: wings with endplates, h/b below about 0.4
effects: downforce_n: up (small); drag_n: down (small); drag_induced_n: down (moderate); drag_profile_n: up (moderate); l_over_d: up (moderate)
levers: endplate_height_mm
source: Hoerner and Borst, Fluid-Dynamic Lift, ch. on end plates
check: step endplate_height_mm +30

### P-SKIN-FRICTION
statement: Every wetted surface costs skin friction, about Cf = 0.074 Re^-0.2 per face for a turbulent flat plate. Endplates add wetted area without lift, so they are not free.
applies_when: attached turbulent boundary layers
effects: drag_profile_n: up (moderate)
levers: endplate_height_mm, chord_mm
source: Schlichting, Boundary-Layer Theory (turbulent flat-plate friction)
check: step endplate_height_mm +30

### P-PROFILE-LOADING
statement: Section profile drag rises with loading and climbs steeply near the lift limit. Here flap is its main driver: one 3 deg flap step at the default adds about 37 % profile drag.
applies_when: section loaded toward its lift limit
effects: drag_profile_n: up (strong); drag_n: up (strong)
levers: flap_angle_deg, aoa_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 6 (section drag polars)
check: step flap_angle_deg +3

### P-REYNOLDS-CHORD
statement: Rear wing: chord sets Reynolds number (rho V c / mu, about 3.5-6 x 10^5 here). Higher Re lowers the friction coefficient; in this model the stall angle does not move across the chord range, and chord's area and aspect-ratio effects dominate.
applies_when: section Reynolds numbers of about 10^5 to 10^6
effects: reynolds: up (strong); stall_margin_deg: flat
levers: chord_mm
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 7 (scale effect); Sharpe and Hansman, NeuralFoil (2025)
check: step chord_mm +20

### P-LD-TRADEOFF
statement: Rear wing: almost every downforce lever adds drag. Under a drag cap, rank moves by downforce gained per newton of drag: span is usually best, endplates nearly free, angle and flap only while the section is lightly loaded (not at the default; see P-FLAP-TRIM). When drag binds, a move that raises L/D beats a bigger one that does not.
applies_when: a goal with a drag limit or an L/D objective
effects: l_over_d: flat
levers: span_mm, endplate_height_mm, aoa_deg, flap_angle_deg, flap_chord_frac, chord_mm
source: Katz, Race Car Aerodynamics (downforce-drag tradeoff); McBeath, Competition Car Aerodynamics

### P-NO-GROUND-EFFECT
statement: Rear wing: the solver has no ground effect, car body or wake, so absolute downforce is an isolated-wing estimate. Never explain a result by ground effect or body interaction.
applies_when: interpreting absolute downforce
effects: downforce_n: flat
levers: none
source: Katz, Race Car Aerodynamics (wings in ground effect)

### P-FIN-SPAN-STABILITY
statement: Rocket fin: span is the strongest stability lever: fin normal-force slope grows about with (span / body diameter)^2 and its CP sits far aft. Returns diminish (+1.1 cal per 10 mm at 40 mm, +0.5 at 60, +0.3 at 80). It raises drag and mass and cuts flutter margin; at the reference (margin 1.6, floor 1.5) a 10 mm step breaks flutter unless thickness rises too (+0.5 mm restores about 0.35).
applies_when: subsonic rockets, Barrowman's assumptions
effects: stability_margin_cal: up (strong); drag_n: up (strong); fin_mass_total_g: up (strong); flutter_margin: down (strong)
levers: semi_span
source: Barrowman and Barrowman, The Theoretical Prediction of the Center of Pressure, NARAM-8 (1966)
check: step semi_span +10

### P-FIN-SWEEP-OPTIMUM
statement: Rocket fin: sweep moves the fins' CP aft but lowers their lift slope, so stability peaks at about 30-45 deg and falls either side. Sweep adds aft overhang (fragile on landing) and in this model no drag or mass.
applies_when: subsonic rockets, below about 60 deg sweep
effects: stability_margin_cal: flat; drag_n: flat; fin_mass_total_g: flat; aft_overhang_mm: up (strong)
levers: sweep_deg
source: Barrowman and Barrowman, NARAM-8 (1966); lift-slope reduction with sweep from Anderson ch. 5
check: step sweep_deg +10

### P-FIN-TAPER
statement: Rocket fin: with root chord and span fixed, a higher taper ratio (bigger tip) adds area: about +7 % mass per +0.1, more flutter margin (lower fin aspect ratio), slightly more stability (+0.06 cal per 0.1 at low taper, +0.01 near 1.0), drag nearly flat. From about 0.8 at 30 deg sweep the tip overhangs the body end.
applies_when: trapezoidal fins, root chord and span fixed
effects: stability_margin_cal: up (small); fin_mass_total_g: up (strong); flutter_margin: up (small); drag_n: flat
levers: taper_ratio
source: Barrowman and Barrowman, NARAM-8 (1966) (trapezoidal-fin normal force and CP); Martin, NACA TN 4197 (1958) (flutter vs aspect ratio and taper)
check: step taper_ratio +0.1

### P-FIN-ROOT-CHORD
statement: Rocket fin: stability peaks at a root chord of about 75-90 mm (80 at the reference, about 105 at 55 deg sweep). Past it, longer chord moves the fin CP forward and adds aft mass, so stability falls. It always adds mass (+11 % per 10 mm) and cuts flutter margin (thinner relative to chord); drag barely moves (+0.5 %).
applies_when: trapezoidal fins flush with the body's aft end
effects: stability_margin_cal: down (small); fin_mass_total_g: up (strong); flutter_margin: down (small); drag_n: flat
levers: root_chord
source: Barrowman and Barrowman, NARAM-8 (1966); Martin, NACA TN 4197 (1958); Stine and Stine, Handbook of Model Rocketry (CG and stability)
check: step root_chord +10

### P-FIN-FLUTTER-THICKNESS
statement: Rocket fin: the flutter boundary rises steeply with thickness, roughly as (thickness / chord)^1.5, so thin fins flutter first. Thickening is the most direct fix for a flutter violation, at a cost in mass and drag.
applies_when: thin plate fins, isotropic material
effects: flutter_margin: up (strong); fin_mass_total_g: up (strong); drag_n: up (strong)
levers: thickness, root_chord
source: Martin, Summary of Flutter Experiences as a Guide to the Preliminary Design of Lifting Surfaces on Missiles, NACA TN 4197 (1958)
check: step thickness +0.5

### P-FIN-MASS-CG
statement: Rocket fin: fins sit at the tail, so their mass pulls the CG aft and reduces stability margin. Heavier fins (thicker or longer-chord) partly cancel their own stability gain.
applies_when: fins are a meaningful share of the rocket's aft mass
effects: stability_margin_cal: down (small); fin_mass_total_g: up (strong)
levers: thickness, root_chord
source: Barrowman and Barrowman, NARAM-8 (1966); Stine and Stine, Handbook of Model Rocketry (CG and stability)
check: step thickness +0.5

### P-FIN-COUNT
statement: Rocket fin: four fins give more stability than three, with about a third more fin drag and mass; flutter margin is a per-fin property and does not change.
applies_when: three or four identical fins
effects: stability_margin_cal: down (strong); drag_n: down (strong); fin_mass_total_g: down (strong); flutter_margin: flat
levers: fin_count
source: Barrowman and Barrowman, NARAM-8 (1966) (normal force scales with fin count)
check: step fin_count -1

### P-FIN-BASE-DRAG
statement: Rocket fin: square-edged fins get most of their drag from base pressure behind the blunt trailing edge, which scales with thickness times span; root chord (+0.5 % per 10 mm), taper and sweep barely change drag.
applies_when: square-edged (blunt) fins
effects: drag_n: up (strong)
levers: thickness, semi_span
source: Hoerner, Fluid-Dynamic Drag (base drag of blunt trailing edges)
check: step thickness +0.5

### P-FIN-STABILITY-TARGET
statement: Rocket fin: a stability margin of about 1-2 calibers is the usual target. Below about 1 the rocket can be unstable; well above about 3 it weathercocks into the wind. More stability is not always better.
applies_when: stability goals for subsonic rockets
effects: stability_margin_cal: flat
levers: semi_span, sweep_deg, fin_count
source: Stine and Stine, Handbook of Model Rocketry (stability margin)
