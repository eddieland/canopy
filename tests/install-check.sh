#!/bin/sh
# Install canopy the way README step 2 does, as a new user would, and run it end to end against the fakes (ROADMAP M5).
# Everything happens under a temporary HOME with its own uv tool and cache directories, so nothing from this checkout's
# virtual environment or the caller's home is visible. Needs uv, git, python3, and network access to the package index.
#
# Usage: tests/install-check.sh [SOURCE]
#   SOURCE is anything `uv tool install` accepts: this checkout by default, or git+https://github.com/eddieland/canopy
#   to check what README tells people to run. Or it is the single executable `make binary` builds (D067), installed
#   the way README says to install a release: copied onto PATH as `canopy`, with the sinks as links to it.
set -eu

repo=$(cd "$(dirname "$0")/.." && pwd)
source=${1:-$repo}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

export HOME="$work/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_DATA_HOME="$HOME/.local/share" XDG_CACHE_HOME="$HOME/.cache"
export UV_TOOL_DIR="$work/tools" UV_TOOL_BIN_DIR="$work/bin" UV_CACHE_DIR="$work/uv-cache"
export USER=installcheck
unset VIRTUAL_ENV CANOPY_TICK_ID
mkdir -p "$HOME"

fail() {
    echo "install-check: $*" >&2
    exit 1
}

if [ -f "$source" ] && [ -x "$source" ]; then
    echo "install-check: single executable $source"
    binary=1
    mkdir -p "$UV_TOOL_BIN_DIR"
    cp "$source" "$UV_TOOL_BIN_DIR/canopy"
    ln -s canopy "$UV_TOOL_BIN_DIR/canopy-notify-desktop"
    ln -s canopy "$UV_TOOL_BIN_DIR/canopy-notify-slack"
else
    echo "install-check: uv tool install $source"
    binary=0
    uv tool install --quiet "$source"
fi

# The installed canopy first, then the fake treehouse and agent. The fakes are stdlib-only scripts.
export PATH="$UV_TOOL_BIN_DIR:$repo/tests/fakes:$PATH"
[ "$(command -v canopy)" = "$UV_TOOL_BIN_DIR/canopy" ] || fail "canopy on PATH is $(command -v canopy), not the install"

canopy --version
canopy --help >/dev/null
# The sinks canopy ships come with the same install (DESIGN §20).
for sink in canopy-notify-desktop canopy-notify-slack; do
    [ "$(command -v "$sink")" = "$UV_TOOL_BIN_DIR/$sink" ] || fail "$sink was not installed with canopy"
    # canopy's own --help succeeds too, so the usage line must name the sink: a link that runs canopy fails here.
    usage=$("$sink" --help </dev/null) || fail "$sink --help failed"
    echo "$usage" | grep -q "^usage: $sink " || fail "$sink --help did not print the sink's usage"
done
# Output is captured before grep, so a command that fails after printing the expected text still fails the check.
skill=$(canopy skill)
echo "$skill" | grep -qx 'name: canopy' || fail "canopy skill did not print the operator skill"

project="$work/project"
mkdir -p "$project"
cd "$project"
git init --quiet
git remote add origin https://example.test/team/project.git
canopy init --provider github

# Point the runtime at the fake agent, keeping {definitions_dir} as the templates require.
config="$XDG_CONFIG_HOME/canopy/config.toml"
sed 's/opencode run --agent/agent --agent/' "$config" >"$config.new"
mv "$config.new" "$config"

export FAKE_TREEHOUSE_STATE="$work/treehouse.json"
export FAKE_AGENT_RESULT="tick complete"
export FAKE_AGENT_COMMANDS='[["canopy", "decide", "GH-1", "wait", "--rationale", "install check"]]'
canopy tick --dry-run
decisions=$(canopy decisions)
echo "$decisions" | grep -q 'GH-1  wait  install check' || fail "the dry tick's decision was not recorded"
canopy status >/dev/null

# The migrations, prompts, agent definitions, and skills came from the wheel, not from this checkout.
state="$HOME/.canopy"
ls "$state"/runtime/*/agents/canopy-worker.md >/dev/null || fail "no agent definitions snapshot in $state/runtime"
if [ "$binary" = 1 ]; then
    # The executable cannot run a script of ours, and has no path to this checkout. What it snapshotted must be what
    # this checkout ships.
    for dir in agents skills; do
        diff -r "$repo/.agents/$dir" "$state"/runtime/*/"$dir" >/dev/null || fail "the snapshot's $dir are not .agents/"
    done
    echo "install-check: ok"
    exit 0
fi
"$UV_TOOL_DIR/canopy/bin/python" -c '
import sys
from pathlib import Path
from canopy.infra import resources
tool = Path(sys.argv[1]).resolve()  # resources resolves symlinks, such as macOS /var -> /private/var
for found in (resources.migrations_dir(), resources.prompts_dir(), resources.agents_dir(), resources.skills_dir()):
    if not found.is_relative_to(tool):
        sys.exit(f"install-check: {found} is outside the installed tool")
' "$UV_TOOL_DIR"

echo "install-check: ok"
