"""Domain-neutral STL health checks.

STL has no unit metadata. A millimetre-scale verdict therefore requires a
known expected bbox; without one, the report explicitly marks scale unknown.
"""
from collections import Counter, defaultdict, deque
from typing import Optional, Sequence

from cad.stl import Mesh, parse


def _topology(mesh: Mesh):
    # Quantize at a micron to absorb harmless ASCII/binary float roundoff.
    def point(v):
        return tuple(round(float(x) * 1000.0) for x in v)

    edges = Counter()
    owners = defaultdict(list)
    for ti, tri in enumerate(mesh.triangles):
        vs = [point(v) for v in tri]
        for a, b in ((vs[0], vs[1]), (vs[1], vs[2]), (vs[2], vs[0])):
            edge = tuple(sorted((a, b)))
            edges[edge] += 1
            owners[edge].append(ti)
    watertight = bool(edges) and all(n == 2 for n in edges.values())
    adjacency = [set() for _ in mesh.triangles]
    for tris in owners.values():
        for ti in tris:
            adjacency[ti].update(t for t in tris if t != ti)
    seen = set()
    parts = 0
    for start in range(len(adjacency)):
        if start in seen:
            continue
        parts += 1
        queue = [start]
        seen.add(start)
        while queue:
            for nxt in adjacency[queue.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
    return watertight, parts


def verify(data, *, expected_bbox_mm: Optional[Sequence[float]] = None,
           bbox_tolerance_mm: float = 0.5, expected_parts: Optional[int] = 1,
           units: Optional[str] = None):
    """Return measurements and pass/fail checks for any STL byte/string input."""
    mesh = parse(data)
    bbox = mesh.bbox()
    volume = mesh.volume_mm3()
    watertight, parts = _topology(mesh)
    checks = {
        "watertight": {"ok": watertight, "value": watertight},
        "nonzero_volume": {"ok": volume > 0.0, "value": volume},
        "part_count": {"ok": expected_parts is None or parts == expected_parts,
                       "value": parts, "expected": expected_parts},
    }
    if expected_bbox_mm is not None:
        if len(expected_bbox_mm) != 6:
            raise ValueError("expected_bbox_mm must contain six coordinates")
        deltas = [abs(float(a) - b) for a, b in zip(expected_bbox_mm, bbox)]
        checks["bbox"] = {"ok": max(deltas) <= bbox_tolerance_mm,
                          "value_mm": bbox, "expected_mm": list(expected_bbox_mm),
                          "max_delta_mm": max(deltas)}
        # Absolute expected coordinates provide the only reliable STL scale check.
        checks["mm_scale"] = {"ok": checks["bbox"]["ok"],
                              "basis": "expected_bbox_mm"}
    else:
        checks["bbox"] = {"ok": True, "value_mm": bbox}
        normalized_units = str(units or "").strip().lower()
        if normalized_units in ("mm", "millimeter", "millimeters"):
            checks["mm_scale"] = {"ok": True,
                                  "basis": "trusted export units"}
        else:
            checks["mm_scale"] = {"ok": None,
                                  "basis": "STL carries no unit metadata"}
    ok = all(c["ok"] is True for c in checks.values())
    return {"ok": ok, "checks": checks, "bbox_mm": bbox,
            "volume_mm3": volume, "triangles": mesh.triangle_count,
            "parts": parts}
