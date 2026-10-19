# M31. Search in the web UI

One box over tickets, messages, chore runs, decisions, and ticks (`core/search.py`).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the timed check is SCENARIOS S32. A plain `LIKE` scan was measured fast
enough, so there is no FTS5 index.
Next: FTS5 when a real journal's empty search takes more than a quarter of a second (DESIGN §22, Search).
