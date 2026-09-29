# «Инспектор ИИ» — local developer entry points (no Docker; macOS arm64 and Linux, see README.md and docs/runbook/LINUX.md).
# Owner: AG-00. Run `make` or `make help` for the list. Every target is run from the repo root.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Local settings (optional): copy .env.example to .env.
-include .env
export

ML_DIR       := services/ml
UV           ?= uv
# Python 3.12 for uv: Homebrew's on macOS, else whatever `python3.12` is on PATH (Linux); when neither exists UV_PYTHON
# stays unset and uv finds or downloads a managed 3.12 itself.
UV_PYTHON    ?= $(shell test -x /opt/homebrew/bin/python3.12 && echo /opt/homebrew/bin/python3.12 || command -v python3.12)
ifneq ($(strip $(UV_PYTHON)),)
export UV_PYTHON
else
unexport UV_PYTHON
endif
# SKIP_MODEL_CHECK=1 skips the model check of `make setup` (CI, fresh Linux box: run `make fetch-models` afterwards).
SKIP_MODEL_CHECK ?=
UV_RUN       := cd $(ML_DIR) && $(UV) run --locked
PNPM         := COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm
PYTEST_ARGS  ?=
# Fast tests run on pytest-xdist workers (4 by default: up to 10 agents share the 12-core host).
# PYTEST_WORKERS=0 runs serially (debugging, -x/--pdb). Slow tests always run serially: they time things.
PYTEST_WORKERS ?= 4
PYTEST_XDIST := $(if $(filter 0 1,$(PYTEST_WORKERS)),,-n $(PYTEST_WORKERS))
OBJECT       ?=
OBJECT_ARGS  := $(foreach o,$(OBJECT),--object $(o))
ARGS         ?=
SUITE        ?= ocr
PRED         ?=
PRED_ARGS    := $(if $(PRED),--pred $(abspath $(PRED)),)
DB_NAME      ?= inspector
RUN_ID       ?=

.PHONY: help setup test test-py test-js test-slow test-registry-slow test-docproc-slow test-params seed seed-check \
        lint format contracts contracts-check verify-models verify-models-all verify-models-ocr fetch-models gpu-check guard \
        bench-ocr inventory inventory-all run-train score score-selftest dev api-dev web-dev ml-api-dev db-create db-migrate \
        db-seed test-db clean

help: ## Show this list
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install everything locally: Python workspace (uv sync), pnpm via corepack, quick model check
	cd $(ML_DIR) && $(UV) sync --locked
	corepack enable pnpm
	$(PNPM) install --frozen-lockfile
	$(if $(SKIP_MODEL_CHECK),@echo "Проверка моделей пропущена (SKIP_MODEL_CHECK): make fetch-models",$(UV_RUN) python ../../tools/models/verify_models.py --quick)
	@echo "Готово. Дальше: make test"

test: ## Fast tests (< 90 s): pytest without `slow` on xdist workers, contracts self-check, hidden-test guard, pnpm tests
	$(UV_RUN) pytest -m "not slow" $(PYTEST_XDIST) $(PYTEST_ARGS)
	$(UV_RUN) inspector-contracts check
	$(UV_RUN) python ../../tools/guards/hidden_test_guard.py
	$(PNPM) -r --workspace-concurrency=1 --if-present test

test-py: ## Fast Python tests only (pytest without `slow`, PYTEST_WORKERS=4 xdist workers; 0 = serial)
	$(UV_RUN) pytest -m "not slow" $(PYTEST_XDIST) $(PYTEST_ARGS)

test-js: ## TypeScript tests only (apps/api, apps/web; no database)
	$(PNPM) -r --workspace-concurrency=1 --if-present test

test-slow: ## Slow and heavy tests only (`@pytest.mark.slow`: full model sha256, large files, OCR gates ≈ 5 min)
	$(UV_RUN) pytest -m slow $(PYTEST_ARGS)

test-registry-slow: ## AG-01 slow tests: full sha256 of both train objects against the manifest
	$(UV_RUN) pytest packages/inspector_registry -m slow $(PYTEST_ARGS)

test-docproc-slow: ## AG-02A slow gates: recognition benchmark quality and speed (≈ 5 min, idle machine)
	$(UV_RUN) pytest packages/inspector_docproc -m slow $(PYTEST_ARGS)

test-params: ## AG-03 matrix seed tests, including the slow regex timing fuzz and real train pages
	$(UV_RUN) pytest packages/inspector_common/tests -k params $(PYTEST_ARGS)

seed: ## Rebuild packages/contracts/seed/*.json from seed/src (AG-03)
	$(UV_RUN) python ../../packages/contracts/seed/src/build_seed.py

seed-check: ## Fail when packages/contracts/seed/*.json drifts from seed/src (no writes)
	$(UV_RUN) python ../../packages/contracts/seed/src/build_seed.py --check

lint: ## Ruff lint + format check, contracts self-check, hidden-test guard
	$(UV_RUN) ruff check . ../../tools
	$(UV_RUN) ruff format --check . ../../tools
	$(UV_RUN) inspector-contracts check
	$(UV_RUN) python ../../tools/guards/hidden_test_guard.py
	$(PNPM) -r --if-present lint

format: ## Apply ruff format and safe lint fixes
	$(UV_RUN) ruff format . ../../tools
	$(UV_RUN) ruff check --fix . ../../tools

contracts: ## Regenerate derived contract files (enums.schema.json, enums.py) after editing enums.yaml/errors.yaml
	$(UV_RUN) inspector-contracts gen
	$(UV_RUN) inspector-contracts check

contracts-check: ## Validate contracts, examples, generated files and the params seed (no writes)
	$(UV_RUN) inspector-contracts check
	$(UV_RUN) python ../../packages/contracts/seed/src/build_seed.py --check
	$(UV_RUN) python -m inspector_common.params check

verify-models: ## sha256 of the required models in .models/ against tools/models/manifest.json
	$(UV_RUN) python ../../tools/models/verify_models.py

verify-models-ocr: ## sha256 of the 3 OCR models only (all the recognition pipeline needs; Linux/CI after `make fetch-models`)
	$(UV_RUN) python ../../tools/models/verify_models.py --ocr-only

fetch-models: ## Download the 3 required OCR models into .models/ocr (network, one-off; sha256 checked against the manifest)
	$(UV_RUN) python ../../tools/models/fetch_models.py

gpu-check: ## Which ONNX executor `--providers auto` picks on this machine (coreml | cuda | cpu) and why
	$(UV_RUN) python ../../tools/models/gpu_check.py

verify-models-all: ## sha256 of every pinned model file, including benchmark candidates
	$(UV_RUN) python ../../tools/models/verify_models.py --all

guard: ## Hidden-test integrity guard: code and config must not mention the hidden object
	$(UV_RUN) python ../../tools/guards/hidden_test_guard.py

bench-ocr: ## Recognition benchmark (AG-02A), `SUITE=ocr|vector|scans|orientation|drawings` (default ocr ≈ 5 min)
	$(UV_RUN) inspector-batch bench --suite $(SUITE) $(ARGS)

inventory: ## Manifest/file inventory, e.g. `make inventory OBJECT=OBJ-TYUMENSKAYA-5-GOLD-SEED ARGS=--verify-sha256`
	$(UV_RUN) inspector-batch inventory $(OBJECT_ARGS) $(ARGS)

inventory-all: ## Inventory of every object incl. the hidden one (input handling only), with sha256 verification
	$(UV_RUN) inspector-batch inventory --all --verify-sha256 $(ARGS)

run-train: ## Train end-to-end chain inventory → recognize → layout → tables → compare → export → score, e.g. `make run-train OBJECT=OBJ-TYUMENSKAYA-5-GOLD-SEED ARGS="--steps recognize,layout"`
	$(UV_RUN) inspector-batch $(if $(RUN_ID),--run-id $(RUN_ID),) run $(OBJECT_ARGS) $(ARGS)

score: ## Local score on TRAIN objects: `make score PRED=runs/<id>/submission` (default: newest export); refuses hidden
	$(UV_RUN) inspector-batch score $(OBJECT_ARGS) $(PRED_ARGS) $(ARGS)

score-selftest: ## T-GOLD gate: inspector-score reproduces the 93 §2.3/§4.10 cases (must pass in CI)
	$(UV_RUN) inspector-score selftest

dev: ## Web stack: API :3000, web :5173 (proxy /api), ml-api :8090 (page renders); PostgreSQL + Redis; Ctrl-C stops all
	@trap 'kill 0' INT TERM EXIT; \
	(cd $(ML_DIR) && $(UV) run --locked inspector-ml-api serve) & \
	$(PNPM) --parallel --filter @inspector/api --filter @inspector/web dev

api-dev: ## API only (NestJS on 127.0.0.1:3000, /api/v1)
	$(PNPM) --filter @inspector/api dev

web-dev: ## Web only (Vite on 127.0.0.1:5173, proxies /api to :3000)
	$(PNPM) --filter @inspector/web dev

ml-api-dev: ## Internal ml-api only (FastAPI on 127.0.0.1:8090): PDF page renders and tiles for the evidence viewer
	$(UV_RUN) inspector-ml-api serve

db-create: ## Create the local PostgreSQL database (idempotent)
	@psql -h localhost -p 5432 -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$(DB_NAME)'" | grep -q 1 \
		&& echo "База $(DB_NAME) уже существует." \
		|| (createdb -h localhost -p 5432 $(DB_NAME) && echo "База $(DB_NAME) создана.")

db-migrate: ## Apply the API migrations (apps/api/drizzle) to the local database
	$(PNPM) --filter @inspector/api db:migrate

db-seed: ## Demo user (inspector, the single super-role); ARGS=--reset-passwords
	$(PNPM) --filter @inspector/api db:seed $(ARGS)

test-db: ## API integration tests on a real PostgreSQL (creates/migrates the `inspector_test` database)
	$(PNPM) --filter @inspector/api test:db

clean: ## Remove Python caches (never touches data, models or runs)
	find $(ML_DIR) tools -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
