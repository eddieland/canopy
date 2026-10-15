# canopy requirements

The primary operator's requirements, written down 2026-10-06 (R11 to R13 on 2026-10-08, R14 on 2026-10-09, R15 to R17
on 2026-10-14), and where canopy stands on each. The design (`design/`) is how canopy meets them; this file is what it
must meet. Where the two disagree, the conflict is listed under [Conflicts](#conflicts) until a `DECISIONS.md` entry
settles it, and the design doc stays normative until then (AGENTS.md).

A bare § is a section of the design (`design/`). Status words:

- **Built**: in code with fakes-based tests; live acceptance may still be the operator's to run (ROADMAP).
- **Planned**: designed, in a ROADMAP milestone, not built.
- **Partial**: some of it is built or planned; the rest is listed as a gap.
- **Gap**: nothing designed yet; a ROADMAP sketch names where it goes.
- **Conflict**: the requirement and a normative doc disagreed; see [Conflicts](#conflicts) for how each was settled.

## Hard constraints

### H1. Runs entirely on the operator's machine; no hosted relay, no mobile app, nothing exposed off-box

Built. Nothing listens on the network yet; the loop is a foreground command (§6, D042); state, logs, and
worktrees are local and operator-only. The services canopy's agents reach (the tracker's MCP server, such as
Atlassian's remote MCP, GitHub, and the model provider) are ones the operator already uses, reached by the agent runtime
with the operator's own credentials (D003); canopy adds no service of its own in between. The planned Slack sink (§20)
posts outbound only and listens for nothing.

Listeners are now allowed on loopback, or on a private-network address the operator sets, behind the operator's
secret (TRUST_MODEL T8, D055, C2). Loopback, the default, keeps this constraint; a private-network address is the
operator's choice to reach the machine from elsewhere on the VPC, which relaxes "nothing exposed off-box".

### H2. Extended only through native plugins or config; no custom layer to maintain

Partial. The runtime is a command template (D009), trackers are MCP plus a skill (D014), and customization is skills
where OpenCode already looks (§13). Worktree setup is treehouse's own hooks and `.worktreeinclude`, and a setup
command the operator writes for their repositories, not for canopy (R10). Two places still ask the operator to keep
code or text of their own in step with canopy:

- A notification destination other than the shipped ones is "a small program of the operator's" (§20). The desktop
  and Slack destinations the operator wants (N2) ship with canopy (M10).
- Prompt overrides (§12) are copies the operator maintains, and an override must keep what canopy's guards rely on
  (D051). Prefer a skill; treat an override as a last resort. Opening PRs, which an operator's employer may need done
  with its own tooling, takes a skill of the operator's through `runtime.pr_skill` instead (§8), and a habit every
  worker should keep, such as how to commit review fixes, takes a few lines in `paths.worker_instructions` (§12).

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

Built. treehouse is the pool (D002): canopy leases a slot per run, one in each repository a joint run covers (§18),
records it in `run_slots`, returns it on every exit path, and returns stale leases in reconcile (§6, §8). The capacity
limit is `capacity.max_workers`; treehouse's `max_trees` bounds the pool. In a workspace the operator can declare each
pool's size (`capacity.slots_per_repo`), which leases stay within and `canopy workspace sync` creates and trims slots
to match, alongside cloning and removing repositories to match the map (§18, M17). The web UI's worktrees page shows
every slot: what holds it, its branch, and what runs in it (§22).

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

Known prompt gap that makes routing noisier than it should be (PRIOR_ART "In prompts"): CI newness is keyed on the
check run id so a re-run counts as new. The worker's own PR replies no longer read back as new feedback: workers mark
every comment with `trust.comment_prefix` and `trust.comment_suffix`, which only take authority away (§8, D069). A
merge conflict now has a phase: `conflicted` sends a `resume` to merge the base in (§7).

### R5. Needs-a-human queue: one view of what is blocked on the operator

Built. The attention list (§14): `canopy status`, `attention.md`, and `notify.cmd`. It covers review
(`green_unreviewed`, `approved`), input (`needs_human`, and review comments the overseer judges need a human), and
failed retries (`attempt_limit`, `worker_failed`, `crashed`, `unpushed`, `unknown_result`).

Gap: DESIGN §15's attention item after three consecutive overseer failures is not built (M3's status line).

### R6. Two-way control: see status of active and recent sessions, and prompt any of them

Partial; the rest is M15.

- See: built. `canopy status` shows the attention list, running workers, the last tick, and the ten runs that ended
  most recently with their outcome, PR, summary, cost, run log, and OpenCode session id, which opens the run's
  transcript with OpenCode's own tools (§13); `canopy decisions` shows what a tick decided. The web UI shows an
  ended run's or tick's transcript, its tool calls included, read back from its log (M27), and the end of a tick's
  output as written, stderr included. A running worker's session id and events are known only once it ends:
  they are read from what `opencode run` printed.
- Prompt an idle ticket: built. An authorized reply on the ticket, or a review comment on the PR, is picked up by the
  next tick and resumes the work (§7). This keeps the operator's daily surface where coworkers' already is.
- Prompt a running session: not possible today; M15 runs workers against OpenCode's server so the operator can
  attach (C3, D055).

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

Built in code (M4), live acceptance pending. Blockers are read from the tracker's own relations (Jira "is blocked by"
links) each tick (§10). canopy may start B before A lands by stacking B on A's open, green PR; the operator keeps that
or turns it off with `policy.stacking` (C1).

### R9. PR-scoped workspaces for "address feedback" and "fix CI on my PR"

Gap; sketched as M14, which the operator deferred on 2026-10-15: real use has not needed it. All of canopy's work is
keyed by ticket. M11's `review.query` reviews the operator's own PRs without a ticket, but never pushes to them (§21).
Fixing CI or addressing review on a hand-written PR needs a PR-keyed unit of work, and pushing to the PR's own branch,
which D056 now allows (C4).

### R10. Worktree setup hooks that cope with the Bazel monorepo

Built in M16; its live check is the operator's. Setting up a slot is three steps, all the operator's (§9):

- Seeding: a committed `.worktreeinclude` seeds gitignored files (local config, generated files) from the primary clone
  into each slot on every lease. A personal manifest, `paths.worktree_include`, replaces it; canopy passes it to every
  `treehouse get` as `--include-file`.
- `post_create` hooks in the user-level treehouse config, run in each slot when it is created or reused, on the base.
- `runtime.setup_cmd`, run in each slot after `_run` checks out the ticket's branch; a failure fails the run.

For Bazel (§9, and the operator's guide, `docs/BAZEL.md`): slots are reused at fixed paths, and Bazel keys its output
base on the workspace path, so each slot's output base stays warm across leases. A shared `--disk_cache` and
`--repository_cache` in the operator's `.bazelrc` share work between slots, `--output_user_root` puts the output bases
on a fast disk, and `startup --max_idle_secs` ends a slot's idle server. A fast disk otherwise takes the whole
workspace, pools and clones together (§18, D033). Unverified until the canary's first real run: that the worker reads
through `bazel-out/` and its siblings, links into the output base, and is refused the output base by its own path.

### R11. Private tickets: deliver a ticket without the conversation appearing on it

Built in M18; its live check is the operator's. When a client files the ticket, the operator wants canopy to deliver it
without the agent's reports, its questions, or the operator's answers showing on the client's ticket. Today the ticket
is the only channel for both (§7, §8), and the queue label is itself visible.

Shape (§22, D072): the operator starts the ticket in canopy (`canopy start`) instead of labeling it; its
workers can only read the tracker; questions reach the attention list (`awaiting_reply`) and `canopy show`, and the
operator answers with `canopy reply` or from the web UI. Its branch and PR title still name the ticket key, which a
tracker's VCS integration may link to the ticket (DESIGN §22, Open).
The PR still carries the commit attribution TRUST_MODEL T5 gives it: privacy covers the conversation, not authorship.

### R12. One record of every ticket's conversation

Built in M19, live acceptance pending. Every ticket's conversation, public or private, in one place canopy owns, so the
web UI (N1) can show it as one inbox and later channels such as Slack join it rather than keeping their own (§22, D072).
For a public ticket the tracker stays the authority and the journal holds the overseer's copy: each tick the overseer
mirrors new tracker comments with `canopy mirror` (D081), and `canopy show` lists them with workers' reports and the
operator's replies. Gap: PR review comments, which join with PR subjects (M14).

### R13. Trusted and untrusted reviewers

Built in M22, live acceptance pending. Written down 2026-10-08. Only reviewers the operator trusts send a worker back
to a PR on their own. Anyone else's feedback, a review bot's included, waits for the operator's approval, ideally with
an instruction ("use your best judgement based on the bot's review").

Shape (§7, D089): `trust.trusted_reviewers` lists the trusted, empty by default, with `canopy:review` for canopy's own
reviewer. Untrusted feedback is `untrusted_review` on the attention list. The operator answers with `canopy reply` or
the web UI, on a public ticket too; the reply is the worker's instruction and never reaches the ticket. Every public
worker hears it, an `implement` or `fix-ci` as well as a `resume` (D093); keeping it off the ticket is the worker
prompt's, not a guard (TRUST_MODEL T6). The gate is the
overseer's judgment, checked again by the worker; the harness cannot see who wrote a review comment (D003).

### R14. Flaky CI is rerun, not fixed

Deferred (M25, 2026-10-15). Written down 2026-10-09. When a PR's check fails for a reason the change did not cause (a
flaky test, a lost runner, a registry outage), canopy should rerun it instead of sending a worker to "fix" code that is
not broken. Which failures are flaky is the repository's knowledge, so it comes from a skill the operator or the
repository provides, and a CI that is not GitHub Actions is reached through its own MCP server.

Shape (§23): a `triage-ci` run comes before `fix-ci` on a new failure. It reads the failure, follows the
named skill, and either reruns the failed jobs or reports the failure real, which sends `fix-ci` as today. It never
edits or pushes. The operator turns it on with `policy.max_triage_ci_attempts`, off by default; the repository supplies
the skill but cannot turn reruns on. Needs TRUST_MODEL changes (T1, T3, T6, T7, §6, §7) approved in M25's PR.

### R15. Tell every run that builds or reads CI about a passing condition, for as long as it lasts

Built in M35, live acceptance pending (SCENARIOS S37). Written down 2026-10-14. When something outside the work goes
wrong for a while (an artifact registry outage, so CI builds will likely fail), the operator should be able to say so
once and have every run that builds, tests, or reads CI hear it until it is over, without editing a file and remembering
to edit it back. The overseer should hear it too, so it does not spend `fix-ci` attempts, which never reset (D030), on
failures the notice explains. `paths.worker_instructions` (§12) carries text to workers, but it never lapses, the
overseer, reviews, and chores never read it, and nothing shows it is in force; a notice to workers (`canopy notice`, or
the web UI's settings page, §8) lapses, reaches all of them, and shows on every page while it lasts.

### R16. Change limits and tighten trust settings from the web UI

Gap (M41). Written down 2026-10-14. The operator changes some settings often enough that opening the user config file
is friction: a pool's slots, how many workers run at once, an attempt limit, how often the loop ticks. They should be
able to change those from the web UI's settings page and have the loop take them up, as a reload does today. Trust
settings may be changed from the page only toward stricter: removing an authorized replier or a trusted reviewer,
turning `trust.rebase` off, turning the commit trailer on. Loosening one, or changing any key that runs a command,
chooses a prompt, or moves the listener, stays an edit to the file. Today the web channel writes no config at all
(TRUST_MODEL T8).

### R17. Review a coworker's PR on request, once or for as long as it is open

Gap (M42). Written down 2026-10-14. The operator should be able to hand canopy someone else's PR to review: once, at
its current commit, or watched, reviewed again at each new commit until it merges or closes. Today canopy reviews a PR
only as the loop's own (`review.agent_prs`) or as a match of `review.query`, a standing search in the user file, so
one PR means editing config and editing it back. The review is what any canopy review is: findings in the journal for
the operator, posted nowhere (D114), with no worker and no ticket.

## Nice to have

- **N1. Local web UI on localhost.** Built in M20, live acceptance pending. Allowed under TRUST_MODEL T8 (C2, D055),
  behind the listener secret the operator signs in with. The operator expects it to become their main surface
  (C5), served by `canopy loop` with an off switch (D073). OpenCode's own attach (M15) covers sessions first.
- **N2. Notifications when something needs the operator, desktop first, Slack later.** Built in M10, live acceptance
  pending: canopy ships a desktop sink, `canopy-notify-desktop`, and a Slack sink, `canopy-notify-slack` (DESIGN §20,
  D035). No wrapper script of the operator's is needed.
- **N3. Planner agent that splits a larger ticket into worker tasks.** Built in M8, live acceptance pending, and only on
  request: an authorized replier's comment asks for the split. The split creates child tickets
  in the tracker, blocked on each other in order, with no queue label; the operator labels each to start it (§18).
- **N4. Copilot CLI support.** Deferred until a coworker asks. More than a config change: canopy's definitions
  directory, its permissions, and the D044 guard are written in OpenCode's terms, so a second runtime needs its own
  definitions set and its own shadowing check (ROADMAP's deferred list).
- **N5. Docker or remote sandbox runtimes later.** Deferred. A local OS sandbox, opt-in, is ROADMAP M26
  (DESIGN §24). A remote sandbox runs agents off the operator's machine, so it would change H1 and needs its own
  decision first.

## Non-goals for now

- Mobile access, remote relay, team or hosted features. Aligned: DESIGN §3, TRUST_MODEL §4.
- A new CLI that coworkers must learn to get value. Aligned: coworkers' surface is labels, ticket comments, and PR
  review (DESIGN §2, §4). Only the operator runs `canopy`. M14's sketch authorizes PR work with a label for the same
  reason.

## Conflicts

Each was settled by the operator, C1 to C4 on 2026-10-06 and C5 on 2026-10-08, and recorded in `DECISIONS.md` (C1 in
DESIGN §10).

- **C1. Stacking vs "won't start B until A lands" (R8).** The overseer stacks B on A's open, green PR (§10), so
  B starts before A lands. Settled (DESIGN §10): stacking stays, controlled by `policy.stacking` (`"auto"` or
  `"never"`), which the overseer prompt follows. No harness guard. Under `"never"`, B waits until A has landed: closed,
  and its PR merged if it had one.
- **C2. Local web UI vs no listener (N1, H1).** Settled by D055: listeners are allowed on loopback, or on a private
  network address the operator sets, behind the operator's listener secret (TRUST_MODEL T8). Loopback is the default
  and keeps H1; a private-network address is the operator's choice to relax it. A UI is now deferred, not ruled out.
- **C3. Prompting a running session vs one-shot runs (R6).** Settled by D055: workers may run against OpenCode's own
  server, and the operator prompts a running session with `opencode attach` (M15).
- **C4. Pushing to the operator's own PR branches vs `trust.branch_prefix` (R9).** Settled by D056: a worker may push
  to the head branch of an open, non-fork PR the operator authored and labeled with a queue label, never with force
  (TRUST_MODEL T1, §6; to be built in M14, now deferred).
- **C5. The web UI as the operator's main surface vs "daily surface is labels, ticket comments, PR review, and one
  attention list" (DESIGN §4 principle 6, N1).** Settled by the operator on 2026-10-08 (D072, D073): the operator's
  own surface moves to the web UI once M20 is built, and private tickets (R11) are answered there or with the CLI.
  Coworkers' surface is unchanged: labels, ticket comments, and PR review. Principle 6 says so since M20.
- **C6. Repositories that refuse merge commits vs pushes that are never forced (R4, R9).** Settled by the operator on
  2026-10-13 (issue #293, D056): with `trust.rebase`, user-only and off by default, workers rebase onto their base and
  push with `--force-with-lease`, the only force their definitions allow. Without it, they merge, as before.
