# Connectors

Part of the canopy design, normative like all of it: the programs that read the tracker and GitHub into the journal,
and what canopy derives from what they read. Sections are numbered across the whole design; the [README](README.md)
has the map. Previous: [Review replies](REVIEW_REPLIES.md).

## 30. Connectors

ROADMAP M36, D003, D008. The overseer reads the tracker and GitHub again every tick, through MCP, and most of what it
reads has not changed since the tick before; once the queue settles, that watching is most of canopy's spend
(MEASUREMENTS 2026-10-15). The operator asked (2026-10-14) for each tick to run from journal state, read into it by
deterministic programs. This section is the first step: canopy reads the world into the journal and derives in code
what §7 and §14 derive, beside the overseer, which sees and does nothing different. ROADMAP M37 to M39 go further, each
with its own design.

A **connector** is a deterministic program that reads one source and prints what it saw as JSON lines. canopy runs it
through `procs`, validates and bounds each line, and records it as an **observation**: a dated copy of a fact about the
world. Authority stays with the source (§4 principle 1, §22): an observation says what a connector saw and when, never
what is true now. In this section nothing reads an observation to decide anything; the derivation reads them, and only
the operator and the measurement read the derivation.

### Sources

A source is §29's `[connect.sources]` table: at most one of each kind, `tracker` and `vcs`, each a command run with no
shell (§20), its request on stdin, under a timeout. Every `connect.*` key is private (§12, TRUST_MODEL T7), since each
runs a command with the operator's credentials. The `vcs` source defaults to canopy's own programs (§29), so PRs are
observed with nothing configured. There is no default `tracker` source, since the harness never branches on
`tracker.provider` (§17); without one, tickets are not observed, and the derivation says so. An observation older than
`connect.max_age_minutes` is stale; the default outlasts the overseer's timeout, so what a tick observed before its
overseer started is fresh through its dispatches.

### The contract

On stdin, one JSON object naming what to observe; a connector reads only what it is given. A `tracker` source is sent
`tracker.query` and every ticket the state block lists (§6 step 4), public and private, each with the time of its
newest comment the journal holds, so only newer ones are printed. A `vcs` source is sent every PR on a unit of a ticket
not marked done, merged and closed included, every PR a draft waits on (§29), the repositories with credentials
dropped from their URLs, `trust.branch_prefix`, and `review.query`.

On stdout, one JSON line per observation, naming its kind: `ticket` and `comment` from a tracker; `pr`, `branch`,
`check`, and `review` from a vcs; and last, `end`, naming what the run read whole.

- Ids, states, times, and bounded text; never logs, diffs, or PR descriptions, which no decision used.
- A connector pages everything before `end` names it: the tracker query to its last page (REQUIREMENTS R1), a PR's
  threads, its head's contexts.
- CI is observed by named context, never the combined status, which read green PRs as pending (MEASUREMENTS
  2026-10-15). Statuses are a closed vocabulary onto which the connector maps its host's.
- A watched ticket's blockers are printed too, one level deep, and every branch under the prefix, so a pushed branch
  with no PR and a PR the journal has no unit for are observed.
- The exit code is not read: `end` alone says what was read. A connector never prints a credential, on either stream.

A kind the source does not own is skipped, so one source's program never writes another's facts. Unknown kinds and
fields are ignored, so a newer connector works with an older canopy. A connector of the operator's own speaks this
contract and nothing else: it is all the harness knows of any of them.

### Validating and the journal

- Each line is validated against its kind (D026). Text is cut and marked, as a mirrored comment's is (§22); a field
  whose cut would change what it says (an id, a key, a time, a state, a list of labels) refuses the line instead.
- A refused line is logged and counted, and its subject is not whole this run, whatever `end` says: a line canopy could
  not read never looks like a review or a check gone.
- A run with no `end` line, one that times out, or one that does not start records nothing and is `failed`: without
  `end`, canopy cannot tell what is missing from what is not there.
- A subject read whole has its observations replaced in one transaction, so what is gone from the source is gone from
  the journal; a subject not read whole keeps its old rows and their age.
- Comments go into the conversation as mirrored comments do (§22), once each, the workers' marks (D069) read in code.
  The connector moves no mirror cursor and records no decision, so the overseer mirrors as before.
- Each run is recorded `ok`, `partial` (it read less than asked), or `failed`. A dry run observes as a live tick does.

### In the tick

In §6 step 3, after runs, slots, chores, and reviews are reconciled, the tick runs the `tracker` source, then the `vcs`
source, each once; a tick that closes `reconcile_failed` runs neither. The `vcs` run is also §29's reconcile read.

A source that fails, or reads less than it was asked, keeps its previous observations and raises the harness's
`connector_failed` (§14), naming what was not read, each tick until a run reads everything; the overseer's view of the
list leaves it out. The tick goes on and loses nothing, since the overseer still reads live. `canopy status` names each
source, how its last run ended, and the age of its oldest observation still asked about. The derivation follows, before
the state block is rendered.

### The derivation, in shadow

D008 moves a rule from the prompt into code one at a time, each checked against the `decisions` corpus first; applied
by hand, §7's table disagreed with the overseer on `ci_red` (MEASUREMENTS 2026-10-15). So the derivation runs in
shadow, and the measurement that closes M36 says which rows M38 may take.

- Each tick the harness derives, from the observations and the journal, what §7 and §14 derive: the candidates (§17),
  each ticket's and unit's phase, its next action, and the attention reasons. It records every row that holds, since §7
  does not yet order them, and where a next action is a choice, the actions it allows.
- A ticket that depends on a stale or missing observation is derived as `stale` and counted apart, never as a
  disagreement. A private ticket's phases come from the journal (§7).
- The derivation is recorded beside `decisions`. It writes no decision, and changes no state block, attention item,
  cursor, phase, or guard.
- It agrees with the overseer when the phase the overseer set is one of the rows that held and its decision one that
  row allows. Agreement is computed, never stored, so a fix to the comparison reads every tick already recorded. The
  loop's per-tick block (§6) prints how many differ. A tick whose overseer did not run, or failed, is not compared.

### Checks that are not CI

Some contexts stay pending until a person acts, a deploy approval or a sign-off, and counting one as CI holds a green PR
at `ci_running` for as long. Each repository names them in the map (§18) as `human_checks`, by full name. A listed
context is not CI: it does not hold a unit at `ci_running`, make it `ci_red`, or have to pass. It is still shown.

- The list names the exceptions, not the CI: a job left off a list of CI would hide a red build, while a human check
  left off this one holds a PR where the operator sees it waiting. Missing an entry fails toward waiting.
- Shared: it is a fact about the repository, and runs, spends, and authorizes nothing. A hostile edit could list a real
  CI job, never then read as red; branch protection still holds the PR, and T7's residual says so. M38, the first to
  act on it in code, revisits whether it stays shared.
- Rejected: branch protection's required checks (reading them needs admin, and one can be the human check); a time past
  which a pending check counts as human (a slow build crosses any threshold).

### canopy's connectors

Each is a uv workspace member, stdlib only and importing nothing from canopy, as §29's programs are (§5).

- `canopy-connect-github`, §29's reader, becomes the `vcs` connector, every watched PR in one query a run, not calls
  per PR. Given a repository, it is also a `tracker` connector for GitHub Issues. It uses `gh`'s token, as §29 says.
- `canopy-connect-jira` reads Jira Cloud at the site its argument names, with credentials from an operator-only file
  held to the Slack sink's checks (§20), sent only to that site, and never in config, argv, journal, or logs.
- Rejected: the harness calling the APIs (D003: the process that holds the journal and enforces the guards never opens
  a connection or reads a token, TRUST_MODEL T2); an agent as the connector (a model run as a poll, against §4
  principle 4, and what it prints is a claim, not an observation); MCP servers driven from Python (a client in the
  harness, and their credentials with it).

### What the building PR changes

For the operator to approve in merging it: D003, that the harness reads the world only through connectors; TRUST_MODEL
T1 (a connector's comments are data), T2 (the connectors' calls), and T7 (`human_checks` in the residual).

### Open

- Proposed (2026-10-15): the tracker query's result in the state block in place of the query, since a cheaper
  overseer skipped the query, stalling new work with no tick failing. This section records the result, nothing more.
- Whether one failed run should raise `connector_failed`, or only one that leaves an observation stale, since each
  transient server error is an item for a tick.
