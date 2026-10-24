# Rear wing Part Studio build guide (W-A A2)

This guide turns the frozen `rear_wing_v1` contract in `PLAN.md` B.5 and the W-A A2 checklist into a manual Onshape workflow. Build this in a development document. The Part Studio must be editable by the existing Variable-feature write path; keep the six Variable features at the top of the feature tree and give them the exact names below.

## 1. Create the six driving variables

In a new Part Studio, add one Onshape **Variable** feature per row. Enter the default as the Variable value. These are the accepted Darwin bounds and units; ordinary Onshape Variable features store an expression/value and do **not** encode or enforce the listed minimum and maximum. The application validates requested values against these bounds before writing. Keep the range table with the design and do not assume Onshape will prevent a manual out-of-range edit.

| Variable feature name | Default expression | Unit | Allowed range (Darwin contract) |
|---|---:|---|---:|
| `aoa_deg` | `6 deg` | deg | 0–16 |
| `span_mm` | `850 mm` | mm | 700–1000 |
| `chord_mm` | `280 mm` | mm | 200–350 |
| `flap_angle_deg` | `15 deg` | deg | 0–35 |
| `flap_chord_frac` | `0.30` | dimensionless | 0.20–0.40 |
| `endplate_height_mm` | `200 mm` | mm | 100–300 |

Use the exact spelling, underscores, and case. Put the features before all sketches and solid features so references are easy to audit. Do not create duplicate variables with the same names.

## 2. Establish a simple coordinate system

Use a rectangular wing centered on the origin. Let X run from leading edge to trailing edge, Y run spanwise, and Z be vertical. Place the section in the XZ plane and make the wing symmetric about the XZ plane so the span is split equally on both sides of Y=0. Keep the mount axis fixed in the model; the wing's angle of attack is a rotation about that axis. Keep mounts and ride height fixed as `PLAN.md` specifies.

For an inverted NACA 4412 section, use a NACA 4412 profile and invert it vertically in the sketch or with a fixed transform. The intended result is the inverted section at positive `#aoa_deg`, reported by the solver as downforce. Do not change the airfoil identity as a variable.

## 3. Main element

1. Create an empty sketch on the XZ plane for the main-element NACA 4412 profile. Use **Insert DXF/DWG**, choose millimetres before selecting the file, and import `cad/assets/naca4412_inverted_unit.dxf` with **Use file origin position** enabled. The file is already inverted and has a nominal one-unit chord. Apply the sketch's first dimension between its leading- and trailing-edge chord points and enter `#chord_mm`; Onshape uses the first dimension on an inserted DXF to scale the entire sketch. Constrain the leading-edge chord point to the chosen fixed datum.
2. Make the section symmetric about the vehicle centerline in span. Extrude the section symmetrically to total width `#span_mm` (use the Onshape symmetric extent option, or equivalent half-span on each side).
3. Rotate the main wing about the fixed mount axis by `#aoa_deg`. Arrange the feature order/references so changing `aoa_deg` changes only the wing orientation, not the mount locations or ride height. If your chosen sketch/extrude workflow makes a later transform more reliable, use a Move/Transform feature after the main solid and before attaching geometry that must follow the wing.
4. Regenerate after changing `chord_mm`, `span_mm`, and `aoa_deg` individually. Check that chord changes the section scale, span changes total span on both sides, and AoA rotates the wing about the intended axis.

## 4. Hinged trailing-edge flap

The flap is the trailing portion of the same NACA 4412 section, treated as a hinged flap—not a second isolated lifting surface. The solver does not model a flap slot or gap. Represent a shared hinge/split in the CAD model, with no modeled slot and no seventh variable.

1. In a second sketch on the section plane, draw a line through the profile at `#chord_mm * (1 - #flap_chord_frac)` aft of the leading-edge chord point. Extrude that line as a surface through the full span and use **Split Part** to separate the trailing portion from the main element.
2. Create a spanwise axis through the split line. Use it as the hinge axis for the flap; the two solids may share the hinge edge at zero deflection because the solver does not model the slot.
3. Rotate the flap around its hinge by `#flap_angle_deg`, with positive direction chosen consistently and checked at both 0 and 35 degrees. It should deflect relative to the main element, not rotate around the global origin.
4. Keep the hinge location and span fixed. Verify the feature regenerates at the default and at both flap-angle extremes. Avoid modeling it as an independent lifting surface separated by a slot or gap.

## 5. Endplates and fixed mounts

Create one endplate at each span tip. Their height is `#endplate_height_mm`; keep thickness and planform details fixed. Constrain the plates to the wing tips so they follow span changes while retaining the requested height. Keep the mount/upright geometry fixed in position and dimensions, attached to the chosen fixed mount datums. Do not drive mount locations or ride height with any of the six variables.

## 6. Recommended feature-tree order

Keep dependency order clear. A practical tree is:

1. Six Variable features (the exact names above).
2. Fixed datum planes/axes for the mount axis and centerline.
3. Main-element section sketch and symmetric extrusion.
4. Main-element AoA rotation about the mount axis.
5. Flap section/profile, symmetric extrusion, and hinge rotation.
6. Endplate sketches and extrusions at the span tips.
7. Fixed uprights/mounts.

If your feature dependencies require endplates before a transform, adjust the order while preserving the same behavior: endplates follow span, the flap follows main-wing AoA and deflects around its hinge, and mounts stay fixed. Name important sketches/features so a later reviewer can identify the main element, flap, endplates, and mounts.

## 7. Validate the full 64-corner envelope

There are six variables and two endpoints each, so test all `2^6 = 64` combinations. For each combination, set the six Variable values to the corresponding minimum or maximum, regenerate the Part Studio, and confirm there are no failed features, dangling references, or self-intersections that prevent the intended solids from regenerating. Onshape Variables do not provide a built-in 64-case range check; this is a manual acceptance check for A2.

Use this checklist as a record. Mark each row only after regeneration succeeds. The bit order is `aoa_deg, span_mm, chord_mm, flap_angle_deg, flap_chord_frac, endplate_height_mm`; `0` means minimum and `1` means maximum.

| Cases | Bit patterns |
|---|---|
| 1–8 | `000000`, `000001`, `000010`, `000011`, `000100`, `000101`, `000110`, `000111` |
| 9–16 | `001000`, `001001`, `001010`, `001011`, `001100`, `001101`, `001110`, `001111` |
| 17–24 | `010000`, `010001`, `010010`, `010011`, `010100`, `010101`, `010110`, `010111` |
| 25–32 | `011000`, `011001`, `011010`, `011011`, `011100`, `011101`, `011110`, `011111` |
| 33–40 | `100000`, `100001`, `100010`, `100011`, `100100`, `100101`, `100110`, `100111` |
| 41–48 | `101000`, `101001`, `101010`, `101011`, `101100`, `101101`, `101110`, `101111` |
| 49–56 | `110000`, `110001`, `110010`, `110011`, `110100`, `110101`, `110110`, `110111` |
| 57–64 | `111000`, `111001`, `111010`, `111011`, `111100`, `111101`, `111110`, `111111` |

After the corner sweep, restore all six defaults and regenerate. Confirm the final model has the expected main wing, hinged flap, two endplates, and fixed mounts. If any corner fails, identify which variable combination caused it and report the failing feature and combination to W-B before changing the frozen ranges.

## 8. Handoff to the API integration

Save the development Part Studio and copy its workspace URL. The URL is needed to bind the specific wing document later; do not put a guessed URL in the environment. Send W-A the workspace URL and confirm that all six Variable features are readable by exact name and that the default Part Studio regenerates.

For the demo setup, bind the wing workspace URL as `DARWIN_DOC_WING` in the local secrets/environment setup, and enable writes only for the intended development or production document through `DARWIN_ONSHAPE_WRITE_DOCS`. Keep the key allowlist and call-budget reserve behavior intact. A2 is complete when the model is editable, the 64-corner sweep passes, and the saved workspace URL is ready for the W-A live write/read-back/STL checks.

## Airfoil asset

`cad/assets/naca4412_inverted_unit.dxf` is the checked-in import asset. It is a closed, cosine-spaced, inverted NACA 4412 profile generated by `cad/generate_naca4412.py`; the focused asset test checks deterministic regeneration, realistic thickness, inverted camber and chord bounds. Do not substitute an unrelated airfoil file.
