# M26. Sandboxed workers, opt-in

HOST_ISOLATION, TRUST_MODEL T4 and T6, D107, D109. Needs M2. Asked for by the operator (2026-10-12), ahead
of the deferred list's trigger: the sandbox should be proven on the operator's machines before a second team adopts
canopy, not built after an incident.

- The per-run object directory (HOST_ISOLATION §4.2). `_run` makes `<state_dir>/runs/<id>.objects/` before step 2 and
  passes it to `setup_cmd` and the worker as `CANOPY_GIT_OBJECTS`, never as git's own variables. When the worker left
  anything in it, step 5 runs with `GIT_OBJECT_DIRECTORY` and `GIT_ALTERNATE_OBJECT_DIRECTORIES` set, and then, on
  every exit path, each slot is checked out detached at step 2's commit, its HEAD reflog expired, and the directory
  deleted, before the slot is returned. An unsandboxed run leaves it empty, and nothing changes for it.
- `run_slots` records each slot's `.git` link (a new migration), so reconcile's `end_run` does the same cleanup for a
  run whose `_run` is gone, after the same link check `_run` makes; this closes the gap a `_run` killed with SIGKILL
  leaves (HOST_ISOLATION §5 item 2).
- `canopy-sandbox`, the wrapper HOST_ISOLATION §4.1 describes (resolve the cwd's worktrees and their git directories,
  write a per-run `srt` policy, drop `BASH_ENV`, map `CANOPY_GIT_OBJECTS` to git's variables,
  `exec srt --settings <policy> -- "$@"`), taking a role (`worker`, `setup`, `chore`, `review`) that picks the
  policy; and the policy template, §4.2's filesystem table and §4.3's network allowlist with the operator's hosts
  left to fill in. No Unix sockets, so sandboxed runs push over HTTPS. Not harness code: the harness sees only the
  command template, as today. First an example under `examples/sandbox/`; on the operator's request (2026-10-14) it
  ships with canopy, as the workspace member `packages/canopy-sandbox` (D041), and `canopy sandbox setup` copies the
  templates, installs the `srt` its lockfile pins with npm, and checks and prints what needs root (D117).
- `docs/SANDBOX.md`, an operator's guide like `docs/BAZEL.md`: `canopy sandbox setup` and what it cannot install, the
  prefixes for `worker_cmd`, `private_worker_cmd`, `setup_cmd`, and chore `cmd`, the allowlist, HTTPS
  remotes, and Ubuntu 24.04's restriction on unprivileged user namespaces. `canopy init` prints the suggested
  `worker_cmd` and writes nothing.
- The canary (HOST_ISOLATION §6), `tests/canopy_sandbox/test_sandbox_canary.py`, opt-in with `CANOPY_SANDBOX_CANARY=1`:
  a plain script run through the real `worker_cmd` prefix and the shipped wrapper, every denial and every positive
  control §6 lists, the prompt property test included. A Linux CI job runs it with bubblewrap and `srt`.
- Settled before Accept, each in HOST_ISOLATION §7 or a decision: what treehouse's `return` runs in a slot; caches that
  tools keep as git repositories under the per-run object directory; OpenCode's local MCP servers inside the sandbox.
- TRUST_MODEL T4 and T6: the sandbox as a control, what it does not cover (the shared kernel, exfiltration through an
  allowed host), and that it is opt-in. DESIGN §8 and §15 for the object
  directory and reconcile's cleanup; HOST_ISOLATION's settled parts move to DESIGN.
- Tests with the fakes: an empty object directory sets no git variable for step 5 and is deleted; a worker that commits
  through it is pushed and leaves the slot on step 2's commit with `git gc` clean in the primary clone; a `_run`
  killed after the worker leaves cleanup to reconcile, which puts back a slot's changed link before any git there.

Accept: the tests above pass, and the canary passes in CI on Linux. Live: the canary passes on the operator's Linux and
macOS machines, then a day of `canopy loop` with sandboxed workers pushes and opens PRs as before, and a worker run that
tries to read `~/.ssh` or write `~/.config/canopy` is refused.

Status: in progress. The per-run object directory and the `run_slots` link are in: `_run` and reconcile tidy each slot
before it is returned, and `tests/canopy/runs/test_run_objects.py` holds the fakes-based tests above. Checking them
found that the tidy step must also drop the slot's own refs, and that `_run`'s own push must put origin's
remote-tracking ref back (HOST_ISOLATION §4.2). The wrapper and a policy template for each role are in
`packages/canopy-sandbox`, tested against a fake `srt` in `tests/canopy_sandbox/test_sandbox_wrapper.py`, `_run` with
the wrapper as `worker_cmd`'s prefix included. Trying them under `srt` 0.0.79 and bubblewrap found that `srt` binds an
`allowRead` path over an `allowWrite` path beneath it, so the wrapper names the common git directory entry by entry, and
that a write under a denied directory lands in a `tmpfs` and is dropped, so the canary must check writes on the host
(HOST_ISOLATION §4.2, §6). `docs/SANDBOX.md` is the operator's guide, and `canopy init` prints the suggested
`worker_cmd`. Running the guide's check under `srt` 0.0.79 and bubblewrap 0.9 found that a check run through the wrapper
outside canopy must use a worktree of its own, since nothing tidies a slot it commits in, and that a process started
with `setsid` inside the sandbox ends with it. `canopy sandbox setup` installs the wrapper's pinned `srt` in
`~/.local/share/canopy/`; trying it found that `srt`'s seccomp helper runs inside the sandbox, so under the `$HOME` a
template denies it is not found unless the wrapper re-allows reading `srt`'s `vendor/` directory, which it now does
wherever `srt` is installed. The canary is `tests/canopy_sandbox/test_sandbox_canary.py` (`make sandbox-canary`), and
CI's `sandbox-canary` job runs it on Linux and macOS after `canopy sandbox setup`. Running it under `srt` 0.0.79 and
bubblewrap 0.9 found that `srt` makes its network sockets in the run's temp directory, so a long system temp directory
fails every run; the wrapper now refuses one on Linux with a message that says so. macOS's deep per-user temp directory,
which `srt`'s source suggested was too long, is not: the macOS job runs a case under it (HOST_ISOLATION §7). Run against
a fake `srt` that sandboxes nothing, the canary fails every case but its positive controls. It passes in CI on Ubuntu
24.04, with the AppArmor restriction lifted as docs/SANDBOX.md says, and on macOS, both with `srt` 0.0.79. What
treehouse's `return` runs in a slot is settled from its source (HOST_ISOLATION §7): plain git, which reads only what a
sandboxed worker cannot write. Tracing it found that the slot's own `commondir` and `gitdir` were writable, and a worker
that rewrote `commondir` had every git on the host in its slot, canopy's included, read a config it wrote; the wrapper
now denies writing both, the canary checks it, and `_run` and reconcile check `commondir` as they do the `.git` link.
Caches that tools keep as git repositories are settled too: git's variables, set for the whole run, sent the objects of
Go's module sources and of OpenCode's snapshots, which persist under its data directory, to the run's directory, so the
wrapper now puts a `git` of its own first on `PATH` that sets them in the run's worktrees only; pre-commit was never
affected. OpenCode's MCP servers are settled from its source: a local one is OpenCode's child and runs under the
worker's policy, and one started with `docker run` cannot work, since the sandbox refuses Unix sockets, which the canary
now checks. `review_cmd`, HOST_ISOLATION §7's last open wrapping question, is settled as a role of its own, `review`,
with a template that reads the checkout through the review directory's link and writes none of it, no object directory,
and no `github.com`; the canary runs its HOME and state attempts as `review` too, and checks that a review writes
nothing in the checkout. Run against the fake `srt`, every review denial fails and its positive control passes.
TRUST_MODEL T4 and T6 name the sandbox as an opt-in control, with its residuals: the shared kernel, the unwrapped
overseer and harness calls, `/tmp/claude`, and exfiltration through an allowed host with the credentials a run holds
(D118).
HOST_ISOLATION's settled parts are DESIGN §24 now, with its answered questions beside what they settled; HOST_ISOLATION
keeps the problem, goals, and options, and points each later section there.
Giving sandboxed runs caches of their own, §24's open question on build caches, found that the templates let a run
write `~/.cache/opencode`, from which OpenCode imports packages and runs programs, the unsandboxed overseer's
included: a way out of the sandbox at the next tick. Each role now caches in `~/.cache/canopy/sandbox/<role>/`, setup
in the worker's, through `@CACHE@` and the cache variables the wrapper sets; the canary checks that no run writes the
operator's OpenCode cache or another role's, and that a role's cache persists; `canopy sandbox setup` says when a
template it kept still writes the operator's caches. Whether OpenCode's data and state directories, which the
templates also leave writable and the overseer also reads, are another way out is DESIGN §24's open question now.
Tracing it found that the data directory is: a `wellknown` entry in `auth.json`, the active account in `opencode.db`,
and a planted snapshot git directory each make the overseer's OpenCode, or the operator's, run what a worker chose;
the state directory is not (DESIGN §24, Open).
CI dropped its macOS canary job 2026-10-17, at the operator's request: macOS is left to the live check on the
operator's machine.
Data of the sandbox's own is in, on the operator's call (2026-10-18) that they log in once, not again for the sandbox:
each role's OpenCode keeps its data in `~/.local/share/canopy/sandbox/<role>/`, the wrapper copies the operator's
`auth.json` and `mcp-auth.json` in before each run and copies back after it only an OAuth refresh of a login the
operator has, and it denies writing the operator's OpenCode data whatever the template says, so a template kept from
before is closed too; `canopy sandbox setup` says when one still names it. Reading OpenCode 1.19.3's source found that
it drops a login it cannot decode, and the whole of `mcp-auth.json` for one bad entry, so what comes back is checked
field by field against the shapes OpenCode writes (DESIGN §24, Logins). The canary's new cases pass under `srt` 0.0.79
and bubblewrap 0.9 on Ubuntu 24.04, and fail under the fake `srt`, as its others do.
Next: the canary on the operator's Linux and macOS machines, then a day of `canopy loop` with sandboxed workers.
