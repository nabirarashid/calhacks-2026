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

## G-4 Bracket mesh and solve ≤ 20 s — **pending W-A's P3-A1 export**

Cannot run until a meshable bracket export exists. Projection from the measured
scaling (3075 dofs → 0.13 s, direct sparse solve ≈ O(n^1.5)):

| bracket dofs | projected solve |
|---|---|
| 20 000 | ~2 s |
| 50 000 | ~9 s |
| 100 000 | ~24 s — **over budget** |

**Guidance for W-A / the mesher: keep the coarse bracket under ~60 000 dofs**
(roughly 15 000 quadratic tets). Two-level refinement for the champion only, per
B.10's fidelity ladder. If a coarse mesh exceeds that, drop element size before
dropping element order — order 1 is not an acceptable trade.

## G-5 Verdict

**GO (b).** `structural_fea_v1` is built on `scikit-fem` + `gmsh` with quadratic
tetrahedra. Stress is evaluated excluding a 1.5 × hole-radius zone around
fixtures and load application, with protected-hole stress read separately
(C.2 P3-B2).

Residual risks:

- **G-4 is unproven** until the bracket export lands. If the coarse solve blows
  the 20 s budget, the fallback is a coarser mesh, then analytic screening only.
- **STL → volume mesh** may need gmsh `classifySurfaces` + `createGeometry`.
  Untested here; it is the next W-B task once W-A produces an export.
- Candidate (a) CalculiX is **not validated**. Choosing it later would mean
  writing `.inp` generation and `.frd` parsing from scratch.
