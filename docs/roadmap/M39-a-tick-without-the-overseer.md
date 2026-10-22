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

Status: not started. Designed 2026-10-22 (DESIGN §39); the build waits on M38, and on S27's overnight run and its
re-measurement. The design settles what the sketch left open: a tick with nothing left still runs steps 1 to 3 and the
disk check, owes no duties, and skips the `canopy` check; the poll's comparison counts anything newly listed to the
overseer, not only a new decision, so a reply on a ticket it waited on is seen within a poll; a stale or unobserved
subject is the harness's `wait`; the overseer's tick-wide skip goes with its servers; and a failed poll's item is raised
by the tick it wakes, as a tick's own read raises it (M36's question about one failed run stays M36's). Chosen
conservatively, for the operator to change: every early tick is held by `loop.min_gap_minutes`, as every wake is; a tick
that runs no overseer leaves idle pacing's count as it was; the operator's tick-now runs no overseer with nothing
listed; and the fallback gate keeps `loop.idle_max_minutes` as its backstop. Open for the operator: whether a `tracker`
source is required, M37's question, which this needs settled (recommended: required, before the build), and whether
`runtime.allow_bash`, the overseer's alone, goes with its MCP servers (recommended: yes, and the key with it).
