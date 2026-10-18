# Sandboxed runs

Part of the canopy design, normative like all of it: the OS sandbox an operator can put around every agent run but the
overseer's. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Flaky
CI](FLAKY_CI.md). Next: [Plans](PLANNING.md).

## 24. Sandboxed runs (M26)

Opt-in, and not yet proven on the operator's machines (ROADMAP M26). A worker runs as the operator, reads text other
people wrote, and is assumed to follow injected instructions some of the time (TRUST_MODEL §3). Without a sandbox its
limits are OpenCode permissions, which are defense in depth (T4, D021), and its shell reaches the whole machine:
`~/.ssh`, the user config, the journal, the pool's shared git directory, and any host. The sandbox bounds that for each
run it wraps.

It is a prefix on the command templates, nothing more (D118). The harness never learns whether a run is sandboxed: it
passes every run `CANOPY_GIT_OBJECTS`, which an unsandboxed run ignores, and runs on the host only what reads nothing a
sandboxed run can write. What it defends and what it leaves open are TRUST_MODEL T4 and T6. The problem, goals, and
options weighed are [HOST_ISOLATION](../HOST_ISOLATION.md) §1 to §3; the operator's guide is
[SANDBOX.md](../SANDBOX.md). The claims below about `srt` were checked against its source at version 0.0.79; re-check
them when the pinned version changes.

The sandbox is Anthropic's `sandbox-runtime` (`srt`, Apache-2.0): bubblewrap on Linux, `sandbox-exec` on macOS, and
all network traffic through a local proxy that enforces a domain allowlist. It needs no image, reads the worktree in
place, and runs on both platforms; the shared kernel is the gap, and a steered agent using ordinary tools does not
reach it. Rejected for now (HOST_ISOLATION §3): a container or a microVM, since each needs an image carrying every
toolchain, and Firecracker has no shared filesystem, which treehouse's leases and `_run`'s push check need. `srt` is a
beta, so canopy pins its version (D117). A hand-written bubblewrap or Seatbelt profile behind the same wrapper is the
fallback if `srt` changes under us; the harness would not notice the swap.

### The wrapper

The operator sets, in the user file or the workspace's private file (§12), never the workspace file:

```toml
[runtime]
# A multi-line literal string: the template is split into words, so the line break is only a space.
worker_cmd = '''canopy-sandbox worker --read {definitions_dir} -- env OPENCODE_CONFIG_DIR={definitions_dir}
    opencode run --agent canopy-worker --format json {prompt}'''
```

`canopy-sandbox` is a short program canopy installs beside itself, not harness code (D041, D117). Its first argument is
a role, `worker`, `setup`, `chore`, or `review`, which picks the policy template `~/.config/canopy/sandbox/<role>.json`;
`--read` names a path the command may read, which is how canopy's agent definitions are re-allowed: pass it
`{definitions_dir}`. Name the wrapper by its absolute path when `PATH` has a relative entry: canopy runs the template
from the slot, where `.` finds what the branch committed. It runs in the run's cwd, the slot or the desk (§8, §18),
and:

1. Drops from its environment, and so from the command's, what would point git at another repository (`GIT_DIR` and its
   kind), every relative `PATH` entry, so nothing is found through the checkout, and `BASH_ENV` and `ENV`, which the
   inner `bash -c` would act on.
2. Resolves the paths the policy needs: the cwd, each worktree a desk or a review's directory links to, and each
   worktree's own and common git directories. A worker or setup outside a linked worktree is refused, since a clone's
   HEAD and index live in the directory every slot shares, and so is a desk or a review's directory with a `.git`,
   which a branch could commit.
3. Writes a per-run policy from the template into a directory private to the operator, with the run's temp directory
   beside it. It adds to `denyRead` the directory holding every run's, since the system temp directory is outside
   `$HOME`, and the workspace's `.canopy/` when the run's directories name it, for a workspace outside `$HOME`. It
   refuses a template with no `denyRead` or no network allowlist: `srt` runs a command whose policy restricts nothing
   without bubblewrap at all.
4. Sets the command's `TMPDIR`, and `srt`'s, to the run's temp directory: `srt` otherwise uses `/tmp/claude`, shared by
   every sandboxed process. On Linux it refuses a system temp directory too long to hold `srt`'s network sockets
   (macOS's deep per-user one is not too long). It points the command's caches and OpenCode's data at the role's own,
   copies the operator's OpenCode logins in (Caches and Logins, below), and for a worker or setup puts a `git` of its
   own first on the command's `PATH` (Git state, below).
5. Runs `srt --settings <policy> -- "$@"`: after a `--`, since `srt` reads its own options anywhere in its arguments,
   and `-c` takes a shell command. It waits for `srt` and then removes its directory; a run killed with SIGKILL leaves
   one that a later run removes. It re-allows reading `srt`'s `vendor/`, whose seccomp helper runs inside the sandbox.
   Then it copies back each login token the run refreshed (Logins, below).

Because `worker_cmd` is a private key (TRUST_MODEL T7), a repository cannot remove the prefix. Because the sandbox
denies writes to `~/.config/canopy`, a worker cannot remove it either.

### What is wrapped

| Command | Role | Why |
| --- | --- | --- |
| `worker_cmd`, `private_worker_cmd`, `split_cmd`, `plan_cmd` | `worker` | The work. |
| `runtime.setup_cmd` | `setup` | It runs the branch's code in the slot just before the worker (§9). |
| `runtime.chore_cmd`, a chore's `cmd` | `chore` | A chore using the operator's own tools has a shell for them (§19). |
| `review_cmd` | `review` | It reads the most hostile text the loop meets, a diff by anyone `review.query` matches (T1). |
| `overseer_cmd` | none | It acts through `canopy`, which needs the journal, the lock, and the operator's config. |
| `notify.cmd`, `git`, `treehouse` | none | The harness's own calls; what they read of a run is below. |

The overseer's sandbox would have to allow exactly what the policy denies. It has no edit or write tools, and its bash
is limited to `canopy *` and `treehouse status*` (§13); revisit if that changes. A review gets a role of its own: the
worker's policy would let it write the checkout and commit, and a chore's would not find the checkout.

### Filesystem policy

Reads are denied under the home directory and re-allowed where needed. Writes are denied everywhere and allowed where
needed. A deny list of known secret paths was rejected: it always misses one. In `srt`, `allowRead` outranks
`denyRead`, so a denied `$HOME` can re-allow directories under it (a denied file only by naming that file). The shipped
templates deny `$HOME`. For a workspace outside it, the wrapper denies `.canopy/` where it can find it (step 3); a chore
with a `cwd` of its own names no `.canopy/`, so the operator adds the workspace to its template's `denyRead`.

| Path | Read | Write | Why |
| --- | --- | --- | --- |
| The cwd and every worktree a desk links to | yes | yes | The work. |
| Each worktree's `.git` link file | yes | no | Repointing it moves host-side git somewhere the worker owns. |
| The git common dir, except this slot's `worktrees/<slot>/` | yes | no | Shared by every slot (Git state, below). |
| This slot's `worktrees/<slot>/`, except `config.worktree`, `commondir`, `gitdir` | yes | yes | Its own HEAD, index, and reflog. |
| The run's object directory, `<state_dir>/runs/<id>.objects/` | yes | yes | New commits (§8). |
| The runtime's config (`~/.config/opencode`) | yes | no | A worker must not rewrite its own permissions. |
| The runtime's state (`~/.local/state/opencode`) | yes | yes | Not code the host runs (Logins, below). |
| The role's data directory, `~/.local/share/canopy/sandbox/<role>/` | yes | yes | The runtime's data, with a copy of the logins (below). |
| The operator's runtime data (`~/.local/share/opencode`) | no | no | The host's OpenCode acts on it (Logins, below). |
| Toolchains the build needs (`~/.local/bin`, `~/.cargo`, `~/.nvm`, ...) | yes | no | Running tests. |
| The role's cache directory, `~/.cache/canopy/sandbox/<role>/` | yes | yes | Every cache, the runtime's too (below). |
| The operator's own caches (`~/.cache`, `~/.npm`, ...) | no | no | The host runs what is in them. |
| A per-run temp directory, exported as `TMPDIR` | yes | yes | Scratch space. |
| A chore's own `cwd` (default `<state_dir>/chores/<name>/`) | yes | only if it writes | Chores only (below). |
| A review's directory (`<state_dir>/reviews/<id>/`) | yes | no | Reviews only (below). |
| canopy's agent definitions (`<state_dir>/runtime/<digest>/`) | yes | no | The agent's own definition (D040). |
| The rest of `~/.config/canopy` and the workspace's `.canopy/` | no | no | Config and journal belong to the harness. |
| The rest of `$HOME` | no | no | Secrets, other repositories. |

A refused write under a denied directory may look as if it worked: `srt` hides a denied directory under an empty,
writable `tmpfs`, and what is written there is gone when the run ends, without reaching the host. So the canary checks
writes on the host.

A chore's default `cwd` is inside `.canopy/`, so its policy re-allows that one directory: read-only by default, since a
chore's only output is its result line, and writable for a chore whose own tooling writes there. The rest of `.canopy/`
stays denied, the journal with it, so `canopy chore history` (§19) fails in a sandboxed chore.

A review starts in its directory, which the policy re-allows reading, and reads the checkout through the link there: the
checkout and its git directories are readable and none of them writable, since the reviewer writes nothing (§21) and
what it reads was written by the PR's author. It gets no object directory and no wrapper `git`. Its network allowlist
leaves out `github.com`, since it neither fetches nor pushes.

### Caches

A cache is code the host runs later. OpenCode imports the providers and plugins it installs, and runs `rg`, LSP
servers, and formatters, from `~/.cache/opencode/` (OpenCode 1.19.0). The overseer is OpenCode too, outside any
sandbox, under the same HOME, so a run that can write that directory runs code on the host at the next tick. The
operator's own caches are the same: npm, uv, Go, and pip install from them, and Bazel's disk cache hands builds their
outputs.

So no run writes the operator's caches. Each role has a cache directory of its own,
`$XDG_CACHE_HOME/canopy/sandbox/<role>/`, private to the operator, which the templates allow reading and writing as
`@CACHE@`. Setup shares the worker's, since warming the worker's caches is its job (§9). The wrapper points the
command's `XDG_CACHE_HOME` there, and the caches of npm, Go, and pip, which do not all follow it, under it, whatever the
operator set them to. It denies reading the directory that holds every role's, so a review cannot read the worker's,
nor a worker the review's. What a review leaves in its cache reaches only later reviews, which write nothing in a
checkout and reach no `github.com`. Rejected: a cache per run, which would fetch every package and binary on every run;
and one cache for every role, which would hand what a review left to a worker.

What a role's runs share is theirs to poison for one another, as `/tmp/claude` is (Trust model changes, below): a
private ticket's worker and a public one share the worker's. Bazel's caches are the operator's own builds' too, and
nothing yet gives the sandbox Bazel caches of its own (Open, below). `canopy sandbox setup` says when a template it kept
still allows writing in the operator's cache directory.

### Logins

OpenCode's data directory is code the host runs too. In OpenCode 1.19.3, a run that writes `~/.local/share/opencode`
can make the overseer's OpenCode, or the operator's, run code outside the sandbox at its next start: through
`auth.json` (a `wellknown` login names a URL whose config OpenCode merges, with its plugins and local MCP servers),
`opencode.db` (the console account's remote config, the same way), or a snapshot git directory there, whose planted
config (`core.fsmonitor`, say) runs on OpenCode's `git add`; that last reaches the overseer only when the workspace is
inside a git repository. Its state directory, `~/.local/state/opencode`, is not a way out, and stays writable.

So a run's OpenCode keeps its data in a directory of its role's own, `$XDG_DATA_HOME/canopy/sandbox/<role>/`, private
and shared by the role's runs as the cache directory is, which the templates allow as `@DATA@`. The wrapper points the
command's `XDG_DATA_HOME` there, keeps uv's Pythons and tools where the operator keeps them, since the templates let a
run read those, and denies writing the operator's OpenCode data directory whatever the template says, so a template
from before `@DATA@` cannot write it either. canopy reads a run's transcript from the run's log, never from OpenCode's
data, so the sessions there are the role's alone.

The logins are the one part of that data a run needs: each provider's in `auth.json`, and each remote MCP server's
OAuth tokens in `mcp-auth.json`. The operator settled (2026-10-18) that they log in once, as without a sandbox, so the
wrapper shares them:

- Just before the command starts, it copies the operator's two files into the role's directory, whole, over what an
  earlier run left there; a file the operator has none of is removed.
- When the command ends, it copies into the operator's files only what an OAuth refresh changes: of a login the
  operator has, OAuth in both, the run's tokens and expiry, when that expiry is later; of an MCP server's, its
  `tokens`, when its server URL is the same. It never adds a login, never takes a `wellknown` or API-key one, and
  never takes a field that says where a token goes or whose account it is (`enterpriseUrl`, `accountId`, `serverUrl`,
  `clientInfo`). Without this step, a provider that rotates refresh tokens would log the operator out the first time a
  run refreshed one.
- A run canopy kills at its timeout copies nothing back; the role's next run does, before it copies the logins in.
- What a run left is read on the host without following a link or blocking on a fifo, and only up to 1 MiB. An entry
  that is not the shape OpenCode writes is left where it is: OpenCode drops a login it cannot decode, and the whole of
  `mcp-auth.json` for one bad entry.

Rejected: a second login for the sandbox, which the operator, with many credentials, did not want; logins in
environment variables, which leave OAuth logins out; and copying in without copying back, which logs the operator out
at a rotated refresh token. What remains is that a run can hand back, as a refresh, a token of another account at the
same provider, or a bad one (Trust model changes, below). `canopy sandbox setup` says when a template it kept names
the operator's OpenCode data, or leaves out `@DATA@`.

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
  `FETCH_HEAD`, which is per worktree, works (`git fetch --refmap= origin <ref>`).

`srt` cannot express "the common directory, except `worktrees/<slot>/`" as one read rule, so the policy names the
common directory's entries one by one; what it gains after the run starts, such as a first `packed-refs`, is not
visible inside the sandbox. `config.worktree`, `commondir`, and `gitdir`, in the slot's own directory, are denied
writing, renaming over, and removing, as the `.git` link is; `config.worktree` even before it exists. A `commondir`
rewritten to a directory the worker made, with a `config`, `objects/`, and `refs/`, would make every git on the host in
the slot read that config and its hooks: `_run`'s step 5, the tidy step, and treehouse's `return`; a
`remote.origin.uploadpack` there ran on `_run`'s `ls-remote` despite D107's flags. `gitdir` is the back link
`git worktree prune` acts on. git writes none of them in a slot's ordinary work.

git's object variables (`GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`) apply to every repository. Set
for a whole process tree, they send the objects of every repository a tool keeps as a cache (Go's module sources,
OpenCode's snapshots) to the run's directory, lost with it; that was tried and rejected. So `_run` passes the directory
only as `CANOPY_GIT_OBJECTS` (§8), and the wrapper's own `git`, first on the command's `PATH` and not writable by the
run, sets the variables only when git would act on one of the run's worktrees, never for `init` or `clone`, and drops
them elsewhere. A git run by its absolute path gets none, and so cannot write objects in a slot at all: it fails rather
than writing where it should not.

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

A local MCP server is a child of OpenCode, started in the slot with its environment, so it runs under the run's policy,
`TMPDIR`, proxy, and `git`. What it writes outside `allowWrite` is gone after the run, so one started with `npx` or
`uvx` fetches itself each run, from a registry that must be allowed. One started with `docker run` cannot work: the
Docker daemon is a Unix socket, which the sandbox refuses, and which would be a way out if it did not; run such a server
as a binary, or use its remote form, whose host must be allowed. OpenCode keeps MCP OAuth tokens in its data directory,
so a run starts with a copy of the operator's (Logins, above). None of this needs a role or a template of its own.

### What the harness runs around a sandboxed run

The prefix alone moves the problem to the boundary: after the worker exits, `_run` runs git on the host in the slot the
worker just had, and treehouse runs git there when the slot is returned. That is code running outside the sandbox on
files a worker wrote. These hold with or without a sandbox:

1. Every git the harness runs has hooks, filesystem monitors, submodule fetches, and the `ext::` transport off (§8,
   D107). They do not stop a command the shared config names, a filter driver or `remote.<name>.uploadpack`; under the
   sandbox, a worker cannot write that config.
2. `_run` reads each slot's `.git` link before any git step, and checks it and the slot's `commondir` when the
   worker exits; a changed one makes the run `crashed`, runs no git in any of its slots, and is put back before the
   slot is returned (§8 steps 2, 5, and 6). Reconcile does the same for a `_run` killed with SIGKILL (§15). The policy
   already denies writing both; this catches a template that forgot.
3. The run's object directory is tidied away on every exit path, the slots first, so that nothing in a slot or the
   primary clone names an object only that directory held (§8 step 6, §15).
4. `treehouse return --force`, after the tidy step, ends the processes working in the slot, then runs plain git there,
   without D107's flags and without the network, so a hook in the common directory, the filesystem monitor, and a
   filter driver the config names all run. A sandboxed worker writes none of those, nor `commondir`, which says where
   they are. A `.gitattributes` it leaves can select only a driver the operator's own config defines, such as Git
   LFS's, as any checkout of that branch would. treehouse's own hooks come only from the operator's user config, under
   the denied `$HOME`. A template that drops `@GIT_PROTECTED@` from `denyWrite` is caught by canopy's own `commondir`
   check before any git runs. So a new step in a slot keeps D107's flags and runs after that check (D118).

The prompt reaches the runtime byte for byte. D023 keeps ticket text out of a shell, but `srt` joins its arguments into
one `bash -c` string, quoted at each layer: the POSIX-safe form, but a second parser on ticket-written text. That bash
reads no rc file, and the wrapper drops the `$BASH_ENV` it would source. `_run` reads the prompt as UTF-8, so invalid
bytes never reach the command line. On Linux the quoted command must fit in one argument (128 KiB), or `srt` refuses
it. If either is a problem, D023's own revisit clause applies: a `{prompt_file}` placeholder naming the prompt file
`_run` already writes.

Timeouts still end everything. `_run` kills the worker's process group with SIGKILL, and `srt` starts nothing outside
it. On Linux the sandboxed processes are in a PID namespace that dies with bubblewrap, so a process started with
`setsid` inside the sandbox ends with it. On macOS a process that calls `setsid` escapes, as it would without a
sandbox. canopy reads the result line, not the exit status, and a timeout is canopy's own clock.

No config key turns the sandbox on. `canopy sandbox setup` installs the templates and the pinned `srt`, and checks
what needs root (§12, D117); `canopy init` prints a suggested `worker_cmd`. Neither writes the config.

### The canary

OpenCode's permissions needed a model to test (D021). The sandbox does not: it is the boundary, so a plain script run
through the real prefix is the test. The canary, opt-in, run by `make sandbox-canary` and in CI on Linux,
sets the machine up as docs/SANDBOX.md tells the operator to, and uses the shipped templates unchanged, with a primary
clone and two slots under a fake `$HOME`. An attempt that failed because nothing ran fails the test, and a write is
checked on the host, never by whether the attempt reported an error. Every attempt must fail:

- Read a fake SSH key, and anything else under `$HOME` outside the policy.
- Write under `$HOME`, `~/.config/canopy`, the operator's `~/.cache/opencode` or `~/.local/share/opencode` (the
  latter under a template from before `@DATA@` too), or the state directory; read the operator's OpenCode data; read
  or write another role's cache or data directory.
- Move another slot's branch or any other ref; write the common directory's config or hooks, a `config.worktree`, the
  slot's `commondir` or `gitdir`, or its `.git` link.
- Connect to a host off the allowlist, to a metadata address, to the host's loopback, or to a Unix socket the host
  listens on. Each is tried through `srt`'s proxy and around it, and must be refused the way that route refuses, so a
  certificate error, another proxy's 403, or a sandbox with no network passes nothing.

The attempts on `$HOME` and the state directory run as `setup`, `chore`, and `review` too, and a review must also fail
to write the checkout and its git directories.

The positive controls must succeed, so a sandbox that blocks everything cannot pass: commit in the slot, its objects
only in the run's directory; commit in a repository a tool keeps as a cache, its objects in its own; keep a cache for
the role's next run; read the operator's logins and hand back a refreshed token, as a worker, a chore, and a review;
read the checkout as a review; reach an allowed host; run under the system temp directory; receive
an arbitrary prompt byte for byte; and be killed at a timeout, leaving no process behind (on macOS, only the sandbox's
process group). Against a fake `srt` that sandboxes nothing, every case but the positive controls fails.

### Trust model changes

TRUST_MODEL T4 and T6 name the sandbox as an opt-in control (D118), with what it does not cover: the shared kernel, the
unwrapped overseer and harness calls, `/tmp/claude`, which every process `srt` sandboxes can write whatever the policy
says, so two runs can pass files through it, and exfiltration through an allowed host with the credentials a run holds.
A run can also hand back, as a refresh, a token of another account for a login the operator has, or a bad one: the
operator's OpenCode, the overseer's included, then works as that account, or fails until the operator logs in again.
It runs no code on the host. The tests with a fake `srt` check what is copied back; the canary checks the denials.
The rest of the system temp directory stays readable, as other system paths do: denying it breaks tools that write
there without reading `TMPDIR`.

### Open

- SSH pushes. `srt`'s per-path `allowUnixSockets` is macOS-only; on Linux the only switch is `allowAllUnixSockets`,
  which lifts the block entirely. Whether to support SSH inside the sandbox at all (allow the agent socket, or push
  from the host in `_run`), or leave it to unsandboxed runs, is undecided.
- Bazel's caches. §9 shares them across slots, and BAZEL.md through the operator's own `~/.bazelrc`, so its own
  builds share them too. A sandboxed run may not write them (Caches, above), so it builds cold, until a bazelrc that
  only sandboxed runs read points them under the cache directory.
- The repository's OpenCode config (skills, MCP servers, plugins) comes from the checked-out branch (T7 residual).
  canopy's own agent definitions do not (D040, D044). The sandbox does not change that, but it bounds what a hostile
  config can reach.
- `sandbox-exec` is marked deprecated on macOS, though the Seatbelt framework it drives is what Chrome and several agent
  runtimes still use. Apple's `container` (a lightweight VM per container) is the macOS fallback if it goes away.
- Credential scoping. A fine-grained GitHub token limited to the pool's repositories closes most of the network
  residual. `srt` also has an experimental mode that gives the sandbox a placeholder credential and substitutes the
  real one only on requests to named hosts; evaluate it once the sandbox is in use.
- A hypervisor boundary, if canopy ever runs workers off the operator's machine: a microVM with virtiofs behind the same
  prefix, a different wrapper.
- Making the sandbox the default, once the canary passes on the operator's machines and a day of sandboxed runs (D118).
