# Decisions

Why canopy is the way it is, for a developer about to change it. Not a changelog, not a design doc, not a PR
description.

Write less. An entry is a title that states the decision and two to four bullets:

- what we chose, if the title does not already say it;
- `Why:` only when it is not obvious;
- `Rejected:` alternatives worth not reconsidering, one line;
- `Revisit:` what would reopen it, one line.

No history of how we got here, no list of what the change touched, no restating DESIGN. If it takes a paragraph, it
belongs in DESIGN or the PR. A changed choice edits its entry in place, so the log reads as what is true now; the old
text is in git history. Numbers are never reused, so gaps are entries that were pruned.

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

- ruff `TID251` bans `subprocess`, `os.system`, `os.popen` outside `infra/procs.py`, tests included (except D024).
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
- Revisit: on any OpenCode major version (the opt-in live canary checks it).

## D022. Runtime files are bundled into the wheel

- hatch `force-include` puts `migrations/` and `.agents/` under `canopy/_data/`. A new runtime directory needs a line.

## D023. Command templates are split into argv; no shell runs

- `shlex.split`, substitute `{prompt}` exactly once, run the argv. The prompt carries untrusted text.
- Templates cannot pipe or redirect; a wrapper such as a sandbox is a prefix or a script.
- Revisit: if the prompt must go on stdin or nears Linux's 128 KiB argument limit.

## D024. The fake agent may start processes

- `tests/fakes/agent` imports `subprocess` (`noqa: TID251`) so a fake overseer can run the real CLI.

## D025. click for the CLI

- Exit codes: usage and config errors 2, refusals 1. `decide [KEY] ACTION` parses positionals by hand.
- Rejected: argparse (the CLI grows every milestone).

## D026. pydantic for config and other programs' output

- Per-file scope and tighten checks stay plain code before the merge (TRUST_MODEL T7); pydantic validates the result.
- Rejected: pydantic-settings (its env and dotenv sources are the back door T7 closes).

## D027. hypothesis for property tests of validators (dev only)

- For validators between agent-written text and paths, argv, and prompts. Its first run found `$` matching before a
  trailing newline.

## D028. The harness raises attention for failed runs; retrying needs an authorized reply

- Raised when a ticket's latest run crashed, went unpushed, timed out, or failed; cleared by a newer run or done.
- The prompt forbids redispatch until an authorized replier comments; the attempt limit (D030) is the hard bound.

## D029. Runs are detached `python -m canopy _run`, claimed by pid, serialized by flock

- Spawned in a new session and process group, which reconcile kills before returning the slot.
- `dispatch.lock` (not SQLite's write lock) covers guards through spawn, so `_run` can still close its row.
- Revisit: if pid reuse is ever observed; then compare process start times.

## D030. Attempt limits and cooldowns are derived from `runs`, with no reset

- An attempt is a `runs` row of that kind, however it ended. The overseer can run any `canopy` command, and a guard it
  can reset is not a guard; a human raises a limit in config.
- `--cursor` advances only once the worker starts, so a refused dispatch leaves its trigger for the next tick.
- Revisit: if limits routinely hit healthy tickets; then count per PR.

## D031. `--context` points at what to read; it is not a file and not a quote

- At most 2000 characters. A path could pull any operator-readable file into a prompt; quoting invites injection.

## D032. An attention item is its ticket, reason, and repository, notified once while open

- The overseer rewording an item does not re-notify. Only a zero exit within 60 seconds counts as sent.
- Revisit: if operators want reminders for long-open items.

## D033. Workspaces: one directory, a repository map, pools inside it

- One queue, one capacity, one journal. One repository is a workspace with a map of one (D016).
- No pool root of its own: a fast disk takes the whole workspace, since git keeps each worktree's files in its clone.
- Rejected: one loop per repository (two journals must agree on one ticket); one pool for all repositories; a
  user-only pool root (treehouse pools by repository and remote URL, so workspaces sharing it share pools).

## D034. Chores: recurring non-ticket runs the operator defines and the overseer schedules

- User config only. The harness refuses one not due, running, or over `max_chores`. No lease, no push, no write
  tools; findings go to attention. Not "task", which is OpenCode's subagent tool.
- Rejected: cron (no guards, journal, or judgment); the overseer checking inline.

## D035. Notification sinks are commands fed from the journal

- One message on stdin per tick, derived with no model; an outbox cursor per sink lets a failing sink retry alone.
- The harness makes no network call; Slack is a separate process with its own webhook file.
- Rejected: HTTP in the harness (T2); the overseer posting via Slack MCP; interactive Slack (needs a listener).

## D036. A dry run runs every guard and changes nothing the next live tick reads

- Dry dispatches count as running but take no lease and spawn nothing. So `decisions` stays a faithful eval corpus.

## D037. A tick-wide skip closes the tick `skipped` and leaves attention standing

- An outage (tracker or GitHub unreachable) must not resolve and re-raise every item.

## D038. Recommend HTTPS remotes; `canopy workspace sync` warns about SSH and refuses nothing

- A sandboxed worker cannot reach the SSH agent socket.
- Revisit: when the sandbox ships.

## D039. Reviews: a fresh reviewer per PR commit that comments as itself and never approves

- One comment ending in a verdict marker; approve, push, label, and edit tools are denied. The loop trusts its journal,
  not the marker.
- Rejected: a GitHub review (the line-comment tool can approve); a status or label verdict (can set any).

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

## D045. Stacking checks the base's shape in code; the overseer picks it each dispatch

- `--base` must be `trust.branch_prefix` plus one component, so a PR cannot target a release branch.
- The base is chosen from live PR state, not stored. A retargeted PR merges the base in; no force-push.

## D046. Proprietary, installed from git, never from PyPI under this name

- `canopy` on PyPI is unrelated; `Private :: Do Not Upload` blocks an upload. `make install-check` checks the install.
- Revisit: before any public release, together with the name.

## D047. `canopy skill` prints the operator's skill; agent runs do not load it

- In the snapshot it would help no run, and a `$HOME` copy would collide with it by name.

## D048. treehouse is pinned to a commit

- Commit `1185dc6`: canopy requires the lease's `base_branch`, which no release had.
- Revisit: when a treehouse release includes `base_branch`.

## D050. Build canopy rather than adopt Symphony, agent-orchestrator, or Hermes Kanban

- None offers any-tracker-via-MCP, never merging, no daemon, released worktrees, and a fresh overseer per tick
  (`PRIOR_ART.md`). Take lessons, not code.

## D051. A dispatch names the queue label it relies on, and the worker checks it again

- `--label` is a claim the harness cannot verify (D003); the worker re-reads the labels and fails without changes.

## D053. State directories and snapshots must be private to the operator

- Refuse a symlink, another owner, or group/world access: a shared checkout could plant a journal or a permissive
  snapshot. Checks permissions, not provenance.

## D054. `policy.stacking` is `"auto"` or `"never"`, enforced by prompt only

- Under `"never"` a blocker has landed only when closed and its PR, if any, merged; a PR closed unmerged gives the
  dependent ticket `needs_author`.
- Revisit: if the overseer stacks under `"never"`; then add a harness guard.

## D055. Listeners only on loopback or a private network, behind the operator's secret

- Never a wildcard or public address. Whoever holds the secret acts as the operator; listeners lift no guard.
- Revisit: more than one person per machine or listener, or a network the operator does not control.

## D056. A worker may push to an open, non-fork PR the operator wrote and labeled

- Agents check author and label (D003). Never forced.
- Rejected: any labeled PR (a label would put commits on a coworker's branch).

## D058. A ticket's work is units, one per repository

- Each unit has its own PR, phase, cursors, and attempts. Any `implement` may add one, before or after another
  unit's PR merged. At most one per repository, so a follow-up PR is a new ticket.

## D059. One branch per ticket; a desk only for a joint run; `run_slots` holds every run's slots

## D060. Pending migrations wait for runs an earlier canopy started

- Applied only when no run of any kind has a live process; until then commands fail naming them.

## D061. A multi-repository ticket stays one ticket; split only on an authorized request

- `--request <comment id>` is verified by the splitter; children get no queue label, so a human authorizes each.
- Rejected: a split label (anyone who can label could add it).

## D062. A split runs in a desk at the base branches and records only new children

- Own `runtime.split_cmd` and attempt limit; no branch, no push. A child must be new to the journal and not the parent.

## D063. A chore names the workspaces it runs in; by default every one

- Rejected: a chore table per workspace.

## D064. The desktop sink ships inside canopy; Slack stays separate

- Slack is separate because it holds a secret and needs the network; the desktop sink needs neither.

## D065. The reviewer reads its checkout through a link in a directory of its own

- `<state_dir>/reviews/<id>/` with `external_directory: deny`, so the PR supplies no runtime config.

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

## D070. A merge conflict is the unit phase `conflicted`, handled by `resume`

- GitHub runs no checks on a conflicting PR, so it read as green. Derived before CI and review.
- Rejected: a separate dispatch kind; rebasing (needs force).

## D071. A run's session and cost come from OpenCode's JSON events

- One invalid cost drops the whole cost rather than understating it.
- Revisit: when OpenCode changes the event shape or a second runtime lands.

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

## D078. Workers open PRs with the operator's skill when `runtime.pr_skill` names one

- Missing skill fails the run; an override without `{{OPEN_PR}}` is `bad_prompt`.
- Rejected: a harness command that opens PRs (VCS knowledge in code).
- Revisit: if more single steps need the operator's tooling; then generalize.

## D079. The web UI is a single-page app in `ui/`

- Vite, React, TypeScript, Tailwind, shadcn/ui, TanStack; types generated from FastAPI's OpenAPI. Built by the wheel's
  hook when npm is present, so operators never need Node. Rules in `ui/AGENTS.md`.
- Rejected: Jinja2 with htmx (per-page script drifts); committing the build; building at install; server rendering.
- Revisit: if the UI shrinks to pages a template would serve.

## D080. The private worker is its own template and definition, with the tracker's read tools allowed by name

- `"<server>_*": deny`, then each `tracker.read_tools` entry allowed, so an unlisted write tool fails closed.
- Rejected: denying write tools by name pattern (an unexpected name stays open).
- Revisit: if a tracker multiplexes reads and writes through one tool (Atlassian's `execute`).

## D081. The overseer mirrors comments through a quoted heredoc with a per-tick random delimiter

- No comment can end the heredoc. Workers' marks are read in code; at most 100 mirrors per tick.
- Rejected: the body as a quoted argument (one missed escape runs it); a fixed delimiter.

## D082. The browser signs in once with the listener secret and keeps a signed cookie

- `HttpOnly`, `SameSite=Strict`, HMAC-signed, 30 days; no server sessions. `canopy secret --rotate` signs everyone out.
- Rejected: a one-time link; the secret held by the page (`EventSource` sends no headers); server-side sessions.
- Revisit: with D055, or when sessions must end one at a time.

## D083. The loop paces idle ticks from the journal

- Wait doubles after each idle tick up to `loop.idle_max_minutes`, ends at a gate (fix-ci cooldown, chore `due_at`),
  and wakes early on operator messages and on runs ending after the tick's `ticks.read_at`.
- A cap not above `base` turns all of it off, gates and run wakes included, so today's pacing is one setting away; an
  unset cap under a longer interval does the same rather than fail an existing config.
- Rejected: polling GitHub or the tracker in Python (D003); a cheap pre-check agent; quiet hours; webhooks (T8).
- Revisit: if the cap's latency on teammates' comments or CI is felt.

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

## D087. `canopy init` writes only keys whose default does not serve

- A written default is pinned and goes stale when canopy changes it. `examples/config.toml` documents every key.

## D088. Pressing `t` at the loop's countdown ticks now

- Skips the one-minute wake floor (which guards against message bursts); a keypress is deliberate. Stdlib `termios`.
- Rejected: a TUI library for one key.

## D089. Untrusted reviewers' feedback waits for the operator's go-ahead

- `trust.trusted_reviewers` (user-only, empty by default; `canopy:review` for canopy's reviewer). Anyone else's
  feedback is `untrusted_review` attention until the operator answers with `canopy reply` or the web UI.
- Enforced by prompt only: the harness cannot read a comment's author (D003).
- Rejected: an untrusted list (new bots trusted until noticed); the go-ahead as a tracker comment.
- Revisit: if the overseer dispatches without a go-ahead; then a `--review-from` claim checked like `--label`.

## D090. The worktrees page reads treehouse on request and every 30 seconds while visible

- `treehouse status --json` per pool on each `GET /api/worktrees`; refetched on `runs.updated` and every 30 seconds in
  a visible tab (the UI's one `refetchInterval`). Each read briefly takes the pool's lock.
- Rejected: a journal snapshot (stale, needs a migration); reading treehouse on the event stream (cost per open page).
- Revisit: if lock time shows up in leases, or treehouse can push changes.

## D092. `make test` runs in parallel with pytest-xdist

- About 200s to 60s. In `make test`, not `addopts`, so one test under a debugger stays serial.
- Revisit: if a test needs shared state; then an xdist group, never a serial-only suite.

## D093. Every public worker hears the operator's messages

- `implement`, `fix-ci`, and `resume` carry `{{OPERATOR_MESSAGES}}`. An override without it is `bad_prompt` only once
  the ticket has a message, so older overrides keep working.
- Revisit: if overrides are rare enough to require the placeholder outright.

## D094. The web UI looks like an operations inbox, in IBM Plex

- Counters and severity over a list beside its thread; IBM Plex Sans and Mono. Replaces the instrument panel.
- Rejected: the other six directions in `docs/ui-explorations/2026-10-08-style/`.
- Revisit: if the ops inbox layout reads worse than the panels it replaces.

## D095. The web UI's spend is the last 24 hours, by start, of what the journal records

- Runs, chore runs, and ticks that started in the 24 hours before now, each counted in full by its start; the stream
  resends it when the cost changes, not as the window moves.
- Rejected: a calendar day (whose midnight); by end (a running run's cost would be missing until it ended).
- Revisit: when M13 designs the budget; the counter then shows the budget's own unit and window.

## D096. The `review` cursor is a time, not an id

- It covers reviews, inline review comments, and canopy's review runs, which no one id sequence orders; the cursor
  holds the newest handled item's time, `YYYY-MM-DDTHH:MM:SSZ`, and `--cursor review=` refuses anything else.
- Why: with ids the overseer guessed which items were new, and replays flipped an attention item tick to tick.
- Rejected: a cursor per kind (review runs still need their own); `kind:id` values (still no order across kinds).
- Revisit: if two reviewers' items in the same second are seen to hide one; then a time plus id.

## D097. A tick records the newest message it read; the web UI shows what no `ok` tick has

- `ticks.message_id`, set before the harness items: an operator message after the latest `ok` tick's waits for the
  next tick, which is when the attention list catches up (§14). The list itself stays the latest `ok` tick's.
- Rejected: comparing `messages.at` with `ticks.started_at` (a tick reads messages after reconcile, not at its start);
  dropping an answered `awaiting_reply` from the served list at once (the UI and `canopy status` would disagree).
- Idle pacing (D083) reads it too: an operator message after the previous tick's is one that tick could not have seen.

## D098. `canopy chore try` runs outside every guard and records nothing

- The operator's, for writing a chore: the same as running its command by hand, with canopy's prompt and result check.
- Rejected: recording it as a chore run (a test result would clear real findings and reset `not_due`); applying the
  guards (a chore being written would wait out `every_minutes`).
- Revisit: if the loop gets a way to call it, or operators want a try's findings kept.

## D099. A chore's days and hours are a guard in code; `when` keeps the judgment

- `days`, `hours`, and `timezone` move `due_at` to the window's next opening and refuse `outside_hours`.
- Why: clock times need no model, and outside them `due` is false, so the overseer records no `wait` every tick.
- Rejected: an overnight window (`22:00-06:00`), until someone needs one; cron syntax (a schedule, where
  `every_minutes` is a floor).

## D100. The operator's notes to a chore are messages on its subject, carried into its next prompts

- `canopy reply chore:NAME`; the latest 10 go into every run's `## Run` section, as instructions.
- Rejected: editing the prompt file (a note is about this week's findings); clearing notes after a run (a note "until
  the 15th" must outlast one); a dismiss per finding (the agent, not the harness, knows whether a finding is the same).
- Revisit: if operators need a note to end without writing another.

## D101. Screenshot baselines are made on CI, by a workflow run on demand that pushes them

- `screenshots.yml`: run on a branch, it updates the baselines with ci.yml's Chromium and fonts and commits the PNGs.
- Why: a local machine or an agent's container renders text differently, so its baselines fail CI.
- Two jobs: the branch's code runs with a read-only token; the job that pushes runs none of it and commits only PNGs.
- Rejected: a Playwright Docker image (CI does not use one); updating on every PR push (a visual change is deliberate).

## D102. Flaky CI is judged by a separate `triage-ci` run, the only run that reruns CI

- It reads a new failure before `fix-ci`, then reruns the failed jobs or reports the failure real. No edits, no
  pushes, no slot.
- Why: the agent that can push never gets a rerun tool, and flakes spend their own attempts, not `fix-ci`'s.
- Rejected: triage inside `fix-ci` (the worker gains reruns and holds a slot to rerun); the overseer judging (it would
  read CI logs while holding dispatch).
- Revisit: if the tick between a `real` verdict and its `fix-ci` is measured as a real cost.

## D103. The operator turns reruns on; the repository says what is flaky

- `policy.max_triage_ci_attempts` defaults to 0, which a repository cannot loosen. `runtime.triage_skill` names a skill
  the repository or the operator provides, read from the unit's primary clone, never the PR's branch.
- Rejected: a repository turning reruns on (the first shared key that loosens policy, T7); the PR's branch (a PR would
  write its own judge); a named but missing skill falling back to general rules (fails toward hiding regressions).
- Revisit: when a repository needs to refuse reruns an operator turned on.

## D104. A tick's page names its overseer output's file and does not serve it

- The web UI shows what the journal holds; `ticks/<id>.log` is agent output from a file, unbounded and unchecked.
- Rejected: serving the file, or its tail (a new file-reading surface behind the listener for a debugging aid).
- Revisit: if the operator debugs overseer runs from the browser often enough to want it.

## D105. Setup that needs the run's branch is `runtime.setup_cmd`, run by `_run` after checkout

- In each slot of a worker run, before the worker; a failure or timeout ends the run `crashed`. Not for splits or
  reviews. No placeholders; `CANOPY_REPO` names the slot's repository and `CANOPY_BRANCH` the run's branch.
- Why: treehouse's `post_create` runs on the base before `_run` checks out the branch; a failing hook keeps the lease.
- Rejected: an upstream treehouse hook (treehouse never sees the run's branch); a command per repository (one command
  reads `CANOPY_REPO`).
- Revisit: if a broken setup spending an attempt on every ticket it meets proves common.

## D106. canopy does not stop a slot's Bazel server; `startup --max_idle_secs` in the operator's `.bazelrc` does

- Why: the harness knows no build tool, and a server stopped at return is cold for a run that reuses the slot at once.
- Rejected: `bazel shutdown` when a slot is returned; a release command in config, for what one Bazel flag does.
- Revisit: if idle servers still exhaust memory with a short idle timeout.

## D107. Every git the harness runs has hooks, the filesystem monitor, submodule fetches, and `ext::` off

- `-c` flags from `core/hostgit.py`, which outrank any config; a test fails on a `"git"` literal anywhere else.
- Why: slots share a git directory a worker can write, and `fetch` alone runs `reference-transaction` hooks.
- Rejected: flags only on the calls after the worker (the next run's `fetch` is the same exposure).
- Revisit: if a repository needs a hook on the harness's fallback push (Git LFS); the worker's own push runs hooks.

## D108. A run whose slot's `.git` file changed is `crashed`, runs no more git, and the file is put back

- `_run` reads it before any git step; after the worker, a change skips the push check in every slot of the run.
- Why: a repointed link moves host git to a directory the worker owns, past D107's flags; treehouse runs git there.
- Rejected: leaving the slot leased for a human (reconcile returns it, running treehouse's git anyway).
- Revisit: when a sandbox denies writing the link (HOST_ISOLATION §4.2); this stays as the check for a policy gap.

## D109. Runs check out detached and push HEAD by refspec; no run makes a local branch

- `_run` checks out `origin/<branch>` or `origin/<base>` detached; workers and the fallback push use
  `git push origin HEAD:refs/heads/<branch>`.
- Why: a pool's slots share branch refs, so a run's local branch is state other slots see and a sandboxed worker
  cannot write (HOST_ISOLATION §4.2).
- Rejected: `checkout -B` (git 2.43 lets two worktrees hold one branch, so a commit in either moves both).
- Revisit: if an operator's `runtime.pr_skill` tool needs a local branch.

## D110. Sandboxed runs push over HTTPS; the sandbox allows no Unix sockets

- An operator with SSH remotes runs workers unsandboxed or switches to HTTPS, which `canopy init` already recommends.
- Why: `srt` on Linux can allow Unix sockets only all at once (`allowAllUnixSockets`), which would open the Docker
  socket and every other along with the SSH agent's.
- Rejected: all sockets; pushing from the host in `_run` (more host-side git in a slot a worker wrote, D107).
- Revisit: if `srt` gains per-path socket rules on Linux, or an operator cannot use HTTPS.

## D111. The Slack sink can post with a bot token as well as a webhook

- `--channel` switches to `chat.postMessage`; the token lives in its own operator-only file, like the webhook URL.
- Why: some workspaces disallow incoming webhooks, and one app token can serve several channels and sinks.
- Rejected: the token in an environment variable or canopy's config (the harness would see it, T2); user tokens.
- Revisit: when threads per ticket (§20, two-way) need the sink to report what it posted on stdout.

## D112. The web UI's forget needs the ticket's key typed, checked by the server

- Forget cannot be undone from the UI, so one more click (as Stop now asks) is too easy; the server refuses
  `not_confirmed` too, so no client skips the challenge.
- Rejected: a browser `confirm()` dialog (ui/DESIGN.md: never); a client-only check.
- Revisit: if forget gains an undo.
