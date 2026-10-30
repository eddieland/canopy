# Sandboxed runs

Part of the canopy design, normative like all of it: the OS sandbox an operator can put around each agent run. Sections
are numbered across the whole design; the [README](README.md) has the map. Previous: [Flaky CI](FLAKY_CI.md). Next:
[Plans](PLANNING.md).

## 24. Sandboxed runs

Opt-in, and not yet proven on the operator's machines. A worker runs as the operator and is assumed to follow
injected instructions some of the time (TRUST_MODEL §3); without a sandbox its limits are OpenCode permissions, defense
in depth (T4, D021). The sandbox is the boundary for each run it wraps; T4's and T6's residuals hold what it leaves
open. Options weighed: [HOST_ISOLATION](../HOST_ISOLATION.md). Guide: [SANDBOX.md](../SANDBOX.md).

It is a prefix on the command templates, nothing more (D118): the operator's own, or the one canopy adds for a run in a
repository `runtime.sandbox_repos` names. Beyond adding it, the harness never learns whether a run is sandboxed: it
passes every run `CANOPY_GIT_OBJECTS`, which an unsandboxed run ignores, and runs on the host only what reads nothing a
sandboxed run can write. The sandbox is Anthropic's `sandbox-runtime` (`srt`): bubblewrap on Linux, `sandbox-exec` on
macOS, and all network traffic through a local proxy that enforces a domain allowlist. It is a beta, so canopy pins the
version this section was checked against (D117).

### The wrapper

The prefix runs `canopy-sandbox`, a program canopy installs beside itself, not harness code (D041, D117), with a role
that picks the operator's policy template. The prefix is private config (§12, T7), so no repository can remove it, and
the sandbox denies writes to canopy's config, so no worker can; nothing canopy runs writes it. The wrapper strips the
environment that would point git elsewhere or run a startup file; refuses a run outside the place its role starts in,
and a template with no read denials, no network allowlist, or an allowance over what it denies every run; and gives
each run a policy, a private temp directory, the role's cache and data, and, for a worker or setup, its own `git`. The
prompt passes through `srt`'s quoted shell string byte for byte (D023's revisit clause). Timeouts end everything; on
macOS a process that calls `setsid` escapes.

### What is wrapped

The `worker` role wraps `worker_cmd`, `private_worker_cmd`, and `plan_cmd`; `setup` wraps `runtime.setup_cmd`, which
runs the branch's code just before the worker (§9); `chore` wraps `runtime.chore_cmd` and a chore's `cmd` (§19);
`review` wraps `review_cmd`, which reads the most hostile text the loop meets (T1). `overseer` wraps `overseer_cmd` and
the tools' server its runtime starts (§27); the runs it asks for start outside it, from the tick (§40), so none
inherits its sandbox or ends with it. Unwrapped: the harness's own `notify.cmd`, `git`, and `treehouse`.

`runtime.sandbox_repos` sandboxes some repositories and not others: canopy starts a worker run, `setup_cmd`, and a
review in one of them in the wrapper, with the role above, by its absolute path beside canopy's interpreter, so no
branch's file stands in for it. It is private, as the prefix is, and refused beside a template that already starts in
the wrapper. One run is one command, so a joint run whose repositories disagree is refused at dispatch. Chores name no
repository, and keep their own prefix.

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
| A worker's or a review's answers directory | yes | no | The operator's answer to the question it asks (§41). |
| The role's own runtime data, and the runtime's state | yes | yes | Sessions, and a copy of the logins (below). |
| The operator's runtime data | no | no | The host's runtime acts on what is in it (below). |
| Toolchains, the runtime's config, canopy's agent definitions | yes | no | Tests; a worker must not rewrite its permissions (D040). |
| The operator's own caches | no | no | The host runs what is in them. |
| canopy's config, the workspace's `.canopy/`, the rest of `$HOME` | no | no | Config, journal, secrets. |

A chore's default working directory, inside `.canopy/`, is writable only for a chore that writes. A review writes none
of its checkout or git directories (§21) and gets no object directory, no wrapper `git`, and no GitHub. The overseer
reads its workspace and the user config file, and of `.canopy/` writes only the journal, its locks, and canopy's log:
the rest is config and code canopy and its agents load later. Each role has a cache and runtime data of its own, setup
sharing the worker's (§9); no role reads another's. The runtime's data is code the host runs too, a planted login
making the operator's runtime run what a run chose, so no run writes the operator's. They log in once (2026-10-18):
the wrapper copies their logins in before each run, and after it takes back only an OAuth refresh of a login they have,
never a new login or a field that says where a token goes or whose it is; copying in alone would turn a rotated
refresh token into a logout. A run can still hand back a bad token, or another account's (T4).

### Git state

A pool's slots share one common directory, refs, hooks, and config included, so a worker that can write refs can move
another running worker's branch, which that worker then pushes as its own. A sandboxed worker writes no shared git
state: it works on a detached HEAD and pushes by refspec (§8, D109), puts new objects in the run's own object
directory (§8), and leaves fetching to `_run`. It cannot touch the slot's `.git` link, `config.worktree`, `commondir`,
or `gitdir`, which would point the host's git at its config and hooks.

### Network policy

Everything is denied but the operator's allowlist: the model provider, GitHub, MCP endpoints, and the build's package
registries. An allowed name never connects to loopback, link-local, metadata, or the host's own addresses, except
behind a parent proxy. No Unix socket is reachable, the SSH agent's included, so sandboxed runs push over HTTPS (§12).

### What the harness runs around a sandboxed run

`_run` and then treehouse run git on the host in files a worker wrote, so these hold with or without a sandbox:

1. Every git the harness runs has hooks, filesystem monitors, submodule fetches, and `ext::` off (§8, D107).
2. A slot whose `.git` link or `commondir` changed makes the run `crashed`, runs no git in it, and is put back before
   the slot is returned (§8 steps 2, 5, and 6; reconcile for a killed `_run`, §15).
3. The run's object directory is tidied away on every exit path, the slots first (§8 step 6, §15).
4. treehouse's return runs plain git after the tidy step, and a sandboxed worker writes nothing it would run. A new
   step in a slot keeps D107's flags and runs after the `commondir` check (D118).

### The canary

A script through the real prefix and shipped templates, no model (unlike D021), is the test; writes are checked on
the host. Every attempt must fail:

- Read a fake SSH key or anything under `$HOME` outside the policy; write under `$HOME`, canopy's config, the
  operator's runtime cache or data, or the state directory; read or write another role's cache or data.
- Move any ref; write the common directory's config or hooks, or the slot's `.git` link, `config.worktree`,
  `commondir`, or `gitdir`; as `review`, write the checkout or its git directories; as `overseer`, write the
  workspace, or its state but the journal's files.
- Connect off the allowlist, to a metadata address, the host's loopback, or a host Unix socket, by the proxy or not.

Positive controls must succeed, so a sandbox that blocks everything cannot pass: commit in the slot, objects only in
the run's directory, and in a tool's cache repository; keep the role's cache; read the operator's logins and hand back
a refreshed token; read the checkout as a review; record a decision as the overseer; reach an allowed host; use the
system temp directory; receive any prompt byte for byte; die at a timeout, leaving no process.

### Open

- Bazel's caches: a sandboxed run may not write them, so it builds cold until it has caches of its own.
- Credential scoping: a GitHub token limited to the pool's repositories closes most of the network residual.
