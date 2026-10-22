# canopy requirements

The primary operator's requirements, written down 2026-10-06 (R11 to R13 on 2026-10-08, R14 on 2026-10-09, R15 to R17 on
2026-10-14, R18 on 2026-10-15, R19 on 2026-10-16, R20 to R22 and R26 on 2026-10-17, R23 and R24 on 2026-10-19, R25 on
2026-10-21), and where canopy stands on each. The design (`design/`) is how canopy meets them; this file is what it must
meet. Where the two disagree, the conflict is listed under [Conflicts](#conflicts) until a `DECISIONS.md` entry settles
it, and the design doc stays normative until then (AGENTS.md).

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

Built in code (M3, M56), live acceptance pending. A `resume` continues the ticket's branch and PR for whatever comes
back to it, failed checks and review comments in one run, with cursors so each failure and comment is handled once (§7,
§8), and one attempt limit and a CI cooldown in code (D030).

Partial on "the agent that owns the PR": each run is a fresh worker on the pushed branch with no transcript of the run
before it. That is deliberate (PRIOR_ART: long-lived sessions fed events contaminate), and M15 kept it: a feedback run
does not continue the earlier run's OpenCode session (§8, A fresh session per run). It reads the latest runs'
reports instead (`{{PREVIOUS_RUNS}}`).

Known prompt gap that makes routing noisier than it should be (PRIOR_ART "In prompts"): CI newness is keyed on the
check run id so a re-run counts as new. The worker's own PR replies no longer read back as new feedback: workers mark
every comment with `trust.comment_prefix` and `trust.comment_suffix`, which only take authority away (§8, D069). A
merge conflict now has a phase: `conflicted` sends a `resume` to merge the base in (§7).

### R5. Needs-a-human queue: one view of what is blocked on the operator

Built. The attention list (§14): `canopy status`, `attention.md`, and `notify.cmd`. It covers review
(`green_unreviewed`, `approved`), input (`needs_human`, and review comments the overseer judges need a human), and
failed retries (`attempt_limit`, `worker_failed`, `crashed`, `unpushed`, `unknown_result`).

A failing loop is not an attention item: it cannot add to the latest `ok` tick's list. Three consecutive ticks not
`ok` send a `loop.failing` notification once per streak, and `loop.recovered` at the next `ok` (§15, §20).

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
With `tracker.private` set, a labeled ticket is started privately by its first dispatch (D119): the operator's queue
label brings it in, and the label stays visible on the ticket.

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
worker hears it, an `implement` as well as a `resume` (D093); keeping it off the ticket is the worker
prompt's, not a guard (TRUST_MODEL T6). The gate is the
overseer's judgment, checked again by the worker; the harness cannot see who wrote a review comment (D003).

### R14. Flaky CI is rerun, not fixed

Built in M25, live acceptance pending (SCENARIOS S63). Written down 2026-10-09. When a PR's check fails for a reason
the change did not cause (a flaky test, a lost runner, a registry outage), canopy should get it rerun instead of sending
a worker to "fix" code that is not broken, again and again.

Shape (§23), reshaped by the operator 2026-10-22: the `resume` worker sent for the failure judges it, with evidence,
and reports it `flaky` rather than changing anything; the overseer then asks the operator to rerun the check
(`flaky_rerun`) instead of waiting for a newer run. No agent reruns CI. Rejected: a `triage-ci` run before each `resume`
that reran what it judged flaky, the first design, deferred 2026-10-15.

### R15. Tell every run that builds or reads CI about a passing condition, for as long as it lasts

Built in M35, live acceptance pending (SCENARIOS S37). Written down 2026-10-14. When something outside the work goes
wrong for a while (an artifact registry outage, so CI builds will likely fail), the operator should be able to say so
once and have every run that builds, tests, or reads CI hear it until it is over, without editing a file and remembering
to edit it back. The overseer should hear it too, so it does not spend `resume` attempts, which never reset (D030), on
failures the notice explains. `paths.worker_instructions` (§12) carries text to workers, but it never lapses, the
overseer, reviews, and chores never read it, and nothing shows it is in force; a notice to workers (`canopy notice`, or
the web UI's settings page, §8) lapses, reaches all of them, and shows on every page while it lasts.

### R16. Change limits and tighten trust settings from the web UI

Gap (M41). Written down 2026-10-14. The operator changes some settings often enough that opening a config file is
friction: a pool's slots, how many workers run at once, an attempt limit, how often the loop ticks. They should be
able to change those from the web UI's settings page and have the loop take them up, as a reload does today. Trust
settings may be changed from the page only toward stricter: removing an authorized replier or a trusted reviewer,
turning `trust.rebase` off, turning the commit trailer on. Loosening one, or changing any key that runs a command,
chooses a prompt, or moves the listener, stays an edit to the file. Today the web channel writes no config at all
(TRUST_MODEL T8).

### R17. Review a coworker's PR on request, once or for as long as it is open

Built in part (M42): `canopy start URL --review`, or the web UI's reviews page, has canopy review a
PR once, at its head (§21, Review requests); the live check is SCENARIOS S39. Watching one, reviewed again at each new
commit until it merges, is deferred (ROADMAP's deferred list): the operator judged it more than MVP needs. Written down
2026-10-14. The operator should be able to hand canopy someone else's PR to review: once, at its current commit, or
watched, reviewed again at each new commit until it merges or closes. Before M42 canopy reviewed a PR only as the
loop's own (`review.agent_prs`) or as a match of `review.query`, a standing search in the user file, so one PR meant
editing config and editing it back. The review is what any canopy review is: findings in the journal for the
operator, posted nowhere unless the operator publishes it (D114), with no worker and no ticket. Publishing one on the
PR, word for word as the operator approved it after editing it in canopy, is built from the CLI; iterating on it with
an agent, and doing it from the web UI, are planned (M43, §34).

### R18. Plan a ticket before implementing it, and keep the plan

Planned (M44, §25). Written down 2026-10-15. Planning should be a step canopy can take for a ticket: a run that reads
the ticket and the code and writes down how it will do the work, before any `implement` starts. Two reasons. A worker
that starts from an explicit plan should do better than one that plans as it goes. And the plan should be kept, so
the operator can read it later for any ticket, as they read its conversation and runs today: on disk, as a file of its
own outside the journal (2026-10-16), that they can read and edit with their own tools.

Whether a ticket is planned is a config default the operator can change for one ticket. When a ticket is planned, the
operator reads the plan before work starts: nothing is implemented until they approve it, and a reply asking for
changes makes a new plan. The plan stays in canopy and is posted nowhere, so a private ticket is planned the same way.
Today the `implement` worker plans inside its own session, and nothing of it survives but its summary.
2026-10-16: the operator reads a plan as a document, edits it in place, and comments on its passages, as on a shared
document; asking for changes gives the planner each comment with the passage it is on.

### R19. Configure each workspace on its own

Built in M49, live acceptance pending. Written down 2026-10-16. Most of what the operator sets belongs to one
workspace: its queue labels, who may steer its workers, its capacity and pools, its chores and reviews, how often its
loop runs, and the port its web UI listens on. Those settings should live with the workspace, so that changing one
workspace's leaves every other alone, and two loops in two workspaces do not share a port. Only what serves every
workspace stays in a file of the operator's own, and that file is optional. The workspace file is shared and perhaps
committed, so it can hold none of these (TRUST_MODEL T7); each workspace's private file, `.canopy/config.toml`, does,
and the user file is optional (§12).

### R20. Read every reply to a coworker's review before it is sent, in place on the PR

Built (M53, DESIGN §29): under `trust.review_replies = "approve"`, the default, workers draft their replies, canopy reads
the threads itself, and the operator edits, drops, or sends each draft on its thread on the PR's page, or with
`canopy draft`, posted unmarked as one comment review by canopy's own GitHub program. Written down 2026-10-17.
A `resume` worker answers review comments on the PR as the operator, and the
operator first sees what it said when their coworkers do. They want the worker to plan its replies and canopy to show
them each one on its thread, in place on the PR's diff, to edit, drop, or send. A reply the operator sends is their
own words, so it should not start with `CANOPY:`; the marks stay for what workers post themselves (D069). Reading the
threads and posting the replies should be deterministic, done by canopy rather than an agent, which needs canopy to
ship a program that writes to GitHub (C7).

### R21. Plan each round of PR feedback, and approve the plan rather than sort the reviewers

Planned (M54, §32). Written down 2026-10-17. Before a `resume` runs, canopy should plan it, and the operator accepts
the planned fixes, item by item if they like, instead of first deciding whose feedback is trusted (R13). The plan covers
what is new on the PR, from anyone, with the PR's CI state. Until the operator accepts, new feedback, a new push, or a
change in CI makes the plan stale, and canopy plans again, once the PR has gone quiet rather than on every comment.

### R22. Skip the plan for trivial work

Deferred by the operator (M55, 2026-10-20): in use, triage judged too few tickets trivial for its runs to save what they
cost, so it was removed, and every ticket `policy.plan` plans is planned, trivial or not; the operator still skips one
ticket's plan with `canopy plan KEY --skip` (D126). The approval half is met another way (§25, 2026-10-20): under
`policy.planner_may_approve` the planner may say its plan needs no review, so the plan run stays and the click goes.
Written down 2026-10-17. With plans on (R18, R21), an obvious change
still costs a planner run and the operator's approval. As an option, a smaller, cheaper agent should judge a change
trivial, without the operator having to say what that means (2026-10-19), and let it go ahead unplanned, without asking
the operator first. When it is unsure, or fails, the work is planned as before. A waived change canopy's own reviewer
judges high impact is called out to the operator; its size alone is not, since size says little about risk.

### R23. Canary a model on one ticket

Partial: planned (M58, §13, Each agent's model). A run records the model canopy asked for, not the one that served it;
with a template's `--model` refused, a session runs the model asked for or fails before its first call.
Written down 2026-10-19, from issue #418. The operator wants to try a model change on one ticket before
every worker takes it, by running that ticket's workers on another model and comparing the result. Today a worker's
model is OpenCode's default unless the operator's command template names one, which then applies to every worker run,
and the journal does not record which model a run used. canopy should choose the model itself: a default the operator
sets, and an override per ticket that only the operator can set, never the overseer or a worker, checked against the
models OpenCode has. Each run should record the model it was given, and the one that served it where OpenCode says so,
and spend should split by model, so that the canary can be compared.

### R24. Personas for planning, reviews, and implementation

Partial (M60, §31): the default persona, the shipped ones, a persona per agent in private config, the override per
ticket, and the operator's choice for one run or one review request are built; M60's live checks remain. Written down
2026-10-19. The operator wants to give planning, reviews, or implementation a flair of its own by choosing a persona
for the planner, the reviewer, or the workers: a short file of voice and
emphasis, chosen by the operator alone, by default for each agent and per ticket. A default persona holds canopy's
standard personality, taken out of the shipped prompts, so a chosen one replaces that voice rather than competing with
it. A persona changes how an agent writes and what it weighs, never a guard, a contract, or a model. canopy ships a few,
and the operator adds or shadows them in private config. Each run records which persona it had, so personas can be
compared.

### R25. One-off private tasks, about no ticket

Built in part (M61, §36): a task runs, and the operator's replies run it again; its report and tickets are to come.
Written down 2026-10-21. The operator wants to hand canopy one-off work in their own words that belongs to no ticket:
exploring a question in the code, or planning the tickets that should follow. A task runs once in a worktree and may
push a branch, open a draft PR, and file tickets with no queue label. What it leaves is throwaway quality until the
operator gives it a pass of their own. Like a started ticket, its conversation stays in canopy.

### R26. Publish artifacts people comment on, and bring their comments back to the ticket

Gap (M62, §38). Written down 2026-10-17. A worker should be able to publish what it made for people to read, such as a
report, a design, or an HTML mock-up, to an artifact store, and anyone the operator shares it with should be able to
comment on its passages. Those comments should come back to the ticket that produced the artifact, where they steer
its next run as review feedback does, and the worker's revision should answer them in place. The store is Louvre, a
hosted platform for the operator's organization that is its own program, not part of canopy; or, for the operator
alone, a local store canopy ships that serves the same tools. canopy reaches Louvre through the agent runtime's MCP
and a connector, with the operator's own token, and pulls comments rather than listening for them, so H1 holds.

## Nice to have

- **N1. Local web UI on localhost.** Built in M20, live acceptance pending. Allowed under TRUST_MODEL T8 (C2, D055),
  behind the listener secret the operator signs in with. The operator expects it to become their main surface
  (C5), served by `canopy loop` with an off switch (D073). OpenCode's own attach (M15) covers sessions first.
- **N2. Notifications when something needs the operator, desktop first, Slack later.** Built in M10, live acceptance
  pending: canopy ships a desktop sink, `canopy-notify-desktop`, and a Slack sink, `canopy-notify-slack` (DESIGN §20,
  D035). No wrapper script of the operator's is needed.
- **N3. Planner agent that splits a larger ticket into worker tasks.** Replaced by follow-ups (ROADMAP M46, §18,
  Follow-up tickets), built, live acceptance pending. M8's split run is gone. An `implement` or `resume` worker files
  follow-up tickets, with no queue label, which authorize nothing; canopy asks the operator to label or start each. An
  authorized reply asking for a split is guidance to the ticket's next run, whose worker files the pieces as
  follow-ups, blocked on each other in order.
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

Each was settled by the operator, C1 to C4 on 2026-10-06, C5 on 2026-10-08, and C7 on 2026-10-17, and recorded in
`DECISIONS.md` (C1 in DESIGN §10).

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
  2026-10-13 (issue #293, D056): with `trust.rebase`, private and off by default, workers rebase onto their base and
  push with `--force-with-lease`, the only force their definitions allow. Without it, they merge, as before.
- **C7. canopy's own GitHub program vs connectivity through the agent runtime (R20, D003, DESIGN §4 principle 5).**
  Showing a PR's threads and sending exactly the approved reply, deterministically, needs a program canopy ships that
  reads and writes GitHub with the token `gh` holds, where today only agents reach GitHub. Settled by the operator on
  2026-10-17 (D003): canopy will ship such programs, separate from the harness, which still imports no client and
  holds no token. M36 builds the reads and M53 the writes; until one of them lands, agents remain the only way in.
