# M48. The overseer's tools over MCP

DESIGN §27, D020, D124. The overseer acts through MCP tools canopy serves over stdio, `canopy _mcp` in a tick, in
place of the `canopy` CLI through bash: its verbs are requests and functions in `loop/tools.py`, its definition allows
its tools by name and has no shell but `runtime.allow_bash`, every other definition denies `canopy_*`, a run a tool
starts is spawned through an intermediate and without the entry, and the tick closes `canopy_unavailable` when the
server does not answer `initialize`. A chore reads its own history through `canopy_chore_history`, and the verbs have
left the CLI.

Status: done 2026-10-31.
Learned: closed on real use, at the operator's word, with stage 3's check passed (`make install-check`'s dry tick
decides through `canopy_decide`) and none of the live checks run: stage 0's baseline of bash calls was never measured,
and its tick logs are past `tick_files_days`, so it cannot be now; stage 1b's week of chores and stage 2's day of the
loop are S70 in SCENARIOS, held to 2026-10-13's tool-result tokens instead. OpenCode's source changed the plan: it
signals every descendant of a local server when the run ends, never reads the server's stderr, and times a tool call
out after a minute unless the entry sets `timeout`, and a tool name holds no underscore (§27, What OpenCode does).
Next: structured results as JSON stay open (§27, Open).
