# Decisions

The few choices every developer and agent working on canopy must know, whatever part of the code they work on. It is
kept short so that reading all of it is cheap; every entry added makes that a little less true.

## What belongs here

Most choices do not. An entry earns its place only if an agent working on an unrelated part of canopy could break it,
or reopen it, without knowing. In practice that is one of:

- a constraint or principle that spans the codebase (the layers, the subprocess seam, no network in the harness,
  guards in code);
- a rule the trust boundary relies on, such as one `TRUST_MODEL.md` cites;
- a runtime dependency or a toolchain choice;
- a direction the operator settled that would otherwise be proposed again (build rather than adopt, never PyPI).

Everything else goes where the next person to change that code will look:

- why a feature behaves as it does, and what was rejected for it: the design (`design/`), next to the behavior;
- why a line of code is the way it is: a comment at that line;
- the story of a change: its PR;
- progress, and what a milestone taught: its `Status:`, `Learned:`, and `Next:` lines in `ROADMAP.md`.

A new feature, command, config key, default, or mechanism is not a decision by itself. When in doubt, leave it out:
an entry that turns out to matter can be added later, and one that does not costs every future reader.

## Format

An entry is a title that states the decision and two to four bullets:

- what we chose, if the title does not already say it;
- `Why:` only when it is not obvious;
- `Rejected:` alternatives worth not reconsidering, one line;
- `Revisit:` what would reopen it, one line.

No history of how we got here, no list of what the change touched, no restating DESIGN. If it takes a paragraph, it
belongs in DESIGN or the PR. A changed choice edits its entry in place, so the log reads as what is true now; the old
text is in git history. Numbers are never reused, so gaps are entries that were pruned; a file that cannot change,
such as a shipped migration, may still cite one, and git history has its text.

## D002. treehouse is the worktree pool

- Hard dependency: pooled worktrees, durable leases (holder `canopy:<TICKET>`), dirty detection, JSON, no daemon.
- Worktrees are ephemeral; the pushed branch is the checkpoint.
- Revisit: if treehouse's lease semantics change incompatibly.

## D003. Connectivity through the agent runtime's MCP, not harness code

- The harness imports no tracker or VCS client and holds no token. Agents reach trackers and GitHub through MCP.
- Consequence: the harness cannot verify anything the tracker says, such as who wrote a comment.
- Revisit: if the overseer's token cost for reading state dominates; then move polling into Python.

## D004. SQLite journal plus flock, not a stateless overseer

- SQLite (WAL, numbered migrations) holds loop facts; world facts are re-read every tick. `flock` around the tick.
- Rejected: state in ticket comments and labels (slow, noisy for teammates, unqueryable).

## D005. Release worktrees aggressively

- A slot is held only while a worker process runs, never while waiting on CI, review, or a human.
- Workers always push before release, so build caches must not depend on the slot.

## D006. OpenCode is the agent runtime

- Built-in MCP with OAuth, per-agent permissions, `opencode run --agent`, and the team uses it.
- Rejected: Pi (MCP needs an extension, putting connectivity code back in our hands).

## D007. Python with uv

- Python 3.12+, uv, ruff, pytest, stdlib first. Isolated `uv tool install`, stdlib `sqlite3` and `tomllib`.
- Rejected: Go.

## D008. Policy in prompts, guards in code

- What to do about a ticket lives in the overseer prompt; what the loop may never do lives in dispatch guards and agent
  permissions. A prompt cannot relax a guard.
- Revisit: if prompt behavior proves unstable; then move one rule at a time into code.

## D009. The runtime is a command template, not an adapter

- `runtime.*_cmd` are templates with `{prompt}` (rendered per D023), so another runtime is a config change.
- Revisit: when a second runtime needs different invocation or result parsing.

## D010. Everything runs as the operator

- No bot account. Agent work is marked by branch prefix, PR label, and commit trailer.
- Revisit: when audit or compliance requires a distinct identity.

## D014. Tracker-agnostic: MCP plus a contract, with optional provider skills

- Config names a free-form `tracker.provider` and `tracker.query`; DESIGN §17 is the contract; provider knowledge goes
  in optional `tracker-<provider>` skills.
- The label, not the query, authorizes work. Ticket keys are regex-guarded: they reach branch names, paths, and argv.
- Revisit: a tracker that needs code gets an entry before the code.

## D015. The subprocess boundary is enforced by lint

- ruff `TID251` bans `subprocess`, `os.system`, `os.popen` outside `infra/procs.py`, tests included (the fake agent
  opts out with a `noqa`, so a fake overseer can run the real CLI).
- Revisit: if anything reaches for `os.exec*`, `os.spawn*`, or `pty`; ban them too.

## D016. Layered config: the workspace file, then the user file; nothing in a code repository

- Defaults, then the workspace's `canopy-workspace.toml` (shared keys only), then the user's `config.toml`, per key.
- canopy runs only from a workspace, even for one repository, and reads no config from a code repository: nothing
  shared is repository-specific, and every operator would otherwise commit or gitignore a `canopy.toml`.
- Keys that run commands, choose prompts, spend, or authorize are user-only; the workspace file's `policy.*` may only
  tighten.
- Rejected: a repository `canopy.toml` (per-repository config that is really per queue); tracker keys in the user file
  (one file overrides every workspace); a gitignored `canopy.local.toml` (easy to commit by accident).

## D017. `pyrefly` strict is the only type checker

- Over `src`, `tests`, and the extensionless fakes.
- Rejected: also running `ty` (two checkers to satisfy for little extra coverage).
- Revisit: if strict costs more than it catches; then relax error kinds, not the project.

## D018. ruff selects every stable rule

- `select = ["ALL"]`, no preview rules. Opt out with a commented `ignore` or a `noqa` with a code, never by narrowing.

## D019. Every test directory is a package

- Without the root `tests/__init__.py`, pytest names `tests/canopy/` `canopy` and shadows `src/canopy`.
- Rejected: `--import-mode=importlib` (changes how `conftest.py` imports, for no gain).

## D020. The overseer reaches the journal through the CLI, keyed by `CANOPY_TICK_ID`

- `dispatch`, `decide`, and `attention` refuse without a running tick, so the journal holds only what the loop did.
- Attention items are decisions with action `attention:<reason>`; the list is the latest `ok` tick's. No own table.

## D021. How OpenCode enforces permissions under `opencode run`

- `ask` is auto-rejected and ends the turn; `deny` is enforced and the model continues; the last matching rule wins;
  bash compound commands are checked per command. So every catch-all `"*"` comes before its exceptions.
- The overseer denies `task`: subagents run with wider permissions. Permissions are defense in depth, not the boundary.
- Allow tools by name after a catch-all deny rather than deny them by pattern, so a tool nobody listed fails closed.
- Revisit: on any OpenCode major version (the opt-in live canary checks it).

## D023. Command templates are split into argv; no shell runs

- `shlex.split`, substitute `{prompt}` exactly once, run the argv. The prompt carries untrusted text.
- Templates cannot pipe or redirect; a wrapper such as a sandbox is a prefix or a script.
- Revisit: if the prompt must go on stdin or nears Linux's 128 KiB argument limit.

## D025. click for the CLI

- Exit codes: usage and config errors 2, refusals 1. `decide [KEY] ACTION` parses positionals by hand.
- Rejected: argparse (the CLI grows every milestone).

## D026. pydantic for config and other programs' output

- Per-file scope and tighten checks stay plain code before the merge (TRUST_MODEL T7); pydantic validates the result.
- Rejected: pydantic-settings (its env and dotenv sources are the back door T7 closes).

## D029. Runs are detached `python -m canopy _run`, claimed by pid, serialized by flock

- Spawned in a new session and process group, which reconcile kills before returning the slot.
- `dispatch.lock` (not SQLite's write lock) covers guards through spawn, so `_run` can still close its row.
- Revisit: if pid reuse is ever observed; then compare process start times.

## D030. Attempt limits and cooldowns are derived from `runs`, with no reset

- An attempt is a `runs` row of that kind, however it ended. The overseer can run any `canopy` command, and a guard it
  can reset is not a guard; a human raises a limit in config, or one unit's with `canopy grant` (DESIGN §22).
- `--cursor` advances only once the worker starts, so a refused dispatch leaves its trigger for the next tick.
- Revisit: if limits routinely hit healthy tickets; then count per PR.

## D033. Workspaces: one directory, a repository map, pools inside it

- One queue, one capacity, one journal. One repository is a workspace with a map of one (D016).
- No pool root of its own: a fast disk takes the whole workspace, since git keeps each worktree's files in its clone.
- Rejected: one loop per repository (two journals must agree on one ticket); one pool for all repositories; a
  user-only pool root (treehouse pools by repository and remote URL, so workspaces sharing it share pools).

## D035. Notification sinks are commands fed from the journal

- One message on stdin per tick, derived with no model; an outbox cursor per sink lets a failing sink retry alone.
- Presentation is the sink's: canopy sends fields, and each sink renders them in its channel's native form.
- The harness makes no network call; Slack is a separate process with its own secret file. The desktop sink, holding
  no secret and needing no network, ships inside canopy.
- Rejected: HTTP in the harness (T2); the overseer posting via Slack MCP; interactive Slack (needs a listener).

## D036. A dry run runs every guard and changes nothing the next live tick reads

- Dry dispatches count as running but take no lease and spawn nothing. So `decisions` stays a faithful eval corpus.

## D040. Agents load canopy's definitions from a snapshot canopy owns, never the repository

- An immutable `<state_dir>/runtime/<digest>/`, passed as `OPENCODE_CONFIG_DIR`. A missing agent makes OpenCode
  silently run its allow-everything default.
- Rejected: `OPENCODE_DISABLE_PROJECT_CONFIG` (blocks the repository's skills and MCP servers).

## D041. Layered subpackages; separate programs are uv workspace members

- Imports go down, never between features; only `cli` imports click. Checked by `test_layers.py`.
- Rejected: ruff `TID251` for layers (per-file exemptions for click would also allow `subprocess`).

## D042. The loop is `canopy loop` in the foreground

- Not a daemon: no detaching, pid file, or self-restart. An outside scheduler cannot pace ticks by what they cost.
- Rejected: cron, launchd.

## D043. rich for terminal output

- Rejected: curses (loses scrollback, the loop's record); hand-written ANSI.

## D044. Refuse to start an agent where the repository's OpenCode config defines a canopy agent

- OpenCode deep-merges definitions keeping first-loaded key order, so a repository could put an `allow` before
  canopy's rules. JSONC and substitutions are not parsed (a T7 residual).

## D046. Proprietary, installed from git, never from PyPI under this name

- `canopy` on PyPI is unrelated; `Private :: Do Not Upload` blocks an upload. `make install-check` checks the install.
- The repository is public to read, still unlicensed for use and unsupported (2026-10-13).
- Revisit: before a release meant for others to run, together with the name.

## D050. Build canopy rather than adopt Symphony, agent-orchestrator, or Hermes Kanban

- None offers any-tracker-via-MCP, never merging, no daemon, released worktrees, and a fresh overseer per tick
  (`PRIOR_ART.md`). Take lessons, not code.

## D051. A dispatch names the queue label it relies on, and the worker checks it again

- `--label` is a claim the harness cannot verify (D003); the worker re-reads the labels and fails without changes.

## D053. State directories and snapshots must be private to the operator

- Refuse a symlink, another owner, or group/world access: a shared checkout could plant a journal or a permissive
  snapshot. Checks permissions, not provenance.

## D055. Listeners only on loopback or a private network, behind the operator's secret

- Never a wildcard or public address. Whoever holds the secret acts as the operator; listeners lift no guard.
- Revisit: more than one person per machine or listener, or a network the operator does not control.

## D056. A worker may push to an open, non-fork PR the operator wrote and labeled

- Agents check author and label (D003). Never forced.
- Rejected: any labeled PR (a label would put commits on a coworker's branch).

## D058. A ticket's work is units, one per repository

- Each unit has its own PR, phase, cursors, and attempts. Any `implement` may add one, before or after another
  unit's PR merged. At most one per repository, so a follow-up PR is a new ticket.
- One branch per ticket; a desk only for a joint run; `run_slots` holds every run's slots.

## D066. Pool sizes are user config; `workspace sync` converges on them

- treehouse's `max_trees` lives only in committed or global files, so canopy enforces sizes itself.

## D067. Releases ship one executable per platform, built by CI

- A pex in a scie with interpreter and locked dependencies: no Python, uv, credential, or network on the target.
- Rejected: PyInstaller, Nuitka, shiv, zipapp (break `sys.executable -m canopy`); PyApp, uvbox (install from network).

## D068. Migrations were squashed into one for v0.1; older journals are not upgraded

- A one-time exception. Never edit a shipped migration.

## D069. Worker comments carry a configurable prefix and suffix that only take authority away

- A comment with every mark, outside a quote, is a worker's and never authority. Forging the marks only silences.
- Rejected: an HTML comment marker (Jira drops or escapes it).

## D072. The journal holds every ticket's conversation; authority stays with its source

- Private tickets (`canopy start`) never touch the tracker; only operator messages authorize them.
- On public tickets the mirror authorizes nothing; replies are read live.
- Rejected: a shadow ticket in a private tracker; the journal as source for public tickets (forgeable).

## D073. `canopy loop` serves the web UI from a thread, behind an off switch

- Own journal connection, writes only through CLI functions, never ends the loop on failure.
- Rejected: a separate `canopy serve` (two commands to keep running).

## D074. FastAPI on uvicorn for the web UI's server

- Only `canopy.serve` imports it. Rejected: `http.server` (routing, forms, escaping left to us, in the browser-facing
  package).

## D075. Operator commands are top-level verbs taking a reference to any subject

- `start`, `stop`, `reply`, `show` take a `REF` (ticket, PR, `chore:NAME`, `run:ID`).
- Rejected: a command group per kind.

## D076. Private tickets and the web UI ship without sandboxing or TLS

- The operator accepted the residuals (2026-10-08): guards cannot contain an agent running as the operator; limiting
  untrusted text (T1) is what matters.
- Revisit: with D055, or after a run writes outside its run or posts to a private ticket.

## D077. No agent has web tools

- Every definition denies `webfetch`, `websearch`, `codesearch`. Web content is untrusted text; bash still reaches the
  network (a T1 residual).
- Revisit: when workers are sandboxed with egress controls, or if missing lookups measurably hurt runs.

## D079. The web UI is a single-page app in `ui/`

- Vite, React, TypeScript, Tailwind, shadcn/ui, TanStack; types generated from FastAPI's OpenAPI. Built by the wheel's
  hook when npm is present, so operators never need Node. Rules in `ui/AGENTS.md`.
- Rejected: Jinja2 with htmx (per-page script drifts); committing the build; building at install; server rendering.
- Revisit: if the UI shrinks to pages a template would serve.

## D081. The overseer mirrors comments through a quoted heredoc with a per-tick random delimiter

- No comment can end the heredoc. Workers' marks are read in code; at most 100 mirrors per tick.
- Rejected: the body as a quoted argument (one missed escape runs it); a fixed delimiter.

## D084. Workers set labels through the tracker's MCP edit tool and deny dangerous MCP tools by name

- Merge, review, close, transition, create, delete, fork, and workflow tools are denied; `test_definitions.py` checks.
- Rejected: `gh --add-label` (GitHub-only); allowing GitHub's `issue_write` by default (it also closes issues).
- Revisit: when GitHub's server gains a label-only tool.

## D085. The version comes from the latest `v*` tag (uv-dynamic-versioning)

- Pushing the tag is the whole release step, so tag and version cannot disagree. Build-time dependency only.
- Rejected: a static version checked against the tag; hatch-vcs (pulls in setuptools).
- Revisit: if a build that matters runs without tags (shallow clone).

## D086. `canopy forget` clears a ticket's branch and units but keeps every run

- Runs drive attempt limits (D030), so forgetting them would be a reset. Operator-only; closes no PR.
- Revisit: if operators routinely raise a limit to restart a forgotten ticket; then count attempts per branch.

## D089. Untrusted reviewers' feedback waits for the operator's go-ahead

- `trust.trusted_reviewers` (user-only, empty by default; `canopy:review` for canopy's reviewer). Anyone else's
  feedback is `untrusted_review` attention until the operator answers with `canopy reply` or the web UI.
- Enforced by prompt only: the harness cannot read a comment's author (D003).
- Rejected: an untrusted list (new bots trusted until noticed); the go-ahead as a tracker comment.
- Revisit: if the overseer dispatches without a go-ahead; then a `--review-from` claim checked like `--label`.

## D093. Every public worker hears the operator's messages

- `implement`, `fix-ci`, and `resume` carry `{{OPERATOR_MESSAGES}}`. An override without it is `bad_prompt` only once
  the ticket has a message, so older overrides keep working.
- Revisit: if overrides are rare enough to require the placeholder outright.

## D107. Every git the harness runs has hooks, the filesystem monitor, submodule fetches, and `ext::` off

- `-c` flags from `core/hostgit.py`, which outrank any config; a test fails on a `"git"` literal anywhere else.
- Why: slots share a git directory a worker can write, and `fetch` alone runs `reference-transaction` hooks.
- Rejected: flags only on the calls after the worker (the next run's `fetch` is the same exposure).
- Revisit: if a repository needs a hook on the harness's fallback push (Git LFS); the worker's own push runs hooks.

## D109. Runs check out detached and push HEAD by refspec; no run makes a local branch

- `_run` checks out `origin/<branch>` or `origin/<base>` detached; workers and the fallback push use
  `git push origin HEAD:refs/heads/<branch>`.
- Why: a pool's slots share branch refs, so a run's local branch is state other slots see and a sandboxed worker
  cannot write (HOST_ISOLATION §4.2).
- Rejected: `checkout -B` (git 2.43 lets two worktrees hold one branch, so a commit in either moves both).
- Revisit: if an operator's `runtime.pr_skill` tool needs a local branch.

## D113. The web UI links URLs in journal text, and only to themselves

- An http or https URL in untrusted text becomes a link whose text is the URL as written; no other scheme, and no
  Markdown or link syntax, so a link never shows one destination and opens another.
- Why: workers and trackers write PR and CI URLs into their prose, and copying them out was the common next step.
- Rejected: rendering Markdown (labelled links hide their target); a linkify library (a regex and `URL.canParse` do it).
- Revisit: if journal text should link ticket keys or `repo#N` references to their pages as well.

## D114. canopy's reviews post nothing; they live in the journal

- The reviewer has no write tool and reports only its result line. Its findings reach the operator through
  `canopy review show` and a worker through `resume --review-run`, never the PR or the ticket. Settled by the operator.
- Why: a review on the PR speaks in the operator's name before they have seen it; kept local it needs no write grant.
- Rejected: one identified comment per commit with a marker (the M11 design); repository automation on the verdict.
- Revisit: with a bot identity, or once the operator wants the web UI's shadow review (ROADMAP M32) published.
