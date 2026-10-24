# S4 integration requests

## Discovered-space registration

`POST /api/discover` currently returns a discovered `DesignSpace`, but `backend/server.py` does not register that space in `W.spaces`. Consequently, the next contract-defined calls to `POST /api/goal/parse` or `POST /api/runs` reject its new `design_space_id` as unknown.

The S4 discovery UI is implemented and stages the returned space, editable bounds, and scorer choice. To enable its final “start run” step, S3 should register the confirmed space (or provide the planned scorer-binding/confirmation endpoint) before those existing routes are called. No frozen `shared/` contract change is required.
