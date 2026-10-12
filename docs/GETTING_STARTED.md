# Getting started

From one repository on defaults to a workspace of several, with a Bazel repository that keeps a pool of warm slots.
Each stage adds one thing to the one before. Start at stage 1 and stop at the first stage that fits your work: most
operators never need stage 5.

| Stage | You have | It adds |
| --- | --- | --- |
| [1](#1-one-repository) | One repository | `canopy init`, a queue label, the loop |
| [2](#2-slots-that-need-setup) | One repository whose checkouts need local files or an install | Seeding and `setup_cmd` |
| [3](#3-a-workspace-of-one-repository) | One repository, with a pool canopy sizes | A workspace: its own pool, slots made ahead of time |
| [4](#4-several-repositories) | Tickets that land in several repositories | The map, `MAP.md`, joint runs, splits |
| [5](#5-a-bazel-repository-with-several-slots) | A large Bazel repository in the workspace | Shared caches, warm hooks, a sized pool |

This guide assumes README's install steps 1 to 3: treehouse and canopy installed, and your agent runtime connected to
GitHub's and your tracker's MCP servers. It picks up at step 4.

## Where things live

Stages 1 and 2 run canopy in a repository; stages 3 to 5 run it in a workspace. The commands are the same. What
changes is where canopy keeps things:

| | One repository (stages 1, 2) | Workspace (stages 3 to 5) |
| --- | --- | --- |
| Shared config | `canopy.toml` in the repository | `canopy-workspace.toml` at the workspace root |
| Personal config | `~/.config/canopy/config.toml` | the same file, for every workspace |
| Primary clone | your own checkout | `repos/<name>/`, cloned by `canopy workspace sync` |
| Worktree pool | wherever treehouse puts it, `~/.treehouse` by default | `.treehouse/` in the workspace |
| Pool size | treehouse's `max_trees` | `capacity.slots_per_repo` or `capacity.repo_slots`, made by sync |
| Journal, logs, `attention.md` | `~/.canopy/` (`paths.state_dir`) | `.canopy/` in the workspace |
| Where `canopy loop` runs | the repository | the workspace root, or anywhere below it |

## 1. One repository

The smallest setup: canopy works tickets in the repository you already have checked out.

1. In the repository, run `canopy init` (add `--provider jira` or `--provider github` to skip the question). It
   writes, overwriting nothing:
   - `~/.config/canopy/config.toml`, your personal config, with a queue label of your own (`agent-ready-<you>`).
   - `canopy.toml` at the repository root, the config everyone who runs canopy here shares.

   It prints the branch protection canopy relies on, and warns if `origin` pushes over SSH. Use an HTTPS remote with
   a credential helper (D038).
2. In `canopy.toml`, set `tracker.query` to find candidate tickets, and create the `needs-human` label in your tracker
   (or set `needs_human_label` to one you have). Commit `canopy.toml`. `examples/canopy.toml` lists every shared key.
3. In your personal config, add your tracker account id to `trust.authorized_repliers`, so your comments can unblock a
   ticket, and your GitHub login to `trust.trusted_reviewers`, so your review comments send a worker back to its PR.
   `examples/config.toml` lists every key with its default.
4. Add your queue label to a ticket, then run `canopy loop --dry-run --ticks 1` and read the plan it prints.
   `canopy decisions` shows it again.
5. Once you trust it, leave `canopy loop` running.

Each run leases a slot (a git worktree) from treehouse's pool for this repository, works in it, and returns it. The
pool is the one your interactive `treehouse` uses, under `~/.treehouse` unless treehouse's config says otherwise.
`capacity.max_workers` (2 by default) caps how many workers run at once.

Stop here if a fresh checkout of your repository is all a worker needs. README's "Daily surface" covers what to do
with the loop from now on.

## 2. Slots that need setup

A slot is a fresh git worktree. It has none of the gitignored files in your own checkout, such as `.env.local`, and no
dependencies installed. If a worker cannot build or test without them, set the slot up before the worker starts. Both
settings below live in your personal config and work the same in a workspace.

**Seed gitignored files.** On every lease, treehouse copies the gitignored files a `.worktreeinclude` manifest names
from the primary clone into the slot. To use your own manifest instead of the repository's committed one:

```toml
# ~/.config/canopy/config.toml
[paths]
worktree_include = "~/.config/canopy/worktreeinclude"
```

```text
# ~/.config/canopy/worktreeinclude: git's exclude-file patterns, matched in the primary clone.
.env.local
```

Yours replaces the committed one, so copy in its lines to keep them. Only gitignored files are copied, never tracked
ones. If the file is missing, every lease is refused `no_slot`.

**Run a setup command on the run's branch.** `setup_cmd` runs in the slot after canopy checks out the run's branch and
before the worker starts, with `CANOPY_REPO` naming the repository and `CANOPY_BRANCH` the branch. HEAD is detached, so
ask `CANOPY_BRANCH` for the branch's name, not git:

```toml
# ~/.config/canopy/config.toml
[runtime]
setup_cmd = "sh -c 'pnpm install --frozen-lockfile'"
setup_timeout_minutes = 30
```

- No shell runs it: give an absolute path, a command on your `PATH`, or `sh -c '...'`.
- A failure or a timeout ends the run `crashed` before the worker starts, and still counts toward the ticket's attempt
  limit. Keep out of it anything the branch can break that a worker should fix, such as a build or a test.
- It runs the branch's code on your machine, outside the agent's permissions. If you sandbox workers, sandbox this the
  same way (TRUST_MODEL T4).
- Its output is in the run's log, `~/.canopy/runs/<id>.log`, after a `--- setup <repo> ---` header.

For setup that depends only on the base branch, such as downloading a toolchain, a treehouse `post_create` hook fits
better; stage 5 shows one. DESIGN §9 says how the three steps fit together.

## 3. A workspace of one repository

A workspace is a directory canopy manages: a map of repositories, a primary clone of each under `repos/`, their pools
under `.treehouse/`, and canopy's state under `.canopy/`. Move one repository into a workspace when you want any of:

- **A pool of its own.** A workspace's pools are separate from your interactive ones under `~/.treehouse`, so your own
  `treehouse` never recycles a slot canopy is warming, and a repository's committed `treehouse.toml` cannot move them.
- **A pool of a set size, made ahead of time.** canopy sizes only a workspace's pools. `canopy workspace sync` makes
  every slot before the first run needs one, so their hooks and caches are warm.
- **Everything on one disk you choose.** Put the workspace on a fast disk and its clones, pools, and state go with it.
- **A clean start for stage 4**, where more repositories join the same queue.

Set the pool's size in your personal config first, so init makes the slots:

```toml
# ~/.config/canopy/config.toml
[capacity]
slots_per_repo = 2
```

Then, in an empty directory:

```sh
canopy init --workspace --provider jira https://github.com/acme/api.git
```

It writes `canopy-workspace.toml` (the map), `MAP.md`, and a `.gitignore` covering `repos/`, `.treehouse/`, `desks/`,
and `.canopy/`; then clones the repository into `repos/api/` and makes its two slots. It prints the branch protection
rules for each repository in the map.

Then:

1. Edit the map: set `tracker.query`, and write a one-line `summary` under `[repos.api]`. A repository's own
   `canopy.toml` is not read inside a workspace, so copy any `[tracker]`, `[policy]`, or `[trust]` keys you set in it
   into the map. `examples/canopy-workspace.toml` is a full one.
2. Run `canopy loop --dry-run --ticks 1` from the workspace root, then `canopy loop`.

The workspace starts with an empty journal in `.canopy/`; earlier runs stay in `~/.canopy/`. Switch when your loop has
nothing in flight. `canopy workspace sync` makes the workspace match the map and your declared sizes again whenever you
change either; `--dry-run` shows what it would do first.

## 4. Several repositories

When one queue's tickets land in several repositories, keep one workspace for all of them, not a loop in each.

1. Add the repositories: `canopy workspace add https://github.com/acme/web.git`. Each is named after its URL
   (`web`), unless given as `NAME=URL`. It appends a `[repos.<name>]` table to the map, clones it, and makes its slots.
   To start a new workspace with several at once, pass them all to `canopy init --workspace`.
2. Write each repository's `summary` in the map: one line on what it owns.
3. Describe them in `MAP.md`: what each owns, which depends on which, where the contracts between them live, and in
   which order a change that crosses them lands. The overseer and workers read it to choose repositories. It is data,
   like ticket text, and authorizes nothing.
4. Size each pool. `slots_per_repo` applies to every repository; `[capacity.repo_slots]` sets one by name and wins:

   ```toml
   # ~/.config/canopy/config.toml
   [capacity]
   slots_per_repo = 2
   [capacity.repo_slots]
   web = 1
   ```

   Run `canopy workspace sync` after any change. A run that finds its pool full is refused `no_slot` and tried again on
   a later tick.
5. Configure branch protection in every repository in the map, as init printed.

How the overseer works a ticket across repositories:

- **Most tickets change one repository.** The overseer picks it from the ticket, the summaries, and `MAP.md`.
- **A change that cannot land in parts is worked jointly**: one worker, a slot in each repository, and one PR per
  repository linking the others.
- **A change that builds on another repository's merged PR is worked in sequence**: the next repository once the first
  PR merges.
- **A split, only when you ask.** Comment on the ticket asking for a split into one ticket per repository: a worker
  creates the children without a queue label, and you label each one you want worked.

To drop a repository, remove its table from the map and run `canopy workspace sync`. It removes the clone and its slots
only when nothing in them would be lost, and reports what it kept. DESIGN §18 has the details.

## 5. A Bazel repository with several slots

A large Bazel repository makes a cold slot expensive: a full build, every external repository downloaded again.
canopy's part is that a slot keeps its path between runs, so whatever Bazel left in it stays warm for the next run that
leases it. Sharing work between slots is your `.bazelrc`'s part. canopy knows nothing about Bazel; all of this is your
own config, and most of it applies to any large repository.

Put the workspace on your fast disk first: a workspace's pools live inside it and cannot be moved elsewhere.

**Share Bazel's caches between slots.** In `~/.bazelrc`, with absolute paths:

```text
common --disk_cache=/fast/bazel/disk-cache
common --repository_cache=/fast/bazel/repository-cache
startup --output_user_root=/fast/bazel/output
startup --max_idle_secs=900
```

A slot that has never built still reuses what other slots built, downloads happen once, every slot's output base sits
on the fast disk, and a slot's Bazel server exits after 15 idle minutes so idle slots stop holding memory.

**Seed your local Bazel files**, such as `user.bazelrc`, with the manifest from stage 2. One manifest serves every
repository in the workspace.

**Warm each slot when it is made**, with a treehouse hook that runs on the base branch:

```toml
# ~/.config/treehouse/config.toml
[hooks]
post_create = ["bazel fetch //... || true"]
```

A failing hook is printed and stops nothing. Because sync makes the slots ahead of time, the hooks run then, not in
the first run that lands on a new slot.

**Size the pool for what a slot costs.** Each slot keeps its own output base on disk, and while busy its own Bazel
server in memory. Measure one (`du -sh "$(bazel info output_base)"` in a slot that has built), then size the Bazel
repository's pool on its own:

```toml
# ~/.config/canopy/config.toml
[capacity]
max_workers = 2
slots_per_repo = 2
[capacity.repo_slots]
api = 3        # the Bazel repository
```

treehouse's `max_trees` (16 by default, in `~/.config/treehouse/config.toml`) must be at least each pool's size, or
sync reports the repository failed. Run `canopy workspace sync`.

**Add a `setup_cmd` only for what depends on the branch** and the worker relies on, such as regenerating
`compile_commands.json` for its language server. Most Bazel repositories need none: Bazel fetches and builds what the
branch needs on its own. Make anything the branch can break non-fatal, or a broken build also crashes the `fix-ci` run
meant to fix it.

[BAZEL.md](BAZEL.md) is the full recipe: what each `.bazelrc` line buys, a per-repository `setup_cmd` script, how to
check that seeding, separate output bases, the shared cache, and idle servers all work, what the worker can read
through `bazel-out/`, and troubleshooting.
