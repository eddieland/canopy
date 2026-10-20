# M39. A tick without the overseer

Needs M38 and M21's overnight run (SCENARIOS S27). Sketch only; the design comes first. This is M29's gate without the
trust change: the overseer runs when the journal leaves it something to judge, not when a fingerprint moved.

- When the harness's decisions leave nothing for the overseer, no ticket and no due chore, the tick records them,
  closes `ok`, and does not run the overseer: the common tick overnight, and after a run ends with nothing to
  classify. `ticks` says whether the overseer ran, and M33's spend page splits ticks by it.
- Connectors poll between ticks: the loop runs them every `connect.every_minutes` (default 2, 2026-10-12 F10) during
  its wait and writes their observations, which M36 built at the operator's request (2026-10-19). What M39 adds: it ticks
  early when the derivation over them yields a decision the latest
  tick did not record, a gate comes due, or the operator acts, as today. An external event is then seen within one
  poll, not up to `loop.idle_max_minutes` later (M21's trade, lifted). Idle pacing paces only the overseer's runs. A
  connector that fails during a poll raises `connector_failed` and the loop falls back to today's pacing.
- The overseer's definition loses the tracker and GitHub MCP servers: it has canopy's tools (M48) and nothing else,
  since a `stale` subject now gets `wait` instead of a live read. TRUST_MODEL T1: the overseer can be steered only by
  text the journal holds, bounded and labeled by source, and can call no tracker or VCS tool at all.
- M29's open questions are answered by M36's contract (which subjects to watch), `connect.every_minutes` (how often),
  and M40 (a cold overseer run after a long gap). If M36's measurement leaves the derivation untrusted, the series
  need not stop there for want of M29: a gate on the observations alone, running the overseer only when one changed
  since its last run, a gate came due, or the operator acted, can be taken from M36 without M37 or M38.

Accept: written with the design, before work starts. Live, once built: S27 re-measured (MEASUREMENTS) with most ticks
running no overseer, overseer spend per day at a quarter of the first day's for the same queue, median latency from
an external event to the tick that acted on it under three minutes, and no action missed.

Status: not started.
