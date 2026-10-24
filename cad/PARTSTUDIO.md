# Build the fin Part Studio (Onshape UI, ~40 min, 0 API calls)

For whoever has used parametric CAD before. Nothing here consumes API calls —
the Onshape UI is free. Only the spike afterwards spends calls.

The geometry spec is PLAN.md B.5. This is the click path.

---

## 0. Setup (2 min)

1. Sign in to <https://cad.onshape.com> with the **dev account** whose keys are
   in `~/.darwin_secrets.sh` (currently Hannah's: `hzw@andrew.cmu.edu`).
2. **Create** > **Document**, name it `darwin-fin`.
3. It opens with one Part Studio tab. Rename it `fin` (double-click the tab).

## 1. Configuration inputs FIRST (10 min)

Do this before sketching, so the sketch can reference the variables.

Click the **Configuration** panel (left sidebar, the ⚙/slider icon) >
**Add configuration input**. Add five **Configuration variable** inputs, one at
a time. Set type **Length** for the four lengths and **Real** for the ratio:

| Name | Type | Default | Min | Max |
|---|---|---|---|---|
| `root_chord` | Length | `90 mm` | `50 mm` | `130 mm` |
| `taper_ratio` | Real | `0.5` | `0.2` | `1.0` |
| `semi_span` | Length | `60 mm` | `30 mm` | `90 mm` |
| `sweep_deg` | Angle | `30 deg` | `0 deg` | `60 deg` |
| `thickness` | Length | `3 mm` | `2 mm` | `5 mm` |

> **Names must match exactly** — lowercase, underscores. The code looks them up
> by these ids (`cad_ref` in `shared/fixtures/design_space_fin.json`).

Referencing them in a sketch or feature field uses a `#` prefix: `#root_chord`.

**Skip `edge_profile` for now.** It is a List input that suppresses/unsuppresses
a fillet and a chamfer, and it is the fiddliest part. Square edges are enough
for CP1 — see "Later" at the bottom.

## 2. Sketch the trapezoid (15 min)

1. **Sketch** on the **Front plane**.
2. Draw a four-sided closed polygon roughly the right shape — exact
   coordinates come from the dimensions, not the drawing.
3. Put the **root leading edge corner on the origin**.
4. Dimension it so the four corners land where B.5 says. With `x` chordwise
   (positive aft) and `z` spanwise (positive outward):

   | Corner | x | z |
   |---|---|---|
   | root LE | `0` | `0` |
   | root TE | `#root_chord` | `0` |
   | tip LE | `#semi_span * tan(#sweep_deg)` | `#semi_span` |
   | tip TE | `#semi_span * tan(#sweep_deg) + #root_chord * #taper_ratio` | `#semi_span` |

   The practical way: make the root edge horizontal on the x axis and dimension
   its length to `#root_chord`. Dimension the tip edge length to
   `#root_chord * #taper_ratio`. Dimension the perpendicular distance between
   root and tip edges to `#semi_span`. Then dimension the **angle of the
   leading edge** from the z axis to `#sweep_deg`.

   That is 4 dimensions and it fully constrains the trapezoid. The sketch
   should go black (fully constrained). **If it stays blue, it is
   under-constrained** and will regenerate unpredictably — fix it now.

5. Accept the sketch.

## 3. Extrude (3 min)

1. **Extrude** the sketch region.
2. End type: **Symmetric**.
3. Depth: `#thickness`.

Symmetric matters — B.5 puts the plate from `y = -t/2` to `+t/2`, and the STL
sanity check compares the bounding box against exactly that.

## 4. Check the corners (10 min, free)

In the Configuration panel, type values in and watch it regenerate. The UI does
not consume API calls, so check generously. Try at least these:

- defaults (90 / 0.5 / 60 / 30 / 3)
- all minimums (50 / 0.2 / 30 / 0 / 2)
- all maximums (130 / 1.0 / 90 / 60 / 5)
- `sweep_deg = 60` with `semi_span = 90` (largest overhang)
- `taper_ratio = 1.0` (rectangular, no taper)
- `taper_ratio = 0.2` with `root_chord = 50` (tiny tip chord)

**If any combination errors or produces nothing**, narrow that input's range in
the Configuration panel and write the new bounds down — the bounds are part of
the frozen contract, so S3 has to be told.

## 5. Hand off (1 min)

Copy the **browser URL** while the Part Studio tab is open. It looks like:

```
https://cad.onshape.com/documents/<did>/w/<wid>/e/<eid>
```

Send that URL to whoever is running the spike. It goes in
`~/.darwin_secrets.sh` as `DARWIN_FIN_DOC_URL`, then:

```bash
source ~/.darwin_secrets.sh
python -m cad.spike all        # ~6 calls, prints the verdict
```

The spike checks each exported STL's bounding box and volume against the
analytic formulas in `shared/fin_geometry.py`. If they agree, the cheap
configured-export path works and we are done.

---

## Later (after CP1): the `edge_profile` List input

1. Add a **Fillet** feature: full round, radius `#thickness / 2`, on the
   leading edge and tip edge.
2. Add a **Chamfer** feature on the leading and trailing edges, distance
   `min(3 * #thickness, 0.25 * #root_chord * #taper_ratio)`. The `min()` guard
   stops the chamfer exceeding the tip chord at small sizes.
3. Add a **Configuration input** of type **Configuration list** named
   `edge_profile` with options `square`, `rounded`, `beveled`.
4. In the configuration table, suppress both features for `square`, suppress
   the chamfer for `rounded`, and suppress the fillet for `beveled`.

Until this exists, keep runs on `square` or `rounded`: a square-edged model
measured against `rounded` params differs by only ~2 % in volume and passes the
6 % sanity tolerance, but `beveled` differs ~40 % and will trip `SANITY_FAIL`.
