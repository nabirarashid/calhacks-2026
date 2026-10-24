"""STL parsing, geometry measurement and the analytic sanity check (S1).

No network. Everything here is pure and testable against shared/fixtures/geometry/.

Onshape returns ASCII STL by default for Part Studio exports; binary is handled
as a fallback in case the Accept header or defaults change under us.
"""
import re
import struct
from typing import Dict, List, Optional, Tuple

from shared import fin_geometry
from shared.contracts import ParamValue

# "vertex 1.234e+01 -5.0e+00 0.0" — three floats after the keyword.
_FLOAT = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"
_VERTEX_RE = re.compile(r"vertex\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")")

# Sanity-check tolerances (PLAN.md S1: bbox within 0.5 mm, volume within 6 %).
BBOX_TOL_MM = 0.5
VOLUME_TOL_FRAC = 0.06

Triangle = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]


class StlParseError(ValueError):
    """Raised when bytes cannot be read as either ASCII or binary STL."""


class Mesh(object):
    """Triangle soup with the measurements S1 needs. Lengths in mm."""

    def __init__(self, triangles: List[Triangle]):
        if not triangles:
            raise StlParseError("STL contains no triangles")
        self.triangles = triangles

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    def bbox(self) -> List[float]:
        """[xmin, ymin, zmin, xmax, ymax, zmax]."""
        xs = []
        ys = []
        zs = []
        for tri in self.triangles:
            for v in tri:
                xs.append(v[0])
                ys.append(v[1])
                zs.append(v[2])
        return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]

    def volume_mm3(self) -> float:
        """Signed volume by the divergence theorem: sum of v0 . (v1 x v2) / 6.

        Returned as an absolute value so a mesh with inward-facing normals still
        measures positive. A correctly oriented closed mesh gives a positive sum.
        """
        total = 0.0
        for (a, b, c) in self.triangles:
            cx = b[1] * c[2] - b[2] * c[1]
            cy = b[2] * c[0] - b[0] * c[2]
            cz = b[0] * c[1] - b[1] * c[0]
            total += a[0] * cx + a[1] * cy + a[2] * cz
        return abs(total) / 6.0


def parse_ascii(text: str) -> Mesh:
    """Parse ASCII STL by scanning for vertex lines (3 per facet, in order)."""
    verts = [(float(m.group(1)), float(m.group(2)), float(m.group(3)))
             for m in _VERTEX_RE.finditer(text)]
    if not verts:
        raise StlParseError("no vertex lines found in ASCII STL")
    if len(verts) % 3 != 0:
        raise StlParseError("vertex count %d is not a multiple of 3" % len(verts))
    tris = [(verts[i], verts[i + 1], verts[i + 2]) for i in range(0, len(verts), 3)]
    return Mesh(tris)


def parse_binary(data: bytes) -> Mesh:
    """Parse binary STL: 80-byte header, uint32 count, then 50 bytes per facet."""
    if len(data) < 84:
        raise StlParseError("binary STL shorter than its 84-byte header")
    (count,) = struct.unpack_from("<I", data, 80)
    expected = 84 + 50 * count
    if count == 0:
        raise StlParseError("binary STL declares 0 triangles")
    if len(data) < expected:
        raise StlParseError(
            "binary STL declares %d triangles (needs %d bytes) but has %d"
            % (count, expected, len(data)))
    tris = []
    off = 84
    for _ in range(count):
        # 12 floats: normal (skipped), then three vertices.
        vals = struct.unpack_from("<12f", data, off)
        tris.append(((vals[3], vals[4], vals[5]),
                     (vals[6], vals[7], vals[8]),
                     (vals[9], vals[10], vals[11])))
        off += 50
    return Mesh(tris)


def parse(data) -> Mesh:
    """Parse ASCII or binary STL from str or bytes, sniffing the format.

    A binary STL may still begin with "solid", so the declared triangle count is
    cross-checked against the file length before trusting the ASCII path.
    """
    if isinstance(data, str):
        return parse_ascii(data)
    if not isinstance(data, (bytes, bytearray)):
        raise StlParseError("expected str or bytes, got %s" % type(data).__name__)
    raw = bytes(data)
    if len(raw) >= 84:
        (count,) = struct.unpack_from("<I", raw, 80)
        if count > 0 and len(raw) == 84 + 50 * count:
            return parse_binary(raw)
    try:
        return parse_ascii(raw.decode("utf-8", errors="replace"))
    except StlParseError:
        return parse_binary(raw)


def sanity_check(params: Dict[str, ParamValue], mesh: Mesh,
                 bbox_tol_mm: float = BBOX_TOL_MM,
                 volume_tol_frac: float = VOLUME_TOL_FRAC) -> Tuple[bool, List[str]]:
    """Compare a parsed mesh against the frozen analytic prediction for `params`.

    This is the 0-call guard against silent regeneration failures and stale
    exports: Onshape can return HTTP 200 with the geometry of the *previous*
    configuration, and only the measurements reveal it.

    Returns (ok, reasons). `reasons` is empty when ok.
    """
    reasons = []

    want_bbox = fin_geometry.bbox_mm(params)
    got_bbox = mesh.bbox()
    labels = ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")
    for label, want, got in zip(labels, want_bbox, got_bbox):
        delta = abs(got - want)
        if delta > bbox_tol_mm:
            reasons.append("bbox %s off by %.3f mm (want %.3f, got %.3f)"
                           % (label, delta, want, got))

    want_vol = float(fin_geometry.derived(params)["volume_mm3"])
    got_vol = mesh.volume_mm3()
    if want_vol > 0:
        frac = abs(got_vol - want_vol) / want_vol
        if frac > volume_tol_frac:
            reasons.append("volume off by %.1f %% (want %.1f mm3, got %.1f mm3)"
                           % (frac * 100.0, want_vol, got_vol))

    return (not reasons), reasons


def measure(params: Optional[Dict[str, ParamValue]], data) -> Dict[str, object]:
    """Parse `data` and return the GeometryRef measurement fields.

    When `params` is given, the analytic sanity check runs too and the result
    carries regen_status "OK" or "SANITY_FAIL" with the reasons.
    """
    mesh = parse(data)
    out = {
        "bbox_mm": [round(v, 4) for v in mesh.bbox()],
        "volume_mm3": round(mesh.volume_mm3(), 4),
        "triangles": mesh.triangle_count,
    }
    if params is not None:
        ok, reasons = sanity_check(params, mesh)
        out["regen_status"] = "OK" if ok else "SANITY_FAIL"
        out["sanity_reasons"] = reasons
    return out
