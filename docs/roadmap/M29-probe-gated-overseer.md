# M29. Probe-gated overseer

A `probe_cmd` that fingerprinted tickets and PRs, so the overseer ran only when one changed, the loop was woken, a gate
came due, or `loop.idle_max_minutes` passed (MEASUREMENTS 2026-10-12 F7 to F10).

Status: superseded by M36 to M39 (2026-10-15). M36's connectors observe into the journal every fact the probe would
have fingerprinted, and M39 runs the overseer only when those observations leave it something to judge.
