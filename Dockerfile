# syntax=docker/dockerfile:1
# Songbook image. Phase 7 adds the web build stage; the runtime stage is the
# production base, and `test` runs the backend suite with real ffmpeg/rubberband.

FROM python:3.12-slim AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg rubberband-cli fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && rubberband --version && ffmpeg -version | head -1
WORKDIR /app
COPY api/pyproject.toml api/pyproject.toml
COPY api/songbook api/songbook
RUN pip install --no-cache-dir ./api

FROM runtime AS test
RUN pip install --no-cache-dir -e './api[dev]'
COPY . /app
RUN ./scripts/make_fixtures.sh >/dev/null
WORKDIR /app/api
CMD ["python", "-m", "pytest", "-q"]
