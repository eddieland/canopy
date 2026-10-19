# M48. The overseer's tools over MCP

DESIGN §27, D020, D081. Asked for by the operator (2026-10-16): the overseer acts through MCP tools canopy serves,
not by running the `canopy` CLI through bash. Needs nothing; taken before M37, so that M37 and M38 rewrite the
overseer's prompt once, against tools. Workers are out of scope (§27, Why). Four stages, in order, each in its own
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

**Stage 2, the overseer switches.**

- The harness gives the overseer's run the server's entry, removes it from every run it starts, and removes the code
  mode flags from the overseer's environment; the definition
  allows each tool by exact name and denies `bash`, `treehouse status*` included; every other definition denies
  `canopy_*`; `project_config.shadowing` refuses a workspace config that names a `canopy` server; §6's preflight starts
  the server and sends `initialize`, closing the tick `canopy_unavailable` if it fails.
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
`set` would also be `canopy_ticket_set`. Inline config merges after the workspace's, as assumed. The baseline from
the operator's tick logs remains.
