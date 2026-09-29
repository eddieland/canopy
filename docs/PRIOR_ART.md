# Prior art

A survey of open-source projects that overlap with canopy, and what their issue trackers show they learned the hard
way. Surveyed 2026-09-29. Why canopy is built anyway is D050.

The canopy statuses below are as of that date and are not kept current. Check the code before acting on one.

## Overlap

- **[OpenAI Symphony](https://github.com/openai/symphony)**: a spec plus an Elixir reference implementation
  (Apache-2.0, March 2026). A daemon polls the tracker, gives each issue a workspace, and runs a Codex session in it.
  Unlike canopy: Codex app-server only; a tracker adapter per provider (Linear); state in memory only; workspaces kept
  per issue; a repository-owned `WORKFLOW.md` sets the agent command, sandbox policy, and shell hooks. CI and review
  follow-up are left to the prompt, and the example workflow merges and moves tickets.
- **[agent-orchestrator](https://github.com/ComposioHQ/agent-orchestrator)**: a Go daemon with desktop and mobile apps
  (Apache-2.0). A worktree and agent per issue; CI failures and review comments are sent back to the agent. Unlike
  canopy: tracker intake is GitHub and GitLab only, and three Jira attempts were closed unmerged; agent sessions are
  long-lived and fed messages; it runs loopback and optional LAN listeners; "never merge" is a prompt line and branch
  protection, not code.
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent) Kanban**: a board in Hermes' own SQLite database. A
  cron dispatcher starts one agent process per task, in a git worktree for coding tasks. Unlike canopy: tasks live on
  Hermes' board, not the team's tracker, and there is no CI or review follow-up. A Symphony-style tracker loop is a
  proposal ([#404](https://github.com/NousResearch/hermes-agent/issues/404)).

## Lessons canopy's design already answers

- **In-memory claims let a restart run two workers on one issue** (Symphony
  [#97](https://github.com/openai/symphony/pull/97), [#54](https://github.com/openai/symphony/pull/54)). canopy: the
  journal (D004), the pid claim and dispatch lock (D029), treehouse leases (D002), no retries in the worker.
- **A retry budget that resets on a state change never escalates** (agent-orchestrator
  [#1531](https://github.com/ComposioHQ/agent-orchestrator/pull/1531)). canopy: attempts are derived from `runs` and
  never reset (D030); retrying needs an authorized reply (D028).
- **Pushing events into a long-lived orchestrator session duplicates and contaminates it.** agent-orchestrator added
  automatic re-engagement and removed it two days later
  ([#3394](https://github.com/ComposioHQ/agent-orchestrator/pull/3394)). canopy: a fresh overseer each tick with a
  state block (§6), a fresh worker per run from the pushed branch (§9).
- **Auto-answering an agent's input prompts fabricates answers** (Symphony
  [#10](https://github.com/openai/symphony/pull/10), reversed in [#112](https://github.com/openai/symphony/pull/112)).
  canopy: `ask` is auto-rejected (D021) and the run goes to attention.
- **Intake open to anyone who can file an issue** (agent-orchestrator
  [#2527](https://github.com/ComposioHQ/agent-orchestrator/pull/2527)). canopy: queue labels are user-only (§12, §17),
  and a label finds tickets, it does not authorize replies.
- **A reused worktree ran on the previous run's branch** (Hermes
  [#71978](https://github.com/NousResearch/hermes-agent/pull/71978),
  [#68201](https://github.com/NousResearch/hermes-agent/issues/68201)). canopy: every run fetches with `--prune` and
  checks out from `origin`, never from local HEAD (§8).
- **A failed automation step passed a gate silently** (agent-orchestrator
  [#5424](https://github.com/ComposioHQ/agent-orchestrator/issues/5424),
  [#2827](https://github.com/ComposioHQ/agent-orchestrator/issues/2827)). canopy: `review_failed` and
  `review_unposted` (§21); review comments are classified, never filtered by author.

## Gaps

### In code today

- **`_run` imports from the repository root.** `runs/dispatch.py` spawns `python -m canopy _run` with the repository
  root as cwd, so a top-level `types.py`, `logging/`, or `canopy/` there shadows canopy's imports. A branch a worker
  wrote, checked out in the main checkout, would run on the host outside any sandbox. Hermes hit this: a workspace
  `inspect.py` crashed every dispatch ([#126896](https://github.com/NousResearch/hermes-agent/pull/126896)); the fix is
  `python -P`.
- **An `implement` run that commits nothing is recorded `done`.** `_ensure_pushed` in `runs/worker.py` treats "no new
  commits" as pushed, and nothing checks HEAD, the result's branch, or a dirty tree. Hermes shipped fabricated
  completions until it checked git ([#108782](https://github.com/NousResearch/hermes-agent/issues/108782),
  [#105452](https://github.com/NousResearch/hermes-agent/issues/105452)). `resume` and `fix-ci` can rightly commit
  nothing.
- **Harness git in a slot runs the slot's hooks.** `_GIT_ENV` in `runs/worker.py` sets only `GIT_TERMINAL_PROMPT`;
  `checkout` and the fallback `push` run hooks and `core.fsmonitor` from a git directory a worker can write.
  HOST_ISOLATION §5.1 already proposes the `-c` flags as correct with or without a sandbox. Hermes kept finding call
  sites that missed its hardened git env ([#126017](https://github.com/NousResearch/hermes-agent/issues/126017)).
- **Agent-written text reaches the terminal with control bytes intact.** `cli/params.truncate` bounds length only;
  `canopy status` echoes attention details, which also go to `attention.md` and `notify.cmd`. Symphony strips ANSI and
  control bytes centrally ([#23](https://github.com/openai/symphony/pull/23)).
- **pid reuse, D029's named residual, has been observed elsewhere.** agent-orchestrator killed users' tmux sessions
  through stale pids and now checks process start times
  ([#3491](https://github.com/ComposioHQ/agent-orchestrator/pull/3491)). That is D029's revisit trigger.

### In prompts

- **Workers' own comments read back as feedback.** Everything runs as the operator (D010), who is usually an authorized
  replier. `worker-resume.md` has workers reply on the PR after the `review` cursor was set, and nothing in the phase
  table tells a worker's comment from the operator's, so a reply can look like new review feedback and spend a
  `resume` attempt. agent-orchestrator has the same loop open
  ([#5574](https://github.com/ComposioHQ/agent-orchestrator/issues/5574)). A fixed marker on worker comments that can
  only take authority away, like §21's reviewer marker, fails safe.
- **The tracker search is not paged.** The overseer "reads each result"; nothing says to page, so a labeled ticket past
  the first page (Jira and GitHub return 30 to 50) is never seen. Symphony truncated at 50
  ([#43](https://github.com/openai/symphony/pull/43)).
- **CI newness is keyed on the check run id.** A human re-run or a runner or billing failure makes a newer run and
  another `fix-ci`. agent-orchestrator woke an agent 8 times in 40 minutes from one billing refusal
  ([#5089](https://github.com/ComposioHQ/agent-orchestrator/pull/5089)). Keying on commit and check name, and raising
  attention for failures the branch did not cause, avoids that.
- **Merge conflicts have no phase** (§7). A conflicting PR may get no CI run and sit in `ci_running` or show a stale
  green. agent-orchestrator tracks mergeability and fixed two bugs in its conflict nudge
  ([#3766](https://github.com/ComposioHQ/agent-orchestrator/pull/3766)). Its "rebase" instruction does not fit canopy,
  whose workers never force-push; merging the base in does.

### Open design questions

- **Dependencies are installed before the branch is checked out.** treehouse `post_create` (§9) runs on the base
  branch, before `_run` checks out a stacked or continued branch, and a failing hook does not fail the lease. Hermes
  gates on a setup hook that fails closed ([#104226](https://github.com/NousResearch/hermes-agent/pull/104226)).
- **A run on a ticket closed or unlabeled mid-run keeps going** to `worker_timeout_minutes`, and still pushes. Symphony
  stops such runs (SPEC §8.5, [#88](https://github.com/openai/symphony/pull/88)). A worker prompt that re-reads the
  ticket first is the cheap half ([#15](https://github.com/openai/symphony/pull/15)).
- **An outage spends every ticket's attempts.** Crashes during a provider or treehouse outage count toward D030 limits,
  one ticket at a time. Hermes logged 3,452 rate-limited runs in a week
  ([#127495](https://github.com/NousResearch/hermes-agent/issues/127495)); agent-orchestrator treats many sessions
  dying at once as one outage (#3491 above).
- **Returning a slot discards uncommitted work unrecorded.** `return --force` is deliberate (D002, D005), but nothing
  records what was thrown away. Hermes refuses a dirty reclaim without `--force`
  ([#101788](https://github.com/NousResearch/hermes-agent/issues/101788)); recording paths, never contents, is enough.
- **Child processes inherit the operator's whole environment**, tokens included (`infra/procs._child_env`), and
  HOST_ISOLATION allowlists files but not variables. Symphony found tracker tokens in env aliases crossing its boundary
  ([#119](https://github.com/openai/symphony/pull/119)).
- **Spend per run.** A looping agent-orchestrator worker used 45M tokens in 45 minutes, canopy's default worker timeout
  ([#6032](https://github.com/ComposioHQ/agent-orchestrator/issues/6032)). Symphony counts absolute totals, not
  deltas, and has an open PR to persist them ([#60](https://github.com/openai/symphony/pull/60)). Input for M13.
- **A runtime minor release can hang headless agents on a permission prompt**
  ([agent-orchestrator #4810](https://github.com/ComposioHQ/agent-orchestrator/issues/4810)). D021 revisits only on an
  OpenCode major version.

## What not to copy

- **A repository file that sets commands, sandbox policy, or hooks.** Symphony's `WORKFLOW.md` does; TRUST_MODEL T7
  and §6 keep all of that user-only.
- **Agents that merge, land, or move tickets.** Symphony's example workflow has a `land` skill; TRUST_MODEL §6 forbids
  it, and agent-orchestrator shows that a prompt line is not a guard.
- **Long-lived sessions fed events, a daemon, or a listener** (D042, TRUST_MODEL §4). agent-orchestrator's own
  reverted re-engagement is the evidence.
- **Tracker adapters.** agent-orchestrator wrote Jira three times and shipped none; canopy's tracker is MCP plus a
  contract (D003, D014).
- **Pasting issue bodies or CI logs into prompts** (D031, T1).
