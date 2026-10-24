"""Geometry cache: keyed by geometry_key, costs zero Onshape calls on a hit (S1).

Two tiers:
  1. .darwin/geometry/   runtime, gitignored, written by build_geometry
  2. demo/geometry/      committed, read-only, used by replay and the demo

Each entry is <key>.stl plus a <key>.json sidecar holding the GeometryRef.
"""
import json
import os
from typing import Optional

from shared.contracts import GeometryRef

RUNTIME_DIR = os.path.join(".darwin", "geometry")
DEMO_DIR = os.path.join("demo", "geometry")
# Shipped fixtures act as a third read-only tier so tests and the dashboard
# have geometry before any real export has happened.
FIXTURE_DIR = os.path.join("shared", "fixtures", "geometry")

READ_TIERS = (RUNTIME_DIR, DEMO_DIR, FIXTURE_DIR)


def stl_path(geometry_key: str) -> Optional[str]:
    """First existing STL for this key across the read tiers, or None."""
    for d in READ_TIERS:
        p = os.path.join(d, "%s.stl" % geometry_key)
        if os.path.exists(p):
            return p
    return None


def load(geometry_key: str) -> Optional[GeometryRef]:
    """Return the cached GeometryRef if both STL and sidecar are present."""
    for d in READ_TIERS:
        stl_p = os.path.join(d, "%s.stl" % geometry_key)
        side_p = os.path.join(d, "%s.json" % geometry_key)
        if not (os.path.exists(stl_p) and os.path.exists(side_p)):
            continue
        try:
            with open(side_p) as fh:
                data = json.load(fh)
        except ValueError:
            continue
        # A cache hit spends nothing, whatever the original build cost.
        data["source"] = "cache"
        data["onshape_calls"] = 0
        data["status"] = "ready"
        data["stl_url"] = "/api/geometry/%s.stl" % geometry_key
        try:
            return GeometryRef(**data)
        except Exception:
            continue
    return None


def store(ref: GeometryRef, stl_text: str) -> GeometryRef:
    """Write the STL and sidecar into the runtime tier. Returns `ref`."""
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    key = ref.geometry_key
    with open(os.path.join(RUNTIME_DIR, "%s.stl" % key), "w") as fh:
        fh.write(stl_text)
    with open(os.path.join(RUNTIME_DIR, "%s.json" % key), "w") as fh:
        json.dump(json.loads(ref.model_dump_json()), fh, indent=2, sort_keys=True)
    return ref
