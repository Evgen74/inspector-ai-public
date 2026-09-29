# syntax=docker/dockerfile:1.7
# «Инспектор ИИ»: one multi-stage build, two targets.
#   app  — API (Node 22) + Python 3.12 engine (uv venv, OCR models). The API spawns `python -m inspector_batch.cli`
#          for an uploaded package, so both runtimes live in one image; ml-api and the migration job reuse it.
#   web  — the Vite production build behind nginx (proxies /api to the api service).
# Build context: the repository root (see docker-compose.yml). Organizer data and models never enter the context.
ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.7.12
ARG NGINX_IMAGE=nginx:1.27-alpine

FROM ${NODE_IMAGE} AS node-base
FROM ${UV_IMAGE} AS uv-bin

# ---------------------------------------------------------------- js: pnpm install, API and web builds
FROM node-base AS js
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=true
RUN corepack enable pnpm
WORKDIR /app
# manifests first: the dependency layer is reused while only sources change
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/api/package.json apps/api/package.json
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
RUN pnpm install --frozen-lockfile
COPY apps apps
COPY packages packages
# API -> apps/api/dist (tsc); web -> apps/web/dist (tsc --noEmit + vite build)
RUN pnpm --filter @inspector/api build && pnpm --filter @inspector/web build

# ---------------------------------------------------------------- models: the 3 OCR models, sha256-checked
FROM ${PYTHON_IMAGE} AS models
WORKDIR /src
COPY tools/models tools/models
# same as `make fetch-models` + `make verify-models-ocr` (stdlib only; network is needed at build time only)
RUN set -e; \
    for attempt in 1 2 3 4 5; do \
      python tools/models/fetch_models.py --models-root /models && break; \
      if [ "$attempt" = 5 ]; then echo "OCR models could not be fetched" >&2; exit 1; fi; \
      echo "attempt $attempt failed"; sleep 10; \
    done; \
    python tools/models/verify_models.py --ocr-only --models-root /models; \
    chmod -R a+rX /models  # fetched via temp files (mode 0600); the app runs as an unprivileged user

# ---------------------------------------------------------------- app: API + Python engine
FROM ${PYTHON_IMAGE} AS app
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ORT_DISABLE_TELEMETRY=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never
# libarchive: 7z/rar/zip of an uploaded package (libarchive-c + bsdtar); libgl1/libglib2.0-0/libgomp1: opencv and
# onnxruntime; tesseract-osd: optional page-orientation hint
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates libarchive13 libarchive-tools libgl1 libglib2.0-0 libgomp1 tesseract-ocr tesseract-ocr-osd \
 && rm -rf /var/lib/apt/lists/*
COPY --from=node-base /usr/local/bin/node /usr/local/bin/node
COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /app
COPY --from=models /models /app/.models
COPY packages/contracts packages/contracts
COPY services/ml services/ml
# Linux x86_64: onnxruntime-gpu with the NVIDIA pip runtime (large; runs on the CPU when there is no GPU)
RUN --mount=type=cache,target=/root/.cache/uv \
    cd services/ml && uv sync --locked --no-dev

COPY tools/models tools/models
COPY docs/analysis/norms_staging docs/analysis/norms_staging
COPY --from=js /app/package.json /app/pnpm-workspace.yaml ./
COPY --from=js /app/node_modules node_modules
COPY --from=js /app/apps/api apps/api

# unprivileged user; runs/ and the token cache live in named volumes mounted at /data/*
RUN groupadd --gid 10001 inspector \
 && useradd --uid 10001 --gid inspector --create-home --home-dir /home/inspector --shell /usr/sbin/nologin inspector \
 && mkdir -p /data/runs /data/cache \
 && chown -R inspector:inspector /data /home/inspector \
 && ln -s /data/cache /app/.cache

ENV PATH=/app/services/ml/.venv/bin:$PATH \
    HOME=/home/inspector \
    INSPECTOR_REPO_ROOT=/app \
    INSPECTOR_MODELS_ROOT=/app/.models \
    INSPECTOR_RUNS_ROOT=/data/runs \
    INSPECTOR_CACHE_ROOT=/data/cache \
    INSPECTOR_API_HOST=0.0.0.0 \
    INSPECTOR_API_PORT=3000
USER inspector
WORKDIR /app/apps/api
EXPOSE 3000 8090
CMD ["node", "--enable-source-maps", "dist/main.js"]

# ---------------------------------------------------------------- web: static build + nginx
FROM ${NGINX_IMAGE} AS web
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=js /app/apps/web/dist /usr/share/nginx/html
EXPOSE 80
