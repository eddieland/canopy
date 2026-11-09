# Prior art

A survey of open-source projects that overlap with canopy, and what their issue trackers show they learned the hard
way. Surveyed 2026-09-29, aide 2026-10-18, shared plans across tickets 2026-11-02 ([Shared plans across
tickets](#shared-plans-across-tickets)), and tools for token efficiency 2026-11-08 ([Tools for token
efficiency](#tools-for-token-efficiency)). Why canopy is built anyway is D050.

The canopy statuses below are as of those dates and are not kept current. Check the code before acting on one.

A bare § is a section of the design (`design/`); other documents are named, as in TRUST_MODEL §6.

## Overlap

- **[OpenAI Symphony](https://github.com/openai/symphony)**: a spec plus an Elixir reference implementation
  (Apache-2.0, March 2026). A daemon polls the tracker, gives each issue a workspace, and runs a Codex session in it.
  Unlike canopy: Codex app-server only; a tracker adapter per provider (Linear); state in memory only; workspaces kept
  per issue; a repository-owned `WORKFLOW.md` sets the agent command, sandbox policy, and shell hooks. CI and review
  follow-up are left to the prompt, and the example workflow moves tickets and merges, though only after a human has
  approved and moved the ticket to `Merging`.
- **[agent-orchestrator](https://github.com/Untrivial-ai/agent-orchestrator)** (formerly ComposioHQ/agent-orchestrator):
  a Go daemon with desktop and mobile apps (Apache-2.0). A worktree and agent per issue; CI failures and review comments
  are sent back to the agent. Unlike canopy: tracker intake is GitHub and GitLab only, and at least eight Jira attempts
  were closed unmerged; agent sessions are long-lived and fed messages; it runs loopback and optional LAN listeners;
  "never merge" is a prompt line and branch protection, and only its reviewer's permissions deny a merge.
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent) Kanban**: a board in Hermes' own SQLite database. A
  cron dispatcher starts one agent process per task, in a git worktree for coding tasks. Unlike canopy: tasks live on
  Hermes' board, not the team's tracker, and there is no CI or review follow-up. A Symphony-style tracker loop is a
  proposal ([#404](https://github.com/NousResearch/hermes-agent/issues/404)).
- **[aide](https://github.com/jmylchreest/aide)**: a plugin for Claude Code, OpenCode, and Codex CLI (MIT,
  February 2026): a Go binary, an MCP server over its own store, behind TypeScript hooks. It works inside the
  operator's own session: memories and decisions injected at its start, a code index, static-analysis findings, and a
  `swarm` skill with which the session spawns subagents, each in a git worktree through design, test, implement,
  verify, and docs stages. Unlike canopy: no tracker, loop, PRs, or CI follow-up; the orchestrator is the operator's
  interactive session; agents write memory and decisions through its CLI. Read from its code and commit history at
  [457e4e6](https://github.com/jmylchreest/aide/commit/457e4e6) (2026-10-12).

## Shared plans across tickets

Surveyed 2026-11-02 for REQUIREMENTS R28 and ROADMAP M67: how harnesses and plan-driven frameworks give several tickets
one plan. None shipped canopy's target shape, an approved plan for the whole and a plan per ticket pinned to it. Read in
source unless marked secondary; docs sites the session could not reach are so marked.

### Ticket-loop harnesses

- **Symphony** has no parent, sub-issue, or project document in its normalized issue (SPEC §4.1.1); the template's
  only inputs are the issue and the attempt. Ordering is `blocked_by`, "best-effort provider metadata", which holds an
  issue back only while it is in `Todo` (`elixir/lib/symphony_elixir/linear/client.ex`); the GitHub, GitLab, and Asana
  adapters return none. Its `WORKFLOW.md` has the agent file out-of-scope work as new issues, related and `blockedBy`,
  for a human to move to `Todo`, as canopy's follow-ups do (§18).
- **agent-orchestrator** removed its one decomposition feature, `ao spawn --decompose`
  ([#1104](https://github.com/Untrivial-ai/agent-orchestrator/pull/1104), from
  [#1045](https://github.com/Untrivial-ai/agent-orchestrator/issues/1045)): every leaf opened its own branch and PR,
  "fragmenting history and complicating review/merge". A work-graph proposal, items with acceptance criteria and typed
  edges in SQLite, was closed not planned ([#2764](https://github.com/Untrivial-ai/agent-orchestrator/issues/2764)).
  Today an orchestrator session plans in its chat; a worker gets its own issue inlined, nothing of its parent.
- **Hermes kanban** decomposes a triage task into 2 to 6 children by a model call (`hermes_cli/kanban_decompose.py`),
  on by default, and copies context rather than linking it: "every child card body must carry every decision it
  depends on", since workers cannot see sibling cards. Its issues show what copying costs: a task re-triaged after its
  PR merged was split into four children that redid finished work, the decomposer reading only title and body
  ([#147234](https://github.com/NousResearch/hermes-agent/issues/147234)), and parked cards were decomposed and their
  children run ([#144887](https://github.com/NousResearch/hermes-agent/issues/144887)). An edge added to a running
  child is refused.
- **Copilot coding agent** gets a snapshot of its own issue at assignment and nothing of its parent; GitHub staff said
  an agent on a parent issue "does not take in context of its sub issues" (community discussion #159068). Copilot Chat
  drafts a parent with sub-issues the human edits before publishing, each sub-issue carrying its own acceptance
  criteria and file pointers: copying again.
- **Linear for Agents** inlines the parent issue's title and description and the project's summary into
  `promptContext` when a session starts, frozen there (developer docs, agent interaction; read from a mirror). Its
  Agent Plan API is a checklist per session, not shared.
- **Factory Missions** (secondary: an unofficial, reverse-engineered gist) is the nearest analogue: the operator
  approves a mission, the orchestrator writes `mission.md`, a validation contract, and an ordered `features.json` with
  preconditions, and workers read the files themselves. A change mid-run pauses the workers, gets the user's agreement,
  rewrites "every file that states the old truth", resets the assertions it unproves, and commits atomically; passed
  milestones are sealed.
- **Devin** (secondary): a coordinator session launches child sessions, each with its own prompt and playbook, children
  starting without asking by default. No shared plan the children read was found.

### Plan-driven frameworks

- **BMAD v7** ([BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD), `docs/plan/`, `skills/bmad-agent-po/`) is
  the closest to R28's shape, initiative to epic to story. The parent is a list of requirements with stable ids
  (`R3 (prd FR-2): ...`), its contracts, and a `tickets.toml` of children in build order, each a thin entry:
  `covers = ["R2", "R3"]`, `after = [...]`, `verify`. A child's full plan is written just before it is built, "so detail
  is not written months before it is used". On a change, ids are kept, children whose `covers` cite a changed id are
  marked stale, an in-progress child's plan is never edited ("ask whether its build stops"), nothing built is
  rewritten, and a dated decision line goes in the parent. Contracts several epics must adopt are settled in the
  architecture or become a story in the opening epic the others wait on. A retrospective at the epic's end looks for
  defects at the seams between stories. v6's `create-story` inlined the upstream docs into each story file and is
  deprecated.
- **Spec Kit** ([github/spec-kit](https://github.com/github/spec-kit), `docs/concepts/spec-of-specs.md`): a shallow
  `roadmap.md` per epic (id, scope boundary, depends on, status) that "does not design" its sub-features; each child
  spec's Input line points back to its roadmap entry; children are specified one at a time; reconciling a change is by
  hand, "roadmap first, then reconcile", and the docs call the pattern a last resort.
- **Taskmaster** ([claude-task-master](https://github.com/eyaltoledano/claude-task-master)) inlines the PRD into each
  task's `details` with no link back; `update --from` rewrites later tasks and leaves completed ones alone.
- **Conductor** approves a track's spec and plan separately and, when a track completes, updates the project-level docs
  from it. **Agent OS v3** dropped its spec and task scaffolding altogether. Both, and Spec Kit, name the same
  complaints: over-planning, and the burden of reviewing markdown.

### What they agree on, and what none does

- The parent is shallow: boundaries, requirement ids, the children's order, and the contracts between them.
- A child points back by id and never inlines the parent: Hermes, Taskmaster, and BMAD v6 show copies going stale.
- A child's plan is written just in time, as canopy's planner already does (§25).
- Shared contracts are settled first, in the parent or as a first ticket the others are blocked by.
- A human approves at both levels; the defaults that approved alone (Hermes, Devin) are where the incidents are.
- None pins the parent's version in the child. Staleness is ignored, frozen at dispatch, or a manual pause and rewrite.
  canopy's plan hashes and `plan_changed` guard (§25) would make that a guard in code; M67 says how.

## Tools for token efficiency

Surveyed 2026-11-08 for ROADMAP M71: what tools harnesses give coding agents to read less, and what anyone has measured
of it. Read from the vendors' own posts and documentation, the papers' abstracts, and the tools' READMEs; a claim read
only in a search excerpt or a secondary summary, where the site could not be reached, is marked secondary. The
canopy comparisons are as of that date.

### What is measured, by someone other than the vendor

- **Symbol tools do not save a strong model tokens when grep is at hand.** A tokens-to-success ablation over Python and
  TypeScript repositories ([arXiv 2608.13568](https://arxiv.org/abs/2608.13568), secondary): for finding a named
  symbol a language server *adds* 6% to 118% tokens by model, since the agent still greps; only the weakest model
  saved, by flailing less. canopy's M70 puts an outline in the prompt and measures a gate first, which this supports,
  and offers lookups last, which it says not to expect much of.
- **Compressing what a model reads costs accuracy.** A code-graph server ([arXiv 2603.27277](https://arxiv.org/abs/2603.27277))
  read a tenth of the tokens and answered 83% against a plain file-reading agent's 92%; minified code in context cut
  SWE-bench input tokens 42% and resolution 12 points ([arXiv 2606.01326](https://arxiv.org/abs/2606.01326)); compact
  serializations of tool results (TOON, TRON) saved up to 27% tokens at 9 to 14 points of accuracy and parse failures
  that compound over turns ([arXiv 2605.29676](https://arxiv.org/abs/2605.29676)). So a canopy tool answers in plain
  text or JSON records, as `canopy_git_log` and `grep` do, and never a terser form.
- **Compact records between agents halve what the next one reads.** PACT ([arXiv 2606.05304](https://arxiv.org/abs/2606.05304)),
  one model on SWE-bench Verified: each turn kept in shared history as a fixed-field record (action, observed state,
  planned effect) rather than its text halved SWE-agent's input tokens at the same resolve rate. canopy's result line,
  card (§41), and state block are such records already; what a worker's prose `summary` carries into later runs'
  prompts is the one place a fixed shape has not been tried.
- **Every shipped harness retrieves code deterministically.** A source study of eleven coding harnesses
  ([arXiv 2609.00006](https://arxiv.org/pdf/2609.00006), secondary): ripgrep and tree-sitter in all, vector search for
  code in none; seven compact on a threshold, Codex instead writes a summary the harness restores on resume. M70's
  rejection of embeddings stands.
- **Code execution against MCP** ([arXiv 2602.15945](https://arxiv.org/abs/2602.15945), secondary) cuts tokens and
  widens the attack surface, with worse fulfillment where several servers are orchestrated. D077 denies it.

### What vendors measure of their own

Upper bounds, each against a baseline the vendor chose.

- Anthropic's [writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents): a
  `response_format` of `concise` or `detailed` answered in 72 against 206 tokens; names in place of ids cut
  hallucinated follow-ups; a truncated result should say how to narrow the next call; errors should state the fix;
  consolidate a workflow into one tool rather than overlapping getters; many redundant calls in an evaluation mean the
  limits or the pagination are wrong, many invalid-parameter errors that the descriptions are. canopy's git tools
  already page, bound, and refuse by field name; `show` and `diff` have no range, and no cut result says how to narrow.
- Anthropic's [code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp): one example,
  150k to 2k tokens, by filtering a result where it is made rather than in the model's context; the harness doing the
  filtering, as canopy's connectors do (§30), is the same saving without the model writing the code.
  [Advanced tool use](https://anthropic.com/engineering/advanced-tool-use): loading tool definitions on demand cut a
  77k-token prefix to 8.7k and raised accuracy; OpenCode has no form of it, and a prefix the provider caches is cheap
  on a warm run (MEASUREMENTS 2026-10-21).
- Anthropic's [context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  and [multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system): a subagent spends
  tens of thousands of tokens and returns one to two thousand; multi-agent work costs about fifteen times a chat; token
  use explains most of the variance in task performance; the lead's plan goes to memory before the window fills.
  canopy's runs are such subagents of a loop with no shared context, so each starts with the brief in its prompt and
  returns a result line; the parallel is the brief's fields, an objective, an output shape, which tools, and bounds.
- [Claude Code](https://code.claude.com/docs/en/tools-reference) caps a tool result at 25k tokens, saves a longer one to
  a file and returns its path with a preview, pages `read` with an offset and a limit, defaults `grep` to file names,
  and names the follow-up in each truncation notice ([costs](https://code.claude.com/docs/en/costs): a hook that keeps
  only a test run's failures turns tens of thousands of tokens into hundreds, and a CLI such as `gh` is cheaper than
  an MCP server because it lists no tools). OpenCode cuts a tool's output at 2,000 lines or 50 KiB to a file it names
  ([PR #23770](https://github.com/anomalyco/opencode/pull/23770)), which canopy's overseer prompt already tells it to
  page. Codex keeps a byte budget per exec with the head kept and a line count in the hint
  ([exec.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/exec.rs)).
- Tool vendors: [jcodemunch](https://github.com/jgravelle/jcodemunch-mcp) "94.5% fewer tokens per lookup" against a
  scripted grep that opens three files, success unmeasured; [agent-lsp](https://github.com/blackwell-systems/agent-lsp)
  2 to 34 times by bytes, single runs; [rtk](https://github.com/rtk-ai/rtk) "up to 90%" of shell output, its own
  table; [Serena](https://github.com/oraios/serena) claims and does not count, and turns its own file and shell tools
  off under Claude Code and Codex because the harness has them. [aider's repo map](https://aider.chat/2023/10/22/repomap.html)
  is tree-sitter and PageRank to a token budget, the model's one view of the repository, with no tools beside it.

### Tools the harnesses give their agents

- Progress and plans: Claude Code's task list, Codex's `update_plan`, Copilot's coding agent's `report_progress` with a
  checklist in the PR body (secondary), Manus's `todo.md` recited each turn (secondary). canopy's card (§41) is the
  same, with proof per step and a question the operator answers by letter.
- Asking the user: Cline's and Roo's `ask_followup_question` with options (secondary); MCP's elicitation
  (2025-06-18). canopy's card asks with lettered options and works around meanwhile; a message arrives through a tool
  of canopy's, never a line (§44).
- Subagents: Claude Code's Explore and Plan agents, Amp's Oracle and Librarian, each in its own context, returning a
  summary (secondary); Amp replaced compaction with a hand-off thread that packages the relevant context and a goal.
  Every canopy definition denies `task` (T1, spend); a run's hand-off is its result line and the next run's prompt.
- Code structure: Cline's `list_code_definition_names`, a tree-sitter outline of one directory (secondary); Claude
  Code's code-intelligence plugins for go-to-definition. M70.
- Output filtering: Claude Code's hooks on a tool's result; rtk as a shell wrapper. canopy's plugin adds a line to a
  result and never changes one (T4), and OpenCode's cut to a file already keeps a long output out of the context.

### What held up as design, and what did not

- Return high-signal fields, cap every result, keep the full text in a file the agent can page, and say in the cut how
  to narrow the next call. Every shipped harness converged here, and it is where the independent savings are.
- Keep the tool set small, stable through a run, and not overlapping the runtime's own `read`, `grep`, and shell:
  changing the tools mid-run invalidates the cache behind them (Claude Code, Manus's "mask, don't remove", secondary).
- MCP's annotations (`readOnlyHint` and the rest) are hints a client must treat as untrusted, never a guard; canopy's
  `Hints` sets them so a client can skip a prompt, and its guards stay in code (D020). `structuredContent` saves no
  tokens, since the spec has the text carry the same JSON and OpenCode reads the text alone (§27); it saves re-parsing.
- Block rebuilt a tracker server from thirty tools to two, by workflow (secondary,
  [recap](https://www.plushcap.com/content/workos/blog/workos-mcp-night-20-demo-recap-blocks-goose-the-layered-tool-pattern)).
  canopy's overseer has one verb per decision on purpose, for spend by tool (§27); a worker's one read of its
  feedback (M71 stage 2) follows Block's shape, one tool for what three getters would return.
- Not to copy: a terser result format than JSON; minified code in a result; a runner tool whose commands skip the
  shell's rules; the log or the thread pasted into the prompt (What not to copy, below).

## Lessons canopy's design already answers

- **In-memory claims let a restart run two workers on one issue** (Symphony
  [#97](https://github.com/openai/symphony/pull/97)). canopy: the
  journal (D004), the pid claim and dispatch lock (D029), treehouse leases (D002), no retries in the worker.
- **A retry budget that resets on a state change never escalates** (agent-orchestrator
  [#1531](https://github.com/Untrivial-ai/agent-orchestrator/pull/1531)). canopy: attempts are derived from `runs` and
  never reset (D030); retrying needs an authorized reply.
- **Pushing events into a long-lived orchestrator session duplicates and contaminates it.** agent-orchestrator added
  automatic re-engagement and removed it two days later
  ([#3394](https://github.com/Untrivial-ai/agent-orchestrator/pull/3394)). canopy: a fresh overseer each tick with a
  state block (§6), a fresh worker per run from the pushed branch (§9).
- **Auto-answering an agent's input prompts fabricates answers** (Symphony
  [#10](https://github.com/openai/symphony/pull/10), reversed in [#112](https://github.com/openai/symphony/pull/112)).
  canopy: `ask` is auto-rejected (D021) and the run goes to attention.
- **Intake open to anyone who can file an issue** (agent-orchestrator
  [#2527](https://github.com/Untrivial-ai/agent-orchestrator/pull/2527)). canopy: queue labels are private (§12, §17),
  and a label finds tickets, it does not authorize replies.
- **A reused worktree ran on the previous run's branch** (Hermes
  [#71978](https://github.com/NousResearch/hermes-agent/pull/71978),
  [#68201](https://github.com/NousResearch/hermes-agent/issues/68201)). canopy: every run fetches with `--prune` and
  checks out from `origin`, never from local HEAD (§8).
- **A failed automation step passed a gate silently** (agent-orchestrator
  [#5424](https://github.com/Untrivial-ai/agent-orchestrator/issues/5424),
  [#2827](https://github.com/Untrivial-ai/agent-orchestrator/issues/2827)). canopy: `review_failed`
  (§21); review comments are classified, never filtered by author.
- **Usage read per message, or summed from snapshots, is wrong.** aide found that a Claude transcript's output count
  can be a placeholder written as a response starts ([#78](https://github.com/jmylchreest/aide/pull/78)),
  that OpenCode's message-level usage can omit earlier steps, and that cumulative snapshots must never be summed; it
  now keeps unknown apart from zero
  ([model usage](https://github.com/jmylchreest/aide/blob/457e4e6/docs/docs/reference/model-usage.md)).
  canopy: cost is summed from each model call's `step_finish` (§13), and a step it cannot read makes the run report no
  cost rather than too little.

## Gaps

### In code today

- **`_run` imports from the repository root.** `runs/dispatch.py` spawns `python -m canopy _run` with the repository
  root as cwd, so a top-level `inspect.py`, `sqlite3/`, or `canopy/` there shadows canopy's imports. A branch a worker
  wrote, checked out in the main checkout, would run on the host outside any sandbox. Hermes hit this: a workspace
  `inspect.py` crashed every dispatch ([#126896](https://github.com/NousResearch/hermes-agent/pull/126896)), and an
  open Hermes PR proposes `python -P`.
- **An `implement` run that commits nothing is recorded as the worker reports it.** `_ensure_pushed` in
  `runs/worker.py` treats "no new commits" as pushed, and nothing checks HEAD, the result's branch, or a dirty tree, so
  a worker that says `done` is recorded `done`. With no branch on origin the ticket derives as `ready` again (§7) and
  is redispatched, spending `implement` attempts on work that never happened. Hermes has an open issue about fabricated
  completions ([#108782](https://github.com/NousResearch/hermes-agent/issues/108782)); a PR that gated completion on
  git was closed unmerged ([#105452](https://github.com/NousResearch/hermes-agent/pull/105452)). A `resume`
  can rightly commit nothing.
- **Harness git in a slot runs the slot's hooks.** `_GIT_ENV` in `runs/worker.py` sets only `GIT_TERMINAL_PROMPT`;
  `checkout` and the fallback `push` run hooks and `core.fsmonitor` from a git directory a worker can write.
  HOST_ISOLATION §5 item 1 already proposes the `-c` flags as correct with or without a sandbox. Hermes kept finding
  call sites that missed its hardened git env ([#126017](https://github.com/NousResearch/hermes-agent/issues/126017)).
- **Agent-written text reaches the terminal with control bytes intact.** `cli/params.truncate` bounds length only;
  `canopy status` echoes attention details, which also go to `attention.md` and `notify.cmd`. Symphony strips ANSI and
  control bytes centrally ([#23](https://github.com/openai/symphony/pull/23)).
- **pid reuse, D029's named residual, has been observed elsewhere.** agent-orchestrator killed users' tmux sessions
  through stale pids and now checks process start times
  ([#3491](https://github.com/Untrivial-ai/agent-orchestrator/pull/3491)). That is D029's revisit trigger.

### In prompts

- **Workers' own comments read back as feedback.** Everything runs as the operator (D010), who is usually an authorized
  replier. `worker-resume.md` has workers reply on the PR after the `review` cursor was set, and nothing in the phase
  table tells a worker's comment from the operator's, so a reply can look like new review feedback and spend a
  `resume` attempt. agent-orchestrator has the same loop open
  ([#5574](https://github.com/Untrivial-ai/agent-orchestrator/issues/5574)). A fixed marker on worker comments that can
  only take authority away, like §21's reviewer marker, fails safe.
- **The tracker search is not paged.** `overseer.md` has the overseer run the configured query and union the result
  with the state block's tickets, but nothing says to page, so a new labeled ticket past the first page (Jira and
  GitHub return 30 to 50) is not seen until earlier ones leave the queue; the union covers only tickets canopy already
  knows. Symphony's refresh of running issues by id truncated at 50 until it paged
  ([#43](https://github.com/openai/symphony/pull/43)).
- **CI newness is keyed on the check run id.** A human re-run or a runner or billing failure makes a newer run and
  another `resume` for CI. agent-orchestrator woke an agent 8 times in 40 minutes from one billing refusal
  ([#5089](https://github.com/Untrivial-ai/agent-orchestrator/pull/5089)). Keying on commit and check name, and raising
  attention for failures the branch did not cause, avoids that.
- **Merge conflicts have no phase** (§7). A conflicting PR may get no CI run and sit in `ci_running` or show a stale
  green. agent-orchestrator tracks mergeability and fixed two bugs in its conflict nudge
  ([#3766](https://github.com/Untrivial-ai/agent-orchestrator/pull/3766)). Its "rebase" instruction does not fit canopy
  by default, whose workers never force-push; merging the base in does. With `trust.rebase` they rebase (C6).

### Open design questions

- **Dependencies are installed before the branch is checked out.** treehouse `post_create` (§9) runs on the base
  branch, before `_run` checks out a stacked or continued branch, and a failing hook does not fail the lease. An open
  Hermes PR proposes a worktree-created hook
  ([#104226](https://github.com/NousResearch/hermes-agent/pull/104226)).
- **A run on a ticket closed or unlabeled mid-run keeps going** to `worker_timeout_minutes`, and still pushes. Symphony
  stops such runs (SPEC §8.5, [#88](https://github.com/openai/symphony/pull/88)), and refreshes an issue just before
  spawning its worker so one that changed since the poll is skipped
  ([#15](https://github.com/openai/symphony/pull/15)).
- **An outage spends every ticket's attempts.** Crashes during a provider or treehouse outage count toward D030 limits,
  one ticket at a time. Hermes logged 3,452 rate-limited runs in a week
  ([#127495](https://github.com/NousResearch/hermes-agent/issues/127495)); agent-orchestrator treats many sessions
  dying at once as one outage (#3491 above).
- **Returning a slot discards uncommitted work unrecorded.** `return --force` is deliberate (D002, D005), but nothing
  records what was thrown away. An open Hermes issue asks for reclaim to notice uncommitted work
  ([#101788](https://github.com/NousResearch/hermes-agent/issues/101788)); recording paths, never contents, is enough.
- **Child processes inherit the operator's whole environment**, tokens included (`infra/procs._child_env`), and
  the sandbox (DESIGN §24) allowlists files but not variables. Symphony found tracker tokens in env aliases crossing its
  boundary ([#119](https://github.com/openai/symphony/pull/119)).
- **Spend per run.** A looping agent-orchestrator worker used 45M tokens in 45 minutes, canopy's default worker timeout
  ([#6032](https://github.com/Untrivial-ai/agent-orchestrator/issues/6032)). Symphony counts absolute totals, not
  deltas, and has an open PR to persist them ([#60](https://github.com/openai/symphony/pull/60)). Input for M13.
- **A running worker hears nothing after its prompt.** It is told `{{TIMEOUT_MINUTES}}` once and has no clock, a
  notice (M35) reaches only runs rendered after it, and at the timeout what it has not committed goes with the slot.
  aide's PreToolUse hook hands a running subagent a halt, a pause, or an urgent message on its next tool call, and
  warns it in the last five minutes before a soft deadline
  ([agent-signals.ts](https://github.com/jmylchreest/aide/blob/457e4e6/src/hooks/agent-signals.ts)), under Claude
  Code only: its OpenCode plugin has no such signal, and adds context each turn, for memory, through
  `experimental.chat.system.transform`. A warning before the kill would let a worker push what it has (M57).
- **Lessons mined from transcripts, without a model.** §28 leaves open a chore that drafts proposals from transcripts.
  aide's `reflect` makes a first pass with no model at session end: a shell command run four times in 30 minutes, past
  a list where repetition is normal (`git status`, `ls`), or a user's correction between two edits of one file, each
  becomes a draft marked for rewriting and held for the user's approval
  ([pkg/instinct](https://github.com/jmylchreest/aide/blob/457e4e6/aide/pkg/instinct)). canopy already rolls each
  run's tool calls up by tool, errors included (§13), so such a pass stays in the deterministic core. aide cannot see a
  failed native tool under OpenCode, whose plugin API has no failure hook; canopy reads the failure from the event
  stream.
- **The token split is OpenCode's, and OpenCode has changed it.** canopy's new tokens add `output` and `reasoning`
  (`runtime/opencode/events.py`). In OpenCode 1.19.3 `output` already leaves reasoning out (`session.ts`:
  `output: outputTokens - reasoningTokens`), so the sum holds; aide found the overlap differed in earlier releases and
  keeps OpenCode's raw output apart. SCENARIOS S44 checks it on an upgrade.
- **A runtime point release can hang headless agents on a permission prompt**
  ([agent-orchestrator #4810](https://github.com/Untrivial-ai/agent-orchestrator/issues/4810)). D021 revisits only on an
  OpenCode major version.

## What not to copy

- **A repository file that sets commands, sandbox policy, or hooks.** Symphony's `WORKFLOW.md` does; TRUST_MODEL T7
  and TRUST_MODEL §6 keep all of that private.
- **Agents that merge, land, or move tickets.** Symphony's example workflow has a `land` skill, run once a human moves
  the ticket to `Merging`; TRUST_MODEL §6 forbids agents merging at all. canopy's own guard is layered: the prompts, a
  `gh pr merge` deny in canopy's agent permissions, and branch protection, which governs. The deny is defense in depth
  (TRUST_MODEL T4, T7): it names only the `gh` CLI, not MCP merge tools, and a repository that gets past the shadowing
  check can add bash rules after it. aide's `swarm` must end in `worktree-resolve`, which merges each story's branch
  locally.
- **Agent-written memory every later session reads.** aide's swarm agents record decisions and memories with its CLI,
  and both are injected into every later session; `AIDE_SHARE_AUTO_IMPORT` imports teammates' records committed under
  `.aide/shared/` at session start. §28 lets workers only propose, and TRUST_MODEL T7 keeps what configures agents out
  of the repository. aide's own later `reflect` holds its proposals for the user's approval.
- **A hook that refuses to let a session stop.** aide's persistence hook blocks a stop while the session's todo list has
  items open, up to 20 times
  ([persistence-logic.ts](https://github.com/jmylchreest/aide/blob/457e4e6/src/core/persistence-logic.ts)).
  A canopy worker ends when it says it is done, the harness checks what it pushed (§8), and another try is a new run
  that D030 counts.
- **Long-lived sessions fed events, or a service installed with the OS** (D042). agent-orchestrator's own reverted
  re-engagement is the evidence. Listeners are allowed since D055, on loopback or a private network behind the
  operator's secret (TRUST_MODEL T8), for the operator's own input; events are still not pushed into sessions
  automatically.
- **Tracker adapters.** agent-orchestrator has closed at least eight Jira attempts unmerged; canopy's tracker is MCP
  plus a contract (D003, D014).
- **Pasting issue bodies or CI logs into prompts** (T1).
