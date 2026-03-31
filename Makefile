PY ?= .venv/bin/python
OFFLINE = scripts/offline-run
LEASE ?= <local>

.PHONY: setup lint test test-offline demo demo-offline e2e-offline canary-check bench-live bench-learning bench-tree

setup:            ## install locked deps (needs network)
	uv sync --frozen

lint:
	$(PY) -m ruff check .

test:             ## unit + integration tests; in-process sockets limited to localhost
	$(PY) -m pytest -q --disable-socket --allow-hosts=127.0.0.1,localhost

demo:             ## keyless demo on the mock device
	$(PY) scripts/demo.py

demo-offline:     ## the demo with the whole process tree sandboxed (macOS)
	$(OFFLINE) $(PY) scripts/demo.py

e2e-offline:      ## full test suite + demo, sandboxed, keys unset, canaries on
	$(OFFLINE) $(PY) -m pytest -q
	$(OFFLINE) $(PY) scripts/demo.py

canary-check:     ## companion check: the canary does connect when NOT sandboxed
	SPECTRA_NETWORK_TESTS=1 $(PY) -m pytest -q tests/test_egress_canary.py

bench-live:       ## live Gemini eval, v0.1-yhack vs HEAD (needs GEMINI_API_KEY; never in CI)
	$(PY) $(LEASE) run spectra-eval -- $(PY) -m bench.run_suite \
	  --arm v0.1-yhack=git:v0.1-yhack --arm head=. --seeds 0,1,2 --backend live \
	  --out bench/results/live-paired

bench-learning:   ## live learning-sequence experiment (memory persists across tasks)
	$(PY) $(LEASE) run spectra-eval -- $(PY) -m bench.run_suite \
	  --arm v0.1-yhack=git:v0.1-yhack --arm head=. --seeds 0,1 --backend live --experiment learning \
	  --out bench/results/live-learning

bench-tree:       ## tree serialization benchmark (offline; adds Gemini token counts if a key is set)
	$(PY) -m bench.tree_tokens --out bench/results/tree-tokens
