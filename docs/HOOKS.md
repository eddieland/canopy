# Checking a worker's push with git hooks

How to have canopy's workers run your repository's fast checks before they push, so a lint error or a broken unit test
fails in the worker's own shell, where it fixes it, instead of in CI, where it costs a run of every job and often another
worker run to fix. The examples use [prek](https://github.com/j178/prek), which reads pre-commit's
`.pre-commit-config.yaml`; plain git hooks and pre-commit itself work the same way. Everything here is your own setup,
in your primary clones and your repository: canopy needs none of it, and none of this is required to run it.
For why canopy's own git runs no hooks, see DESIGN §8 and §24.

## Which git runs your hooks

A worker commits and pushes with its own git, in its slot, and that git runs the repository's hooks as yours would.
Every git canopy itself runs has hooks turned off (D107). So a hook checks only what a worker commits and pushes:

- **A worker's commits and pushes:** checked.
- **canopy's fallback push:** not checked. When a worker ends with commits it did not push, canopy pushes them once,
  without hooks, so that its work is not lost (DESIGN §8, `_run` step 5). CI is still the check there.
- **Reviews and plans:** nothing to check. Neither commits.
- **A joint run:** each repository's hooks apply in its own slot.

A hook is not a guard: a worker can still commit with `--no-verify`, and canopy does not stop it (step 5 below).

A worker's git finds your hooks through canopy's own: its environment points `core.hooksPath` at hooks canopy ships,
which add canopy's commit trailers and prefix (TRUST_MODEL T5) and then run the hook of the same name from wherever
git would have looked without them, your primary clone's or a `core.hooksPath` your config sets. Nothing here changes
for that. In a repository with a checklist (DESIGN §42), canopy's `pre-push` holds a worker's first push to ask it the
list, before your `pre-push` runs; the push after it goes through canopy's and runs yours, with the refs git handed.
It needs git 2.31 or later, which reads `GIT_CONFIG_COUNT`; an older git runs your hooks alone, each tick raises
`git_too_old` on the attention list, and each run's note names the commits that lack canopy's marks.

## 1. Install prek where workers can run it

Install it as a uv tool, so it has a fixed path:

```sh
uv tool install prek
```

The hook git runs is a short script that names the prek that installed it, and falls back to the `prek` on `PATH`. A
path under uv's tool directory stays put; one from `uvx prek` points into uv's cache and stops working when the cache
is pruned. A sandboxed worker can read `~/.local/bin` and `~/.local/share/uv` under the shipped template, so a uv tool
runs there too.

## 2. Install the hooks once, in each primary clone

Every slot is a git worktree of the repository's primary clone, `repos/<name>/` in the workspace, and shares its git
directory, hooks included. One install there covers every slot the pool has now and every one it makes later:

```sh
cd repos/api
prek install
```

`prek install` installs the hook types `default_install_hook_types` names in the config (step 3), or `pre-commit` alone
without it.

- **Install only `pre-commit` and `pre-push`.** treehouse's `return` runs plain git in the slot, on your machine and
  with hooks on (DESIGN §24, Git state). A hook git runs on a checkout or a merge, such as `post-checkout` or
  `post-merge`, could run then, outside any sandbox, with the hook config the worker left in the slot. Returning a slot
  neither commits nor pushes, so these two never run there.
- **A hook already there is kept.** prek moves it to `pre-push.legacy` and runs it too. That matters for Git LFS:
  a repository whose push needs LFS's `pre-push` depends on the worker's push running it (DESIGN §8).
- **A sandboxed worker cannot change the installed hooks:** it cannot write the shared git directory. It can edit
  `.pre-commit-config.yaml` in its slot, and the edit shows in its PR's diff.
- **A new primary clone needs its own install.** A repository `canopy workspace sync` clones later has no hooks until
  you run `prek install` in it.

## 3. Write hooks that run your repository's own tools

Use local hooks that call the tools your repository already pins, not hooks prek downloads. A sandboxed worker reaches
only the hosts in its template and writes only its own cache, so a hook prek would have to fetch and build, usually from
a package registry the template does not list, fails there. A local hook runs what `setup_cmd` already installed in the
slot, at the version your lockfile names.

```yaml
# .pre-commit-config.yaml, committed in the repository
default_install_hook_types: [pre-commit, pre-push]
repos:
  - repo: local
    hooks:
      # Seconds: on every commit, on the files it changes.
      - id: format
        name: format
        entry: uv run --no-sync ruff format
        language: system
        types: [python]
        stages: [pre-commit]
      - id: lint
        name: lint
        entry: uv run --no-sync ruff check --fix
        language: system
        types: [python]
        stages: [pre-commit]
      # Slower: once per push, and only when the commits pushed change Python.
      - id: typecheck
        name: type check
        entry: uv run --no-sync pyright
        language: system
        types: [python]
        pass_filenames: false
        stages: [pre-push]
      - id: unit-tests
        name: fast tests
        entry: uv run --no-sync pytest -q -x -m "not slow"
        language: system
        types: [python]
        pass_filenames: false
        stages: [pre-push]
```

- **Name each hook's stage.** A hook with no `stages` runs on every hook type installed, so a commit hook would run
  again on every push.
- **Stay off the network.** `uv run --no-sync`, `npm run` rather than `npx`, and the like run what is installed and
  fetch nothing. Install it in `setup_cmd` ([GETTING_STARTED.md](GETTING_STARTED.md), stage 2), such as
  `uv sync --frozen` or `npm ci`, with your registries in the `setup` template if you sandbox it.
- **A pre-push hook sees the push's commits.** prek runs it on the files the commits being pushed change, so a push that
  changes only docs skips the Python hooks above.
- **A hook that needs an environment of its own.** prek honors `XDG_CACHE_HOME`, which the sandbox points at the
  role's own cache, so a hook that downloads its tool builds it there; it still needs its registry in the worker's
  template.

## 4. Fit them in the worker's time

Hooks run inside the worker's time limit, `worker_timeout_minutes` (45 by default), on every commit and every push, and
a worker that fixes something after a push commits and pushes again. Size each stage for that:

| Stage | What fits | Budget |
| --- | --- | --- |
| `pre-commit` | formatters, linters | a few seconds in all |
| `pre-push` | type checks, a fast subset of the tests, scoped with `types` or `files` | under a minute |
| CI only | end-to-end and browser tests, install checks, anything that needs a service | as long as it takes |

Pick the hooks from what your CI actually fails on. Look at a few weeks of failed runs first: if your workers already
run your linters, a lint hook saves nothing, and the failures are in the tests a hook can only partly cover. Keep CI as
the check that decides; a hook only moves its cheapest failures earlier.

## 5. Tell workers to fix what a hook reports

A worker reads a hook's failure in its tool output and usually fixes it at once. To keep it from going around one, say
so where it reads your conventions: the worker prompt tells it to follow the repository's `AGENTS.md`. A line such as
this one there covers your own agents too:

```text
Commit and push with the hooks on. When a hook fails, fix what it reports; never use --no-verify.
```

## 6. Check that it works

1. In a primary clone, `ls .git/hooks` lists `pre-commit` and `pre-push`, and a `.legacy` copy of any hook prek moved
   aside.
2. In a slot under `.treehouse/`, `git rev-parse --git-common-dir` names the primary clone's git directory, so the
   slot runs the hooks you installed there.
3. Dispatch a ticket, then read its run log, `.canopy/runs/<id>.log`: the worker's commit and push output there holds
   prek's line for each hook that ran, `Passed`, `Failed`, or `Skipped`.
4. If you sandbox workers, a hook that fails with a refused host or a write denied under `$HOME` is fetching or caching
   outside what the template allows: make it a local hook (step 3), or add what it needs to the `worker` template.

## Troubleshooting

- **No hook runs in a slot.** The primary clone has none installed (step 2), or a `core.hooksPath` in your git config
  sends git elsewhere for them. With it set, `prek install` installs into that directory instead, which every
  repository using that config then shares; unset it, or set it in the primary clone's own config only.
- **`prek: not found`.** The hook falls back to `PATH` when the prek that installed it is gone. Install prek as a uv
  tool (step 1) and run `prek install` again.
- **Every run is slower than before.** A `pre-push` hook is running the whole test suite. Scope it with `types` or
  `files`, or leave those tests to CI.
- **A worker pushed without checks.** Its run ended with commits it never pushed, and canopy pushed them without hooks
  (the first section), or it used `--no-verify` (step 5). The run's report and log say which.
