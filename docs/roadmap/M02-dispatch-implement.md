# M2. Dispatch implement

Guarded dispatch with a lease and a detached `_run`, the `implement` worker, attention for crashed and unpushed runs,
the worker's own agent definition, and definitions from a directory canopy owns (D040, D044).

Status: done 2026-10-07.
Learned: live, GH-64 went from label to PR #69 unattended, and a run killed with SIGKILL was `crashed` on the next tick
with its slot returned. An empty journal's comment cursors make old authorized comments read as new. The worker's MCP
tools cannot label a PR, so the `agent` label lands only when the model uses `gh`.
Next: give the worker a reliable way to label, or have the harness do it.
