# canopy

> Working name. `canopy` on PyPI is an unrelated project, so canopy installs from this repository (D046). Rename
> before any index release.

An unattended, local agent loop driven by your issue tracker.

Label a ticket. When there is capacity, an overseer agent leases a worktree from
a [treehouse](https://github.com/kunchenguid/treehouse) pool, dispatches a worker
agent to do the work, pushes a branch, opens a PR, and releases the worktree.
CI failures and review comments are picked up on later ticks. A running
attention list tells you what actually needs a human.

Everything runs on your machine, under your credentials. No hosted service holds
standing write access to your repositories, your tracker, or your internal tools.

**Status:** pre-alpha, under construction. See [docs/ROADMAP.md](docs/ROADMAP.md). What it must do, and how far
along each requirement is: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).

## Why this exists

- Hosted "label a ticket, get a PR" agents cannot reach systems behind your own
  auth, and require granting a vendor write access to your code and tracker.
  canopy runs where your credentials already are.
- Juggling checkouts is the real daily cost of running several agents at once.
  treehouse already solves that; canopy builds on it instead of reinventing it.
- Orchestration is a prompt, not a workflow engine. The overseer decides what to
  do each tick from live state, so ticket dependencies and branch stacking need
  no DSL and no schema change.

## Install (target: five steps, no more)

1. Install [treehouse](https://github.com/kunchenguid/treehouse) from source at the commit canopy needs:
   `CGO_ENABLED=0 go install github.com/kunchenguid/treehouse@1185dc6cc50e1b66ef5c74b8ac677a6251258abc` (in a canopy
   checkout, `make treehouse` does the same). No release has the lease output canopy reads yet, and `treehouse update`
   installs a release binary that needs glibc 2.34+.
2. Install canopy. Either:
   - From a release, with no credential, Python, or uv on the machine that runs canopy (D067). Where you are signed in
     to GitHub, download `canopy-<platform>` from the
     [latest release](https://github.com/eddieland/canopy/releases/latest) (or `gh release download --repo
     eddieland/canopy --pattern 'canopy-linux-x86_64*'`), check it against its `.sha256`, and copy it to the machine
     as `~/.local/bin/canopy` (`mkdir -p ~/.local/bin` first if it is missing, and put it on `PATH` if it is not).
     Make it executable and link the sinks to it:
     `cd ~/.local/bin && chmod +x canopy && ln -sf canopy canopy-notify-desktop && ln -sf canopy canopy-notify-slack`.
     On macOS, a browser download needs `xattr -d com.apple.quarantine canopy` too. To upgrade, replace the file.
   - Or from git: `uv tool install git+https://github.com/eddieland/canopy`. The repository is private; git needs an
     HTTPS credential for it, as for any private clone. Not `uv tool install canopy`: that name on PyPI is another
     project. To upgrade, run the same command with `--reinstall`.
3. In your agent runtime (OpenCode), connect the GitHub MCP server and your tracker's MCP server (Jira, Linear, anything
   with one; for GitHub Issues the GitHub server is both). Your runtime holds the tokens; canopy never sees them.
   Workers need write tools to comment on a ticket, edit its labels, and open PRs; the reviewer, to comment on a PR.
   Grant nothing more: canopy's definitions deny the dangerous ones by name, but names differ by server. On GitHub
   the only tool that sets labels, `issue_write`, also creates and closes issues; without it, PRs go unlabeled (D084).
4. In your repository: `canopy init`. This writes your personal config (`$XDG_CONFIG_HOME/canopy/config.toml`, by
   default `~/.config/canopy/config.toml`, with a queue label of your own), writes a shared `canopy.toml` if the
   repository has none, and installs nothing else: agent runs load canopy's agent definitions and skills from its own
   directory (D040). Use an HTTPS remote with a credential helper; init warns if `origin` pushes over SSH, which worker
   sandboxing is not expected to support (D038).
5. Add your label (`agent-ready-<you>` by default) to a ticket, then run `canopy loop --dry-run --ticks 1` and read the
   plan. Once you trust it, leave `canopy loop` running: it ticks, waits `loop.interval_minutes` (15 by default), and
   repeats until you press Ctrl-C. It also serves the web UI at `http://127.0.0.1:8765/`; `canopy secret` prints the
   listener secret its sign-in page asks for.

## Daily surface

- Keep `canopy loop` running in a terminal (tmux works). Each tick prints what it decided and what joined or left the
  attention list. Press `t` while it waits to tick now.
- Open the web UI it serves, `http://127.0.0.1:8765/` by default: the attention list, the runs, each pool's worktrees,
  and every ticket's conversation, where you reply, start, and stop as with the CLI. Sign in once per browser with the
  secret `canopy secret` prints. `[serve]` in your user config moves it, to a private address too, or turns it off; so
  does `canopy loop --no-serve` (DESIGN §22, TRUST_MODEL T8).
- Label tickets with your queue label. Each operator has their own, so two loops never work one ticket.
- Answer the agent's questions as comments on the ticket. `canopy show KEY` shows any ticket's conversation, with
  canopy's copy of its comments.
- Or work a ticket privately, say one a client filed: `canopy start KEY` needs no label, and nothing canopy writes
  reaches the ticket. Its workers' reports and questions stay in canopy: `canopy show KEY` reads them, `canopy reply
  KEY 'answer'` answers, and `canopy stop KEY` stops it (DESIGN §22).
- Put your queue label on a PR you wrote by hand, and canopy fixes its CI and addresses its trusted reviewers'
  comments as it does on its own PRs, pushing to the PR's branch without force. Its workers ask you in canopy, never
  on the PR: `canopy show REPO#N` and `canopy reply REPO#N 'answer'`, such as `api#42` (DESIGN §23).
- To have canopy start a ticket over, close its PR and delete its branch, then run `canopy forget KEY`: its next
  implement starts on a new branch. Its earlier runs still count toward the attempt limits (DESIGN §22).
- Review PRs. Humans approve and merge; the agent never does. Only reviewers in `trust.trusted_reviewers` send a
  worker back to a PR on their own; anyone else's comments, a review bot's included, wait on the attention list as
  `untrusted_review` until you say what to do with `canopy reply KEY 'use your judgement on the bot's review'` or the
  web UI. The reply stays in canopy, never on the ticket (DESIGN §7).
- Read the attention list: `canopy status`, or `~/.canopy/attention.md`. To be told when it changes, add a notification
  sink to your user config: `canopy-notify-desktop` for desktop notifications, `canopy-notify-slack` for a Slack
  channel, or a command of your own; `canopy notify test` checks them (DESIGN §20).
- Read what a tick decided and what its overseer cost, or what a dry run would have done: `canopy decisions [TICK]`;
  add `--ticket KEY` to filter. `canopy loop` prints each tick's cost as it goes.
- See what recent runs did: `canopy status` lists each one's outcome, PR, summary, cost, and OpenCode session id, which
  `opencode export <id>` turns into its transcript.
- Optionally, turn on reviews in your user config (`[review]`): a fresh agent reviews each new commit of the loop's own
  PRs, or of PRs your query names, and posts one comment saying what it found. It never approves (DESIGN §21).
- Optionally, define chores in your user config: recurring checks, such as the health of the build queue, that the
  overseer runs when due and that report findings to the attention list (DESIGN §19).
- Ask your own agent session about the loop. `canopy skill` prints a skill that teaches it canopy's commands, files,
  and journal; save it where your runtime reads skills, such as `~/.agents/skills/canopy/SKILL.md`, and again after
  upgrading.

## Several repositories

When one queue's tickets land in several repositories, make a workspace instead of running canopy in each: in an empty
directory, `canopy init --workspace --provider jira https://github.com/acme/api.git https://github.com/acme/web.git`
lists each repository in `canopy-workspace.toml` and clones it under `repos/`. Then write a one-line summary for each
there and describe them in `MAP.md`, for the overseer. `canopy workspace add URL...` adds more later. To size each
repository's worktree pool, set `capacity.slots_per_repo` (and per repository, `[capacity.repo_slots]`) in your user
config, before init to have init make them. Sync makes the workspace match what is declared: it clones what the map
lists, makes or removes idle slots, and removes a clone the map no longer lists when nothing in it would be lost;
`--dry-run` shows what it would do. Run `canopy loop` from the workspace. The overseer picks the repositories each
ticket needs. Most tickets change one; a change that cannot land in parts is worked jointly, one worker opening a linked
PR in each repository; and one that builds on another repository's merged PR is worked there next. To have a ticket
split into one ticket per repository instead, comment on it asking for a split: a worker creates the children unlabeled,
and you label each one you want worked. The pools, journal, and attention list live inside the workspace. See
`examples/canopy-workspace.toml` and [docs/DESIGN.md](docs/DESIGN.md) §18.

## Troubleshooting

- If canopy cannot find `treehouse`, check that it is on `PATH` (usually by adding `$(go env GOPATH)/bin`). If it is
  outdated, rerun the pinned install from step 1 above or run `make treehouse` in a canopy checkout.
- If the overseer records `skip` with `mcp_unavailable: github`, configure the GitHub MCP server in your agent runtime.
- For more detail, check `canopy decisions`, `canopy status`, and the effective log path reported by canopy's command
  output.

## How it works, briefly

```
canopy loop
  take the loop lock
  until Ctrl-C:
    canopy tick (below)
    print what it did, then wait loop.interval_minutes

canopy tick
  acquire lock, run migrations
  reconcile: dead workers, stale leases
  run the overseer agent:
    read the world (tracker and GitHub via MCP, treehouse pool)
    derive each ticket's phase
    decide a next action per ticket
    dispatch workers up to capacity
    update the attention list
  exit
```

canopy has no tracker code. Agents reach the tracker through its MCP server, guided by a short provider-neutral contract
and, where it helps, a provider skill (Jira and GitHub Issues ship). See [docs/DESIGN.md](docs/DESIGN.md) §17.

State lives in a SQLite journal. Facts about the world (ticket status, PRs,
CI, reviews) are always re-read from their source of truth, never from the DB.
Details in [docs/DESIGN.md](docs/DESIGN.md). Security posture in
[docs/TRUST_MODEL.md](docs/TRUST_MODEL.md).

## Related work

- **treehouse**: worktree pool with durable leases. Required dependency.
- **firstmate** (same author as treehouse): an interactive tmux captain/crew
  orchestrator. Different shape: canopy is unattended and queue-driven.
- **GitHub Copilot coding agent, Atlassian Rovo Dev**: hosted equivalents. See
  "Why this exists".
- **OpenAI Symphony, agent-orchestrator, Hermes Agent Kanban**: open-source loops that dispatch agents from a
  tracker or board. Why canopy is built anyway, and what their issue trackers taught: D050 and
  [docs/PRIOR_ART.md](docs/PRIOR_ART.md).

## License

Proprietary, all rights reserved, for now (D046). See [LICENSE](LICENSE). Revisit before any public release.
