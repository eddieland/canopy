# M34. A cacheable overseer prompt

The overseer's fixed prompt and its tracker's skill are the body of its agent definition in canopy's snapshot, where
the runtime caches them across ticks, and a tick's message is the state block alone; a prompt override gets a snapshot
of its own (DESIGN §6 step 4, §13).

Status: done 2026-10-15.
Learned: closed on the operator's request with the tests with the fakes passing, before the live measurement; the
before and after cache check and the 15% re-measurement are SCENARIOS S33. Measured since (MEASUREMENTS 2026-10-15
F23): a warm tick's first step cost 57% less, 15% of the tick, as predicted, but most ticks were cold, at the base
interval and through the night, so the realized saving was about 3%.
Next: M37's state block grows with the connectors' facts, so S33 is worth running again once it lands.
