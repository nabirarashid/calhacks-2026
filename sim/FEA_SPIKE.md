# FEA gate (G-1 … G-5) — W-B

**Verdict: GO (b) — `scikit-fem` + `gmsh`, with quadratic tetrahedra (mandatory).**

Posted for the 14:00 G-FEA gate. Candidate (a) CalculiX is installed and runs
but was **not validated**; (b) cleared the gate with margin and has fewer
failure modes on a demo laptop, so (a) stays an unvalidated fallback.

Reproduce everything here with:

```bash
conda run -n darwin python -m pytest sim/tests/test_fea_cantilever.py -q
```

---

## G-1 Install

Candidate (b), the one we are taking. Latest `scikit-fem` requires Python
≥ 3.10, so it is pinned below 10 for our 3.9 environment:

```bash
conda run -n darwin python -m pip install "scikit-fem<10" gmsh meshio
```

Installed: `scikit-fem 9.1.1`, `gmsh 4.15.2`, `meshio 5.3.5`, with
`numpy 2.0.2`, `scipy 1.13.1`, Python 3.9.23.

Candidate (a), for the record:

```bash
conda install -y -n darwin -c conda-forge calculix     # NOTE: -n darwin
```

It landed in `base` on this laptop (the `-n` was omitted), so the binary is at
`/opt/anaconda3/bin/ccx`, reporting `Version 2.23`. `ccx` is a standalone
executable invoked by subprocess, so its environment does not have to match.

**Regression check:** the full suite is **112 passed** after the install, so
nothing in `sim/`, `cad/` or `backend/` broke. AeroSandbox 4.2.8 is unaffected
by `numpy 2.0.2` (`requirements.txt` already allows `numpy<2.1`).

## G-2 Cantilever vs Euler–Bernoulli — **PASS**

Rectangular section, L = 100, b = h = 10 mm, so **L/h = 10**. E = 70 000 MPa,
ν = 0.33, tip load 100 N. Units are mm/N/MPa throughout.

Analytic reference: tip **0.57143 mm** (`P L³ / 3EI`), σ_xx at x = L/2
**30.00 MPa** (`M(x)·(h/2)/I`). Stress is read at mid-span, away from both the
clamp and the load patch, and restricted to the outer fibres.

| cell | order | mesh | dofs | tip mm | err | σ_xx MPa | err | sec |
|---|---|---|---|---|---|---|---|---|
| hex | 1 | 20×2×2 | 567 | 0.49467 | −13.43 % | 28.57 | −4.75 % | 0.11 |
| hex | 1 | 40×4×4 | 3075 | 0.54874 | −3.97 % | 30.34 | +1.14 % | 0.51 |
| hex | 2 | 20×2×2 | 3075 | 0.56939 | −0.36 % | 30.70 | +2.33 % | 2.93 |
| tet | 1 | 20×2×2 | 567 | 0.27869 | **−51.23 %** | 21.84 | −27.20 % | 0.01 |
| tet | 1 | 40×4×4 | 3075 | 0.44460 | **−22.20 %** | 29.33 | −2.25 % | 0.08 |
| **tet** | **2** | **12×2×2** | **1875** | **0.56510** | **−1.11 %** | 29.36 | −2.15 % | **0.09** |
| tet | 2 | 20×2×2 | 3075 | 0.56805 | −0.59 % | 28.51 | −4.95 % | 0.13 |

Gate configuration: **tet, order 2, 12×2×2** — deflection within 5 % and
stress within 10 %, in 0.09 s.

## G-3 Mesh refinement — **PASS**

Tip deflection from 12×2×2 → 20×2×2 moves **+0.52 %**, inside the 3 % limit.
Convergence is monotonically upward toward the shear-corrected Timoshenko value
(0.57599 mm), which is the correct direction for a displacement-based
formulation: it is stiff and approaches the true answer from below. A solve that
*overshot* Timoshenko would indicate a bug, and
`test_deflection_converges_from_below_toward_timoshenko` asserts it cannot.

## The finding that matters: linear tets are unusable

The bracket will be meshed with **tetrahedra** by gmsh, not structured hexes,
and `ElementTetP1` is the obvious default. It is also wrong by **−51 % coarse
and −22 % refined**, because linear tets lock in bending.

The dangerous part is that P1 tets **converge smoothly while being wrong**, so a
mesh-refinement check alone would not catch it — the classic plausible wrong
number that safety rule 3 exists to prevent. `ElementTetP2` fixes it at a
*lower* dof count and comparable runtime.

This is pinned by `test_linear_tets_are_unacceptably_stiff`, which fails if
anyone reverts the element order. **`structural_fea_v1` must use order 2.**

## G-4 Bracket mesh and solve ≤ 20 s — **partly answered, with a hard limit**

The real bracket export is still pending W-A's P3-A1, so the chain was
exercised end to end on a stand-in STL: a 90 × 60 × 3 mm rectangular plate from
`shared.fin_geometry.prism_stl` (taper 1, sweep 0), via
`sim/fea/mesh.py` → `skfem_elastic.solve_mesh_cantilever`.

**Meshing is not the problem.** `merge → classifySurfaces → createGeometry →
addVolume → generate(3)` runs in 0.05–0.35 s at every size, and the
reconstructed volume matches the analytic part to **0.000 %**.

**Through-wall resolution is the problem.** Reference is *plate* theory, not
beam theory: the plate is wider (90) than it is long (60), so it bends with
modulus `E / (1 − ν²)`. Against beam theory a correct answer reads as −8.5 %
and looks like a failure.

| h | elements through 3 mm | P2 dofs | deflection vs plate theory | solve |
|---|---|---|---|---|
| 3.0 | 1.0 | 30 216 | **−83 %** (locked) | 2.3 s |
| 2.0 | 1.5 | 63 576 | **−85 %** (locked) | 7.2 s |
| 1.5 | 2.0 | 143 550 | **+2.7 %** | 40 s |
| 1.2 | 2.5 | 243 933 | +2.9 % | 113 s |

**Two quadratic elements through the wall is the threshold**, not a preference:
below it the answer is 6× too stiff; at it, refining further moves the result
0.2 %. So `h = t / 2` is both necessary and sufficient
(`mesh.h_for_wall`). The cost is what bites: this small plate already needed
40 s against the 20 s budget.

**Bracket budget** (`mesh.within_dof_budget`, 80k-dof ceiling, default
geometry ≈ 19 900 mm³):

| thickness | h | est. dofs | FEA |
|---|---|---|---|
| 2.0 mm | 1.00 | 595 000 | **decline** |
| 3.0 mm | 1.50 | 176 000 | **decline** |
| 4.0 mm | 2.00 | 74 000 | verify |
| 5.0 mm | 2.50 | 38 000 | verify |
| ≥ 6 mm | ≥ 3.0 | ≤ 22 000 | verify |

**FEA can verify a bracket at ≥ 4 mm and must decline below.** That is in direct
tension with the search: a mass-minimising optimizer proposes thin designs,
which are exactly the ones FEA cannot afford. Below the budget the solve is
declined and the design keeps its analytic screening label, rather than
returning a locked (too-stiff) number or blowing the timeout.

### A measured trap: never `mesh.clear()` between levels

On an STL-derived model, `gmsh.model.mesh.clear()` followed by `generate(3)`
**hangs indefinitely** — no exception, no timeout. Reproduced in isolation: level
1 meshes in 0.06 s, then the second `generate(3)` never returns. Rebuilding the
whole pipeline per level costs 0.07 s, so `refinement_levels()` always rebuilds.
This matters because two-level convergence is required for the champion, and
the obvious implementation is exactly the one that freezes.

## Demo load case (W-B owns it, P3-B5) — the plan's numbers do not work

Evaluated with `structural_analytic_v1` on the default bracket (rib 8 mm, no
lightening holes), goal SF ≥ 2:

- **20 N** (the current fixture): **every thickness passes**, including 2 mm. There
  is no failure to repair, and the optimizer drives to 2 mm, where FEA declines.
- **50 N** (P3-B5's goal text): **only the 8 mm upper bound passes**. A champion
  pinned to a bound is exactly what the critic is built to flag as suspicious.
- **~30 N**: the SF = 2 boundary lands near 4.8 mm, in the interior, inside the
  FEA budget, with thinner designs genuinely failing. **Recommended starting
  point** for P3-B5 tuning.

At 30 N the physics also tells a different story from the demo script
(PLAN.md A.2, 1:30, "fails the stress check at a mounting hole"):

| design | root fillet MPa | hole MPa | mass g | SF | governs |
|---|---|---|---|---|---|
| default, t = 5 | 23.63 | 3.54 | 24.70 | 2.12 ✅ | root fillet |
| thin, t = 4 | 27.86 | 4.42 | 20.24 | 1.79 ❌ | root fillet |
| t = 5 + 3 lightening holes | 23.63 | 31.48 | 24.34 | 1.59 ❌ | **hole** |
| t = 5 + 3 holes + rib 16 | 9.66 | 12.59 | 26.72 | 3.97 ✅ | hole |

- **The mounting holes never govern** (3.5–5 MPa): near the wall the bolt couple
  has a usable arm. Failure happens at the **lightening holes**, in the
  high-moment flange.
- **Lightening holes are a bad trade here**: three of them save 0.36 g (1.5 %)
  while dropping SF from 2.12 to 1.59. That is a non-obvious, explainable
  result — the kind of finding the critic exists to surface.
- **A taller rib is the efficient repair**, cutting root stress 23.6 → 9.7 MPa.

So the 1:30 beat should read "fails at a lightening hole", not "at a mounting
hole". The narrative follows the solver, not the other way round (safety
rule 1). Final values come from P3-B5's ≥ 4-of-5-seeds tuning.

## G-5 Verdict

**GO (b).** `structural_fea_v1` is built on `scikit-fem` + `gmsh` with quadratic
tetrahedra. Stress is evaluated excluding a 1.5 × hole-radius zone around
fixtures and load application, with protected-hole stress read separately
(C.2 P3-B2).

Residual risks:

- **G-4 on the real bracket** is still unproven; the stand-in plate shows the
  chain works and where it stops. Thin designs (< 4 mm) are declined by design.
- **STL → volume mesh** works (`sim/fea/mesh.py`), volume exact. A real CAD
  export may carry defects a generated prism does not; the volume check against
  the analytic or CAD volume is the guard for that.
- Candidate (a) CalculiX is **not validated**. Choosing it later would mean
  writing `.inp` generation and `.frd` parsing from scratch.
