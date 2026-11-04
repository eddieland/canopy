#!/bin/bash
# Installs prek's git hooks (prek.toml, `make hooks`) in a Claude Code cloud session, so an agent's commit runs the
# formatters and linters before CI does. A local session is left alone: there, installing hooks is the operator's call.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
# As `make hooks` does: Git LFS's hooks first, which prek keeps and runs, so a push uploads the screenshot baselines.
# `uv run` syncs the environment first if a session's setup has not; both installs are idempotent in this order.
if command -v git-lfs >/dev/null; then
    git lfs install --local --force >/dev/null
fi
uv run --quiet prek install >/dev/null
