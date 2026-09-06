# CA-ZTCF developer entry points.
PY ?= python3
PKG := src/ca_ztcf
COMPOSE := docker compose -f deploy/compose/core.yml
TESTBED := docker compose -f deploy/compose/testbed.yml

.DEFAULT_GOAL := help
.PHONY: help install format lint typecheck test test-cov check secret-scan \
        docker-build docker-up docker-down docker-logs smoke env clean \
        testbed-build testbed-up testbed-down tier1-wlan experiments \
        process verify gates tier2-up tier2-services tier2-access \
        tier2-validate tier2-reset

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

gates: check secret-scan verify ## Quality gates plus the research safety gates

testbed-build: ## Build every Tier-1 testbed image
	$(TESTBED) build

testbed-up: ## Start core, Mosquitto and the MQTT enforcement point
	$(TESTBED) up -d ca-ztcf-core mosquitto ca-ztcf-mqtt-pep

testbed-down: ## Stop the Tier-1 testbed
	$(TESTBED) down -v

tier1-wlan: ## Run the Tier-1 802.1X/EAP-TLS WLAN authentication-path emulation
	$(TESTBED) --profile wlan run --rm tier1-wlan

tier2-up: ## Start the Tier-2 software-based testbed VM
	limactl start ca-ztcf-tier2 || limactl start testbed/tier2/ca-ztcf-tier2.yaml

tier2-services: ## Start the CA-ZTCF stack inside the Tier-2 VM
	limactl shell ca-ztcf-tier2 sudo bash /opt/ca-ztcf/testbed/tier2/scripts/start_services.sh

tier2-access: ## Bring up the live 5G and WLAN access paths in the Tier-2 VM
	limactl shell ca-ztcf-tier2 sudo bash /opt/ca-ztcf/testbed/tier2/scripts/start_5g.sh
	limactl shell ca-ztcf-tier2 sudo bash /opt/ca-ztcf/testbed/tier2/scripts/start_wlan.sh

tier2-validate: ## Run the Tier-2 dual-access validation flow
	limactl shell ca-ztcf-tier2 sudo /opt/ca-ztcf-venv/bin/python \
		/opt/ca-ztcf/testbed/tier2/scripts/tier2_validation.py

tier2-reset: ## Reset the Tier-2 testbed to a known state
	limactl shell ca-ztcf-tier2 sudo bash /opt/ca-ztcf/testbed/tier2/scripts/reset.sh

experiments: ## Run E01-E05 under all three strategies (Tier-1 development validation)
	$(PY) scripts/run_matrix.py

process: ## Regenerate development tables and figures from raw output
	$(PY) scripts/process_results.py

verify: ## Verify expectations, reproducibility and the research safety gates
	$(PY) scripts/verify_expectations.py
	$(PY) scripts/verify_results.py
	$(PY) scripts/check_source_modes.py
	$(PY) scripts/check_output_privacy.py

secret-scan: ## Heuristic scan of tracked content for credential material
	$(PY) scripts/secret_scan.py
	$(PY) scripts/check_output_privacy.py

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
