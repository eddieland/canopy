# M65. Running agents say where they stand

REQUIREMENTS R6, DESIGN §41, TRUST_MODEL T1, T3, and T4. Workers, planners, and reviewers report where their work
stands while they run: a card the agent rewrites whole through canopy's `status` tool, which the harness records from
the events it already reads, with steps, their share done, and a stuck step; canopy's plugin asks for an update once a
card lapses; the card and its age show in `canopy status`, `canopy show`, and the web UI; and a card's question, with
lettered options and the agent's recommendation, is answered with a letter the agent hears on its next tool call.

Status: done 2026-11-11.
Learned: closed on the operator's own use, before the checks in Accept ran one by one; a card's question answered in a
sandboxed run and an unsandboxed one is SCENARIOS S79. Stage 0's source read found that a tool call's whole input is
printed as the call ends, not at the session's end, so the server writes nothing, and that OpenCode's own `todowrite`
has no `blocked`, stage, or proof, so steps are canopy's. An answer is a letter, never words, so a forged `[canopy]`
line can choose only one of the agent's own options. The week's measurement (MEASUREMENTS "2026-11-10: M65, how often
running cards went stale") had a card lapse at least once on 52% of `implement` runs and end stale on 18%, with no
threshold set.
Next: the answers directory is the channel M68's messages use.
