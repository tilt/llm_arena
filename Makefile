SHELL := /bin/sh
PYTHON_VERSION ?= 3.12

.PHONY: setup doctor sandbox-image help install format validate lint typecheck test test-live smoke report models contracts ui web web-engine test-web clean

help:
	@printf "Targets:\n"
	@printf "  make setup       check prerequisites and install everything (macOS, Linux)\n"
	@printf "  make doctor      only check prerequisites and local model servers\n"
	@printf "  make install     Sync the Python env with uv (all extras)\n"
	@printf "  make format      ruff format + autofixable lint\n"
	@printf "  make validate    ruff + format check + mypy + import-linter contracts (static only)\n"
	@printf "  make test        validate + unit tests (no model server needed)\n"
	@printf "  make test-live   integration tests against running model servers\n"
	@printf "  make models      list and ping configured models\n"
	@printf "  make smoke       run the smoke experiment and build its report\n"
	@printf "  make contracts   regenerate JSON Schemas, scenario data and conformance vectors\n"
	@printf "  make ui          start the local app on http://127.0.0.1:8787 (ARENA_UI_PORT)\n"
	@printf "  make web         build the web UI (web/dist, served by arena ui)\n"
	@printf "  make test-web    svelte-check + vitest for the web UI\n"
	@printf "  make sandbox-image  build the Docker image that isolates model-written code\n"
	@printf "                      without it, code scenarios require explicit --sandbox unsafe-process\n"

setup:
	sh scripts/setup.sh

doctor:
	sh scripts/setup.sh --check

install:
	uv sync --all-extras --python $(PYTHON_VERSION)

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

validate:
	uv run ruff format --check src tests
	uv run ruff check src tests
	uv run mypy
	uv run lint-imports

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy

test: validate
	uv run pytest -q

test-live:
	uv run pytest -q -m live

ui:
	uv run arena ui

web: web-engine
	cd web && npm ci && npm run build

# The browser engine: the arena wheel plus the conformance vectors for the in-browser self-test.
web-engine:
	rm -rf web/public/py && mkdir -p web/public/py
	uv build --wheel -q -o web/public/py
	uv run python -c "import json, pathlib; vectors = {p.stem: json.loads(p.read_text()) for p in pathlib.Path('contracts/conformance').glob('*.json')}; pathlib.Path('web/public/py/conformance.json').write_text(json.dumps(vectors))"

test-web:
	cd web && npm run contracts && npm run check && npm test

contracts:
	uv run arena contracts

sandbox-image:
	docker build -f docker/sandbox.Dockerfile -t llm-arena-sandbox:latest docker

models:
	uv run arena models ping

smoke:
	uv run arena run configs/experiments/smoke.yaml --report

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
