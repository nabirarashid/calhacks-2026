"""Deterministic design-space sampling and non-critical disk caching."""

import hashlib
import json
import math
import os
import random
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from shared.contracts import DesignSpace, Goal, ParamSpec, ParamValue, Score, canonicalize


EvaluateFn = Callable[[DesignSpace, Dict[str, ParamValue], Goal], Score]
BatchEvaluateFn = Callable[..., List[Score]]

# Bump whenever scorer physics or serialization changes; this prevents a
# previously generated cloud from masquerading as results from a new model.
_CACHE_SCHEMA = 3  # 3: drag_n normalization changed (scores are cached, the catalog is not keyed)
DEFAULT_CACHE_DIR = Path(".darwin") / "landscape"


def _model_payload(model: Any) -> Dict[str, Any]:
    """Return a JSON-compatible Pydantic payload on v1 or v2."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())


def _score_from_payload(payload: Dict[str, Any]) -> Score:
    if hasattr(Score, "model_validate"):
        return Score.model_validate(payload)
    return Score.parse_obj(payload)


def _cache_key(space: DesignSpace, goal: Goal, n: int, seed: int) -> str:
    payload = {
        "schema": _CACHE_SCHEMA,
        "space": _model_payload(space),
        "goal": _model_payload(goal),
        "n": n,
        "seed": seed,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _cache_path(cache_dir: Path, space: DesignSpace, key: str) -> Path:
    safe_space_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", space.id)
    return cache_dir / ("%s-%s.json" % (safe_space_id, key))


def _integer_values(spec: ParamSpec) -> List[int]:
    if spec.min is None or spec.max is None:
        return [int(round(float(spec.default)))]
    lower = int(math.ceil(spec.min))
    upper = int(math.floor(spec.max))
    values = list(range(lower, upper + 1))
    return values or [int(round(float(spec.default)))]


def _discrete_values(spec: ParamSpec) -> List[ParamValue]:
    if spec.kind == "choice":
        return list(spec.choices or [str(spec.default)])
    return _integer_values(spec)


def latin_hypercube_params(
    space: DesignSpace, n: int, seed: int = 0
) -> List[Dict[str, ParamValue]]:
    """Generate exactly *n* canonical designs using only the standard library.

    Every continuous dimension visits each of ``n`` equal-width strata once.
    Each discrete dimension cycles through a seeded permutation of all allowed
    values, so category counts differ by at most one.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return []

    rng = random.Random(seed)
    columns = {}  # type: Dict[str, Sequence[ParamValue]]
    for spec in space.parameters:
        if spec.kind == "continuous":
            if spec.min is None or spec.max is None:
                raise ValueError("continuous parameter %s requires min and max" % spec.name)
            strata = list(range(n))
            rng.shuffle(strata)
            width = float(spec.max - spec.min)
            columns[spec.name] = [
                float(spec.min) + ((stratum + rng.random()) / n) * width
                for stratum in strata
            ]
        else:
            alternatives = _discrete_values(spec)
            if not alternatives:
                raise ValueError("discrete parameter %s has no alternatives" % spec.name)
            rng.shuffle(alternatives)
            columns[spec.name] = [alternatives[index % len(alternatives)] for index in range(n)]

    return [
        canonicalize(space, {spec.name: columns[spec.name][index] for spec in space.parameters})
        for index in range(n)
    ]


def _load_cache(
    path: Path, key: str, space: DesignSpace, expected_n: int
) -> Optional[List[Tuple[Dict[str, ParamValue], Score]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != _CACHE_SCHEMA or payload.get("key") != key:
            return None
        entries = payload["entries"]
        if len(entries) != expected_n:
            return None
        return [
            (canonicalize(space, entry["params"]), _score_from_payload(entry["score"]))
            for entry in entries
        ]
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _write_cache(
    path: Path, key: str, results: List[Tuple[Dict[str, ParamValue], Score]]
) -> None:
    payload = {
        "schema": _CACHE_SCHEMA,
        "key": key,
        "entries": [
            {"params": params, "score": _model_payload(score)}
            for params, score in results
        ],
    }
    temporary = path.with_suffix(path.suffix + ".tmp-%d" % os.getpid())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        os.replace(str(temporary), str(path))
    except (OSError, TypeError, ValueError):
        # Landscape data is an optimization.  A read-only or corrupt cache must
        # never stop the caller from receiving freshly evaluated results.
        try:
            temporary.unlink()
        except OSError:
            pass


def landscape(
    space: DesignSpace,
    goal: Goal,
    n: int = 2000,
    seed: int = 0,
    *,
    evaluate_fn: Optional[EvaluateFn] = None,
    batch_evaluate_fn: Optional[BatchEvaluateFn] = None,
    workers: int = 0,
    cache_dir: Optional[Path] = None,
) -> List[Tuple[Dict[str, ParamValue], Score]]:
    """Sample, evaluate, and cache a deterministic landscape.

    ``sim.api`` injects either ``evaluate_fn`` for serial evaluation or
    ``batch_evaluate_fn`` for batch/process-pool evaluation.  A cache hit needs
    neither callback.  Cache read/write failures are intentionally nonfatal.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if workers < 0:
        raise ValueError("workers must be non-negative")

    resolved_cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    key = _cache_key(space, goal, n, seed)
    path = _cache_path(resolved_cache_dir, space, key)
    cached = _load_cache(path, key, space, n)
    if cached is not None:
        return cached

    params_list = latin_hypercube_params(space, n, seed)
    if not params_list:
        scores = []  # type: List[Score]
    elif batch_evaluate_fn is not None:
        scores = batch_evaluate_fn(space, params_list, goal, workers=workers)
    elif evaluate_fn is not None:
        scores = [evaluate_fn(space, params, goal) for params in params_list]
    else:
        raise ValueError("evaluate_fn or batch_evaluate_fn is required on a cache miss")

    if len(scores) != n:
        raise ValueError("evaluator returned %d scores for %d designs" % (len(scores), n))
    results = list(zip(params_list, scores))
    _write_cache(path, key, results)
    return results
