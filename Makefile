# StockPilot developer commands. Everything runs inside the locked uv environment.
# Later steps replace the "not implemented yet" placeholders (see docs/ROADMAP.md).

UV ?= uv
RUN := $(UV) run --locked
DATA_DIR ?= data
SEED ?= 42

.DEFAULT_GOAL := help
.PHONY: help install data data-small validate-data test lint format ci clean clean-data \
	audit forecast optimize simulate mcp dashboard release

define not_implemented
	@echo "make $@: not implemented yet - see docs/ROADMAP.md (Step $(1))" >&2; exit 1
endef

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Create .venv from uv.lock (runtime + dev tools)
	$(UV) sync --locked

data: ## Generate the default synthetic dataset into $(DATA_DIR)/ and validate it
	$(RUN) stockpilot synth --preset default --seed $(SEED) --out $(DATA_DIR)
	$(RUN) stockpilot validate --data $(DATA_DIR)

data-small: ## Generate the small preset into data-small/ (quick experiments)
	$(RUN) stockpilot synth --preset small --seed $(SEED) --out data-small
	$(RUN) stockpilot validate --data data-small

validate-data: ## Re-check an existing dataset against its manifest and targets
	$(RUN) stockpilot validate --data $(DATA_DIR)

test: ## Run the test suite
	$(RUN) pytest

lint: ## Check lint rules and formatting (no changes)
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Apply formatting and safe lint fixes
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

ci: lint test ## What CI runs on every push and pull request

clean: ## Remove caches and build artefacts (keeps data/)
	rm -rf .pytest_cache .ruff_cache build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

clean-data: ## Remove generated datasets (regenerate with make data)
	rm -rf $(DATA_DIR) data-small

audit: ## Step 2 - data quality audit
	$(call not_implemented,2)

forecast: ## Step 3 - forecasting tournament
	$(call not_implemented,3)

optimize: ## Step 4 - safety stock and reorder points
	$(call not_implemented,4)

simulate: ## Step 4 - policy simulation in THB
	$(call not_implemented,4)

mcp: ## Step 5 - MCP agent server
	$(call not_implemented,5)

dashboard: ## Step 6 - static dashboard
	$(call not_implemented,6)

release: ## Step 7 - release checks
	$(call not_implemented,7)
