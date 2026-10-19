# M46. Workers file follow-up tickets

REQUIREMENTS N3, DESIGN §18. Sketch only; the design comes first. Asked for by the operator (2026-10-16): a worker
should be able to file follow-up work and properly linked TODOs, and canopy should work them. The split worker, a
whole run kind whose only output is tickets, has never run live and is not worth keeping on its own. The operator moved
the authorization line: a human's queue label on a ticket authorizes it and the follow-ups its runs file, since that
work happens on a branch in a leased worktree and lands only through a PR a human reviews and merges. "Humans should
authorize work, but I'm not super worried about the prospect of an agent authorizing itself to work in a sandboxed copy
of the repo." Humans still authorize everything that lands; canopy still never merges (TRUST_MODEL §6).

- Any `implement`, `fix-ci`, or `resume` worker may create tickets: in its ticket's project, linked to its ticket as
  the parent, with the repository in the body (`canopy-repo: web`) when one applies, no assignee, and no labels. It
  reports them in its result as `"created": {"PROJ-14": "web", "PROJ-15": null}`. `_run` validates them as it
  validates a split's children today (a valid key, new to the journal, not the parent, a mapped repository or null)
  and records them, with the run that made them, in a table generalized from `split_children` by a new migration.
- A follow-up the journal records is a candidate without a queue label: its authorization is its parent's. Dispatch
  names no `--label` for it, and refuses it while the parent is stopped or forgotten. The worker's re-read (D051) is
  that the ticket links its parent.
- None of this stops a steered agent from authorizing work for itself, and M46 does not try. A worker can already add
  a queue label to any ticket it can reach, and every label check is agent judgment (TRUST_MODEL T1). So M46 drops the
  split's label-history checks rather than generalize them. What bounds an agent that authorizes its own work is the
  harness's guards in code (capacity, attempt limits, cooldowns, never merge) and a human reviewing every PR before
  it lands.
- Volume bounds, in code: at most `policy.max_follow_ups` recorded per run (default 5), and only one generation deep.
  They keep a well-meaning worker from fanning out; they do not stop a steered one. Anything past them is an ordinary
  ticket, worked only with a queue label, and the harness raises attention naming it.
- Splitting stops being a kind. An authorized reply asking for a split is guidance to the ticket's next run, which
  files the children as follow-ups, ordered with the tracker's blocker relation as now. `multi_repo` attention stays
  for a ticket nobody asked to split.
- Removed: `--kind split`, `--request`, the `split` phase, `split_unlabeled` and `split_self_labeled`, `split_cmd`
  and `policy.max_split_attempts` (to `REMOVED_KEYS`), the `canopy-splitter` definition and its sandbox role,
  `worker-split.md`, SCENARIOS S2 and S15, and M44's `bad_plan` for a split's parent. Old `runs` rows of kind
  `split` stay as history. The detached desk a split runs in stays, since M44's planner runs in one.
- The worker definitions allow the tracker's create and link tools. On GitHub, `issue_write` already creates issues
  and only the prompt kept the worker from it (TRUST_MODEL T6), so the line this moves was mostly prompt-deep already.
- Private tickets are unchanged: their workers write nothing to the tracker.
- TRUST_MODEL T1 (from "the loop may create tickets, but never decides to" to "a worker may file follow-ups to its
  ticket, worked under its ticket's authorization; authorization checks on tickets are best effort, and the backstops
  are the guards in code and review of what lands") and T6 (a worker's write scope adds creating and linking tickets
  in its ticket's project), a decision entry for the new line, and the overseer prompt, worker
  prompts, and definitions.
- Open: what a parent's phase is once its work has moved into follow-ups; whether a private ticket's worker should
  file journal-only follow-ups; whether an operator who wants the old line should get a private switch that makes
  follow-ups wait for a label.

Accept: written with the design, before work starts.

Status: not started.
