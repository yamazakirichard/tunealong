# Run every target from this directory (TuneAlong/). Nothing here reaches outside it.
SHELL := /bin/bash
VENV  := api/.venv
PY    := $(VENV)/bin/python
DEV_ROOT ?= $(CURDIR)/.dev-data
PORT  ?= 8080

.PHONY: test test-api test-docker test-web e2e compose-test fixtures dev build venv clean

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
	docker build -q --target test -t tunealong:test . >/dev/null
	docker run --rm tunealong:test

test-web: web/node_modules
	cd web && npx vitest run

web/node_modules: web/package-lock.json
	cd web && npm ci --no-audit --no-fund
	touch $@

# Playwright in Docker (Chromium, Python, ffmpeg and rubberband in one image),
# against scripts/dev_stack.py with the built UI and a fake MeTube.
e2e:
	docker build -q --target e2e -t tunealong:e2e . >/dev/null
	docker run --rm --ipc=host tunealong:e2e

# Gate 7: the compose deployment end to end (needs host port 8080 free).
compose-test:
	./scripts/compose_test.sh

# API + worker + fake MeTube + built UI over a scratch root seeded with the
# webm fixtures (wiped on start). For the real thing, use docker compose.
dev: venv fixtures build
	$(PY) scripts/dev_stack.py --port $(PORT) --root $(DEV_ROOT)

build: web/node_modules
	cd web && npm run build

clean:
	rm -rf $(VENV) fixtures/originals api/.pytest_cache web/node_modules web/dist e2e/node_modules
