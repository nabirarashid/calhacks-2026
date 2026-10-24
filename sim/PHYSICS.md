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
