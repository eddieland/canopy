#!/bin/sh
# Install canopy the way README step 2 does, as a new user would, and run it end to end against the fakes (ROADMAP M5).
# Everything happens under a temporary HOME with its own uv tool and cache directories, so nothing from this checkout's
# virtual environment or the caller's home is visible. Needs uv, git, python3, and network access to the package index.
#
# Usage: tests/install-check.sh [SOURCE]
#   SOURCE is anything `uv tool install` accepts: this checkout by default, or git+https://github.com/eddieland/canopy
#   to check what README tells people to run. Or it is the single executable `make binary` builds (D067), installed
#   the way README says to install a release: copied onto PATH as `canopy`, with the sinks as scripts that run it.
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
    # README's loop, in a subshell so the cd does not stick. The link is what an older README installed: the loop must
    # replace it, not write through it to canopy.
    (
        cd "$UV_TOOL_BIN_DIR" && chmod +x canopy
        ln -s canopy canopy-notify-slack
        for sink in canopy-notify-desktop canopy-notify-slack; do
            rm -f "$sink" && printf '#!/bin/sh\nexec env SCIE_BOOT=%s "%s/canopy" "$@"\n' "$sink" "$PWD" >"$sink"
            chmod +x "$sink"
        done
    )
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
    # canopy's own --help succeeds too, so the usage line must name the sink: a command that runs canopy fails here.
    usage=$("$sink" --help </dev/null) || fail "$sink --help failed"
    echo "$usage" | grep -q "^usage: $sink " || fail "$sink --help did not print the sink's usage"
done
# Output is captured before grep, so a command that fails after printing the expected text still fails the check.
skill=$(canopy skill)
echo "$skill" | grep -qx 'name: canopy' || fail "canopy skill did not print the operator skill"

# A workspace of one repository, cloned from a local origin as `canopy init` clones any URL it is given.
origin="$work/project.git"
git init --quiet --bare "$origin"
seed="$work/seed"
git init --quiet "$seed"
git -C "$seed" -c user.name=install -c user.email=install@example.test commit --quiet --allow-empty -m initial
git -C "$seed" push --quiet "$origin" HEAD
workspace="$work/acme"
mkdir -p "$workspace"
cd "$workspace"
canopy init --provider github "project=$origin"
[ -d "$workspace/repos/project/.git" ] || fail "canopy init did not clone the repository into the workspace"

# Point the runtime at the fake agent, keeping {definitions_dir} as the templates require. init writes no [runtime]:
# the defaults run OpenCode.
config="$XDG_CONFIG_HOME/canopy/config.toml"
cat >>"$config" <<'TOML'

[runtime]
overseer_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} agent --agent canopy-overseer --format json {prompt}'
worker_cmd = 'env OPENCODE_CONFIG_DIR={definitions_dir} agent --agent canopy-worker --format json {prompt}'
TOML

export FAKE_TREEHOUSE_STATE="$work/treehouse.json"
export FAKE_AGENT_RESULT="CANOPY_TICK_DONE"
export FAKE_AGENT_COMMANDS='[["canopy", "decide", "GH-1", "wait", "--rationale", "install check"]]'
canopy tick --dry-run
decisions=$(canopy decisions)
echo "$decisions" | grep -q 'GH-1  wait  install check' || fail "the dry tick's decision was not recorded"
canopy status >/dev/null

# canopy runs each sink by the name in its cmd (DESIGN §20), as a child of its own process. The Slack sink has no
# webhook file and fails saying so; the desktop sink shows the test or fails in its own words. canopy run in a sink's
# place would reject the sink's arguments or print its own usage instead.
cat >>"$config" <<'TOML'

[notify.sinks.slack]
cmd = "canopy-notify-slack --webhook-file /nonexistent/slack-webhook"

[notify.sinks.desktop]
cmd = "canopy-notify-desktop"
TOML
sinks=$(canopy notify test) && fail "canopy notify test passed"
echo "$sinks" | grep -q '^slack: failed: exited 2: canopy-notify-slack: cannot read the webhook file' ||
    fail "canopy did not run canopy-notify-slack: $sinks"
echo "$sinks" | grep -Eq '^desktop: (delivered|failed: exited [12]: canopy-notify-desktop: )' ||
    fail "canopy did not run canopy-notify-desktop: $sinks"
sed -i.bak '/^\[notify\.sinks\./,$d' "$config"

# The web UI (DESIGN §22): the listener secret, then the loop serving the UI this install bundles. The wheel bundles it
# when npm was on PATH at build time; a release always has it.
secret=$(canopy secret 2>/dev/null)
[ "${#secret}" -ge 32 ] || fail "canopy secret printed no secret"
printf '\n[serve]\nport = 18765\n' >>"$config"
loop=$(canopy loop --dry-run --ticks 1)
echo "$loop" | grep -q 'web UI .*http://127.0.0.1:18765/' || fail "canopy loop did not serve the web UI"
if [ "$binary" = 1 ] || command -v npm >/dev/null; then
    if echo "$loop" | grep -q 'not built'; then fail "the web UI is not built into this install"; fi
fi

# The migrations, prompts, agent definitions, and skills came from the wheel, not from this checkout.
state="$workspace/.canopy"
ls "$state"/runtime/*/agents/canopy-worker.md >/dev/null || fail "no agent definitions snapshot in $state/runtime"
if [ "$binary" = 1 ]; then
    # The executable cannot run a script of ours, and has no path to this checkout. What it snapshotted must be what
    # this checkout ships.
    # The private worker's definition is rendered with the tracker's server and tools (DESIGN §22): with those lines,
    # the only ones a two-space quoted key on the github server starts, taken out, it is the shipped file.
    # The overseer's is rendered with its prompt from its marked line on (DESIGN §13): above that line it is the shipped
    # file, and the prompt follows.
    private=agents/canopy-worker-private.md
    overseer=agents/canopy-overseer.md
    for dir in agents skills; do
        diff -r -x "${private#agents/}" -x "${overseer#agents/}" "$repo/.agents/$dir" "$state"/runtime/*/"$dir" \
            >/dev/null || fail "the snapshot's $dir are not .agents/"
    done
    grep -q '^  "github_\*": deny$' "$state"/runtime/*/"$private" ||
        fail "the snapshot's $private names no tracker tools"
    grep -v '^  "github_' "$state"/runtime/*/"$private" | diff - "$repo/.agents/$private" >/dev/null ||
        fail "the snapshot's $private is not .agents/ with the tracker's tools"
    head=$(sed -n '/^<!-- canopy: overseer prompt -->$/q;p' "$repo/.agents/$overseer" | wc -l)
    prompt="$repo/.agents/prompts/overseer.md"
    { head -n "$head" "$repo/.agents/$overseer" && cat "$prompt"; } >"$work/overseer.md"
    head -n "$((head + $(wc -l <"$prompt")))" "$state"/runtime/*/"$overseer" | diff - "$work/overseer.md" >/dev/null ||
        fail "the snapshot's $overseer is not .agents/ with the overseer's prompt"
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
