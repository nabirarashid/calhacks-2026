# shared/: frozen contracts (owner: S3)

Every section imports from here, and only S3 edits it. The spec is PLAN.md Part B.

| File | What it is |
|---|---|
| `contracts.py` | pydantic models + `canonicalize`, `param_hash`, `geometry_key`, `make_design_id` (source of truth) |
| `events.py` | websocket and recording `Event` envelope, one payload model per event type, `make_event`, `validate_event` |
| `contracts.ts` | TypeScript mirror (snake_case on the wire), plus `AnyDarwinEvent` discriminated union |
| `fin_geometry.py` / `.md` | fin_v1 analytic geometry: area, volume, bbox, corners, square-edged STL |
| `fixtures/` | example payloads + `sample_run.jsonl` (recorded event stream from the fakes) |
| `mocks/` | `fake_sim`, `fake_cad`, `fake_llm`, `mock_server` (`:8000`), `make_sample_run`, `make_fixtures` |
| `check.py` | `make contracts`: validates every fixture and recording |

## Usage

```bash
python -m shared.check                 # or: make contracts
python -m shared.mocks.mock_server     # fixture-backed REST + WS on :8000 (or: make mock)
python -m shared.mocks.make_sample_run # regenerate fixtures/sample_run.jsonl
```

Run from the repo root with Python 3.9 (`pip install -r requirements.txt`).

## Changing a contract

Don't edit this folder. Write what you need in `<your section>/CONTRACT_REQUESTS.md` and tell S3.
- Only **additive, optional** fields are accepted.
- Each accepted change bumps `CONTRACT_VERSION` and is announced in the team chat.
