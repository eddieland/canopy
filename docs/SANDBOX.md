# Running workers in a sandbox

How to run canopy's workers, setup commands, chores, and reviews inside an OS sandbox, so that a worker steered by text
in a ticket cannot read your secrets, rewrite canopy's config, or reach hosts you did not list. Everything here is your
own config and what `canopy sandbox setup` installs: the loop sees only the command templates, and none of this is
required to run it.
For why it works this way and what it was checked against, see DESIGN §24, [Sandboxed
runs](design/SANDBOXING.md); for what it does and does not defend against, TRUST_MODEL T4 and T6.
A step to take first, sandbox or not: deny each agent the MCP servers and skills it never uses, as
[GETTING_STARTED.md](GETTING_STARTED.md#narrowing-what-canopys-agents-are-offered) shows.

The sandbox is opt-in and not yet proven: ROADMAP M26 is open. The canary that checks every property (DESIGN §24)
runs in CI on Linux; it has yet to pass on the operator's own machines. Try it on yours with the check below
before you rely on it.

## What a sandboxed run can do

A run's command starts in `canopy-sandbox`, a short wrapper canopy installs beside itself. The wrapper writes a policy
for that run from a template of yours and runs the command under `srt`, Anthropic's sandbox runtime, which uses
bubblewrap on Linux and `sandbox-exec` on macOS and sends all network traffic through a proxy that enforces a domain
allowlist. Under the shipped templates:

| | Allowed | Refused |
| --- | --- | --- |
| Read | the run's worktrees and their git directories, canopy's agent definitions, the runtime's files, the toolchains you list | the rest of `$HOME`: `~/.ssh`, cloud credentials, other repositories, `~/.config/canopy`, the workspace's `.canopy/` |
| Write | the run's worktrees, its own HEAD and index, a per-run object directory, a per-run temp directory, the role's own cache and data directories | everything else, shared git state included: no branch moves, no hooks, no git config, none of your own caches |
| Network | the hosts in the template's allowlist | every other host, loopback, link-local, and cloud metadata addresses |

A write the policy refuses under `$HOME` may look as if it worked: `srt` puts an empty, writable `tmpfs` over a denied
directory, and what is written there is gone when the run ends. Nothing reaches the host.

What it does not cover: a worker can still send anything to a host you allowed, with the credentials it has, such as
your GitHub token; the overseer is not wrapped yet ([The overseer](#the-overseer)); and the sandbox shares the kernel,
so it is no defense against an exploit written to escape it (DESIGN §24).

You log in once, as without a sandbox: each run's OpenCode starts with a copy of your OpenCode logins, and a token it
refreshes comes back to yours (section 2).

## 1. Run `canopy sandbox setup`

```sh
canopy sandbox setup
```

It installs what it can without root, prints what is left as `To do:` lines, and exits 1 until nothing is. Run it
again after each upgrade of canopy: it keeps your templates and installs a new `srt` when canopy pins one. It:

- copies the policy templates to `~/.config/canopy/sandbox/`, never over one that is there, and says when one that is
  there lets a run write in your own cache directory, as templates copied before `@CACHE@` let it write
  `~/.cache/opencode`, or names your own OpenCode data, `~/.local/share/opencode`, as templates copied before `@DATA@`
  did (section 3);
- installs `srt`, pinned by a lockfile canopy ships, with `npm ci`, into `~/.local/share/canopy/sandbox-runtime/`. That
  needs Node 22.12 or later and npm on `PATH`. A worker cannot write there, and the wrapper prefers that `srt` to any
  other on `PATH`;
- checks what needs root, which it never runs, and prints the commands for it (below).

On Linux, `srt` needs bubblewrap, socat, and ripgrep:

```sh
sudo apt-get install bubblewrap socat ripgrep
```

On macOS it needs ripgrep (`brew install ripgrep`); `sandbox-exec` comes with the system.

Setup also checks two things `srt` only warns about in its debug log, and runs anyway:

- bubblewrap 0.5.0 or later. On an older one, `srt` cannot hide a socket, fifo, or device a template denies reading,
  and leaves on the host the mount points of a sandbox that was killed. Ubuntu 20.04 and Debian 11 ship older ones.
- an x86_64 or aarch64 machine. `srt` ships its seccomp filter, which blocks making Unix sockets, for those alone;
  elsewhere a sandboxed command can reach your SSH agent, or Docker's socket. Do not rely on the sandbox there.

On Ubuntu 24.04 and later, AppArmor restricts unprivileged user namespaces
(`kernel.apparmor_restrict_unprivileged_userns`), and bubblewrap fails without them. Setup tries bubblewrap, and when
it fails this way, says to lift the restriction, now and at boot, or give `bwrap` an AppArmor profile that allows
`userns`:

```sh
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
echo 'kernel.apparmor_restrict_unprivileged_userns = 0' | sudo tee /etc/sysctl.d/60-canopy-sandbox.conf
```

Run canopy as yourself, not as root.

## 2. What setup installed

`canopy-sandbox` comes with canopy: `uv tool install` puts it on `PATH` beside `canopy`. The wrapper reads the
template for its role from `$XDG_CONFIG_HOME/canopy/sandbox/` (`~/.config/canopy/sandbox/` when that is unset):

| Template | Used for |
| --- | --- |
| `worker.json` | `worker_cmd`, `private_worker_cmd`, and `plan_cmd` |
| `setup.json` | `setup_cmd` |
| `chore.json` | `chore_cmd` and each chore's own `cmd` |
| `review.json` | `review_cmd` |
| `overseer.json` | `overseer_cmd`, once canopy takes the prefix there ([The overseer](#the-overseer)) |

It runs the `srt` in `~/.local/share/canopy/sandbox-runtime/` (under `$XDG_DATA_HOME` when that is set), or else the
first on `PATH`. It drops every relative entry from `PATH`, so `git`, and any other `srt`, must be on `PATH` through
an absolute one. `srt` runs its seccomp helper inside the sandbox, so the wrapper lets each run read `srt`'s own
`vendor/` directory, wherever `srt` is installed.

Each role caches in a directory of its own, `~/.cache/canopy/sandbox/<role>/` (under `$XDG_CACHE_HOME` when that is
set), which the wrapper makes, and setup in the worker's, so that what it installs is there for the worker. The
wrapper points the command's `XDG_CACHE_HOME` there, and `npm_config_cache`, `GOCACHE`, `GOMODCACHE`, and
`PIP_CACHE_DIR` under it, whatever you set them to. The first sandboxed run of each role fills its cache from nothing.
Nothing empties them but `canopy gc --caches`, which skips a role's while a run of it is live, and the overseer's
while a tick runs.

OpenCode keeps its data the same way, in `~/.local/share/canopy/sandbox/<role>/` (under `$XDG_DATA_HOME` when that is
set), which the wrapper makes the command's `XDG_DATA_HOME`: your own, `~/.local/share/opencode`, is what your
OpenCode, and an unsandboxed overseer's, act on outside the sandbox, so no run writes it, a sandboxed overseer's
included, whatever its template says. Your logins
are the one part a run needs, and you keep them where they are:

- Just before each run, the wrapper copies your `auth.json` and `mcp-auth.json` from your OpenCode data into the
  role's, replacing what an earlier run left there. Log in, or out, as you always do; the next run has the change.
- When a run refreshes an OAuth token, the wrapper copies the new token back into yours when the run ends, and the run's
  log says `canopy-sandbox: copied back the refreshed tokens of auth.json: anthropic`. It takes nothing else: no new
  login, no API key, and no field that says where a token is sent or whose account it is. A run killed at its timeout
  hands its token back at the role's next run.

uv's Pythons and tools stay where you keep them: the wrapper sets `UV_PYTHON_INSTALL_DIR` and `UV_TOOL_DIR` to them
unless you have.

`srt` is a beta. canopy pins the version DESIGN §24 was checked against; to try another, install it on `PATH`
and remove canopy's, and re-read DESIGN §24's claims first.

## 3. Fill in the templates

Each template is `srt`'s settings file with comments (keys that start with `#`) and placeholders (`@CWD@`,
`@WORKTREES@`, and so on) that the wrapper fills in for each run. Leave the placeholders as they are; the wrapper
refuses a template with an unknown one, with no `denyRead`, or with no `allowedDomains`.

`network.allowedDomains` is the allowlist; everything not on it is refused. Add:

- your model provider's API host (`api.anthropic.com` is there as an example);
- GitHub: `github.com`, `api.github.com`, and `*.githubusercontent.com` are there, and `api.githubcopilot.com` for
  GitHub's remote MCP server;
- your tracker's MCP endpoint, and every internal MCP service your agents use: an internal host needs its own entry;
- the package registries your builds and tests fetch from, in `worker.json` and `setup.json` alike.

To keep allowed names from resolving to your private network, list its ranges in `network.deniedResolvedAddresses`,
unless an internal MCP service lives there. Behind a corporate proxy, which `srt` forwards through when
`HTTPS_PROXY` is set, `srt` makes none of its address checks, loopback and metadata addresses included: the proxy's
own rules are the only ones.

`filesystem.allowRead` re-allows what a run must read under `$HOME`, which `denyRead` hides. Trim the toolchains to
the ones you build with, and add any that are missing: `~/.local/bin`, `~/.nvm`, `~/.cargo`, `~/.rustup`, `~/go`,
and `~/.local/share/uv` are there. A toolchain is readable, not writable. Name each directory, never one that holds
the role caches or the run directories, such as `~` or `/tmp`: `srt` would bind it back over them, so the wrapper
refuses it.

Caches go in `@CACHE@`, the role's cache directory, which the templates allow reading and writing. Never put one of
your own caches in `allowWrite`: your own tools run what is in them, outside the sandbox, so a run that can write one
can run code on your machine. OpenCode's is one: it imports packages and runs programs from `~/.cache/opencode`, the
overseer's OpenCode included, which is why the templates name `@CACHE@` instead. OpenCode's data, logins and
sessions, goes in `@DATA@` for the same reason: leave `~/.local/share/opencode` out of both lists. A tool whose cache
the wrapper does not move, such as cargo's under `~/.cargo`, writes under the `$HOME` the template hides, so its cache
lasts one run; to keep it, point it under the cache directory, by its absolute path, in the command after the
wrapper's `--`, such as `env CARGO_HOME=/home/you/.cache/canopy/sandbox/worker/cargo`: the template is split into
words, and no shell expands `$HOME` in it. Two more you are likely to need:

- **Push credentials.** A worker pushes from inside the sandbox, so its git credential helper does too. Add what the
  helper reads: `~/.config/gh` for `gh auth setup-git`, `~/.git-credentials` for the store helper. That token is in
  the worker's reach, as it is without a sandbox.
- **A workspace outside `$HOME`.** Add the workspace to `denyRead` in each template, so its `.canopy/` stays hidden.
  The wrapper denies `.canopy/` itself when the run's directories name it, but a chore with a `cwd` of its own names
  none.

OpenCode's local MCP servers start inside the sandbox and inherit its policy: each one's hosts must be on the
allowlist, and a server that reads credentials from `$HOME` needs those paths in `allowRead`. A server started with
`npx` or `uvx` needs its registry on the allowlist (`registry.npmjs.org`, or `pypi.org` and
`files.pythonhosted.org`), and fetches itself into the role's cache directory the first time it runs. A
server started with `docker run` cannot work: the sandbox refuses Unix sockets, the Docker daemon's included. Use the
server's binary, or its remote form, whose host goes on the allowlist like any other.

## 4. Push over HTTPS

A sandboxed worker cannot reach your SSH agent: on Linux, `srt` blocks making a Unix socket, which is how `ssh`
talks to the agent. Point each
primary clone's `origin` at its HTTPS URL, with a credential helper, and change the map's `url` to match:

```sh
git -C repos/api remote set-url origin https://github.com/acme/api.git
gh auth setup-git    # or any credential helper
```

`canopy workspace sync` warns about every push URL git would reach over SSH, after `insteadOf` rewrites.

## 5. Prefix the commands

In `~/.config/canopy/config.toml`, never a workspace file (TRUST_MODEL T7), put `canopy-sandbox`, its role, and `--`
before each command. `--read {definitions_dir}` lets the agent read canopy's agent definitions (D040).
`worker_cmd_prefix` goes before all three commands a worker run starts, `worker_cmd`, `private_worker_cmd`, and
`plan_cmd`; `canopy init` prints its line.

```toml
[runtime]
worker_cmd_prefix = 'canopy-sandbox worker --read {definitions_dir} --'
# Multi-line literal strings: the template is split into words, so a line break is only a space.
chore_cmd = '''canopy-sandbox chore --read {definitions_dir} --
    env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore --format json --thinking
    --title={title}'''
review_cmd = '''canopy-sandbox review --read {definitions_dir} --
    env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer --format json --thinking
    --title={title}'''
# setup_cmd takes no placeholders; give the wrapper no --read.
setup_cmd = "canopy-sandbox setup -- sh -c 'pnpm install --frozen-lockfile'"
```

- Prefix every one of them. If you wrap the worker templates by hand instead of with `worker_cmd_prefix`,
  `private_worker_cmd` is easy to miss, and a private ticket's worker then runs outside the sandbox.
- A chore with a `cmd` of its own (DESIGN §19) needs the prefix there too, with `--read {definitions_dir}` only if the
  command names it: `cmd = 'canopy-sandbox chore -- opencode run --agent build-health --format json'`.
- `overseer_cmd` takes a role of its own (The overseer, below).
- The reviewer reads the checkout and writes nothing in it, not even a commit, so `review.json` allows reading the
  checkout and its git directories and writing none of them, and leaves `github.com` off the allowlist.
- If your `PATH` has a relative entry, such as `.`, name the wrapper by its absolute path: canopy runs the template
  in the slot, where a relative entry finds what the branch committed.

### Or sandbox some repositories only

To sandbox the runs of some repositories and leave the rest as they are, name them instead of writing the prefixes,
also in `~/.config/canopy/config.toml` or the workspace's private file:

```toml
[runtime]
sandbox_repos = ["api", "billing"]
```

canopy then starts each worker run, `setup_cmd`, and review in those repositories in `canopy-sandbox` itself, with the
role above, by its absolute path beside canopy's own Python, so a relative `PATH` entry cannot find a branch's file in
its place. Runs in any other repository start as their templates have them. `canopy config commands` prints the
wrapped commands too.

- Leave the prefixes out: canopy refuses `sandbox_repos` beside a worker, setup, or review template that already starts
  in `canopy-sandbox`, which would sandbox those runs twice.
- A joint run, over several repositories, is one command, so it runs in one sandbox or none: canopy refuses a dispatch
  over repositories that disagree, as `mixed_sandbox`. Sandbox all of them or none.
- Chores name no repository; a chore's command is sandboxed only by its own prefix.

A sandboxed worker's new commits go to a per-run object directory, which canopy reads to push and then deletes, after
putting each slot back on the commit the run started from (DESIGN §8). An unsandboxed run leaves that directory
empty.

### The overseer

The overseer reads the most hostile text the loop sees, ticket text, and without a sandbox its OpenCode permissions are
its only limit. `overseer.json` is its policy, for the `overseer` role. Every run the overseer asks for is started by
the tick once the overseer's run has ended (DESIGN §40), outside its sandbox, so no run inherits the overseer's policy
or dies with it. The prefix is the same as the others':

```toml
[runtime]
overseer_cmd = '''canopy-sandbox overseer --read {definitions_dir} --
    env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer --format json --thinking
    --title={title}'''
```

The overseer starts in the workspace root, and acts through canopy's tools, a server its OpenCode starts inside the same
sandbox. Under the shipped template it:

- reads the workspace and its `.canopy/`, the user config file `~/.config/canopy/config.toml` and no other file
  beside it (the web UI's `listener-secret` is there), canopy's install, and OpenCode's files;
- writes, of `.canopy/`, only the journal, its locks, and `canopy.log`: not the private config, the agent definitions,
  the chores' agents and prompts, or any new file, such as an OpenCode config a chore or review that starts under
  `.canopy/` would load. The wrapper makes the journal's locks first, if canopy has yet to;
- reaches your model provider, your tracker's MCP endpoint, and GitHub's API hosts, not `github.com`.

Fill in `overseer.json` as the others: your model provider and tracker hosts, and, if canopy is installed anywhere
but `uv tool install`'s `~/.local/share/uv` and `~/.local/bin`, or `XDG_CONFIG_HOME` moves the user file, those
paths. A command `runtime.allow_bash` grants the overseer runs in the sandbox too, and needs what it reads in
`allowRead`.

## 6. Check that it works

With the loop stopped, run a plain script through the wrapper in a worktree made for the check, never in one of
canopy's slots: a commit there leaves the slot naming objects that are deleted with the check, and canopy's own
cleanup is not running to put it back. From the workspace root, with one of its repositories:

```sh
repo=$PWD/repos/api
check=$(mktemp -d)
git -C "$repo" worktree add --quiet --detach "$check/slot"
mkdir "$check/objects"
cd "$check/slot"
CANOPY_GIT_OBJECTS="$check/objects" canopy-sandbox worker -- sh -c '
  try() { if sh -c "$2" >/dev/null 2>&1; then echo "$1: allowed"; else echo "$1: refused"; fi; }
  try "read ~/.ssh" "cat ~/.ssh/*"
  try "read the user config" "cat ~/.config/canopy/config.toml"
  try "write a hook" "echo x > $(git rev-parse --git-common-dir)/hooks/post-checkout"
  try "move a branch" "git branch -f main HEAD"
  try "reach example.com" "curl -sSf -m 10 https://example.com"
  try "commit in the slot" "echo x >> sandbox-check && git add sandbox-check && git commit -qm check"
  try "reach github.com" "curl -sSf -m 10 -o /dev/null https://github.com"
'
cd - && git -C "$repo" worktree remove --force "$check/slot" && rm -rf "$check"
```

Every line but the last two should say `refused`, and the last two `allowed`. If your default branch is not `main`,
use its name in the branch line. Then run `canopy loop --ticks 1` on a ticket and read the run's log,
`.canopy/runs/<id>.log`: the worker should push and open its PR as before.

From a checkout of canopy, `make sandbox-canary` runs the whole canary against what `canopy sandbox setup` installed:
every denial and positive control DESIGN §24 lists, with the shipped templates unchanged. It needs to reach
github.com.

## Troubleshooting

- **`canopy-sandbox: no policy template at ...`** or **`srt is not installed`:** run `canopy sandbox setup`.
- **`... filesystem.allowRead names ..., which holds ...`** (or `allowWrite`): the template, or a chore's `cwd`, names
  a directory that holds the role caches, the run directories, or `.canopy/`, which would let one run read another's.
  Name the directories the command needs instead, and give a chore a `cwd` of its own, not `$HOME` or a directory
  above it.
- **`CANOPY_GIT_OBJECTS is not set`:** the wrapper's `worker` or `setup` role is on a command canopy does not run as
  a worker or setup, such as `review_cmd` or a chore's. Use the `review` or `chore` role there.
- **`... links to no worktree`:** the `review` role is on a command canopy does not run as a review, or a desk is
  empty. Use the role the command's key names.
- **`... is not a linked worktree`:** a worker or setup ran outside one of treehouse's slots. canopy always runs them
  in one; in the check above, run it in the worktree it makes.
- **`... has too long a path for srt's sockets`**, or `srt`'s own **`Failed to create bridge sockets`**: on Linux,
  `srt` makes the sockets that carry the sandbox's network in the run's temp directory, under the system one, and a
  socket's path holds at most 107 bytes. Run canopy with `TMPDIR` set to a shorter directory, such as `/tmp`.
- **Every request from the sandbox fails with `Failed to connect to localhost port 3128`**, allowed hosts included:
  on Linux, `srt` carries the sandbox's network to its proxy through socat, which listens on IPv6 unless told
  otherwise, and on a kernel without IPv6 exits unreported. On such a host the wrapper sets `SOCAT_DEFAULT_LISTEN_IP=4`
  for `srt`, unless you set it yourself, and `canopy sandbox setup` prints a `Note:` saying so. If you still see this,
  check that the command starts with `canopy-sandbox`, and that you have not set that variable to `6`.
- **bubblewrap fails with a permission error setting up the user namespace:** the Ubuntu restriction in step 1, or
  canopy running as root.
- **The worker cannot push:** an SSH remote (step 4), or a credential helper whose files are not in `allowRead`
  (step 3).
- **A run's OpenCode is not logged in:** a template without `@DATA@` in `allowRead` and `allowWrite`, as one copied
  before it was; `canopy sandbox setup` says which. Or the login is not in your own OpenCode data: log in there, as
  without a sandbox.
- **A build cannot fetch, or a tool cannot find its files:** a registry missing from `allowedDomains`, or a toolchain
  missing from `allowRead`. The error is the tool's own, in the run's log. A tool that writes outside `TMPDIR`, the
  worktree, and the cache directory needs its directory moved under the cache directory (step 3), or, if nothing of
  yours runs what it writes, in `allowWrite`.
- **Bazel:** the disk and repository caches and `--output_user_root` from [BAZEL.md](BAZEL.md) are your own builds'
  too. In `allowWrite`, a run can leave outputs there that your builds then use, outside the sandbox; left out, each
  run builds cold. Prefer the cold build, or a remote cache only CI writes, until DESIGN §24 settles Bazel caches of
  the sandbox's own. Expect each run's Bazel server to end with its sandbox, so a run starts its own.
- **A tool's git cannot write objects in the slot:** inside the sandbox, `git` on `PATH` is the wrapper's own, which
  points git at the run's object directory in the run's worktrees (DESIGN §24, Git state). A tool that runs git by its
  absolute path skips it, and the slot's shared object directory is read-only. Have the tool find `git` on `PATH`.
