# Decisions

Append-only. One entry per choice that someone might later want to revisit.
Format: context, decision, consequences, and what would make us revisit.

## D001. Do not build on Azimuth

Context: Azimuth encoded the workflow in code, was hard to grow, and never
shipped as something a second person could run. treehouse solves worktree
problems Azimuth had.
Decision: new repository, no shared code.
Revisit: never; salvage ideas, not code.

## D002. treehouse is the worktree pool

Context: pooled, reusable worktrees with durable leases, dirty and in-use
detection, safe prune, no daemon, JSON output.
Decision: hard dependency. canopy wraps `status --json`, `get --lease --json`,
`return --force --if-lease-id --if-lease-holder`. Lease holder is
`canopy:<TICKET>`.
Consequences: worktrees are ephemeral; the pushed branch is the checkpoint.
Revisit: if treehouse's lease semantics change incompatibly.

## D003. Connectivity through the agent runtime's MCP, not harness code

Context: Jira and GitHub are reachable as remote MCP servers with OAuth
handled by the runtime.
Decision: the harness imports no tracker or VCS client and never sees a token.
Tracker specifics are prompt and config.
Consequences: the harness cannot poll Jira or GitHub itself; the overseer
does, each tick, guided by cursors in the journal. A second tracker is a
prompt edit.
Revisit: if the overseer's token cost for reading state dominates, or if
MCP client auth from a script becomes trivial. Then move polling into Python.

## D004. SQLite journal plus flock, not a stateless overseer

Context: a stateless design hid state in ticket comments and label timestamps,
which is slower, noisier for teammates, and unqueryable.
Decision: SQLite in WAL mode with numbered migrations; `flock` around the
tick. The journal owns loop facts only; world facts are always re-read.
Consequences: cursors, attempt counts, cooldowns, crash detection, and an
audit log are all queries.
Revisit: multi-machine operation (not planned).

## D005. Aggressive release of worktrees

Decision: hold a slot only while a worker process is running. Waiting on CI,
review, or a human holds nothing. Worker pushes before release, always.
Consequences: reacquisition lands on any slot, so build caches must be
slot-independent; repository concern, documented.
Revisit: if reacquisition cost is measured to exceed the capacity gained.

## D006. OpenCode as the agent runtime, not Pi

Context: Pi is a minimal, extensible agent with a TypeScript extension API,
print/JSON/RPC/SDK modes, and deliberately no built-in MCP, no permission
prompts, and no sub-agents; those are meant to be added by extensions or run
in a container. OpenCode has built-in MCP (including remote OAuth servers),
agent definitions with per-tool permissions, non-interactive `opencode run
--agent`, TypeScript plugins, and a server/SDK.
Decision: OpenCode.
Reasons:
1. D003 depends on the runtime doing MCP and OAuth. OpenCode does this out of
   the box; Pi would need an extension for it, which puts connectivity code
   back in our hands.
2. The pluggability canopy needs is one thing: run a named agent
   non-interactively in a cwd and read stdout. `opencode run --agent` is
   sufficient. Pi's richer extension API is for changing the agent from the
   inside; canopy orchestrates from the outside and does not need it.
3. The team already uses OpenCode skills and MCP servers. Pi is another
   runtime to install (Node 22+).
4. Per-agent tool permissions give a second layer of guardrails for the
   overseer (read-only) and worker (worktree-scoped) without writing code.
Consequences: `overseer_cmd` and `worker_cmd` are OpenCode invocations by
default. Because they are command templates, a Pi worker is a config change.
Caveat to verify in M1: that agent permission denies hold under `opencode run`
(a past report suggested denies were ignored via the SDK). Config permissions
remain defense in depth, not the boundary.
Revisit: if we want the loop inside the agent process (extension hooks on
turn end, structured-output termination). That is firstmate's shape, and it
was rejected in favor of outside orchestration.

## D007. Python with uv, not Go

Context: Go would match treehouse's single-binary distribution. Python with
`uv tool install` gives an isolated install, faster iteration, stdlib
`sqlite3` and `tomllib`, and matches team tooling.
Decision: Python 3.12+, uv, ruff, ty, pytest. Stdlib first.
Revisit: if installation friction on coworker machines shows up in M5.

## D008. Policy in prompts, guards in code

Decision: what to do about a ticket lives in `prompts/overseer.md`. What the
loop may never do lives in `dispatch.py` guards and agent permissions.
Consequences: a new capability is a tool plus a paragraph. Guards are
non-negotiable from the prompt side. `decisions` table is the prompt eval
corpus.
Revisit: if prompt behavior proves too unstable, move specific phase rules
into code one at a time, recording each move here.

## D009. Runtime abstraction is a command template

Decision: no adapter interface. `runtime.overseer_cmd` and
`runtime.worker_cmd` are shell templates with `{prompt}`.
Revisit: when a second runtime needs different result parsing or invocation
shape. Then, and only then, introduce the smallest interface that covers both.

## D010. Operator identity for the MVP

Decision: all actions run as the operator. Agent work is distinguishable by
branch prefix, PR label, and commit trailer. No bot account.
Consequences: zero org approval needed; audit relies on the local journal plus
the markers above.
Revisit: when audit or compliance requires a distinct identity.

## D011. `ty` for type checking

Context: `ty` and `pyrefly` were both candidates; `ty` pairs with `uv` and
`ruff` from the same vendor.
Decision: `ty`.
Revisit: if `ty` blocks on a needed feature; swapping checkers is a Makefile
change.

## D012. Milestone status lives in ROADMAP.md

Context: there was nowhere to record that a milestone was finished, or what
building it taught us, so the next agent started without that context.
Decision: each milestone in `ROADMAP.md` ends with a `Status:` line. When the
milestone is done it gets a date, a `Learned` note, and a `Next` note. No
separate status file.
Consequences: the file agents already read in order also carries the
outcomes. `ROADMAP.md` stays editable, unlike this file.
Revisit: if status notes grow long enough to crowd out the plan.

## D013. 120-character line length everywhere

Context: ruff was set to 100 and nothing governed non-Python files, so editors and agents picked their own widths.
Decision: 120 columns for every file type. `.editorconfig` sets it (plus charset, line endings, indentation) for all
editors; `pyproject.toml` sets ruff's `line-length` to match. AGENTS.md states the rule.
Consequences: one number to remember; existing text wrapped narrower is left alone rather than reflowed.
Revisit: if a tool we adopt cannot be configured to 120.

## D014. Tracker-agnostic: MCP plus a contract, with optional provider skills

Context: D003 put tracker access behind the runtime's MCP servers, but config (`jql`), prompts ("Tracker MCP
(Atlassian)"), and docs still assumed Jira. The goal is that any tracker with an MCP server works: Jira, GitHub Issues,
Linear, others.
Decision: the harness stays tracker-blind. Config names a free-form `tracker.provider` and a `tracker.query` in the
tracker's own syntax (or plain language). DESIGN §17 states a provider-neutral contract of capabilities the loop needs.
Per-provider knowledge goes in optional skills (`tracker-<provider>`), shipped for `jira` and `github`, loaded by the
agents when present. No adapter interface, consistent with AGENTS.md.
Consequences: a new tracker is config plus, if agents misread it, a skill. The label, not the query, authorizes work, so
a vague query cannot widen scope. Keys are validated by a regex guard in the CLI, since they end up in branch names,
paths, and shell arguments. Skill loading depends on the runtime.
Revisit: if the `decisions` table shows agents ignoring skills, have the harness inline the skill body into the rendered
prompt instead. If a tracker needs code to be usable, record why here before writing it.

## D015. The subprocess boundary is enforced by lint

Context: AGENTS.md says every external process goes through `procs.py`, because that is the seam tests fake and the
place timeouts and process-group handling live. A rule only reviewers check erodes.
Decision: ruff's `flake8-tidy-imports` banned-api rule (`TID251`) bans `subprocess`, `os.system`, and `os.popen`
everywhere except `src/canopy/procs.py`. Tests follow the same rule: they run the fakes through
`procs.SubprocessRunner`. The fakes in `tests/fakes/` are stdlib-only Python executables, linted by ruff through
`extend-include`.
Consequences: a stray `import subprocess` fails `make check`. `os.exec*`, `os.spawn*`, and `pty` are not banned; add
them if anything reaches for them.
Revisit: never for the rule itself; widen the banned list if a new way to start processes shows up.

## D016. Layered config: shared repository file, personal user file

Context: `canopy.toml` was one file at the repository root, written by each operator's `canopy init`. Most of its keys
are personal: the queue, machine capacity, runtime commands, authorized repliers, notify. A committed file can be
changed by anyone who can push, and a checked-out branch carries its own version. The queue label must be personal:
the guards see only the local journal and multi-machine coordination is out of scope, so two operators sharing a label
would both work the same tickets.
Decision: built-in defaults, then the repository's `canopy.toml` (committed, shared keys only), then the user's
`$XDG_CONFIG_HOME/canopy/config.toml`, merged key by key. Every key is shared or user-only (DESIGN §12); a user-only
key in the repository file is an error. Keys that run commands, choose prompts, spend, or authorize are user-only.
Repository `policy.*` may only tighten. `tracker.label` becomes `tracker.labels`, a list, user-only and required.
Stdlib only: `tomllib` and a dict merge.
Consequences: a second operator on a repository runs `canopy init` and gets only a user file. Operators must choose
distinct labels, and canopy cannot check that. Rejected: a gitignored `canopy.local.toml` per repository (easy to
commit by accident, a third file to explain); a shared label with an assignee filter in the query (the query finds
tickets but does not authorize them, D014).
Revisit: when one operator runs canopy on several repositories and needs different labels or state per repository
(DESIGN §16), or when a team wants a shared authorized-replier list.

## D017. `pyrefly` in strict mode is the only type checker

Context: D011 chose `ty`, but the seed `Makefile`, `pyproject.toml`, and AGENTS.md ran both `ty` and `pyrefly`, and M0
shipped that way without a record. Two checkers meant satisfying both on the same code for little extra coverage, and
neither looked at the test fakes.
Decision: `pyrefly` with `preset = "strict"` is the only type checker. It covers `src`, `tests`, and the extensionless
fakes (listed in `[tool.pyrefly] project-includes`, as ruff's `extend-include` lists them). `ty` is removed from the
dev dependencies and the `Makefile`. This supersedes D011 and the `ty` in D007.
Consequences: one checker, one set of suppressions. Strict mode rejects implicit `Any`, such as a bare `dict`
annotation. Adopting it only needed the treehouse fake's `dict` annotations parameterized.
Revisit: if strict mode forces suppressions on correct code often enough to cost more than it catches; then drop to
the default preset for the offending error kinds, not the whole project.

## D018. ruff selects every stable rule

Context: ruff ran a hand-picked set (`E`, `F`, `I`, `UP`, `B`, `SIM`, `PL`, `TID`). That missed whole families that fit
this codebase: bandit (`S`), pathlib (`PTH`), docstrings (`D`), unused arguments (`ARG`), `print` in library code
(`T20`), pytest style (`PT`), and ruff's own (`RUF`). A hand-picked set also silently skips every rule ruff adds later.
Decision: `select = ["ALL"]` with a short `ignore` list in `pyproject.toml`, each entry commented with its reason, plus
per-file ignores for `tests/**` (asserts, magic numbers, fixtures used for side effects, no docstrings) and the
fakes (`print`). Docstrings follow the Google convention (`Args:`, `Returns:`, `Raises:`
sections); tests, fakes included, need none and are not docstring-checked. Relative imports are banned. Preview
rules stay off. The `ruff` floor is 0.16, the version the ignore list was written against.
Consequences: adopting it needed docstrings on the public API in `src/`, `pathlib` in the agent fake, and `S603` added
to `procs.py`'s per-file ignores next to `TID251`. A new ruff release can add rules and fail `make check`; `uv.lock`
pins the version, so that happens only in the PR that bumps it, which fixes or ignores (with a reason) what it flags.
Opting out is an `ignore` entry with a comment or a `noqa` with a code, never narrowing `select`.
Revisit: if the ignore list grows past what one screen of `pyproject.toml` explains, or a ruff bump routinely costs
more than it catches.

## D019. Every test directory is a package

Context: M0 removed `tests/canopy/__init__.py` because, with no `tests/__init__.py`, pytest's default `prepend` import
mode named that directory `canopy` and shadowed `src/canopy`. The fix left test modules as top-level names
(`test_cli`), so two test files with the same basename in different directories collide, and what a test module is
called depends on which directories happen to lack an `__init__.py`.
Decision: every directory under `tests/` has an `__init__.py`, the root included. Test modules import as
`tests.canopy.test_cli` and so on, and `src/canopy` stays the only `canopy`. ruff's `INP001` is no longer ignored in
tests, so a new test directory without one fails the lint. `tests/fakes/` gets one too, for uniformity; the fakes are
executables and are never imported.
Consequences: test basenames may repeat across directories. Removing `tests/__init__.py` brings the shadowing back;
`INP001` catches that. Rejected: `--import-mode=importlib`, which avoids the shadowing without packages but changes
how `conftest.py` and test helpers are imported for no gain here.
Revisit: if pytest's default import mode changes.

## D020. The overseer reaches the journal through the CLI, keyed by `CANOPY_TICK_ID`

Context: M1's dry-run tick has to record the overseer's plan. The overseer is an agent process; it writes only through
`canopy dispatch`, `decide`, `attention`, and `ticket set`, each a separate process that must know which tick it
belongs to. The schema has no attention table, and a dry run must not change what a later live tick sees.
Decision: the tick sets `CANOPY_TICK_ID` in the overseer's environment. `dispatch`, `decide`, and `attention` refuse
without it, or when it names a tick that is not `running`; `ticket set` uses it only to learn whether this is a dry run.
Attention items are decisions with action `attention:<reason>`, and the current list is those of the latest `ok` tick.
In a dry run, `dispatch` records `dispatch:<kind>` and starts nothing, and `ticket set` records phases but not cursors.
Until M2, `canopy tick` without `--dry-run` is refused, and a dispatch outside a dry run records
`refused:not_implemented`.
Consequences: no prompt change and no new table. Commands run by hand outside a tick are refused, which is the point:
the journal only holds what the loop did. Dry-run decisions are the evaluation corpus the M1 acceptance run reads.
Revisit: if the runtime stops passing the environment to its bash tool (then add a `--tick` flag and a prompt line), or
if attention items need state that survives a failed overseer run (then a table, with a migration).

## D021. OpenCode permissions under `opencode run` (the M1 canary)

Context: DESIGN §16 asked whether `ask` permissions block or auto-deny under `opencode run`, and D006 noted a report
that denies were ignored. The answer decides whether agent permissions are a real second layer.
Finding, from OpenCode 1.18.32's source (`anomalyco/opencode`): `opencode run` auto-rejects every `ask` unless run with
`--auto` or `--dangerously-skip-permissions`, and a rejection ends the agent's turn (`cli/cmd/run.ts`,
`session/processor.ts`). `deny` is enforced before any prompt; the model sees an error and continues
(`permission/index.ts`). The last matching rule wins, so a catch-all `"*"` must come before its exceptions. Bash
compound commands are checked command by command. A `tools:` map in agent frontmatter is deprecated in favor of
`permission:`. Project agents are read from `.opencode/agent/` or `.opencode/agents/`, skills from
`.opencode/skill/<name>/SKILL.md` or `.opencode/skills/`.
Decision: the overseer definition puts `"*": deny` first under `bash`. The old order denied every command, `canopy`
included. It drops the deprecated `tools:` map and denies `task`, since subagents run with their own, wider
permissions. `canopy init` installs to `.opencode/agent/` and `.opencode/skill/`. The live canary
(`tests/canopy/test_opencode_canary.py`) is opt-in (`CANOPY_OPENCODE_CANARY=1`) because it needs a model and spends
tokens. It includes a positive control, so a model that does nothing cannot pass.
Consequences: `ask` is safe to use under `opencode run`: it never hangs a tick, and it behaves as a deny that also
stops the turn. Agent permissions remain defense in depth, not the boundary.
Revisit: when the operator first runs the canary against a real model; record the result here in a new entry. Also on
any OpenCode major version change.

## D022. Runtime files are bundled into the wheel

Context: canopy reads `migrations/` and `.agents/` (prompts, agent definitions, skills) at run time. They live at the
repository root, outside `src/canopy/`, so `uv tool install` would not ship them.
Decision: hatch's `force-include` copies them into the wheel under `canopy/_data/`. `resources.py` looks there first,
then at the repository root for a source checkout or editable install. The layout of DESIGN §5 stays as it is.
Consequences: one place knows where the files are. A new top-level runtime directory needs a `force-include` line.
Revisit: if moving the directories under `src/canopy/` becomes simpler than keeping the two lookups.

## D023. Command templates are split into argv; no shell runs

Context: DESIGN §12 said `{prompt}` is replaced by a shell-quoted string, which implies running the template through a
shell. The prompt contains ticket state the overseer wrote, and later ticket text; a quoting mistake there is command
execution on the operator's machine.
Decision: `shlex.split` the template, then replace `{prompt}` inside each word, and run the argv directly. The template
must contain `{prompt}`.
Consequences: the prompt is always exactly one argument. Templates cannot use pipes, redirection, or `$VAR`; a wrapper
such as a sandbox is written as a prefix (`bwrap ... opencode run ...`) or as a script. Linux caps one argument at
128 KiB, far above today's overseer prompt.
Revisit: if a runtime needs the prompt on stdin or in a file, or the prompt approaches the argument limit.

## D024. The fake agent may start processes

Context: D015 bans `subprocess` everywhere but `procs.py`, tests included. The M1 end-to-end test needs a fake overseer
that runs `canopy decide` and friends, as a real agent does through its bash tool.
Decision: `tests/fakes/agent` imports `subprocess` with a `noqa: TID251` naming this entry. It is a stand-in for an
external agent runtime, not canopy code, and runs as its own process.
Consequences: the e2e test exercises the real CLI in separate processes, environment variables included.
Revisit: if a second fake needs the same, move the exception to `per-file-ignores` for `tests/fakes/`.
