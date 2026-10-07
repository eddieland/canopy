---
name: canopy
description: Help the operator of a canopy agent loop from their own agent session. Explain what the loop decided and why, what needs a human, and where the logs are. Use when the user mentions canopy, the overseer, a canopy worker, or the attention list. Not for canopy's own overseer or worker runs.
---

# canopy

canopy is an unattended agent loop on the operator's machine. Each tick, an overseer agent reads the issue tracker and
GitHub through MCP, decides one action per ticket, and dispatches worker agents into leased
[treehouse](https://github.com/kunchenguid/treehouse) worktrees. Workers push a branch, open a PR, comment on the
ticket, and exit. Humans review, approve, and merge; canopy never does.

## First: are you canopy's own agent?

If the environment variable `CANOPY_TICK_ID` is set, or your prompt starts with `# canopy overseer` or `# canopy
worker`, you were started by canopy. Stop reading this skill and follow your prompt; it alone says what you may run.

Everything below is for an agent helping the operator in their own session.

## Ground rules

- Read, explain, and suggest. Do not start ticks or loops yourself: `canopy loop` runs until Ctrl-C and would hang your
  session, and `canopy tick` runs the overseer, which spends money. Suggest the command and let the operator run it,
  unless they ask you to run a single `canopy tick --dry-run`.
- `canopy dispatch`, `canopy decide`, `canopy attention`, and `canopy ticket set` are the overseer's tools. They refuse
  to run outside a tick, by design. There is no way to dispatch a ticket by hand; the way to get a ticket worked is its
  queue label (below).
- Never edit the journal (`canopy.db`) or anything under the state directory. Read it with `sqlite3 -readonly`.
- The journal is what the loop saw and did. The tracker and GitHub are the truth about tickets and PRs. When they
  disagree, the journal is stale, not wrong about the world.

## Commands

Run these from the repository the loop works on, or from anywhere in a workspace of several repositories (they find it
from the current directory: the nearest `canopy-workspace.toml` above it, else the repository).

| Command | What it does |
|---|---|
| `canopy status` | The last tick, attention list, running workers, each chore, and each sink. Start here. |
| `canopy decisions [TICK]` | A tick's decisions and rationales (default: the latest), and its overseer output file. |
| `canopy tick --dry-run` | One tick: the overseer plans, nothing is dispatched. See it with `canopy decisions`. |
| `canopy loop [--dry-run] [--every MINUTES] [--ticks N]` | The loop, in the foreground. The operator runs this. |
| `canopy init [--provider NAME]` | Writes the user config and `canopy.toml` if missing. Never overwrites either. |
| `canopy init --workspace [[NAME=]URL...]` | Sets up a workspace: map, `MAP.md`, `.gitignore`; adds and syncs URLs. |
| `canopy workspace sync [--dry-run]` | Converges `repos/` on the map and each pool on its declared size (DESIGN §18). |
| `canopy workspace add [NAME=]URL...` | Adds repositories to the map by clone URL, then syncs. |
| `canopy notify test [SINK]` | Sends a test message to every notification sink, or one, now. Changes nothing. |
| `canopy skill` | Prints this skill. |
| `canopy --version`, `canopy --help` | As usual; `canopy <command> --help` for options. |

## Where things are

The state directory is `paths.state_dir`, `~/.canopy` by default, or `.canopy/` at the root of a workspace. Everything
in it is readable only by the operator; in the commands below, replace `~/.canopy` with it.

| Path | What it holds |
|---|---|
| `attention.md` | The attention list, rewritten after every tick. |
| `canopy.db` | The journal: `ticks`, `tickets`, `ticket_units`, `runs`, `run_slots`, `decisions`, `chore_runs`, ... |
| `canopy.log` | JSON lines, one object per line with `ts`, `level`, `msg`, and `tick_id`. |
| `ticks/<tick id>.log` | The overseer's full output for that tick. |
| `runs/<run id>.log` | A worker run's output, including the worker agent's own. |
| `runs/<run id>.prompt` | The prompt that run's worker got. |
| `chores/<run id>.log`, `.prompt` | A chore run's output and prompt; `chores/<name>/` is a chore's own directory. |

Config: the user file `~/.config/canopy/config.toml` (`$XDG_CONFIG_HOME/canopy/config.toml`), personal, and the
repository's `canopy.toml` (in a workspace, `canopy-workspace.toml`, which also lists the repositories), shared. The
user file wins key by key; some keys, such as `tracker.labels` and everything under `runtime`, may be set only in the
user file.

## Answering "why wasn't KEY picked up?"

Work through these in order and stop at the first that explains it.

1. Did a recent tick run at all? `canopy status` shows the last tick. `skipped` usually means the overseer could not
   reach an MCP server (`mcp_unavailable: <which>`); `overseer_failed` and `reconcile_failed` have a summary, and
   `ticks/<id>.log` has the detail. A failed or skipped tick decides nothing.
2. What did the overseer decide about KEY?

   ```sh
   sqlite3 -readonly ~/.canopy/canopy.db \
     "select tick_id, action, rationale from decisions where ticket_key = 'KEY' order by id desc limit 20"
   ```

   No rows means the overseer never considered it: the ticket did not match `tracker.query`, or it lacks one of
   `tracker.labels`, or it is closed. Only the labels authorize work; the query only finds candidates.
3. Read the action:
   - `wait` or `skip`: the rationale says why. `blocked_by: <KEY>` means an open blocker.
   - `refused:<guard>`: the harness refused the dispatch. `unauthorized` (the overseer named no label from
     `tracker.labels`), `capacity` (all `capacity.max_workers` slots busy), `running` (a worker is already on it),
     `attempt_limit` (the kind's `policy.max_<kind>_attempts` is used up; this never resets), `cooldown` (fix-ci waits
     `policy.fix_ci_cooldown_minutes` after the last one), `no_slot` (treehouse had no free worktree, or the pool is
     at its declared size), `bad_slug`, `bad_base`, `no_branch` (nothing to continue in that repository yet),
     `unknown_repo` (in a workspace: no `--repo`, or a repository not in the map or not cloned), `bad_prompt` (the
     worker prompt did not render; an override may lack `{{LABELS}}`, or for a run over several repositories
     `{{REPOSITORIES}}` and `{{PRS}}`), `spawn_failed`. In a workspace, attempt limits and the fix-ci cooldown count per
     repository of the ticket. A run that ends `failed` with a summary starting `not authorized:` is the worker finding
     the ticket closed or unlabeled; it changed nothing, but it spent one of the kind's attempts.
   - `dispatch:<kind>`: it was dispatched. In a dry-run tick the rationale starts with `dry run: not dispatched`.
   - `attention:<reason>`: it is waiting on a human (below).
4. If it was dispatched, look at its runs:

   ```sh
   sqlite3 -readonly ~/.canopy/canopy.db \
     "select id, kind, status, branch, started_at, ended_at, result_json from runs where ticket_key = 'KEY' order by id"
   ```

   `run_slots` holds each run's worktrees, one per repository, and `ticket_units` each repository's PR for the ticket.

   Then read `runs/<id>.log`. A run that ended `crashed`, `unpushed`, `unknown`, `timeout`, or `failed` is on the
   attention list, and the overseer will not dispatch the ticket again until an account in
   `trust.authorized_repliers` comments on the ticket after the run ended. That comment is how a human says "try
   again".

## The attention list

`canopy status` or `attention.md`. Each item is a ticket and a reason, and in a workspace sometimes the repository of
the ticket's PR it is about, shown as `KEY (repo)`. It disappears on its own the first tick its cause is gone; there is
no dismissing. Reasons:

| Reason | What the human does |
|---|---|
| `needs_reviewer` | The PR is green and unreviewed: review it. |
| `ready_to_merge` | The PR is approved: merge it. canopy never merges. |
| `needs_author` | A review comment needs a person (design pushback, scope), or a stacked-on PR closed: decide. |
| `attempt_limit` | The ticket used up its attempts of one kind. Take it over, or raise the limit in the user config. |
| `crashed`, `unpushed`, `unknown_result`, `worker_failed` | A run went wrong. Read the run log the detail names. |
| `chore_failed` | A chore's latest run could not check (failed, timed out, crashed): read its log. |
| `review_failed`, `review_unposted`, `review_limit` | A PR's review failed, lost its comment, or hit its limit. |
| `repo_missing` | A repository in the workspace map has no clone: run `canopy workspace sync`. |
| `multi_repo` | Independent pieces in several repositories, or a split not done: decide. Ask for a split below. |
| `split_unlabeled` | A split's children have no queue label: label each one you want worked. |
| `split_self_labeled` | A split child was labeled before its split ended: remove the label, add it again. |

To retry after a run went wrong, an authorized replier comments on the ticket; otherwise take the ticket over.

To split a ticket that needs several repositories into one ticket per repository, an authorized replier comments on it
asking for a split. In a workspace of several, a later tick dispatches a splitter, which creates the children with no
labels and comments on the ticket; label each child to start it. Without such a comment a ticket is never split.

The overseer may record other reasons; the detail says what it wants.

A worker that needs an answer posts its question as a ticket comment and adds `tracker.needs_human_label`. An
authorized replier's comment on the ticket resumes it on a later tick; anyone else's comment is ignored.

Workers post as the operator, so every comment they post starts with `trust.comment_prefix` (`CANOPY:` by default) and
ends with `trust.comment_suffix`, whichever are set. A comment carrying those marks is a worker's: it never resumes,
splits, or asks for changes, whoever wrote it. Do not start a reply meant to steer a worker with the prefix.

## Getting a ticket worked

Add the operator's queue label (`tracker.labels` in the user config, `agent-ready-<user>` by default) to an open ticket
that `tracker.query` finds. The next live tick with free capacity dispatches it. To preview, run
`canopy tick --dry-run` and then `canopy decisions`.
