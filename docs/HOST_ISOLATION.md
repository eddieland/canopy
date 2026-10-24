# Host isolation for agent runs

Status: background, not normative. This was the proposal ROADMAP M26 adopted (2026-10-12); what it settled is DESIGN
§24, [Sandboxed runs](design/SANDBOXING.md), which is normative, with TRUST_MODEL T4 and T6 (D118). What stays here is
why: the problem, the goals, and the options weighed. The operator's guide is [SANDBOX.md](SANDBOX.md).

## 1. Problem

A worker runs as the operator, reads text other people wrote, and is assumed to follow injected instructions some of
the time (TRUST_MODEL §3). Without a sandbox its only limits are OpenCode permissions, which are defense in depth (T4,
D021). The shipped `canopy-worker` definition allows `bash: "*"`, and `external_directory: deny` covers OpenCode's edit
tool, not what a shell command touches. So a steered, unsandboxed worker can:

- Read `~/.ssh`, `~/.aws`, `~/.netrc`, `~/.docker/config.json`, browser profiles, and every other repository on disk.
- Rewrite `~/.config/canopy/config.toml`: change `worker_cmd`, add itself to `trust.authorized_repliers`, raise
  capacity. T7 keeps those keys out of shared files, but nothing keeps a worker out of the user config.
- Write to the journal under the workspace's `.canopy/`, which is the audit log (T5).
- Plant a hook or `core.fsmonitor` in the pool's shared git directory. Later `git` calls run it on the host outside
  any worker: in `_run`, in the next run on that pool, or in the operator's own checkout if it shares that directory.
- Append to `~/.bashrc`, drop binaries in `~/.local/bin`, or install a launch agent.
- Send anything anywhere over the network (T6).

Each of these is the same exposure as an interactive agent, minus the human glance. The ROADMAP's trigger for fixing it
was "a T4 or T6 incident, or before any second team adopts it"; the operator moved it ahead of both (M26).

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
- Sandboxing the overseer (§4.4). It has since got a role of its own, `overseer`, which canopy refuses on
  `overseer_cmd` until the tick starts every run the overseer asks for (DESIGN §24, §40).
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

Moved to DESIGN §24: §4.1, the prefix, is [The wrapper](design/SANDBOXING.md#the-wrapper); §4.2, the filesystem
policy, is [Filesystem policy](design/SANDBOXING.md#filesystem-policy) and [Git
state](design/SANDBOXING.md#git-state); §4.3 is [Network policy](design/SANDBOXING.md#network-policy); §4.4 is [What
is wrapped](design/SANDBOXING.md#what-is-wrapped).

## 5. Harness changes

Moved to DESIGN §24, [What the harness runs around a sandboxed
run](design/SANDBOXING.md#what-the-harness-runs-around-a-sandboxed-run), and §8 and §15 for the object directory and
reconcile's cleanup. Item 1 is D107, item 3 the prompt, item 4 timeouts, item 5 D109 and the object directory.

## 6. The canary

Moved to DESIGN §24, [The canary](design/SANDBOXING.md#the-canary).

## 7. Open questions

The answered ones are in DESIGN §24 next to what they settled; the open ones are its [Open](design/SANDBOXING.md#open).

## 8. Later

Moved to DESIGN §24, [Open](design/SANDBOXING.md#open): credential scoping and a hypervisor boundary.
