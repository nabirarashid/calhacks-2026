# outputs/ — snapshot of Darwin's local outputs

Copied from `.darwin/` (the live, git-ignored working folder) by `make outputs PY=~/.venvs/darwin/bin/python`,
which refuses to finish if any file contains an Onshape document id or an API key. Re-run it to refresh.

| Folder | What it is |
|---|---|
| `runs/` | Every session and run recording (event JSONL, replayable by the panel). `session_HHMM_*` are panel/API sessions, `session_HHMMSS` terminal runs, `run_*` the older population loop. Highlights below. |
| `ledger/prod.jsonl` | Every Onshape API call Darwin made: endpoint template, purpose, status. No ids. |
| `spend/` | LLM spend totals per provider (`spend.json` = Anthropic direct, `spend_deepseek.json`, `spend_openrouter.json`). |
| `landscape/` | Random design-space samples used by the proof bench (C5) for "best known value". |
| `geometry/` | STL exports of designs Onshape built. |

Darwin's wing feature ids live in `projects/rear_wing/onshape_feature_ids.json` (used by the server).

**Highlights (Sat Oct 24):**
- `session_1925_d20d.jsonl` — the wing, live in Onshape, Haiku 5.5 via OpenRouter: downforce 98 → 139 N
  (+41%) under 15 N drag, 5 morphs, versions before/after, chord locked (A5).
- `session_1822_fa83.jsonl` — DeepSeek, wing variables on the retired trapezoid copy: drag −34%.
- `session_1834_0571.jsonl`, `session_1843_c64f.jsonl` — the retired fin/trapezoid demo (drag −12%, mass −28%).
- `session_152525.jsonl` — first live Sonnet session on the real solver (also in `demo/recordings/`).
- The C5 proof-bench results are in `demo/bench_wing.json`.
