# Running workers in a sandbox

How to run canopy's workers, setup commands, and chores inside an OS sandbox, so that a worker steered by text in a
ticket cannot read your secrets, rewrite canopy's config, or reach hosts you did not list. Everything here is your own
config and what `canopy sandbox setup` installs: the loop sees only the command templates, and none of this is
required to run it.
For why it works this way and what it was checked against, see [HOST_ISOLATION.md](HOST_ISOLATION.md); for what it
does and does not defend against, TRUST_MODEL T4 and T6.

The sandbox is opt-in and not yet proven: ROADMAP M26 is open, and the canary that checks every property in CI
(HOST_ISOLATION §6) is still to come. Try it on your machine with the check below before you rely on it.

## What a sandboxed run can do

A run's command starts in `canopy-sandbox`, a short wrapper canopy installs beside itself. The wrapper writes a policy
for that run from a template of yours and runs the command under `srt`, Anthropic's sandbox runtime, which uses
bubblewrap on Linux and `sandbox-exec` on macOS and sends all network traffic through a proxy that enforces a domain
allowlist. Under the shipped templates:

| | Allowed | Refused |
| --- | --- | --- |
| Read | the run's worktrees and their git directories, canopy's agent definitions, the runtime's files, the toolchains you list | the rest of `$HOME`: `~/.ssh`, cloud credentials, other repositories, `~/.config/canopy`, the workspace's `.canopy/` |
| Write | the run's worktrees, its own HEAD and index, a per-run object directory, a per-run temp directory, the runtime's data | everything else, shared git state included: no branch moves, no hooks, no git config |
| Network | the hosts in the template's allowlist | every other host, loopback, link-local, and cloud metadata addresses |

A write the policy refuses under `$HOME` may look as if it worked: `srt` puts an empty, writable `tmpfs` over a denied
directory, and what is written there is gone when the run ends. Nothing reaches the host.

What it does not cover: a worker can still send anything to a host you allowed, with the credentials it has, such as
your GitHub token; the overseer and the reviewer (`review_cmd`) are not wrapped; and the sandbox shares the kernel,
so it is no defense against an exploit written to escape it (HOST_ISOLATION §2, §4.3, §4.4).

## 1. Run `canopy sandbox setup`

```sh
canopy sandbox setup
```

It installs what it can without root, prints what is left as `To do:` lines, and exits 1 until nothing is. Run it
again after each upgrade of canopy: it keeps your templates and installs a new `srt` when canopy pins one. It:

- copies the policy templates to `~/.config/canopy/sandbox/`, never over one that is there;
- installs `srt`, pinned by a lockfile canopy ships, with `npm ci`, into `~/.local/share/canopy/sandbox-runtime/`. That
  needs Node 22.12 or later and npm on `PATH`. A worker cannot write there, and the wrapper prefers that `srt` to any
  other on `PATH`;
- checks what needs root, which it never runs, and prints the commands for it (below).

On Linux, `srt` needs bubblewrap, socat, and ripgrep:

```sh
sudo apt-get install bubblewrap socat ripgrep
```

On macOS it needs ripgrep (`brew install ripgrep`); `sandbox-exec` comes with the system.

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

`canopy-sandbox` comes with canopy: `uv tool install` puts it on `PATH` beside `canopy`. From a release's single
executable, setup tells you to put a script on `PATH` that runs it, as README does for the notification sinks:

```sh
#!/bin/sh
exec env SCIE_BOOT=canopy-sandbox /path/to/canopy "$@"
```

The wrapper reads the template for its role from `$XDG_CONFIG_HOME/canopy/sandbox/` (`~/.config/canopy/sandbox/` when
that is unset):

| Template | Used for |
| --- | --- |
| `worker.json` | `worker_cmd`, `private_worker_cmd`, and `split_cmd` |
| `setup.json` | `setup_cmd` |
| `chore.json` | `chore_cmd` and each chore's own `cmd` |

It runs the `srt` in `~/.local/share/canopy/sandbox-runtime/` (under `$XDG_DATA_HOME` when that is set), or else the
first on `PATH`. It drops every relative entry from `PATH`, so `git`, and any other `srt`, must be on `PATH` through
an absolute one. `srt` runs its seccomp helper inside the sandbox, so the wrapper lets each run read `srt`'s own
`vendor/` directory, wherever `srt` is installed.

`srt` is a beta. canopy pins the version HOST_ISOLATION was checked against; to try another, install it on `PATH`
and remove canopy's, and re-read HOST_ISOLATION's claims first.

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
and `~/.local/share/uv` are there. A toolchain is readable, not writable; a cache a build writes to goes in
`allowWrite` too. Two more you are likely to need:

- **Push credentials.** A worker pushes from inside the sandbox, so its git credential helper does too. Add what the
  helper reads: `~/.config/gh` for `gh auth setup-git`, `~/.git-credentials` for the store helper. That token is in
  the worker's reach, as it is without a sandbox.
- **A workspace outside `$HOME`.** Add the workspace to `denyRead` in each template, so its `.canopy/` stays hidden.
  The wrapper denies `.canopy/` itself when the run's directories name it, but a chore with a `cwd` of its own names
  none.

OpenCode's local MCP servers start inside the sandbox and inherit its policy: each one's hosts must be on the
allowlist, and a server that reads credentials from `$HOME` needs those paths in `allowRead`.

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
before each command. `--read {definitions_dir}` lets the agent read canopy's agent definitions (D040). `canopy init`
prints the `worker_cmd` line for your current template.

```toml
[runtime]
# Multi-line literal strings: the template is split into words, so a line break is only a space.
worker_cmd = '''canopy-sandbox worker --read {definitions_dir} --
    env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --format json --title={title} {prompt}'''
private_worker_cmd = '''canopy-sandbox worker --read {definitions_dir} --
    env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker-private --format json
    --title={title} {prompt}'''
split_cmd = '''canopy-sandbox worker --read {definitions_dir} --
    env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-splitter --format json --title={title} {prompt}'''
chore_cmd = '''canopy-sandbox chore --read {definitions_dir} --
    env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore --format json --title={title} {prompt}'''
# setup_cmd takes no placeholders; give the wrapper no --read.
setup_cmd = "canopy-sandbox setup -- sh -c 'pnpm install --frozen-lockfile'"
```

- Prefix every one of them. `private_worker_cmd` is easy to miss, and a private ticket's worker then runs outside the
  sandbox.
- A chore with a `cmd` of its own (DESIGN §19) needs the prefix there too, with `--read {definitions_dir}` only if the
  command names it: `cmd = 'canopy-sandbox chore -- opencode run --agent build-health --format json {prompt}'`.
- Leave `overseer_cmd` and `review_cmd` as they are. The overseer needs the journal and the config the sandbox
  denies, and `canopy-sandbox worker` refuses a command canopy does not run as a worker.
- If your `PATH` has a relative entry, such as `.`, name the wrapper by its absolute path: canopy runs the template
  in the slot, where a relative entry finds what the branch committed.

A sandboxed worker's new commits go to a per-run object directory, which canopy reads to push and then deletes, after
putting each slot back on the commit the run started from (DESIGN §8). An unsandboxed run leaves that directory
empty.

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

## Troubleshooting

- **`canopy-sandbox: no policy template at ...`** or **`srt is not installed`:** run `canopy sandbox setup`.
- **`CANOPY_GIT_OBJECTS is not set`:** the wrapper's `worker` or `setup` role is on a command canopy does not run as
  a worker or setup, such as `review_cmd`. Remove it there.
- **`... is not a linked worktree`:** a worker or setup ran outside one of treehouse's slots. canopy always runs them
  in one; in the check above, run it in the worktree it makes.
- **bubblewrap fails with a permission error setting up the user namespace:** the Ubuntu restriction in step 1, or
  canopy running as root.
- **The worker cannot push:** an SSH remote (step 4), or a credential helper whose files are not in `allowRead`
  (step 3).
- **A build cannot fetch, or a tool cannot find its files:** a registry missing from `allowedDomains`, or a toolchain
  missing from `allowRead`. The error is the tool's own, in the run's log. A tool that writes outside `TMPDIR` and
  the worktree needs its directory in `allowWrite`.
- **Bazel:** put the disk and repository caches and `--output_user_root` from [BAZEL.md](BAZEL.md) in `allowWrite`
  of `worker.json` and `setup.json`. Expect each run's Bazel server to end with its sandbox, so a run starts its own.
- **A Go module cache or pre-commit breaks after a sandboxed run:** a tool that keeps a git repository in its cache
  writes that repository's objects to the run's object directory, which is deleted when the run ends. Give the
  sandbox a cache of its own, or keep such tools out of sandboxed builds (HOST_ISOLATION §7, open).
