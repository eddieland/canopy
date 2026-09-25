# Host isolation for agent runs

Status: proposal, not normative. `TRUST_MODEL.md` wins where the two disagree. Adopting any of this takes a ROADMAP
milestone, a `DECISIONS.md` entry, and changes to TRUST_MODEL T4 and T6 with explicit human approval.

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
  capacity. T7 keeps those keys out of the repository, but nothing keeps a worker out of the user config.
- Write to the journal under `~/.canopy`, which is the audit log (T5).
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
    opencode run --agent canopy-worker {prompt}'''
```

`canopy-sandbox` is a short script the operator installs (canopy would ship it as an example, not as harness code). It
runs in the worker's cwd, which `_run` sets to the slot or the desk (DESIGN §8, §18), and:

1. Resolves the paths the policy needs: the cwd, each worktree a desk links to, and each worktree's git common directory
   (`git rev-parse --git-common-dir`).
2. Writes a per-run policy from a template in `~/.config/canopy/sandbox/`, filling in those paths.
3. `exec`s the sandbox with that policy and the rest of its arguments unchanged.

The sandbox recommended here is Anthropic's `sandbox-runtime` (`srt`, Apache-2.0). It wraps any command using
bubblewrap on Linux and `sandbox-exec` on macOS, and routes all network traffic through a local proxy that enforces a
domain allowlist. It is a beta research preview, so the operator pins a version. A hand-written bubblewrap or Seatbelt
profile behind the same script is the fallback if `srt` changes under us; the harness would not notice the swap.

Because `worker_cmd` is a user-only key (TRUST_MODEL T7), a repository cannot remove the prefix. Because the sandbox
denies writes to `~/.config/canopy` (§4.2), a worker cannot remove it either.

### 4.2 Filesystem policy

Reads are denied under the home directory and re-allowed where needed. Writes are denied everywhere and allowed where
needed. A deny list of known secret paths was considered and rejected: it always misses one.

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
| The rest of `~/.config/canopy` and `state_dir` (`~/.canopy`) | no | no | Config and journal belong to the harness. |
| The rest of `$HOME` | no | no | Secrets, other repositories. |

The run log is unaffected: the worker's stdout and stderr are file descriptors `_run` opened before the sandbox
started.

Git state is where the worktree boundary leaks. Every slot in a pool shares one common directory: refs, objects, hooks,
config, and every other slot's metadata. Path rules cannot give a worker write access to its own branch alone, because
git updates a ref through a lock file beside it and rewrites a shared `packed-refs`. A worker that can write refs can
move another running worker's branch, which that worker then builds on and pushes as its own. So a worker writes no
shared git state:

- `_run` checks the branch out detached (`git checkout --detach`, from `origin/<branch>` or the base). A detached
  worktree keeps HEAD, the index, and the reflog in `worktrees/<slot>/`, which belongs to that slot alone.
- `_run` sets `GIT_OBJECT_DIRECTORY` to a per-run directory and lists the shared object directory in
  `GIT_ALTERNATE_OBJECT_DIRECTORIES`. New objects land in the per-run directory; existing ones are read from the shared
  directory, read-only. The per-run directory goes away with the run's temp directory.
- The worker pushes with `git push origin HEAD:refs/heads/<branch>`, and step 5's verification compares the remote
  branch with HEAD.

A chore gets the same policy. Its default `cwd` is inside `state_dir`, so its policy re-allows that one directory:
read-only by default, since a chore's only output is its result line (D034), and writable for a chore whose own
tooling writes there. The rest of `state_dir` stays denied.

### 4.3 Network policy

Everything is denied except an allowlist in the operator's policy template:

- The model provider's API host.
- GitHub: `github.com`, `api.github.com`, `*.githubusercontent.com`, and the GitHub MCP endpoint if it is remote.
- The tracker's MCP endpoint, and any internal MCP services the operator uses. Internal hosts need an explicit entry;
  that is the point of running canopy locally, so the template says so.
- The package registries the repository's build and tests fetch from.

`srt` also refuses to connect an allowed name to loopback, link-local, cloud metadata addresses, or the host's own
addresses. Private ranges can be denied too, unless internal MCP services live there.

The residual is exfiltration through an allowed host. With `github.com` allowed and the operator's token in reach, a
worker can still push to any repository or post anywhere the operator can. That is §8's step.

### 4.4 What is wrapped

- `worker_cmd`: yes.
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

1. Host-side git in a slot runs with hooks and filesystem monitors off:
   `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c fetch.recurseSubmodules=false`. Cheap and correct with or
   without a sandbox.
2. `_run` records the slot's `.git` link before the worker starts and refuses (`crashed`, attention item) if it changed
   afterwards, without running git there. The policy already denies writing it; this catches a policy that forgot.
3. The prompt reaches the runtime byte for byte. D023 keeps ticket text out of a shell. `srt` joins its arguments into
   one `bash -c` string after single-quoting each one. That is the POSIX-safe form, but it is a second parser on
   ticket-written text. The canary (§6) proves prompts come through unchanged with a hypothesis property test over
   quotes, newlines, `$()`, backticks, and arbitrary Unicode text (D027). `_run` reads the prompt as UTF-8, so bytes
   that are not valid UTF-8 never reach the command line. If that is not convincing, D023's own revisit clause
   applies: add a `{prompt_file}` placeholder and pass the path of the prompt `_run` already writes.
4. Timeouts still end everything. `_run` kills the worker's process group with SIGKILL. The canary checks that nothing
   inside the sandbox outlives it. canopy reads the result line, not the exit status, so `srt` exiting 0 on SIGTERM
   does not matter.
5. Worker git state is private (§4.2): a detached checkout in step 2, a per-run object directory with the shared one
   as an alternate, and a push by refspec. `_run` sets the object variables for the worker and for its own fallback
   push in step 5. This changes DESIGN §8 steps 2 and 5, and the push instruction in the worker prompts. The `-B`
   reasoning in step 2 goes away, since no run creates a local branch.

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

- Fetching inside a run. The worker cannot update shared remote-tracking refs, so a plain `git fetch` fails. `_run`
  fetches before the worker starts, which covers most runs. Check what the fix-ci and resume prompts ask for, and
  whether a fetch that writes only `FETCH_HEAD` (per worktree) is enough.
- Git push credentials. HTTPS with a credential helper works through the proxy. SSH does not work out of the box on
  Linux: `srt` blocks creating Unix sockets, which includes the agent socket. canopy already recommends HTTPS remotes
  and `canopy init` warns about SSH ones (D038). Still open: whether to support SSH inside the sandbox at all (allow
  the agent socket, or push from the host in `_run`), or to leave SSH to unsandboxed runs.
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
- Where this sits in the ROADMAP: the trigger says before a second team adopts canopy. It needs M2's real worker to be
  worth testing against.

## 8. Later

- Credential scoping. A fine-grained GitHub token limited to the pool's repositories closes most of §4.3's residual.
  `srt` also has an experimental mode that gives the sandbox a placeholder credential and substitutes the real one
  only on requests to named hosts. Evaluate it once the first phase is in use.
- A hypervisor boundary, if canopy ever runs workers off the operator's machine. Same prefix, different script.
