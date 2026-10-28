# M48. The overseer's tools over MCP

DESIGN §27, D020, D081. Asked for by the operator (2026-10-16): the overseer acts through MCP tools canopy serves,
not by running the `canopy` CLI through bash. Needs nothing; taken before M37, so that M37 and M38 rewrite the
overseer's prompt once, against tools. Workers are out of scope (§27, Why). Five stages, in order, each in its own
PRs, a stage starting only once the one before has passed its check, recorded on the `Status:` line.

**Stage 0, measure and read.** Nothing is built.

- From the operator's tick logs, a dated section of `MEASUREMENTS.md`: the overseer's bash calls per tick, and how
  many failed on usage, quoting, or a refused command. That is the baseline stage 2 is held to, and if such failures
  are rare, the operator decides whether the rest is still worth building.
- From OpenCode's source, as §24 read it: the inline config's form, how it merges with the operator's and the
  workspace's, whether it reaches OpenCode's children, what a run does when a local server fails to start, and the
  protocol versions its client asks for.
- Check: both written down; §27's "How the overseer gets them" revised first if OpenCode differs from it.

**Stage 1, the server.** Nothing the overseer runs changes.

- The overseer's verbs move below `cli/` into `loop/tools.py`, each a function over a pydantic request model that
  holds §6's bounds and the rules across fields; the click commands build the request and call it. The CLI's tests
  pass unchanged.
- `canopy _mcp` in `loop/mcp.py` (§27, The server): the five methods, one tool per verb, refusals as tool errors,
  nothing listed or served outside a running tick or under `CANOPY_RUN_ID`.
- `procs` gains a way to remove a variable from a child's environment, for the entry's, and a spawn through an
  intermediate that exits at once, so a run a tool starts is never the server's descendant, which OpenCode stops
  with it (§27, What OpenCode does).
- A DECISIONS entry: canopy serves MCP itself, over stdio only, to the overseer only; the `mcp` SDK rejected.
- Tests: a stdio client in `tests/canopy/helpers.py` drives `canopy _mcp` inside a tick. Each tool records what its
  command records, a refusal is `isError` and the server keeps serving, an unknown field is refused, and no tool is
  listed outside a tick or with `CANOPY_RUN_ID` set. One parameterized test sends each refusal through both a tool and
  its command. A spawned run's environment lacks a removed variable, and a run spawned from the server is not its
  descendant and outlives it. The server writes nothing to stderr, and exits when its stdin closes.
- Check: `make check`, and a hand-run `canopy _mcp` in a dry tick answering an OpenCode client.

**Stage 1b, a chore trials the server.** The operator's call (2026-10-21): an agent with fewer responsibilities than
the overseer is given the server first. Nothing the overseer runs changes.

- Every chore's one command, `canopy chore history`, is also a tool, `canopy_chore_history`, scoped to that chore's own
  runs: one request and one function (`chores/history.py`) that the command and the tool share, the same bounds and the
  same refusal of another chore's history. `canopy _mcp --chore` lists and serves that tool alone, only where
  `CANOPY_RUN_ID` names a chore's run; the overseer's tools are still served only inside a tick and never in a run.
- A chore run's environment carries the server's inline-config entry and code mode off, as stage 2 gives the overseer;
  every run canopy starts drops both first. `canopy-chore` allows the tool by exact name and loses its shell; every other
  definition denies the tool. The example chores' agents allow it too and keep their shell for canopy's read-only
  commands. The `## Run` section names the tool.
- Tests with the fakes: the fake agent gains `FAKE_AGENT_TOOLS`, calls through the server its inline config names. A
  chore reads its history through the tool from a `cwd` outside the workspace, told what the command prints; another
  chore's history is refused; nothing is listed without a chore's run; a run below a chore's inherits no server.
- Check: a week of the operator's chores with the tool, no chore run failing for the server, and history read through
  the tool in the transcripts.

**Stage 2, the overseer switches.** Waits on stage 1b's check.

- The harness gives the overseer's run the server's entry, removes it from every run it starts, and removes the code
  mode flags from the overseer's environment; the definition
  allows each tool by exact name and denies `bash`, `treehouse status*` included; every other definition denies
  `canopy_*`; `project_config.shadowing` refuses a workspace config that names a `canopy` server; §6's preflight starts
  the server and sends `initialize`, closing the tick `canopy_unavailable` if it fails.
- A run a tool starts is spawned by `canopy _mcp`'s own runner (`cli/mcp.py`), not `canopy dispatch`'s: the entry is
  removed in that runner's `unset` too.
- The guards' refusals still name the CLI's flags and commands (`runs/dispatch.py`, `reviews/start.py`,
  `core/review_requests.py`, `core/conversation.py`), as the decisions record them: each gets one wording that names
  the field, its flag in brackets, as `loop/tools.py`'s do (`repo is required (--repo): ...`).
- The prompt names tools, not commands; a mirror's body is a field; the state block drops the heredoc delimiter.
- TRUST_MODEL T1 and T7; DESIGN §6, §13, §22; D020 edited in place, D081 superseded.
- Tests with the fakes: the fake agent gains `FAKE_AGENT_TOOLS`, tool calls it makes through the server its config
  names, and the dry-run end-to-end test plays the overseer through them; a worker dispatched through a tool starts
  without the entry; a server that cannot start closes the tick `canopy_unavailable`.
- Check: a day of the operator's loop, a dated section of `MEASUREMENTS.md`: no bash call in any overseer transcript,
  no tick failed for a call the overseer could not make, duties met at least as often as the baseline's, and
  tool-result tokens per tick no higher.

**Stage 3, MCP only.** The operator's end state (2026-10-16): the CLI keeps the verbs only while the tools settle.

- The overseer's verbs leave the CLI (`dispatch`, `decide`, `queried`, `attention`, `ticket set`, `mirror` if M37 has
  not retired it, `review run`, `review wait`, `review end`, `chore run`, `chore wait`), and `OverseerCommand` and its
  completion filter with them. Tests that drove a command drive its tool. D020 names the tools alone.
- Open: tool results as JSON rather than the CLI's text (§27, Open).
- Check: `make install-check`'s dry tick passes against the fakes, its overseer acting through the tools.

Status: in progress. Stage 0's source read is done (2026-10-16, OpenCode 1.19.3, §27 What OpenCode does). It
changed the plan in three places: OpenCode sends SIGTERM to every descendant of a local server when the run ends, so
a run a tool starts must be spawned through an intermediate or it dies with the tick; a local server's stderr is
piped and never read, so the server writes none; and tool names hold no underscore, since `canopy_ticket` with a tool
`set` would also be `canopy_ticket_set`. Inline config merges after the workspace's, as assumed. Stage 0's baseline,
from the operator's tick logs, was waived by the operator for Stage 1 (2026-10-20); it is still to be measured before
Stage 2's check, which is held to it. Stage 1 is built (2026-10-20): the verbs are requests and functions in
`loop/tools.py`, which the commands and `canopy _mcp` both call; `procs` removes named variables from a child's
environment and spawns through an intermediate. Its check: `make check`, and in a dry tick OpenCode 1.19.3's own client,
given the server in its inline config and a stand-in model, listed the eleven tools as `canopy_<tool>` and called
`canopy_decide`, which recorded its decision; with no running tick it was offered none. Stage 1b is built against the
fakes (#1119, 2026-10-21); its check, a week of the operator's chores, is the operator's. Since then a chore's run is
also given the reports' server (`canopy_reports`), and the example chores read canopy through tools alone, with no
shell (2026-10-23). Stage 2 was built in #1090, closed unmerged once main moved past it, and is rebuilt on main
(2026-10-23), held as before for Stage 1b's check and Stage 0's baseline: the overseer's process alone gets the
overseer's server in `OPENCODE_CONFIG_CONTENT`, its definition allows its twelve tools by name and has no shell but the
commands `runtime.allow_bash` names (#1166), every other definition denies `canopy_*`, a chore's allowing its own
tools after and the reviewer's and the planner's their git tools (#1171), and the tick checks the server answers
`initialize`. A read of OpenCode 1.19.3's build changed one thing: a tool call to a local server times out after a
minute unless its entry sets `timeout`, so the overseer's entry sets its own; OpenCode 2's entry sets
`timeout.execution` (2026-10-24). Stage 2's check, a day of the operator's loop held to Stage 0's baseline, which is
still to be measured, is the operator's.
