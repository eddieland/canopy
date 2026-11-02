# Decisions

The few choices every developer and agent working on canopy must know, whatever part of the code they work on. It is
kept short so that reading all of it is cheap; every entry added makes that a little less true.

## What belongs here

Most choices do not. An entry earns its place only if an agent working on an unrelated part of canopy could break it,
or reopen it, without knowing. In practice that is one of:

- a constraint or principle that spans the codebase (the layers, the subprocess seam, no network in the harness,
  guards in code);
- a rule the trust boundary relies on, such as one `TRUST_MODEL.md` cites;
- a toolchain choice, or a dependency that code across canopy is shaped around, that handles untrusted input, or
  that would otherwise be proposed again;
- a direction the operator settled that would otherwise be proposed again (build rather than adopt, never PyPI).

Everything else goes where the next person to change that code will look:

- why a feature behaves as it does, and what was rejected for it: the design (`design/`), next to the behavior;
- why a line of code is the way it is: a comment at that line;
- the story of a change: its PR;
- progress, and what a milestone taught: its `Status:`, `Learned:`, and `Next:` lines in `roadmap/`.

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

## D002. canopy will own its worktree pools; treehouse stays until M45's stages prove the replacement

- Slots become git worktrees canopy makes, with leases as journal rows. Until M45's last stage removes it, treehouse
  (holder `canopy:<TICKET>`) is a supported pool, and the default until its third stage changes it.
- Why: treehouse needs Go and an unreleased commit to install (against D067), keeps leases outside the journal, and
  reads config canopy cannot set (D066).
- Kept: worktrees are ephemeral and the pushed branch is the checkpoint; reuse and return keep ignored files.
- Rejected: changing treehouse upstream (still a second toolchain and a second store of leases).

## D003. Connectivity through the agent runtime's MCP and separate programs, not harness code

- The harness imports no tracker or VCS client and holds no token. Agents reach trackers and GitHub through MCP.
- Settled by the operator (2026-10-17, REQUIREMENTS C7): canopy ships separate programs, run as commands with their own
  credentials, that read the tracker and GitHub into the journal (DESIGN §30) and post what the operator approved word
  for word (§29); the harness itself polls nothing.
- Consequence: the harness can check what a connector observed, such as who wrote a comment (DESIGN §7), never more;
  a subject no source observes stays the agents' word.

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
- Revisited (M38, DESIGN §37): the harness decides a ticket in code when every row of §7 holding for it is one it
  decides, and the overseer is refused `decided` on it. A row moves into code one at a time, by a PR citing a
  measurement that shows the derivation right on it; one the harness reads from its journal alone needs none.

## D009. The runtime is a command template, and only its implementation in `canopy.runtime` knows it

- `runtime.*_cmd` are templates, rendered per D023: how a run starts is config, not code.
- What canopy reads and writes of OpenCode, its events, definitions' format, config files, and variables, is in its
  implementations alone, `runtime/opencode/` (OpenCode 1's) and `runtime/opencode2/`, which only
  `runtime/implementation.py` imports; the rest of canopy calls the `runtime` package's surface. `test_layers.py` fails
  on a string naming OpenCode, or an import of it, anywhere else.
- Config's `runtime.version` chooses the implementation every surface call goes to, 1 by default, and the default
  templates are its. A new runtime, or a new major version, is a sibling implementation with its own definitions and
  default templates; still no adapter interface, one runtime at a time.
- Rejected: an adapter interface over several runtimes at once (AGENTS.md, Do not build).
- Revisit: when two runtimes must run side by side.

## D010. Everything runs as the operator

- No bot account. Agent work is marked by branch prefix and a commit trailer the operator may turn off.
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

## D016. Layered config: the workspace file, the user file, the private file; nothing in a code repository

- Defaults, then the workspace's `canopy-workspace.toml` (shared keys only), then the user's `config.toml`, which serves
  every workspace and is optional, then the workspace's private `.canopy/config.toml`, per key.
- canopy runs only from a workspace, even for one repository, and reads no config from a code repository: nothing
  shared is repository-specific, and every operator would otherwise commit or gitignore a `canopy.toml`.
- Keys that run commands, choose prompts, spend, or authorize are private: the user file or the private file, never the
  workspace file, whose `policy.*` may only tighten. A state directory git tracks any file in is refused.
- Rejected: a repository `canopy.toml` (per-repository config that is really per queue); per-workspace keys only in the
  user file (one file overrides every workspace); a gitignored `canopy.local.toml` (easy to commit by accident).

## D017. `pyrefly` strict is the only type checker

- Over `src`, `tests`, and the extensionless fakes.
- Rejected: also running `ty` (two checkers to satisfy for little extra coverage).
- Revisit: if strict costs more than it catches; then relax error kinds, not the project.

## D018. ruff selects every stable rule, and preview rules named one by one, the docstring sections' among them

- `select = ["ALL"]`. Opt out with a commented `ignore` or a `noqa` with a code, never by narrowing.
- Preview rules stay off but for those named one by one under `explicit-preview-rules`, so a ruff bump adds none:
  the pydoclint `DOC` rules (a public function's Returns, Yields, and Raises sections must match its body), and
  others chosen for what they catch here. Add one by naming it.
- Preview mode also turns on preview behavior in stable rules, so a ruff bump can change the lint; fix or opt out then.

## D019. Every test directory is a package

- Without the root `tests/__init__.py`, pytest names `tests/canopy/` `canopy` and shadows `src/canopy`.
- Rejected: `--import-mode=importlib` (changes how `conftest.py` imports, for no gain).

## D020. The overseer reaches the journal through canopy's tools, keyed by `CANOPY_TICK_ID`

- Its verbs are MCP tools canopy serves its run alone (D124, DESIGN §27); it has no shell but the commands the
  operator names in `runtime.allow_bash`, never canopy's own: `dispatch`, `decide`, `attention`, `ticket-set`,
  `review-run`, `review-wait`, `review-end`, `review-revise`, `chore-run`, and `chore-wait`, and no command of the CLI
  does what one does. They refuse without a running tick, so the journal holds only what the loop did.
- Attention items are decisions with action `attention:<reason>`; the list is the latest `ok` tick's, with the
  overseer's items held through a tick that did not give it their subject, and the three it keeps held from the one
  that recorded them until what they name ends them (`decisions.kept`, DESIGN §14, §37). No own table.
- The harness raises the items that need no judgment from their causes, keeping one while an observation it rests on
  is stale, and the overseer's tools refuse it those reasons (`raised`, DESIGN §37).

## D021. How OpenCode enforces permissions under `opencode run`

- `ask` is auto-rejected and ends the turn; `deny` is enforced and the model continues; the last matching rule wins;
  bash compound commands are checked per command. So every catch-all `"*"` comes before its exceptions.
- The overseer denies `task`: subagents run with wider permissions. Permissions are defense in depth, not the boundary.
- Allow tools by name after a catch-all deny rather than deny them by pattern, so a tool nobody listed fails closed.
- Revisit: on any OpenCode major version (the opt-in live canary checks it).

## D023. Command templates are split into argv; no shell runs

- `shlex.split`, substitute `{prompt}` at most once, run the argv. The prompt carries untrusted text.
- A template that places no `{prompt}` gets the prompt on stdin, as the defaults do: Linux caps one argument at 128
  KiB, which a state block with the connectors' observations passes (the operator, 2026-10-22).
- Templates cannot pipe or redirect; a wrapper such as a sandbox is a prefix or a script, and passes stdin through.
- Revisit: if a runtime takes its message only as an argument.

## D025. click for every command line

- canopy's CLI and every program it ships, the workspace members included (the operator, 2026-10-21). Options or
  setup two programs share go in a common workspace member, not copied into each.
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

- An attempt is a `runs` row of that kind, however it ended; a `fix-ci` row counts as a `resume` (DESIGN §8). The
  overseer can run any `canopy` command, and a guard it can reset is not a guard; a human raises a limit in config, or
  one unit's with `canopy grant` (DESIGN §22).
- `--cursor` advances only once the worker starts, so a refused dispatch leaves its trigger for the next tick.
- Revisit: if limits routinely hit healthy tickets; then count per PR.

## D033. Workspaces: one directory, a repository map, pools inside it

- One queue, one capacity, one journal. One repository is a workspace with a map of one (D016).
- No pool root of its own: a fast disk takes the whole workspace, since git keeps each worktree's files in its clone.
- Rejected: one loop per repository (two journals must agree on one ticket); one pool for all repositories; a
  private pool root (treehouse pools by repository and remote URL, so workspaces sharing it share pools).

## D035. Notification sinks are commands fed from the journal

- One message on stdin per tick, derived with no model; an outbox cursor per sink lets a failing sink retry alone.
- Presentation is the sink's: canopy sends fields, and each sink renders them in its channel's native form.
- The harness makes no network call; Slack is a separate process with its own secret file. The desktop sink, holding
  no secret and needing no network, ships inside canopy.
- Rejected: HTTP in the harness (T2); the overseer posting via Slack MCP; interactive Slack (needs a listener).
  Replies read back by a connector, polled outbound, need none (M64).

## D036. A dry run runs every guard and changes nothing the next live tick reads

- Dry dispatches count as running but take no lease and spawn nothing. So `decisions` stays a faithful eval corpus.

## D040. Agents load canopy's definitions from a snapshot canopy owns, never the repository

- An immutable `<state_dir>/runtime/<digest>/`, passed as `OPENCODE_CONFIG_DIR`. A missing agent makes OpenCode
  silently run its allow-everything default.
- Rejected: `OPENCODE_DISABLE_PROJECT_CONFIG` (blocks the repository's skills and MCP servers).

## D041. Layered subpackages; separate programs are uv workspace members

- Imports go down, never between features; only `cli` imports click. Checked by `test_layers.py`.
- Rejected: ruff `TID251` for layers (per-file exemptions for click would also allow `subprocess`).

## D042. The loop is `canopy loop`, in the foreground or detached by `canopy daemon`

- `canopy daemon start` runs the same loop in its own session, its output in `.canopy/daemon.log`. Nothing is
  installed with the OS, nothing restarts it, and it does not start at login (the operator, 2026-10-17).
- Why: pacing stays in the loop. An outside scheduler cannot pace ticks by what they cost.
- Rejected: cron; launchd or systemd units (an install step the operator does not want).

## D043. rich for terminal output

- Rejected: curses (loses scrollback, the loop's record); hand-written ANSI.

## D044. Refuse to start an agent where the repository's OpenCode config defines a canopy agent

- OpenCode deep-merges definitions keeping first-loaded key order, so a repository could put an `allow` before
  canopy's rules. JSONC and substitutions are not parsed (a T7 residual).

## D046. MIT, installed from git, never from PyPI under this name

- `canopy` on PyPI is unrelated; `Private :: Do Not Upload` blocks an upload. `make install-check` checks the install.
- MIT since 2026-10-13, when the repository went public; proprietary before. Unsupported: outside issues and PRs may
  go unanswered.
- Revisit the name before a release meant for others to run.

## D050. Build canopy rather than adopt Symphony, agent-orchestrator, or Hermes Kanban

- None offers any-tracker-via-MCP, never merging, no installed service, released worktrees, and a fresh overseer per tick
  (`PRIOR_ART.md`). Take lessons, not code.

## D051. A dispatch names the queue label it relies on, and the worker checks it again

- Where a `tracker` source observes the ticket, the label must be one it observed, checked in code (`unauthorized`,
  DESIGN §7); without one, `--label` stays a claim. Either way the worker re-reads the labels and fails without changes.

## D053. State directories and snapshots must be private to the operator

- Refuse a symlink, another owner, or group/world access: a shared checkout could plant a journal or a permissive
  snapshot. Checks permissions, not provenance; a state directory git tracks is refused apart (D016).

## D055. Listeners only on loopback or a private network, behind the operator's secret

- Never a wildcard or public address. Whoever holds the secret acts as the operator; listeners lift no guard.
- Revisit: more than one person per machine or listener, or a network the operator does not control.

## D056. A worker may push to an open, non-fork PR the operator wrote and labeled

- Agents check author and label (D003). Never forced, unless the operator sets `trust.rebase` (private): then a
  rebased branch is pushed with `--force-with-lease`, the only force a worker's definition allows.
- The harness's one force of its own: with `trust.max_flaky_kicks` (private), a lease of the rebased branch to rerun
  checks a worker judged flaky, a limited number of times per pushed head (DESIGN §23).
- Rejected: any labeled PR (a label would put commits on a coworker's branch); rebasing by default (merging needs no
  force, and most repositories accept merge commits).

## D058. A ticket's work is units, one per repository

- Each unit has its own PR, phase, cursors, and attempts. Any `implement` may add one, before or after another
  unit's PR merged. At most one per repository, so a follow-up PR is a new ticket.
- One branch per ticket; a desk only for a joint run; `run_slots` holds every run's slots.

## D066. Pool sizes are private config; `workspace sync` converges on them

- treehouse's `max_trees` lives only in committed or global files, so canopy enforces sizes itself.

## D068. Migrations were squashed into one for v0.1; older journals are not upgraded

- A one-time exception. Never edit a shipped migration.

## D069. Worker comments carry a configurable prefix and suffix that only take authority away

- A comment with every mark, outside a quote, is a worker's and never authority. Forging the marks only silences.
- A reply the operator sent through canopy carries no marks: canopy knows it by the comment id the post returned.
- Rejected: an HTML comment marker (Jira drops or escapes it).

## D072. The journal holds every ticket's conversation; authority stays with its source

- Private tickets (`canopy start`) never touch the tracker; only operator messages authorize them.
- On public tickets a tracker comment in the journal authorizes nothing; replies are read live.
- Rejected: a shadow ticket in a private tracker; the journal as source for public tickets (forgeable).

## D073. `canopy loop` serves the web UI from a thread, behind an off switch

- Own journal connection, writes only through CLI functions, never ends the loop on failure.
- Rejected: a separate `canopy serve` (two commands to keep running).

## D074. FastAPI on uvicorn for the web UI's server

- Only `canopy.serve` imports it. Rejected: `http.server` (routing, forms, escaping left to us, in the browser-facing
  package).
- `anyio`, which both run on, is declared too, and confined the same way: `serve` names its exceptions to tell a client
  leaving an event stream from a failure.

## D075. Operator commands are top-level verbs taking a reference to any subject

- `start`, `stop`, `reply`, `show` take a `REF` (ticket, PR, `chore:NAME`, `run:ID`, `task:N`).
- Rejected: a command group per kind.

## D076. Private tickets and the web UI ship without sandboxing or TLS

- The operator accepted the residuals (2026-10-08): guards cannot contain an agent running as the operator; limiting
  untrusted text (T1) is what matters.
- Revisit: with D055, or after a run writes outside its run or posts to a private ticket.

## D077. No agent has web tools

- Every definition denies `webfetch`, `websearch`, `codesearch`. Web content is untrusted text; bash still reaches the
  network (a T1 residual).
- And `execute`, OpenCode 2's code mode, whose code can make HTTP requests; an MCP server an agent needs is set to
  `codemode: false` rather than reached through it (the operator, 2026-10-23).
- Revisit: when workers are sandboxed with egress controls, or if missing lookups measurably hurt runs.

## D079. The web UI is a single-page app in `ui/`

- Vite, React, TypeScript, Tailwind, shadcn/ui, TanStack; types generated from FastAPI's OpenAPI. Built by the wheel's
  hook, which fails without Node rather than build a wheel with no UI: an install from git needs Node. Rules in
  `ui/AGENTS.md`.
- Rejected: Jinja2 with htmx (per-page script drifts); committing the build; building at install; server rendering;
  a wheel without the UI.
- Revisit: if the UI shrinks to pages a template would serve.

## D084. Workers set labels through the tracker's MCP edit tool and deny dangerous MCP tools by name

- Merge, review, close, transition, delete, fork, and workflow tools are denied. Both workers create follow-ups
  (D123): the public one's create tools are not denied, and the private one's are allowed by name after its tracker
  wildcard. `test_definitions.py` checks.
- Rejected: `gh --add-label` (GitHub-only); allowing GitHub's `issue_write` by default (it also closes issues).
- Revisit: when GitHub's server gains a label-only tool.

## D085. The version comes from the latest `v*` tag (uv-dynamic-versioning)

- Pushing the tag is the whole release step, so tag and version cannot disagree. Build-time dependency only.
- Every package canopy ships takes it, the workspace members under `packages/` too; none writes a static version.
- Rejected: a static version checked against the tag; hatch-vcs (pulls in setuptools).
- Revisit: if a build that matters runs without tags (shallow clone).

## D086. `canopy forget` clears a ticket's branch and units but keeps every run

- Runs drive attempt limits (D030), so forgetting them would be a reset. Operator-only; closes no PR.
- Revisit: if operators routinely raise a limit to restart a forgotten ticket; then count attempts per branch.

## D089. Untrusted reviewers' feedback waits for the operator's go-ahead

- `trust.trusted_reviewers` (private, empty by default; `canopy:review` for canopy's reviewer). Anyone else's
  feedback is `untrusted_review` attention until the operator answers with `canopy reply` or the web UI.
- Checked in code where the `vcs` source observes the PR fresh (DESIGN §7): a `resume` for `review` must cover a
  trusted reviewer's item or a trusted canopy review, and anyone else's only with an operator message after it among
  those it carries; else `unauthorized`. Unobserved, it is the prompt's. With `policy.feedback_plan = "approve"`
  (DESIGN §32) the go-ahead is the approval of a feedback plan instead, in code, and trust only informs the operator.
- Rejected: an untrusted list (new bots trusted until noticed); the go-ahead as a tracker comment.

## D093. Every public worker hears the operator's messages

- `implement` and `resume` carry `{{OPERATOR_MESSAGES}}`. An override without it is `bad_prompt` only once
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
  cannot write (DESIGN §24).
- Rejected: `checkout -B` (git 2.43 lets two worktrees hold one branch, so a commit in either moves both).
- Revisit: if an operator's `runtime.pr_skill` tool needs a local branch.

## D113. The web UI links URLs in journal text, and only to themselves

- An http or https URL in untrusted text becomes a link whose text is the URL as written; no other scheme, and no
  Markdown or link syntax, so a link never shows one destination and opens another. A GitHub PR's address in a
  conversation or a finding is its `PullRequestLink`, named from the URL alone (`acme/web#88`).
- Why: workers and trackers write PR and CI URLs into their prose, and copying them out was the common next step.
- Rejected: rendering Markdown (labelled links hide their target); a linkify library (a regex and `URL.canParse` do it).
- Revisit: if journal text should link ticket keys or `repo#N` references to their pages as well.

## D114. canopy's reviews post nothing the operator has not published, word for word

- The reviewer has no write tool and reports only its result line, kept in the journal. A review of a PR the loop does
  not own reaches the PR only as a version of its draft the operator publishes, unmarked (DESIGN §34). Settled by the
  operator; revisited for M43, 2026-10-20.
- Why: a review on the PR speaks in the operator's name, so only what they read and chose posts; no agent writes it.
- Rejected: one identified comment per commit with a marker (the M11 design); repository automation on the verdict.
- Revisit: with a bot identity.

## D115. The web UI's branch links default to the GitHub page a clone URL implies

- A repository's GitHub `url` gives `https://github.com/OWNER/REPO/tree/{branch}` unless its map sets `branch_url`.
  This one URL format is the only host knowledge in the harness; it builds a link and calls nothing. Settled by the
  operator.
- Why: most workspaces are GitHub, and a link that needs a template per repository is a link nobody configures.
- Rejected: templates only (more config for the common case); formats for other hosts (a template covers them).
- Revisit: if a second host is common enough to want its own default.

## D116. A worker may push more than once in a run; it still never polls CI or retries a rejected push

- A worker pushes again for anything it fixes after a push, in a new commit, never an amend. Settled by the operator.
- Why: under "push once", a worker that found its own lint error after pushing left it for a `resume` for CI, or
  for nobody when the check is not in CI. Extra pushes cost a CI run each; the run timeout still bounds them.
- Unchanged: no CI polling, no retry loop on a rejected push, and the harness's own fallback push happens once.

## D117. The sandbox wrapper ships with canopy; `canopy sandbox setup` installs a pinned `srt` with npm

- `canopy-sandbox` and its templates are a workspace member (D041); the harness reads the templates, never runs it.
- `srt` is Node: `npm ci --ignore-scripts` from a lockfile canopy ships, into `~/.local/share/canopy/`, which a worker
  cannot write. A new `srt` is a lockfile change. Root-only steps are printed, never run.
- Rejected: `npm install -g` (unpinned, shared with the operator's own); bundling `srt` (it needs Node regardless).
- Revisit: if `srt` ships a standalone binary, or the sandbox stops being opt-in.

## D118. The sandbox is an opt-in prefix on the command templates, and the boundary for the runs it wraps

- The harness never learns whether a run is sandboxed, beyond adding the prefix itself for a repository the private
  `runtime.sandbox_repos` names (the operator's ask, 2026-10-23); it passes only `CANOPY_GIT_OBJECTS`, which an
  unsandboxed run ignores. Every agent command can be wrapped, the overseer's too, since the tick starts every run it
  asks for (DESIGN §40); its role writes, of the state, the journal's files alone.
- What the harness runs on the host after a run (git, treehouse) reads nothing a sandboxed run can write (TRUST_MODEL
  T4): a new step in a slot keeps D107's flags and runs after `_run`'s link and `commondir` check.
- Revisit: making it the default, once the canary passes on the operator's machines and a day of sandboxed runs.

## D119. Under `tracker.private`, a labeled ticket's first dispatch writes its start record

- The loop writes a start record, which only the operator's commands wrote before, when the operator set the switch
  and a ticket canopy never ran is dispatched on a queue label. Settled by the operator.
- No worker re-reads the label after that, and removing it does not stop the ticket; `canopy stop` does (TRUST_MODEL
  T1's residual).
- Rejected: the label authorizing every run (more code: phases and replies without a start record); keeping the
  worker's label check for such tickets (the operator chose an ordinary private ticket).

## D120. The plan editor is Tiptap on ProseMirror, in the web UI alone

- `@tiptap/*`, pinned, with `marked` under `@tiptap/markdown`, edits a plan as a document (DESIGN §25); nothing else
  imports it, and it loads only with the page that edits a plan. Comments are ours, anchored by their words.
- Why: selection, undo, tables, and highlights that follow edits are a ProseMirror's worth of code, and a hand-made
  `contenteditable` is a known trap. It renders by schema, so model text stays text: HTML and images are characters,
  and a link does not navigate (D113).
- Rejected: Lexical and Milkdown (less control of the Markdown written back); a textarea beside a preview (the
  operator asked for editing in place); Tiptap's paid comments extension (it anchors by position).
- Revisit: if Tiptap's license or its Markdown changes, or a second editor is wanted.

## D121. Code is highlighted by Shiki, in the web UI alone

- `shiki`, pinned, with its JavaScript regex engine (no WebAssembly) and a curated list of grammars, each loaded on
  demand, for a diff's code and the guide's code blocks (ui/DESIGN.md, "A review", "The guide"). Its tokens are data,
  rendered as React text with our `syntax-*` tokens, never its HTML, so a PR's text stays text.
- Why: an editor's TextMate grammars, for every language a PR touches; a tokenizer of our own per language is far
  more code and reads worse.
- Rejected: Prism (its grammars register on a global, and are rougher than an editor's), highlight.js (returns
  HTML), Lezer (no TOML, shell, or SQL without CodeMirror).
- Revisit: if its core grows past what the page should load, or diffs need grammars it does not have.

## D122. The web UI's public demo serves mock data only

- `canopy.serve.demo` serves the fixtures (`serve/mock/`) under public host names with no listener secret, on a host
  that runs the app itself (Vercel, `vercel_app.py`). `ServeOptions` refuses `public_hosts` without `mock`, so the
  loop's server never takes one (TRUST_MODEL T8).
- Why: anyone can try the latest UI, at no cost on Vercel's free plan; the fixtures hold nothing of the operator's.
- Rejected: a static build over a mock written again in TypeScript (a second mock that drifts from the API).
- Revisit: if the demo should show anything but fixtures, which T8 would then govern as a listener.

## D123. Workers may file follow-up tickets, which authorize nothing

- An `implement` or `resume` worker, public or private, may create tickets for work outside its own and report them;
  canopy records them and tells the operator once (`follow_ups.filed`), and works one only once a human labels or
  starts it, as any ticket (DESIGN §18, TRUST_MODEL T1). Settled by the operator (2026-10-19): workers notice and
  ask, humans authorize.
- Rejected: working a follow-up under its parent's label (a worker would authorize work for itself); a `canopy` verb
  that records one (anything with a shell could).
- Revisit: if asking about each follow-up proves noise the operator wants gone; then bound them per ticket.

## D124. canopy serves MCP itself, over stdio only, to the overseer, a chore, and the reviewer and planner

- `canopy _mcp` is a child of the overseer's run and opens no socket, so it is no listener (TRUST_MODEL T8). It lists
  no tool and refuses every call under `CANOPY_RUN_ID` or outside a running tick (D020). A tool is one request and one
  function (`loop/tools.py` and its siblings, `loop/*_tools.py`); a read a command also prints, a chore's history,
  shares the command's, so they cannot drift apart.
- With `--chore` it serves a chore's run one tool, its own chore's history, and nothing of the overseer's (DESIGN §27).
- With `--reports` it serves a chore's run canopy's read-only reports, and nothing of the overseer's (DESIGN §27).
- With `--git NAME=PATH` it serves a review's or a plan's run read-only git in the checkouts the harness names, alone.
- It and the local artifact store speak the protocol through one workspace member, `canopy-mcp`, never a copy each.
- Rejected: the `mcp` SDK (a runtime dependency with its own async stack and HTTP transports, for five methods); any
  transport but stdio; tools for workers, whose results are read after they exit (DESIGN §27).
- Revisit: if the overseer needs more of MCP than tools, or a runtime that cannot start a stdio server.

## D125. Every journal query is built with `core/sql.py`, from literal SQL and bound values

- Each clause's text is a `LiteralString` and each value a `?`, so the type checker refuses SQL built from data; a
  name chosen at run time comes from a `Literal` or `sql.name`. Clauses stay written in SQL, so a query still reads
  as one. Settled by the operator (2026-10-20), in place of f-strings and their `noqa: S608`.
- Rejected: SQLAlchemy Core (a schema to keep beside the migrations, and an engine canopy does not need); PyPika (a
  dependency for what one module of ours does); f-strings with a reason on each (a promise no checker holds).
- Revisit: if a feature builds queries from what the operator picks at run time, such as arbitrary filters.

## D126. Trivial work is planned; only its own planner may spare the operator's review

- Every ticket `policy.plan` plans is planned, trivial or not; only the operator's `canopy plan KEY --skip` waives one.
  Under the private `policy.planner_may_approve`, the planner that wrote a plan may say it needs no review, and the
  harness approves it as the planner's; no other agent approves or waives a plan (DESIGN §25, TRUST_MODEL T1).
- Why: the operator (2026-10-20) found that M55's triage judged too few tickets trivial for its runs to save what they
  cost, while the planner has read the ticket and the code already, at no run of its own (#1050).
- Rejected: a cheaper agent judging trivial work before the plan, with its verdict waiving it (M55, built and removed).
- Revisit: when the spend page shows plan runs on tickets the operator calls trivial costing enough that a cheaper
  judge would pay for its own runs.

## D127. A web write needs no CLI verb when no command would use it

- The web UI writes through `canopy.core`'s functions and their guards, and TRUST_MODEL T8 names every write; one that
  only a page would make, such as marking a review seen, gets no CLI verb to match it.
- Why: the operator (2026-10-20) found a verb nobody would type, `canopy seen`, to be surface kept for a rule's sake.
- Rejected: a CLI verb for every web write (`canopy seen`, built and removed).
- Revisit: before a page-only write that authorizes work, which T8 would then have to guard as the CLI's verbs are.

## D128. The web channel writes only named config keys: limits within ceilings, trust only stricter

- An allowlist by key name in `serve/config_edit.py`, never a section; a new key is not writable until named. Only the
  workspace's private file (M49), never the workspace file or the user file. Settled by the operator (ROADMAP M41).
- Why: a config write outlives the listener secret. A raised limit is spend, bounded by a ceiling; an added replier or
  reviewer would steer workers after a new secret, so trust settings only tighten.
- Nothing that runs a command, picks a prompt, is read as words, or moves the listener. No CLI verb: it would be in
  reach of the overseer's `canopy *` rule.

## D129. tomlkit edits the private config in place

- `tomllib` only reads. tomlkit keeps the operator's comments and layout through a write; only `canopy.serve` imports
  it (`tests/canopy/test_layers.py`).
- Rejected: writing the file anew with the stdlib (comments lost); a file of canopy's own layered after the private
  file (a hand edit to the private file would be silently overridden).

## D130. Every program canopy ships makes its HTTP requests through `canopy-http`

- One client, on httpx2: bound to one origin, following no redirect, trusting the system's certificates, and telling
  a request that never left from one that may have been carried out, so only what cannot happen twice is sent again.
- The harness imports neither it nor httpx2 (`tests/canopy/test_layers.py`), as it imports no stdlib network module.
- Rejected: urllib in each program (its errors escape `OSError`, so a reply cut off crashed a run; each copy drifted).

## D131. A plan's or the guide's Mermaid diagram is drawn by mermaid, as an image, in the web UI alone

- `mermaid`, pinned, draws a plan's or a guide page's ```` ```mermaid ```` fence (flowchart, sequence, and state
  diagrams only); only `ui/src/lib/diagram.ts` imports it, on demand. Its code stays the document: comments, the diff,
  and the file see it.
- A plan is model text (T1), so mermaid runs `strict`, with SVG labels, and its config locked against the diagram's own.
- What is shown is only ever an `<img>` of its SVG: an image runs no script, follows no link, and fetches nothing, so
  a gap in mermaid's sanitizer reaches nothing shown. While drawing, mermaid lays the SVG out off screen in the page,
  where `strict` is the guard.

## D132. Traces go through OpenTelemetry behind `infra/tracing.py`, and are off until the operator turns them on

- Every span is a `tracing.span`; only `infra` imports OpenTelemetry (`tests/canopy/test_layers.py`), and only once
  `telemetry.traces` is on, so a process that traces nothing loads none of it.
- A span holds canopy's own facts, never text it read (T2): a span that raised names its exception's type alone.
- `procs` passes the current span to every child as `TRACEPARENT`, so a detached run is traced under its tick.
- Spans stay on the machine, in the state directory; sending them off it would be a separate opt-in, and a T2 change.
