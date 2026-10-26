# Run every target from this directory (Songbook/). Nothing here reaches outside it.
SHELL := /bin/bash
VENV  := api/.venv
PY    := $(VENV)/bin/python
DEV_ROOT ?= $(CURDIR)/data
PORT  ?= 8080

.PHONY: test test-api test-docker test-web e2e fixtures dev build venv clean

test: test-api test-web

venv: $(VENV)/.installed
$(VENV)/.installed: api/pyproject.toml
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e 'api[dev]'
	touch $@

fixtures:
	./scripts/make_fixtures.sh

test-api: venv fixtures
	cd api && .venv/bin/python -m pytest -q

# The backend suite inside the image, with the real ffmpeg and rubberband
# (test_render.py skips locally when rubberband isn't installed).
test-docker:
	docker build -q --target test -t songbook:test . >/dev/null
	docker run --rm songbook:test

# The web app arrives in Phase 6; until then these are no-ops.
test-web:
	@if [ -f web/package.json ]; then cd web && npm test; else echo "test-web: no web/ app yet (Phase 6)"; fi

e2e:
	@if [ -f e2e/package.json ]; then cd e2e && npx playwright test; else echo "e2e: no e2e suite yet (Phase 6)"; fi

dev: venv
	SONGBOOK_ROOT=$(DEV_ROOT) $(VENV)/bin/uvicorn --factory songbook.main:create_app --reload --port $(PORT) --app-dir api

build:
	@if [ -f web/package.json ]; then cd web && npm ci && npx vite build; else echo "build: no web/ app yet (Phase 6)"; fi

clean:
	rm -rf $(VENV) fixtures/originals api/.pytest_cache
