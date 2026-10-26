# syntax=docker/dockerfile:1
# Songbook image.
#   web      Node build of web/ (vitest runs here too); output in /web/dist
#   runtime  Python + ffmpeg + rubberband, the base of `app` and `test`
#   test     the backend suite with real ffmpeg/rubberband (`make test-docker`)
#   e2e      Playwright against scripts/dev_stack.py (`make e2e`)
#   app      the production image: `api` (default) or `worker`, see docker/entrypoint.sh
#
# Always build with --target (compose uses `target: app`). It sits right after
# runtime because the classic builder (no BuildKit) builds every stage before
# the target, and test/e2e would pull Playwright into a production build.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY fixtures/cache_keys.json /fixtures/cache_keys.json
COPY web/ ./
RUN npx vitest run && npm run build

FROM python:3.12-slim AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg rubberband-cli fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && rubberband --version && ffmpeg -version | head -1
WORKDIR /app
COPY api/pyproject.toml api/pyproject.toml
COPY api/songbook api/songbook
RUN pip install --no-cache-dir ./api

FROM runtime AS app
COPY --from=web /web/dist /app/web/dist
COPY docker/entrypoint.sh /usr/local/bin/songbook-entrypoint
ENV SONGBOOK_ROOT=/data \
    SONGBOOK_WEB_DIR=/app/web/dist \
    SONGBOOK_HEARTBEAT=/tmp/songbook-worker.heartbeat \
    PYTHONUNBUFFERED=1
RUN rubberband --version && ffmpeg -version >/dev/null && setpriv --version
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-m", "songbook.healthcheck", "api"]
ENTRYPOINT ["songbook-entrypoint"]
CMD ["api"]

FROM runtime AS test
RUN pip install --no-cache-dir -e './api[dev]'
COPY . /app
RUN ./scripts/make_fixtures.sh >/dev/null
WORKDIR /app/api
CMD ["python", "-m", "pytest", "-q"]

FROM mcr.microsoft.com/playwright:v1.64.1-noble AS e2e
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg rubberband-cli fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY api/pyproject.toml api/pyproject.toml
COPY api/songbook api/songbook
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir ./api
COPY e2e/package.json e2e/package-lock.json e2e/
RUN cd e2e && npm ci --no-audit --no-fund
COPY api/tests api/tests
COPY scripts scripts
COPY fixtures/cache_keys.json fixtures/cache_keys.json
RUN ./scripts/make_fixtures.sh >/dev/null
COPY --from=web /web/dist web/dist
COPY e2e e2e
ENV PYTHON=/venv/bin/python
WORKDIR /app/e2e
CMD ["npx", "playwright", "test"]
