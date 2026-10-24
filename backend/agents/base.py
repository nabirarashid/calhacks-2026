"""Helpers shared by the agent roles: prompt loading, the input-block convention,
run history, and the numeric-claim check."""
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from shared.contracts import DesignResult, DesignSpace, Directive, Goal

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_cache = {}  # type: Dict[str, str]


def system_prompt(role: str) -> str:
    if role not in _cache:
        _cache[role] = (PROMPTS / ("%s.md" % role)).read_text()
    return _cache[role]


def user_message(instruction: str, block: Dict[str, Any]) -> str:
    """Every role's user message ends with a ```json block (the mock provider parses it)."""
    return "%s\n\n```json\n%s\n```" % (instruction, json.dumps(block, separators=(",", ":"), default=str))


class RunHistory:
    """Everything the agents may look at. Mutated only by the run loop thread."""

    def __init__(self, space: DesignSpace, goal: Goal, generations: int) -> None:
        self.space = space
        self.goal = goal
        self.generations = generations
        self.designs = []  # type: List[DesignResult]
        self.by_id = {}  # type: Dict[str, DesignResult]
        self.hashes = set()  # type: set
        self.generation = 0
        self.champion = None  # type: Optional[DesignResult]
        self.best_by_gen = []  # type: List[float]
        self.stagnation = 0
        self.insights = []  # type: List[str]
        self.directive = Directive(mode="explore", n_explore=4, step_scale=0.2, reason="first generation")

    def add(self, d: DesignResult) -> None:
        self.designs.append(d)
        self.by_id[d.design_id] = d
        self.hashes.add(d.param_hash)

    def top(self, k: int) -> List[DesignResult]:
        return sorted(self.designs, key=lambda d: d.score.aggregate, reverse=True)[:k]

    def last_generation(self) -> List[DesignResult]:
        return [d for d in self.designs if d.generation == self.generation]


def goal_metrics(goal: Goal) -> List[str]:
    names = [o.metric for o in goal.objectives] + [c.ref for c in goal.constraints if not c.ref.startswith("param:")]
    return list(dict.fromkeys(names))


def compact_design(d: DesignResult, metrics: Iterable[str]) -> Dict[str, Any]:
    return {"design_id": d.design_id, "params": d.params, "aggregate": round(d.score.aggregate, 4),
            "feasible": d.score.feasible,
            "metrics": {m: round(d.score.metrics[m], 3) for m in metrics if m in d.score.metrics},
            "violations": [v.ref for v in d.score.violations]}


def compact_specs(space: DesignSpace) -> List[Dict[str, Any]]:
    out = []
    for p in space.parameters:
        s = {"name": p.name, "kind": p.kind, "unit": p.unit, "description": p.description}  # type: Dict[str, Any]
        if p.kind == "choice":
            s["choices"] = p.choices
        else:
            s["min"], s["max"] = p.min, p.max
        out.append(s)
    return out


# ---------------------------------------------------------------- numeric-claim check

_NUM = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?")


def _numbers(obj: Any, out: List[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(float(x) for x in _NUM.findall(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _numbers(k, out)
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)


def unverified_numbers(text: str, source: Any, rel_tol: float = 0.02) -> List[str]:
    """Numbers in `text` that match no number in `source` within 2 % (small integers allowed)."""
    known = []  # type: List[float]
    _numbers(source, known)
    bad = []
    for tok in _NUM.findall(text):
        x = float(tok)
        if x.is_integer() and abs(x) <= 10:
            continue
        if not any(abs(x - k) <= rel_tol * max(abs(k), 1e-9) or abs(x - k) < 1e-6 for k in known):
            bad.append(tok)
    return bad


def scrub_claims(text: str, source: Any) -> Tuple[str, List[str]]:
    """Replace unverified numbers with [?]; returns (clean_text, removed_tokens)."""
    bad = unverified_numbers(text, source)
    clean = text
    for tok in set(bad):
        clean = re.sub(r"(?<![A-Za-z_\d.])%s(?![\d])" % re.escape(tok), "[?]", clean)
    return clean, bad
