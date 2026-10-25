#!/usr/bin/env bash
# One command for the demo laptop (PLAN.md A6): live backend on :8000 + panel on :5173.
# Reads keys and the wing document from ~/.darwin_secrets.sh; nothing secret lives in the repo.
set -euo pipefail
cd "$(dirname "$0")/.."
source ~/.darwin_secrets.sh
PY="${PY:-$HOME/.venvs/darwin/bin/python}"
: "${DARWIN_DOC_WING:?add DARWIN_DOC_WING (the wing Part Studio URL) to ~/.darwin_secrets.sh}"
: "${OPENROUTER_API_KEY:?add OPENROUTER_API_KEY to ~/.darwin_secrets.sh}"
export DARWIN_ONSHAPE_WRITE_DOCS="${DARWIN_ONSHAPE_WRITE_DOCS:-DARWIN_DOC_WING}"
export DARWIN_SIM=real DARWIN_CAD=real DARWIN_MODE=live
export DARWIN_LOCKED_PARAMS="${DARWIN_LOCKED_PARAMS-chord_mm}"   # chord isn't wired in CAD yet (A2b); set it empty to unlock
unset DARWIN_DOC_FIN DARWIN_FIN_DOC_URL           # the wing is the demo
"$PY" -c "
import os, sys
from cad.onshape_client import parse_doc_url
from cad.variables import adopted_ids
did, _, eid = parse_doc_url(os.environ['DARWIN_DOC_WING'])
ids = adopted_ids(did, eid)
print('adopted Darwin variables:', ', '.join(sorted(ids)) or 'NONE (copy .darwin/feature_ids from the setup laptop)')
sys.exit(0 if len(ids) == 6 else 1)
"
lsof -ti tcp:8000 -sTCP:LISTEN >/dev/null && { echo "port 8000 is busy: stop the old backend first"; exit 1; }
"$PY" -m backend.server &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null' EXIT
"$PY" -c "import urllib.parse, os; print('\nPanel: http://localhost:5173/panel?doc=' + urllib.parse.quote(os.environ['DARWIN_DOC_WING'], safe='') + '\n')"
cd dashboard && npm run dev -- --port 5173 --strictPort
