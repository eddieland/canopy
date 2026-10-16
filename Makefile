.DEFAULT_GOAL := help

.PHONY: help all check fmt lint test snapshots ui-fmt ui-check ui-e2e ui-build install-check sandbox-canary treehouse

##@ General

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} \
		/^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2} \
		/^##@ / {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)}' $(MAKEFILE_LIST)

all: fmt check ## Everything to run before committing: fmt, then check

check: lint test ui-check ## Verify without modifying files: lint, test, the UI's checks (what CI runs)

##@ Development

fmt: ui-fmt ## Run autoformatters (ruff import sorting, ruff format, rumdl for Markdown, oxfmt for ui/)
	uv run ruff check --select I --fix .
	uv run ruff format .
	uv run rumdl fmt .

# ruff owns Python and rumdl Markdown; editorconfig-checker holds every other file to .editorconfig.
lint: ## Run linters and the type checker (ruff, pyrefly strict, rumdl, editorconfig-checker, shellcheck, actionlint)
	uv run ruff format --check .
	uv run ruff check .
	uv run pyrefly check
	uv run rumdl check .
	uv run ec
	uv run shellcheck $$(git ls-files '*.sh')
	uv run actionlint

# One worker per CPU. For one test or a debugger, run `uv run pytest` without -n: it stays serial.
test: ## Run all tests, in parallel
	uv run pytest -q -n auto

# Review the diff before committing it: a snapshot is what the tests hold canopy's output to (tests/snapshot.py).
snapshots: ## Run all tests, recording every snapshot under tests/snapshots/ that differs
	uv run pytest -q -n auto --update-snapshots

##@ Web UI (ui/; needs Node 22.12+, D079)

ui/node_modules: ui/package.json ui/package-lock.json
	npm --prefix ui ci --no-audit --no-fund
	@touch $@

ui-fmt: ui/node_modules ## Format ui/ with oxfmt
	npm --prefix ui run fmt

ui-check: ui/node_modules ## Check ui/ without changing it: format, lint, types, generated API types, unit tests, build
	npm --prefix ui run check

ui-build: ui/node_modules ## Build ui/dist, which canopy serves from a checkout and bundles into its wheel
	npm --prefix ui run build

# Not part of check: it needs a browser. CI runs it as its own job. PLAYWRIGHT_CHROMIUM_EXECUTABLE points it at a
# preinstalled Chromium instead of the one `npx playwright install chromium` downloads.
ui-e2e: ui/node_modules ## Build ui/ and run Playwright against it served by FastAPI
	npm --prefix ui run test:e2e

# Not part of check: it downloads canopy's dependencies into an empty cache. CI runs it as its own job.
# INSTALL_SOURCE is what to install: this checkout by default, or anything `uv tool install` accepts.
install-check: ## Install canopy into an empty HOME and run it against the fakes (INSTALL_SOURCE: default this checkout)
	tests/install-check.sh $(INSTALL_SOURCE)

# Not part of check: it needs what `canopy sandbox setup` installs and checks, and runs as you, not root. CI runs it as
# its own job, on Linux (DESIGN §24, The canary, docs/SANDBOX.md).
sandbox-canary: ## Check that the sandbox holds: the shipped wrapper and templates under the real srt
	CANOPY_SANDBOX_CANARY=1 uv run pytest -q -n auto tests/canopy/test_sandbox_canary.py

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
