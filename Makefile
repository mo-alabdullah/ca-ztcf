# CA-ZTCF developer entry points.
PY ?= python3
PKG := src/ca_ztcf
COMPOSE := docker compose -f deploy/compose/core.yml

.DEFAULT_GOAL := help
.PHONY: help install format lint typecheck test test-cov check secret-scan \
        docker-build docker-up docker-down docker-logs smoke env clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with development extras
	$(PY) -m pip install -e '.[dev]'

format: ## Apply automatic formatting and import ordering
	$(PY) -m ruff format src tests scripts
	$(PY) -m ruff check --fix src tests scripts

lint: ## Static lint (ruff)
	$(PY) -m ruff check src tests scripts
	$(PY) -m ruff format --check src tests scripts

typecheck: ## Static type check (mypy)
	$(PY) -m mypy

test: ## Run the test suite
	$(PY) -m pytest

test-cov: ## Run the test suite with coverage
	$(PY) -m pytest --cov=ca_ztcf --cov-report=term-missing --cov-report=xml

check: lint typecheck test ## Run every quality gate

secret-scan: ## Heuristic scan of tracked content for credential material
	$(PY) scripts/secret_scan.py

env: ## Capture reproducibility metadata for the development environment
	$(PY) scripts/collect_env.py --out artifacts/dev-validation

docker-build: ## Build the CA-ZTCF container image
	$(COMPOSE) build

docker-up: ## Start the CA-ZTCF core service
	$(COMPOSE) up -d

docker-down: ## Stop the CA-ZTCF core service
	$(COMPOSE) down -v

docker-logs: ## Follow service logs
	$(COMPOSE) logs -f

smoke: ## Run the development validation flow against a running service
	$(PY) scripts/dev_validation_flow.py --base-url http://127.0.0.1:8080 --out artifacts/dev-validation

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info src/*.egg-info coverage.xml .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
