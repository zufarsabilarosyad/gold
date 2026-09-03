# ==============================================================================
# Basalt Makefile
# ==============================================================================

.PHONY: help install dev-install test test-cov lint format clean docker-build docker-run server doctor

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
MYPY ?= .venv/bin/mypy
BASALT ?= .venv/bin/basalt

help: ## Display available Makefile targets
	@echo "Basalt Development & Administration Makefile"
	@echo "============================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies and package in editable mode
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

dev-install: install ## Install all development dependencies
	$(PIP) install -e ".[dev]"

test: ## Execute complete unit and integration test suite
	$(PYTEST) tests/

test-cov: ## Execute pytest test suite with code coverage report
	$(PYTEST) --cov=basalt --cov-report=term-missing tests/

lint: ## Run static linting analysis (ruff and mypy)
	$(RUFF) check src/ tests/
	$(MYPY) src/

format: ## Auto-format source code with ruff
	$(RUFF) format src/ tests/

clean: ## Recursively clean __pycache__, cache directories, and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type f -name ".DS_Store" -delete
	rm -rf .pytest_cache .mypy_cache .coverage .ruff_cache htmlcov dist build ctrf-report.json

docker-build: ## Build production Docker container image (basalt:latest)
	docker build -t basalt:latest .

docker-run: ## Run production Docker container binding port 8000
	docker run -d --name basalt_engine -p 8000:8000 basalt:latest

server: ## Launch local FastAPI REST API server
	$(BASALT) server start --host 127.0.0.1 --port 8000

doctor: ## Run Basalt environment diagnostics check
	$(BASALT) doctor
