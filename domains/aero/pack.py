"""aero domain pack (PLAN.md B.8). Content: W-B (principles.md). Parser and wiring: W-C."""
import os
import re
from pathlib import Path
from typing import Dict, List

from shared.manifest import CadInventory, SourceRef

_HERE = Path(__file__).resolve().parent
_BLOCK = re.compile(r"^### (P-[A-Z0-9-]+)\s*$")
_FIELDS = ("statement", "applies_when", "effects", "levers", "source")


def parse_principles(text: str) -> List[Dict[str, str]]:
    """Parse '### P-ID' blocks with 'key: value' lines. Unknown keys are ignored; ids must be unique."""
    out, cur = [], None  # type: List[Dict[str, str]], Dict[str, str]
    for line in text.splitlines():
        m = _BLOCK.match(line)
        if m:
            cur = {"id": m.group(1)}
            out.append(cur)
            continue
        if cur is not None and ":" in line and not line.startswith(("#", "<!--")):
            key, _, value = line.partition(":")
            if key.strip() in _FIELDS:
                cur[key.strip()] = value.strip()
    ids = [p["id"] for p in out]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate principle ids in principles.md")
    missing = [p["id"] for p in out if any(f not in p for f in _FIELDS)]
    if missing:
        raise ValueError("principles missing fields: %s" % ", ".join(missing))
    return out


class AeroPack:
    pack_id = "aero"
    version = "0.1.0"
    solver_ids = ["rear_wing_v1", "fin_v1"]
    verifier = None                      # wing geometry is analytic; CAD checks live in cad/
    questions = []                       # type: list
    headline_metrics = ["downforce_n", "drag_n"]
    limitations = [
        "Lifting-surface aerodynamics (AeroBuildup/VLM with NeuralFoil polars): subsonic, attached flow, "
        "no ground effect; predictions past stall are not reliable.",
        "Screening-level results for ranking design moves; final sign-off needs CFD or a wind tunnel.",
    ]
    sources = [SourceRef(kind="project_doc", source_id="domains/aero/principles.md", title="Darwin aero principles")]
    renderer = None
    # Words users say -> parameters (the goal parser's deterministic "you can change X" reading).
    param_aliases = {
        "angle of attack": ["aoa_deg"], "aoa": ["aoa_deg"], "angle": ["aoa_deg"], "incidence": ["aoa_deg"],
        "pitch": ["aoa_deg"], "span": ["span_mm"], "width": ["span_mm"], "chord": ["chord_mm"],
        "flap angle": ["flap_angle_deg"], "flap deflection": ["flap_angle_deg"],
        "flap chord": ["flap_chord_frac"], "flap size": ["flap_chord_frac"],
        "flap": ["flap_angle_deg"],          # conservative: resizing the flap needs "flap chord"/"flap size"
        "endplate": ["endplate_height_mm"],
        "end plate": ["endplate_height_mm"],
    }

    @property
    def prompt_fragment(self) -> str:
        """Only the "## all" intro. The principles reach the model solely through the investigator's
        plan input, so DARWIN_KNOWLEDGE=off really removes them (the ablation)."""
        text = (_HERE / "principles.md").read_text()
        return re.split(r"\n<!--|\n### ", text, maxsplit=1)[0].strip() + "\n"

    def principles(self) -> List[Dict[str, str]]:
        """The knowledge layer. DARWIN_KNOWLEDGE=off removes it (the proof-bench ablation)."""
        if os.environ.get("DARWIN_KNOWLEDGE", "on").lower() == "off":
            return []
        return parse_principles((_HERE / "principles.md").read_text())

    def signature_match(self, inv: CadInventory) -> float:
        want = {"aoa_deg", "span_mm", "chord_mm", "flap_angle_deg"}
        names = {c.name.lower() for c in inv.config_inputs} | {c.id.lower() for c in inv.config_inputs}
        return len(want & names) / float(len(want))


PACK = AeroPack()
