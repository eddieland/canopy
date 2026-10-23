#!/bin/bash
# Installs prek's git hooks (prek.toml, `make hooks`) in a Claude Code cloud session, so an agent's commit runs the
# formatters and linters before CI does. A local session is left alone: there, installing hooks is the operator's call.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
# `uv run` syncs the environment first if a session's setup has not; prek install is idempotent.
uv run --quiet prek install >/dev/null
