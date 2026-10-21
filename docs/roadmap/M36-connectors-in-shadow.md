# M36. Connectors: the world observed into the journal, in shadow

MEASUREMENTS 2026-10-12 F6, F9, F10; 2026-10-13 F13, F14, F16, F17; 2026-10-15 F25 to F29; D003's revisit and
D008's. Needs M28 and M34.
Asked for by the operator (2026-10-14): each tick of the overseer should run from journal state, read into it by
deterministic programs, instead of an agent re-reading the tracker and GitHub every tick. M36 to M39 take that one
step at a time, and supersede M29 and M30: the probe's facts go into the journal rather than gating on them, and the
overseer runs only when they leave it something to judge. Sketch only; the design comes first, as a new design file
(§30).

The shape the four share:

- A **connector** is a deterministic program, configured like a sink (§20) and run by the harness through `procs`,
  that reads one source and prints what it saw as JSON lines. canopy validates each line (pydantic, D026), bounds its
  text, and writes it to the journal as an **observation**: a dated copy of a fact about the world. Authority stays
  with the source (principle 1, §22): an observation says what the connector saw and when, never what is true now.
- The harness still imports no tracker or VCS client and holds no token (D003). A connector is a separate program
  with credentials of its own, as the Slack sink is (`packages/`, stdlib only, nothing from canopy). canopy ships
  `canopy-connect-github` (GitHub Issues and PRs, with the token `gh` holds; M53 builds its first slice, a PR's review
  threads into `observed_reviews`, in the workspace member that also posts) and `canopy-connect-jira` (Jira Cloud's
  REST API, an email and API token from an operator-only file); another tracker is the operator's program speaking
  the same contract, the only thing the harness knows of any of them. In the same PR, AGENTS.md's "no tracker code"
  line (Toolchain) is scoped to the harness package, its "a tracker adapter interface" line (Do not build) is
  amended to allow this contract, and D003 is reshaped.
- The overseer's message becomes the journal: observations, the phase the harness derives from them in code, and
  what is new since each cursor. Judgment stays the overseer's: which repository, a slug and title, a worker's
  context, whether a review comment is a change or a question, what an operator's reply asks for, a chore's `when`.
  Reading does not, and neither does anything §7's table derives from facts alone (D008's revisit: one rule at a
  time, each checked against the `decisions` corpus before it moves).

This milestone adds the connectors and the derivation without changing what the overseer sees or does:

- The contract. On stdin, one JSON object naming what to observe: the tracker query, every ticket not marked done, every
  PR URL on an unfinished unit (merged and closed included, 2026-10-13 F16), the repositories, the branch prefix
  (`trust.branch_prefix`), and `review.query` when set. On stdout, one JSON line per observation: `ticket` (key, title,
  body cut, open or closed, labels, updated at, blocker keys, label events when the tracker has them), `comment`
  (ticket, id, author account id, time, body cut), `pr` (url, repository, number, head sha, base ref, open, merged, or
  closed, draft, mergeable, mergeable state, author login, labels), `branch` (repository, name, head sha, for each
  branch under the branch prefix, so `pushed_no_pr` and a PR the journal has no unit for are observed), `check` (pr,
  head sha, context name, status, conclusion, run id, url), `review` (pr, id, review or review comment, author login,
  whether a bot, state, time, body cut, url, and for a review comment its thread, and whether that is resolved or
  outdated), and last an `end` line naming what it covered, so a connector cut off mid-way does not read as everything
  else having vanished. Unknown kinds are skipped. Ids, states, times, and bounded text; never logs or diffs. The
  tracker query is paged by the connector (REQUIREMENTS R1's gap), and CI is observed by named context, every one of
  them, never the combined status (2026-10-12 F9), which stops at 30 contexts (2026-10-15 F25). A ticket a watched
  ticket names as its blocker is observed too, whether or not the query returns it. PR labels, branches, thread state,
  every context, and blockers are what the overseer used to decide that the first draft left out (2026-10-15 F28). Open,
  and settled before the derivation reads a pending check: where the contexts that are not CI (ones that stay pending
  until a human acts) are configured, per repository, since counting one as CI holds a green PR at `ci_running`
  (2026-10-15 F28). The GitHub connector reads every watched PR in one GraphQL query a poll, not REST calls per PR,
  which would cost 15 to 18 times the overseer's MCP calls today (2026-10-15 F29), and pages any PR's contexts past the
  first page of 100 before its `end` line covers that PR.
- The journal: one table per kind (`observed_tickets`, `observed_prs`, `observed_branches`, `observed_checks`,
  `observed_reviews`), each row keyed by the source's id and replaced on each observation with its `observed_at`; a
  subject the `end` line did not cover keeps its old rows and their age. Comments go into `observed_comments`, apart
  from `messages`, so no worker's prompt carries one the overseer did not mirror (DESIGN §30), with the workers'
  marks read in code (D069). `connector_runs` records each run: when, status, counts, the tail of stderr.
- Retention (#424, DESIGN §26's journal rule): the PR that creates `connector_runs` and `derivations` adds them to
  `canopy gc --dry-run`'s report, counted with what a pass would remove, and to the deletes of M47's third stage, so
  they go with the harness's attention rows past the attention list's window and `retention.journal_days`, keeping
  each source's newest run and the newest that recorded the query's result. If that stage is built first, the PR that
  creates the tables also deletes them in its pass. `decisions` and `messages` stay whole.
- Config, private (TRUST_MODEL T7): `[connect.sources.<name>]` with `cmd` (argv, no shell, as a sink's), `kind`
  (`tracker` or `vcs`), and `timeout_minutes`, one per kind at most, nested as sinks are (§20). Beside the table, the
  scalars later milestones read, defined here so the model needs no special case: `connect.max_age_minutes` (M37)
  and `connect.every_minutes` (M39).
- Each tick runs the connectors after reconcile and before the state block (§6 step 3). A failure, a timeout, or
  output that does not validate keeps the previous observations, is logged, and raises `connector_failed`, a
  harness item like `repo_missing`; the tick goes on, and in this milestone loses nothing, since the overseer still
  reads live.
- `loop/phases.py` derives every candidate, phase, and attention reason of §7 and §14 from the observations and the
  journal's cursors, in code, and records them per tick in a `derivations` table beside `decisions`, which it does
  not touch. The loop's per-tick block and its `loop waits` line count the disagreements with what the overseer
  recorded.
- `canopy status` names each connector's last run and the age of its observations.
- Proposed (2026-10-15), for the operator to settle: the tracker connector's query first, on its own, as the one part of
  this milestone that changes what the overseer does. Run in code each tick, its result is in the state block as the
  tickets the query returned, less the tickets marked done that DESIGN §7's `recently_done` names, and the overseer
  reads those instead of running the query. When that run failed or its result is older than `connect.max_age_minutes`,
  the block says so and the overseer runs the query itself that tick, as today. A cheaper overseer skipped the query and
  read only the block's tickets, which stalls new work with no tick failing (2026-10-15 F31, DESIGN §7). A tick whose
  query was due now fails without `canopy queried` (DESIGN §6 step 5), which catches a skipped query but not a result
  read short or named short. TRUST_MODEL T1.
- Tests with the fakes: `tests/fakes/connector` prints configured lines; a line out of bounds is refused and the
  rest kept; a cut-off output keeps the previous observations; the derivation over journals written by hand, one
  case per row of the phase table, each a snapshot test (syrupy) as the state block's are; once the pass deletes them,
  rows on both sides of the window, a source's newest run kept past it.

Accept: written with the design, before work starts. Live, once built: a day of `canopy loop` with both connectors
against the real queue, and a MEASUREMENTS section giving the agreement between the derivation and the overseer per
phase row, counted by distinct situation as well as by decision (2026-10-15 F26), each disagreement read and
attributed (the rationale says which side was right), and what the connectors cost (calls and seconds per tick, no
tokens).

Status: in progress. Designed 2026-10-19 (DESIGN §30). The design settles what the sketch left open: one request
whose keys are each optional, so §29's read is one, each source sent its own kind's; a source writes only the kinds it
owns; a refused line, like a subject the `end` line did not cover, keeps its subject's old rows; the `vcs` run each tick
is also §29's reconcile read; the checks that are not CI are `human_checks` per repository in the map, shared, naming
the exceptions so a missing entry fails toward waiting; the derivation records every row that holds, since §7 has no
order yet, and a ticket whose observations are stale apart; agreement is computed, never stored; and
`connect.max_age_minutes` defaults to 30 and `connect.every_minutes` to 2; and the two per-tick tables are pruned by
§26's pass under its journal rule (#424). Built (2026-10-19): each tick runs the sources after reconcile, validates and
bounds each line, records `observed_tickets`, `observed_comments`, `observed_checks`, `observed_branches`, and a PR's
labels and mergeable state, records each run in `connector_runs`, which `canopy gc --dry-run` counts, raises
`connector_failed`, and `canopy status` names each source with its last run and the age of its observations;
`tests/fakes/connector` plays any source. `canopy loop` also polls the sources between ticks every
`connect.every_minutes`, apart from how it paces ticks (operator, 2026-10-19, ahead of M39): a poll records its runs
with no tick, raises nothing, and ends no wait. Built (2026-10-20): the derivation, `loop/phases.py`, after the
connectors each tick, recording in `derivations` each ticket's candidacy and every §7 row that held for it and each
unit, or what stale or missing observation it depended on, and at the tick's close the phase the overseer left each
at; agreement is computed per ticket (`phases.compare`), its counts in the loop's per-tick block and `loop waits`
line, and `canopy gc --dry-run` counts the rows; each repository's `human_checks` in the map is not CI. Chosen
conservatively, for the operator to change: a check with no run id or a `ci` cursor that is not a number reads every
failure as new; a candidate with no PR needs its repositories' branches read fresh, else it is stale; what a PR's
own author writes is not review feedback; and the comparison takes a ticket's dispatches, waits, skips, and done marks
as its decision, its attention items only when it has none, and the `running` its dispatch left it at as the row that
allowed the dispatch. Built
(2026-10-21): `canopy-connect-jira`, the `tracker` source for Jira Cloud, a workspace member (`packages/canopy-jira`)
speaking the whole contract: the query paged to its end, each watched ticket with its comments since canopy's newest and
each label's time from its changelog, and every blocker those name; tested against a stand-in for Jira's REST API and
through canopy's own validation, not yet against a real site (S56). Built (2026-10-21): canopy's GitHub reader,
`canopy-connect-github`, grown to the whole contract, so a tick and a poll send it the whole request whether or not a
PR is watched: each PR many to a GraphQL query, with its labels, mergeable state, and every context at its head paged
past 100, each map repository's branches under the prefix, and the review query to its last page; tested against the
stand-in for GitHub's GraphQL API and through canopy's own validation, not yet against GitHub (S57). Chosen
conservatively, for the operator to change: a context named twice at a head is its newest check run; a link canopy
would refuse is left off a check rather than refusing its PR; a PR with more than 100 labels, or a repository with more
than 1,000 branches under the prefix, is not read whole; a host `gh` holds no token for leaves only its own PRs and
repositories unread; and the review query runs on each host the map's repositories are on, or on github.com when the
map names none. Open for the operator: the tracker query run in code (Proposed 2026-10-15), and whether one failed
run raises `connector_failed` or only one that leaves an observation stale.
