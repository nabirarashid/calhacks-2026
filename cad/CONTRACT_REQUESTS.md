# Contract change requests from S1

Process: PLAN.md header — S1 writes the request here, **S3 decides** and is the
only writer of `shared/`.

---

## 1. `sweep_deg` minimum: 0 → 5 deg

**Status: open. Requested by S1 for CP1.**

**What.** In `shared/fixtures/design_space_fin.json`, change the `sweep_deg`
`ParamSpec` minimum from `0` to `5`.

**Why.** `sweep_deg = 0` does not regenerate in the fin Part Studio, so the
Part Studio's configuration input was narrowed to a 5 deg floor. PLAN.md B.5
states the bounds are part of the frozen contract and that S1 must report a
narrowing: *"If one doesn't, S1 narrows the bounds in the Part Studio and
reports the new bounds before CP0."*

**Why it matters rather than being cosmetic.** `canonicalize()` clamps to the
contract's `min`, not the Part Studio's. While the contract says 0, the proposer
and CMA-ES can both generate designs in `[0, 5)`. Those are valid to `sim`,
which scores them happily, but `cad.build_geometry` will get a regeneration
failure from Onshape and spend calls to find out. Every such design is a wasted
pair of API calls and a `failed` GeometryRef in the demo.

**Blast radius.** One number in one fixture. No model or code change: `sim`
reads bounds from the space, `cad` reads them from the space, and the dashboard
renders whatever the space says. `shared/check.py` should still pass.

**Not urgent for correctness, only for waste.** Nothing breaks if this is not
changed before CP1 — `build_geometry` returns `failed` cleanly and the run
continues. It just burns calls and puts failures on screen.
