# Contract change requests from S1

Process: PLAN.md header — S1 writes the request here, **S3 decides** and is the
only writer of `shared/`.

---

## 1. `sweep_deg` minimum: 0 → 5 deg — withdrawn

**Status: withdrawn. Keep the contract minimum at 0 deg.**

The earlier request conflated a sketch-angle defect with a lower-bound
limitation. Darwin measures leading-edge sweep from the spanwise/perpendicular
axis, so `sweep_deg = 0` is the valid unswept, right-angle fin.

The Part Studio correction is `90 deg - #sweep_deg` because its sketch angle is
measured from the root chord. The frozen `0..60 deg` contract is correct.

---

## 2. `make secrets-check` is broken and now always fails

**Status: resolved on current `main`.** `Makefile` now excludes
`":!**/package-lock.json"`, and `make secrets-check` passes with both dashboard
and Droid lockfiles present.

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

---

## 3. Wire domain verifiers into every real CAD build

**Status: open. Requested by W-A. Safety gate.**

Generic `cad/` no longer imports `shared.fin_geometry` or selects a domain from
`space.scorer`. `build_geometry`, print export, and `OnshapeCadAdapter` now fail
closed without an injected `GeometryVerifier`. W-C's adapter/domain registry
must construct the CAD adapter with `PACK.verifier` and pass the same verifier
to legacy fin-facing calls during the compatibility window. Otherwise the real
v1 backend path correctly returns `domain_geometry_verifier_required`.

## 4. Bind and check the disposable write target revision

**Status: open. Requested by W-A. Contract decision required.**

`CadBinding.source_microversion` protects the source document, while commits go
to `write_target_ref`. Add an optional `write_target_microversion` (or equivalent
approval-bound target revision) so the adapter can refuse a disposable copy
that changed after preview. The configuration POST already rejects skew after
its fresh GET, but that does not prove the target still matches the revision the
engineer reviewed.

## 5. Carry protected-interface measurements into the verifier

**Status: open. Requested by W-A.**

The static verifier can compare injected mate-connector origins and exported
hole diameters to `ProtectedInterface.nominal`, and fails closed when either is
missing. The onboarding/domain plumbing needs to pass sanitized `CadInventory`
mate-connector evidence plus hole-axis/diameter measurements from the geometry
extractor into the verifier. Nominal points merely falling inside the body bbox
are deliberately not treated as proof that a hole exists.

## 6. Add run identity to CAD call-budget context

**Status: open. Requested by W-A.**

`Authority.max_onshape_calls_per_run` cannot be scoped perfectly from the B.4
method signatures because `CadAdapter.build_geometry` receives a manifest but
no run id. W-C should either instantiate one adapter per run or add an explicit
run/execution context. W-A currently scopes counters by manifest object,
project, revision, and source microversion; a reused manifest instance is
therefore intentionally conservative across calls.

## 7. Supply print-label metadata from the backend

**Status: open. Requested by W-A.**

The real print package now requires `design_id`, deterministic `score`, and the
domain verifier. The existing backend route still calls the legacy three-arg
signature. W-C should pass the selected design's id/score and registered
verifier; until then the real route fails closed rather than emitting an
unlabelled or unverified STL.
