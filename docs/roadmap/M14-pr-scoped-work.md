# M14. PR-scoped work

REQUIREMENTS R9 and D056. Needs M3's and M56's `resume`. Sketch only; the design comes first.

- A unit of work keyed by a PR rather than a ticket, for the operator's own hand-written PRs: a `resume` when its checks
  fail or review comments arrive, with the same cursors, attempt limits, and cooldown as a ticket's.
- Authorization by a queue label on the PR, as on a ticket, so neither the operator nor a coworker learns a command.
  Only PRs the operator authored, in the repository or workspace the loop runs for.
- The worker pushes to the PR's head branch, never with force, never on a PR from a fork; the harness refuses the
  repository's base branch. The worker prompt re-reads the PR's author and labels first and changes nothing without
  both (D051's pattern).
- `canopy status` and the attention list name PR units by the PR, not a ticket key.
- PR references (`repo#N` or the PR's URL) in `canopy start`, `stop`, `reply`, and `show` (DESIGN §22, D075), so
  the operator can also start one of their own PRs privately instead of labeling it. That is a T1 change beside D056's,
  needing the operator's approval as M18's does.
- `canopy mirror` for a PR reference: the PR's review comments join the journal as its conversation (DESIGN §22, M19).
- TRUST_MODEL T1 and §6 already allow it (D056).

Accept: written with the design, before work starts, and like every milestone's, a real run of what it delivers.

Status: deferred 2026-10-15. The operator judged it YAGNI once canopy was in real use; the sketch stays for when the
deferred list's trigger fires.
