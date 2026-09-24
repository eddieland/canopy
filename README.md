# canopy

> Working name. Rename freely; check PyPI and Homebrew collisions before publishing.

An unattended, local agent loop driven by your issue tracker.

Label a ticket. When there is capacity, an overseer agent leases a worktree from
a [treehouse](https://github.com/kunchenguid/treehouse) pool, dispatches a worker
agent to do the work, pushes a branch, opens a PR, and releases the worktree.
CI failures and review comments are picked up on later ticks. A running
attention list tells you what actually needs a human.

Everything runs on your machine, under your credentials. No hosted service holds
standing write access to your repositories, your tracker, or your internal tools.

**Status:** pre-alpha, under construction. See [docs/ROADMAP.md](docs/ROADMAP.md).

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

1. Install [treehouse](https://github.com/kunchenguid/treehouse).
2. Install canopy: `uv tool install canopy`.
3. In your agent runtime (OpenCode), connect the GitHub MCP server and your tracker's MCP server (Jira, Linear, anything
   with one; for GitHub Issues the GitHub server is both). Your runtime holds the tokens; canopy never sees them.
4. In your repository: `canopy init`. This writes your personal config (`$XDG_CONFIG_HOME/canopy/config.toml`, by
   default `~/.config/canopy/config.toml`, with a queue label of your own), writes a shared `canopy.toml` if the
   repository has none, installs the overseer and worker agent definitions, and installs the tracker skill for your
   provider if one ships. Use an HTTPS remote with a credential helper; init warns if `origin` pushes over SSH, which
   worker sandboxing is not expected to support (D038).
5. Add your label (`agent-ready-<you>` by default) to a ticket, then run `canopy loop --dry-run --ticks 1` and read the
   plan. Once you trust it, leave `canopy loop` running: it ticks, waits `loop.interval_minutes` (15 by default), and
   repeats until you press Ctrl-C.

## Daily surface

- Keep `canopy loop` running in a terminal (tmux works). Each tick prints what it decided and what joined or left the
  attention list.
- Label tickets with your queue label. Each operator has their own, so two loops never work one ticket.
- Answer the agent's questions as comments on the ticket.
- Review PRs. Humans approve and merge; the agent never does.
- Read the attention list: `canopy status`, or `~/.canopy/attention.md`. Set `notify.cmd` to have changes piped to a
  command of your own.
- Read what a tick decided, or what a dry run would have done: `canopy decisions [TICK]`.

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

## License

Not yet decided. Do not add a `LICENSE` file until it is.
