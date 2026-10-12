# Working in a Bazel repository

How to set canopy up for a large Bazel monorepo, so each run starts in a slot that builds fast and has what the worker
needs. Everything here is your own config, outside the repository: canopy knows nothing about Bazel, and none of this
is required to run it. For why it works this way, see DESIGN §9 and §18. To build up to a workspace from one
repository first, see [GETTING_STARTED.md](GETTING_STARTED.md).

## What happens to a slot during a run

Each run leases a slot (a git worktree) from treehouse, works in it, and returns it. The slot keeps its path, so the
next run that leases it finds whatever the last one left that git ignores, Bazel's output base included. In order:

1. **Lease.** treehouse hands canopy an idle slot, reset to the base branch, or makes a new one.
2. **Seed.** treehouse copies gitignored files you name from your primary clone into the slot (setup step 2 below).
3. **`post_create` hooks.** treehouse runs your hooks in the slot, on the base branch (setup step 3).
4. **Checkout.** canopy fetches and checks out the run's branch.
5. **`setup_cmd`.** canopy runs your setup command in the slot, at the run's branch with a detached HEAD
   (`CANOPY_BRANCH` names it). If it fails, the run ends there (setup step 4).
6. **Worker.** The agent works and pushes.
7. **Return.** canopy returns the slot. The next lease's reset discards uncommitted files; ignored ones such as
   `bazel-out/` stay, and seeded ones are copied in fresh.

Seeding, the hooks, and `setup_cmd` are where you set a slot up. Bazel's own caches (setup step 1) make the slots
share work.

## Before you start: a fast disk

Put the workspace on the fast disk (`canopy init` in a directory there). A workspace's slots live inside
it, under `.treehouse/`, and canopy has no setting to move them, because git keeps each slot's index and objects in
the primary clone under `repos/` anyway. Bazel's outputs and caches go wherever your `.bazelrc` says, so they can sit
on the fast disk even when the workspace cannot.

## 1. Share Bazel's caches between slots

Add this to `~/.bazelrc`, which every Bazel command you run reads, in every slot. Use absolute paths.

```text
# Bazel 7 or later, where `common` skips options a command does not take.
# Action outputs and downloaded external repositories, shared by every slot.
common --disk_cache=/fast/bazel/disk-cache
common --repository_cache=/fast/bazel/repository-cache
# Every slot's output base, under one root on the fast disk.
startup --output_user_root=/fast/bazel/output
# A slot's server exits after 15 idle minutes, not Bazel's default of 3 hours.
startup --max_idle_secs=900
```

What each line buys:

- `--disk_cache`: a build in one slot reuses actions another slot already ran. A run that lands on a slot it has never
  used still starts warm. The cache grows without bound: prune it now and then, or on Bazel 7.4 or later cap it with
  `common --experimental_disk_cache_gc_max_size=200G`. If your repository has a remote cache, that does this job for
  every machine and you can leave the disk cache out.
- `--repository_cache`: a module or archive is downloaded once, not once per slot.
- `--output_user_root`: Bazel keys each output base on the workspace's path, so every slot has its own, and it stays
  warm across runs because the slot keeps its path. This puts all of them on the fast disk. Changing it later makes
  every slot cold once.
- `--max_idle_secs`: each slot runs its own Bazel server, and canopy does not stop it when it returns the slot (D106).
  This ends a server once nobody has used its slot for that long, so idle slots stop holding memory. A run that lands
  on the slot within the window still finds the server warm.

If your repository's `.bazelrc` already does `try-import %workspace%/user.bazelrc`, you can put these lines there
instead, and seed that file into every slot (setup step 2).

## 2. Seed your local files into each slot

Gitignored files in your primary clone, such as `user.bazelrc`, `.env.local`, or credentials a build reads, are not in
a new slot. treehouse copies the ones a `.worktreeinclude` manifest names. To use your own manifest, write one and
point canopy at it in `~/.config/canopy/config.toml`:

```toml
[paths]
worktree_include = "~/.config/canopy/worktreeinclude"
```

```text
# ~/.config/canopy/worktreeinclude: git's exclude-file patterns, matched in each primary clone.
user.bazelrc
.env.local
```

- Yours **replaces** the repository's committed `.worktreeinclude`; treehouse reads one or the other. Copy the
  committed lines into yours to keep them.
- Only gitignored files are copied, never tracked ones. `git check-ignore -v user.bazelrc` in the primary clone says
  whether a file qualifies.
- treehouse seeds on every lease, a reused slot's too, so an edit to the file in the primary clone reaches the next
  run.
- In a workspace, one manifest serves every repository. A pattern that matches nothing in one copies nothing there.
- If the manifest file is missing, every dispatch is refused with `no_slot` and treehouse's `failed to read include
  file` message.

## 3. Warm slots with `post_create` hooks

treehouse runs the hooks in `~/.config/treehouse/config.toml` in each slot after seeding, when it makes or reuses the
slot. They run on the **base branch**, through `/bin/sh`, and a failing hook is printed but does not stop anything.
They suit work that depends only on the base, such as downloading the toolchain and external repositories:

```toml
# ~/.config/treehouse/config.toml
[hooks]
post_create = ["bazel fetch //... || true"]
```

Hooks in a repository's committed `treehouse.toml` are ignored; only yours run.

In a workspace, set `capacity.slots_per_repo` and run `canopy workspace sync`: it makes every slot ahead of time, so
the hooks run then and not in the first run that lands on a new slot.

## 4. Set up the run's branch with `setup_cmd`

Most Bazel repositories need no `setup_cmd`: Bazel fetches and builds what the branch needs on its own. Use it for
setup that depends on the branch, that the worker relies on but will not do itself. Examples: regenerating
`compile_commands.json` so the agent's language server matches the branch, or installing JavaScript dependencies a
tool outside Bazel needs.

```toml
# ~/.config/canopy/config.toml
[runtime]
setup_cmd = "/home/you/.config/canopy/setup.sh"
setup_timeout_minutes = 30
```

```sh
#!/bin/sh
# Run by canopy in each slot, at the run's branch (detached), before the worker. CANOPY_REPO names the repository,
# CANOPY_BRANCH the branch.
set -eu
case "$CANOPY_REPO" in
api)
    # The worker's language server reads this; a stale one misleads it.
    bazel run @hedron_compile_commands//:refresh_all || echo "compile_commands.json not refreshed" >&2
    ;;
web)
    pnpm install --frozen-lockfile
    ;;
esac
```

- canopy runs it with no shell, so give an absolute path (no `~`) or a command on your `PATH`. Write
  `sh -c '...'` for a one-liner.
- It runs in each slot of a run: once for a run in one repository, once per repository in a joint run. Splits and
  reviews run none.
- Its output goes to the run's log, `.canopy/runs/<id>.log` in the workspace, after a
  `--- setup <repo> ---` header.
- **A failure stops the run.** An exit other than 0, or running past `setup_timeout_minutes`, ends the run `crashed`
  before the worker starts, and the ticket goes on the attention list. The run still counts toward the ticket's
  attempt limit.
- So keep out of it anything the branch can break that a worker should fix: a build, a test, or fetching a changed
  `MODULE.bazel`. If setup fails on those, it also fails the `fix-ci` run meant to fix them. Make such steps
  non-fatal, as the `api` case above does.
- It runs the branch's code (install scripts, generators) on your machine, outside the agent's permissions, just
  before the worker's own shell would. If you run workers in a sandbox, run this in the same one (TRUST_MODEL T4).

## 5. Size the pool

Every slot keeps its own output base on disk and, while it is busy or within `--max_idle_secs`, its own Bazel server
in memory. Measure one before you pick a size:

```sh
du -sh "$(bazel info output_base)"    # disk, in a slot that has built
```

The server's memory is shown by `ps` once a build has run. Then set the pool's size in `~/.config/canopy/config.toml`
and run `canopy workspace sync`:

```toml
[capacity]
max_workers = 2
[capacity.repo_slots]
api = 3        # the Bazel repository: slots cost disk and memory
```

A run that finds every slot busy is refused `no_slot` and tried again on a later tick, so a pool smaller than
`max_workers` only queues work; reviews take slots too. treehouse's own `max_trees` (16 by default) must be at least
the size. Set it in `~/.config/treehouse/config.toml`, unless the repository commits a `treehouse.toml`, whose
`max_trees` wins.

## Check that it works

In a workspace, after `canopy workspace sync`:

- **Seeding**: `ls -la .treehouse/*/1/api/user.bazelrc` shows the seeded file in a slot.
- **Separate output bases**: `bazel info output_base` in two slots prints two directories under
  `/fast/bazel/output`.
- **Shared disk cache**: build a target in one slot, then the same target in another. Bazel's summary line in the
  second reports `disk cache hit` for most actions.
- **Setup**: after a run, its log has `--- setup api exit 0 ---`. To see a failure handled, set `setup_cmd = "false"`
  and dispatch: the run ends `crashed` with the note `setup exited 1; see the run log`, and no worker runs.
- **Idle servers**: `pgrep -fa 'output_base=/fast/bazel/output'` lists running servers, one per busy slot. Fifteen
  minutes after the last run on a slot, its server is gone.

## What the worker can read

`bazel-out/`, `bazel-bin/`, and `bazel-testlogs/` in a slot are links into its output base, outside the worktree. The
worker's file tools read through them, so it can open its own test logs. The same files by their real paths under
`/fast/bazel/output` should be refused. That rule is defense in depth, not a boundary: the worker's shell can read
either. An opt-in canary checks it against your OpenCode; run it once from a canopy checkout:

```sh
CANOPY_OPENCODE_CANARY=1 uv run pytest tests/canopy/test_opencode_canary.py -k bazel
```

## Troubleshooting

- **Every run is `crashed` with a setup note**: your `setup_cmd` is failing. Read the run log and fix the command.
  A crashed ticket waits on the attention list; `canopy reply KEY 'setup is fixed, try again'` or the web UI sends it
  back to the overseer.
- **Dispatches refused with `no_slot` and `failed to read include file`**: `paths.worktree_include` names a file that
  is not there.
- **The first run on a new slot is slow**: the slot's output base is cold. In a workspace, `canopy workspace sync` makes
  slots ahead of time; the disk cache keeps the first build short either way.
- **Memory fills up**: lower `--max_idle_secs`, or shrink the pool.
- **The disk fills up**: the disk cache has grown. Prune it, or cap it as in setup step 1.
