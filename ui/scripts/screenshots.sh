#!/usr/bin/env bash
# Regenerates the Playwright screenshot baselines locally, in Docker, so they match the ones CI's ubuntu-latest runner
# makes: Playwright's own Ubuntu 24.04 image at the @playwright/test version ui/package.json pins, run with CI=1, the
# spec files the Screenshots workflow runs, and oxipng at the version and digest that workflow pins. It is the local
# twin of .github/workflows/screenshots.yml, which stays CI's way; `make screenshots` runs it. Needs Docker.
#
# Usage: ui/scripts/screenshots.sh [changed|all|check] [CHECKOUT]
#   changed (the default) rewrites the images that fail the comparison and writes missing ones, all rewrites every
#   one, and check only compares, writing none. CHECKOUT is a canopy checkout, this one by default.
#
# The checkout's tracked and untracked (not ignored) files are copied into the container, so its node_modules, .venv,
# and ui/dist are never touched. Downloads persist in the Docker volume canopy-shots-cache. SHOTS_WORKERS sets
# Playwright's workers (default 4): its own default, half the CPUs, starves the one mock server on a big machine and
# the live stream times out, where CI's 4-CPU runner gets 2.
set -euo pipefail

usage() {
    echo "usage: $0 [changed|all|check] [CHECKOUT]" >&2
    exit 2
}
[ $# -le 2 ] || usage
MODE=${1:-changed}
case "$MODE" in changed | all | check) ;; *) usage ;; esac
WT=$(cd "${2:-$(dirname "$0")/../..}" && pwd)
WORKERS=${SHOTS_WORKERS:-4}
[ -f "$WT/ui/playwright.config.ts" ] || {
    echo "$WT is not a canopy checkout" >&2
    exit 2
}
command -v docker >/dev/null || {
    echo "screenshots need Docker, and docker is not on PATH" >&2
    exit 2
}

PW_VERSION=$(sed -nE 's/.*"@playwright\/test": "([0-9.]+)".*/\1/p' "$WT/ui/package.json")
IMAGE="mcr.microsoft.com/playwright:v${PW_VERSION}-noble"
# Read from the workflow, so the two pin one oxipng.
WORKFLOW="$WT/.github/workflows/screenshots.yml"
OXIPNG_VERSION=$(sed -nE 's/^ *OXIPNG_VERSION: *([0-9.]+) *$/\1/p' "$WORKFLOW")
OXIPNG_SHA256=$(sed -nE 's/^ *OXIPNG_SHA256: *([0-9a-f]{64}) *$/\1/p' "$WORKFLOW")
[ -n "$PW_VERSION" ] && [ -n "$OXIPNG_VERSION" ] && [ -n "$OXIPNG_SHA256" ] || {
    echo "cannot read the Playwright version from ui/package.json or oxipng's pin from $WORKFLOW" >&2
    exit 2
}
OUT=$(mktemp -d "${TMPDIR:-/tmp}/canopy-shots.XXXXXX")
trap 'rm -rf "$OUT"' EXIT

# The checkout's files, as git sees them, without what is ignored (node_modules, .venv, dist, test-results).
git -C "$WT" ls-files -z -co --exclude-standard | tar -C "$WT" --null -T - -cf "$OUT/src.tar"

echo "Image $IMAGE, mode $MODE, checkout $WT"
start=$(date +%s)
rc=0
# The container's script is single-quoted on purpose: its variables expand inside the container, not here.
# shellcheck disable=SC2016
docker run --rm --init --ipc=host \
    -e CI=1 -e UV_LOCKED=1 -e MODE="$MODE" -e WORKERS="$WORKERS" -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    -e OXIPNG_VERSION="$OXIPNG_VERSION" -e OXIPNG_SHA256="$OXIPNG_SHA256" \
    -e UV_CACHE_DIR=/cache/uv -e UV_PYTHON_INSTALL_DIR=/cache/python -e npm_config_cache=/cache/npm \
    -v canopy-shots-cache:/cache \
    -v "$OUT":/out \
    "$IMAGE" bash -euo pipefail -c '
        if ! [ -x /cache/bin/uv ]; then
            curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL=/cache/bin sh >/dev/null
        fi
        export PATH=/cache/bin:$PATH
        mkdir -p /work && tar -C /work -xf /out/src.tar && cd /work
        git init -q  # a repository with no tags: uv-dynamic-versioning falls back to 0.0.0
        uv sync --locked --python 3.12 --quiet
        npm --prefix ui ci --no-audit --no-fund --loglevel=error
        cd ui
        mapfile -t specs < <(grep -lE "toHaveScreenshot|screenshot(Main|Whole)\(" e2e/*.spec.ts)
        printf "Taking screenshots in %s\n" "${specs[@]}"
        rc=0
        if [ "$MODE" = check ]; then
            npm run test:e2e -- --workers="$WORKERS" "${specs[@]}" || rc=$?
        else
            # A commit to diff against, so only the images this run wrote are optimized and copied out.
            git add -A -- e2e && git -c user.name=x -c user.email=x commit -qm base
            npm run test:e2e -- --workers="$WORKERS" --update-snapshots="$MODE" "${specs[@]}" || rc=$?
            cd /work
            mapfile -t pngs < <(git ls-files --modified --others --exclude-standard -- "ui/e2e/*-snapshots/*.png")
            if [ "${#pngs[@]}" -gt 0 ]; then
                if ! [ -x "/cache/bin/oxipng-$OXIPNG_VERSION" ]; then
                    name="oxipng-${OXIPNG_VERSION}-x86_64-unknown-linux-musl"
                    curl -fsSL -o /tmp/oxipng.tar.gz \
                        "https://github.com/shssoichiro/oxipng/releases/download/v${OXIPNG_VERSION}/${name}.tar.gz"
                    echo "${OXIPNG_SHA256}  /tmp/oxipng.tar.gz" | sha256sum --check --strict --quiet
                    tar -xzf /tmp/oxipng.tar.gz -C /tmp && cp "/tmp/$name/oxipng" "/cache/bin/oxipng-$OXIPNG_VERSION"
                fi
                "/cache/bin/oxipng-$OXIPNG_VERSION" --quiet --opt 4 --strip safe "${pngs[@]}"
                mkdir -p /out/pngs && cp --parents "${pngs[@]}" /out/pngs/
            fi
            cd ui
        fi
        if [ "$rc" -ne 0 ]; then
            mkdir -p /out/report && cp -r test-results playwright-report /out/report/ 2>/dev/null || true
        fi
        chown -R "$HOST_UID:$HOST_GID" /out
        exit "$rc"
    ' || rc=$?
echo "Container finished in $(($(date +%s) - start))s with exit $rc"

if [ -d "$OUT/report" ]; then
    rm -rf "$WT/ui/test-results" "$WT/ui/playwright-report"
    cp -r "$OUT/report/." "$WT/ui/"
    echo "Failures: see $WT/ui/test-results and $WT/ui/playwright-report"
fi
if [ -d "$OUT/pngs" ]; then
    cp -r "$OUT/pngs/." "$WT/"
    echo "Images written:"
    (cd "$OUT/pngs" && find . -name '*.png' | sed 's|^\./|  |' | sort)
elif [ "$MODE" != check ]; then
    echo "No image changed."
fi
exit "$rc"
