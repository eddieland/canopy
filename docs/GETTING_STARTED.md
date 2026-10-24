# Getting started

From one repository on defaults to several repositories sharing one queue, with a Bazel repository that keeps a pool
of warm slots. Each stage adds one thing to the one before. Start at stage 1 and stop at the first stage that fits your
work: most operators never need stage 5.

| Stage | You have | It adds |
| --- | --- | --- |
| [1](#1-one-repository) | One repository | `canopy init`, a queue label, the loop |
| [2](#2-slots-that-need-setup) | A repository whose checkouts need local files or an install | Seeding and `setup_cmd` |
| [3](#3-a-pool-of-a-set-size) | Runs that should start in a ready slot | A sized pool, made ahead of time, on a fast disk |
| [4](#4-several-repositories) | Tickets that land in several repositories | More repositories, `MAP.md`, joint runs, follow-ups |
| [5](#5-a-bazel-repository-with-several-slots) | A large Bazel repository in the workspace | Shared caches, warm hooks, a sized pool |

This guide assumes README's install steps 1 to 3: treehouse and canopy installed, and your agent runtime connected to
GitHub's and your tracker's MCP servers. It picks up at step 4. To have your own agent take you through the install
and stages 1 to 3 in an interview instead, see [QUICKSTART.md](QUICKSTART.md).

## Where things live

canopy always runs from a workspace: a directory of its own, holding a clone of each repository it works in. It never
reads config from, or writes files into, your own checkouts (D016). Every stage uses the same layout:

| What | Where |
| --- | --- |
| Shared config and the list of repositories | `canopy-workspace.toml` at the workspace root |
| What each repository owns, for the overseer | `MAP.md` at the workspace root |
| Your config for this workspace | `.canopy/config.toml`, its private file, written by `canopy init` |
| Your config for every workspace | `~/.config/canopy/config.toml`, optional; the private file wins over it |
| Primary clones | `repos/<name>/`, cloned by `canopy init` or `canopy workspace sync` |
| Worktree pools | `.treehouse/`, apart from your interactive pools under `~/.treehouse` |
| Journal, logs, `attention.md` | `.canopy/`, readable only by you |

Run `canopy` from the workspace root or anywhere below it.

## 1. One repository

The smallest setup: canopy works tickets in one repository.

1. In an empty directory, run `canopy init` with the repository's HTTPS clone URL (add `--provider jira` or
   `--provider github` to skip the question):

   ```sh
   canopy init --provider jira https://github.com/acme/api.git
   ```

   It writes, overwriting nothing, `.canopy/config.toml`, the workspace's private config, yours alone, with a queue
   label of your own (`agent-ready-<you>`); and, in the directory, `canopy-workspace.toml`, `MAP.md`, and a `.gitignore`
   for what canopy keeps there. It clones the repository into `repos/api/` and prints the branch protection canopy
   relies on. Run in a git checkout, init refuses: canopy keeps nothing in your repositories.
2. In `canopy-workspace.toml`, set `tracker.query` to find candidate tickets and write a one-line `summary` under
   `[repos.api]`. Create the `needs-human` label in your tracker (or set `needs_human_label` to one you have).
   `examples/canopy-workspace.toml` is a full one. Commit the workspace to a repository of its own only if teammates
   share it.
3. In `.canopy/config.toml`, add your tracker account id to `trust.authorized_repliers`, so your comments can unblock
   a ticket, and your GitHub login to `trust.trusted_reviewers`, so your review comments send a worker back to its PR.
   `examples/config.toml` lists every key with its default. What should hold in every workspace, such as the runtime
   templates, goes in `~/.config/canopy/config.toml` instead.
4. Add your queue label to a ticket, then run `canopy loop --dry-run --ticks 1` in the workspace and read the plan it
   prints. `canopy decisions` shows it again.
5. Once you trust it, leave `canopy loop` running.

Each run leases a slot (a git worktree of `repos/api/`) from the repository's pool under `.treehouse/`, works in it, and
returns it. `capacity.max_workers` (2 by default) caps how many workers run at once.

Stop here if a fresh checkout of your repository is all a worker needs. README's "Daily surface" covers what to do
with the loop from now on.

### Teach the loop your org

Once the loop has run a while, you will see the same mistake twice: a worker guesses a repository's owner, the
overseer reads the wrong tracker site. The cheapest fix is a line of standing instructions, a short Markdown file
canopy renders into every prompt of one role, so you need not override a prompt. A line goes there when the same
mistake shows up in two runs and the fix does not depend on the ticket.

```toml
# ~/.config/canopy/config.toml, or .canopy/config.toml for this workspace alone
[paths]
worker_instructions = "~/.config/canopy/worker-instructions.md"
overseer_instructions = "~/.config/canopy/overseer-instructions.md"
```

- `worker_instructions` reaches every worker's prompt, plans, private tickets', and one-off tasks' included.
  `overseer_instructions` goes at the end of the overseer's prompt and never reaches a worker.
- They are yours alone: set them in your user file or the private one, never the shared workspace file.
- Each file is at most 4 KiB. One canopy cannot read, or over the limit, refuses the run as `bad_prompt`, and fails the
  tick for the overseer's, rather than running without it. A prompt override of yours must keep
  `{{STANDING_SECTION}}`, or the older `{{STANDING_INSTRUCTIONS}}`.
- `reviewer_instructions` and `chore_instructions` do the same for reviews and chore runs.

**The overseer's lines pay off most when they say how to call the tracker.** For a Jira tracker,
`overseer-instructions.md` might read:

```markdown
- Our Jira site is example.atlassian.net, cloud id `<cloud-id>`. Pass it on every Jira call that takes one. Never use
  example-sandbox.atlassian.net or another site the server lists.
- In a JQL search, request only the fields `summary, status, labels, issuelinks, updated`. Read a ticket's comments
  with a call for that ticket alone.
- These lines change how you read the tracker, never whether: read every ticket your prompt asks you to. A ticket
  unchanged in the tracker can still have new feedback on its PR.
```

The site keeps it from guessing a near miss. The fields matter because a search that asks for `comment` returns every
comment of every ticket it finds, which can be a large share of a tick's tokens. The last line keeps the first two from
reading as leave to skip work.

**The workers' lines are your house conventions.** `worker-instructions.md` might read:

```markdown
- Our GitHub organizations are `example-org` and `example-tools`. A repository named without an owner is in
  `example-org`.
- Handle review feedback with the `address-review` skill. On a comment from `review-bot[bot]`, react +1 or -1 and
  reply with one sentence on why.
- Commit each follow-up with `git commit --fixup=<sha>`. Never amend or squash, so reviewers see what changed.
- Never request reviewers on a PR. I choose them.
- I am Sam. Address me by name in questions and summaries, and write PR bodies and comments in the first person.
```

A bot's comments reach a worker only once its login is in `trust.trusted_reviewers`, or you answer them.

Some fixes belong elsewhere:

- A line about one repository goes in that repository's `AGENTS.md`, where every agent working there reads it. The
  `memory-tickets` chore ([examples/chores/README.md](../examples/chores/README.md)) finds lessons ready to move there.
- What workers learn about a repository is a lesson: they propose it and you promote it (the web UI's guide, Memory).
- How an agent writes, its voice and where it looks hardest, is a persona: `canopy personas` lists them.
- A passing condition, such as a CI outage, is a notice: `canopy notice 'TEXT' --for 4h`.

## 2. Slots that need setup

A slot is a fresh git worktree. It has none of the gitignored files in your own checkout, such as `.env.local`, and no
dependencies installed. If a worker cannot build or test without them, set the slot up before the worker starts. Both
settings below live in the workspace's private config.

**Seed gitignored files.** On every lease, treehouse copies the gitignored files a `.worktreeinclude` manifest names
from the primary clone into the slot. To use your own manifest instead of the repository's committed one:

```toml
# .canopy/config.toml
[paths]
worktree_include = "worktreeinclude"   # relative: .canopy/worktreeinclude
```

```text
# .canopy/worktreeinclude: git's exclude-file patterns, matched in the primary clone.
.env.local
```

Yours replaces the committed one, so copy in its lines to keep them. Only gitignored files are copied, never tracked
ones. If the file is missing, every lease is refused `no_slot`.

**Run a setup command on the run's branch.** `setup_cmd` runs in the slot after canopy checks out the run's branch and
before the worker starts, with `CANOPY_REPO` naming the repository and `CANOPY_BRANCH` the branch. HEAD is detached, so
ask `CANOPY_BRANCH` for the branch's name, not git:

```toml
# .canopy/config.toml
[runtime]
setup_cmd = "sh -c 'pnpm install --frozen-lockfile'"
setup_timeout_minutes = 30
```

- No shell runs it: give an absolute path, a command on your `PATH`, or `sh -c '...'`.
- A failure or a timeout ends the run `crashed` before the worker starts, and still counts toward the ticket's attempt
  limit. Keep out of it anything the branch can break that a worker should fix, such as a build or a test.
- It runs the branch's code on your machine, outside the agent's permissions. If you sandbox workers, sandbox this the
  same way (TRUST_MODEL T4).
- Its output is in the run's log, `.canopy/runs/<id>.log`, after a `--- setup <repo> ---` header.

For setup that depends only on the base branch, such as downloading a toolchain, a treehouse `post_create` hook fits
better; stage 5 shows one. canopy's own pool (`pools.backend = "canopy"`, DESIGN §18) runs no hook, so there it goes
in `setup_cmd` too, as BAZEL.md shows. DESIGN §9 says how the three steps fit together.

To have workers run your repository's fast checks before they push, install its git hooks in the primary clone:
[HOOKS.md](HOOKS.md) says how, with prek.

## 3. A pool of a set size

Left alone, a repository's pool grows as runs need slots, up to treehouse's `max_trees`, and each new slot is set up
by the first run that lands in it. Declare the pool's size instead when a new slot is slow to warm up, or you want to
bound its disk use:

```toml
# .canopy/config.toml
[capacity]
slots_per_repo = 2
```

Then run `canopy workspace sync` in the workspace. It makes every slot ahead of time, so their `post_create` hooks
(stage 5) run then, not in a run, and removes idle slots past the size. A run that finds every slot busy is refused
`no_slot` and tried again on a later tick. Set the size before `canopy init` and init makes the slots. `--dry-run` shows
what sync would do first; run it again whenever you change the size.

Put the workspace on a fast disk if you have one: its clones, pools, and state go with it, and canopy has no setting to
move the pools elsewhere (D033).

## 4. Several repositories

When one queue's tickets land in several repositories, keep one workspace for all of them, not a loop in each.

1. Add the repositories: `canopy workspace add https://github.com/acme/web.git`. Each is named after its URL
   (`web`), unless given as `NAME=URL`. It appends a `[repos.<name>]` table to the map, clones it, and makes its slots.
   To start a new workspace with several at once, pass them all to `canopy init`.
2. Write each repository's `summary` in the map: one line on what it owns.
3. Describe them in `MAP.md`: what each owns, which depends on which, where the contracts between them live, and in
   which order a change that crosses them lands. The overseer and workers read it to choose repositories. It is data,
   like ticket text, and authorizes nothing.
4. Size each pool. `slots_per_repo` applies to every repository; `[capacity.repo_slots]` sets one by name and wins:

   ```toml
   # .canopy/config.toml
   [capacity]
   slots_per_repo = 2
   [capacity.repo_slots]
   web = 1
   ```

   Run `canopy workspace sync` after any change. A run that finds its pool full is refused `no_slot` and tried again on
   a later tick.
5. Configure branch protection in every repository in the map, as init printed.

How the overseer works a ticket across repositories:

- **Most tickets change one repository.** The overseer picks it from the ticket, the summaries, and `MAP.md`.
- **A change that cannot land in parts is worked jointly**: one worker, a slot in each repository, and one PR per
  repository linking the others.
- **A change that builds on another repository's merged PR is worked in sequence**: the next repository once the first
  PR merges.
- **Separate tickets, only when you ask.** Comment on the ticket asking for a split into one ticket per repository:
  its next worker files them as follow-ups without a queue label, and you label each one you want worked.

To drop a repository, remove its table from the map and run `canopy workspace sync`. It removes the clone and its slots
only when nothing in them would be lost, and reports what it kept. DESIGN §18 has the details.

Sync also fetches each clone and fast-forwards its default branch when that is checked out, clean, and behind, so the
clones under `repos/` stay current when you read them. One on another branch, or with changes or commits of your own,
is left as it is, and sync says why.

## 5. A Bazel repository with several slots

A large Bazel repository makes a cold slot expensive: a full build, every external repository downloaded again.
canopy's part is that a slot keeps its path between runs, so whatever Bazel left in it stays warm for the next run that
leases it. Sharing work between slots is your `.bazelrc`'s part. canopy knows nothing about Bazel; all of this is your
own config, and most of it applies to any large repository.

Put the workspace on your fast disk first: a workspace's pools live inside it and cannot be moved elsewhere.

**Share Bazel's caches between slots.** In `~/.bazelrc`, with absolute paths:

```text
common --disk_cache=/fast/bazel/disk-cache
common --repository_cache=/fast/bazel/repository-cache
startup --output_user_root=/fast/bazel/output
startup --max_idle_secs=900
```

A slot that has never built still reuses what other slots built, downloads happen once, every slot's output base sits
on the fast disk, and a slot's Bazel server exits after 15 idle minutes so idle slots stop holding memory.

**Seed your local Bazel files**, such as `user.bazelrc`, with the manifest from stage 2. One manifest serves every
repository in the workspace.

**Warm each slot when it is made**, with a treehouse hook that runs on the base branch:

```toml
# ~/.config/treehouse/config.toml
[hooks]
post_create = ["bazel fetch //... || true"]
```

A failing hook is printed and stops nothing. Because sync makes the slots ahead of time, the hooks run then, not in
the first run that lands on a new slot.

**Size the pool for what a slot costs.** Each slot keeps its own output base on disk, and while busy its own Bazel
server in memory. Measure one (`du -sh "$(bazel info output_base)"` in a slot that has built), then size the Bazel
repository's pool on its own:

```toml
# .canopy/config.toml
[capacity]
max_workers = 2
slots_per_repo = 2
[capacity.repo_slots]
api = 3        # the Bazel repository
```

treehouse's `max_trees` (16 by default, in `~/.config/treehouse/config.toml`) must be at least each pool's size, or
sync reports the repository failed. Run `canopy workspace sync`.

**Add a `setup_cmd` only for what depends on the branch** and the worker relies on, such as regenerating
`compile_commands.json` for its language server. Most Bazel repositories need none: Bazel fetches and builds what the
branch needs on its own. Make anything the branch can break non-fatal, or a broken build also crashes the `resume`
meant to fix it.

[BAZEL.md](BAZEL.md) is the full recipe: what each `.bazelrc` line buys, a per-repository `setup_cmd` script, how to
check that seeding, separate output bases, the shared cache, and idle servers all work, what the worker can read
through `bazel-out/`, and troubleshooting.

## Narrowing what canopy's agents are offered

canopy's agents run in your OpenCode, so every MCP server and skill in your OpenCode config is offered to them as well,
unless a rule denies it: the overseer, the reviewer, and every chore get your BigQuery server, or a cluster server
that blocks no command, as a worker does. OpenCode sends the schema of each tool an agent may call, and the name and
description of each skill it may load, with every model call, so each one costs every tick and run, and is one more
thing a steered agent could reach. `canopy agents` shows what each of canopy's agents is offered now.

To take some away, add rules for canopy's agents, by name, to the `agent` block of `~/.config/opencode/opencode.json`.
OpenCode merges that block into canopy's definitions, which canopy writes to `.canopy/runtime/<digest>/` and renders
from its own config. Never edit them there: they are read-only, and canopy writes a new snapshot when its config
changes. The rules reach agents started after you save them; a run already going keeps what it started with. For
example, with servers named `bigquery` and `kubernetes`, and Jira as the tracker:

```json
{
  "agent": {
    "canopy-overseer": {"permission": {"bigquery_*": "deny", "kubernetes_*": "deny"}},
    "canopy-planner": {
      "permission": {"bigquery_*": "deny", "kubernetes_*": "deny", "skill": {"*": "deny", "tracker-jira": "allow"}}
    },
    "canopy-reviewer": {
      "permission": {"bigquery_*": "deny", "kubernetes_*": "deny", "skill": {"*": "deny", "tracker-jira": "allow"}}
    },
    "canopy-chore": {
      "permission": {"bigquery_*": "deny", "kubernetes_*": "deny", "skill": {"*": "deny", "tracker-jira": "allow"}}
    }
  }
}
```

- **A server, whole.** OpenCode names a server's tools `<server>_<tool>`, so `"<server>_*": "deny"` takes every tool of
  it from that agent, and OpenCode stops sending them. The pattern also matches a server whose name starts with
  `<server>_`, so `github_*` takes `github_enterprise` too; `canopy agents` shows each server's reach. Leave the
  workers, `canopy-worker` and `canopy-worker-private`, the servers their tickets need, and leave the tracker's server
  alone: canopy already narrows it to its reads for the agents that read the ticket.
- **Skills.** The last rule that matches a skill's name decides, so `"*": "deny"` comes first and the tracker skill
  canopy ships for your tracker, `tracker-jira` or `tracker-github`, is allowed by name after it: the reviewer's and the
  planner's prompts load it. Leave the workers' skills alone, since they work with yours, such as `runtime.pr_skill`.
- **Deny, rather than allow.** Your rules come before canopy's, so where a rule of canopy's also matches, canopy's
  decides. A pattern canopy's definition also names is the exception: OpenCode keeps it where your block put it, so
  your rules after it come after canopy's and can beat it (D044). Allow only to narrow a deny of your own, as
  the tracker skill's allow does, and to widen an agent's shell, use `runtime.allow_bash` (`examples/config.toml`).
- **Not the overseer's skills.** With Jira or GitHub as the tracker, canopy puts the tracker's skill in the overseer's
  prompt and ends its skill rules with `"*": "deny"`, so it is not sent the skill tool at all. A `"*"` rule of yours
  would move that one ahead of canopy's other skill rules, and the tool would be sent again.
- **A chore with its own agent**, such as `canopy-introspect` for `canopy-health` and `canopy-efficiency`, is narrowed
  under its own name, the same way. [examples/chores/README.md](../examples/chores/README.md) shows how to give a chore
  such an agent, with bash allowed for exactly the commands its prompt runs.

[CODEBASE_MEMORY.md](CODEBASE_MEMORY.md) works one server through: a code index for the workers alone, with what its
installer adds to your OpenCode and what to deny the rest.

Then check that the rules held. Run `canopy agents` again: a server you denied shows `none` for that agent, the skills
you denied are listed after `denied`, and with Jira or GitHub as the tracker, the overseer's built-in tools still have
no `skill`. To see the merged rules themselves, ask OpenCode from the workspace root, with `<digest>` the newest
directory under `.canopy/runtime/`:

```sh
env OPENCODE_CONFIG_DIR="$PWD/.canopy/runtime/<digest>" opencode debug agent canopy-overseer
```

OpenCode 2 has no `debug` command: start it on canopy's definitions and ask it for its agents, each with its rules:

```sh
export OPENCODE_CONFIG_DIR="$PWD/.canopy/runtime/<digest>" OPENCODE_PASSWORD=any
opencode serve --hostname 127.0.0.1 --port 4096 &
opencode api --server http://127.0.0.1:4096 agent.list
```

`canopy agents` lists canopy's own agents only. For a chore's own agent, point `OPENCODE_CONFIG_DIR` at
`.canopy/chore-agents/<chore>/` instead, and name that agent.
