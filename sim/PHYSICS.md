# Darwin physics models

Two solvers, one file. **`rear_wing_v1`** is the hero demo (W-B, PLAN.md v4 B.5); **`fin_v1`**
is the second part and the origin story. Both are screening models: they rank design moves
and expose tradeoffs; they do not certify a part.

- [Validation table](#validation-table) — every check, regenerated from the code
- [`rear_wing_v1`](#rear_wing_v1-physics-model) — the race-car rear wing
- [`fin_v1`](#fin_v1-physics-model) — the rocket fin set

---

## Validation table

Regenerate with `python -m sim.validation` (deterministic, no network, about 2 s).
`sim/tests/test_validation.py` fails if any row stops passing, so this table cannot drift
from the model. Every reference is independent of the code it checks: closed-form theory or
published section data, never the solver checking itself.

**Rear wing (`rear_wing_v1`)**

| Quantity | Reference | Result | |
|---|---|---|---|
| Lift slope, NACA 4412, AR 3.04, AoA 2-6 deg | Helmbold low-AR lifting line | -3.8 to -3.4 % | pass |
| Lift slope, NACA 0012, AR 3.04, AoA 2-6 deg | Helmbold low-AR lifting line | -3.7 to -3.2 % | pass |
| Flap lift increment, 5-20 deg | Glauert thin-airfoil flap theory | -4.5 to -2.1 % | pass |
| VLM resolution, default design | converged 24x12 lattice | +0.30 % at 12x6 | pass |
| Span efficiency, rectangular wing | Anderson ch. 5: delta about 0.05 at AR 6 | delta 0.048 at AR 6; e 0.981 here | pass |
| Induced drag, default flapped wing | independent VLM near-field estimate | -2.5 % | pass |
| NACA 4412 section, Re 1e6 (NeuralFoil) | Abbott & von Doenhoff: aL0 ~ -4 deg, ~0.1/deg, CLmax 1.3-1.8 | aL0 -4.3 deg, 0.109/deg, CLmax 1.59 at 14.5 deg | pass |
| Viscous-correction fixed point | 10 iterations | 0.013 % at 4 | pass |
| Downforce at 2x speed | q = 0.5 rho V^2: x4, less a Reynolds effect | x4.04 | pass |

**Measured and rejected (why the lift path is VLM, not AeroBuildup)**

| Quantity | Reference | Result | |
|---|---|---|---|
| AeroBuildup lift, NACA 4412, AoA 0-8 deg | Helmbold low-AR lifting line | x1.27 to x1.74 (worst at AoA 0) | rejected |
| VLM with ControlSurface flaps, 0/15/30 deg | should rise with flap | CL 0.5683 / 0.5683 / 0.5683 (flap ignored) | rejected |

**Rocket fin (`fin_v1`)**

| Quantity | Reference | Result | |
|---|---|---|---|
| Fin lift slope, 7 designs across the box | Barrowman (1966) vs AeroSandbox | ratio 0.86 to 1.19 (default 1.03) | pass |
| Flutter vs thickness, 2-5 mm | NACA TN 4197: V_f ~ (t/c)^1.5 | exponent 1.50 | pass |

**How to read the AeroBuildup row.** AeroBuildup was the plan's fast path for wing lift. Its
lift *slope* is right but it does not reduce camber lift for a finite wing, so on this
aspect-ratio-3 wing it reports close to the 2D section value at zero angle of attack. A flap
is extra camber, so the same error inflated flap effectiveness by about 50 % at small angles.
The trends looked sensible, which is why it passed the prototype; only a comparison against
theory exposed it.

**Knowledge-layer pilot (Sat Oct 24, n = 1 each, not a result).** One live Sonnet session per
arm on the default wing goal, same 20-simulation budget: prediction accuracy 0.93 with the
principles and 0.77 without; final downforce 133.7 N vs 133.2 N (a tie, because both runs
pushed span and endplates to their limits on step 1). The formal ablation is the proof
bench (PLAN.md C5).

---

# `rear_wing_v1` physics model

`sim/plugins/rear_wing_v1.py`. An inverted NACA 4412 wing with a plain trailing-edge flap and
endplates, at 25 m/s. Solved as an upright wing at positive angle of attack and reported as
downforce; with no ground effect modelled the two are mirror images, so this is exact within
the model. About 18 ms per fast evaluation.

## Evaluation path

| Step | Quantity | Source |
|---|---|---|
| 1 | Effective aspect ratio | Hoerner: `AR_eff = AR (1 + 1.9 h / b)` |
| 2 | Span efficiency `e` | Prandtl lifting line, Glauert's Fourier solution for the planform |
| 3 | Inviscid 3D lift | VLM on one full-chord lattice, flap deflected in the airfoil geometry |
| 4 | Endplate lift correction | ratio of lifting-line slopes at `AR_eff` and `AR` |
| 5 | Viscous lift loss | NeuralFoil section CL over Glauert thin-airfoil CL, capped at 1.0 |
| 6 | Effective angle | AoA minus induced angle `CL / (pi e AR_eff)`; 5 and 6 iterate to a fixed point |
| 7 | Induced drag | `CL^2 / (pi e AR_eff)` |
| 8 | Profile drag | NeuralFoil section CD at the effective angle, plus endplate skin friction |
| 9 | Stall margin | NeuralFoil section CL peak for the deflected flap, minus AoA |

`hifi` runs the identical model at a converged 24x12 VLM resolution, so the high-fidelity
check is a genuine mesh-refinement check rather than a comparison between unrelated methods.

## Why each piece is what it is

- **VLM for lift, not AeroBuildup.** See the rejected rows above.
- **The flap is deflected in the airfoil coordinates.** AeroSandbox 4.2.8's VLM ignores
  `ControlSurface` deflection entirely (rejected row). Splitting the main element and flap
  into two lattices, each with its own 4412 camber, builds a double-humped section that
  under-predicts lift by 25 % at zero flap. One lattice with the true camber line fixes both.
- **A viscous correction on top of VLM.** VLM is inviscid, so it never sees a flap's
  boundary layer separate. NeuralFoil's viscous/inviscid ratio for the flapped section is
  about 1.0 up to 10 deg of flap and falls to 0.78 at 20 deg and about 0.6 at 30 deg. Without
  it, VLM over-predicts flap lift by 25-75 %. The same ratio handles stall smoothly, so there
  is no hard cap.
- **`e` from lifting-line theory, not from VLM.** VLM's near-field induced drag implies
  `e = 1.04` on this wing, above the planar maximum of 1 (Munk). Glauert gives 0.981.
- **Endplate skin friction is included** (turbulent flat plate, `Cf = 0.074 Re^-0.2`, both
  faces of both plates). It is about 2 % of drag at the default, but without it endplate height
  would be free and the optimizer would always max it out for a reason that isn't physics.

## Validity envelope

Inside it the model is good for ranking design moves; outside it, results are labelled.

- **Incompressible**, Mach about 0.07 at 25 m/s.
- **No ground effect, isolated wing.** No car body, wake or interference. Real wings close to
  the ground make more downforce; absolute numbers are an isolated-wing estimate.
- **Plain flap, no slot.** A real race-car flap is slotted and stays attached to larger
  angles, so this model's maximum downforce is **conservative** and its flap saturates early.
- **Linear lifting-line corrections** for endplates and induced angle: reliable below stall.
  Past stall the viscous ratio still bounds lift, the design is flagged, and the loop treats
  negative stall margin as infeasible.
- **Section Reynolds number 3.5-6 x 10^5**, inside NeuralFoil's validated range for this
  airfoil; outside about 10^5-10^6 a warning is raised.
- **Steady flow.** No flap or endplate vortex unsteadiness.

## Behaviour the optimizer meets

All covered by `sim/tests/test_rear_wing.py`.

- **Flap has an interior optimum near 20 deg.** Strong lever at small deflection (+15 % per
  3 deg from 5 deg), diminishing to +1 % at 15 deg, then downforce falls past about 20 deg
  while profile drag keeps rising.
- **AoA and flap share the section's lift budget.** At 5 deg of flap, AoA adds +7 % per
  degree; at 15 deg of flap it adds +1.4 %.
- **AoA raises downforce until stall, then it falls.** Default stall margin is +3.5 deg.
- **Span cuts induced drag per newton of downforce**, but raw induced drag *rises*, because
  with chord fixed the extra span carries extra lift.
- **Chord adds area but lowers aspect ratio**, so L/D falls.
- **Endplates give a small downforce gain and a net drag reduction.**
- **Headroom:** under a 20 N drag cap, the best design in a 300-sample Latin hypercube makes
  146 N against 105 N at the default, +39 %.

## Metric normalisation

`typical_min`/`typical_max` for the objectives are calibrated from that 300-sample Latin
hypercube over the frozen B.5 box (p2 to p98, rounded out). A range that overshoots the real
spread compresses the score; one that undershoots saturates it; either way the agent loses its
gradient. The first draft's `downforce_n` range topped out at 260 N against a real maximum of
157 N, which would have scored the best possible wing at about half the scale.

## Not for

Certification, ride-height or yaw studies, multi-element slot optimisation, or any absolute
downforce number quoted as a prediction for a real car. Final sign-off is CFD or a wind
tunnel; the loop is solver-agnostic and can call either.

---

# `fin_v1` physics model

The simulation is a deterministic, reduced-order design-ranking model for a
trapezoidal model-rocket fin. It is intended to compare many candidates quickly
and expose the tradeoffs among stability, drag, mass, flutter margin, and aft
overhang. It is not CFD, structural FEA, flight certification, or a substitute
for a qualified stability and safety review.

The geometry contract is frozen in `shared/fin_geometry.md`. All simulation
length inputs are millimetres, angles are degrees, masses are grams, forces are
newtons, speeds are metres per second, pressure and modulus calculations use
pascals, and normal-force slopes use inverse radians.

## Evaluation path

`sim.api.evaluate` performs the following steps:

1. Canonicalize parameters against the frozen design space.
2. Merge the reference-rocket context with goal context overrides.
3. Calculate geometry, mass, CG, Barrowman stability, flutter, and aerodynamic
   metrics.
4. Convert goal objectives to normalized scores and evaluate hard and soft
   constraints.
5. Return raw metrics, objective scores, violations, warnings, feasibility, and
   the aggregate score. The simulator does not call Onshape or any network API.

The default context describes a fixed reference rocket: a 76.2 mm diameter,
1,200 mm long body with a 300 mm tangent-ogive nose, 1,500 g non-fin mass at
700 mm from the nose, a 120 m/s design speed, sea-level altitude, two degrees
incidence, and solid PLA with density 1.24 g/cm³ and shear modulus 1.3 GPa.
Goal context overrides may replace those values.

## Geometry and mass

One fin is a constant-thickness swept trapezoid. With root chord `c_r`, tip
chord `c_t = lambda * c_r`, semi-span `s`, leading-edge sweep `Lambda`, and
thickness `t`, its planform area is

```text
A = s * (c_r + c_t) / 2
```

Volume starts at `A * t` and subtracts the edge-removal volume defined by the
shared geometry contract. Rounded fins remove the full-round cross-section
from the leading and tip edges; beveled fins remove the symmetric chamfer from
the leading and trailing edges. The analytic correction ignores the small
overlap where treated edges meet at a corner.

Mass is `volume * density`. `fin_mass_g` is one fin and
`fin_mass_total_g = fin_mass_g * fin_count`. The rocket CG is the mass-weighted
average of the fixed non-fin rocket and the complete fin set. Fins are mounted
flush with the aft end of the body, and their centroid is the area centroid of
the trapezoid. Small centroid shifts caused by edge treatments are ignored.

This model assumes uniform material, 100% infill, no adhesive or fillets, no
manufacturing voids, and a rigid attachment.

## Stability: Barrowman model

Barrowman owns the reported stability calculation. The fin-set normal-force
slope is

```text
(CNalpha)_F = K_fb * 4*n*(s/D)^2
              / (1 + sqrt(1 + (2*l_m/(c_r+c_t))^2))

K_fb = 1 + r/(s+r)
```

where `n` is fin count, `D` and `r` are body diameter and radius, and `l_m` is
the mid-chord-line length. Fin CP uses the standard Barrowman trapezoidal-fin
expression. The tangent-ogive nose contributes `CNalpha = 2` at
`0.466 * nose_length`; the cylindrical body contributes no normal force. The
combined CP is the normal-force-weighted average of nose and fins.

```text
stability_margin_cal = (CP - CG) / body_diameter
```

Positive margin means the CP is aft of the CG in this nose-origin coordinate
system. Because fin mass is included in CG, increasing fin size can improve
aerodynamic CP while also pulling CG aft.

The method assumes low angle of attack, a slender rigid vehicle, subsonic flow,
and the fixed reference body. It does not model dynamic stability, roll,
weathercocking, launch-rail departure, body lift, fin flexibility, or wake
interaction among fins.

## Aerodynamic drag and lift-slope cross-check

### Fast path

When AeroSandbox 4.2.8 imports and solves successfully, the fast path constructs
one physical fin in metres with a symmetric NACA 00xx section.
Section thickness is selected from thickness divided by mean aerodynamic chord.
`AeroBuildup` is evaluated at zero incidence for profile drag and at zero plus
the configured incidence for a finite-difference one-fin lift slope. The lift
slope is a plausibility cross-check; Barrowman still owns stability.

An edge pressure-drag increment is added using a projected-edge heuristic:
square edges use coefficient 1.29, rounded edges 0.12, and beveled edges 0.0.
The complete fin-set drag is

```text
drag_n = CD_one_fin * dynamic_pressure * one_fin_area
         * fin_count * 1.10
```

The factor 1.10 is the fixed body-interference allowance. `cd_fins` converts
that force back to a coefficient referenced to the rocket body's circular
cross-section, not the fin area.

This is an isolated-fin model. It does not resolve fin-fin interference, the
body boundary layer, mounting fillets, surface roughness, separated flow,
transonic effects, or angle-dependent induced drag. The reported drag is a
screening estimate at the configured speed, atmosphere, and zero-incidence
profile-drag condition.

### Analytic fallback

If AeroSandbox is unavailable, rejects a result, or fails, evaluation continues
and emits a warning. The fallback uses the Schlichting turbulent flat-plate
skin-friction correlation `0.455/log10(Re)^2.58` on both faces, a thickness form factor, the same
edge pressure heuristic, and a lifting-line approximation for one-fin lift
slope. Atmospheric properties use a clipped -500 to 11,000 m standard
troposphere and Sutherland viscosity. This fallback is deliberately smooth and
conservative; it does not claim CFD fidelity.

## Flutter screen

Flutter velocity uses the NACA TN 4197-style expression frozen in the plan:

```text
V_f = a * sqrt(G / ((1.337*AR^3*P*(lambda+1))
                    / (2*(AR+2)*(t/c_r)^3)))
```

`AR = 2*s^2/A` is the full-pair aspect-ratio convention, `G` is converted from
GPa to Pa, `P = 101325 Pa`, and `a = 340.3 m/s`. The reported flutter margin is
`V_f / design_velocity`.

This is a screening boundary, not a guarantee. It assumes isotropic PLA and
uses sea-level pressure and speed of sound even when the aerodynamic context
uses another altitude. It omits orthotropic print behavior, layer adhesion,
temperature, damping, root-joint compliance, structural modes, manufacturing
defects, and aeroelastic coupling beyond the closed-form estimate.

## High-fidelity check

`sim.api.validate_high_fidelity` evaluates only a selected design. The current
implementation runs the ordinary fast evaluation and a second aerodynamic
evaluation that uses AeroSandbox's vortex-lattice method over -4 to 6 degrees
for the independent lift-slope and linearity cross-check. It retains
AeroBuildup's zero-incidence profile drag and adds the VLM induced-drag
increment at the configured incidence; mass, CG, Barrowman stability, and
flutter are unchanged. The VLM model uses a mirrored pair and doubled reference
area to supply a root symmetry plane while preserving per-fin coefficients. A
drag discrepancy over 15% or alpha-sweep nonlinearity over 10% is surfaced as
a warning.

If AeroSandbox or VLM fails, the high-fidelity call degrades to the analytic
fallback and says so in `Score.warnings`. The current implementation does **not**
yet include structural FEA, CFD, or OpenRocket validation. “High fidelity” should
therefore be read as an independent aerodynamic cross-check, not certification.

## Published metrics

| Metric | Unit | Meaning and method |
|---|---:|---|
| `stability_margin_cal` | cal | `(CP - CG) / body_diameter`; Barrowman CP and mass-coupled CG. |
| `cp_mm` | mm | Combined nose-and-fin Barrowman CP from the nose tip. |
| `cg_mm` | mm | Rocket CG from the nose tip after adding the fin set. |
| `drag_n` | N | Complete fin-set drag at design speed. |
| `cd_fins` | - | Fin-set drag coefficient referenced to body cross-section. |
| `fin_mass_g` | g | Analytic volume times density for one fin. |
| `fin_mass_total_g` | g | One-fin mass times fin count. |
| `flutter_velocity_mps` | m/s | Closed-form flutter screening boundary. |
| `flutter_margin` | - | Flutter velocity divided by design velocity. |
| `cn_alpha_fins` | 1/rad | Complete fin-set Barrowman normal-force slope. |
| `aft_overhang_mm` | mm | Positive distance by which the tip trailing edge extends aft of the root trailing edge. |
| `planform_area_cm2` | cm² | Trapezoidal area of one fin. |

The scorer warns, but still returns a score, if one-fin fin-area CD is outside
0.002-0.2, stability margin is outside -2 to 8 calibers, analytic mass is
inconsistent with volume times density, or the AeroSandbox-to-Barrowman
lift-slope ratio is outside 0.6-1.6.

## Objectives, constraints, and Pareto ranks

Raw metrics remain available; the aggregate is only a user-goal ranking aid.
Maximize and minimize objectives are clipped to `[0, 1]` using each metric's
published typical range. Target objectives score one at the target and fall
linearly to zero at the requested tolerance. Objective scores are combined by
weight. Soft violations subtract `0.1 * normalized_violation`; hard violations
make the design infeasible and give it a negative aggregate. A pathological
collection of large soft violations can also make an aggregate negative; hard
feasibility remains a separate field and Pareto ranking always separates the
feasible and infeasible groups.

Metric violation amounts are normalized by metric typical range and numeric
parameter violations by parameter range. A mismatched fixed choice parameter is
a full hard violation. Pareto sorting uses the normalized objective scores, all
interpreted as “higher is better,” and places every infeasible front after all
feasible fronts.

## Validation methodology

Validation is layered so a plausible optimization result does not hide a unit
or implementation error:

| Check | Result in the configured Python 3.9 / AeroSandbox 4.2.8 environment |
|---|---|
| Geometry and units | PASS: a square-edged 90 x 60 x 3 mm PLA rectangle evaluates to 20.088 g at 1.24 g/cm³. |
| Barrowman reference | PASS: the independent rectangular case gives `CNalpha=2.83281573`, fin CP `925.0 mm`, combined CP `580.7700 mm`, and margin `0.496085 cal`. |
| Aerodynamic lift slope | PASS: the mirrored rectangular AeroBuildup reference gives `2.52465 /rad` versus lifting-line `2.51327 /rad`, a 0.45% difference (15% limit). |
| Monotonicity | PASS: the selected span, thickness, sweep, and taper comparisons all move their expected metrics in the documented direction. |
| Determinism and contracts | PASS: repeated metrics and scores match excluding elapsed time; the metric catalog exactly matches the frozen fixture. |
| Aggregation and Pareto | PASS: hand-computed objective/violation cases and feasibility-separated non-dominated ranks match. |
| Performance | PASS locally: 64 warmed serial evaluations in 1.045 s; 2,000-point landscape with four workers in 19.386 s. |
| Full S2 suite | PASS: 37 tests. |
| CAD integration | PENDING S1/CP2: compare analytic volume and bounds with exported Onshape geometry for selected champions. |

Run `pytest sim/tests` to reproduce the local validation suite, `python -m
sim.bench` for the performance targets, and `python -m sim.demo` for a
deterministic comparison of the default, frozen example, and continuous-
parameter box corners. Any AeroSandbox fallback is printed as a warning and
must be disclosed in a demo or report.

## Appropriate use

Use this model to rank designs, reject obvious constraint violations, explore
tradeoffs, select a short list for higher-fidelity analysis, and explain why one
candidate differs from another. Do not use it alone to authorize a launch,
establish a safe operating envelope, certify a printed part, or predict actual
flight performance. Final hardware requires geometry verification, material
and process characterization, a complete rocket stability analysis, and
physical testing under the applicable safety code.
