# M12. The loop

`canopy loop` (D042, D043): one tick after another, a lock, stops on SIGINT and SIGTERM, and rich output.

Status: done 2026-10-13.
Learned: checked live on 2026-10-07, and the loop has been the operator's daily surface since. Pausing (`p`,
`canopy pause` and `resume`) and reloading config (SIGHUP) joined it on request. A session's legibility and a live
reload are SCENARIOS S26 and S31.
Next: the closing line does not say a signal stopped it; a small follow-up, not a milestone.
