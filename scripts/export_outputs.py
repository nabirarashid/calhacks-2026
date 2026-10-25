"""Snapshot .darwin/ (local, git-ignored) into outputs/ for the team. Run: make outputs PY=~/.venvs/darwin/bin/python

Copies session recordings, the Onshape call ledger, LLM spend totals, bench landscapes and exported
geometry; skips pure caches. Darwin's wing feature ids go to projects/rear_wing/onshape_feature_ids.json
(named by project, not by document id). Refuses to finish if any copied file contains a document id or
an API key.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, DST = ROOT / ".darwin", ROOT / "outputs"
COPY_DIRS = ["runs", "ledger", "landscape", "geometry"]
KEYS = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}|sk-or-v1-[a-f0-9]{16,}|sk-[a-f0-9]{32}")
DOC_ENVS = ["DARWIN_DOC_WING", "DARWIN_DOC_FIN", "DARWIN_FIN_DOC_URL", "DARWIN_ONSHAPE_WRITE_TARGET_URL"]


def doc_ids():
    ids = set()
    for env in DOC_ENVS:
        ids.update(re.findall(r"[0-9a-f]{24}", os.environ.get(env, "")))
    return ids


def main():
    ids = doc_ids()
    if not ids:
        sys.exit("source ~/.darwin_secrets.sh first: the document ids are needed to check nothing leaks")
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir()
    for d in COPY_DIRS:
        if (SRC / d).is_dir():
            shutil.copytree(SRC / d, DST / d)
    (DST / "spend").mkdir()
    for f in SRC.glob("spend*.json"):
        shutil.copy2(f, DST / "spend" / f.name)
    from cad.onshape_client import parse_doc_url
    wing = os.environ.get("DARWIN_DOC_WING")
    if wing:
        did, _, eid = parse_doc_url(wing)
        local = SRC / "feature_ids" / ("%s_%s.json" % (did, eid))
        if local.exists():
            shutil.copy2(local, ROOT / "projects" / "rear_wing" / "onshape_feature_ids.json")
    leaks = []
    for f in list(DST.rglob("*")) + [ROOT / "projects" / "rear_wing" / "onshape_feature_ids.json"]:
        if not f.is_file():
            continue
        text = f.read_text(errors="ignore")
        if KEYS.search(text) or any(i in text or i in f.name for i in ids):
            leaks.append(str(f.relative_to(ROOT)))
    if leaks:
        shutil.rmtree(DST)
        sys.exit("refused: document id or key found in %s" % ", ".join(leaks))
    n = sum(1 for f in DST.rglob("*") if f.is_file())
    print("outputs/: %d files, no document ids or keys" % n)


if __name__ == "__main__":
    main()
