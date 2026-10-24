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
