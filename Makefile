.DEFAULT_GOAL := help

.PHONY: help all check fmt lint test coverage snapshots ui-fmt ui-check ui-e2e ui-build install-check sandbox-canary
.PHONY: screenshots test-plugin pool-contract treehouse prompt-sizes burn-in burn-in-py burn-in-ui ui-e2e-burn-in

##@ General

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} \
		/^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2} \
		/^##@ / {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)}' $(MAKEFILE_LIST)

all: fmt check ## Everything to run before committing: fmt, then check

check: lint test ui-check ## Verify without modifying files: lint, test, the UI's checks (what CI runs)

##@ Development

fmt: ui-fmt ## Run autoformatters (ruff imports and trailing commas, ruff format, rumdl for Markdown, oxfmt for ui/)
	uv run ruff check --select I,COM812 --fix .
	uv run ruff format .
	uv run rumdl fmt .

# ruff owns Python and rumdl Markdown; editorconfig-checker holds every other file to .editorconfig.
# zizmor runs offline, so the lint needs no GitHub token and gives the same answer on every machine.
# tsc checks the JSDoc types of the plugin canopy ships for its agents against each pinned OpenCode's (tests/plugins).
lint: tests/plugins/node_modules ## Lint and type check: ruff, pyrefly, rumdl, ec, shellcheck, actionlint, zizmor, tsc
	uv run ruff format --check .
	uv run ruff check .
	uv run pyrefly check
	uv run rumdl check .
	uv run ec
	uv run shellcheck $$(git ls-files '*.sh')
	uv run actionlint
	uv run zizmor --offline --quiet .
	npm --prefix tests/plugins exec -- tsc -p tests/plugins

# One worker per CPU. For one test or a debugger, run `uv run pytest` without -n: it stays serial.
# A test still running after a minute (the slowest takes ~10s) is hung: faulthandler dumps every thread's stack and
# ends its worker, which fails that test by name instead of stalling the run until CI's job timeout. Here, not in
# pyproject.toml, so the opt-in canaries, which wait minutes on a real sandbox or model, keep no limit.
# COVERAGE=1 also measures coverage and writes coverage.xml, which is how CI's `make check` feeds Codecov.
PYTEST := uv run pytest -q -n auto -o faulthandler_timeout=60 -o faulthandler_exit_on_timeout=true

test: test-plugin ## Run all tests, in parallel (COVERAGE=1: also write coverage.xml)
	$(PYTEST) $(if $(COVERAGE),--cov --cov-report=xml)

# The plugin canopy ships in its agents' snapshot is plain JavaScript (DESIGN §33), tested with Node's own runner and
# type-checked by `lint` with the dev-only packages in tests/plugins. The rest of the JavaScript, ui/, is ui-check's.
tests/plugins/node_modules: tests/plugins/package.json tests/plugins/package-lock.json
	npm --prefix tests/plugins ci --no-audit --no-fund
	@touch $@

test-plugin: ## Run the tests of the agent runtime plugin canopy ships (needs Node 22.12+)
	node --test 'tests/plugins/*.test.mjs'

# Coverage settings live in pyproject.toml ([tool.coverage]). Open htmlcov/index.html for the lines a test never ran.
coverage: ## Run all tests measuring coverage: a summary, htmlcov/, and coverage.xml
	$(PYTEST) --cov --cov-report=term:skip-covered --cov-report=html --cov-report=xml

# Review the diff before committing it: a snapshot is what the tests hold canopy's output to (syrupy). It also deletes
# the snapshots no test reads any more. Serial: syrupy refuses to update under xdist without an experimental file lock.
snapshots: ## Run all tests, recording every snapshot that differs
	uv run pytest -q --snapshot-update

# What tests/canopy/test_prompt_sizes.py holds to .agents/sizes.toml, for reading before and after a prompt edit.
prompt-sizes: ## Print each bundled prompt, agent definition, and skill's size in characters and estimated tokens
	uv run python tests/canopy/test_prompt_sizes.py

##@ Flaky tests

# For when a test is suspected of being flaky, and to prove a fix for one: these run the tests a change touched many
# times over, and fail if any run does. Nothing runs them unasked; the Flaky tests workflow runs them on CI's runners on
# demand. BASE is what the change is measured from, by default where this branch left origin/main; ALL=1 runs every
# test instead. REPEAT is how many times each runs.
BASE ?= $(shell git merge-base origin/main HEAD 2>/dev/null)
REPEAT ?= 10
need-base = @test -n "$(ALL)$(BASE)" || { echo "BASE is empty: fetch origin/main, or pass BASE=ref or ALL=1"; exit 1; }

burn-in: burn-in-py burn-in-ui ## Run the Python and UI unit tests changed since BASE (ALL=1: every one) REPEAT times

# Whole runs one after another, not pytest-repeat's parametrized copies: those rename each test, so no syrupy snapshot
# matches, and each run here also spreads the tests across xdist's workers in a different order.
burn-in-py: ## Run each Python test file changed since BASE REPEAT times, the whole file each time
	$(need-base)
	@files=$$($(if $(ALL),echo tests,git diff --name-only --diff-filter=AMR $(BASE) -- 'tests/*test_*.py')); \
	if [ -z "$$files" ]; then echo "No Python test file changed since $(BASE)."; exit 0; fi; \
	for i in $$(seq $(REPEAT)); do \
		echo "Run $$i of $(REPEAT):" $$files; \
		$(PYTEST) $$files || { echo "Failed on run $$i of $(REPEAT): flaky, or broken."; exit 1; }; \
	done

# --changed takes every test a file changed in a commit since BASE reaches through its imports, not only the test files
# changed; it reads no change not yet committed.
burn-in-ui: ui/node_modules ## Run the UI's unit tests that a change since BASE reaches REPEAT times each
	$(need-base)
	npm --prefix ui test -- $(if $(ALL),,--changed $(BASE) --passWithNoTests) --repeats $$(( $(REPEAT) - 1 ))

# --only-changed takes the spec files changed and those whose imports, such as e2e/helpers.ts, changed; not a change
# to the app alone. Skipped without a build when nothing under e2e/ changed.
ui-e2e-burn-in: ui/node_modules ## Build ui/ and run the Playwright spec files changed since BASE REPEAT times each
	$(need-base)
	@$(if $(ALL),,if git diff --quiet $(BASE) -- ui/e2e; then echo "No Playwright test changed."; exit 0; fi;) \
	npm --prefix ui run test:e2e -- $(if $(ALL),,--only-changed=$(BASE) --pass-with-no-tests) --repeat-each=$(REPEAT)

##@ Web UI (ui/; needs Node 22.12+, D079)

ui/node_modules: ui/package.json ui/package-lock.json
	npm --prefix ui ci --no-audit --no-fund
	@touch $@

ui-fmt: ui/node_modules ## Format ui/ with oxfmt
	npm --prefix ui run fmt

# COVERAGE=1 also measures the unit tests' coverage and writes ui/coverage/lcov.info, which CI sends to Codecov.
ui-check: ui/node_modules ## Check ui/ without changing it: format, lint, types, generated API types, unit tests, build
	$(if $(COVERAGE),COVERAGE=1 )npm --prefix ui run check

ui-build: ui/node_modules ## Build ui/dist, which canopy serves from a checkout and bundles into its wheel
	npm --prefix ui run build

# Not part of check: it needs a browser. CI runs it as its own job. PLAYWRIGHT_CHROMIUM_EXECUTABLE points it at a
# preinstalled Chromium instead of the one `npx playwright install chromium` downloads. SHARD=i/n runs the i-th of n
# slices, as CI's jobs do.
ui-e2e: ui/node_modules ## Build ui/ and run Playwright against it served by FastAPI (SHARD=i/n: one slice of it)
	npm --prefix ui run test:e2e$(if $(SHARD), -- --shard=$(SHARD))

# Not part of check: it needs Docker. The Screenshots workflow stays CI's way to regenerate the baselines; this renders
# the same images locally, in Playwright's Ubuntu image at the version ui/package.json pins, in under a minute once the
# image and its cache volume are pulled. UPDATE is changed (rewrite the images that fail the comparison), all (rewrite
# every one), or check (compare only).
screenshots: ## Regenerate the Playwright screenshot baselines in Docker, as CI renders them (UPDATE=changed|all|check)
	ui/scripts/screenshots.sh $(or $(UPDATE),changed)

# Not part of check: it downloads canopy's dependencies into an empty cache. CI runs it as its own job.
# INSTALL_SOURCE is what to install: this checkout by default, or anything `uv tool install` accepts.
install-check: ## Install canopy into an empty HOME and run it against the fakes (INSTALL_SOURCE: default this checkout)
	tests/install-check.sh $(INSTALL_SOURCE)

# Not part of check: it needs what `canopy sandbox setup` installs and checks, and runs as you, not root. CI runs it as
# its own job, on Linux (DESIGN §24, The canary, docs/SANDBOX.md).
sandbox-canary: ## Check that the sandbox holds: the shipped wrapper and templates under the real srt
	CANOPY_SANDBOX_CANARY=1 uv run pytest -q -n auto tests/canopy_sandbox/test_sandbox_canary.py

# Not part of check: it needs real treehouse on PATH (`make treehouse`). `make test` runs the same suite against the
# fake, and against real treehouse too when it is on PATH; this fails where that skips. CI runs it as its own job, on
# Linux (ROADMAP M45, DESIGN §18 What a pool guarantees).
pool-contract: ## Check that real treehouse keeps every guarantee canopy takes from a pool
	CANOPY_POOL_CONTRACT=1 uv run pytest -q -n auto tests/canopy/core/test_pool_contract.py

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
