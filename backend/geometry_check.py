"""Geometry check: does the CAD Onshape built match what the solver assumed? Owner: W-C.

The solver computes from parameters, not from the CAD, so a parameter the Part Studio ignores (Sat 19:30:
chord) makes the solver's result for it fiction. After every write the session measures the Part Studio
(bounding box + part volumes, see cad.variables.measure_parts) and compares with the last measurement:

- span: the wing parts' measured width must equal `span_mm` (exact; the wing is a straight extrusion;
  the endplates sit outside it, so the overall box is span + their thickness).
- endplates: their volume must scale exactly with `endplate_height_mm` (when chord, which also sizes
  them, didn't change in the same step).
- every other parameter: if a step changed parameters and no wing part moved or changed volume, those
  parameters don't drive the geometry. The session locks them for the rest of the run and says so. (Part
  boxes, not the overall box: the endplates enclose the wing, so a rotating flap is invisible overall.)
"""
from typing import Any, Dict, List, Tuple

SPAN_TOL_MM = 2.0          # measured width vs span_mm
EP_TOL = 0.01              # endplate volume ratio vs height ratio
MOVED_MM = 0.05            # a bbox coordinate change smaller than this is "nothing moved"
MOVED_VOL = 0.0005         # likewise a relative part-volume change


def _width(m: Dict[str, Any]) -> float:
    boxes = list(m.get("parts", {}).values()) or [m["bbox"]]
    return max(b[4] for b in boxes) - min(b[1] for b in boxes)


def moved(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
    for pid, box in after.get("parts", {}).items():
        old = before.get("parts", {}).get(pid)
        if old is None or any(abs(a - b) > MOVED_MM for a, b in zip(old, box)):
            return True
    for pid, v in after["volumes"].items():
        old = before["volumes"].get(pid)
        if old is None or abs(v - old) > MOVED_VOL * max(abs(old), 1.0):
            return True
    return set(before["volumes"]) != set(after["volumes"])


def compare(before: Dict[str, Any], after: Dict[str, Any], old: Dict[str, float], new: Dict[str, float],
            params: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """(problems for the user, parameters that don't drive the CAD). `old`/`new` = values this step changed;
    `params` = every value now."""
    problems = []  # type: List[str]
    if "span_mm" in params and (after.get("parts") or after.get("bbox")):
        w = _width(after)
        if abs(w - float(params["span_mm"])) > SPAN_TOL_MM:
            problems.append("Onshape's wing is %.0f mm wide but the solver assumes span %.0f mm." % (w, params["span_mm"]))
    eps = [pid for pid, role in after.get("roles", {}).items() if role == "endplate"]
    if "endplate_height_mm" in new and "chord_mm" not in new and eps and old.get("endplate_height_mm"):
        want = float(new["endplate_height_mm"]) / float(old["endplate_height_mm"])
        got = [after["volumes"][p] / before["volumes"][p] for p in eps if before["volumes"].get(p)]
        if got and any(abs(g - want) > EP_TOL * want for g in got):
            problems.append("Endplates changed by %.0f%% in Onshape but the solver assumed %.0f%%."
                            % (100 * (sum(got) / len(got) - 1), 100 * (want - 1)))
    dead = sorted(new) if new and not moved(before, after) else []
    return problems, dead
