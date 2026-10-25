PY ?= python
NPM ?= npm

.PHONY: contracts test mock sample dev secrets-check compile39

contracts:            ## validate shared fixtures against the frozen models
	$(PY) -m shared.check

sample:               ## regenerate shared/fixtures/sample_run.jsonl with the fakes
	$(PY) -m shared.mocks.make_sample_run

mock:                 ## fixture-backed API on :8000 (for the dashboard)
	$(PY) -m shared.mocks.mock_server

dev:                  ## real backend on :8000 (S3)
	$(PY) -m backend.server

test: compile39 contracts
	$(PY) -m pytest -q shared $(wildcard cad/tests) $(wildcard sim/tests) $(wildcard backend/tests)

compile39:            ## fail fast on syntax newer than Python 3.9
	$(PY) -c "import sys; assert sys.version_info[:2] == (3, 9), \"use Python 3.9 (PLAN.md Part A)\""
	$(PY) -m compileall -q shared $(wildcard cad) $(wildcard sim) $(wildcard backend) >/dev/null

secrets-check:        ## grep the tree for anything that looks like a key
	@! git grep -nIE "sk-ant-[A-Za-z0-9_-]{8,}|sk-[a-f0-9]{32}|ONSHAPE_SECRET_KEY *= *[A-Za-z0-9]{8,}|[A-Za-z0-9+/]{40,}={0,2}" -- . ":!**/*.lock" ":!**/package-lock.json" ":!**/*.stl" ":!**/dist/**" || (echo "possible secret found ^" && false)
	@echo "secrets-check OK"
