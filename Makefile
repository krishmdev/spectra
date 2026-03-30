PY ?= .venv/bin/python

.PHONY: setup lint test

setup:
	uv sync --frozen

lint:
	$(PY) -m ruff check .

test:
	$(PY) -m pytest -q
