# M28. Overseer reliability from the first live session

A check that the overseer's `canopy` works before the overseer runs, the `CANOPY_TICK_DONE` line anywhere in the final
message, starts and grants ending the loop's wait, churn in the `loop waits` line, and the overseer's open attention
items in its state block.

Status: done 2026-10-14.
Learned: closed on the operator's request before the live re-measurement, which is SCENARIOS S34. A check beat putting
canopy's launcher first on PATH, which misses a launcher whose environment is gone (DESIGN §6 step 5). The first day's
churn was the overseer dropping items it could not see, fixed in the prompt (DESIGN §6 step 4).
Next: M39 waits on S27's overnight run.
