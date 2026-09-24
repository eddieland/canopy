.DEFAULT_GOAL := help

.PHONY: help all check fmt lint test

##@ General

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} \
		/^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2} \
		/^##@ / {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)}' $(MAKEFILE_LIST)

all: fmt check ## Everything to run before committing: fmt, then check

check: lint test ## Verify without modifying files: lint, test (what CI runs)

##@ Development

fmt: ## Run autoformatters (ruff import sorting, ruff format)
	uv run ruff check --select I --fix .
	uv run ruff format .

lint: ## Run linters and the type checker (ruff, pyrefly strict)
	uv run ruff format --check .
	uv run ruff check .
	uv run pyrefly check

test: ## Run all tests
	uv run pytest -q
