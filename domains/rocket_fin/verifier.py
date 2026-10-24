"""Rocket-fin geometry verification (owner W-A).

Combines domain-neutral STL health checks with the fin's analytic bbox and
volume expectations. ``verify`` implements the frozen public contract, while
``verify_data`` supports the existing in-memory CAD path.
"""
from typing import Mapping

from cad import verify as generic_verify
from cad.stl import parse
from shared import fin_geometry
from shared.contracts import ParamValue, geometry_key
from shared.manifest import CheckResult, GeometryEvidence, ProjectManifest

BBOX_TOL_MM = 0.5
VOLUME_TOL_FRAC = 0.06


class FinGeometryVerifier:
    def verify(self, manifest: ProjectManifest,
               params: Mapping[str, ParamValue], stl_path: str) -> GeometryEvidence:
        key = geometry_key(manifest.design_space, dict(params))
        try:
            with open(stl_path, "rb") as fh:
                raw = fh.read()
            report = self.verify_data(params, raw)
            mesh = parse(raw)
        except Exception as exc:  # malformed or unavailable geometry blocks safely
            return GeometryEvidence(
                geometry_key=key, parse_ok=False, watertight=False,
                checks=[CheckResult(id="parse", passed=False, detail=str(exc))],
            )

        checks = [
            CheckResult(id="parse", passed=True),
            CheckResult(id="watertight", passed=report["checks"]["watertight"]["ok"]),
            CheckResult(id="nonzero_volume", passed=report["checks"]["nonzero_volume"]["ok"]),
            CheckResult(id="analytic_bbox", passed=report["checks"]["bbox"]["ok"],
                        detail="; ".join(r for r in report["reasons"] if "bbox" in r)),
            CheckResult(id="analytic_volume", passed=report["analytic_volume_ok"],
                        detail="; ".join(r for r in report["reasons"] if "volume" in r)),
        ]
        return GeometryEvidence(
            geometry_key=key, parse_ok=True,
            watertight=bool(report["checks"]["watertight"]["ok"]),
            volume_mm3=round(mesh.volume_mm3(), 3),
            bbox_mm=[round(v, 4) for v in mesh.bbox()],
            triangles=mesh.triangle_count, checks=checks,
        )

    def verify_data(self, params, raw):
        """Return the legacy in-memory shape consumed by ``cad.stl``."""
        mesh = parse(raw)
        expected_bbox = fin_geometry.bbox_mm(params)
        expected_volume = float(fin_geometry.derived(params)["volume_mm3"])
        health = generic_verify.verify(raw, expected_bbox_mm=expected_bbox,
                                       bbox_tolerance_mm=BBOX_TOL_MM)
        vol_delta = (abs(mesh.volume_mm3() - expected_volume) / expected_volume
                     if expected_volume > 0 else float("inf"))
        analytic_volume_ok = vol_delta <= VOLUME_TOL_FRAC
        reasons = []
        if not health["checks"]["watertight"]["ok"]:
            reasons.append("mesh is not watertight")
        if not health["checks"]["nonzero_volume"]["ok"]:
            reasons.append("mesh has zero volume")
        if not health["checks"]["bbox"]["ok"]:
            reasons.append("fin bbox differs from analytic prediction")
        if not analytic_volume_ok:
            reasons.append("volume differs from analytic prediction by %.1f%%" % (100 * vol_delta))
        return {"ok": not reasons, "reasons": reasons,
                "bbox_mm": mesh.bbox(), "volume_mm3": mesh.volume_mm3(),
                "expected_volume_mm3": expected_volume,
                "analytic_volume_ok": analytic_volume_ok,
                "checks": health["checks"]}


# Existing callers and the domain pack retain their established names.
FinVerifier = FinGeometryVerifier
VERIFIER = FinGeometryVerifier()
