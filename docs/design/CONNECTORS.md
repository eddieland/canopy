# Connectors

Part of the canopy design, normative like all of it: the programs that read the tracker and GitHub into the journal,
and what canopy derives from what they read. Sections are numbered across the whole design; the [README](README.md)
has the map. Previous: [Review replies](REVIEW_REPLIES.md). Next: [Personas](PERSONAS.md).

## 30. Connectors

D003, D008. An overseer re-reading the tracker and GitHub every tick mostly reads what has not changed, and once the
queue settles that is most of canopy's spend (MEASUREMENTS 2026-10-15). So deterministic programs read the world into
the journal, the overseer decides from it, and the harness checks the overseer's claims against it (§7).

A **connector** is a deterministic program that reads one source and prints what it saw as JSON lines. canopy runs it
through `procs`, validates and bounds each line, and records it as an **observation**: a dated copy of a fact about the
world. Authority stays with the source (§4 principle 1, §22): an observation says what a connector saw and when, never
what is true now.

### Sources

There is at most one source of each kind, `tracker`, `vcs`, `artifacts` (an artifact store's comment feed, §38), and
`slack` (the operator's replies in the Slack sink's threads and mentions of its bot, §20), each a command run with
no shell (§20) under a timeout. Every `connect.*` key is private (§12, TRUST_MODEL T7), since each runs a command with
the operator's credentials. The `vcs` source defaults to canopy's own programs (§29), so PRs are observed with nothing
configured. A `tracker` source that reads is required, and config refuses a workspace without one: the overseer
reads no tracker itself (§13), so it could do nothing with a ticket no source observes. There is no default one, since
the harness never branches on `tracker.provider` (§17).

### The contract

On stdin, one JSON object naming what to observe, and a connector reads only what it is given: a `tracker` source the
tracker query and every ticket the state block lists (§6 step 4); a `vcs` source every PR of a ticket not marked done,
with a draft or a review waiting on it (§21, §29), or last observed open, so no observation stays open unread, the
repositories, the branch prefix, and the review query; an `artifacts` source its feed's cursor; a `slack` source the
workspace, which names the sink's threads, and its `operators`, whose replies alone it prints. On stdout, one JSON line
per observation, naming its kind, and last an `end` line naming what the run read whole, or for a feed the cursor its
next run reads from; the exit code is not read. A connector of the operator's own speaks this contract and nothing else:
it is all the harness knows of any of them.

- Ids, states, times, and bounded text; never logs, diffs, PR descriptions, or a credential.
- A connector pages everything before `end` names it: the tracker query to its last page (REQUIREMENTS R1), a PR's
  threads, its head's checks, a watched ticket's blockers, and every branch under the prefix.
- CI is observed by named context, never the combined status, which read green PRs as pending (MEASUREMENTS 2026-10-15).
- A kind the source does not own is skipped, so one source's program never writes another's facts. Unknown kinds and
  fields are ignored, so a newer connector works with an older canopy.

### Validating and the journal

Each line is validated against its kind (D026). Text is cut and marked, as a tracker comment's is (§22); a field whose
cut would change what it says, such as an id or a state, refuses the line instead. A refused line leaves its subject
not whole this run, whatever `end` says, so a line canopy could not read never looks like a review or a check gone. A
run with no `end` line records nothing: without it, canopy cannot tell what is missing from what is not there. A
subject read whole has its observations replaced in one transaction, so what is gone from the source is gone from the
journal; a subject not read whole keeps its old rows and their age. A refused line whose subject canopy cannot read
leaves no subject of its kind whole. A feed is never read whole: each change is read once, past the cursor the last
run's `end` line named, and kept as the newest change to its thread or comment. A refused change holds the cursor before
it, so the next run reads it again and none is missed.

Comments are observed once each, cut and marked, the workers' marks (D069) read in code, and each is recorded in its
ticket's conversation when first observed (§22). The connector moves no cursor and records no decision. §29's reads
after a run and before a send are validated the same way.

### In the tick, and between ticks

In §6 step 3, after the reconciles, the tick runs each source once, the `vcs` source's run being §29's reconcile read;
a tick whose reconcile failed runs none, and a dry run observes as a live tick does. A source that fails, or reads less
than it was asked, keeps its previous observations and raises the harness's `connector_failed` (§14), naming what was
not read, each tick until a run reads everything; the overseer's view of the list leaves it out. The tick goes on: what
was not read ages until it is stale (below), when the harness waits on it and no dispatch rests on it (§7, §37). The
loop's polls between ticks run the same sources the same way and raise nothing (§6).

### What the overseer is shown

- Each subject the state block shows (§6 step 4), a ticket or one of its units, is `fresh`, read whole within
  `connect.max_age_minutes`, whose default keeps what a tick read fresh through its dispatches; `stale`, past it or
  never read, naming what; or `unobserved`, when no source covers it.
  The overseer reads neither world itself (§13): a candidate resting on a stale or unobserved subject is the
  harness's `wait` and is not listed to it (§37), and no dispatch rests on a stale subject (§7).
- Every ticket the block lists or the query returned is a candidate or not by its observed labels and state, decided
  in code (§17); one that is not is shown by key and why, with none of its text (TRUST_MODEL T7).
- A candidate shows what the overseer decides from, its body only until its first unit and its items only past their
  cursors (§7). The harness marks in code whether each comment's author is an authorized replier and whether it is a
  worker's (D069), and whether each review item's author is trusted (D089).
- Each subject shows the rows of §7 the derivation found holding (below), which the overseer may overrule, and each
  query its result as its source last read it whole (§7, §21).
- Source and author are labeled in code, never by a model. A subject shows a fixed number of new items, oldest first,
  and counts the rest, which stay new (§35).

### The derivation

D008 moves a rule from the prompt into code one at a time, on a measurement against the `decisions` corpus (§37):
applied by hand, §7's table disagreed with the overseer on `ci_red` (MEASUREMENTS 2026-10-15).

- Each tick the harness derives, from the observations and the journal, what §7 and §14 derive: the candidates (§17),
  each ticket's and unit's phase, its next action and the actions a choice allows, and the attention reasons. A ticket
  that depends on a stale or missing observation is derived as stale and counted apart, never as a disagreement.
- It records every row of §7 that held, as §7 has no order yet, beside the phase the overseer left each subject at,
  and agrees when that phase is one of the rows and the overseer's decision one that row allows. The overseer is
  shown it (above); by itself it changes no attention item, cursor, phase, or guard.

### Checks that are not CI

Some contexts are not CI: a deploy approval or an ownership sign-off stays pending until a person acts, and a merge
queue's status is never green on an open PR. Counted as CI, one holds a green PR at `ci_running` and never raises
`needs_reviewer`. So each repository gives such a check, by exact name, a role in the map (§18): `human`, `merge`, or
`ignore`; every other is `ci`. A non-CI check never holds a unit at `ci_running`, makes it `ci_red`, has to pass,
becomes a feedback plan's item, or makes a waiting one stale; the overseer is shown a `human` one, as waiting on a
person, and not the others. One left unnamed that stalls a PR long after its other checks finished raises
`check_stuck` (§14), naming it and its key in the map: it only asks, and the role stays the operator's.

- The map names the exceptions, not the CI: a job left off a list of CI would hide a red build, while a check left
  off this one holds a PR where the operator sees it waiting.
- Shared: it is a fact about the repository, and runs, spends, and authorizes nothing (TRUST_MODEL T7).
- Rejected: branch protection's required checks (reading them needs admin, and one can be the human check); a time past
  which a pending check counts as human (a slow build crosses any threshold); patterns of names (one can catch a CI job
  and hide it red).

### canopy's connectors

Each is a uv workspace member importing nothing from canopy (§5), speaks the whole contract, and holds its own
credentials (TRUST_MODEL T2). `canopy-connect-github`, §29's reader, is the `vcs` connector, and given a repository, a
`tracker` connector for GitHub Issues. `canopy-connect-jira` reads Jira Cloud, only at the site the operator names.
`canopy-connect-slack`, beside the Slack sink, is the `slack` connector, with the sink's own bot token file.

What a `slack` source reads is no observation: a reply from one of its `operators`, on a ticket canopy knows, is the
operator's message, recorded as `canopy reply` records one, once per Slack message (§22, TRUST_MODEL T1); the harness
checks the id against config in code, whatever the connector printed. The connector prints no one else's, and a dry
run records none (D036). A `tracker` source's `operators` are tracker account ids: a comment one of them wrote on a
private ticket since its latest start, without the workers' marks, is recorded the same way, as the operator's
message rather than as data, when the source first observes it (§22). A dry run records it too, since the source
reads each comment once.

Rejected: the harness calling the APIs (D003, TRUST_MODEL T2: the process that holds the journal and enforces the
guards never opens a connection or reads a token); an agent as the connector (a model run as a poll, against §4
principle 4, printing a claim, not an observation); MCP servers driven from Python (a client in the harness, and their
credentials with it).

### Open

- Whether one failed run should raise `connector_failed`, or only one that leaves an observation stale.
