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

---

## 2. `make secrets-check` is broken and now always fails

**Status: open. Requested by S1. Safety gate — worth fixing immediately.**

**What.** In the `Makefile`, change the `secrets-check` exclude pathspec from
`":!package-lock.json"` to `":!**/package-lock.json"`.

**Why.** A git pathspec without a glob anchors at the repo root, so
`":!package-lock.json"` excludes only a root-level lockfile. Now that S4 has
pushed `dashboard/package-lock.json`, its npm `integrity` hashes (base64 sha512,
well over 40 chars) match the `[A-Za-z0-9+/]{40,}={0,2}` pattern and
`make secrets-check` fails on every run:

```
dashboard/package-lock.json:43:  "integrity": "sha512-6Ozddx...=="
... (hundreds more)
```

**Why it matters more than a broken target.** PLAN.md says to run this before
every push and before Devpost, and risk #14 (secrets leak) is rated Critical.
A check that always fails is a check everyone learns to ignore — and then the
one time it fires for a real key, nobody looks. Verified by hand that there is
currently **no** real hit: excluding nested lockfiles, the pattern matches
nothing in the tree.

**Second-order note for whoever runs it in a script:** `make secrets-check |
tail -2` swallows the failure, because a pipeline's exit status is the last
command's. Call the target bare if you are gating on it.
