# Epics

An epic is work that spans several tickets, toward one goal you write in your own words. canopy plans the whole
once, you approve that plan once, and each ticket you make a member is then planned against it, so its planner stops
settling the shared questions again and you stop approving them again.

## An epic, a ticket, and a task

- **A ticket** is one piece of work in the tracker, planned and built on its own. See [Tickets](tickets).
- **A task** is one-off work in your words, about no ticket, run once in one repository. See [Tasks](tasks).
- **An epic** is the plan over several tickets: the goal, the requirements it traces to your words, the contracts
  between the tickets, and a breakdown of which tickets to file. It writes no code and files nothing on its own.

Like a task, an epic is yours alone. Your text is the instruction and your submitting it authorizes its plan runs; the
overseer never sees it, and its conversation never touches the tracker. The word is canopy's: an epic in Jira or
GitHub is a [tracker epic](glossary#tracker-epic), and it never becomes one of canopy's by itself.

## Submitting one

From the shell, for now:

```sh
canopy epic submit "Let customers export their invoices as CSV, from the API and the web app." \
    --repo api --repo web
```

Name each repository its plan reads with `--repo`, and the tracker project its tickets belong in with `--project KEY`.
The next tick starts its plan run, before the overseer, within `capacity.max_workers`.

## Its plan

A planner reads the epic's repositories and writes one plan, in an outline that does not change: the goal; each
requirement `R1`, `R2`, ... traced to your words; each contract `C1`, ... between the tickets, with who provides it
and who uses it; the breakdown, each entry `B1`, ... with the requirements it covers, the contracts it provides and
uses, its repositories, and what it comes after; its decisions; and what is out of scope. It is shallow on purpose:
no ticket's steps, which each ticket's own plan writes just before it is built.

The ids are the one part of the plan canopy reads, and they never change meaning, so a later plan can say what it
changed by id. You approve the plan with `canopy plan epic:N --approve`, or ask for changes with
`canopy reply epic:N "TEXT"`, and the next tick plans again with your reply. Its plan runs count against
`policy.max_plan_attempts` and are never reset, so a planner that can't land one stops rather than burning the budget
on its fortieth try.

## Its members

A member is a ticket you add to the epic, usually one you filed for an entry of the approved plan:

```sh
canopy epic add epic:2 ABC-140 --entry B1
```

Name the entries it fulfils with `--entry`, once for each, or `--no-entry` for one the breakdown didn't foresee.
`canopy epic remove epic:2 ABC-140` takes it out again. A ticket is a member of one epic at most, and an epic holds
`policy.max_epic_tickets` at most. Being a member authorizes no work: a member is worked once you label it or start
it, like any other ticket, and then its planner reads the epic's approved plan beside its own ticket.

## The list

[Epics](/epics) lists every epic you submitted, the newest first. Each row leads with where the epic stands, in the
color a run in that state wears:

- `queued`, muted: the next tick starts its plan run.
- `planning`: its plan run is working.
- `waiting on you`: its plan is proposed. Approve it, or reply with what to change.
- `approved`: you approved its plan, and its breakdown is what's left to file.
- `unplanned`, in the failure color: its plan runs ended without a plan, and none starts again until you reply. Once
  `policy.max_plan_attempts` is used up, a reply starts none either.

Hover the word for its spelling in the CLI and what it means. Then come `epic:N`, its repositories, your goal's first
line, how many of its breakdown's entries have a member (`2 of 4 entries filed`; `no breakdown` before it has a plan,
and `breakdown unreadable` for a plan canopy can't read: its file is gone, or its ids repeat or won't parse), and how
long ago you submitted it.

From the shell, `canopy epic list` lists them and `canopy show epic:N` prints one, its breakdown with each entry's
members.
