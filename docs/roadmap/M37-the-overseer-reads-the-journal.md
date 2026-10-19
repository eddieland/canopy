# M37. The overseer reads the journal

Needs M36's measurement, with the disagreements that were the derivation's fixed, and M48's second stage. Sketch
only; the design comes first. This is M30's cut, taken from the journal rather than a probe, and it is where the trust
model gains its first code checks on what the overseer claims.

- The state block carries the observations: per ticket, its title, state, labels, blockers, and the comments newer
  than its comment cursor (id, author, time, body, and whether the author is an authorized replier, decided in code);
  per unit, its PR (state, head, base, draft, mergeable), each named check at the head, and the reviews and review
  comments newer than its review cursor (author, trusted or not, decided in code, body); and the derived phase of
  each, as the harness's reading. Bounded text, labeled by source and author in code, after the fixed sections
  (M34's order).
- The prompt's procedure drops its reads: no tracker search, no ticket or PR reads, no mirror, no provider skill.
  An MCP call is allowed only for a subject the block marks `stale`, one no connector has covered within
  `connect.max_age_minutes`; M39 removes that too.
- Claims become references to observations, checked in code: `canopy dispatch --label` is refused `unauthorized`
  unless the connector saw that label on the ticket (D051 gains a code check before the worker's own); a
  `human_replied` resume must name a comment by an authorized replier or an operator message; a `resume` for review
  feedback must name items by trusted reviewers, or an operator message about them (D089's revisit); `--cursor` must
  name an observed item. `canopy dispatch` is refused `stale` when a subject it depends on has an observation older
  than `connect.max_age_minutes`: a public ticket's, and the PR's of a unit a `resume` names. It covers
  only subjects a connector observes: a private ticket, authorized by its start record, a chore, and a subject no
  connector covers are not refused. Principle 1's "re-read before any action that matters" becomes "observed this
  tick, or no dispatch".
- Cursors become journal ids: observations order reviews, review comments, and canopy's review runs together, so the
  `review` cursor's time form (§7) is no longer needed. CI is keyed on head sha, context, and run id, so a re-run at the
  same head is observed, as resolving a held check needs (M35, 2026-10-13 F16); a `resume` for `ci` alone starts only
  when a context's conclusion changed at that head, never on a re-run that went red to red (PRIOR_ART).
- The `mirror` tool is retired (M48 retired the heredoc, D081): the tracker connector writes comments. Open: whether
  a tracker with no connector keeps the live-read procedure, or a connector is required (recommended: required; the
  two shipped cover the operator's trackers, and the contract is a page of Python for another).
- TRUST_MODEL T1 (labels, repliers, and reviewers checked in code; the overseer's MCP narrowed to stale subjects),
  T2 (a connector's credentials), T7 (`connect.*`); DESIGN §6, §7, §17, §22; D003 edited in
  place (M48 superseded D081).

Accept: written with the design, before work starts. Live, once built: a re-measurement (MEASUREMENTS) with
tool-result tokens per tick at a tenth of the first day's median (about 14k), no MCP call on a tick whose
observations are fresh, and no action missed over a day, checked against the derivation as in M36.

Status: not started.
