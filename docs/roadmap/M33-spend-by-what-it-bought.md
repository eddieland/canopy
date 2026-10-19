# M33. Spend by what it bought

Each tick the loop runs records `ticks.idle` and `ticks.woken_by`; `canopy spend [--days N] [--json]` and the web UI's
spend page read them with every run's cost: per UTC day by kind, idle overseer spend as its own series, the ticks by
what they bought and by what woke them, and the runs that reported no cost (DESIGN §11, §22; `core/spend.py`).

Status: done 2026-10-14.
Learned: closed on the operator's request before the day-long live check, which is SCENARIOS S35. One module behind the
command and the route makes them agree by construction, so the check is against the journal. The open questions
settled small: the rail's two counters stay and open the page, and `--json` is in, for a re-measurement to start from.
Next: a re-measurement (MEASUREMENTS) can take idle share and `woken_by` from `canopy spend --json` rather than an
analysis session; a spend budget, if one is built (Deferred), can read the same breakdown.
