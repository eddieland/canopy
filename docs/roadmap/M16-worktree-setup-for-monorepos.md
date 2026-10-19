# M16. Worktree setup for large monorepos

`paths.worktree_include`, `runtime.setup_cmd`, and for Bazel a shared-cache recipe (`docs/BAZEL.md`) and a canary.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the Bazel run and the canary's first real run are SCENARIOS S7 and S1.
Pools get no root of their own: a fast disk takes the whole workspace (DESIGN §18, D033).
Next: run S1 before relying on a worker's reads through Bazel's links.
