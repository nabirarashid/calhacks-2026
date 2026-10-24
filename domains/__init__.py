"""Installed domain packs (PLAN.md v3 B.4). Owner: W-B (prompts.md: W-C, verifier.py: W-A).

A pack is domains/<pack_id>/pack.py exposing PACK (see shared.adapters.DomainPack).
Only committed, installed packs load. Nothing under a `drafts` folder ever loads, and a
pack id is never taken from model output without being checked against installed().
"""
import importlib
import re
from pathlib import Path
from typing import Any, List

_HERE = Path(__file__).resolve().parent
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def installed() -> List[str]:
    return sorted(d.name for d in _HERE.iterdir()
                  if d.is_dir() and _ID.match(d.name) and not d.name.startswith("drafts")
                  and (d / "pack.py").exists())


def get_pack(pack_id: str) -> Any:
    if pack_id not in installed():
        raise KeyError("domain pack %r is not installed" % pack_id)
    return importlib.import_module("domains.%s.pack" % pack_id).PACK


__all__ = ["installed", "get_pack"]
