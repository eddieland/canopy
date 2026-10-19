# M55. Trivial work skips its plan

REQUIREMENTS R22, DESIGN §25, TRUST_MODEL T1, T3, T6, and T7. Needs M44; its feedback half needs M54. Asked for by
the operator (2026-10-17): with plans on, a typo fix or a one-line config change costs a planner run and the operator's
approval for a plan nobody needed. A smaller, cheaper agent should be able to judge such a change trivial, so that it
goes ahead unplanned. An option, to save tokens and the operator's time on obvious work. Sketch only; the design comes
first, in §25.

- **The setting.** `policy.plan_triage`, `"off"` (default) or `"on"`, and `policy.trivial`, optional plain language
  for the triage agent saying what counts as trivial, in place of its prompt's own measure (2026-10-19). Both private:
  unlike `policy.plan`, which a shared file may only tighten, triage loosens the operator's plan gate, so only the
  operator turns it on (T7).
  `runtime.plan_triage_cmd` names the model, a cheaper one than `plan_cmd`'s recommended, with a short timeout of its
  own, `runtime.plan_triage_timeout_minutes` (10).
- **When it runs.** Only for a plan the policy asks for: a ticket whose own setting says `plan` (`canopy plan KEY`, or
  `start --plan`) is planned whatever triage would say, since that is the operator's word for that ticket. Before the
  first `plan` of such a ticket, with no branch, no plan run, and no triage run yet, the
  overseer dispatches a `needs-plan` run, once per ticket: a second is refused `triaged` however the first ended, and
  one not due `bad_triage`. Under M54, before a feedback plan too, once per round of feedback.
- **The run.** A read-only run with a verdict, as M25's `triage-ci` is (DESIGN §23): it leases no slot, reads the ticket
  through the tracker's read tools and the named repositories' primary clones, linked from a directory of canopy's,
  and writes nothing anywhere. It still counts toward `capacity.max_workers` with workers and reviews, since it is an
  agent run with spend: a slot bounds worktrees, the cap bounds runs. Its definition, `canopy-plan-triage`, is the
  planner's with nothing to edit (T6). Result line:
  `{"status":"done|failed","verdict":"trivial|plan","reason":"one sentence"}`. Its prompt says: when unsure, `plan`.
- **Fails closed.** Only a `done` run with the verdict `trivial` waives the plan. A `plan` verdict, a failure, a
  timeout, or a result that does not validate leaves the ticket needing its plan, and the next tick dispatches `plan`
  as today. The waiver is a journal fact naming the run and its reason, distinct from the operator's `--skip`, shown on
  the ticket's page and by `canopy show`. The operator undoes it with `canopy plan KEY` until the `implement` starts,
  and `canopy forget` ends it. A triage that ends other than `done` raises no run attention item, since the plan
  follows at once, and the `implement` a waiver lets through never hears the triage's reason.
- **Feedback stays gated.** Under M54, a `trivial` verdict on a round of feedback returns it to today's rules rather
  than letting it through: a trusted reviewer's items dispatch `resume`, and anyone else's wait for the operator's
  go-ahead (D089). So triage never lets an untrusted reviewer's text start a worker.
- **A second opinion after.** Size says little about risk: a long PR repeating one change can be trivial, and a
  one-line change can break everything, so no line count is checked (the operator, 2026-10-17). Where
  `review.agent_prs` is on, canopy's reviewer (§21) already judges each of the loop's PRs `low`, `normal`, or `high`
  impact against `review.low_impact`; a waived ticket's PR it judges `high` raises `not_trivial` on the attention list,
  naming the triage run's reason. It stops nothing: the PR's review is still the gate. It tells the operator, and the
  `decisions` corpus, how often triage was wrong. With reviews off there is no second opinion but the PR's review.
- **No glance first.** A waiver goes ahead without the operator: a ticket its author calls trivial usually is, and
  waiting on the operator would give back the time triage saves (the operator, 2026-10-17).
- **Code shared.** M25's `triage-ci` shape (a slotless read-only run with a verdict, never built yet, so whichever is
  built first builds it for both), M44's planner definition and read tools, §21's plain-language criteria, and the
  spend page (M33), which shows triage runs as a kind of their own.
- **TRUST_MODEL**, in the PR that builds it: T1 (a triage verdict, an agent's judgment that ticket text can steer, may
  lift the plan gate, but only where the operator turned triage on and only for a plan the policy asked for; the
  operator's own `plan` setting and D089's gate on feedback stay; the reviewer's impact and the PR's review are the
  backstop; the operator accepts that a ticket's text can talk triage into `trivial`); T3 (one triage per ticket and per
  feedback round, its timeout, and capacity); T6 (the triage run writes nothing); T7 (both keys private).
- Tests with the fakes: `trivial` waives the plan and `implement` follows unplanned; `plan`, `failed`, a timeout, and a
  bad result each leave the plan needed; a ticket set to `plan` by the operator is never triaged; one triage per
  ticket, refused `triaged`; `triage_off` and `bad_triage`; a failed triage raising no attention item, with the plan
  following; `canopy plan KEY` undoes a waiver and `canopy forget` ends one; a `high` review of a waived ticket's PR
  raises `not_trivial`, a `normal` one does not; a trivial feedback round with an untrusted item waits for the
  go-ahead; `"off"` leaves every snapshot unchanged.
- **No model per run.** Triage chooses no model for the work. With plans on, the operator runs a cheaper `worker_cmd`
  (2026-10-17), since every worker then has an approved plan or a ticket judged trivial: a setting of theirs, not a
  choice an agent makes.
- **No retry.** A triage run that crashes, times out, or prints a result that does not parse is not run again: the
  ticket is planned at once (the operator, 2026-10-17).

Accept: written with the design, before work starts. Live, once built: over a week with plans and triage on, the
spend page shows triage runs' cost against the planner runs they saved; every waived ticket's PR is one the operator
agrees needed no plan, or that its review judged `high` and raised `not_trivial`.

Status: in progress. Designed 2026-10-19 (DESIGN §25, Triage before a plan). The design settles what the sketch left
open: when a triage is due and the guards that hold it to once per ticket; that it reads the named repositories'
primary clones through links, as a plan's desk links slots; that only a validated result writes the waiver, which
`unplanned` reads in code and `canopy forget` ends; and that `not_trivial` lasts until the ticket is done or
forgotten. Open for the operator: the feedback half, which M54's design settles; the sandbox role for
`plan_triage_cmd`; and whether a waiver sends an event to the sinks. Built 2026-10-19, against the fakes: the four
private keys; the `needs-plan` run, slotless in a desk linking the primary clones, with `canopy-plan-triage`, one
prompt for public and private tickets, and its result validated; dispatch's `triage_off`, `triaged`, and `bad_triage`,
counted within capacity; the waiver, which only a validated `done` `trivial` result writes, `unplanned` reads,
`canopy plan KEY` undoes, and `canopy forget` ends; the state block's `triage_due` and `waived`; `canopy show` naming
it; and the TRUST_MODEL lines. Until the open three are settled, a triage runs in no sandbox and a waiver sends no event
of its own. Then, 2026-10-19, the overseer prompt's triage row: `needs-plan` where `plan.triage_due` is true, before
any `plan`, and after a failed triage the plan at once, with no `wait`. Then, 2026-10-19, the reviewer's second
opinion: the harness raises `not_trivial` every tick about a unit whose PR any `done` review judged `high` while its
ticket's waiver is in force, naming the review and the triage's reason, with no change to the reviewer's prompt or
result. Then, 2026-10-19, the web UI's plan card, which shows a ticket's triage running, its waiver with the run
and its reason and, until the implement starts, Ask for a plan to undo it, or the triage that left the ticket to be
planned; and triage runs as a kind of their own in `canopy spend`, `canopy health`, and the spend page, with the plans
they waived. Then, 2026-10-19, `policy.trivial` made optional (the operator: a model can tell trivial work without
being told): the triage prompt carries its own measure, settled work with one reasonable way to do it, and the
operator's words, where set, take its place; `"on"` without them is no longer a config error. Left: the feedback half
(M54).
