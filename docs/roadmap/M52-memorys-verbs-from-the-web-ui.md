# M52. Memory's verbs from the web UI

DESIGN §22 and §28, TRUST_MODEL T8. Needs M50. Asked for by the operator (2026-10-17): promote a proposal or a
ticket's note to a lesson, reject a proposal, renew a lesson, and forget a memory from the page that shows it, without
a shell. Today the web UI reads memory and writes none, and T8's list of web writes leaves memory out.

- Each write is the function its `canopy memory` verb calls (`promote`, `reject`, `renew`, `forget`), with its guards;
  a refusal names its guard as the CLI does, and an outcome says what the CLI says: a lesson promoted while proposals
  are at `record` is recorded and served to no run. Logged with channel `web`.
- Those functions are in `canopy.memory.manage`, a feature `serve` may not import (DESIGN §5). The build moves
  `manage` down into `core`, as the verbs both channels call already are (`core/notice.py`, `core/plans.py`); it
  imports only `core` now, so nothing else moves. DESIGN §5's line for `memory/` drops the operator's verbs.
- Promote takes the CLI's options: the lesson's text, starting as the source's own and held to the same bound, and its
  repository, the proposal's or every one for a note. Before the save the form says which lesson in force under the key
  it would supersede, and, while the text is still a private ticket's run's own words, the warning `promote` gives.
- Forget cannot be undone, so it asks for the memory's ref typed out (`memory:42`), as a ticket's Forget asks for its
  key, checked in code. It retires a lesson as it drops a note or a proposal: the body goes, the tombstone stays.
- Where: the memory page, Promote and Reject on each proposal, Renew and Forget on each lesson; a ticket's Memory panel,
  Promote on each note that keeps its text, done or invalidated included (PR #687's case); the attention list,
  Promote as written and Reject on a `memory_proposal`, Renew on each lesson a `lesson_review` names, and a link to the
  lessons from a `lesson_wrong`. With `memory.proposals` off, none shows. The lists change over the event stream.
- TRUST_MODEL T8: the web channel gains those four verbs. Its residual gains that a stolen session could make a lesson
  that reaches every worker at `use`, as a notice set that way does, and outlives a new secret until the operator
  forgets it. DESIGN §28 drops "the web UI reads memory and writes none"; §22 gains the routes. The guide's memory page
  and `ui/DESIGN.md`'s pattern for the promote form follow.
- Tests with the fakes: each verb through the API, and each refused with `CANOPY_RUN_ID` set, on an unknown id, on a
  proposal no longer pending, on a note whose text is gone, on text past the bound, and with proposals off; Forget
  refused without the ref typed exactly; Vitest for the forms, Playwright for promoting from the memory and ticket
  pages.
- Settled (2026-10-18): the form asks the server when it opens, reading the memory overview, which gains the
  workspace's repositories, rather than every ticket's memory carrying the lessons in force.

Accept: the tests above pass. Live: with proposals at `record`, the operator promotes a done ticket's note in their own
words from its page and rejects a proposal from the attention list; `canopy memory lessons` shows the lesson, named as
from that note, and `canopy memory proposals` no longer lists the rejected one.

Status: in progress. Built 2026-10-18, its tests passing: `canopy.core.memory_manage`, which the CLI's repository check
and private-run warning moved into with it; the four verbs under `/api/memory/{id}`; the forms on the memory page, a
ticket's Memory panel, and the attention list's three items; T8, DESIGN §22 and §28, `ui/DESIGN.md`, and the guide.
The live check is the operator's.
