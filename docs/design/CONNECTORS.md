# Connectors

Part of the canopy design, normative like all of it: the programs that read the tracker and GitHub into the journal,
and what canopy derives from what they read. Sections are numbered across the whole design; the [README](README.md)
has the map. Previous: [Review replies](REVIEW_REPLIES.md).

## 30. Connectors (M36)

ROADMAP M36, D003, D008. The overseer reads the tracker and GitHub again every tick, through MCP, and most of what it
reads has not changed since the tick before (MEASUREMENTS 2026-10-12 F6, 2026-10-13 F14); once the queue settles, that
watching is most of canopy's spend (2026-10-15 F21). The operator asked (2026-10-14) for each tick to run from journal
state, read into it by deterministic programs. ROADMAP M36 to M39 take that one step at a time, and this section is the
first: canopy reads the world into the journal and derives in code what §7 and §14 derive, beside the overseer, which
sees and does nothing different. M37 gives the overseer the observations, M38 moves into code the rows the derivation
gets right, and M39 runs the overseer only when something is left to judge; each gets its own design.

A **connector** is a deterministic program that reads one source and prints what it saw as JSON lines. canopy runs it
through `procs`, validates and bounds each line, and records it as an **observation**: a dated copy of a fact about the
world. Authority stays with the source (§4 principle 1, §22): an observation says what a connector saw and when, never
what is true now. In this section nothing reads an observation to decide anything; the derivation reads them, and only
the operator and the measurement read the derivation.

### Sources

```toml
[connect]
max_age_minutes = 30         # an observation older than this is stale
every_minutes = 2            # how often ROADMAP M39's loop polls between ticks

[connect.sources.github]     # unset: canopy's own GitHub programs (§29)
kind = "vcs"
cmd = "canopy-connect-github"
post_cmd = "canopy-post-github"
timeout_minutes = 2

[connect.sources.jira]       # optional; there is no tracker source unless the operator names one
kind = "tracker"
cmd = "canopy-connect-jira --site acme.atlassian.net"
timeout_minutes = 2
```

- `[connect.sources]` is §29's table, unchanged: a command split into words as a sink's is (§20), run with no shell,
  its request on stdin, a timeout, and at most one source of each kind, `tracker` and `vcs`. Every `connect.*` key is
  private (§12, TRUST_MODEL T7), since each runs a command with the operator's credentials. M36 adds no kind: a source's
  `cmd` becomes its connector, which this section grows from §29's reader of review threads into a reader of every
  kind its source owns.
- The `vcs` source defaults to canopy's own programs, as §29 says, so a tick observes PRs with nothing configured, for
  one GraphQL query a tick (2026-10-15 F29). A workspace on another host names its own. There is no `tracker` source by
  default: the harness never branches on `tracker.provider` (§17), so the operator names the connector for their
  tracker. Without one, tickets are not observed, and the derivation says so (below).
- `connect.max_age_minutes`, default 30, at least `every_minutes`: an observation older than this is stale. The
  derivation reads it now, and ROADMAP M37's dispatch guard will. 30 is longer than a tick's overseer may run (§12's
  `overseer_timeout_minutes`, 15), so what a tick observed before its overseer started is fresh through its dispatches.
- `connect.every_minutes`, default 2 (2026-10-12 F10), at least 1: how often M39's loop runs the connectors during its
  wait. Nothing reads it before M39; it is defined here so the series has one config model from the start.

### The contract

On stdin, one JSON object naming what to observe. Every key is optional and a connector reads only what it is given,
so §29's `{"prs": [...]}` is one such request:

```json
{"query":"project = PROJ AND statusCategory != Done",
 "tickets":[{"key":"PROJ-12","comments_since":"2026-10-19T09:12:00Z"}],
 "prs":["https://github.com/acme/api/pull/7"],
 "repositories":[{"name":"api","url":"https://github.com/acme/api.git"}],
 "branch_prefix":"agent/","review_query":"is:pr is:open review-requested:@me"}
```

- A `tracker` source is sent `query`, `tracker.query` as configured, and `tickets`: every ticket the state block lists
  in `tickets` (§6 step 4), public and private, each with the time of the newest tracker comment the journal holds for
  it, so the connector prints only what is newer, or every comment when it holds none.
- A `vcs` source is sent `prs`, every PR on a unit of a ticket not marked done, merged and closed included (2026-10-13
  F16), and every PR a draft waits on (§29); `repositories`, the map's names and clone URLs, each URL's credential
  dropped; `branch_prefix`, `trust.branch_prefix`; and `review_query`, `review.query`, when set.

On stdout, one JSON line per observation, each naming its `kind`:

| Kind | Source | What it carries |
|---|---|---|
| `ticket` | tracker | key, title, body, open or closed, labels each with when it was last added where the tracker says, updated at, blocker keys |
| `comment` | tracker | ticket, id, author account id, time, body |
| `pr` | vcs | url, repository, number, head sha, base ref, open, merged, or closed, draft, mergeable, mergeable state, author login, labels |
| `branch` | vcs | repository, name, head sha |
| `check` | vcs | pr, head sha, context name, status, conclusion, run id, url |
| `review` | vcs | as §29: pr, id, review or review comment, author login, whether a bot, state, time, body, url; a comment's review and thread, and whether that is resolved or outdated |
| `end` | either | what the run read whole (below) |

- Ids, states, times, and bounded text; never logs, diffs, PR descriptions, or PR issue comments, none of which a
  decision used (2026-10-15 F28).
- A connector pages everything it reads before its `end` line names it: the tracker query to its last page
  (REQUIREMENTS R1), a PR's threads, and its head's contexts past the first page of 100.
- CI is observed by named context, every check run and commit status at the head, never the combined status, which
  read every green PR as pending and stops at 30 contexts (2026-10-12 F9, 2026-10-15 F25). A context's status and
  conclusion are words of a closed vocabulary the contract lists, onto which the connector maps its host's.
- A ticket a watched ticket names as its blocker is printed too, one level deep, whether or not the query returns it,
  and every branch under the prefix in each repository, so a pushed branch with no PR and a PR the journal has no unit
  for are observed (2026-10-15 F28).
- The last line is `end`, naming what was read whole: `tickets`, `prs`, and `repositories` it read in full, and
  `query` and `review_query` as the keys and URLs each returned, in order, absent when not read to the end. A ticket is
  whole with its comments since the time asked, a PR with its checks and reviews, a repository with its branches.
- The exit code is not read: the `end` line alone says what was read. A connector never prints a credential, on
  either stream.

Unknown kinds are skipped, and so is a kind the source does not own, such as a `pr` from a `tracker` source, so one
source's program never writes another's facts. Unknown fields are ignored, so a newer connector works with an older
canopy. A connector of the operator's own speaks this contract and nothing else: it is all the harness knows of any of
them.

### Validating and bounding

Each line is validated against its kind (pydantic, D026) before anything is written.

- Text is cut and marked, as a mirrored comment's is (§22): a body at 2000 characters, a title at 200 and on one line.
  A field whose cut would change what it says refuses the line instead: an id, key, login, or name that does not match
  its pattern (a ticket key as §17's, a branch as plain ref components under the prefix, a PR URL as §29's reader
  takes one); a time that is not ISO 8601, read as UTC without an offset; a state outside its vocabulary; more than 100
  labels or blockers, since a list cut short reads as a label removed.
- A line over 1 MiB is refused, and output past 16 MiB ends the read as cut off.
- A refused line is logged and counted, the rest of the output is kept, and the refused line's subject is not whole
  this run, whatever `end` says: a line canopy could not read never looks like a review or a check gone.
- A run with no `end` line, one that times out, or one whose command does not start records nothing and is `failed`.
  Lines printed before the cut are not applied: without `end`, canopy cannot tell what is missing from what is not
  there.

### The journal

- One table per kind: `observed_tickets`, `observed_prs` and `observed_reviews` (§29's, `observed_prs` gaining labels
  and mergeable state), `observed_checks`, and `observed_branches`. Each row is keyed by the source's id and carries
  when it was observed. A subject read whole has its rows replaced in one transaction, so a label, check, review, or
  branch gone from the source is gone from the journal; a subject not read whole keeps its old rows and their age.
- Comments go into `messages` as mirrored comments do (§22): once per ticket and comment id, channel `tracker`, source
  `worker` when they carry the workers' marks (D069), read in code. The connector moves no mirror cursor and records no
  decision, so the overseer mirrors as before, and its mirror of a comment the connector recorded records nothing new.
  A comment edited after it was recorded is not updated, as now.
- The `query` and `review_query` results are recorded with the run that read them whole.
- `connector_runs` records each run: its source and kind, when it started and ended, its status (`ok`; `partial`, when
  it read less than it was asked; `failed`), the lines recorded and refused of each kind, and the last 300 characters
  of its stderr.
- A dry run observes as a live tick does: reading changes nothing in the world, and a mirrored comment is recorded in
  a dry run already (§22).
- `connector_runs` and `derivations` gain a row or more every tick; §26's pass removes them under the rule it applies to
  the harness's attention rows. Observations are replaced, so they do not grow with ticks.

### In the tick

In §6 step 3, after the runs, slots, chores, and reviews are reconciled and before the harness's items are recorded,
the tick runs the `tracker` source, then the `vcs` source, each once, each within its own timeout. A tick that closes
`reconcile_failed` runs neither. The `vcs` run is also §29's reconcile read: its request names every PR a draft waits
on, and each draft is checked against it as §29 says.

A source that fails, or reads less than it was asked, keeps its previous observations, is logged, and raises the
harness's `connector_failed` (§14), recorded as `repo_missing` is, each tick its latest run did not read everything
asked. The item is about the source and shown under its name; its detail names what was not read, with the tail of
stderr, and its cause is gone at the first run that reads everything. The overseer's view of the list leaves it out, as
it does every harness item (§6 step 4). The tick goes on, and in this milestone loses nothing, since the overseer still
reads live.

The derivation follows, before the state block is rendered.

### The derivation, in shadow

D008 moves a rule from the prompt into code one at a time, each checked against the `decisions` corpus first. Applied
by hand to three days of decisions, §7's table agreed with the overseer on 92.8%, and on nearly every row that is a fact
alone, but `ci_red` differed on 61 of 65, on facts the overseer used and the first contract left out (2026-10-15 F26
to F28). So the derivation runs beside the overseer first, and the measurement that closes M36 says which rows M38 may
take.

- Each tick the harness derives, in code (`loop/phases.py`), from the observations and the journal (runs, cursors,
  attempt limits and cooldowns, notices, plans, splits, starts, operator messages), what §7 and §14 derive: the
  candidates, by §17's rule, from the query's result and the tickets the journal holds; each ticket's and unit's
  phase; its next action; and the attention reasons the facts give.
- §7 does not yet order its rows (M38 puts the order there), so the derivation records every row that holds, and the
  measurement counts how often more than one did. Where a row's next action is a choice, such as `resume` or
  `needs_author` for `changes_requested`, a `ci_red` with a notice in force or past (§8), or the repository for
  `ready`, the derivation records the actions it allows.
- A ticket that depends on a subject whose observation is stale or missing (no `tracker` source, or a run that did not
  cover it) is derived as `stale`, naming the subject, and counted apart, never as a disagreement. A private ticket's
  own phases come from the journal (§7), so it needs no tracker observation.
- The derivation is recorded per tick in `derivations`, beside `decisions`. It writes no decision, and it changes no
  state block, attention item, cursor, phase, or guard.
- Once the overseer has run, its tick's derivation is compared with what it recorded for each ticket and unit: its
  phase (`canopy ticket set --phase`) and its decision (`wait`, `done`, a dispatch's kind and reasons, an attention
  reason). They agree when the phase is one of the rows that held and the decision one that row allows. Agreement is
  computed from the two tables, never stored, so a fix to the comparison reads every tick already recorded. The loop's
  per-tick block (§6) prints how many differ, by row, and its `loop waits` log line carries the count. A tick whose
  overseer did not run, or failed, is not compared.

### Checks that are not CI

Some contexts stay pending until a person acts, a deploy approval or a sign-off, and counting one as CI holds a green
PR at `ci_running` for as long (2026-10-12 F9, 2026-10-15 F28). Each repository names them in the map (§18):

```toml
[repos.api]
url = "https://github.com/acme/api.git"
human_checks = ["deploy/approval", "Product sign-off"]
```

- Context names, matched in full and by case, as the connector prints them. A listed context is not CI: it does not
  hold a unit at `ci_running`, make it `ci_red`, or have to pass for it to be green. It is still observed and shown.
- The list names the exceptions, not the CI. A repository has a median 52.5 contexts a head (2026-10-15 F25): a new
  job left off a list of CI would hide a red build, while a new human check left off this one holds a PR at
  `ci_running`, where the operator sees it waiting. Missing an entry fails toward waiting.
- Shared, beside `summary` and `branch_url`: which checks wait on a person is a fact about the repository, the same for
  everyone who works on it, and the list runs nothing, spends nothing, and authorizes no one. A hostile edit could list
  a real CI job, which the derivation would then never read as red; branch protection still holds the PR (TRUST_MODEL
  §7), and T7's residual says so.
- In M36 only the derivation reads it: the overseer still reads every check live. M37's state block carries it with the
  observations.
- Rejected: a list of the CI contexts (above); a repository's required checks from branch protection (reading them
  needs admin on the repository, and a required check can be the human one); a time past which a pending check counts
  as human (a slow build crosses any threshold, and the phase would flip under it); a private key (the list is the
  repository's, and every operator would keep a copy).

### `canopy status`

`canopy status` names each source with its kind, when its last run ended and how, and the age of the oldest observation
of a subject canopy still asks it about, marked stale past `connect.max_age_minutes`.

### canopy's connectors

Each is a uv workspace member under `packages/`, stdlib only and importing nothing from canopy, as the Slack sink and
§29's programs are (§5), linted out of the harness, with a fake for the tests.

- `canopy-connect-github`, §29's reader, becomes the `vcs` connector: every watched PR in one GraphQL query a run, not
  REST calls per PR, which would cost 15 to 18 times the overseer's MCP calls today (2026-10-15 F29), paging a PR's
  contexts and threads before its `end` line names it; each repository's branches under the prefix; and
  `review_query` as a search. Given the repository its issues live in, it is also a `tracker` connector for GitHub
  Issues. It reads `gh`'s token for the host a URL names, as §29 says.
- `canopy-connect-jira`, a new member: Jira Cloud's REST API at the site its argument names, the query in JQL, with an
  email and API token from an operator-only file (default `~/.config/canopy/jira-token`) held to the checks the Slack
  sink's token file is (§20), sent only to that site, and never in canopy's config, argv, journal, or logs.
- Another tracker is the operator's program speaking the contract.
- Rejected: the harness calling the APIs (D003: the process that holds the journal and enforces the guards never opens
  a connection or reads a token, TRUST_MODEL T2); an agent as the connector (a model run a poll, against §4 principle
  4, and what it prints is its claim, not an observation); MCP servers driven from Python (a client in the harness,
  and their credentials with it).

### What the building PR changes

To be approved by the operator in merging the PR that builds the connectors:

- D003 is reshaped: the harness imports no tracker or VCS client and holds no token; it reads the world only through
  connectors, separate programs it runs as commands speaking this contract, and agents still reach the tracker and
  GitHub through MCP. Its revisit is what this section does.
- AGENTS.md's "a tracker adapter interface" line (Do not build) allows this contract, and its Toolchain line names the
  Jira connector beside the GitHub programs.
- §3's tracker non-goal, §4 principle 5, and §17 say the tracker is reached through MCP and connectors, with no
  tracker code in the harness. §6 step 3, §11, §12 (the keys above and `human_checks`), §14 (`connector_failed`), and
  §26's table change as this section says.
- TRUST_MODEL T1: comments a connector records are data, as mirrored ones are, and authorize nothing; in this milestone
  no observation decides anything. T2: the Jira connector reads its credentials file and calls only its site, and the
  GitHub connector's reads widen to issues, branches, and checks, with `gh`'s token as before. T7: `human_checks`
  joins the residual.

### Open

- Proposed (2026-10-15), for the operator to settle: the tracker connector's query first, on its own, as the one part
  of M36 that changes what the overseer does. Run in code each tick, its result, less `recently_done` (§7), would be in
  the state block as the tickets to read in place of the query, the overseer running the query itself only on a tick
  whose run failed or is older than `connect.max_age_minutes`; a cheaper overseer skipped the query, which stalls new
  work with no tick failing (2026-10-15 F31, §7). This design records the query's result every tick, which that needs,
  and builds nothing more of it.
- Whether one failed run should raise `connector_failed`, as above, or only a run that leaves an observation stale:
  over three days the GitHub server answered 503 six times (2026-10-15 F29), each an item for one tick, and to every
  sink that takes `attention`.
