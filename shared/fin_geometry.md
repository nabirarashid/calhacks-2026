# fin_v1 geometry definition (frozen at CP0)

The Onshape Part Studio (S1), the simulation (S2) and the dashboard preview mesh (S4) must all agree with this file. The reference implementation is `shared/fin_geometry.py`. The TS mirror is `dashboard/src/geometry/finPreview.ts`.

## Frame (Onshape, sketch on the Front plane)

| Axis | Meaning |
|---|---|
| **x** | Chordwise. x = 0 at the root leading edge, positive aft. |
| **z** | Spanwise, positive outward. z = 0 at the root, which sits on the body tube. |
| **y** | Thickness. The plate is extruded **symmetric**, from y = −t/2 to +t/2. |

Onshape is Z-up and three.js is Y-up, so the dashboard rotates −π/2 about x.

## Planform (trapezoid)

| Symbol | Definition |
|---|---|
| `c_r` | `root_chord` |
| `c_t` | `root_chord × taper_ratio` |
| `s` | `semi_span` |
| `Λ` | `sweep_deg` (leading-edge sweep) |
| `t` | `thickness` |

**Corners `(x, z)`:**

| Corner | Position |
|---|---|
| Root LE | `(0, 0)` |
| Root TE | `(c_r, 0)` |
| Tip TE | `(s·tanΛ + c_t, s)` |
| Tip LE | `(s·tanΛ, s)` |

## Edge profile (`edge_profile`)

| Value | Treatment | Removed cross-section per unit edge length |
|---|---|---|
| `square` | none | 0 |
| `rounded` | full-round fillet, r = t/2, on **LE and tip**; TE square | `t²·(1/2 − π/8)` ≈ 0.1073·t² |
| `beveled` | symmetric chamfer to a sharp edge on **LE and TE**, bevel length `b = min(3t, 0.25·c_t)` measured chordwise | `b·t/2` |

## Derived quantities (one fin)

| Quantity | Formula |
|---|---|
| Planform area | `A = s·(c_r + c_t)/2` |
| Mean aerodynamic chord | `c̄ = (2/3)·c_r·(1 + λ + λ²)/(1 + λ)`, with λ = taper_ratio |
| LE length | `s / cosΛ` |
| TE length | `√(s² + (s·tanΛ + c_t − c_r)²)` |
| Tip length | `c_t` |
| Volume | `V = A·t − removed × (sum of treated edge lengths)` |
| Aft overhang | `max(0, s·tanΛ + c_t − c_r)` |
| Bbox | `[min(0, s·tanΛ), −t/2, 0, max(c_r, s·tanΛ + c_t), t/2, s]` |

The volume formula ignores the small overlap where two treated edges meet at a corner. S1's sanity check therefore uses a 6 % volume tolerance and 0.5 mm on the bbox.

## Parameters

| name | kind | unit | min | max | step | default | cad_driven |
|---|---|---|---|---|---|---|---|
| root_chord | continuous | mm | 50 | 130 | 0.5 | 90 | ✓ |
| taper_ratio | continuous | – | 0.2 | 1.0 | 0.01 | 0.5 | ✓ |
| semi_span | continuous | mm | 30 | 90 | 0.5 | 60 | ✓ |
| sweep_deg | continuous | deg | 0 | 60 | 0.5 | 30 | ✓ |
| thickness | continuous | mm | 2.0 | 5.0 | 0.1 | 3.0 | ✓ |
| edge_profile | choice | – | square / rounded / beveled | | | rounded | ✓ |
| fin_count | integer | – | 3 | 4 | 1 | 4 | ✗ (sim-only) |
