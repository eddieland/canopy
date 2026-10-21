# M46. Workers file follow-up tickets

REQUIREMENTS N3, DESIGN §18 (Follow-up tickets). Asked for by the operator (2026-10-16): a worker should be able to
file follow-up work and properly linked TODOs. The split worker, a whole run kind whose only output is tickets, has
never run live and is not worth keeping on its own. The operator settled the authorization line (2026-10-19): workers
do not authorize downstream work, they notice the need and request it. A follow-up a worker files authorizes nothing;
a human's queue label, or the operator's `canopy start`, authorizes it as any ticket. Humans authorize everything that
runs and everything that lands; canopy still never merges (TRUST_MODEL §6).

- Any `implement` or `resume` worker, public or private, on a ticket that is not itself a follow-up may create tickets
  (M56 folded `fix-ci` into `resume`): in its ticket's project, linked to its ticket as the parent, with the repository
  in the body (`canopy-repo: web`) when one applies, no assignee, and no labels. It reports them in its result as
  `"created": {"PROJ-14": "web", "PROJ-15": null}`. `_run` checks each entry alone (a valid key, new to the journal,
  not the parent, the parent's key prefix where both have one, a mapped repository or null) and records those that
  pass, with the run that made them, in a journal record of its own. A refused entry leaves the run's status as the
  worker reported it.
- A recorded follow-up is a request. Nothing dispatches it until a human labels it or the operator starts it; then it is
  an ordinary ticket. canopy tells the operator instead, once: the run's close records a `follow_ups.filed` event
  naming each with its repository (DESIGN §20). Filing is an event, not a state: an attention item would stand until a
  run, a start, or done, so a follow-up the operator declined stayed on the list until its parent was done (2026-10-20).
- Volume bounds, in code: at most `policy.max_follow_ups` recorded per run (default 5; 0 records none), and only one
  generation deep. Anything past them, or reported by a run that rewrote its slot's git, is not recorded, and the
  harness raises `follow_up_unrecorded` naming it. The bounds keep the operator's list short; none of it runs anyway.
- A private ticket's worker files follow-ups too, the one thing it writes to the tracker (2026-10-19).
  `canopy-worker-private` allows the tracker's create tools by name, whole, so on GitHub `issue_write`, which also
  edits and closes issues: accepted. Its follow-ups are tickets on the tracker like any other, worked only once the
  operator starts or labels them.
- Splitting stops being a kind. An authorized reply asking for a split is guidance to the ticket's next run, which
  files the children as follow-ups, ordered with the tracker's blocker relation as now; a human authorizes each, as
  with split children. `multi_repo` attention stays for a ticket nobody asked to split.
- Removed: `--kind split` (refused `bad_kind`), `--request`, `bad_request`, `bad_split`, the `split` phase,
  `split_unlabeled` and `split_self_labeled`, `split_cmd` and `policy.max_split_attempts` (to `REMOVED_KEYS`), the
  `canopy-splitter` definition and its sandbox role, `worker-split.md`, SCENARIOS S2 and S15, `canopy forget`'s
  `split` refusal, and M44's `bad_plan` for a split's parent. Old `runs` rows of kind `split` stay as history. The
  detached desk a split runs in stays, since M44's planner runs in one.
- The worker definitions allow the tracker's create tools. On GitHub, `issue_write` already creates issues and only the
  prompt kept the public worker from it (TRUST_MODEL T6). An operator's own OpenCode config cannot deny a tool canopy's
  definition allows, since canopy's is merged after it (D044); `policy.max_follow_ups = 0` and the MCP server's own tool
  selection are what an operator has.
- TRUST_MODEL T1 (the loop may create tickets, but they authorize nothing; a human's label or start authorizes work;
  an accepted gap: `_run` checks a reported key's text only, so a worker can record a ticket it did not file, which
  changes only what the attention item names), T3 (the volume bounds), and T6 (a worker's write scope adds creating
  tickets in its ticket's project), D123, D084's edit, and the overseer prompt, worker prompts, and definitions. The
  design's other sections that name splits change with the removal.
- Tests with the fakes: an `implement` reporting `created` records each valid follow-up with its repository; each
  refused entry (bad key, the parent, a known key, another prefix, an unmapped repository, past `max_follow_ups`, from
  a follow-up's run, from a run that rewrote its slot's git, a key another run recorded first) recorded nowhere, named
  in the run's note and in `follow_up_unrecorded`, the run's status unchanged; a follow-up refused without a label;
  `follow_ups.filed` naming each recorded follow-up once, and no attention item for it; a private run's follow-up
  recorded and started only by the operator; `--kind split` refused; the removed keys' errors.
- Open: the parent's phase once a split request moved its work into follow-ups; a bound per ticket rather than per
  run; how long `follow_up_unrecorded` stands; and whether a follow-up is a draft under `trust.review_replies =
  "approve"`.

Accept: the tests above pass, and the design names splitting only as old runs' kind. Live, once built: on a labeled
ticket in the toy workspace (TOY_REPOS), a worker files a follow-up linked to it, with no labels; a sink hears
`follow_ups.filed`; the operator labels the follow-up, the overseer dispatches it, and its PR lands for review.

Status: in progress. Designed 2026-10-19 (DESIGN §18, Follow-up tickets), and the line moved the same day: a follow-up
is a request the operator decides on, never work a worker authorized. Built: workers, public and private, may file
follow-ups and are told they are requests; `_run` checks and records them (migration 0049); the harness raises
`follow_up_unrecorded`, and the run's close records `follow_ups.filed` (an attention item until 2026-10-20);
TRUST_MODEL T1, T3, T6, D123, and D084 as written; and splits removed (2026-10-19): every bullet under "Removed", an
authorized reply asking for a split as guidance to the next run, and the design naming splitting only as old runs'
kind. Left: the live check.
