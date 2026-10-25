#!/usr/bin/env bash
# Offline fallback (PLAN.md C6/D6): replay the live wing session in the panel. No keys, no network, no Onshape.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-$HOME/.venvs/darwin/bin/python}"
SESSION="${SESSION:-session_1925_d20d}"
for port in 8000 5173; do
  lsof -ti tcp:$port -sTCP:LISTEN >/dev/null && { echo "port $port is busy (an old Darwin server?): run  make stop  first"; exit 1; }
done
DARWIN_CAD=off DARWIN_LLM_PROVIDER=mock DARWIN_MODE=replay "$PY" -m backend.server &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null' EXIT
echo
echo "Replay panel: http://localhost:5173/panel?session=$SESSION"
echo
cd dashboard && npm run dev -- --port 5173 --strictPort
