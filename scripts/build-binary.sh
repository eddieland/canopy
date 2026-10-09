#!/bin/sh
# Build dist/canopy: one executable holding Python, canopy, its sinks and relay, and the dependencies uv.lock pins
# (D067). It runs on a machine with no Python, no uv, and no access to the package index, for the platform it is built
# on. The release workflow builds it on each runner it ships for.
#
# The file is a pex in venv mode, wrapped in a scie that carries a python-build-standalone interpreter. Venv mode
# matters: dispatch starts `_run` as `sys.executable -m canopy` (DESIGN §5), which needs an interpreter that can import
# canopy. It is a BusyBox over canopy's four commands: run under the name of one, or with that name as the first
# argument, it runs that command.
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
# hash makes pip require one on every line, so the two local wheels get theirs appended.
uv export --quiet --frozen --no-dev --no-emit-workspace -o "$dist/requirements.txt"
for wheel in "$dist"/wheels/*.whl; do
    echo "$wheel --hash=sha256:$(shasum -a 256 "$wheel" | cut -d' ' -f1)" >>"$dist/requirements.txt"
done

# The commands, by the names the links to the executable carry.
busybox=canopy,canopy-notify-desktop,canopy-notify-slack=canopy_notify_slack:main
busybox="$busybox,canopy-notify-relay=canopy_notify_relay:main"

# --no-emit-warnings: canopy lists its workspace members' scripts among its own (D064), and pex warns about each
# collision on every first run although both name the same function.
uvx --python "$PYTHON_VERSION" "pex@$PEX_VERSION" \
    -r "$dist/requirements.txt" \
    --venv \
    --no-emit-warnings \
    --scie eager \
    --scie-only \
    --scie-pbs-release "$PBS_RELEASE" \
    --scie-python-version "$PYTHON_VERSION" \
    --scie-pbs-stripped \
    --scie-busybox "$busybox" \
    -o "$dist/canopy"

"$dist/canopy" --version
echo "build-binary: $dist/canopy"
