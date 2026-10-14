#!/bin/sh
# Build dist/canopy: one executable holding Python, canopy, canopy-notify-slack, canopy-sandbox, and the dependencies
# uv.lock pins (D067). It runs on a machine with no Python, no uv, and no access to the package index, for the platform
# it is built on. The release workflow builds it on each runner it ships for.
#
# The file is a pex in venv mode, wrapped in a scie that carries a python-build-standalone interpreter. Venv mode
# matters: dispatch starts `_run` as `sys.executable -m canopy` (DESIGN §5), which needs an interpreter that can import
# canopy. It is a BusyBox over canopy's four commands: SCIE_BOOT names the one to run, and unset, its name `canopy`
# picks canopy. README installs the sinks, and `canopy sandbox setup` names the wrapper, as scripts that set SCIE_BOOT,
# not links named for them: a link can run canopy itself, and SCIE_BOOT picks the command whatever the name.
#
# Usage: scripts/build-binary.sh
set -eu

# Pinned, so a build is the same from one day to the next. Move them together with a uv.lock bump when needed.
PEX_VERSION=2.103.4
PBS_RELEASE=20260718
PYTHON_VERSION=3.12.13

repo=$(cd "$(dirname "$0")/.." && pwd)
dist="$repo/dist"
rm -rf "$dist"
mkdir -p "$dist"
cd "$repo"

uv build --quiet --all-packages --wheel -o "$dist/wheels"
# Pins and hashes for everything but the workspace's own packages, whose wheels were just built. A requirement with a
# hash makes pip require one on every line, so the local wheels get theirs appended.
uv export --quiet --frozen --no-dev --no-emit-workspace -o "$dist/requirements.txt"
for wheel in "$dist"/wheels/*.whl; do
    echo "$wheel --hash=sha256:$(shasum -a 256 "$wheel" | cut -d' ' -f1)" >>"$dist/requirements.txt"
done

# The commands SCIE_BOOT picks between; a workspace member's names its entry point.
commands=canopy,canopy-notify-desktop,canopy-notify-slack=canopy_notify_slack:main,canopy-sandbox=canopy_sandbox:main

# --no-emit-warnings: canopy lists canopy-notify-slack's and canopy-sandbox's scripts among its own (D035), and pex
# warns about each collision on every first run although both sides name the same function.
uvx --python "$PYTHON_VERSION" "pex@$PEX_VERSION" \
    -r "$dist/requirements.txt" \
    --venv \
    --no-emit-warnings \
    --scie eager \
    --scie-only \
    --scie-pbs-release "$PBS_RELEASE" \
    --scie-python-version "$PYTHON_VERSION" \
    --scie-pbs-stripped \
    --scie-busybox "$commands" \
    -o "$dist/canopy"

"$dist/canopy" --version
echo "build-binary: $dist/canopy"
