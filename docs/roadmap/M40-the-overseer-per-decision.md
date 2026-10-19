# M40. The overseer per decision

Needs M39. Sketch only, and taken only if M39's re-measurement shows the state block's size still dominating what the
overseer spends: M34's cache hit needs ticks minutes apart, which M39 makes rarer, so each remaining run may be cold.

- One overseer run per ticket left to judgment, whose message is that ticket's observations alone: a cold run writes
  a few thousand tokens, not fifty, and text on one ticket cannot steer a decision about another.
- The harness orders dispatches across tickets by phase priority (§7's order, written there by M38), which today
  the one overseer does, and bounds the runs per tick by capacity.
- Open: whether runs go in parallel; chores' `when`, which needs no ticket; whether one run may still see the queue;
  a model per run, chosen by the ticket's phase: the strongest for `ready`, review feedback, and a free-text reply,
  a cheaper one for the rest. That is a split overseer's saving without two standing overseers, whose split by job
  buys only the cheaper model's price, since finding new work was 0.2% of overseer spend (2026-10-15 F31).

Accept: written with the design, before work starts.

Status: not started.
