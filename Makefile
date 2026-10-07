.DEFAULT_GOAL := help

.PHONY: help all check fmt lint test install-check binary treehouse

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
# INSTALL_SOURCE is what to install: this checkout by default, or dist/canopy after `make binary`.
install-check: ## Install canopy into an empty HOME and run it against the fakes (INSTALL_SOURCE: default this checkout)
	tests/install-check.sh $(INSTALL_SOURCE)

##@ Release

binary: ## Build dist/canopy, one executable with Python and the locked dependencies, for this platform (D067)
	scripts/build-binary.sh

##@ Setup

TREEHOUSE_REPO := https://github.com/kunchenguid/treehouse
# A release tag, commit, or branch, e.g. `make treehouse TREEHOUSE_VERSION=v2.4.0`. The default is a pinned commit, not
# the newest release: canopy needs `base_branch` in `get --lease --json`, which no release has yet (v2.3.0 lacks it).
# Move to a release tag once one includes it. README's install step names the same commit; keep the two in sync.
TREEHOUSE_VERSION ?= 1185dc6cc50e1b66ef5c74b8ac677a6251258abc

# Built from source by commit: treehouse tags v2+ without a /v2 module path, so `go install ...@latest` stops at v1.8.0
# and `@v2.x` is rejected. The prebuilt release binaries need glibc 2.34+, so `treehouse update` can install one that
# does not run. CGO_ENABLED=0 gives a static binary.
treehouse: ## Install treehouse (TREEHOUSE_VERSION: tag, commit, or branch; default a pinned commit) with go install
	@sha=$$(git ls-remote $(TREEHOUSE_REPO) 'refs/tags/$(TREEHOUSE_VERSION)^{}' 'refs/tags/$(TREEHOUSE_VERSION)' \
		'refs/heads/$(TREEHOUSE_VERSION)' | sort -k2 | tail -1 | cut -f1); \
	sha=$${sha:-$(TREEHOUSE_VERSION)}; \
	echo "installing treehouse $(TREEHOUSE_VERSION) ($$sha)"; \
	CGO_ENABLED=0 go install github.com/kunchenguid/treehouse@$$sha && \
	if ! command -v treehouse >/dev/null 2>&1; then \
		echo "treehouse is installed but not on PATH (add $$(go env GOPATH)/bin)"; \
	elif ! treehouse --version 2>&1 | grep -q -- "$$(echo $$sha | cut -c1-12)"; then \
		echo "warning: $$(command -v treehouse) comes first on PATH and is not the one just installed; remove it"; \
	fi
