"""STL parsing, geometry measurement and the analytic sanity check (S1).

No network. Everything here is pure and testable against shared/fixtures/geometry/.

Onshape returns ASCII STL by default for Part Studio exports; binary is handled
as a fallback in case the Accept header or defaults change under us.
"""
import re
import struct
from typing import List, Tuple

# "vertex 1.234e+01 -5.0e+00 0.0" — three floats after the keyword.
_FLOAT = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"
_VERTEX_RE = re.compile(r"vertex\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")")

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


def sanity_check(params, mesh, verifier=None, bbox_tol_mm=0.5, volume_tol_frac=0.06):
    """Run a caller supplied domain verifier; generic CAD has no domain policy."""
    if verifier is None:
        return False, ["domain geometry verifier was not provided"]
    result = verifier.verify_data(params, _mesh_bytes(mesh))
    return result["ok"], result["reasons"]


def _mesh_bytes(mesh):
    # Keep the legacy helper usable for parsed Mesh instances without teaching
    # this generic module any domain geometry. ASCII is sufficient for triangles.
    rows = ["solid mesh"]
    for tri in mesh.triangles:
        rows.append("facet normal 0 0 0\nouter loop")
        rows.extend("vertex %.9g %.9g %.9g" % v for v in tri)
        rows.append("endloop\nendfacet")
    rows.append("endsolid mesh")
    return "\n".join(rows)


def measure(params_or_data, data=None, verifier=None) -> dict:
    """Parse and measure; optional domain verifier adds regen status."""
    params = params_or_data if data is not None else None
    raw = data if data is not None else params_or_data
    mesh = parse(raw)
    out = {
        "bbox_mm": [round(v, 4) for v in mesh.bbox()],
        "volume_mm3": round(mesh.volume_mm3(), 4),
        "triangles": mesh.triangle_count,
    }
    if params is not None:
        evidence = (verifier.verify_data(params, raw) if verifier is not None
                    else {"ok": False, "reasons": ["domain geometry verifier was not provided"]})
        out["regen_status"] = "OK" if evidence["ok"] else "SANITY_FAIL"
        out["sanity_reasons"] = evidence["reasons"]
    return out
