# canopy setup interview

You are the operator's own coding agent, in a session they started to set up canopy. Interview them and do the setup
with them, stage by stage, in the directory they started you in: their new canopy workspace. A person reads this file
too ([QUICKSTART.md](QUICKSTART.md) says how it is used), but it is written to you.

canopy is an unattended, local agent loop driven by an issue tracker. An overseer agent reads the tracker and GitHub
each tick and dispatches worker agents into worktrees leased from a [treehouse](https://github.com/kunchenguid/treehouse)
pool; workers push branches and open PRs; humans review and merge.

## Read first

Fetch these from `https://raw.githubusercontent.com/eddieland/canopy/main/`, with `curl -fsSL`, before you start. They
are the source of truth: where they and this file disagree, they win, and their commands, pinned versions, and paths
are the ones you run.

- `README.md`, section "Install": the five steps you are walking the operator through.
- `docs/GETTING_STARTED.md`: the workspace's layout, and stages 1 to 3 (one repository, slots that need setup, a
  pool of a set size). Stages 4 and 5 when the operator's answers call for them.
- `docs/SANDBOX.md`: only if the operator wants the sandbox (stage 7).
- `docs/BAZEL.md`: only for a Bazel repository.

## How to run the interview

- One question at a time, or a few that belong together. Say in a sentence why you ask, and offer the default when
  there is one. Find what you can yourself before asking: the OS, what is installed and on `PATH`, what a repository's
  lockfiles and README say.
- Before each stage, say what it will do in a line or two. After it, say what you did and what you checked.
- Check before you change: if a stage is already done, as on a second run of this interview, say so and move on.
- Run canopy's own checks rather than trusting your edits: `canopy status` loads the config, `canopy workspace sync
  --dry-run` says what sync would do, `canopy sandbox setup` says what is left. Run `canopy <command> --help` for any
  flag you are unsure of.
- Keep a list of what is left for the operator to do, and give it to them at the end.

## Ground rules

- **Ask first** before you run anything with `sudo`, install anything, edit a shell startup file, write a file outside
  the workspace, `~/.config/canopy/`, `~/.config/opencode/`, and `~/.config/treehouse/`, or do anything that writes to
  the tracker or GitHub (a label, a comment, branch protection).
- **Never touch secrets.** The operator signs in to OpenCode, its MCP servers, `gh`, and git's credential helper
  themselves. Do not read, print, copy, or write a token, and never put one in any config file canopy reads.
- **Never start the loop.** `canopy loop` without `--ticks` runs until Ctrl-C and would hang this session;
  `canopy daemon start` leaves it running. The one tick you may run is the dry one in stage 9, with the operator's
  go-ahead, because it spends a model call.
- **Never run canopy's overseer tools**: `canopy dispatch`, `decide`, `queried`, `attention`, `ticket set`, `mirror`.
  They refuse outside a tick by design.
- **Keep agent config out of the workspace.** Do not write an `opencode.json`, `.opencode/`, or any other agent
  runtime's config into the workspace or the clones under `repos/`: the overseer runs there, and canopy refuses to start
  its agents where a repository's OpenCode config names one of them (D044). MCP servers go in the operator's
  user-level OpenCode config, `~/.config/opencode/opencode.json`.
- **canopy writes nothing into the operator's repositories**, and neither do you: no commits, no pushes, no files
  added to the clones under `repos/`, except gitignored local files the operator asks you to copy in (stage 6).
- Workers run as the operator, under their credentials. Say so when it matters, such as granting MCP write tools.

## 1. Orient

Check, and say what you found:

- The current directory is the workspace the operator meant: not their home directory, not inside a git checkout
  (`git rev-parse --show-toplevel` fails), with no `.canopy/` unless a `canopy-workspace.toml` is beside it (a second
  run). If any check fails, stop and ask them to start you in a directory of its own.
- It is on the disk the operator wants: the clones and every worktree slot live inside it, and canopy cannot move the
  pools elsewhere. Show `df -h .` and ask, if more than one disk is mounted.
- The OS: Linux or macOS. Anything else is unsupported; say so and stop.
- Which agent you are. If you are not OpenCode, say that canopy's own runs use OpenCode whatever runs this interview.

Then ask the questions the later stages need, so the operator can gather the answers once:

1. Their tracker: Jira, GitHub Issues, Linear, or another with an MCP server.
2. The HTTPS clone URL of each repository canopy should work in. One is a fine start; more is stage 4 of
   GETTING_STARTED.
3. Whether they want to try canopy on a toy repository first. If so, a small repository of theirs with a few easy
   issues is the safest start.

## 2. Prerequisites

Check each, and show one table of what is there, with its version, and what is missing:

| Tool | Why | Check |
| --- | --- | --- |
| git | clones, worktrees | `git --version` |
| uv | installs canopy | `uv --version` |
| Go | builds treehouse at its pinned commit | `go version` |
| Node 22.12+ and npm | the install builds the web UI; the sandbox installs `srt` with npm | `node --version`, `npm --version` |
| OpenCode 2.1.4 or later | canopy's agent runtime | `opencode --version` |
| gh (optional) | an HTTPS credential helper for git, `gh auth setup-git` | `gh --version` |

For each missing one, propose how to install it on this OS (the upstream installer, the system package manager, or
`nvm install 22` for Node) and ask before you run it. Prefer installs that need no `sudo`.

## 3. Install treehouse and canopy

README "Install" steps 1 and 2, with its exact commands: treehouse from source at the pinned commit (never a release,
never `treehouse update`), then canopy with `uv tool install git+https://github.com/eddieland/canopy`, never
`uv tool install canopy`, which is an unrelated project on PyPI. If canopy is already installed, ask whether to
upgrade it with `--reinstall`.

Then check that `treehouse`, `canopy`, and `canopy-sandbox` are on `PATH` in a new login shell. If not, the usual fix
is `$(go env GOPATH)/bin` for treehouse and `uv tool update-shell` for canopy; ask before you edit a startup file.

## 4. OpenCode and its MCP servers

README "Install" step 3. canopy's agents reach GitHub and the tracker only through the MCP servers OpenCode has, and
need a model provider OpenCode is signed in to.

- Run `opencode mcp list` and show what is configured. canopy needs the GitHub MCP server and the tracker's; for
  GitHub Issues, the GitHub server is both.
- For a missing server, show the operator the entry for `~/.config/opencode/opencode.json`, from that server's own
  documentation, and ask before you write it. They complete any sign-in themselves.
- Each server canopy's agents need is set to `"codemode": false`: canopy denies its agents code mode, so a server
  left in it is out of their reach (D077). `canopy agents` shows such a server as `none` for every agent.
- Check that OpenCode is signed in to a model provider (OpenCode's `--help` names the command); if not, the operator
  signs in.
- Explain the grants README step 3 describes: workers need the write tools to comment on a ticket, edit its labels,
  and open PRs; on GitHub, without `issue_write`, PRs go unlabeled (D084).

## 5. The workspace

README "Install" step 4, and GETTING_STARTED stage 1.

1. Make sure git can reach each repository over HTTPS without a prompt: `git ls-remote <url> HEAD`. If it asks for a
   password, the operator sets up a credential helper (`gh auth setup-git`, or another), then you check again. Use
   HTTPS URLs even if the operator usually uses SSH: a sandboxed worker cannot reach an SSH agent.
2. Run `canopy init --provider <tracker> <url>...` in the workspace. Show what it wrote and what it printed.
3. Fill in, with the operator:
   - `tracker.query` in `canopy-workspace.toml`: help them write the query that finds their candidate tickets;
   - each repository's one-line `summary` under `[repos.<name>]`, and `MAP.md` if there are several (stage 4 of
     GETTING_STARTED);
   - in `.canopy/config.toml`, their tracker account id in `trust.authorized_repliers` and their GitHub login in
     `trust.trusted_reviewers`. Ask for both; for Jira, the stable accountId, never a display name.
4. The `needs-human` label must exist in the tracker, or `needs_human_label` must name one that does. Ask the operator
   to create it, or to let you, if you have a tool that can.
5. Show the branch protection `canopy init` printed, and ask the operator to confirm their repositories have it. Do
   not change it yourself.
6. Run `canopy status` and fix whatever stops the config from loading.

## 6. Clones and worktree slots

GETTING_STARTED stages 2 and 3, and stage 5 for a Bazel repository. Each run leases a slot, a fresh git worktree of
the clone under `repos/<name>/`, which has none of the operator's gitignored files and no dependencies installed.

For each repository:

1. Read its README, contributing guide, lockfiles, and CI config under `repos/<name>/` to learn how it builds and
   tests. Tell the operator what you found, and ask whether a fresh checkout is all a worker needs.
2. **Local files.** If the build needs gitignored files, such as `.env.local`, ask which ones. They must be in the
   primary clone for treehouse to copy them into each slot: ask the operator where they are and copy them in only
   with their go-ahead. Then write the manifest and `paths.worktree_include` as stage 2 shows.
3. **Install step.** If the build needs an install that depends on the branch, propose a `setup_cmd` (no shell runs it:
   `sh -c '...'` for one), and keep out of it anything a worker should fix, such as a build or a test. Try it in a
   throwaway worktree, never in one of canopy's slots, then remove it:

   ```sh
   check=$(mktemp -d)
   git -C repos/<name> worktree add --quiet --detach "$check/slot"
   (cd "$check/slot" && CANOPY_REPO=<name> CANOPY_BRANCH=<default branch> <the setup command>)
   git -C repos/<name> worktree remove --force "$check/slot" && rm -rf "$check"
   ```

   `setup_cmd` applies to every repository in the workspace and is told which by `CANOPY_REPO`, so with several,
   write one script that switches on it.
4. **Pool size.** Ask how many workers they want at once (`capacity.max_workers`, 2 by default) and whether slots
   should be made ahead of time (`capacity.slots_per_repo`, or `[capacity.repo_slots]` per repository). Help them size
   it: show the clone's size with `du -sh repos/<name>`, and for a large build, what one built slot costs.

Then run `canopy workspace sync --dry-run`, show what it would do, and with the operator's go-ahead,
`canopy workspace sync`. Report each pool's slots and any warning it printed, such as a push URL git would reach over
SSH.

## 7. Sandboxing

Ask whether the operator wants workers in an OS sandbox, after saying in a few lines what it is, from SANDBOX.md: a
worker steered by text in a ticket cannot then read their secrets, rewrite canopy's config, or reach hosts they did not
list. Say plainly that it is opt-in and not yet proven (ROADMAP M26 is open), and repeat the gaps SANDBOX.md names:
allowed hosts and the credentials a worker has are still in its reach, the overseer is not wrapped, and the "Not yet
closed" item. If they decline, note it in your summary and go to stage 8. If they want it, follow SANDBOX.md:

1. Run `canopy sandbox setup`. Show each `To do:` line. Those that need root are the operator's to run, or yours with
   their go-ahead. Run setup again until it exits 0.
2. Fill in the templates in `~/.config/canopy/sandbox/` with them: in `allowedDomains`, their model provider's API
   host, GitHub's hosts, their tracker's MCP endpoint and every internal MCP service, and the package registries the
   repositories' builds fetch from, which you can read from their lockfiles and CI config. In `allowRead`, the
   toolchains they build with that exist on this machine, and their credential helper's files, such as `~/.config/gh`.
   A workspace outside `$HOME` goes in `denyRead`. Leave the placeholders as they are.
3. Prefix every command template in `~/.config/canopy/config.toml`, never a workspace file, as SANDBOX.md step 5 shows:
   `worker_cmd_prefix` for `worker_cmd`, `private_worker_cmd`, and `plan_cmd`, then `chore_cmd`,
   `review_cmd`, and `setup_cmd` if one is set. Ask whether any chore sets a `cmd` of its own: each needs the
   `canopy-sandbox chore --` prefix there too, as step 5 shows, and the check below does not catch one that lacks it.
   Leave `overseer_cmd` as it is.
4. Run SANDBOX.md's check (step 6) against one repository and show the result. Every line but the last two must say
   `refused`, and the last two `allowed`. If one does not, find which template entry lets it through, fix it, and
   check again. Do not move on with a failing check unless the operator decides to leave the sandbox off.
5. Run `canopy status` again: the config must still load.

## 8. The operator's own agent sessions

Offer, and do only what they accept:

- `canopy skill --install`, which saves canopy's skill for their own agent sessions in `~/.agents/skills/`. For Claude
  Code, `canopy skill --install ~/.claude/skills`. It tells a later session how to read the loop's state.
- Shell completion: `canopy completion <shell>`; its `--help` says which startup file to add it to.
- Notification sinks, a reviewer on PRs, and chores are optional and can wait; point them at README "Daily surface".

## 9. One dry tick

Ask the operator to add their queue label (`canopy init` printed it, `agent-ready-<them>` by default) to one small,
well-described ticket. Then ask before you run, because the overseer spends a model call:

```sh
canopy loop --dry-run --ticks 1 --no-serve
```

The overseer plans and dispatches nothing. Read the plan with them, and `canopy decisions`. A `skip` with
`mcp_unavailable` means OpenCode lacks an MCP server (stage 4). A ticket missing from the plan usually means the query
or the label does not find it. Fix what it shows and, with their go-ahead, run it again.

## 10. Hand over

Do not start the loop. Tell the operator:

- to run `canopy loop` in the workspace (in tmux, or `canopy daemon start` to detach it) when they trust the plan;
- that it serves the web UI at `http://127.0.0.1:8765/`, and `canopy secret` prints what its sign-in asks for;
- that README's "Daily surface" covers what to do with the loop from now on.

End with a summary: what you installed, each file you wrote or changed and why, whether the sandbox is on and checked,
and the list of what is left for them to do.
