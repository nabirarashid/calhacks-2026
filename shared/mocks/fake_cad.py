"""Fake CAD with the same signatures as cad.api (PLAN.md B.7 / B.10). Zero network.

Writes a real ASCII STL of the square-edged plate (B.5 frame) to
.darwin/geometry_mock/ (never the real cad cache). Cache misses sleep FAKE_CAD_LATENCY seconds (default 1.7). About 5 % of
geometry keys fail deterministically with regen_status "ERROR". Keeps a fake
ledger that starts at 2400 calls with reserve 400.
"""
import json
import os
import threading
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from shared import fin_geometry
from shared.contracts import (
    DesignSpace, GeometryRef, OnshapeBudget, ParamValue, canonicalize, geometry_key,
)
from shared.manifest import (
    CadInventory, CheckResult, CommitPreview, GeometryEvidence, ProbeResult, ProjectManifest,
)

_FIXTURE_GEOMETRY = Path(__file__).resolve().parent.parent / "fixtures" / "geometry"
_lock = threading.Lock()
_ledger = {"session": 0, "total": 0}
START, RESERVE = 2400, 400


def cache_dir() -> Path:
    # Separate from cad/'s .darwin/geometry so a mock STL can never be served as an Onshape export.
    d = Path(os.environ.get("DARWIN_CACHE_DIR", ".darwin")) / os.environ.get("FAKE_CAD_SUBDIR", "geometry_mock")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _charge(n: int) -> bool:
    with _lock:
        if START - _ledger["total"] - n < RESERVE and os.environ.get("DARWIN_ALLOW_RESERVE") != "1":
            return False
        _ledger["session"] += n
        _ledger["total"] += n
        return True


def budget_status() -> OnshapeBudget:
    with _lock:
        remaining = START - _ledger["total"]
        unlocked = os.environ.get("DARWIN_ALLOW_RESERVE") == "1"
        return OnshapeBudget(account_label="mock", calls_session=_ledger["session"],
                             calls_ledger_total=_ledger["total"], remaining_estimate=remaining, reserve=RESERVE,
                             reserve_unlocked=unlocked, hard_stop=(remaining <= RESERVE and not unlocked))


def geometry_file(key: str) -> Optional[Path]:
    for d in (cache_dir(), _FIXTURE_GEOMETRY):
        p = d / ("%s.stl" % key)
        if p.exists():
            return p
    return None


def _read_ref(key: str) -> Optional[GeometryRef]:
    for d in (cache_dir(), _FIXTURE_GEOMETRY):
        side = d / ("%s.json" % key)
        if side.exists() and (d / ("%s.stl" % key)).exists():
            ref = GeometryRef.model_validate_json(side.read_text())
            return ref.model_copy(update={"source": "cache", "onshape_calls": 0, "elapsed_ms": 0.0})
    return None


def build_geometry(space: DesignSpace, params: Dict[str, ParamValue], *, allow_network: bool = True) -> GeometryRef:
    t0 = time.perf_counter()
    p = canonicalize(space, params)
    key = geometry_key(space, p)
    cached = _read_ref(key)
    if cached is not None:
        return cached
    if not allow_network:
        return GeometryRef(geometry_key=key, status="skipped", source="none", error="network_disabled")
    if not _charge(1):
        return GeometryRef(geometry_key=key, status="skipped", source="none", error="onshape_budget_reserve")
    time.sleep(float(os.environ.get("FAKE_CAD_LATENCY", "1.7")))
    elapsed = (time.perf_counter() - t0) * 1000.0
    if int(key, 16) % 20 == 0:
        return GeometryRef(geometry_key=key, status="failed", source="mock", onshape_calls=1,
                           regen_status="ERROR", error="mock regeneration failure", elapsed_ms=elapsed)
    stl = fin_geometry.prism_stl(p, name=key)
    d = fin_geometry.derived(dict(p, edge_profile="square"))
    ref = GeometryRef(geometry_key=key, status="ready", source="mock", stl_url="/api/geometry/%s.stl" % key,
                      bbox_mm=[round(x, 3) for x in fin_geometry.bbox_mm(p)], volume_mm3=round(d["volume_mm3"], 1),
                      triangles=12, onshape_calls=1, regen_status="OK", elapsed_ms=elapsed)
    out = cache_dir()
    (out / ("%s.stl" % key)).write_text(stl)
    (out / ("%s.json" % key)).write_text(ref.model_dump_json(indent=2))
    return ref


def commit_to_document(space: DesignSpace, params: Dict[str, ParamValue]) -> GeometryRef:
    ref = build_geometry(space, params)
    if ref.status == "skipped":
        return ref
    _charge(1)
    return ref.model_copy(update={"onshape_calls": ref.onshape_calls + 1})


def discover_design_space(doc_url: str, *, probe: bool = False) -> DesignSpace:
    path = Path(__file__).resolve().parent.parent / "fixtures" / "design_space_fin.json"
    space = DesignSpace.model_validate_json(path.read_text())
    _charge(1 + (4 if probe else 0))
    return space.model_copy(update={"id": "discovered_v1", "scorer": "", "discovered": True,
                                    "notes": ["mock discovery: returned the fin_v1 parameters"]})


def export_print_package(space: DesignSpace, params: Dict[str, ParamValue], out_dir: Path) -> Path:
    p = canonicalize(space, params)
    ref = build_geometry(space, p)
    out_dir.mkdir(parents=True, exist_ok=True)
    zpath = out_dir / ("darwin_print_%s.zip" % ref.geometry_key)
    card = ["# Darwin print card (mock)", "", "- design key: %s" % ref.geometry_key,
            "- PLA, 0.2 mm layers, 100 % infill, no supports, lay flat",
            "- params: %s" % json.dumps(p)]
    with zipfile.ZipFile(zpath, "w") as z:
        src = geometry_file(ref.geometry_key)
        if src is not None:
            z.write(src, "fin.stl")
        z.writestr("print_card.md", "\n".join(card) + "\n")
    return zpath


# ---------------------------------------------------------------- contracts v2 (PLAN.md v3 B.4, B.9)

def inspect(doc_url: str) -> CadInventory:
    """Read-only inventory from the v2 fixtures, chosen by URL substring (bracket / heat sink / duct)."""
    from shared.mocks import make_fixtures_v2 as fx
    u = doc_url.lower()
    _charge(6)
    if "duct" in u or "nozzle" in u:
        return fx.inventory_duct()
    if "heat" in u or "sink" in u:
        return fx.inventory_heatsink()
    return fx.inventory_bracket()


def probe(manifest: ProjectManifest, cases: List[Dict[str, ParamValue]]) -> List[ProbeResult]:
    """Regenerate each case (<= 9). The bracket space gets an L-shaped STL; others the fin plate."""
    from shared.mocks import make_fixtures_v2 as fx
    space = manifest.design_space
    out = []
    for i, values in enumerate(cases[:9]):
        p = canonicalize(space, values)
        key = geometry_key(space, p)
        if space.id == "bracket_v1":
            (cache_dir() / ("%s.stl" % key)).write_text(fx.bracket_stl(p))
            ref = GeometryRef(geometry_key=key, status="ready", source="mock", stl_url="/api/geometry/%s.stl" % key,
                              onshape_calls=1, regen_status="OK", elapsed_ms=300.0)
            _charge(1)
        else:
            ref = build_geometry(space, p)
        ok = ref.status == "ready"
        checks = [CheckResult(id="parse", passed=ok), CheckResult(id="watertight", passed=ok),
                  CheckResult(id="nonzero_volume", passed=ok)]
        case = "seed" if i == 0 else "case:%d" % i
        out.append(ProbeResult(case=case, params=p, geometry=ref, evidence=GeometryEvidence(
            geometry_key=key, parse_ok=ok, watertight=ok, checks=checks)))
    return out


def preview_commit(manifest: ProjectManifest, params: Dict[str, ParamValue],
                   current: Optional[Dict[str, ParamValue]] = None) -> CommitPreview:
    """What a commit would do; no writes, no calls."""
    space = manifest.design_space
    new = canonicalize(space, params)
    old = canonicalize(space, current or {p.name: p.default for p in space.parameters})
    diff = [{"name": p.name, "from": old[p.name], "to": new[p.name], "unit": p.unit}
            for p in space.parameters if p.cad_driven and old[p.name] != new[p.name]]
    blocked = None if manifest.authority.maturity >= 4 else "project is level %d; writes need level 4" \
        % manifest.authority.maturity
    return CommitPreview(target=manifest.name + " (isolated write copy)", param_diff=diff, expected_calls=7,
                         checks_planned=["read back values", "regenerate", "geometry sanity", "protected interfaces",
                                         "create version"], maturity=manifest.authority.maturity,
                         blocked_reason=blocked)
