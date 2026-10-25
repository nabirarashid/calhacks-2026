"""rocket_fin domain pack (PLAN.md v3 P1-B3). Owner: W-B. Minimal version written by W-C for Phase 1."""
import os
from pathlib import Path
from typing import Dict, List

from shared.manifest import BlockingQuestion, CadInventory, SourceRef

from domains.rocket_fin.goal_rules import body_tube_rule
from domains.rocket_fin.verifier import VERIFIER

_HERE = Path(__file__).resolve().parent
_SIGNATURE = {"root_chord", "taper_ratio", "semi_span", "sweep_deg", "thickness"}


class RocketFinPack:
    pack_id = "rocket_fin"
    version = "1.0.0"
    solver_ids = ["fin_v1"]
    verifier = VERIFIER
    questions = [
        BlockingQuestion(id="reference_rocket", field="load_cases[0]", required_for=3,
                         prompt="Which rocket do the fins fly on (body diameter and length, mass without fins, CG)?",
                         why="Stability and drag are relative to the rocket body."),
        BlockingQuestion(id="design_velocity", field="design_space.context.design_velocity_mps", required_for=3,
                         prompt="What is the maximum velocity the fins must survive?",
                         why="Flutter margin is computed at this speed."),
        BlockingQuestion(id="material", field="material", required_for=3,
                         prompt="Which material are the fins made of, and from which source?",
                         why="Mass and flutter depend on density and shear modulus."),
    ]  # type: List[BlockingQuestion]
    prompt_fragment = (_HERE / "prompts.md").read_text()
    headline_metrics = ["drag_n", "stability_margin_cal"]
    mass_metric = "fin_mass_total_g"
    goal_context_keys = ("body_diameter_mm", "design_velocity_mps", "mass_without_fins_g")
    limitations = [
        "The fin model assumes subsonic, low-incidence flow and a fixed reference rocket.",
        "The flutter result is a screening estimate and the material model assumes isotropic solid PLA.",
    ]
    sources = [SourceRef(kind="project_doc", source_id="sim/PHYSICS.md", title="Darwin fin physics")]
    renderer = "fin_morph"
    # Words users say -> parameters (the goal parser's deterministic "you can change X" reading).
    param_aliases = {
        "root chord": ["root_chord"], "chord": ["root_chord"], "taper": ["taper_ratio"],
        "semi span": ["semi_span"], "span": ["semi_span"], "height": ["semi_span"], "sweep": ["sweep_deg"],
        "thickness": ["thickness"], "fin count": ["fin_count"], "number of fins": ["fin_count"],
        "edge": ["edge_profile"],
    }

    def principles(self) -> List[Dict[str, str]]:
        """The fin's knowledge layer: the P-FIN-* blocks of the shared aero file plus dynamic-pressure
        scaling (the wing-only ones would mislead the planner). DARWIN_KNOWLEDGE=off removes it."""
        if os.environ.get("DARWIN_KNOWLEDGE", "on").lower() == "off":
            return []
        from domains.aero.pack import _HERE as AERO, parse_principles
        return [p for p in parse_principles((AERO / "principles.md").read_text())
                if p["id"].startswith("P-FIN-") or p["id"] == "P-Q-SCALING"]

    def signature_match(self, inv: CadInventory) -> float:
        names = {c.id.lower() for c in inv.config_inputs} | {c.name.lower() for c in inv.config_inputs}
        return len(_SIGNATURE & names) / float(len(_SIGNATURE))

    def goal_rules(self, text, space, constraints, overrides, assumptions):
        return body_tube_rule(text, space, constraints, overrides, assumptions)


PACK = RocketFinPack()
