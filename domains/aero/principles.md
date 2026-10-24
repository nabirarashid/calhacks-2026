## all
The part is an aerodynamic lifting surface: a race-car rear wing (downforce) or a rocket fin set. Designs are evaluated by a fast lifting-surface solver; every number comes from the solver, never from you.
Principles below are tagged "Rear wing:" or "Rocket fin:" by the part they apply to; use only those for the part in front of you, plus the untagged general ones. Strength words describe the typical change from one modest step of a lever (about 1 deg of angle, 3 deg of flap, 50 mm of span, 30 mm of endplate): small is under 2 %, moderate 2-6 %, strong over 6 %. A lever's strength changes with the design's state, and several principles say how.

<!--
Principles: one "### ID" block each, in this exact format (PLAN.md B.8). Content: W-B.

Every principle is written to agree with what the solvers actually do, not only with the
textbook, because the agent's predictions are scored against the solver. Where the two
could differ, the statement says which one the model follows.

The `check:` line is read by sim/tests/test_principles.py and nowhere else: the parser
ignores unknown keys, and the investigator passes only id/statement/effects/levers to the
model. It names a starting state and one lever step, and the test confirms every claimed
direction in `effects` against the solver at that state. A principle whose effects depend
on several levers at once (a strategy, or a model limitation) has no check line.
-->

### P-Q-SCALING
statement: Every aerodynamic force scales with dynamic pressure q = 0.5 rho V^2, so doubling speed roughly quadruples both downforce and drag while L/D is nearly unchanged. Speed is fixed by the goal, so percentage changes from geometry levers do not depend on it.
applies_when: any lifting surface in incompressible flow
effects: downforce_n: up (strong); drag_n: up (strong); l_over_d: flat
levers: none (velocity_mps is context, not a lever)
source: Anderson, Fundamentals of Aerodynamics, ch. 1 (dimensional analysis, force coefficients)

### P-AOA-LIFT
statement: Rear wing: below the section's lift limit, downforce rises about linearly with angle of attack and induced drag rises with its square, so L/D falls as angle grows. This is a strong lever only while the section is lightly loaded, for example with a small flap (see P-SECTION-CLMAX).
applies_when: angle of attack below stall, lightly loaded section (small flap)
effects: downforce_n: up (strong); drag_n: up (strong); drag_induced_n: up (strong); l_over_d: down (moderate); stall_margin_deg: down (moderate)
levers: aoa_deg
source: Anderson, Fundamentals of Aerodynamics, ch. 4-5 (lift-curve slope, induced drag)
check: flap_angle_deg=5; step aoa_deg +1

### P-SECTION-CLMAX
statement: Rear wing: the section has a lift ceiling, and angle of attack and flap draw on the same budget. Once the flap is deflected moderately the section is already near its ceiling, so adding angle of attack gains little downforce but still costs drag. Spend angle where flap is small, flap where angle is small.
applies_when: section loaded near its maximum lift coefficient
effects: downforce_n: up (small); drag_n: up (moderate); drag_profile_n: up (strong); l_over_d: down (moderate)
levers: aoa_deg, flap_angle_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 7-8 (maximum lift, flapped sections)
check: flap_angle_deg=15; step aoa_deg +1

### P-STALL
statement: Rear wing: past the section's stall angle, lift falls and profile drag rises steeply. stall_margin_deg falls by one degree for each degree of angle of attack added, and a design with negative margin is infeasible, so treat a margin near zero as a wall.
applies_when: angle of attack at or past the section stall angle
effects: downforce_n: down (small); drag_n: up (moderate); drag_profile_n: up (strong); stall_margin_deg: down (moderate)
levers: aoa_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 7 (stall characteristics)
check: aoa_deg=9; step aoa_deg +1

### P-FLAP-STALL-ANGLE
statement: Rear wing: deflecting the flap lowers the angle at which the section stalls, so a bigger flap leaves less stall margin at the same angle of attack. In this model the clean NACA 4412 stalls near 13.5 deg and each few degrees of flap takes about a degree off that.
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
statement: Rear wing: a low-aspect-ratio wing (about 3 here) has a much lower lift-curve slope than the section, because downwash from the tips reduces the effective angle everywhere. Raising effective aspect ratio, with endplates or span, raises the slope and so the downforce at a given angle.
applies_when: wings with aspect ratio below about 6
effects: downforce_n: up (small); cl: up (small); drag_induced_n: down (moderate)
levers: endplate_height_mm, span_mm
source: Raymer, Aircraft Design: A Conceptual Approach, ch. 12 (Helmbold/DATCOM lift-curve slope)
check: step endplate_height_mm +30

### P-FLAP-CAMBER
statement: Rear wing: at small deflection the flap is the strongest single lever, adding effective camber with an effectiveness set by its chord fraction (Glauert). It also adds induced drag, because induced drag grows with the square of the lift it creates.
applies_when: flap deflection below about 10 deg
effects: downforce_n: up (strong); drag_n: up (strong); drag_induced_n: up (strong); l_over_d: down (strong); cl: up (strong)
levers: flap_angle_deg
source: Anderson, Fundamentals of Aerodynamics, ch. 4 (thin-airfoil theory, flap effectiveness)
check: flap_angle_deg=5; step flap_angle_deg +3

### P-FLAP-SATURATION
statement: Rear wing: a plain flap loses effectiveness at large deflection because its boundary layer separates. In this model downforce gains vanish around 15-20 deg of flap and downforce falls beyond about 20 deg, while profile drag keeps climbing. Past that point more flap is pure drag.
applies_when: flap deflection above about 20 deg
effects: downforce_n: down (moderate); drag_n: up (moderate); drag_profile_n: up (strong); l_over_d: down (strong)
levers: flap_angle_deg
source: Hoerner and Borst, Fluid-Dynamic Lift, ch. on plain flaps; Abbott & von Doenhoff, ch. 8
check: flap_angle_deg=24; step flap_angle_deg +3

### P-FLAP-CHORD
statement: Rear wing: a larger flap chord fraction makes the same flap angle more effective (Glauert's flap effectiveness grows with chord fraction). It matters most at moderate deflection; with a tiny flap angle there is little to amplify, and with the section saturated there is little room left.
applies_when: moderate flap deflection, section not saturated
effects: downforce_n: up (strong); drag_n: up (strong); drag_induced_n: up (strong); cl: up (strong)
levers: flap_chord_frac
source: Glauert, The Elements of Aerofoil and Airscrew Theory, ch. on hinged flaps; Anderson ch. 4
check: step flap_chord_frac +0.03

### P-PLAIN-VS-SLOTTED
statement: Rear wing: real race-car wings use a slotted flap, whose gap feeds high-energy air onto the flap and delays its separation, so it stays effective to larger angles than a plain flap. This solver models a plain flap with no slot, so its maximum downforce is conservative and the flap saturates earlier than a real slotted wing would.
applies_when: interpreting how far flap gains extend
effects: downforce_n: flat
levers: flap_angle_deg
source: A.M.O. Smith, High-Lift Aerodynamics, Journal of Aircraft (1975); Katz, Race Car Aerodynamics

### P-INDUCED-AR
statement: Induced drag coefficient is CL^2 / (pi e AR): at fixed lift, raising effective aspect ratio cuts induced drag. Endplates raise aspect ratio without adding planform area, so they are the cleanest way to use this here. Span also raises aspect ratio but adds lift too (see P-SPAN-AREA-AR).
applies_when: wings and lifting surfaces below stall
effects: drag_induced_n: down (moderate); drag_n: down (small); l_over_d: up (moderate)
levers: endplate_height_mm
source: Anderson, Fundamentals of Aerodynamics, ch. 5 (lifting-line theory)
check: step endplate_height_mm +30

### P-SPAN-AREA-AR
statement: Rear wing: with chord fixed, span raises planform area and aspect ratio together. Downforce rises about in proportion to span. Raw induced drag also rises, because there is more lift, but induced drag per newton of downforce falls, so L/D improves. Span is usually the most drag-efficient way to add downforce, up to the rule width.
applies_when: chord fixed, below stall
effects: downforce_n: up (strong); drag_n: up (moderate); drag_induced_n: up (moderate); l_over_d: up (moderate)
levers: span_mm
source: Anderson, Fundamentals of Aerodynamics, ch. 5; McBeath, Competition Car Aerodynamics (rule-limited span)
check: step span_mm +50

### P-CHORD-AREA-AR
statement: Rear wing: with span fixed, more chord raises planform area but lowers aspect ratio, so induced drag grows faster than downforce and L/D falls. When drag is limited, prefer span to chord for the same added area.
applies_when: span fixed, below stall
effects: downforce_n: up (strong); drag_n: up (strong); drag_induced_n: up (strong); l_over_d: down (moderate)
levers: chord_mm
source: Anderson, Fundamentals of Aerodynamics, ch. 5 (aspect ratio and induced drag)
check: step chord_mm +20

### P-INDUCED-QUADRATIC
statement: Induced drag grows with the square of lift coefficient, so it rises faster than downforce whenever a lever raises CL (angle of attack, flap). At high CL induced drag is the larger share of total drag.
applies_when: any lift-raising lever, attached flow
effects: drag_induced_n: up (strong); downforce_n: up (strong); l_over_d: down (moderate)
levers: aoa_deg, flap_angle_deg
source: Anderson, Fundamentals of Aerodynamics, ch. 5 (drag polar)
check: flap_angle_deg=5; step aoa_deg +1

### P-SPAN-EFFICIENCY
statement: The span efficiency e of a planar wing cannot exceed 1 (elliptic loading). For an untwisted rectangular wing of aspect ratio about 3 it is already close to 1, so planform shape is not where the induced-drag gains are here; aspect ratio and endplates are.
applies_when: planar, untwisted wings
effects: span_efficiency: flat
levers: span_mm, chord_mm
source: Munk, The Minimum Induced Drag of Aerofoils, NACA Report 121 (1921); Anderson ch. 5

### P-ENDPLATE-AR
statement: Rear wing: endplates block tip leakage and raise effective aspect ratio, roughly AR_eff = AR (1 + 1.9 h / b). The result is a small downforce gain and a net drag reduction, because induced drag falls more than the endplates' own skin friction rises. The benefit per millimetre shrinks as they grow.
applies_when: wings with endplates, h/b below about 0.4
effects: downforce_n: up (small); drag_n: down (small); drag_induced_n: down (moderate); drag_profile_n: up (moderate); l_over_d: up (moderate)
levers: endplate_height_mm
source: Hoerner and Borst, Fluid-Dynamic Lift, ch. on end plates
check: step endplate_height_mm +30

### P-SKIN-FRICTION
statement: Every wetted surface costs skin-friction drag, about Cf = 0.074 Re^-0.2 for a turbulent flat plate, on both faces. Endplates add wetted area without adding lift, which is why they are not free.
applies_when: attached turbulent boundary layers
effects: drag_profile_n: up (moderate)
levers: endplate_height_mm, chord_mm
source: Schlichting, Boundary-Layer Theory (turbulent flat-plate friction)
check: step endplate_height_mm +30

### P-PROFILE-LOADING
statement: Section profile drag rises with section loading and climbs steeply near the section's lift limit. On this wing flap deflection is the main driver of profile drag, so a moderate flap step can raise profile drag by tens of percent.
applies_when: section loaded toward its lift limit
effects: drag_profile_n: up (strong); drag_n: up (strong)
levers: flap_angle_deg, aoa_deg
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 6 (section drag polars)
check: step flap_angle_deg +3

### P-REYNOLDS-CHORD
statement: Rear wing: Reynolds number is rho V c / mu, so chord sets it (about 3.5-6 x 10^5 here). Higher Reynolds number slightly raises the section's maximum lift and lowers its friction drag coefficient; across this range the effect is small next to the area and aspect-ratio effects of chord.
applies_when: section Reynolds numbers of about 10^5 to 10^6
effects: reynolds: up (strong)
levers: chord_mm
source: Abbott & von Doenhoff, Theory of Wing Sections, ch. 7 (scale effect); Sharpe and Hansman, NeuralFoil (2025)
check: step chord_mm +20

### P-LD-TRADEOFF
statement: Rear wing: almost every lever that adds downforce also adds drag. When drag is capped, rank moves by downforce gained per newton of drag added, not by downforce alone: span is usually best, endplates are nearly free, and angle or flap pay off only while the section is lightly loaded. When the drag limit is the binding constraint, a move that raises L/D is worth more than a bigger move that does not.
applies_when: a goal with a drag limit or an L/D objective
effects: l_over_d: flat
levers: span_mm, endplate_height_mm, aoa_deg, flap_angle_deg, flap_chord_frac, chord_mm
source: Katz, Race Car Aerodynamics (downforce-drag tradeoff); McBeath, Competition Car Aerodynamics

### P-NO-GROUND-EFFECT
statement: Rear wing: this solver has no ground effect and treats the wing as isolated, with no car body or wake. A real wing low to the ground gains downforce, so absolute numbers are an isolated-wing estimate. Do not explain a result by ground effect or body interaction; the model contains neither.
applies_when: interpreting absolute downforce
effects: downforce_n: flat
levers: none
source: Katz, Race Car Aerodynamics (wings in ground effect)

### P-FIN-SPAN-STABILITY
statement: Rocket fin: fin span is the strongest stability lever, because the fins' normal-force slope grows roughly with (span / body diameter)^2 and their center of pressure sits far aft. It also raises drag and mass and lowers flutter margin, since a longer fin is more flexible.
applies_when: subsonic rockets, Barrowman's assumptions
effects: stability_margin_cal: up (strong); drag_n: up (strong); fin_mass_total_g: up (strong); flutter_margin: down (strong)
levers: semi_span
source: Barrowman and Barrowman, The Theoretical Prediction of the Center of Pressure, NARAM-8 (1966)
check: step semi_span +10

### P-FIN-SWEEP-OPTIMUM
statement: Rocket fin: sweep moves the fins' center of pressure aft, which adds stability, but it also lowers their lift slope. Stability therefore peaks at moderate sweep (about 30-45 deg here) and falls either side. Sweep adds aft overhang, which is fragile on landing, and in this model it does not change drag or mass.
applies_when: subsonic rockets, below about 60 deg sweep
effects: stability_margin_cal: flat; drag_n: flat; fin_mass_total_g: flat; aft_overhang_mm: up (strong)
levers: sweep_deg
source: Barrowman and Barrowman, NARAM-8 (1966); lift-slope reduction with sweep from Anderson ch. 5
check: step sweep_deg +10

### P-FIN-FLUTTER-THICKNESS
statement: Rocket fin: the flutter boundary rises steeply with thickness, roughly with (thickness / chord)^1.5, so thin fins flutter first. Thickening is the most direct fix for a flutter-margin violation, at a cost in mass and drag.
applies_when: thin plate fins, isotropic material
effects: flutter_margin: up (strong); fin_mass_total_g: up (strong); drag_n: up (strong)
levers: thickness, root_chord
source: Martin, Summary of Flutter Experiences as a Guide to the Preliminary Design of Lifting Surfaces on Missiles, NACA TN 4197 (1958)
check: step thickness +0.5

### P-FIN-MASS-CG
statement: Rocket fin: fins sit at the tail, so their mass pulls the center of gravity aft, which reduces stability margin. Heavier fins (thicker or longer-chord) partly cancel their own stability gain.
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
statement: Rocket fin: square-edged fins get most of their drag from base pressure behind the blunt trailing edge, which scales with thickness. Thickness is therefore the main fin drag lever, and sweep barely affects drag here.
applies_when: square-edged (blunt) fins
effects: drag_n: up (strong)
levers: thickness
source: Hoerner, Fluid-Dynamic Drag (base drag of blunt trailing edges)
check: step thickness +0.5

### P-FIN-STABILITY-TARGET
statement: Rocket fin: a stability margin of about 1-2 calibers is the usual target. Below about 1 the rocket can be unstable; well above about 3 it weathercocks into the wind. More stability is not always better.
applies_when: stability goals for subsonic rockets
effects: stability_margin_cal: flat
levers: semi_span, sweep_deg, fin_count
source: Stine and Stine, Handbook of Model Rocketry (stability margin)
