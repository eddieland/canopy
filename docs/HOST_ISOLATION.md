# Host isolation for agent runs

Status: proposal, not normative, adopted as ROADMAP M26 (2026-10-12). `TRUST_MODEL.md` wins where the two disagree.
Adopting any of this takes a ROADMAP milestone, a `DECISIONS.md` entry, and changes to TRUST_MODEL T4 and T6 with
explicit human approval. §5 items 1 and 2, which hold with or without a sandbox, are built (DESIGN §8, D107, D108), and
so is the half of item 5 that does (D109). The claims about `srt` below were checked against its source at version
0.0.79 (2026-10-09); re-check them against the version the operator pins.

This document covers how to keep a worker (and a chore) from reaching the rest of the operator's machine. It recommends
an OS-level sandbox wrapped around `worker_cmd`, lists the small harness changes that sandbox needs to be worth
anything, and says how to prove it holds.

## 1. Problem

A worker runs as the operator, reads text other people wrote, and is assumed to follow injected instructions some of
the time (TRUST_MODEL §3). Its only limits today are OpenCode permissions, which are defense in depth (T4, D021). The
shipped `canopy-worker` definition allows `bash: "*"`, and `external_directory: deny` covers OpenCode's edit tool, not
what a shell command touches. So a steered worker can, today:

- Read `~/.ssh`, `~/.aws`, `~/.netrc`, `~/.docker/config.json`, browser profiles, and every other repository on disk.
- Rewrite `~/.config/canopy/config.toml`: change `worker_cmd`, add itself to `trust.authorized_repliers`, raise
  capacity. T7 keeps those keys out of shared files, but nothing keeps a worker out of the user config.
- Write to the journal under the workspace's `.canopy/`, which is the audit log (T5).
- Plant a hook or `core.fsmonitor` in the pool's shared git directory. Later `git` calls run it on the host outside
  any worker: in `_run`, in the next run on that pool, or in the operator's own checkout if it shares that directory.
- Append to `~/.bashrc`, drop binaries in `~/.local/bin`, or install a launch agent.
- Send anything anywhere over the network (T6).

Each of these is the same exposure as an interactive agent, minus the human glance. The ROADMAP's trigger for fixing it
is "a T4 or T6 incident, or before any second team adopts it." This document is the plan for when that happens.

## 2. Goals and non-goals

Goals:

- A worker can write only to its worktrees, its runtime's own state, and a temp directory.
- A worker cannot read the operator's secrets or canopy's config and state.
- Network egress is limited to an allowlist the operator writes.
- No change to canopy's shape: the sandbox is a prefix on the command template, as TRUST_MODEL T4 and D023 already
  plan. The harness stays ignorant of which sandbox is used.
- Works on Linux and macOS, with one install step for the operator.
- A deterministic canary proves each property, with no model in the loop.

Non-goals:

- Containing a kernel exploit or code written specifically to break out. The threat is a steered agent using ordinary
  tools, not a targeted attacker with a local privilege escalation.
- Hiding from the worker the credentials it legitimately needs (the model API key, the MCP tokens, git push). Scoping
  those is a separate step (§8).
- Sandboxing the overseer (§4.4).
- Remote or multi-machine workers.

## 3. Options

| Option | Boundary | Linux | macOS | Image to maintain | Worktree access | Egress control |
| --- | --- | --- | --- | --- | --- | --- |
| OS sandbox (bubblewrap, Seatbelt) | shared kernel | yes | yes | no | direct | proxy allowlist |
| Rootless container (Podman, gVisor) | namespaces, user-space kernel | yes | via a VM | yes | bind mount | netns |
| MicroVM with virtiofs (Kata, libkrun, Apple `container`) | hypervisor | KVM | some | yes | virtiofs | host firewall |
| Firecracker | hypervisor | KVM | no | yes | no shared FS | host firewall |

Recommendation: the OS sandbox. It needs no image, reads the worktree in place, runs on both platforms, and covers
every item in §1. The shared kernel is the one real gap, and a steered agent using ordinary tools does not reach it.

Firecracker specifically does not fit. It needs KVM, so it excludes macOS operators and many cloud dev VMs. It has no
shared filesystem by design, so the worktree and its git directory would have to be copied in and out, which conflicts
with treehouse leasing and the push check in `_run`. Its guest image would have to carry OpenCode plus every toolchain
the repository builds with. If canopy ever needs a hypervisor boundary, a microVM with virtiofs is the better path, and
the plug point in §4 is the same.

## 4. Proposal

### 4.1 The prefix

The operator sets, in the user config only:

```toml
[runtime]
# A multi-line literal string: the template is split into words, so the line break is only a space.
worker_cmd = '''canopy-sandbox worker env OPENCODE_CONFIG_DIR={definitions_dir}
    opencode run --agent canopy-worker --format json {prompt}'''
```

`canopy-sandbox` is a short script the operator installs (canopy would ship it as an example, not as harness code). It
runs in the worker's cwd, which `_run` sets to the slot or the desk (DESIGN §8, §18), and:

1. Resolves the paths the policy needs: the cwd, each worktree a desk links to, and each worktree's git common directory
   (`git rev-parse --git-common-dir`).
2. Writes a per-run policy from a template in `~/.config/canopy/sandbox/`, filling in those paths.
3. Drops from the environment what the inner `bash -c` would act on, `BASH_ENV` first. `srt` passes the caller's
   environment through and adds its own: `TMPDIR`, the proxy variables, `GIT_SSH_COMMAND`, `GIT_CONFIG_PARAMETERS`.
4. `exec`s the sandbox with that policy and the rest of its arguments unchanged, after a `--`:
   `srt --settings <policy> -- "$@"`. Without it, `srt` reads its own options (`-c`, `-s`, `-d`, combined short forms
   too) anywhere in its arguments, and `-c` takes its value as a shell command, unquoted.

The sandbox recommended here is Anthropic's `sandbox-runtime` (`srt`, Apache-2.0). It wraps any command using
bubblewrap on Linux and `sandbox-exec` on macOS, and routes all network traffic through a local proxy that enforces a
domain allowlist. It is a beta research preview, so the operator pins a version. A hand-written bubblewrap or Seatbelt
profile behind the same script is the fallback if `srt` changes under us; the harness would not notice the swap.

Because `worker_cmd` is a user-only key (TRUST_MODEL T7), a repository cannot remove the prefix. Because the sandbox
denies writes to `~/.config/canopy` (§4.2), a worker cannot remove it either.

### 4.2 Filesystem policy

Reads are denied under the home directory and re-allowed where needed. Writes are denied everywhere and allowed where
needed. A deny list of known secret paths was considered and rejected: it always misses one. `srt`'s policy takes this
shape: its `allowRead` outranks `denyRead`, so a denied `$HOME` can re-allow directories under it (a denied file is
re-allowed only by naming that file).

| Path | Read | Write | Why |
| --- | --- | --- | --- |
| The cwd and every worktree a desk links to | yes | yes | The work. |
| Each worktree's `.git` link file | yes | no | Repointing it moves host-side git somewhere the worker owns (§5). |
| The git common dir, except this slot's `worktrees/<slot>/` | yes | no | Shared by every slot; see below. |
| This slot's `worktrees/<slot>/`, except `config.worktree` | yes | yes | Its own HEAD, index, and reflog. |
| A per-run git object directory | yes | yes | New commits; see below. |
| The runtime's config (`~/.config/opencode`) | yes | no | A worker must not rewrite its own permissions. |
| The runtime's data and cache (`~/.local/share/opencode`, ...) | yes | yes | Sessions and token refresh. |
| Toolchains the build needs (`~/.local/bin`, `~/.cargo`, `~/.nvm`, ...) | yes | no | Running tests. |
| Build and package caches | yes | yes | Separate from the operator's own caches (§7). |
| A per-run temp directory, exported as `TMPDIR` | yes | yes | Scratch space. |
| A chore's own `cwd` (default `<state_dir>/chores/<name>/`) | yes | only if it writes | Chores only (below). |
| The rest of `~/.config/canopy` and the workspace's `.canopy/` | no | no | Config and journal belong to the harness. |
| The rest of `$HOME` | no | no | Secrets, other repositories. |

The run log is unaffected: the worker's stdout and stderr are file descriptors `_run` opened before the sandbox
started.

Git state is where the worktree boundary leaks. Every slot in a pool shares one common directory: refs, objects, hooks,
config, and every other slot's metadata. Path rules cannot give a worker write access to its own branch alone, because
git updates a ref through a lock file beside it and rewrites a shared `packed-refs`. A worker that can write refs can
move another running worker's branch, which that worker then builds on and pushes as its own. So a worker writes no
shared git state:

- Built (D109): `_run` checks the branch out detached (`git checkout --detach`, from `origin/<branch>` or the base).
  A detached worktree keeps HEAD, the index, and the reflog in `worktrees/<slot>/`, which belongs to that slot alone.
- Built (D109): the worker pushes with `git push origin HEAD:refs/heads/<branch>`, and step 5's verification compares
  the remote branch with HEAD.
- Built (D111), but used only by the wrapper (§4.1): new objects go to a per-run directory, with the shared object
  directory as an alternate (below).

Checked with bubblewrap and git 2.43, a worktree slot under exactly this policy (the git common directory read-only,
`worktrees/<slot>/` writable except `config.worktree`, the `.git` link read-only, and a per-run object directory
writable through `GIT_OBJECT_DIRECTORY` and `GIT_ALTERNATE_OBJECT_DIRECTORIES`): a commit on the detached HEAD, a merge
of `origin/<base>`, and the push by refspec all work, and the push leaves the shared remote-tracking refs alone. Moving
any ref, making a branch, writing the common `config`, a hook, `config.worktree`, or the `.git` link all fail, and so
does every plain `git fetch`, since the configured refspec updates a remote-tracking ref.

The per-run object directory needs two things the first draft of this section missed:

- It cannot simply go away with the run. The slot's HEAD, index, refs, and reflog then name objects nobody has:
  `git status` in the slot fails (`bad object HEAD`), and so does `git gc` in the primary clone, the operator's own
  repository. So before deleting it, the slot is tidied (DESIGN §8 step 6): checked out detached at `origin/<base>`,
  which step 2 fetched into the shared directory and a sandboxed worker cannot move, with `--force`, which also ends a
  merge left in progress; its own refs (`refs/worktree/*`, `refs/bisect/*`, `refs/rewritten/*`), `ORIG_HEAD`, and
  `FETCH_HEAD` deleted; and its HEAD reflog expired, never the shared branches'. Checked with bubblewrap and git 2.43
  against a worker that committed, abandoned a commit, fetched into `FETCH_HEAD`, left a conflicted merge, and made a
  `refs/worktree/` ref: without the own refs deleted, `for-each-ref`, `fsck`, and `gc` in the slot still fail; with
  them, `status`, `fsck`, and `gc` are clean in the slot and the primary clone. Step 5 runs before this, with git
  reading the directory too, so it can see and push the worker's commits; and since a host-side push also moves origin's
  remote-tracking ref in the shared directory, which the worker's own push could not, step 5 puts that ref back as it
  was, or every slot would name the deleted commit. Cleanup runs on every exit path, like D108's, and for a run killed
  with SIGKILL reconcile does it, from the `.git` link `_run` recorded in `run_slots`, so the directory lives where
  reconcile finds it from the run, `<state_dir>/runs/<id>.objects/`, which the policy re-allows as it does a chore's
  `cwd`.
- The variables reach every git the worker's process tree runs, not only git in the slot. A commit in any other
  repository lands in the per-run directory, so that repository reads `bad object HEAD` once it is gone, and a
  repository made with `git init` then `git fetch` (how Go fetches modules into its cache) gets no `objects/` at all.
  `git clone` is unaffected. So `_run` must not set them for an unsandboxed worker, whose tools write the operator's
  real caches. `_run` passes the directory as `CANOPY_GIT_OBJECTS`, and the wrapper (§4.1), which knows it is
  sandboxing, turns it into `GIT_OBJECT_DIRECTORY` and lists each slot's shared object directory, colon-separated, in
  `GIT_ALTERNATE_OBJECT_DIRECTORIES`. Inside the sandbox the worker can write only its temp directory and the sandbox's
  own caches, so the leak reaches those; a cache a tool builds with `git init` and `git fetch` breaks after the run.
  Giving such tools a per-run cache, or keeping them out of sandboxed builds, is open (§7).

A chore gets the same policy. Its default `cwd` is inside the workspace's `.canopy/`, so its policy re-allows that one
directory: read-only by default, since a chore's only output is its result line (D034), and writable for a chore whose
own tooling writes there. The rest of `.canopy/` stays denied.

### 4.3 Network policy

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

The residual is exfiltration through an allowed host. With `github.com` allowed and the operator's token in reach, a
worker can still push to any repository or post anywhere the operator can. That is §8's step.

### 4.4 What is wrapped

- `worker_cmd`: yes.
- `runtime.setup_cmd`: yes. It runs the branch's code in the slot just before the worker (DESIGN §9).
- Chore `cmd`: yes.
- `overseer_cmd`: no. The overseer acts through the `canopy` CLI, which needs the journal, the lock, and the user
  config, so its sandbox would have to allow exactly what §4.2 denies. It has no edit or write tools, and its bash is
  limited to `canopy *` and `treehouse status*` (DESIGN §13). Revisit if that changes.
- `notify.cmd`, `git`, and `treehouse`: no. They are the harness's own calls, and §5 covers the ones that touch what a
  worker left behind.

## 5. Harness changes

The prefix alone moves the problem to the boundary. After the worker exits, `_run` runs git on the host in the slot
the worker just had (`ls-remote`, and `push` if needed), and the next run fetches and checks out in it. That is code
running outside the sandbox on files a worker wrote. Five changes, in the same milestone as the sandbox:

1. Built (D107). Every git the harness runs, in a slot or anywhere else, runs with hooks, filesystem monitors,
   submodule fetches, and the `ext::` transport off: `-c core.hooksPath=/dev/null -c core.fsmonitor=false
   -c fetch.recurseSubmodules=false -c protocol.ext.allow=never`. Checked with git 2.43 on a worktree pool: without
   them, `_run`'s own steps run `post-checkout`, `reference-transaction` (on every ref a `fetch` updates),
   `post-index-change`, and `pre-push` from the shared git directory, and the monitor on every index read; with them,
   none. They do not stop a command the shared config names: a filter driver (with a committed `.gitattributes`) runs
   on checkout, and `remote.<name>.uploadpack` on fetch over a local or SSH remote. Until a worker cannot write that
   config (§4.2), those stay open.
2. Built (D108). `_run` reads each slot's `.git` file before any git step. If it changed by the time the worker exits,
   the run is `crashed` (an attention item) and no git runs in any of its slots. The file is put back before the slot
   is returned, since treehouse runs git there. The policy already denies writing it; this catches a policy that
   forgot. Gap: a `_run` killed with SIGKILL leaves the slot to reconcile, which does not know what the file held.
3. The prompt reaches the runtime byte for byte. D023 keeps ticket text out of a shell. `srt` joins its arguments into
   one `bash -c` string after single-quoting each one, and quotes again at each layer it adds (`sh -c` around
   bubblewrap on Linux, `env ... sandbox-exec` on macOS). That is the POSIX-safe form, but it is a second parser on
   ticket-written text. The inner bash is neither a login nor an interactive shell, so it reads no rc file, but it
   does source `$BASH_ENV` (§4.1 step 3). The canary (§6) proves prompts come through unchanged with a hypothesis
   property test over quotes, newlines, `$()`, backticks, and arbitrary Unicode text (D027); the harness's half, that
   the prompt is exactly one argument of the template, is `test_properties.py`. `_run` reads the prompt as UTF-8, so
   bytes that are not valid UTF-8 never reach the command line. On Linux the whole quoted command is one argument to
   `sh`, so it must fit in one argument's limit (128 KiB); `srt` refuses a longer one. If either is a problem, D023's
   own revisit clause applies: add a `{prompt_file}` placeholder and pass the path of the prompt `_run` already writes.
4. Timeouts still end everything. `_run` kills the worker's process group with SIGKILL; `test_procs.py` checks that a
   descendant in the group dies with it. `srt` starts nothing detached: it, its shell, bubblewrap, and its proxies
   (which run inside `srt`) stay in that group. bubblewrap gets `--new-session`, so the sandboxed processes are in a
   group of their own, but also `--die-with-parent` and a PID namespace, so they die with bubblewrap. A kill of the
   `srt` pid alone would not reach them; `kill_group` is the right call. On macOS nothing starts a new group, so a
   process that calls `setsid` escapes, as it would without a sandbox. The canary checks that nothing inside the
   sandbox outlives a timeout. canopy reads the result line, not the exit status, so `srt` exiting 0 when its child
   dies of SIGTERM does not matter: a timeout is canopy's own clock.
5. Worker git state is private (§4.2). Built (D109): a detached checkout in step 2 and a push by refspec, in `_run`
   and the worker prompts; a resume merges `origin/<base>` instead of fetching. Built (D111): the per-run object
   directory, passed as `CANOPY_GIT_OBJECTS`, read by step 5, and tidied away on every exit path and by reconcile, as
   §4.2 describes. Nothing sets git's variables from it until the wrapper does.

No new config keys. `canopy init` can print a suggested `worker_cmd` and the one install command, but does not write
them. The sandbox stays opt-in until the canary has passed on real machines.

## 6. The canary

D021 needed a model to test OpenCode permissions. This does not: the sandbox is the boundary, so a plain script run
through the real `worker_cmd` prefix is the test. An opt-in live test (`CANOPY_SANDBOX_CANARY=1`) sets up a HOME in a
temp directory with a fake `~/.ssh/id_ed25519`, a user config, and a state directory, leases a fake slot backed by a
real git worktree, and runs a script that tries each of these. Every attempt must fail:

- Read the fake SSH key, and anything else under HOME outside the policy.
- Write `~/canary`, `~/.bashrc`, `~/.config/canopy/config.toml`, and anything under the state dir.
- Move another slot's branch or any other ref, write the common dir's `config` or `hooks/post-checkout`, a
  `config.worktree`, or the slot's `.git` link.
- Connect to a host not on the allowlist, to `169.254.169.254`, and to a port on the host's loopback.

And the positive controls must succeed, so a sandbox that blocks everything cannot pass:

- Write and commit in the slot, and reach an allowed host.
- Receive a hypothesis-generated prompt byte for byte (§5.3).
- Be killed at a short timeout, leaving no process behind.

On Linux this can also run in CI, since it needs only bubblewrap and unprivileged user namespaces. Ubuntu 24.04 and
later restrict those by default (`kernel.apparmor_restrict_unprivileged_userns`), which the operator docs must say.

## 7. Open questions

- Fetching inside a run: answered. The worker cannot update shared remote-tracking refs, so every plain `git fetch`
  fails. `_run` fetches just before the worker starts, and the only prompt that fetched (resume, for a PR that
  conflicts with its base) now merges `origin/<base>` instead. A fetch that writes only `FETCH_HEAD`, which is per
  worktree, works under the policy (`git fetch --refmap= origin <ref>`), for a worker that needs something newer.
- Tools that keep git repositories in a cache (Go's module cache, pre-commit) under the per-run object directory
  (§4.2).
- Git push credentials. HTTPS with a credential helper works through the proxy. SSH does not work out of the box on
  Linux: `srt`'s seccomp filter blocks creating Unix sockets, which includes the agent socket. Its per-path
  `allowUnixSockets` is macOS-only; on Linux the only switch is `allowAllUnixSockets`, which lifts the block entirely.
  canopy already recommends HTTPS remotes and `canopy workspace sync` warns about SSH ones (D038). Still open: whether
  to support SSH inside the sandbox at all (allow the agent socket, or push from the host in `_run`), or to leave SSH
  to unsandboxed runs.
- OpenCode's local MCP servers start inside the sandbox and inherit it. Each one's hosts must be on the allowlist, and
  stdio servers that read credentials from HOME need those paths allowed.
- Build caches. DESIGN §9 wants caches shared across slots. Sharing them with the operator's own builds would let a
  worker poison what the operator runs later. Give sandboxed runs their own cache directories.
- treehouse runs git on returned slots (`return --force`) and runs `post_create` hooks. Check whether it runs anything
  from the slot, and what it should turn off, before calling §5 complete.
- The repository's OpenCode config (skills, MCP servers, plugins) comes from the checked-out branch (T7 residual).
  canopy's own agent definitions no longer do (D040, D044). The sandbox does not change that, but it does bound what a
  hostile config can reach.
- `sandbox-exec` is marked deprecated on macOS, though the Seatbelt framework it drives is what Chrome and several
  agent runtimes still use. Apple's `container` (a lightweight VM per container) is the macOS fallback if it goes away.
- A policy with no restrictions at all makes `srt` run the command without bubblewrap. The canary's denials catch a
  template that ends up empty.
- Where this sits in the ROADMAP: the trigger says before a second team adopts canopy. It needs M2's real worker to be
  worth testing against.

## 8. Later

- Credential scoping. A fine-grained GitHub token limited to the pool's repositories closes most of §4.3's residual.
  `srt` also has an experimental mode that gives the sandbox a placeholder credential and substitutes the real one
  only on requests to named hosts. Evaluate it once the first phase is in use.
- A hypervisor boundary, if canopy ever runs workers off the operator's machine. Same prefix, different script.
