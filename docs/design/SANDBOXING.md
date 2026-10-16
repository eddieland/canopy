# Sandboxed runs

Part of the canopy design, normative like all of it: the OS sandbox an operator can put around every agent run but the
overseer's. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Flaky
CI](FLAKY_CI.md).

## 24. Sandboxed runs (M26)

Built, opt-in, and not yet proven on the operator's machines (ROADMAP M26). A worker runs as the operator, reads text
other people wrote, and is assumed to follow injected instructions some of the time (TRUST_MODEL §3). Without a
sandbox its limits are OpenCode permissions, which are defense in depth (T4, D021), and its shell reaches the whole
machine: `~/.ssh`, the user config, the journal, the pool's shared git directory, and any host. The sandbox bounds that
for each run it wraps.

It is a prefix on the command templates, nothing more (D118). The harness never learns whether a run is sandboxed: it
passes every run `CANOPY_GIT_OBJECTS`, which an unsandboxed run ignores, and runs on the host only what reads nothing a
sandboxed run can write. What it defends and what it leaves open are TRUST_MODEL T4 and T6. The problem it answers,
its goals, and the options weighed for it are [HOST_ISOLATION](../HOST_ISOLATION.md) §1 to §3; the operator's guide is
[SANDBOX.md](../SANDBOX.md). The claims below about `srt` were checked against its source at version 0.0.79
(2026-10-09); re-check them when the pinned version changes.

The sandbox is Anthropic's `sandbox-runtime` (`srt`, Apache-2.0). It wraps any command using bubblewrap on Linux and
`sandbox-exec` on macOS, and routes all network traffic through a local proxy that enforces a domain allowlist. It
needs no image, reads the worktree in place, and runs on both platforms; the shared kernel is the gap, and a steered
agent using ordinary tools does not reach it. A container or a microVM was rejected for now (HOST_ISOLATION §3): each
needs an image carrying every toolchain, and Firecracker has no shared filesystem, which treehouse's leases and
`_run`'s push check need. `srt` is a beta, so canopy pins its version (D117). A hand-written bubblewrap or Seatbelt
profile behind the same wrapper is the fallback if `srt` changes under us; the harness would not notice the swap.

### The wrapper

The operator sets, in the user config only:

```toml
[runtime]
# A multi-line literal string: the template is split into words, so the line break is only a space.
worker_cmd = '''canopy-sandbox worker --read {definitions_dir} -- env OPENCODE_CONFIG_DIR={definitions_dir}
    opencode run --agent canopy-worker --format json {prompt}'''
```

`canopy-sandbox` is a short program that canopy installs beside itself, the uv workspace member
`packages/canopy-sandbox`, not harness code (D041, D117). Its first argument is a role, `worker`, `setup`, `chore`, or
`review`, which picks the policy template `~/.config/canopy/sandbox/<role>.json`; `--read` names a path the command may
read, which is how canopy's agent definitions, `<state_dir>/runtime/<digest>/`, are re-allowed: pass it
`{definitions_dir}`. Name the wrapper by its absolute path when `PATH` has a relative entry: canopy runs the template
from the slot, where `.` finds what the branch committed. It runs in the run's cwd, which `_run` sets to the slot or
the desk (§8, §18), and:

1. Drops from its environment, and so from the command's, what would point git at another repository (`GIT_DIR` and its
   kind), every relative `PATH` entry, so that neither its own `git` and `srt` nor git in the run is found through the
   checkout, and what the inner `bash -c` would act on, `BASH_ENV` and `ENV`.
2. Resolves the paths the policy needs: the cwd, each worktree a desk or a review's directory links to, and each
   worktree's own and common git directories (`git rev-parse --git-dir --git-common-dir`). A worker or setup outside a
   linked worktree is refused: a clone's HEAD and index live in the directory every slot shares. A desk is a directory
   with canopy's marker and no `.git`: a branch can commit the marker, and links to other slots beside it, but never a
   `.git`. A review's directory is canopy's, made private just before the reviewer starts (§21), so its link to the
   checkout is canopy's too; one with a `.git` is a checkout, and refused.
3. Writes a per-run policy from the template, filling in those paths, into a directory of its own that is private to the
   operator, with the run's temp directory beside it. It adds to `denyRead` the directory holding every run's, since the
   system temp directory is outside `$HOME`, and the workspace's `.canopy/` when the run's object directory or a chore's
   default cwd names it, for a workspace outside `$HOME`. It refuses a template with no `denyRead` or no network
   allowlist: `srt` runs a command whose policy restricts nothing without bubblewrap at all.
4. Sets the command's `TMPDIR`. `srt` passes the caller's environment through and adds its own: the proxy variables,
   `GIT_SSH_COMMAND`, `GIT_CONFIG_PARAMETERS`, and `TMPDIR`, which it takes from `CLAUDE_CODE_TMPDIR`, or else
   `/tmp/claude`, shared by every sandboxed process, so the wrapper sets that to the run's temp directory. It sets
   `srt`'s own `TMPDIR` there too, so what `srt` makes for the run goes when the run's directory does. On Linux that
   includes the Unix sockets that carry the sandbox's network, whose path holds at most 107 bytes, so the wrapper
   refuses a system temp directory too long to leave room for them; `srt` says only that it could not make them.
   macOS's deep per-user temp directory, which `srt`'s source suggested was too long for its 103-byte limit, is not:
   the canary's macOS job runs a case under it, so the check is Linux-only. It points the command's caches at the
   role's own cache directory (Caches, below). For a worker or setup, the wrapper puts a `git` of its own first on the
   command's `PATH`, which sets git's variables from `CANOPY_GIT_OBJECTS` in the run's worktrees only (Git state,
   below).
5. Runs the sandbox with that policy and the rest of its arguments unchanged, after a `--`: `srt --settings <policy> --
   "$@"`. Without it, `srt` reads its own options (`-c`, `-s`, `-d`, combined short forms too) anywhere in its
   arguments, and `-c` takes its value as a shell command, unquoted. It waits rather than `exec`, so that it can remove
   its directory when `srt` exits, after giving back any permission the command took from a directory in it; the
   directory of a run killed with SIGKILL, which is how canopy ends a timed-out run, is removed by the next run, once
   the process that made it is gone. `srt`'s seccomp helper runs inside the sandbox, so the wrapper re-allows reading
   `srt`'s `vendor/` directory wherever `srt` is installed, or a template that denies `$HOME` would hide it.

Because `worker_cmd` is a user-only key (TRUST_MODEL T7), a repository cannot remove the prefix. Because the sandbox
denies writes to `~/.config/canopy`, a worker cannot remove it either.

### What is wrapped

| Command | Role | Why |
| --- | --- | --- |
| `worker_cmd`, `private_worker_cmd`, `split_cmd` | `worker` | The work. |
| `runtime.setup_cmd` | `setup` | It runs the branch's code in the slot just before the worker (§9). |
| `runtime.chore_cmd`, a chore's `cmd` | `chore` | A chore using the operator's own tools has a shell for them (§19). |
| `review_cmd` | `review` | It reads the most hostile text the loop meets, a diff by anyone `review.query` matches (T1). |
| `overseer_cmd` | none | It acts through `canopy`, which needs the journal, the lock, and the user config. |
| `notify.cmd`, `git`, `treehouse` | none | The harness's own calls; what they read of a run is below. |

The overseer's sandbox would have to allow exactly what the policy denies. It has no edit or write tools, and its bash
is limited to `canopy *` and `treehouse status*` (§13); revisit if that changes. A review gets a role of its own: the
worker's policy would let it write the checkout and commit, and the `worker` role refuses it anyway, with no object
directory; a chore's would not find the checkout.

### Filesystem policy

Reads are denied under the home directory and re-allowed where needed. Writes are denied everywhere and allowed where
needed. A deny list of known secret paths was rejected: it always misses one. `srt`'s policy takes this shape: its
`allowRead` outranks `denyRead`, so a denied `$HOME` can re-allow directories under it (a denied file is re-allowed only
by naming that file). The shipped templates deny `$HOME`. For a workspace outside it, the wrapper denies `.canopy/`
itself where it can find it (step 3); a chore with a `cwd` of its own names no `.canopy/`, so the operator adds the
workspace to its template's `denyRead`.

| Path | Read | Write | Why |
| --- | --- | --- | --- |
| The cwd and every worktree a desk links to | yes | yes | The work. |
| Each worktree's `.git` link file | yes | no | Repointing it moves host-side git somewhere the worker owns. |
| The git common dir, except this slot's `worktrees/<slot>/` | yes | no | Shared by every slot (Git state, below). |
| This slot's `worktrees/<slot>/`, except `config.worktree`, `commondir`, `gitdir` | yes | yes | Its own HEAD, index, and reflog. |
| The run's object directory, `<state_dir>/runs/<id>.objects/` | yes | yes | New commits (§8). |
| The runtime's config (`~/.config/opencode`) | yes | no | A worker must not rewrite its own permissions. |
| The runtime's data and state (`~/.local/share/opencode`, ...) | yes | yes | Sessions and token refresh (Open, below). |
| Toolchains the build needs (`~/.local/bin`, `~/.cargo`, `~/.nvm`, ...) | yes | no | Running tests. |
| The role's cache directory, `~/.cache/canopy/sandbox/<role>/` | yes | yes | Every cache, the runtime's too (below). |
| The operator's own caches (`~/.cache`, `~/.npm`, ...) | no | no | The host runs what is in them. |
| A per-run temp directory, exported as `TMPDIR` | yes | yes | Scratch space. |
| A chore's own `cwd` (default `<state_dir>/chores/<name>/`) | yes | only if it writes | Chores only (below). |
| A review's directory (`<state_dir>/reviews/<id>/`) | yes | no | Reviews only (below). |
| canopy's agent definitions (`<state_dir>/runtime/<digest>/`) | yes | no | The agent's own definition (D040). |
| The rest of `~/.config/canopy` and the workspace's `.canopy/` | no | no | Config and journal belong to the harness. |
| The rest of `$HOME` | no | no | Secrets, other repositories. |

The run log is unaffected: the run's stdout and stderr are file descriptors `_run` opened before the sandbox started.
A write the policy refuses under a denied directory may look as if it worked: `srt` hides a denied directory under an
empty, writable `tmpfs`, and what is written there is gone when the run ends, without reaching the host. The canary
checks writes on the host for that reason.

A chore gets the same policy. Its default `cwd` is inside the workspace's `.canopy/`, so its policy re-allows that one
directory: read-only by default, since a chore's only output is its result line, and writable for a chore whose own
tooling writes there. The rest of `.canopy/` stays denied.

A review gets it too, with nothing in the checkout writable. It starts in `<state_dir>/reviews/<id>/`, which the policy
re-allows reading as it does a chore's `cwd`, and reads the checkout through the link there, so the checkout and its
git directories are readable, as for a worker, and none of them writable: the reviewer writes nothing (§21), and what
it reads was written by the PR's author. So it gets no object directory and no `git` of the wrapper's, and git in the
checkout reads and never writes. Its network allowlist leaves out `github.com`, since it neither fetches nor pushes.

### Caches

A cache is code the host runs later. OpenCode imports the npm packages it installs, providers and plugins, from
`~/.cache/opencode/packages/`, and runs `rg`, LSP servers, and formatters from `~/.cache/opencode/bin/` (from its
source at 1.19.0). The overseer is OpenCode too, outside any sandbox, under the same HOME, so a run that can write that
directory runs code on the host at the next tick. The first templates allowed it; the operator's own caches, which an
earlier SANDBOX.md said to add to `allowWrite`, are the same: npm, uv, Go, and pip install from them, and Bazel's disk
cache hands builds their outputs.

So no run writes the operator's caches. Each role has a cache directory of its own,
`$XDG_CACHE_HOME/canopy/sandbox/<role>/`, which the wrapper makes, private to the operator, and the templates allow
reading and writing as `@CACHE@`. Setup shares the worker's, since warming the worker's caches is its job (§9). The
wrapper points the command's `XDG_CACHE_HOME` there, which moves OpenCode's cache and most tools' on Linux, and
`npm_config_cache`, `GOCACHE`, `GOMODCACHE`, and `PIP_CACHE_DIR` under it, for npm, which never follows it, and for
Go and pip, which do not on macOS, whatever the operator set them to. It denies reading the directory that holds every
role's, so a review cannot read the worker's, nor a worker the review's, even for an `XDG_CACHE_HOME` outside the
HOME the templates deny. A review reads the most hostile text the loop meets (T1); what it leaves in its cache reaches
only later reviews, which write nothing in a checkout and reach no `github.com`. Rejected: the cache of each run its
own, in the run's directory, which would fetch every package and binary on every run; and one directory for every
role, which would hand what a review left to a worker.

What a role's runs share is theirs to poison for one another, as `/tmp/claude` is (Trust model changes, below): a
private ticket's worker and a public one share the worker's. Bazel's caches are the operator's own builds' too, and
nothing yet gives the sandbox Bazel caches of its own (Open, below). `canopy sandbox setup` says when a template it
kept still allows writing in the operator's cache directory.

### Git state

Git state is where the worktree boundary leaks. Every slot in a pool shares one common directory: refs, objects, hooks,
config, and every other slot's metadata. Path rules cannot give a worker write access to its own branch alone, because
git updates a ref through a lock file beside it and rewrites a shared `packed-refs`. A worker that can write refs can
move another running worker's branch, which that worker then builds on and pushes as its own. So a sandboxed worker
writes no shared git state:

- `_run` checks the branch out detached, so HEAD, the index, and the reflog live in `worktrees/<slot>/`, which belongs
  to that slot alone, and the worker pushes with `git push origin HEAD:refs/heads/<branch>` (§8, D109).
- New objects go to the run's object directory, with the shared object directory as an alternate (§8).
- A plain `git fetch` fails, since the configured refspec updates a shared remote-tracking ref. `_run` fetches just
  before the worker starts, and the resume prompt merges `origin/<base>` instead of fetching. A fetch that writes only
  `FETCH_HEAD`, which is per worktree, works (`git fetch --refmap= origin <ref>`), for a worker that needs something
  newer.

Checked with bubblewrap and git 2.43, a slot under exactly this policy: a commit on the detached HEAD, a merge of
`origin/<base>`, and the push by refspec all work, and the push leaves the shared remote-tracking refs alone. Moving any
ref, making a branch, writing the common `config`, a hook, `config.worktree`, or the `.git` link all fail.

`srt` cannot say "the common directory, except `worktrees/<slot>/`" as one read rule. Under a denied directory such as
`$HOME`, it binds each `allowWrite` path back and then each `allowRead` path read-only, so a common directory in
`allowRead` covers the slot's writable directory inside it, and the worker cannot commit. The wrapper's `@GIT_SHARED@`
therefore names what the common directory holds, entry by entry, and every other slot's `worktrees/` entry, but not
this run's. What the common directory gains after the run starts, such as a first `packed-refs`, is not visible inside
the sandbox. A `config.worktree` that does not exist yet is still denied: `srt` binds an empty file over it, which
bubblewrap creates on the host and `srt` removes when the run ends (a run killed with SIGKILL leaves it empty, which
git ignores without `extensions.worktreeConfig`).

Two more files in the slot's own directory point git elsewhere, and the wrapper's `@GIT_PROTECTED@` denies writing them
as it does `config.worktree` and the `.git` link. `commondir` names the common directory, so a worker that rewrites it
to a directory of its own, holding a `config`, `objects/`, and `refs/`, makes every git on the host in the slot read
that config and its hooks: `_run`'s step 5, the tidy step, and treehouse's `return`. Checked with git 2.43, a
`remote.origin.uploadpack` in such a config ran on `_run`'s `ls-remote`, D107's flags notwithstanding. `gitdir` is the
back link `git worktree` reads, which `prune` acts on. git writes neither in a slot's ordinary work. A file that exists
is bound read-only, so a rename over it or its removal fails too.

git's variables (`GIT_OBJECT_DIRECTORY`, and each slot's shared object directory, colon-separated, in
`GIT_ALTERNATE_OBJECT_DIRECTORIES`) apply to every repository, not only the slot. Set for a whole process tree, a commit
in any other repository lands in the run's directory, so that repository reads `bad object HEAD` once it is gone, and a
repository made with `git init` gets no `objects/` at all. That is how tools keep caches: Go fetches a module it cannot
get from a proxy into a bare repository in its module cache, and OpenCode keeps each worktree's snapshots in a git
directory under its data directory, which the templates keep writable from run to run. pre-commit is unaffected: it
drops `GIT_*` variables when it clones a hook's repository. So `_run` passes the directory only as
`CANOPY_GIT_OBJECTS` (§8), and the wrapper's own `git`, first on the command's `PATH` and in the run's directory,
readable and not writable, sets them. It finds the repository git would act on, from the cwd and any `-C`,
`--git-dir`, and `--work-tree` before the subcommand, with one `git rev-parse --git-common-dir`, and sets the variables
only when that is a common directory of the run's worktrees, never for `init` or `clone`; elsewhere it drops them if
they are the run's, as a git under `git rebase --exec` inherits them. A git run by its absolute path gets no variables:
elsewhere that is right, and in a slot it cannot write objects at all, so it fails rather than writing where it should
not. Rejected: setting git's variables in `_run` or the wrapper for the whole run, which sent Go's module sources and
OpenCode's snapshots to the run's directory and lost them when it went.

### Network policy

Everything is denied except an allowlist in the operator's policy template:

- The model provider's API host.
- GitHub: `github.com`, `api.github.com`, `*.githubusercontent.com`, and the GitHub MCP endpoint if it is remote.
- The tracker's MCP endpoint, and any internal MCP services the operator uses. Internal hosts need an explicit entry;
  that is the point of running canopy locally, so the template says so.
- The package registries the repository's build and tests fetch from.

`srt` also refuses to connect an allowed name to loopback, link-local, cloud metadata addresses, or the host's own
addresses. Private ranges can be denied too (`deniedResolvedAddresses`), unless internal MCP services live there. That
check is skipped when `srt` forwards through a parent proxy, which it takes from `HTTP(S)_PROXY` in the caller's
environment; behind a corporate proxy, the proxy's own rules are the address check.

No Unix sockets: on Linux `srt`'s seccomp filter blocks creating them, which includes the SSH agent's and the Docker
daemon's. So sandboxed runs push over HTTPS with a credential helper, through the proxy, and `canopy workspace sync`
warns about SSH remotes (§12).

The residual is exfiltration through an allowed host. With `github.com` allowed and the operator's token in reach, a
worker can still push to any repository or post anywhere the operator can (T6, Open below).

### OpenCode's MCP servers

From OpenCode's source (2026-10-14): a local MCP server is a child of OpenCode, started in the slot with OpenCode's
whole environment and its own `environment` entries, so it runs under the run's policy, `TMPDIR`, proxy, and `git`. It
reaches only hosts on the allowlist, and reads under `$HOME` only what `allowRead` names. What it writes under `$HOME`
outside `allowWrite` lands in `srt`'s `tmpfs` and is gone after the run, so a server started with `npx` or `uvx`
fetches itself each run, from a registry that must be on the allowlist; what it writes in an `allowWrite` path, such
as OpenCode's own data directories, stays. One started with `docker run` cannot work: the Docker daemon is a Unix
socket, which the sandbox refuses, and which would be a way out of it if it did not. Run such a server as a binary, or
use its remote form. A remote server is reached through `srt`'s proxy, so its host must be on the allowlist; OpenCode
keeps its OAuth tokens in its database under `~/.local/share/opencode`, which the worker template allows writing. None
of this needs a role or a template of its own.

### What the harness runs around a sandboxed run

The prefix alone moves the problem to the boundary: after the worker exits, `_run` runs git on the host in the slot the
worker just had, and treehouse runs git there when the slot is returned. That is code running outside the sandbox on
files a worker wrote. These hold with or without a sandbox:

1. Every git the harness runs has hooks, filesystem monitors, submodule fetches, and the `ext::` transport off (§8,
   D107). They do not stop a command the shared config names, a filter driver or `remote.<name>.uploadpack`; under the
   sandbox, a worker cannot write that config.
2. `_run` reads each slot's `.git` link before any git step and checks it, and the slot's `commondir`, when the worker
   exits; a changed one makes the run `crashed`, runs no git in any of its slots, and is put back before the slot is
   returned (§8 steps 2, 5, and 6). Reconcile does the same for a `_run` killed with SIGKILL, from the link `_run`
   recorded in `run_slots` (§15). The policy already denies writing both; this catches a template that forgot.
3. The run's object directory is tidied away on every exit path, the slots first, so that nothing in a slot or the
   primary clone names an object only that directory held (§8 step 6, §15).
4. `treehouse return --force`, which `_run` and reconcile call after the tidy step, ends the processes whose cwd is in
   the slot, then runs plain git there, without D107's flags: `rev-parse`, `remote`, `symbolic-ref`, and `config` in
   the primary clone it finds from the slot, `read-tree --reset -u` onto the base, and `clean -fd`, none of it over
   the network (from its source at the commit canopy pins). So a hook in the common directory, the filesystem monitor,
   and a filter driver the config names all run. A sandboxed worker writes none of those: not the common directory,
   and not where the slot finds it, since `commondir` is protected. A `.gitattributes` the worker leaves can select
   only a driver the operator's own config defines, such as Git LFS's, which then runs the operator's program on the
   base's content, as any checkout of a branch carrying that attribute would. treehouse's own hooks run only from the
   operator's user config, under the `$HOME` the templates deny. A template that drops `@GIT_PROTECTED@` from
   `denyWrite` is caught by canopy's own `commondir` check before any git runs. So a new step in a slot keeps D107's
   flags and runs after that check (D118).

The prompt reaches the runtime byte for byte. D023 keeps ticket text out of a shell, but `srt` joins its arguments into
one `bash -c` string after single-quoting each one, and quotes again at each layer it adds (`sh -c` around bubblewrap
on Linux, `env ... sandbox-exec` on macOS). That is the POSIX-safe form, but a second parser on ticket-written text.
The inner bash is neither a login nor an interactive shell, so it reads no rc file, but it would source `$BASH_ENV`,
which the wrapper drops. `_run` reads the prompt as UTF-8, so bytes that are not valid UTF-8 never reach the command
line. On Linux the whole quoted command is one argument to `sh`, so it must fit in one argument's limit (128 KiB);
`srt` refuses a longer one. If either is a problem, D023's own revisit clause applies: a `{prompt_file}` placeholder
naming the prompt file `_run` already writes.

Timeouts still end everything. `_run` kills the worker's process group with SIGKILL. `srt` starts nothing detached: it,
its shell, bubblewrap, and its proxies stay in that group. bubblewrap gets `--new-session`, so the sandboxed processes
are in a group of their own, but also `--die-with-parent` and a PID namespace, so they die with bubblewrap, and a
process started with `setsid` inside the sandbox ends with it. On macOS nothing starts a new group, so a process that
calls `setsid` escapes, as it would without a sandbox. canopy reads the result line, not the exit status, so `srt`
exiting 0 when its child dies of SIGTERM does not matter: a timeout is canopy's own clock.

No config key turns the sandbox on. `canopy sandbox setup` installs the templates and the pinned `srt`, and checks
what needs root (§12, D117); `canopy init` prints a suggested `worker_cmd`. Neither writes the config.

### The canary

OpenCode's permissions needed a model to test (D021). The sandbox does not: it is the boundary, so a plain script run
through the real prefix is the test. `tests/canopy/test_sandbox_canary.py`, opt-in with `CANOPY_SANDBOX_CANARY=1` and
run by `make sandbox-canary` and CI's `sandbox-canary` job on Linux and macOS, sets the machine up the way
docs/SANDBOX.md tells the operator to, runs `canopy sandbox setup`, and uses the shipped templates unchanged, with a
primary clone and two slots under a fake `$HOME` laid out as treehouse lays them out. Each case is its own run, and
every run prints a marker first, so an attempt that failed because nothing ran fails the test. A write is checked on
the host, never by whether the attempt reported an error. Every attempt must fail:

- Read a fake SSH key, and anything else under `$HOME` outside the policy.
- Write `~/canary`, `~/.bashrc`, `~/.config/canopy/config.toml`, the operator's `~/.cache/opencode`, and anything
  under the state directory; read or write another role's cache directory.
- Move another slot's branch or any other ref, write the common directory's `config` or `hooks/post-checkout`, a
  `config.worktree`, the slot's `commondir` or `gitdir`, or the slot's `.git` link. What the slots share is compared
  file by file on the host: `git pack-refs` and `git gc` change no ref a `for-each-ref` shows.
- Connect to a host not on the allowlist, to `169.254.169.254`, to a port on the host's loopback, and to a Unix socket
  the host listens on, even one in the slot. A connection is tried both through `srt`'s proxy and around it, and must
  be refused the way that route refuses: through the proxy, with the `X-Proxy-Error: blocked-by-allowlist` header
  `srt` sends and no other proxy does; around it, with no route at all. So a certificate error, another proxy's 403, or
  a sandbox with no network passes nothing.

The attempts on `$HOME` and the state directory run as `setup`, `chore`, and `review` too: a chore in its default
directory under the state directory, which is how the wrapper finds the state directory for a workspace outside
`$HOME`, and a review in its directory there, linked to the slot. A review must also fail to write the checkout, its
HEAD and index, and the shared git directory.

The positive controls must succeed, so a sandbox that blocks everything cannot pass: write and commit in the slot, its
objects only in the run's directory; commit in a repository a tool keeps as a cache, its objects in its own; write a
cache that the role's next run reads, in the role's cache directory on the host; read the checkout as a review; reach
an allowed host; receive a hypothesis-generated prompt byte for byte, over quotes, newlines, `$()`, backticks, and
arbitrary Unicode text; and be killed at a short timeout, leaving no process behind (on macOS, which has no `setsid`
command, only the processes in the sandbox's group are checked).

Every case runs under a short temp directory of its own, since `srt` makes its network sockets in the run's temp
directory and pytest's is too long for them, but one, which runs under the system's. Run against a fake `srt` that
sandboxes nothing, the canary fails every case but its positive controls, and, on a machine with no direct route to the
internet, the direct attempt on a host off the allowlist. A sleeper the run leaves must not hold its output, or a
sandbox that lets one outlive the run hangs the test instead of failing it. On Linux it needs bubblewrap and
unprivileged user namespaces, which Ubuntu 24.04 and later restrict by default
(`kernel.apparmor_restrict_unprivileged_userns`); docs/SANDBOX.md says how to lift that.

### Trust model changes

TRUST_MODEL T4 and T6 name the sandbox as an opt-in control (D118), with what it does not cover: the shared kernel, the
unwrapped overseer and harness calls, `/tmp/claude`, which every process `srt` sandboxes can write whatever the policy
says, so two runs can pass files through it, and exfiltration through an allowed host with the credentials a run holds.
The rest of the system temp directory stays readable, as other system paths do: denying it breaks tools that write
there without reading `TMPDIR`.

### Open

- SSH pushes. `srt`'s per-path `allowUnixSockets` is macOS-only; on Linux the only switch is `allowAllUnixSockets`,
  which lifts the block entirely. Whether to support SSH inside the sandbox at all (allow the agent socket, or push
  from the host in `_run`), or leave it to unsandboxed runs, is undecided.
- The runtime's data and state directories. The templates leave `~/.local/share/opencode` and
  `~/.local/state/opencode` writable, for sessions and OAuth tokens, and the overseer's OpenCode reads them too. Its
  data directory holds, among others, the git directories of its snapshots, which OpenCode runs git in with its own
  flags, not D107's. Whether anything there runs as code in the overseer is not yet traced; if it does, sandboxed runs
  need data of their own too, with the credentials they need copied or passed in.
- Bazel's caches. §9 shares them across slots, and BAZEL.md through the operator's own `~/.bazelrc`, so its own
  builds share them too. A sandboxed run may not write them (Caches, above), so it builds cold, until a bazelrc that
  only sandboxed runs read points them under the cache directory.
- The repository's OpenCode config (skills, MCP servers, plugins) comes from the checked-out branch (T7 residual).
  canopy's own agent definitions no longer do (D040, D044). The sandbox does not change that, but it bounds what a
  hostile config can reach.
- `sandbox-exec` is marked deprecated on macOS, though the Seatbelt framework it drives is what Chrome and several agent
  runtimes still use. Apple's `container` (a lightweight VM per container) is the macOS fallback if it goes away.
- Credential scoping. A fine-grained GitHub token limited to the pool's repositories closes most of the network
  residual. `srt` also has an experimental mode that gives the sandbox a placeholder credential and substitutes the
  real one only on requests to named hosts; evaluate it once the sandbox is in use.
- A hypervisor boundary, if canopy ever runs workers off the operator's machine: a microVM with virtiofs behind the same
  prefix, a different wrapper.
- Making the sandbox the default, once the canary passes on the operator's machines and a day of sandboxed runs (D118).
