# canopy

[![codecov](https://codecov.io/gh/eddieland/canopy/graph/badge.svg)](https://codecov.io/gh/eddieland/canopy)

An unattended, local agent loop that takes a ticket from your issue tracker to a green, reviewed PR, and keeps it there
until you merge it.

Start a ticket in canopy, or label it in your tracker. canopy can plan the work first and revise the plan with you until
it is right, before any worker spends a run on code. Then it implements the plan and opens the PR, and keeps the PR
moving: it fixes red CI, brings in a base that moved, and answers review comments, each in a fresh run on the same
branch. You step in only where judgment is needed: shaping and approving the plan, answering a worker's question,
deciding what to do with a comment from someone you have not trusted, and approving and merging. A running attention
list tells you which of those is waiting on you.

canopy reviews other people's PRs the same way, on request: its reviewer reads the PR, you revise the review with an
agent until it says what you mean, and only then is it posted, as your own. Beside the loop, it runs one-off tasks in
your own words, scheduled chores that report what matters and change nothing, and notifications on your desktop or in
Slack.

Everything runs on your machine, under your credentials. No hosted service holds standing write access to your
repositories, your tracker, or your internal tools.

> Not on PyPI: `canopy` there is an unrelated project. Install canopy from this repository.

![The web UI's Attention page: what needs you, the selected item's conversation, and the working runs](ui/e2e/screenshots.spec.ts-snapshots/attention-dark-root-linux.png)

## Why this exists

- Hosted "label a ticket, get a PR" agents cannot reach systems behind your own auth, and they require granting a
  vendor write access to your code and tracker. canopy runs where your credentials already are.
- Getting the first PR up is the easy part. The daily cost of running several agents is everything after: checkouts to
  juggle, CI to watch, review comments to route back, and remembering which PR is waiting on whom. canopy owns that
  stretch and leaves you the decisions.
- Orchestration is a prompt, not a workflow engine. Each tick, an overseer agent decides what to do from live state,
  so ticket dependencies and branch stacking need no DSL. The guards are code, whatever the overseer asks for:
  capacity, attempt limits, cooldowns, one worker per ticket, and never approving or merging a PR.

## The loop

```text
you start a ticket in canopy, or label it in your tracker
  -> plan (optional)        -> you reply with changes and it plans again, or edit it, until you approve it
  -> implement              -> the worker pushes a branch and opens the PR
  -> the PR waits on CI and reviewers, holding no worktree
       CI red, or a conflict with its base  \
                                             > resume: a fresh run on the same branch, then wait again
       a reviewer you trust comments        /  (canopy's own reviewer, if you trust it)
       anyone else comments                 -> attention: you say what to do with it
  -> green and reviewed     -> attention: you approve and merge
  -> merged                 -> done
```

The web UI's guide, [How the loop works](ui/src/guide/how-the-loop-works.md), tells the rest, and
[docs/design/](docs/design/README.md) the design.

## Install (target: five steps, no more)

Or let your own coding agent (Claude Code, OpenCode, ...) walk you through them in an interview, from making the
workspace to a first dry tick, with the sandbox if you want it: [docs/QUICKSTART.md](docs/QUICKSTART.md).

1. **Install treehouse** from source, at the commit canopy needs:

   ```sh
   CGO_ENABLED=0 go install github.com/kunchenguid/treehouse@1185dc6cc50e1b66ef5c74b8ac677a6251258abc
   ```

   In a canopy checkout, `make treehouse` does the same. Do not use a release or `treehouse update`: no release has the
   lease output canopy reads yet, and the release binary needs glibc 2.34+.

2. **Install canopy** from git, with [uv](https://docs.astral.sh/uv/). It needs Node 22.12+ and npm on `PATH` (with
   nvm: `nvm install 22`), because the install builds the web UI:

   ```sh
   uv tool install git+https://github.com/eddieland/canopy
   ```

   Not `uv tool install canopy`: that name on PyPI is another project. To upgrade, run the same command with
   `--reinstall`.

3. **Connect your MCP servers.** In your agent runtime (OpenCode), connect the GitHub MCP server and your tracker's MCP
   server (Jira, Linear, anything with one; for GitHub Issues the GitHub server is both). Your runtime holds the
   tokens; canopy never sees them. To run OpenCode 2 (2.1.4 or later), set `version = 2` under `[runtime]` in your
   user config, and give each of those servers `"codemode": false`, since canopy's agents are denied code mode.

   Grant only what the agents need. Workers need write tools to comment on a ticket, edit its labels, and open PRs;
   the reviewer needs only read tools. canopy's agent definitions deny the dangerous tools by name, but names differ by
   server. On GitHub, the only tool that sets labels, `issue_write`, also creates and closes issues; without it, PRs go
   unlabeled.

4. **Create a workspace.** In an empty directory, which becomes your workspace, run:

   ```sh
   canopy init --provider jira
   ```

   Use `github`, or your tracker's name, in place of `jira`. `canopy init`:

   - writes the workspace's private config, yours alone, with a queue label of your own, to `.canopy/config.toml`;
   - writes the workspace's `canopy-workspace.toml`.

   In `.canopy/config.toml`, fill in your tracker source, the program that reads your tickets into canopy's journal:
   uncomment the table `canopy init` wrote, and the `cmd` for Jira with your site, or for GitHub Issues with your
   repository. canopy reads no ticket any other way, so its config does not load without one. Set
   `tracker.query` in `canopy-workspace.toml`. Point it only at a tracker where everyone who can file a ticket is
   someone you trust, never at a public repository's issues: a ticket is the task, so its author steers your agents,
   with your credentials. Then clone your repository under `repos/`, with an HTTPS URL and a credential helper, since
   worker sandboxing is not expected to support SSH:

   ```sh
   canopy workspace add https://github.com/acme/api.git
   ```

   canopy writes nothing into your repositories and installs nothing else: agent runs load its agent definitions and
   skills from its own directory.

5. **Run it.** Add your label (`agent-ready-<you>` by default) to a ticket, then run
   `canopy loop --dry-run --ticks 1` in the workspace and read the plan.

   Once you trust it, leave `canopy loop` running. It ticks, waits `loop.interval_minutes` (15 by default, longer while
   nothing changes), and repeats until you press Ctrl-C. `canopy daemon start` runs it in the background instead, until
   `canopy daemon stop`. It also serves the web UI at `http://127.0.0.1:8765/`;
   `canopy secret` prints the listener secret its sign-in page asks for.

## Daily surface

Leave `canopy loop` running (tmux works, or `canopy daemon start`) and work from the web UI it serves at
`http://127.0.0.1:8765/`: the attention list, every ticket's conversation and plan, the PRs and canopy's reviews of
them, runs and what they cost, and settings. Its guide, opened from the foot of the rail, says what each page holds
and how to act on it.

| To | Run |
| --- | --- |
| Read the attention list | `canopy status` |
| Read a ticket's conversation, or answer canopy there | `canopy show KEY`, `canopy reply KEY 'text'` |
| Work a ticket privately, with no label and nothing written to it | `canopy start KEY`, then `canopy stop KEY` |
| Hand canopy one-off work in your own words | `canopy task submit 'TEXT'` |
| Have canopy review a coworker's PR | `canopy start PR_URL --review` |
| Pause and resume the loop | `canopy pause`, `canopy resume` |

The rest is in `canopy --help`. `canopy skill --install` teaches your own agent session all of it.
[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) goes on from one repository to several, sandboxed workers, and
troubleshooting.

## Status

Pre-alpha, in daily use by its operator since 2026-10-12. Every stage of the loop is built; what is in progress is in
[docs/roadmap/](docs/roadmap/README.md).

## Related work

- **treehouse**: worktree pool with durable leases. Required dependency.
- **firstmate** (same author as treehouse): an interactive tmux captain/crew orchestrator. Different shape: canopy is
  unattended and queue-driven.
- **GitHub Copilot coding agent, Atlassian Rovo Dev**: hosted equivalents. See [Why this exists](#why-this-exists).
- **OpenAI Symphony, agent-orchestrator, Hermes Agent Kanban**: open-source loops that dispatch agents from a tracker or
  board. Why canopy is built anyway, and what their issue trackers taught: [docs/PRIOR_ART.md](docs/PRIOR_ART.md).

## License

MIT. See [LICENSE](LICENSE). canopy is not supported: issues and pull requests from outside may go unanswered.
