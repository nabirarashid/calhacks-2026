"""Deterministic engineering evidence and human-approval records.

All numeric claims in this module are derived from the frozen run summary.  LLM
prose may be displayed elsewhere, but it never supplies a requirement result or
approval field here.
"""
import hashlib
import html
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _cache_root() -> Path:
    return Path(os.environ.get("DARWIN_CACHE_DIR", ".darwin"))


def _approval_path(run_id: str) -> Path:
    if not _SAFE_ID.match(run_id):
        raise ValueError("invalid run id")
    return _cache_root() / "approvals" / (run_id + ".json")


def _actual(design: Dict[str, Any], ref: str) -> Optional[float]:
    raw = design.get("params", {}).get(ref[6:]) if ref.startswith("param:") \
        else design.get("score", {}).get("metrics", {}).get(ref)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def requirement_results(goal: Dict[str, Any], design: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Evaluate every declared requirement directly against design data."""
    out = []  # type: List[Dict[str, Any]]
    for constraint in goal.get("constraints", []):
        ref = str(constraint.get("ref", ""))
        op = str(constraint.get("op", ""))
        limit = float(constraint.get("value", 0.0))
        actual = _actual(design, ref)
        passed = False
        margin = None  # type: Optional[float]
        if actual is not None and math.isfinite(actual):
            if op == "<=":
                margin, passed = limit - actual, actual <= limit + 1.0e-12
            elif op == ">=":
                margin, passed = actual - limit, actual + 1.0e-12 >= limit
            elif op == "==":
                margin, passed = -abs(actual - limit), math.isclose(actual, limit, rel_tol=1.0e-9, abs_tol=1.0e-9)
        out.append({
            "ref": ref,
            "label": str(constraint.get("label") or ref),
            "op": op,
            "limit": limit,
            "actual": actual,
            "margin": margin,
            "hard": bool(constraint.get("hard", True)),
            "passed": passed,
        })
    return out


def parameter_diff(seed: Optional[Dict[str, Any]], design: Dict[str, Any]) -> List[Dict[str, Any]]:
    before = (seed or {}).get("params", {})
    after = design.get("params", {})
    names = list(dict.fromkeys(list(before) + list(after)))
    return [{"name": name, "before": before.get(name), "after": after.get(name),
             "changed": before.get(name) != after.get(name)} for name in names]


def metric_diff(seed: Optional[Dict[str, Any]], design: Dict[str, Any]) -> List[Dict[str, Any]]:
    before = (seed or {}).get("score", {}).get("metrics", {})
    after = design.get("score", {}).get("metrics", {})
    names = list(dict.fromkeys(list(before) + list(after)))
    rows = []  # type: List[Dict[str, Any]]
    for name in names:
        old, new = before.get(name), after.get(name)
        delta = float(new) - float(old) if isinstance(old, (int, float)) and isinstance(new, (int, float)) else None
        rows.append({"name": name, "before": old, "after": new, "delta": delta})
    return rows


BINDING_KEYS = ("project_id", "manifest_revision", "manifest_hash", "cad_source_microversion", "solver")


def binding_for(manifest: Any) -> Dict[str, Any]:
    """The exact project state an approval binds to (PLAN.md v3 B.8). Any change expires it."""
    from shared.manifest import manifest_hash
    a = manifest.analysis
    solver = [{"adapter_id": x, "version": ""} for x in ([a.screening_adapter, a.verify_adapter] if a else [])
              if x]
    return {"project_id": manifest.project_id, "manifest_revision": manifest.revision,
            "manifest_hash": manifest_hash(manifest), "cad_source_microversion": manifest.cad.source_microversion,
            "solver": solver}


def evidence_hash(evidence: Dict[str, Any]) -> str:
    body = {k: v for k, v in evidence.items() if k != "approval"}
    return hashlib.sha1(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
                        .encode("utf-8")).hexdigest()[:12]


def load_approval(run_id: str, design: Optional[Dict[str, Any]] = None,
                  binding: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    path = _approval_path(run_id)
    try:
        record = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    if design is not None and (record.get("design_id") != design.get("design_id") or
                               record.get("param_hash") != design.get("param_hash")):
        return None
    if binding is not None and any(record.get("binding", {}).get(k) != binding.get(k) for k in BINDING_KEYS):
        return None      # the manifest, CAD revision or solver changed since approval
    return record


def approve(run_id: str, summary: Dict[str, Any], design: Dict[str, Any], approved_by: str = "engineer",
            binding: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    requirements = requirement_results(summary.get("goal", {}), design)
    if not design.get("score", {}).get("feasible") or any(r["hard"] and not r["passed"] for r in requirements):
        raise ValueError("only a design satisfying every hard requirement can be approved")
    geometry = design.get("geometry") or {}
    if geometry.get("status") != "ready" or geometry.get("regen_status") not in (None, "OK"):
        raise ValueError("approval requires ready, successfully regenerated geometry")
    record = {
        "status": "approved",
        "run_id": run_id,
        "design_id": design.get("design_id"),
        "param_hash": design.get("param_hash"),
        "approved_by": (approved_by or "engineer").strip()[:100],
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "goal": summary.get("goal", {}),
        "requirements": requirements,
        "params": design.get("params", {}),
        "score": design.get("score", {}),
        "geometry": geometry,
        "hifi_check": summary.get("hifi_check"),
    }
    if binding is not None:
        record["binding"] = binding
        record["evidence_hash"] = evidence_hash(build_evidence(run_id, summary, design))
    path = _approval_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)
    return record


GENERIC_LIMITATION = "This is optimization and simulation evidence, not safety certification."


def build_evidence(run_id: str, summary: Dict[str, Any], design: Dict[str, Any], project: Any = None,
                   pack: Any = None) -> Dict[str, Any]:
    score = design.get("score", {})
    analysis = design.get("analysis")
    return {
        "run_id": run_id,
        "status": summary.get("status"),
        "request": summary.get("goal", {}).get("source_text", ""),
        "assumptions": summary.get("goal", {}).get("assumptions", []),
        "design_id": design.get("design_id"),
        "param_hash": design.get("param_hash"),
        "parameter_diff": parameter_diff(summary.get("seed_design"), design),
        "metric_diff": metric_diff(summary.get("seed_design"), design),
        "requirements": requirement_results(summary.get("goal", {}), design),
        "score": design.get("score", {}),
        "geometry": design.get("geometry"),
        "hifi_check": summary.get("hifi_check"),
        "budget": summary.get("budget"),
        "degradations": summary.get("degradations", []),
        "approval": load_approval(run_id, design, binding_for(project) if project is not None else None),
        "project": None if project is None else {
            "project_id": project.project_id, "name": project.name, "revision": project.revision,
            "maturity": project.authority.maturity, "domain_pack": project.domain_pack},
        "fidelity": (analysis or {}).get("fidelity") or ("verification" if score.get("fidelity") == "high"
                                                         else "screening"),
        "analysis": analysis,
        "sources": [s.model_dump(mode="json") for s in getattr(pack, "sources", [])],
        "limitations": [GENERIC_LIMITATION] + list(getattr(pack, "limitations", [])),
    }


def render_html(evidence: Dict[str, Any], narrative: str = "") -> str:
    esc = lambda value: html.escape(str(value))
    params = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(row["name"]), esc(row["before"]), esc(row["after"]), "changed" if row["changed"] else "unchanged")
        for row in evidence["parameter_diff"])
    metrics = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(row["name"]), esc(row["before"]), esc(row["after"]),
        "—" if row["delta"] is None else "%+.4g" % row["delta"])
        for row in evidence["metric_diff"])
    requirements = "".join("<tr><td>%s</td><td>%s</td><td>%.4g</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(row["label"]), esc(row["op"]), row["limit"],
        "—" if row["actual"] is None else "%.4g" % row["actual"],
        "—" if row["margin"] is None else "%+.4g" % row["margin"], "PASS" if row["passed"] else "FAIL")
        for row in evidence["requirements"])
    assumptions = "".join("<li>%s</li>" % esc(item) for item in evidence["assumptions"])
    limitations = "".join("<li>%s</li>" % esc(item) for item in evidence["limitations"])
    geometry = evidence.get("geometry") or {}
    approval = evidence.get("approval")
    approval_text = ("Approved by %s at %s (parameter hash %s)." %
                     (esc(approval.get("approved_by")), esc(approval.get("approved_at")),
                      esc(approval.get("param_hash")))) if approval else "Not yet approved."
    hifi = evidence.get("hifi_check") or {}
    hifi_text = "PASS" if hifi.get("feasible") else ("FAIL" if hifi else "not available")
    hifi_warnings = "; ".join(str(item) for item in hifi.get("warnings", [])) or "none"
    budget = evidence.get("budget") or {}
    model_budget = budget.get("model") or {}
    onshape_budget = budget.get("onshape") or {}
    budget_text = ("%s/%s evaluations; %s Onshape calls this session; model spend $%s" %
                   (esc(budget.get("evals_used", "—")), esc(budget.get("evals_budget", "—")),
                    esc(onshape_budget.get("calls_session", "—")), esc(model_budget.get("spend_run_usd", "—"))))
    degradations = ", ".join(str(item) for item in evidence.get("degradations", [])) or "none"
    return """<!doctype html><meta charset=\"utf-8\"><title>Darwin evidence {run}</title>
<style>body{{font:14px system-ui;max-width:980px;margin:2rem auto;color:#172033}}h1,h2{{color:#0d172a}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}th,td{{border:1px solid #cbd5e1;padding:.45rem;text-align:left}}
.card{{border:1px solid #cbd5e1;border-radius:10px;padding:1rem;margin:1rem 0}}code{{font-size:12px}}</style>
<h1>Darwin engineering evidence</h1><p><b>Run:</b> <code>{run}</code> · <b>Design:</b> <code>{design}</code></p>
<div class=\"card\"><b>Engineering request</b><p>{request}</p><ul>{assumptions}</ul></div>
{narrative}<h2>Parameter diff</h2><table><tr><th>Parameter</th><th>Before</th><th>Candidate</th><th>Status</th></tr>{params}</table>
<h2>Performance diff</h2><table><tr><th>Metric</th><th>Before</th><th>Candidate</th><th>Delta</th></tr>{metrics}</table>
<h2>Requirement evaluation</h2><table><tr><th>Requirement</th><th>Operator</th><th>Limit</th><th>Actual</th><th>Margin</th><th>Result</th></tr>{requirements}</table>
<div class=\"card\"><b>CAD evidence:</b> {cad_status}; regeneration {regen}; geometry key <code>{geometry_key}</code>.<br>
<b>Higher-fidelity check:</b> {hifi}; warnings: {hifi_warnings}.<br><b>Budget:</b> {budget}.<br>
<b>Degradations:</b> {degradations}.<br><b>Approval:</b> {approval}</div>
<h2>Limitations</h2><ul>{limitations}</ul>""".format(
        run=esc(evidence["run_id"]), design=esc(evidence["design_id"]), request=esc(evidence["request"]),
        assumptions=assumptions, narrative=narrative, params=params, metrics=metrics, requirements=requirements,
        cad_status=esc(geometry.get("status", "unavailable")), regen=esc(geometry.get("regen_status", "unavailable")),
        geometry_key=esc(geometry.get("geometry_key", "unavailable")), hifi=esc(hifi_text),
        hifi_warnings=esc(hifi_warnings), budget=budget_text, degradations=esc(degradations),
        approval=approval_text, limitations=limitations)
