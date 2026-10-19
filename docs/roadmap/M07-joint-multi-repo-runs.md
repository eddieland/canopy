# M7. Joint multi-repo runs

A ticket with a unit per repository: all-or-nothing leases, desks, `prs` in the result contract, per-unit phases and
cursors, and the desk canary.

Status: done 2026-10-13.
Learned: closed on the operator's real use, without a live joint run (SCENARIOS S14). The desk canary fails when the
workspace root is a git checkout, since OpenCode takes the enclosing repository as its project (TRUST_MODEL T4).
Next: run the canary (S1) before a real joint run in a workspace that is a git checkout.
