# Requests from W-B (sim/) to W-C

Process: PLAN.md v3 header — requests go in your folder's
`CONTRACT_REQUESTS.md`, and W-C decides. These are about `backend/`, which W-B
does not edit.

---

## 1. `ScorerBridge.hifi()` falls back to the screening adapter — every bracket run ends on an error

**Status: open. Found Sat 12:45 after `c4a023d`. Visible in the demo.**

**Reproduce:**

```python
from backend.adapters import ScorerBridge, get_solver
bridge = ScorerBridge(m_bracket, get_solver("structural_analytic_v1"), verify=None)
bridge.hifi(space, params, goal)
# ValueError: structural_analytic_v1 is screening-only; use structural_fea_v1 for verification
```

`ScorerBridge.hifi` does `self._eval(self.verify or self.screening, ..., "verification")`.
With no verify adapter installed it re-runs the **screening** adapter at
**verification** fidelity. `structural_analytic_v1` refuses that on purpose.
`run_loop.py:466-468` catches the exception and emits
`error("sim", "hifi_failed", ...)`, so nothing crashes — but **every bracket run
finishes with an error event**, which the dashboard shows as an amber error card.

**Why the adapter refusing is correct, and the fallback is the bug.** If the
screening adapter *accepted* `fidelity="verification"`, the bridge would stamp a
closed-form screening result as `fidelity="high"` and the evidence report would
call it a verification. Safety rule 7 says fidelity is labeled accurately. The
`ValueError` is the fail-closed path doing its job; removing it would silently
make the result dishonest.

**Suggested fix (W-C's call):** when there is no verify adapter, do not attempt
verification. Return "not available" so the run loop records it as *not run*
rather than *failed*:

```python
def hifi(self, space, params, goal=None):
    if self.verify is None:
        return None          # run loop: hifi_check stays None, no error event
    return self._eval(self.verify, params, goal, "verification")
```

…and in `run_loop.py`, treat a `None` from `validate_high_fidelity` as a skip.
`hifi_check = None` is already the honest value; only the error event is wrong.

---

## 2. The bridge passes no geometry, so FEA cannot verify through it

**Status: open. Blocks P3-B2 integration at CP9 (Sun 02:00). Raising it early.**

`SolverAdapter.evaluate` takes `geometry: Optional[str]` — a local STL/STEP
path — precisely so verification adapters can mesh the real part.
`ScorerBridge._eval` calls `adapter.evaluate(self.m, dict(params), g,
fidelity=fidelity)` and never passes it.

`structural_fea_v1` *cannot* run without geometry: it meshes the exported STL
(`sim/fea/mesh.py`) and solves on that. So even once it is registered as the
verify adapter, verification through the run loop will have nothing to mesh.

The geometry already exists at that point in the run: champions are built by
`cad.build_geometry` and announced in `geometry_ready` events, and
`cad.geometry_file(geometry_key)` resolves the local path. It needs plumbing
from the champion's `GeometryRef` into `hifi(...)` as `geometry=<path>`.

**What W-B will do on its side:** `structural_fea_v1.evaluate(..., geometry=None)`
returns a validity note and declines (never falls back to screening, never
returns a number), so the failure is honest and loud rather than silent.

---

## 3. FEA budget the run loop needs to know about

Not a request, a constraint (details in `sim/FEA_SPIKE.md`, G-4):

- FEA can verify a bracket at **≥ 4 mm** wall thickness and must decline below,
  because bending needs two quadratic elements through the wall and thin walls
  blow the dof budget.
- A mass-minimising run proposes thin designs, so expect `verify_top_k`
  candidates to be **declined** fairly often. A declined verification is a
  normal outcome, not an error, and should not produce an `error` event either.
- Champion verification is ~5–15 s at 4–5 mm. Budget the 60 s demo run for it,
  or verify the champion only.

---

## 4. `ParamSemantics.role` is never enforced — "fixed" and "protected" do nothing

**Status: open. Found Sat ~13:00. Matters for the Phase 2 onboarding review UI.**

The manifest gives every parameter a `role: editable | fixed | protected`, which
is the field that *reads* as "which parameters Darwin may change". No code reads
it. `backend/projects.py:56` reads `semantics`, but only `.confirmed`, for
maturity gating.

**Runtime proof** (fin manifest, `thickness` flipped to `role="fixed"`):

```
thickness role now: fixed
optimizer still sees bounds: 2.0 .. 5.0
a proposal of thickness=4.7 canonicalizes to: 4.7
```

**Why it is harmless today and a trap tomorrow.** `edge_profile` is `role=fixed`
*and* `choices=["square"]` in `projects/fin_reference/r1.json`, so the bound
pins it and the role is merely consistent by hand. But in the Phase 2 review UI
an engineer who marks a parameter "fixed" will expect the optimizer to leave it
alone. It won't. Worse, confirming that semantics raises the project's maturity,
so the review is *recorded as approval* of a constraint that is not enforced.
That is the exact failure safety rule 5 ("approval binds the reviewed state")
exists to prevent.

**Suggested fix (W-C's call).** When a manifest becomes the optimizer's
`DesignSpace`, collapse every `fixed` or `protected` parameter to a single value
(its default, or the value the engineer approved), so it is enforced by the same
`canonicalize` path that already enforces bounds and `goal.fixed_params`. A test
that flips a role and asserts the proposal is clamped would pin it.
