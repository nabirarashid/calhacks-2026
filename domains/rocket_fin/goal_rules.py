"""Deterministic goal rules for the rocket_fin domain (moved from backend/agents/goal_parser.py)."""
import re
from typing import Any, Dict, List

from shared.contracts import Constraint, DesignSpace

_TUBE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|\s)?\s*(inch|in\b|\"|mm)\s*(?:diameter\s*)?(?:body\s*)?tube", re.I)


def body_tube_rule(text: str, space: DesignSpace, constraints: List[Constraint], overrides: Dict[str, Any],
                   assumptions: List[str]) -> List[Constraint]:
    """Deterministic reading of "fits a N-inch body tube" (units are code's job, not the model's).

    The tube is the rocket body the fins mount on, so it sets body_diameter_mm and means the fins
    must not hang past the aft end (aft_overhang_mm <= 0). It never limits a fin dimension: param
    constraints equal to the tube's diameter or radius are misreadings and are dropped.
    """
    m = _TUBE.search(text)
    if not m or "body_diameter_mm" not in space.context:
        return constraints
    d = float(m.group(1)) * (1.0 if m.group(2).lower() == "mm" else 25.4)
    if not 30.0 <= d <= 200.0:
        return constraints
    kept = [c for c in constraints if not (c.ref.startswith("param:") and any(
        abs(c.value - x) <= 0.01 * x for x in (d, d / 2.0)))]
    if abs(d - float(space.context["body_diameter_mm"])) > 0.05:
        overrides["body_diameter_mm"] = round(d, 2)
    if not any(c.ref == "aft_overhang_mm" for c in kept):
        kept.append(Constraint(ref="aft_overhang_mm", op="<=", value=0.0, hard=True,
                               label="Fins must not overhang the aft end"))
    assumptions.append("Read '%s' as the rocket body: %.1f mm diameter, fins may not overhang the aft end."
                       % (m.group(0).strip(), d))
    return kept
