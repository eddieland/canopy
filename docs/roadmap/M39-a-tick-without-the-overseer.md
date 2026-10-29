# M39. A tick without the overseer

DESIGN §39. Needs M38 and M21's overnight run (SCENARIOS S27) with its re-measurement. This is M29's gate without the
trust change: the overseer runs when the journal leaves it something to judge, not when a fingerprint moved.

- When the harness's decisions (M38) leave nothing for the overseer, no ticket and no due chore with a `when`, the
  tick makes the harness's dispatches and closes `ok` with the attention list as it stands, without the overseer: the
  common tick overnight, and after a run ends with nothing to classify. The disk check still holds the dispatches; the
  `canopy` check and the duties go with the overseer. It needs M38's attention list held in code, without which such a
  tick would clear the overseer's items. `ticks` says whether the overseer ran, and M33's spend page and `canopy spend`
  split ticks by it beside `woken_by`, counting a tick without it at nothing, never as a run that reported no cost.
- Connectors poll between ticks: the loop runs them every `connect.every_minutes` (default 2, 2026-10-12 F10) during
  its wait and writes their observations, which M36 built at the operator's request (2026-10-19). What M39 adds: after a
  poll that read every source whole, the harness works out what a tick would record and list, records nothing, and ends
  the wait when that differs from the latest tick: a decision it did not record, or a ticket, a row on one, an item
  past a cursor, or a due chore it did not list to the overseer, compared by what is decided, never by wording. The
  tick records the poll as what woke it. A gate coming due, a run ending, and the operator's acts end the wait as
  today, and `loop.min_gap_minutes` holds every wake. An external event is then seen within one poll, not up to
  `loop.idle_max_minutes` later (M21's trade, lifted).
- Idle pacing paces only the overseer's runs: the timer is its second look at what it was left and waited on, and the
  wait lengthens after each idle tick that ran it; a tick that ran none leaves the count as it was.
- A connector that fails during a poll, or reads less than it was asked, ends the wait once: that tick runs the
  sources again and raises `connector_failed` if they still fail, so a flake the tick's read clears raises nothing.
  Until a run reads every source whole, the polls wake nothing and the loop falls back to today's pacing; the poll that
  reads them whole again ends the wait.
- The overseer's definition loses the tracker and GitHub MCP servers and the provider skill in its body, and denies
  every MCP server but canopy's: it has canopy's tools (M48), or its `canopy` commands until M48's second stage, and
  nothing else, since a `stale` or `unobserved` subject now gets the harness's `wait` instead of a live read, leaving
  M38's list of what the overseer is left. No tick owes `canopy queried`, which the `tracker` source reads. The
  tick-wide `skip` for a server down (`mcp_unavailable`, `tracker_unsupported`) and DESIGN §15's case for it go.
- TRUST_MODEL T1: the overseer can be steered only by text the journal holds, bounded and labeled by source, and can
  call no tracker or VCS tool at all. T3: an early tick is held by `loop.min_gap_minutes`, and one that runs no overseer
  spends nothing. T6: the overseer reaches no server but canopy's. DESIGN §5, §6, §11, §13, §15, §35, and §37, with
  §39 cut to what is left.
- M29's open questions are answered by M36's contract (which subjects to watch), `connect.every_minutes` (how often),
  and M40 (a cold overseer run after a long gap). If M36's measurement leaves the derivation untrusted, so M38 takes no
  row, the series need not stop there for want of M29: a gate on the observations alone (DESIGN §39), ticking only when
  one changed since the last tick, a gate came due, a run ended, or the operator acted, with `loop.idle_max_minutes` as
  its backstop and every tick still running the overseer with its MCP servers, can be taken from M36 without M37 or
  M38.
- Tests with the fakes: a tick whose harness decisions leave nothing, over a journal written by hand, records them and
  its dispatches, closes `ok` with no overseer run, its row marked so at no cost, and the attention list as it was and
  published; a tick with one ticket left, and one with a due chore with a `when`, each runs the overseer; a tick with
  nothing left and too little disk closes `disk_low` and starts nothing; a stale and an unobserved subject each waited
  by the harness, naming what is old, and not listed; the overseer's rendered definition, a snapshot, with no tracker
  or GitHub server, no provider skill, and every MCP server but canopy's denied; a tick whose query no source read
  closes `ok` without `canopy queried`, and a tick-wide `skip` refused; through `scenario` and the fake connector, a
  poll that changes a harness decision ends the wait, no sooner than the minimum gap, with the poll as what woke the
  tick, one that newly lists a ticket, a row, or a new item to the overseer ends it, and one that reads only what the
  latest tick saw, or an edit to an item it saw, ends none; a failed poll ends the wait once, the tick raising
  `connector_failed`, later failed polls end none, and the first whole read ends it again; idle ticks that ran the
  overseer lengthen the wait and ticks that ran none leave it; and `canopy spend --json` and the spend route splitting
  ticks by whether the overseer ran, one without at nothing and not among the runs that reported no cost.

Accept: the tests above pass, and the design (§39) is folded into the sections it names. Live, once built: S27
re-measured (MEASUREMENTS) over a day and a night of `canopy loop` against the real queue, with most ticks running no
overseer, no tick running it with nothing listed to it, overseer spend per day at a quarter of the first day's
(MEASUREMENTS 2026-10-13) for the same queue, median latency from an external event to the tick that acted on it under
three minutes, and no action missed, checked against the derivation as in M36. Once in that run, a source stopped for a
few polls: `connector_failed` raised within a poll, the loop on its timer while it is down, and early ticks again
within a poll of its recovery.

Status: in progress. Designed 2026-10-22 (DESIGN §39); the build waits on M38, and on S27's overnight run and its
re-measurement. The design settles what the sketch left open: a tick with nothing left still runs steps 1 to 3 and the
disk check, owes no duties, and skips the `canopy` check; the poll's comparison counts anything newly listed to the
overseer, not only a new decision, so a reply on a ticket it waited on is seen within a poll; a stale or unobserved
subject is the harness's `wait`; the overseer's tick-wide skip goes with its servers; and a failed poll's item is raised
by the tick it wakes, as a tick's own read raises it (M36's question about one failed run stays M36's). Chosen
conservatively, for the operator to change: every early tick is held by `loop.min_gap_minutes`, as every wake is; a tick
that runs no overseer leaves idle pacing's count as it was; the operator's tick-now runs no overseer with nothing
listed; and the fallback gate keeps `loop.idle_max_minutes` as its backstop. Started 2026-10-23 at the operator's word,
ahead of S27's overnight run, on M38's hold of the overseer's attention items (M38, 2026-10-23). Built (2026-10-23): the
first bullet. After the harness's decisions and the state block, a tick whose block leaves the overseer nothing (no
ticket listed or found by a query the harness recorded, no due chore with a `when`, no query owed, and no review to
start: the review query, an operator's request, or a revision) runs no overseer: it still runs steps 1 to 3 and the disk
check, skips the `canopy` check, owes no duty, makes the harness's dispatches, and closes `ok` with a summary saying so
and the attention list as it stands, the overseer's items held through it (`loop/tick.py`). `ticks.overseer_ran`
(migration 0090) records whether it ran, 0 too for a tick halted before it; `canopy spend`, its `--json`, and the spend
page count a tick without it at nothing, never among the runs that reported no cost, and split each group and each cause
in `woken_by` by how many ran none; `canopy health` names such a tick `no overseer`. Held to the conservative choices
above: every early tick by `loop.min_gap_minutes`; an `ok` tick that ran no overseer leaves idle pacing's count as it
was (`pacing.count`), a halted one resetting it as before; and the operator's tick-now runs no overseer with nothing
listed. Chosen conservatively, for the operator to change: a query due that no source read fresh, and every review the
overseer starts, still leave it something, so a workspace with no `tracker` source and the query due every tick, or with
`review.query` set, ticks with the overseer as before. Built (2026-10-24): the second bullet, and the fourth with it.
After a poll that read every source whole, the loop reads what a tick would record and list, recording nothing
(`loop/outlook.py`): the harness's decisions and dispatches to come, each ticket the state block would list with the
rows of §7 on it and its units, the comments and review items past their cursors it would show, each due chore, and the
review query's PRs. It ends the wait when that holds a fact the latest tick did not, each named by what it is, never by
its text, and the tick it wakes records `poll` in `woken_by`, held by `loop.min_gap_minutes`. A poll that read less than
it was asked ends the wait once, and the tick raises `connector_failed` as any tick does; the polls after it end none
until one reads every source whole, which ends it again. Chosen conservatively, for the operator to change: the latest
tick is read as it ended, not as its block was rendered, so what it started, such as a run the harness then waits on,
wakes nothing; only what is added wakes, so a ticket marked done or a comment a cursor passed does not, nor an item past
a subject's bound until the block shows it; and a workspace with no source wakes on no poll. A run ending is seen by the
next whole poll, since the ticket the harness waited on is then listed, so with idle pacing off it now ends the wait
within a poll too. Settled by the operator (2026-10-28): a `tracker` source is required. Built (2026-10-28): the fifth
bullet's tracker half, where a `tracker` source runs, ahead of config requiring one. A public ticket whose own
observation, or a blocker's, the source left stale or never made is the harness's `wait`, naming what is old, its phase
left as it was, so it is never listed to the overseer (`loop/harness.py`); a query it did not read fresh does not run
that tick and stays due, so no tick owes `canopy queried`, and `canopy queried` and a `tracker_unsupported` skip are
refused; the overseer's definition denies the tracker's server whole, and GitHub's issue reads, and carries no
tracker skill, its skill tool denied (`runtime/opencode/definitions.py`). A workspace with no `tracker` source keeps
the overseer's live reads until config requires one. Chosen conservatively, for the operator to change: a ticket a
query found but the source has not read yet waits a poll for that read; with no tracker server named, by
`tracker.mcp_server` or a provider canopy knows, only GitHub's issue reads are denied. Built (2026-10-28):
the fifth bullet's GitHub half, where a `tracker` source runs beside the `vcs` source, which always does. A candidate
whose unit's PR or branches, its own branches, or an open blocker's PR the `vcs` source left stale or never read is the
harness's `wait`, naming what is old (`loop/harness.py`); the `vcs` request asks for each PR the review query last
found, and the block shows the PRs of the open review requests and the fresh query as read, in
`observations.review_prs`, so the overseer runs no review query; a tick-wide `mcp_unavailable` skip is refused; and the
overseer's definition denies GitHub's PR, branch, and user reads by pattern, and on a GitHub tracker its server whole.
Chosen conservatively, for the operator to change: a review PR's checks are all counted as CI, since which repository
it is in is the overseer's to match; a blocker not listed to the overseer is not stacked on; and off a GitHub tracker
GitHub's server is denied by its tools' names, its own name being the operator's. Built (2026-10-29): the third bullet.
The count was already the overseer's alone; what was left was a tick a poll woke, which counted as idle and lengthened
the wait after it. It is idle no more (`pacing.idle`): a poll wakes the loop only for what is new, so the wait lengthens
after the overseer's second looks at what it was left and waited on, which the timer brings, and not after its first
look at what a poll found. Chosen conservatively, for the operator to change: a failed poll's wake, and the whole read
after one, count as any poll's; the operator's tick-now counts as before. Built (2026-10-29): §30's `tracker` connector
for GitHub Issues, `canopy-connect-github --repo OWNER/NAME` (`canopy_github/issues.py`), so a workspace on GitHub
Issues has a source to require: `GH-N` is issue N, read as `canopy-connect-jira` reads Jira's. Chosen conservatively,
for the operator to change: a blocker is an issue dependency or a `Blocked by #N` line of the body, either; a ticket an
open issue of another repository blocks, which no key names, is not read whole, so it stays stale; and a query that
returns another repository's issue is not read. Built (2026-10-29): config requiring a `tracker` source, one with a
`cmd` that reads, a workspace without one refused with what to add (`core/config.py`), so every live tick takes the
observed path above; the tests' workspaces run the fake connector as theirs, holding every ticket they work open and
labeled. The overseer's definition loses the tracker's skill and read tools on every path. Chosen conservatively, for
the operator to change: `canopy init` writes the table commented out, since only the operator knows their site or
repository and a guess would send their credentials to someone else's, so a new workspace's config does not load, nor
`canopy init` clone its repositories, until they fill it in. Built (2026-10-29): the harness's `wait` on an unobserved
subject. A candidate with a unit whose PR URL names no PR, which no source reads, is the harness's `wait`, saying no
source reads it, and is never listed to the overseer; so is one the `tracker` source read before canopy held it, such as
one the query found that was read as another's blocker, whose comments it never recorded, until a read since, as the
block already counted it stale (`loop/phases.py`, `loop/harness.py`). A ticket, blocker, PR, or repository's branches
with no observation at all was already waited as stale. Built (2026-10-29): an item for that wait, as the operator
decided, so it never sits silent. The harness raises `unobserved_pr` about such a unit, naming its repository and the
URL that names no PR, while its ticket is held; it goes once the unit names a PR, the operator forgets the ticket's
work, which drops its units, or the ticket is done, stopped, or seen closed or unlabeled, and the overseer is refused
it (`raised`) as it is the harness's other items (`loop/harness_items.py`). Chosen conservatively, for the operator to
change: a closed or unlabeled ticket is still decided without its PRs; and a review's PR not read fresh stays the
overseer's `canopy_review-wait`, taken from the read, not a live one. The tests' fake worker reports a PR no source
reads, so a story that needs the overseer listed a ticket with a PR gives it one the fake `vcs` source reads, and one
whose sink must hear no new item has its worker report none. Built (2026-10-29):
the paths config left unreachable removed. `canopy queried`, its tool, and the duty that owed it are gone, the harness
recording the `tracker` source's read of the query as before; every decision names its ticket, so the tick-wide `skip`
and DESIGN §15's case for it are gone, and no tick closes `skipped`; the state block has no `query_due`, and the
overseer's prompt no live read of the tracker or GitHub, only the observations, an unobserved subject its `wait`; and
the loop's branches for a workspace with no `tracker` source, the comment cursor kept as the tracker's id among them,
are gone (`loop/tick.py`, `loop/tools.py`, `loop/observations.py`, `loop/phases.py`). Kept for the journal's history:
the `queried` decision, which the harness still records and `duties.last_queried` reads from an older release's ticks
too; `TickStatus.SKIPPED`, which old ticks hold; and the `last_comment_id` column, no longer read. Built (2026-10-29):
every MCP server but canopy's denied. The overseer's definition denies `*_*`, every tool OpenCode names
`<server>_<tool>`, whatever the operator's runtime config grants, and `read` of any server's resources, before it allows
canopy's tools by name; nothing of the tracker's config is rendered into it, so none can reopen a server
(`.agents/agents/canopy-overseer.md`). Read from OpenCode 1.19.3's source: no built-in tool the overseer uses asks a
permission with a `_`. Left: the design folded into the sections it names.
Still open for the operator: whether `runtime.allow_bash`'s overseer entry goes with its MCP servers (recommended: yes,
and that entry with it), the fifth bullet's.
