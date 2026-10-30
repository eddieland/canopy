# M60. Personas

REQUIREMENTS R24, DESIGN §31, TRUST_MODEL T1, T5, T7, and T8. The `canopy` persona, canopy's voice taken out of the
shipped prompts, and `skeptic`, `minimalist`, and `explainer` beside it; `paths.personas` and `[personas]`, private;
the operator's override per ticket and agent (`canopy persona`, the ticket page), for one run, and per review request;
a run whose persona's file is gone or past its bounds refused, never fallen back; each run's and review's persona and
digest recorded and shown.

Status: done 2026-10-29.
Learned: closed on the operator's own use over a week, several personas chosen and switched between, before the
checks in Accept ran one by one. The refusal of a run whose persona's file was removed was not checked live; it is a
guard in code that the tests with the fakes hold, so by SCENARIOS' bar it is not moved there. Overrides live in
`ticket_overrides`, one table per ticket, agent, and kind, which M58's model override shares.
