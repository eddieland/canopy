# M60. Personas

REQUIREMENTS R24, DESIGN §31, §8, §12, §21, and §25, TRUST_MODEL T1, T5, T7, and T8, D040. Its per-ticket override was
to follow M58's; the operator had it built first (2026-10-21), and M58's model override can share its journal fact.
Asked for by the operator (2026-10-19): personas that give planning, reviews, or implementation a flair of their own,
with a default persona that holds canopy's standard personality. The operator settled four points the same day: only the
operator chooses a persona, from config and a per-ticket override; a persona changes voice and emphasis only, never a
guard, a contract, or a model; the default is canopy's voice taken out of the shipped prompts; and canopy ships a few
personas, which the operator adds to or shadows in a private directory.

- **Stage 0, canopy's voice found.** List every line of the shipped planner, reviewer, implement, and resume prompts,
  public and private, that sets voice or emphasis rather than a task, an obligation, or a contract, and record the list
  in the PR. Each line either moves to the `canopy` persona or stays, with the guard or contract that leans on it named:
  the reviewer's rules for a finding and its verdict stay, and so do the authorization check, the result line, and
  commit attribution. Nothing is built until the operator has read the list.
- **Stage 1, the default persona.** `.agents/personas/canopy.md`, bundled with the prompts. The prompts lose the lines
  Stage 0 moved and gain `{{PERSONA}}`, placed after the obligations with the line that they come first, as
  `{{STANDING_INSTRUCTIONS}}` is. Every run renders `canopy`, so live runs should read as they did before;
  `.agents/sizes.toml` records each prompt shrinking and the persona's own size.
- **Stage 2, chosen personas.** `paths.personas`, a private directory whose files shadow or add to the shipped set by
  name. `[personas]`, one persona name per agent, `worker` (implement and resume, public and private), `planner`, and
  `reviewer`, each `canopy` by default, private as every `paths` key is (T7). A file is bounded, as standing
  instructions are, and held to a lesson's bounds on hidden characters. `canopy personas` lists each persona, where it
  comes from, and the agents it is the default for.
- **The operator's override per ticket.** `canopy persona KEY NAME`, for the ticket's workers, `--agent planner` or
  `--agent reviewer` for its other agents, and `--clear`: a journal fact on the ticket and agent, as M58's model
  override is, which may be set before canopy has seen the ticket and covers every run of that agent for the ticket
  until it is cleared. It refuses `inside_run` and `unknown_persona`. `canopy dispatch` gets no persona flag.
- **The web UI's control.** On the ticket page, beside M58's Model panel: each of the ticket's agents' next persona and
  where it comes from, set or cleared through `canopy persona`'s function (T8). The run and review pages show the
  persona a run had.
- **Refused, not fallen back.** A run whose persona's file is gone refuses `persona_missing`, with an attention item of
  its name, no attempt spent and no slot leased. An override of a prompt without `{{PERSONA}}` serves runs whose
  persona is `canopy` and refuses any other as `bad_prompt`.
- **Recorded on the run.** A migration adds the persona's name and the digest of its text to `runs` and `review_runs`.
  `canopy status` and the web UI's run and review pages show it.
- **Shipped personas**, each a few paragraphs, proposed in the PR that adds them for the operator to keep, rename, or
  drop: `canopy`; `skeptic`, for a reviewer or a planner, which names the input that breaks a claim before accepting
  it; `minimalist`, for a worker, which keeps the diff and the PR's text as small as the ticket allows; and
  `explainer`, for a worker on a team's repository, whose PR says why as well as what, for coworkers new to the code.
- **Out of scope:** a persona for the overseer or a chore; a persona that names a model; a persona
  per repository in the shared map; the overseer or a ticket's labels choosing one; comparison reports beyond what each
  run records.
- **TRUST_MODEL**, in the PR that builds Stage 2: T1 (only the operator chooses a persona, and its text sits below the
  prompt's obligations, as the standing instructions do), T5 (each run records its persona), T7 (`paths.personas` and
  `[personas]` private), and T8 (the web UI's override write).
- Tests with the fakes: each agent's prompt rendering its persona after the obligations, a snapshot, for the shipped
  `canopy` and for an operator's file that shadows it; `[personas]` and `paths.personas` refused in the workspace file;
  an override reaching every run of its agent for the ticket until cleared, and no other agent's; `canopy persona`
  refusing `inside_run` and `unknown_persona`; a run whose persona's file was removed refused `persona_missing` with its
  attention item and no fallback; an override without `{{PERSONA}}` serving a `canopy` run and refused for another; a
  persona file past its bound or with hidden characters refused; the persona's name and digest on the run, in
  `canopy status` and the web API; the ticket page's control (Vitest and Playwright).

Accept: Stage 0's list read by the operator, before Stage 1 starts. Live, once built: a week of runs on `canopy` alone
reads as the runs before it did, with no rise in failed or refused runs in `canopy health`; the operator sets one
ticket's reviewer to `skeptic` and its worker to `minimalist` from its page, its review and PR read in those voices, and
both runs record them; the next ticket, with no override, runs `canopy`; and a persona file removed after it was set
refuses that ticket's next run with an attention item.

Status: in progress. Stage 0's list, in #996, was read and merged by the operator (2026-10-19). Stage 1 is built
(2026-10-20): `.agents/personas/canopy.md` holds the lines that list moved, and every planner, reviewer, and worker run
renders it as `{{PERSONA}}`, after the obligations. The plan and resume prompts shrank; the reviewer and implement
prompts grew by the persona's section, since they gave up only a sentence or a phrase. Stage 2 is built (2026-10-20):
`paths.personas` and `[personas]`, private; a persona file bounded at 4 KiB and refused with hidden characters; `canopy
personas`; a run whose persona has no file refused `persona_missing`, and one whose file is past its bounds
`bad_persona`, each with its attention item, no attempt spent and no slot leased; an override without `{{PERSONA}}`
serving `canopy` runs alone; each run's and review's persona and digest recorded, in `canopy status` and the web API;
and `skeptic`, `minimalist`, and `explainer` shipped, for the operator to keep, rename, or drop. A feedback plan takes
no persona, since its prompt carries none. The override per ticket is built (2026-10-21), ahead of M58 at the
operator's word: `canopy persona KEY NAME`, `--agent planner` or `reviewer`, and `--clear`, refused inside a run and
for a persona with no file, and the ticket page's control of it through the same function (T8). It is a row of
`ticket_overrides`, one table of the operator's choices per ticket, agent, and kind, whose `model` kind M58's override
per ticket can take without a migration. An override whose file has gone refuses the ticket's next run
`persona_missing`, never falling back to `[personas]`. The run and review pages show each run's persona and digest.
The operator's choice for one run is built (2026-10-21): `canopy persona KEY NAME --next`,
`canopy start KEY --persona`, and `canopy plan KEY --persona` choose the persona of a ticket's next worker or planner
run alone, spent by the dispatch that records it; `canopy start URL --review --persona`, given again for a review in
each, and `canopy persona URL` choose a review request's, in place of `[personas] reviewer`. The overseer's commands
take none, as §31 rejects.
The reviews page's request form chooses a request's personas, one review each, at the operator's word (2026-10-21).
Next: the live checks in Accept. Designed 2026-10-19 (DESIGN §31).
