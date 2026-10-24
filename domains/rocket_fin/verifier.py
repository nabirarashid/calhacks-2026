"""rocket_fin GeometryVerifier (owner W-A): generic STL health + the fin's analytic bbox/volume check.

Wraps cad.stl's existing sanity check so the fin keeps its exact behavior; W-A's P1-A1 moves
the generic half into cad/verify.py and the analytic half here.
"""
from typing import Mapping

from shared.contracts import ParamValue, geometry_key
from shared.manifest import CheckResult, GeometryEvidence, ProjectManifest


class FinVerifier:
    def verify(self, m: ProjectManifest, params: Mapping[str, ParamValue], stl_path: str) -> GeometryEvidence:
        from cad import stl
        key = geometry_key(m.design_space, dict(params))
        try:
            mesh = stl.parse(open(stl_path, "rb").read())
        except Exception as e:  # noqa: BLE001 — unparseable geometry blocks, never passes
            return GeometryEvidence(geometry_key=key, parse_ok=False, watertight=False,
                                    checks=[CheckResult(id="parse", passed=False, detail=str(e))])
        ok, reasons = stl.sanity_check(dict(params), mesh)
        vol = mesh.volume_mm3()
        return GeometryEvidence(
            geometry_key=key, parse_ok=True, watertight=vol > 0, volume_mm3=round(vol, 3),
            bbox_mm=[round(v, 4) for v in mesh.bbox()], triangles=mesh.triangle_count,
            checks=[CheckResult(id="parse", passed=True), CheckResult(id="nonzero_volume", passed=vol > 0),
                    CheckResult(id="analytic_bbox_volume", passed=ok, detail="; ".join(reasons))])


VERIFIER = FinVerifier()
