# canopy roadmap

Milestones are sequential. Each has acceptance criteria that must be met before
the next begins. Acceptance criteria that involve running against real systems
are the operator's job; the agent building the repo stops and asks.

Each milestone ends with a `Status:` line. It is the only place milestone
progress is tracked. Keep it current in the same PR that changes it:

- `Status: not started.` or `Status: in progress.` while work is open.
- When the acceptance criteria are met, replace it with:

  ```
  Status: done YYYY-MM-DD.
  Learned: what surprised us or turned out different from the plan.
  Next: how that changes later milestones, docs, or open questions.
  ```

  Keep `Learned` and `Next` to a few bullets or sentences each. Anything that
  deserves a lasting rationale goes in `DECISIONS.md`. The entry here just
  points to it. Edit a later milestone's bullets directly when `Next`
  calls for it.

## M0. Skeleton

- Repository layout per `DESIGN.md` §5. `pyproject.toml`, `Makefile`,
  `uv.lock`.
- `canopy --version`, `canopy --help`.
- `make check`: ruff format check, ruff lint, pyrefly strict (D017), pytest. All green on an
  empty test.
- GitHub Actions running `make check` on push and PR.
- `tests/fakes/treehouse` and `tests/fakes/agent` executables with fixtures
  that put them on `PATH`.
- `procs.py` with the single subprocess boundary and a fake-able runner.

Accept: CI green; fakes exercised by at least one test each.

Status: done 2026-09-23.
Learned:
- `tests/canopy/__init__.py` made pytest import the test directory as a package named `canopy`, shadowing
  `src/canopy`. Test directories now have no `__init__.py`. (Superseded by D019: every test directory, the root
  included, has one.)
- treehouse's real shapes, read from its source (commit `1185dc6`): `status --json` is an array whose `name` is a
  string and whose `leased_at` is `null` when unleased; `get --lease --json` also returns `base_branch`; `return` exits
  0 returned, 1 failed or lease mismatch, 3 dirty and not forced. The fake follows these.
- The subprocess boundary is enforced by ruff's banned-api rule rather than by review (D015). A timeout kills the
  child's whole process group, since agent runtimes spawn children of their own.
Next:
- M1's `treehouse.py` should treat `return` exit 3 as distinct from 1: retrying a dirty return loops. canopy always
  passes `--force`, so 3 should not happen; if it does, it is an attention item, not a retry.
- M1 code that runs processes takes a `procs.Runner`. The PATH fakes cover most tests; add an in-process fake runner
  only when a test needs one.

## M1. Read-only tick

- `config.py` (layered repository and user files with per-key scope checks, DESIGN §12), `db.py` with migrations,
  `lock.py`, `treehouse.py`.
- `canopy init` writes the user config if missing (default label `agent-ready-<$USER>`), writes `canopy.toml` if the
  repository has none (asking for the tracker provider), installs agent definitions to `.opencode/agent/` and the
  `tracker-<provider>` skill if one ships, prints required branch protection rules. It never overwrites either config.
- Ticket key validation (`[A-Za-z0-9][A-Za-z0-9_-]*`) in every CLI subcommand that takes a key.
- `canopy tick --dry-run`: lock, migrate, reconcile (no-op on fresh state),
  render the overseer prompt with state block, run `overseer_cmd`, record
  `ticks` and `decisions`. `canopy dispatch` refuses in dry-run.
- `canopy decide` and `canopy attention` CLI subcommands writing to the journal.
- `canopy status` prints the attention list and running workers.
- Canary test resolving DESIGN §16 question 1: an agent definition with a
  denied tool, run under `opencode run`, must be unable to use it. Record the
  outcome in `DECISIONS.md`.

Accept: e2e test against fakes passes. Operator runs `canopy tick --dry-run`
on a real repository daily for several days and judges the recorded plans
sensible. No dispatches happen.

Status: in progress.

## M2. Dispatch implement

- `dispatch.py` guards, lease, detached `_run`.
- `_run`: branch setup, worker execution with timeout, result parsing, push
  verification, unconditional lease return via trap, `runs` update.
- Reconcile: dead pid detection, stale lease return.
- `prompts/worker-implement.md` with the result contract.
- Attention items for `crashed`, `unpushed`, `unknown_result`.
- `.agents/agents/canopy-worker.md` is still a copy of the overseer definition. Write the worker's own permissions
  (edit and bash inside the worktree), with the ordering rules in D021. Needs human approval like any `agents/` change.
- Lift the M1 stopgaps: `canopy tick` without `--dry-run`, and `canopy dispatch` outside a dry run (D020).

Accept: one real ticket goes from label to open PR unattended, with the slot
returned and a correct `runs` row. A killed worker is detected on the next tick
and its slot returned.

Status: not started.

## M3. Fix-CI and resume

- Phases `ci_red`, `changes_requested`, `needs_human`, `human_replied` in the
  overseer prompt.
- `prompts/worker-fix-ci.md`, `prompts/worker-resume.md`.
- Attempt counters, cooldowns, `attempt_limit` attention.
- Cursors updated per ticket so ticks are incremental.
- `attention.py` render, diff, `notify.cmd`.

Accept: a PR with a failing check gets exactly one fix attempt per cooldown
window and stops at the limit. A blocked worker's question appears on the
ticket; an authorized reply resumes it; an unauthorized reply does not.

Status: not started.

## M4. Dependencies and stacking

- Blocker detection via the tracker's blocker relations in the overseer prompt (DESIGN §17; Jira links and GitHub
  dependencies via their skills).
- `dispatch --base` and PR base handling in `_run` and the worker prompt.

Accept: two linked tickets are worked in order; the second's PR targets the
first's branch when the first is open and green.

Status: not started.

## M5. Shareable

- `skill/` OpenCode skill for the canopy CLI.
- `uv tool install` path verified from a clean machine.
- README install steps performed by a second person without help. Their
  friction becomes issues.
- License decided and added.

Accept: a coworker runs it against their own ticket.

Status: not started.

## Deferred, with the trigger that would unblock each

- Sandboxed workers: when a T4 or T6 incident happens, or before any second
  team adopts it.
- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it.
- Second runtime (Copilot CLI, Claude Code): when a coworker asks; expected to
  be a config change plus prompt tweaks, not code.
- Web UI: not planned.
