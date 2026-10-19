# M21. Idle-paced loop

The wait doubles per idle tick up to `loop.idle_max_minutes`, ends by a cooldown or a chore's due time, and ends early
when a run ends (DESIGN §6, Idle pacing).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the overnight run is SCENARIOS S27. Ticks that fail after doing their work,
and overseer churn, keep a quiet night from backing off (MEASUREMENTS 2026-10-12), which M28 takes. A shorter `--every`
keeps idle pacing from that base.
Next: M39 waits on S27's overnight run and its re-measurement.
