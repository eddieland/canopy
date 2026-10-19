# M46. Workers file follow-up tickets

REQUIREMENTS N3, DESIGN §18 (Follow-up tickets). Asked for by the operator (2026-10-16): a worker should be able to
file follow-up work and properly linked TODOs, and canopy should work them. The split worker, a whole run kind whose
only output is tickets, has never run live and is not worth keeping on its own. The operator moved the authorization
line: a human's queue label on a ticket authorizes it and the follow-ups its runs file, since that work happens on a
branch in a leased worktree and lands only through a PR a human reviews and merges. "Humans should authorize work, but
I'm not super worried about the prospect of an agent authorizing itself to work in a sandboxed copy of the repo."
Humans still authorize everything that lands; canopy still never merges (TRUST_MODEL §6).

- Any `implement` or `resume` worker on a public ticket that is not itself a follow-up may create tickets (M56 folded
  `fix-ci` into `resume`): in its ticket's project, linked to its ticket as the parent, with the repository in the body
  (`canopy-repo: web`) when one applies, no assignee, and no labels. It reports them in its result as
  `"created": {"PROJ-14": "web", "PROJ-15": null}`. `_run` checks each entry alone (a valid key, new to the journal,
  not the parent, the parent's key prefix where both have one, a mapped repository or null) and records those that
  pass, with the run that made them, in a record generalized from `split_children` by a new migration, which carries
  over only the split children already worked; an unlabeled child stays an ordinary ticket. A refused entry leaves the
  run's status as the worker reported it.
- A follow-up the journal records is a candidate without a queue label: its authorization is its parent's, and the
  state block carries it whatever the query returns. Dispatch names no `--label` for it, and refuses it
  (`parent_withdrawn`) while the parent is stopped or once it is forgotten. The worker's re-read (D051) is that the
  ticket links its parent, rendered as `{{AUTHORIZATION}}`.
- None of this stops a steered agent from authorizing work for itself, and M46 does not try. A worker can already add
  a queue label to any ticket it can reach, and every label check is agent judgment (TRUST_MODEL T1). So M46 drops the
  split's label-history checks rather than generalize them. What bounds an agent that authorizes its own work is the
  harness's guards in code (capacity, attempt limits, cooldowns, never merge) and a human reviewing every PR before
  it lands.
- Volume bounds, in code: at most `policy.max_follow_ups` recorded per run (default 5; 0 records none), and only one
  generation deep. They keep a well-meaning worker from fanning out; they do not stop a steered one. Anything past them
  is an ordinary ticket, worked only with a queue label, and the harness raises `follow_up_unrecorded` naming it.
- Splitting stops being a kind. An authorized reply asking for a split is guidance to the ticket's next run, which
  files the children as follow-ups, ordered with the tracker's blocker relation as now. `multi_repo` attention stays
  for a ticket nobody asked to split.
- Removed: `--kind split` (refused `bad_kind`), `--request`, `bad_request`, `bad_split`, the `split` phase,
  `split_unlabeled` and `split_self_labeled`, `split_cmd` and `policy.max_split_attempts` (to `REMOVED_KEYS`), the
  `canopy-splitter` definition and its sandbox role, `worker-split.md`, SCENARIOS S2 and S15, `canopy forget`'s
  `split` refusal, and M44's `bad_plan` for a split's parent. Old `runs` rows of kind `split` stay as history. The
  detached desk a split runs in stays, since M44's planner runs in one.
- The worker definitions allow the tracker's create and link tools. On GitHub, `issue_write` already creates issues
  and only the prompt kept the worker from it (TRUST_MODEL T6), so the line this moves was mostly prompt-deep already.
- Private tickets are unchanged: their workers write nothing to the tracker.
- TRUST_MODEL T1 (from "the loop may create tickets, but never decides to" to "a worker may file follow-ups to its
  ticket, worked under its ticket's authorization; authorization checks on tickets are best effort, and the backstops
  are the guards in code and review of what lands"; an accepted gap: `_run` checks a reported key's text only, so a
  worker can record a ticket it did not file), T3 (the volume bounds), and T6 (a worker's write scope adds
  creating and linking tickets in its ticket's project), a decision entry for the new line and D084's edit, and the
  overseer prompt, worker prompts, and definitions. The design's other sections that name splits change with it.
- Tests with the fakes: an `implement` reporting `created` records each valid follow-up with its repository; each
  refused entry (bad key, the parent, a known key, another prefix, an unmapped repository, past `max_follow_ups`, from
  a follow-up's run, from a private run) recorded nowhere, named in the run's note and in `follow_up_unrecorded`, the
  run's status unchanged; a follow-up dispatched without `--label`; `parent_withdrawn` after the parent's stop or
  forget; a follow-up's prompt carrying its parent check, and an override without `{{AUTHORIZATION}}` refused;
  `unknown_repo` for any other repository; `--kind split` refused; the removed keys' errors; the migration carrying
  over only worked split children; the state block's follow-ups, a snapshot.
- Open, in the design: the parent's phase once a split request moved its work into follow-ups; journal-only
  follow-ups for a private ticket's worker; whether `policy.max_follow_ups = 0` is enough for an operator who wants the
  old line; whether losing its label withdraws a parent's follow-ups; a bound per ticket rather than per run; how long
  `follow_up_unrecorded` stands; and whether a follow-up is a draft under `trust.review_replies = "approve"`.

Accept: written with the design, before work starts. The tests above pass, and the design names splitting only as old
runs' kind. Live, once built: on a labeled ticket in the toy workspace (TOY_REPOS), a worker files a follow-up linked to
it, with no labels; the next tick dispatches the follow-up without a label, its worker checks the parent link, and its
PR lands for review.

Status: in progress. Designed 2026-10-19 (DESIGN §18, Follow-up tickets). The design settles which runs file follow-ups
(public `implement` and `resume`, not a follow-up's own), that `_run` refuses a bad entry alone rather than the run,
that a `--label` on a follow-up dispatches it as any labeled ticket, that `forget` withdraws a parent's follow-ups
rather than refusing, that split children carry over as follow-ups, and the attention item past the bounds; the
sketch's three open points and four more wait on the operator, listed there.
