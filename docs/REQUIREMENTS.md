# canopy requirements

The primary operator's requirements, written down 2026-10-06, and where canopy stands on each. `DESIGN.md` is how
canopy meets them; this file is what it must meet. Where the two disagree, the conflict is listed under
[Conflicts](#conflicts) until a `DECISIONS.md` entry settles it, and the design doc stays normative until then
(AGENTS.md).

A bare § is a section of `DESIGN.md`. Status words:

- **Built**: in code with fakes-based tests; live acceptance may still be the operator's to run (ROADMAP).
- **Planned**: designed, in a ROADMAP milestone, not built.
- **Partial**: some of it is built or planned; the rest is listed as a gap.
- **Gap**: nothing designed yet; a ROADMAP sketch names where it goes.
- **Conflict**: the requirement and a normative doc disagree; see [Conflicts](#conflicts).

## Hard constraints

### H1. Runs entirely on the operator's machine; no hosted relay, no mobile app, nothing exposed off-box

Built. Nothing listens on the network (TRUST_MODEL §4); the loop is a foreground command (§6, D042); state, logs, and
worktrees are local and operator-only. The services canopy's agents reach (the tracker's MCP server, such as
Atlassian's remote MCP, GitHub, and the model provider) are ones the operator already uses, reached by the agent runtime
with the operator's own credentials (D003); canopy adds no service of its own in between. The planned Slack sink (§20)
posts outbound only and listens for nothing.

The local web UI nice-to-have conflicts with this posture as TRUST_MODEL §4 states it: C2.

### H2. Extended only through native plugins or config; no custom layer to maintain

Partial. The runtime is a command template (D009), trackers are MCP plus a skill (D014), and customization is skills
where OpenCode already looks (§13). Worktree setup is treehouse's own hooks and `.worktreeinclude` (R10). Two places
still ask the operator to keep code or text of their own in step with canopy:

- A notification destination other than the shipped ones is "a small program of the operator's" (§20). The desktop
  destination the operator wants first (N2) must therefore ship with canopy.
- Prompt overrides (§12) are copies the operator maintains, and an override must keep what canopy's guards rely on
  (D051). Prefer a skill; treat an override as a last resort.

## Must have

### R1. Ticket intake: label a Jira ticket and it is picked up when there is capacity

Built (M1 to M3), live acceptance pending. The queue label is the operator's own (`tracker.labels`, §12) and is the
only authorization to start work (TRUST_MODEL T1). Jira works through any Jira MCP server the runtime has, Atlassian's
remote MCP included, with the shipped `tracker-jira` skill (§17). Capacity is `capacity.max_workers`, enforced in code
(§8).

Known gap affecting intake at volume: the overseer prompt does not page the tracker search, so a labeled ticket past
the first page waits until earlier ones leave the queue (PRIOR_ART "In prompts"). Fixing it is an overseer prompt
change, which needs human approval.

### R2. Worktree pool: create, track, and clean up worktrees per ticket, with a capacity limit

Built. treehouse is the pool (D002): canopy leases a slot per run, records it in `runs`, returns it on every exit path,
and returns stale leases in reconcile (§6, §8). The capacity limit is `capacity.max_workers`; treehouse's `max_trees`
bounds the pool.

The shape differs from "a worktree per ticket": a ticket holds a slot only while a run is working on it, and its pushed
branch is its checkpoint between runs (§9). That is what makes R3 possible.

### R3. Release capacity when blocked on CI, review, or a human

Built. Aggressive release (§9, D005): waiting holds no slot and no capacity.

### R4. Feedback routing: CI failures and review comments go back to the agent that owns the PR

Built in code (M3), live acceptance pending. `fix-ci` and `resume` runs continue the ticket's branch and PR, with
cursors so each failure and comment is handled once (§7, §8), attempt limits and a cooldown in code (D030).

Partial on "the agent that owns the PR": each run is a fresh worker on the pushed branch with no transcript of the run
before it. That is deliberate (PRIOR_ART: long-lived sessions fed events contaminate). Whether a feedback run should
continue the earlier run's OpenCode session is a question for M15, answered against the decisions corpus.

Known prompt gaps that make routing noisier than it should be (PRIOR_ART "In prompts"): the worker's own PR replies can
read back as new feedback, CI newness is keyed on the check run id so a re-run counts as new, and a merge conflict has
no phase.

### R5. Needs-a-human queue: one view of what is blocked on the operator

Built. The attention list (§14): `canopy status`, `attention.md`, and `notify.cmd`. It covers review
(`green_unreviewed`, `approved`), input (`needs_human`, and review comments the overseer judges need a human), and
failed retries (`attempt_limit`, `worker_failed`, `crashed`, `unpushed`, `unknown_result`).

Gap: DESIGN §15's attention item after three consecutive overseer failures is not built (M3's status line).

### R6. Two-way control: see status of active and recent sessions, and prompt any of them

Partial; the rest is M15.

- See: `canopy status` shows the attention list, running workers, and the last tick; `canopy decisions` shows what a
  tick decided; each run's log is under `<state_dir>/runs/`. Missing: a list of recent runs with their outcome, PR,
  and summary, and the OpenCode session id of each run, which would let the operator open its transcript with
  OpenCode's own tools.
- Prompt an idle ticket: built. An authorized reply on the ticket, or a review comment on the PR, is picked up by the
  next tick and resumes the work (§7). This keeps the operator's daily surface where coworkers' already is.
- Prompt a running session: not possible today, and in tension with H1: C3.

### R7. OpenCode as the runtime, with the operator's existing skills and MCP config

Built. Command templates add canopy's definitions directory with `OPENCODE_CONFIG_DIR`, which OpenCode merges after the
operator's global and repository config rather than replacing it, so the operator's MCP servers and skills load in
every run (§13). Constraints the operator should know:

- A skill in `$HOME` that workers use must be a single `SKILL.md`: the worker's `external_directory: deny` lets it load
  the skill but not read files beside it (§13).
- A repository whose OpenCode config defines an agent named like canopy's is refused (D044).
- Workers need MCP write scope (PR create and update, ticket comments and labels) that a read-only overseer setup does
  not give (M1's `Next`).

### R8. Ticket dependencies: won't start B until A lands

Built in code (M4), live acceptance pending; conflicts as written: C1. Blockers are read from the tracker's own
relations (Jira "is blocked by" links) each tick (§10). canopy may start B before A lands by stacking B on A's open,
green PR.

### R9. PR-scoped workspaces for "address feedback" and "fix CI on my PR"

Gap; sketched as M14. All of canopy's work is keyed by ticket. M11's `review.query` reviews the operator's own PRs
without a ticket, but never pushes to them (§21). Fixing CI or addressing review on a hand-written PR needs a PR-keyed
unit of work and a way to authorize pushing to a branch outside `trust.branch_prefix`: C4.

### R10. Worktree setup hooks that cope with the Bazel monorepo

Partial; the rest is M16. What treehouse provides natively, and canopy relies on:

- `post_create` hooks in the user-level treehouse config, run in each slot when it is created or reset (§9).
- A committed `.worktreeinclude` seeds gitignored files (local config, generated files) from the primary clone into
  each slot. A personal manifest is `treehouse get --include-file`, which canopy does not pass yet.
- Slots are reused at fixed paths. Bazel keys its output base on the workspace path, so each slot's output base stays
  warm across leases; a shared `--disk_cache` and `--repository_cache` in the operator's `.bazelrc` share work between
  slots (§9).

Gaps:

- Fast disk: in a workspace (§18) canopy sets `TREEHOUSE_ROOT` to the workspace root, so the pools live wherever the
  workspace does. In a workspace of one, treehouse's own `root` config applies. Today the answer is to put the
  workspace on the fast disk; a user-only pool root is M16's question.
- `post_create` runs on the base branch before `_run` checks out the ticket's branch, and a failing hook does not fail
  the lease (PRIOR_ART "Open design questions"). Setup that depends on the branch, or that must succeed, has no place.
- Each slot leaves a Bazel server running after its run. Nothing shuts it down; memory grows with the pool.
- Unverified: whether the worker's `external_directory: deny` refuses reads through `bazel-out/` and `bazel-bin/`,
  which are symlinks into the output base outside the worktree.

## Nice to have

- **N1. Local web UI on localhost.** Conflict: C2. DESIGN §3 and ROADMAP's deferred list rule out a web UI, and a
  localhost server is a network listener (TRUST_MODEL §4).
- **N2. Notifications when something needs the operator, desktop first, Slack later.** Planned in M10, Slack first.
  `notify.cmd` can reach the desktop today only through a wrapper script of the operator's (`notify-send` takes
  arguments, not stdin), which H2 rules out. M10 should ship a desktop sink first.
- **N3. Planner agent that splits a larger ticket into worker tasks.** Planned in M8: the split creates child tickets
  in the tracker, blocked on each other in order, with no queue label; the operator labels each to start it (§18).
- **N4. Copilot CLI support.** Deferred until a coworker asks. ROADMAP expects "a config change plus prompt tweaks",
  but canopy's definitions directory, its permissions, and the D044 guard are written in OpenCode's terms; a second
  runtime needs its own definitions set and its own shadowing check.
- **N5. Docker or remote sandbox runtimes later.** Deferred; proposal in `HOST_ISOLATION.md`. A remote sandbox must
  still satisfy H1.

## Non-goals for now

- Mobile access, remote relay, team or hosted features. Aligned: DESIGN §3, TRUST_MODEL §4.
- A new CLI that coworkers must learn to get value. Aligned: coworkers' surface is labels, ticket comments, and PR
  review (DESIGN §2, §4). Only the operator runs `canopy`. M14's sketch authorizes PR work with a label for the same
  reason.

## Conflicts

Each needs the operator's decision, recorded in `DECISIONS.md`. Until then the design doc stands.

- **C1. Stacking vs "won't start B until A lands" (R8).** The overseer stacks B on A's branch when A's PR is open and
  green (§10, D045), so B starts before A lands. Options: keep stacking (B's PR waits on A's merge either way, and the
  requirement is read as "B never lands before A"); make stacking opt-in with a shared `policy` key, off by default, so
  B waits until A's ticket is closed. The second is an overseer prompt change (human approval) and a config key.
- **C2. Local web UI vs no listener (N1, H1).** A localhost server is a listener, which TRUST_MODEL §4 rules out and
  DESIGN §3 lists as a non-goal. Options: keep it out; render a static `status.html` beside `attention.md` that the
  operator opens as a file, which needs no listener; or change TRUST_MODEL §4 to allow a loopback-only, read-only
  server, with human approval.
- **C3. Prompting a running session vs one-shot runs (R6).** Workers run with `opencode run`, which takes no input once
  started; feeding a live session needs `opencode serve`, a listener (C2's problem), and is the long-lived-session
  pattern PRIOR_ART warns against. Options: prompt only between runs, through the ticket or PR as today, with M15
  adding recent runs and session ids to `canopy status`; or stop a run and resume it with the operator's text,
  which needs an operator command (`canopy resume KEY`) the guards check like any dispatch.
- **C4. Pushing to the operator's own PR branches vs `trust.branch_prefix` (R9).** Workers may push only under the
  prefix (TRUST_MODEL T1, §6). Options: the worker pushes a prefixed branch and opens a PR into the operator's branch,
  which keeps T1 as it is but adds a merge step for each fix; or a PR the operator authored and labeled with a queue
  label may be pushed to on its own head branch, never with force, which needs TRUST_MODEL T1 and §6 changes with
  human approval.
