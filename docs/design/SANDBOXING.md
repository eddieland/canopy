# Sandboxed runs

Part of the canopy design, normative like all of it: the OS sandbox an operator can put around every agent run but the
overseer's. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Flaky
CI](FLAKY_CI.md). Next: [Plans](PLANNING.md).

## 24. Sandboxed runs

Opt-in, and not yet proven on the operator's machines. A worker runs as the operator, reads text other people wrote,
and is assumed to follow injected instructions some of the time (TRUST_MODEL §3). Without a sandbox its limits are
OpenCode permissions, which are defense in depth (T4, D021), and its shell reaches `~/.ssh`, the user config, the
journal, the pool's shared git directory, and any host. The sandbox bounds that for each run it wraps.

It is a prefix on the command templates, nothing more (D118). The harness never learns whether a run is sandboxed: it
passes every run `CANOPY_GIT_OBJECTS`, which an unsandboxed run ignores, and runs on the host only what reads nothing a
sandboxed run can write. It defends TRUST_MODEL T4 and T6, and leaves open the shared kernel, the unwrapped overseer and
harness calls, `/tmp/claude`, which every process `srt` sandboxes can write, and exfiltration through an allowed host.
Options weighed: [HOST_ISOLATION](../HOST_ISOLATION.md) §1 to §3. The operator's guide: [SANDBOX.md](../SANDBOX.md).

The sandbox is Anthropic's `sandbox-runtime` (`srt`): bubblewrap on Linux, `sandbox-exec` on macOS, and all network
traffic through a local proxy that enforces a domain allowlist. It is a beta, so canopy pins the version this section was
checked against (D117). Rejected for now: a container or microVM, which needs an image carrying every toolchain and,
for Firecracker, has no shared filesystem for leases and `_run`'s push check.

### The wrapper

The operator sets a prefix for each command, or `worker_cmd_prefix` for the four a worker run starts, in the user file
or the workspace's private file (§12), never the workspace file. The prefix runs `canopy-sandbox`, a short program canopy
installs beside itself, not harness code (D041, D117), with a role, `worker`, `setup`, `chore`, or `review`, that picks
a policy template in `~/.config/canopy/sandbox/`. It:

- drops what would point git at another repository, relative `PATH` entries, and `BASH_ENV` and `ENV`;
- refuses a worker or setup outside a linked worktree, whose HEAD and index every slot would share, a desk or review
  directory with a `.git`, which a branch could commit, and a template with no `denyRead` or no network allowlist;
- gives the run a policy and a temp directory of its own, which other runs cannot read, the role's cache (Filesystem
  policy), and, for a worker or setup, its own `git` first on `PATH` (Git state).

Because `runtime.*` keys are private (TRUST_MODEL T7), a repository cannot remove the prefix; because the sandbox denies
writes to `~/.config/canopy`, a worker cannot either. Nothing canopy runs writes the prefix into the config (§12).

### What is wrapped

| Command | Role | Why |
| --- | --- | --- |
| `worker_cmd`, `private_worker_cmd`, `split_cmd`, `plan_cmd` | `worker` | The work. |
| `runtime.setup_cmd` | `setup` | It runs the branch's code in the slot just before the worker (§9). |
| `runtime.chore_cmd`, a chore's `cmd` | `chore` | A chore using the operator's own tools has a shell for them (§19). |
| `review_cmd` | `review` | It reads the most hostile text the loop meets, a diff by anyone `review.query` matches (T1). |
| `overseer_cmd` | none | It acts through `canopy`, which needs the journal, the lock, and the operator's config. |
| `plan_triage_cmd` | none yet | It reads primary clones, which no role expects; which role holds it is open (§25). |
| `notify.cmd`, `git`, `treehouse` | none | The harness's own calls; what they read of a run is below. |

The overseer's sandbox would have to allow exactly what the policy denies; it has no write tools and its bash is limited
to `canopy *` and `treehouse status*` (§13), so revisit if that changes.

### Filesystem policy

Reads are denied under `$HOME` and re-allowed where needed; writes are denied everywhere and allowed where needed, not
a deny list of secret paths, which always misses one.

| Path | Read | Write | Why |
| --- | --- | --- | --- |
| The cwd and every worktree a desk links to | yes | yes | The work. |
| Each worktree's `.git` link file | yes | no | Repointing it moves host-side git somewhere the worker owns. |
| The git common dir, except this slot's own directory | yes | no | Shared by every slot (Git state). |
| This slot's own directory, except `config.worktree`, `commondir`, `gitdir` | yes | yes | Its HEAD, index, reflog. |
| The run's object directory, its temp directory, the role's cache | yes | yes | Commits (§8), scratch, caches. |
| The runtime's data and state (`~/.local/share/opencode`, ...) | yes | yes | Sessions and tokens (Open). |
| Toolchains, the runtime's config, canopy's agent definitions | yes | no | Tests; a worker must not rewrite its permissions (D040). |
| The operator's own caches (`~/.cache`, `~/.npm`, ...) | no | no | The host runs what is in them. |
| `~/.config/canopy`, the workspace's `.canopy/`, the rest of `$HOME` | no | no | Config, journal, secrets. |

A write refused under a denied directory can look as if it worked, so the canary checks writes on the host. A chore's
default `cwd`, inside `.canopy/`, is re-allowed, writable only for a chore that writes; the journal stays denied. A
review reads the checkout and its git directories and writes none of them, since what it reads was written by the PR's
author (§21); it gets no object directory, no wrapper `git`, and no `github.com`.

A cache is code the host runs later, by the unsandboxed overseer's OpenCode or a package manager, so no run writes the
operator's caches. Each role has a cache of its own instead; setup shares the worker's (§9), and no role reads
another's, though a role's runs, private and public, can poison theirs for one another. Rejected: a cache per run, which
fetches everything every run, and one for every role, which hands what a review left to a worker.

### Git state

Every slot in a pool shares one common directory: refs, objects, hooks, config, and every other slot's metadata. Path
rules cannot give a worker its own branch alone, and a worker that can write refs can move another running worker's
branch, which that worker then pushes as its own. So a sandboxed worker writes no shared git state:

- `_run` checks the branch out detached, so HEAD, the index, and the reflog are the slot's alone, and the worker pushes
  `HEAD:refs/heads/<branch>` (§8, D109).
- New objects go to the run's object directory, with the shared one as an alternate (§8).
- A plain `git fetch` fails, since it updates a shared ref; `_run` fetches just before the worker starts.

The slot's `.git` link, `config.worktree`, `commondir`, and `gitdir` cannot be written, renamed, or removed: a rewritten
`commondir` would make every git the host runs in the slot read the worker's config and hooks.

The wrapper's own `git`, which the run cannot write, sets git's object variables from `CANOPY_GIT_OBJECTS` only when
git acts on one of the run's worktrees; set for a whole process tree, they would lose every cache repository's objects.
A git run by its absolute path gets none, and fails rather than writing where it should not.

### Network policy

Everything is denied except an allowlist in the operator's template: the model provider, GitHub, the tracker's and any
internal MCP endpoints, and the package registries the build needs. `srt` also refuses to connect an allowed name to
loopback, link-local, metadata, or the host's own addresses, except behind a parent proxy, whose rules then decide. No
Unix sockets, the SSH agent's and the Docker daemon's included, so sandboxed runs push over HTTPS, and
`canopy workspace sync` warns about SSH remotes (§12). The residual is exfiltration through an allowed host: with
`github.com` and the operator's token in reach, a worker can still push or post anywhere the operator can (T6, Open).

### What the harness runs around a sandboxed run

After the worker exits, `_run` and then treehouse run git on the host in files a worker wrote. These hold with or
without a sandbox:

1. Every git the harness runs has hooks, filesystem monitors, submodule fetches, and the `ext::` transport off (§8,
   D107). That does not stop a command the shared config names; under the sandbox, a worker cannot write that config.
2. `_run` reads each slot's `.git` link before any git step, and checks it and `commondir` when the worker exits; a
   changed one makes the run `crashed`, runs no git in its slots, and is put back before the slot is returned (§8 steps
   2, 5, and 6). Reconcile does the same for a killed `_run` (§15). This catches a template that forgot to deny them.
3. The run's object directory is tidied away on every exit path, the slots first, so nothing on the host names an
   object only it held (§8 step 6, §15).
4. `treehouse return --force` runs plain git in the slot, without D107's flags, after the tidy step. A sandboxed worker
   writes nothing that git would run. So a new step in a slot keeps D107's flags and runs after the `commondir` check
   (D118).

The prompt reaches the runtime byte for byte, though `srt` passes it through one quoted `bash -c` string, a second
parser on ticket-written text; if that becomes a problem, D023's revisit clause applies. Timeouts still end everything;
on macOS a process that calls `setsid` escapes, as it would unsandboxed.

### The canary

The sandbox needs no model to test (unlike D021): a script run through the real prefix, with the shipped templates and
the machine set up as SANDBOX.md says, is the test. Writes are checked on the host. Every attempt must fail:

- Read a fake SSH key or anything under `$HOME` outside the policy; write under `$HOME`, `~/.config/canopy`, the
  operator's runtime cache, or the state directory; read or write another role's cache.
- Move another slot's branch or any ref; write the common directory's config or hooks, or the slot's `.git` link,
  `config.worktree`, `commondir`, or `gitdir`.
- Connect off the allowlist, to a metadata address, the host's loopback, or a host Unix socket, through `srt`'s proxy
  and around it, refused the way that route refuses. As `review`, write the checkout or its git directories.

Positive controls must succeed, so a sandbox that blocks everything cannot pass: commit in the slot, its objects only
in the run's directory, and in a tool's cache repository; keep the role's cache; read the checkout as a review; reach
an allowed host; run under the system temp directory; receive any prompt byte for byte; die at a timeout, leaving no
process behind.

### Open

- SSH pushes: lift the socket block, push from the host, or leave SSH to unsandboxed runs.
- The runtime's data directory is a way out: writable for sessions and tokens, and read outside any sandbox by the
  overseer's OpenCode and the operator's own, where what a run wrote there can run code. Closing it means data of the
  sandbox's own; how sandboxed runs then get credentials is the operator's call.
- Bazel's caches: a sandboxed run may not write them, so it builds cold until it has caches of its own.
- `sandbox-exec` is deprecated on macOS; Apple's `container` is the fallback.
- Credential scoping: a GitHub token limited to the pool's repositories closes most of the network residual.
- Making the sandbox the default, once the canary passes on the operator's machines and a day of sandboxed runs (D118).
