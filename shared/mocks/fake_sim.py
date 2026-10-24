"""Fake sim with the same signatures as sim.api (PLAN.md B.7 / B.10).

Real B.5 geometry, a Barrowman-style CP, flat-plate skin-friction drag and the
NACA TN 4197 flutter form give plausible magnitudes with no AeroSandbox and
~0.1 ms per eval. The aggregation rule is the frozen one from PLAN.md B.6.
Deterministic. NOT the physics we pitch; S2's sim/ is.
"""
import json
import math
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shared import fin_geometry
from shared.contracts import (
    DesignSpace, Goal, MetricInfo, ParamValue, Score, Violation, canonicalize,
)

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "metric_catalog_fin.json"
_CATALOGS = {"fin_v1": [MetricInfo.model_validate(m) for m in json.loads(_CATALOG_PATH.read_text())]}
_SCORERS = {}  # type: Dict[str, object]

RHO_AIR = 1.225          # kg/m^3, sea level
NU_AIR = 1.46e-5         # m^2/s
P_ATM = 101325.0         # Pa
A_SOUND = 340.3          # m/s
BASE_DRAG = {"square": 0.25, "rounded": 0.12, "beveled": 0.02}   # x q x (t*s) per fin


def metric_catalog(scorer: str) -> List[MetricInfo]:
    return list(_CATALOGS[scorer])


def register_scorer(scorer_id: str, plugin: object) -> None:
    _SCORERS[scorer_id] = plugin


def _ctx(space: DesignSpace, goal: Optional[Goal]) -> Dict[str, float]:
    ctx = dict(space.context)
    if goal is not None:
        ctx.update(goal.context_overrides)
    return ctx  # type: ignore[return-value]


def fin_metrics(params: Dict[str, ParamValue], ctx: Dict[str, float]) -> Dict[str, float]:
    d = fin_geometry.derived(params)
    n = int(params.get("fin_count", 4))
    D = float(ctx["body_diameter_mm"])
    r = D / 2.0
    L = float(ctx["body_length_mm"])
    v = float(ctx["design_velocity_mps"])
    c_r, c_t, s = d["c_r"], d["c_t"], d["s"]

    # mass
    m_fin = d["volume_mm3"] / 1000.0 * float(ctx.get("density_g_cm3", 1.24))
    m_fins = m_fin * n

    # Barrowman CP (nose + fins; body tube adds no normal force)
    x_b = L - c_r                                            # fins flush with the aft end
    l_m = math.hypot(s, d["x_tip_le"] + c_t / 2.0 - c_r / 2.0)
    k_fb = 1.0 + r / (s + r)
    cna_f = k_fb * (4.0 * n * (s / D) ** 2) / (1.0 + math.sqrt(1.0 + (2.0 * l_m / (c_r + c_t)) ** 2))
    x_f = (x_b + d["x_tip_le"] * (c_r + 2 * c_t) / (3 * (c_r + c_t))
           + ((c_r + c_t) - c_r * c_t / (c_r + c_t)) / 6.0)
    cna_n, x_n = 2.0, 0.466 * float(ctx["nose_length_mm"])
    cp = (cna_n * x_n + cna_f * x_f) / (cna_n + cna_f)

    # CG with fin mass at the planform centroid
    x_c = x_b + (c_r ** 2 + c_r * c_t + c_t ** 2 + d["x_tip_le"] * (c_r + 2 * c_t)) / (3 * (c_r + c_t))
    m0, cg0 = float(ctx["mass_without_fins_g"]), float(ctx["cg_without_fins_mm"])
    cg = (m0 * cg0 + m_fins * x_c) / (m0 + m_fins)

    # drag: turbulent flat plate x form factor + edge base drag
    q = 0.5 * RHO_AIR * v * v
    mac_m = d["mac_mm"] / 1000.0
    re = max(v * mac_m / NU_AIR, 1e4)
    cf = 0.074 / re ** 0.2
    tc = d["t"] / d["mac_mm"]
    ff = 1.0 + 2.0 * tc + 60.0 * tc ** 4
    wet = 2.0 * d["area_mm2"] / 1e6
    d_fin = q * wet * cf * ff + q * BASE_DRAG.get(str(params.get("edge_profile")), 0.25) * (d["t"] * s / 1e6)
    drag = d_fin * n * 1.1                                   # 10 % interference
    cd = drag / (q * math.pi * (r / 1000.0) ** 2)

    # flutter (NACA TN 4197 form, semi-span aspect ratio)
    ar = s * s / d["area_mm2"]
    lam = c_t / c_r
    g_pa = float(ctx.get("shear_modulus_gpa", 1.3)) * 1e9
    denom = (1.337 * ar ** 3 * P_ATM * (lam + 1.0)) / (2.0 * (ar + 2.0) * (d["t"] / c_r) ** 3)
    v_f = A_SOUND * math.sqrt(g_pa / denom)

    return {
        "stability_margin_cal": (cp - cg) / D, "cp_mm": cp, "cg_mm": cg,
        "drag_n": drag, "cd_fins": cd,
        "fin_mass_g": m_fin, "fin_mass_total_g": m_fins,
        "flutter_velocity_mps": v_f, "flutter_margin": v_f / v,
        "cn_alpha_fins": cna_f, "aft_overhang_mm": d["aft_overhang_mm"],
        "planform_area_cm2": d["area_mm2"] / 100.0,
    }


# ---------------------------------------------------------------- frozen aggregation rule (B.6)

def objective_score(x: float, direction: str, info: MetricInfo, target: Optional[float],
                    tolerance: Optional[float]) -> float:
    lo, hi = info.typical_min, info.typical_max
    frac = min(1.0, max(0.0, (x - lo) / (hi - lo)))
    if direction == "maximize":
        return frac
    if direction == "minimize":
        return 1.0 - frac
    t = target if target is not None else (info.default_target if info.default_target is not None else (lo + hi) / 2)
    tol = tolerance or info.default_tolerance or (hi - lo) / 4.0
    return max(0.0, 1.0 - abs(x - t) / tol)


def aggregate(space: DesignSpace, params: Dict[str, ParamValue], metrics: Dict[str, float], goal: Goal,
              catalog: List[MetricInfo]) -> Tuple[Dict[str, float], List[Violation], bool, float]:
    info = {m.name: m for m in catalog}
    obj = {}  # type: Dict[str, float]
    num = den = 0.0
    for o in goal.objectives:
        s = objective_score(metrics[o.metric], o.direction, info[o.metric], o.target, o.tolerance)
        obj[o.metric] = s
        num += o.weight * s
        den += o.weight

    viols = []  # type: List[Violation]
    checks = [(c.ref, c.op, c.value, c.hard) for c in goal.constraints]
    for name, val in goal.fixed_params.items():
        if isinstance(val, (int, float)):
            checks.append(("param:" + name, "==", float(val), True))
        elif params.get(name) != val:      # choice pin: any mismatch is a full violation
            viols.append(Violation(ref="param:" + name, op="==", limit=0.0, actual=1.0, amount=1.0, hard=True))
    for ref, op, limit, hard in checks:
        if ref.startswith("param:"):
            p = space.param(ref[6:])
            actual = float(params[p.name])
            span = (p.max - p.min) if (p.max is not None and p.min is not None and p.max > p.min) else 1.0
        else:
            actual = metrics[ref]
            span = info[ref].typical_max - info[ref].typical_min
        ok = (actual <= limit + 1e-9) if op == "<=" else (actual >= limit - 1e-9) if op == ">=" \
            else abs(actual - limit) <= max(1e-6, 1e-3 * span)
        if not ok:
            viols.append(Violation(ref=ref, op=op, limit=limit, actual=actual,
                                   amount=abs(actual - limit) / span, hard=hard))
    hard_sum = sum(v.amount for v in viols if v.hard)
    soft_sum = sum(v.amount for v in viols if not v.hard)
    feasible = not any(v.hard for v in viols)
    agg = (num / den if den else 0.0) - 0.1 * soft_sum if feasible else -hard_sum - 0.1 * soft_sum
    return obj, viols, feasible, agg


def _warnings(space: DesignSpace, params: Dict[str, ParamValue]) -> List[str]:
    out = []
    for p in space.parameters:
        if p.kind == "continuous" and p.min is not None and p.max is not None:
            x = float(params[p.name])
            if x <= p.min + 1e-9:
                out.append("%s at lower bound" % p.name)
            elif x >= p.max - 1e-9:
                out.append("%s at upper bound" % p.name)
    return out


# ---------------------------------------------------------------- public API (mirrors sim.api)

def evaluate(space: DesignSpace, params: Dict[str, ParamValue], goal: Goal, fidelity: str = "fast") -> Score:
    t0 = time.perf_counter()
    p = canonicalize(space, params)
    metrics = fin_metrics(p, _ctx(space, goal))
    if fidelity == "high":      # pretend a slower method: small deterministic shifts
        metrics = dict(metrics, drag_n=metrics["drag_n"] * 1.04, cn_alpha_fins=metrics["cn_alpha_fins"] * 0.97)
    obj, viols, feasible, agg = aggregate(space, p, metrics, goal, metric_catalog(space.scorer))
    warns = _warnings(space, p)
    if fidelity == "high":
        warns.append("hifi(mock): drag +4.0 %, CNa -3.0 % vs fast model")
    return Score(metrics={k: round(v, 4) for k, v in metrics.items()}, objective_scores=obj, violations=viols,
                 feasible=feasible, aggregate=round(agg, 5), warnings=warns, fidelity=fidelity,  # type: ignore[arg-type]
                 eval_ms=(time.perf_counter() - t0) * 1000.0)


def evaluate_batch(space: DesignSpace, params_list: List[Dict[str, ParamValue]], goal: Goal,
                   workers: int = 0) -> List[Score]:
    return [evaluate(space, p, goal) for p in params_list]


def _dominates(a: List[float], b: List[float]) -> bool:
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def pareto_ranks(scores: List[Score], goal: Goal) -> List[int]:
    """Non-dominated sorting over objective_scores; infeasible designs ranked after all feasible."""
    keys = [o.metric for o in goal.objectives]
    ranks = [-1] * len(scores)
    groups = [[i for i, s in enumerate(scores) if s.feasible], [i for i, s in enumerate(scores) if not s.feasible]]
    base = 0
    for group in groups:
        remaining = list(group)
        rank = base
        while remaining:
            vec = {i: [scores[i].objective_scores.get(k, 0.0) for k in keys] for i in remaining}
            front = [i for i in remaining if not any(_dominates(vec[j], vec[i]) for j in remaining if j != i)]
            for i in front:
                ranks[i] = rank
            remaining = [i for i in remaining if i not in front]
            rank += 1
        base = rank
    return ranks


def pareto_front(scores: List[Score], goal: Goal) -> List[int]:
    return [i for i, r in enumerate(pareto_ranks(scores, goal)) if r == 0]


def sensitivity(space: DesignSpace, params: Dict[str, ParamValue], goal: Goal) -> Dict[str, Dict[str, float]]:
    """{param: {metric: d(metric)/d(param) x param_range}} by central differences (+/- 5 % of range)."""
    p0 = canonicalize(space, params)
    ctx = _ctx(space, goal)
    out = {}  # type: Dict[str, Dict[str, float]]
    for spec in space.parameters:
        if spec.kind != "continuous" or spec.min is None or spec.max is None:
            continue
        span = spec.max - spec.min
        h = 0.05 * span
        lo = dict(p0, **{spec.name: max(spec.min, float(p0[spec.name]) - h)})
        hi = dict(p0, **{spec.name: min(spec.max, float(p0[spec.name]) + h)})
        dx = float(hi[spec.name]) - float(lo[spec.name])
        if dx <= 0:
            continue
        m_lo, m_hi = fin_metrics(lo, ctx), fin_metrics(hi, ctx)
        out[spec.name] = {k: round((m_hi[k] - m_lo[k]) / dx * span, 5) for k in m_lo}
    return out


def random_params(space: DesignSpace, rng: random.Random) -> Dict[str, ParamValue]:
    out = {}  # type: Dict[str, ParamValue]
    for p in space.parameters:
        if p.kind == "choice":
            out[p.name] = rng.choice(p.choices or [str(p.default)])
        elif p.kind == "integer":
            out[p.name] = rng.randint(int(p.min), int(p.max))  # type: ignore[arg-type]
        else:
            out[p.name] = rng.uniform(p.min, p.max)  # type: ignore[arg-type]
    return canonicalize(space, out)


def landscape(space: DesignSpace, goal: Goal, n: int = 2000, seed: int = 0) -> List[Tuple[Dict[str, ParamValue], Score]]:
    rng = random.Random(seed)
    pts = [random_params(space, rng) for _ in range(min(n, 500))]
    return [(p, evaluate(space, p, goal)) for p in pts]


def validate_high_fidelity(space: DesignSpace, params: Dict[str, ParamValue], goal: Goal) -> Score:
    return evaluate(space, params, goal, fidelity="high")
