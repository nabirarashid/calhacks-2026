"""Print a deterministic comparison table for the frozen ``fin_v1`` fixtures.

Run from the repository root with ``python -m sim.demo``.
"""

import itertools
import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Type, TypeVar

from shared.contracts import (
    DesignResult,
    DesignSpace,
    Goal,
    ParamValue,
    canonicalize,
)
from sim.api import evaluate_batch


ModelT = TypeVar("ModelT")
FIXTURES = Path(__file__).resolve().parents[1] / "shared" / "fixtures"


def _load_model(path: Path, model: Type[ModelT]) -> ModelT:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    validator = getattr(model, "model_validate", None)
    if validator is not None:
        return validator(data)
    # The repository pins Pydantic 2, but this keeps the standalone demo useful
    # in an older Pydantic 1 environment.
    return model.parse_obj(data)  # type: ignore[attr-defined,no-any-return]


def _corner_cases(space: DesignSpace) -> List[Tuple[str, Dict[str, ParamValue]]]:
    """Return all 2^N corners of the continuous parameter box.

    Choice and integer parameters remain at their frozen defaults. Corner bits
    follow design-space parameter order, with zero=min and one=max.
    """
    continuous = [parameter for parameter in space.parameters if parameter.kind == "continuous"]
    cases = []  # type: List[Tuple[str, Dict[str, ParamValue]]]
    for bits in itertools.product((0, 1), repeat=len(continuous)):
        values = {}  # type: Dict[str, ParamValue]
        for parameter, bit in zip(continuous, bits):
            bound = parameter.max if bit else parameter.min
            if bound is None:
                raise ValueError(
                    "continuous parameter %r is missing its %s bound"
                    % (parameter.name, "max" if bit else "min")
                )
            values[parameter.name] = bound
        cases.append(
            (
                "corner-" + "".join(str(bit) for bit in bits),
                canonicalize(space, values),
            )
        )
    return cases


def _cases(
    space: DesignSpace, example: DesignResult
) -> List[Tuple[str, Dict[str, ParamValue]]]:
    return [
        ("default", canonicalize(space, {})),
        ("example", canonicalize(space, example.params)),
    ] + _corner_cases(space)


def _format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("every table row must match the header width")
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]

    def render(row: Sequence[str]) -> str:
        return "  ".join(cell.rjust(width) for cell, width in zip(row, widths))

    separator = "  ".join("-" * width for width in widths)
    return "\n".join([render(headers), separator] + [render(row) for row in rows])


def main() -> None:
    space = _load_model(FIXTURES / "design_space_fin.json", DesignSpace)
    goal = _load_model(FIXTURES / "goal_example.json", Goal)
    example = _load_model(FIXTURES / "design_result_example.json", DesignResult)

    cases = _cases(space, example)
    scores = evaluate_batch(space, [params for _, params in cases], goal, workers=0)
    headers = (
        "design",
        "root",
        "taper",
        "span",
        "sweep",
        "thick",
        "edge",
        "n",
        "stab",
        "drag_N",
        "mass_g",
        "flutter",
        "agg",
        "ok",
        "warn",
    )
    rows = []  # type: List[Sequence[str]]
    warning_messages = set()
    for (label, params), score in zip(cases, scores):
        warning_messages.update(score.warnings)
        rows.append(
            (
                label,
                "%.1f" % float(params["root_chord"]),
                "%.2f" % float(params["taper_ratio"]),
                "%.1f" % float(params["semi_span"]),
                "%.1f" % float(params["sweep_deg"]),
                "%.1f" % float(params["thickness"]),
                str(params["edge_profile"]),
                str(int(params["fin_count"])),
                "%.3f" % score.metrics["stability_margin_cal"],
                "%.3f" % score.metrics["drag_n"],
                "%.2f" % score.metrics["fin_mass_total_g"],
                "%.2f" % score.metrics["flutter_margin"],
                "%.4f" % score.aggregate,
                "yes" if score.feasible else "no",
                str(len(score.warnings)),
            )
        )

    continuous_names = [
        parameter.name
        for parameter in space.parameters
        if parameter.kind == "continuous"
    ]
    print("fin_v1 fast-model comparison")
    print(
        "Corner bits (0=min, 1=max): %s; other parameters use defaults."
        % ", ".join(continuous_names)
    )
    print(_format_table(headers, rows))
    if warning_messages:
        print("\nWarnings (deduplicated):")
        for warning in sorted(warning_messages):
            print("- " + warning)


if __name__ == "__main__":
    main()
