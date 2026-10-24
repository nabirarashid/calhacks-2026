## all
The part is an aerodynamic lifting surface: a race-car rear wing (downforce) or a rocket fin set. Designs are evaluated by a fast lifting-surface solver; every number comes from the solver, never from you.

<!--
Principles: one "### ID" block each, in this exact format (PLAN.md B.8). W-B owns the content
(target 25-35 entries, real sources only). These seed entries are W-C's, written so the parser and
the loop can be built; W-B replaces or extends them.
-->

### P-INDUCED-AR
statement: Induced drag scales with CL^2 / (pi * e * AR); raising effective aspect ratio cuts induced drag at fixed lift.
applies_when: wings and lifting surfaces below stall
effects: drag_induced_n: down (strong); drag_n: down (moderate); l_over_d: up (moderate)
levers: span_mm, endplate_height_mm, chord_mm
source: Anderson, Fundamentals of Aerodynamics, ch. 5 (lifting-line theory)

### P-ENDPLATE-AR
statement: Endplates block tip leakage and raise effective aspect ratio, roughly AR_eff = AR * (1 + 1.9 h / b).
applies_when: wings with endplates, h/b below about 0.4
effects: drag_induced_n: down (moderate); downforce_n: up (small); drag_profile_n: up (small)
levers: endplate_height_mm
source: Hoerner, Fluid-Dynamic Lift, ch. on end plates

### P-AOA-LIFT
statement: Below stall, lift grows about linearly with angle of attack, and induced drag grows with its square, so L/D falls past a moderate angle.
applies_when: angle of attack below stall
effects: downforce_n: up (strong); drag_n: up (strong); l_over_d: down (moderate); stall_margin_deg: down (strong)
levers: aoa_deg
source: Anderson, Fundamentals of Aerodynamics, ch. 4-5

### P-FLAP-CAMBER
statement: Deflecting a flap adds effective camber, raising CL at a given angle with an effectiveness set by flap chord fraction, at a cost in profile and induced drag.
applies_when: plain or slotted flaps below flap stall
effects: downforce_n: up (strong); drag_n: up (moderate); stall_margin_deg: down (moderate)
levers: flap_angle_deg, flap_chord_frac
source: Anderson, Fundamentals of Aerodynamics, ch. 4 (thin-airfoil theory, flap effectiveness)
