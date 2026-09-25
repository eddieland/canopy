.DEFAULT_GOAL := help

.PHONY: help all check fmt lint test install-check treehouse

##@ General

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} \
		/^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2} \
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

# Not part of check: it downloads canopy's dependencies into an empty cache. CI runs it as its own job.
install-check: ## Install canopy with uv tool install into an empty HOME and run it against the fakes
	tests/install-check.sh

##@ Setup

TREEHOUSE_REPO := https://github.com/kunchenguid/treehouse
# Newest release tag unless overridden, e.g. `make treehouse TREEHOUSE_VERSION=v2.3.0`.
TREEHOUSE_VERSION ?= $(shell git ls-remote --tags --refs --sort=-v:refname $(TREEHOUSE_REPO) 'v*' \
	| head -1 | sed 's|.*refs/tags/||')

# Built from source by commit: treehouse tags v2+ without a /v2 module path, so `go install ...@latest` stops at v1.8.0
# and `@v2.x` is rejected. The prebuilt release binaries need glibc 2.34+. CGO_ENABLED=0 gives a static binary.
treehouse: ## Install treehouse (TREEHOUSE_VERSION, default newest release) with go install
	@sha=$$(git ls-remote $(TREEHOUSE_REPO) 'refs/tags/$(TREEHOUSE_VERSION)^{}' 'refs/tags/$(TREEHOUSE_VERSION)' \
		| sort -k2 | tail -1 | cut -f1); \
	test -n "$$sha" || { echo "no treehouse tag $(TREEHOUSE_VERSION)"; exit 1; }; \
	echo "installing treehouse $(TREEHOUSE_VERSION) ($$sha)"; \
	CGO_ENABLED=0 go install github.com/kunchenguid/treehouse@$$sha
	@command -v treehouse >/dev/null 2>&1 || echo "treehouse is installed but not on PATH (add \$$(go env GOPATH)/bin)"
	@! command -v treehouse >/dev/null 2>&1 || treehouse status --help 2>&1 | grep -q -- --json || \
		echo "warning: $$(command -v treehouse) comes first on PATH and is too old (no --json); remove it"
