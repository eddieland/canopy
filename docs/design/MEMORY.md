# Agent memory

Part of the canopy design, normative like all of it: what workers and reviewers record of what they learn, who reads
it, and who decides. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[The overseer's tools](OVERSEER_TOOLS.md). Next: [Review replies](REVIEW_REPLIES.md).

## 28. Agent memory

§7, §8, §12, §14, and §22 describe canopy with memory off; this section says what memory changes in each. Off by
default, and with it off nothing a run, a tick, or the overseer reads changes. TRUST_MODEL T1, T7, and T8 hold what it
lets the loop do.

Agents gain from short, verified lessons, not raw history; they skip memory tools, so what must be seen is pushed into
the prompt; and memory is poisoned when an agent that read untrusted text writes a store a broader context reads. So
memory comes in tiers, split by who can make text reach another ticket, and by whom it reaches:

- **Ticket notes**: keyed entries a ticket's runs write, read only by that ticket's later runs, as data.
- **Workspace lessons**: workers only propose them, and a proposal reaches no prompt. A lesson is the operator's text,
  promoted from a proposal or a note, beside the standing instructions, and only the operator retires it.
- **Review notes**: keyed entries a review of one of the loop's own PRs writes, read only by its ticket's later
  reviews, as data: what was checked and how, a suspicion disproved, code to read closely at the next commit.

The overseer writes no memory and reads none, since it reads every ticket's text (T1). Chores get none. A review hears
only review notes, and no worker reads them, so neither the author nor its reviewer carries the other's beliefs; a
review of a PR with no ticket gets none.

Each tier has its own private key (§12, T7), since the tiers carry different risk: `off`, `record`, or `use`. `record`
writes and serves nothing, so the operator can judge a tier before it reaches a prompt; `use` writes and serves, what
was recorded too. Turning a key down deletes nothing. A run keeps the modes its prompt was rendered under (§8, step 3).
With every tier off, each shipped prompt is as before memory existed, and what an agent sends of it is stored nowhere.

### The contract

The `implement` and `resume` prompts ask, after the result line, for each optional memory field only while its tier
allows it: `notes` and `proposals` while their tier is not off; `drop_notes`, `memory_used`, and `memory_wrong` at
`use`. A prompt override that lacks what its mode needs is refused. At `use` they carry the ticket's notes, capped,
framed as its previous runs are: data to check against the branch, kept off the tracker, the PRs, and commits. The
reviewer's prompt asks for `review_notes`, and at `use` carries the ticket's review notes and asks for
`drop_review_notes`: data that does not narrow the review, so a defect still goes in its findings.

### Writing

A run's memory is written in the transaction that closes it (§8, step 7), only from a valid result line, and only for
the run's own ticket as its journal row names it, so no run writes another ticket's notes; a review's notes likewise.
Memory is never stored with the result, so `purge` can reach it. A new note under a key supersedes the old, and notes
from failed or blocked runs are kept: a dead end is what a retry most needs. A report of a note wrong retires it; of a
lesson, it only records the report. Only memories rendered into the run's own prompt count, so a worker cannot renew or
retire what it never saw. What a run had refused is recorded in the harness's words, never its text.

### Bounds

Enforced in code at write, and for a lesson's text at promotion. Each entry is refused alone, never cut or cleaned, so
one bad entry costs only itself. Texts and their number a run are bounded, so one run cannot fill the queue. A text is
one line of plain text, with no character that can hide text from the operator while a model still reads it. A text
that looks like a secret is refused (a hexadecimal word never does, since notes name commits), and so is one that
repeats a note in force, a pending proposal, or a lesson.

### Retention

A ticket's notes and review notes are invalidated when it is marked done and on `canopy forget`, as its previous runs
are; `canopy stop` keeps them, since a stopped ticket may start again. A pending proposal nobody reviews expires (§6,
step 3). §26's pass deletes the text of notes and proposals no longer in force, keeping the row; a lesson, and each
version an edit replaced, keeps its text until the operator forgets it.

### Proposals and lessons

- Past a cap on pending proposals a new one is refused, so a flood cannot push older ones out.
- The operator promotes a proposal or a note into a lesson, under the same bounds, or rejects a proposal; both work at
  `record`. Promoting a private ticket's run's own words warns that they may hold what was kept off the tracker.
- An edit writes a lesson anew, the old words kept as history and served to no run. Rejected: an edit in place, which
  would leave a run's citations naming words it never read.
- At `use`, lessons are in every worker prompt that carries the standing instructions (§8), framed as the operator's
  words that the prompt's obligations come before; capped, and a lesson naming a repository only in runs that lease it.
- A lesson unused for a while comes up for review: the operator renews it, graduates it into a repository's AGENTS.md
  or a skill through a PR they merge, or forgets it.
- The attention items (§14), none while proposals are off: `memory_proposal` once a ticket is done, so proposals are
  judged after a merge checked the work, and at `use`, `lesson_review` and `lesson_wrong`.

### Search

`canopy memory search` finds memories by their words, past what the digests' caps leave out, and replaces none of
them. In a worker's run it finds only what that run's prompt could be served: its ticket's notes and its leased
repositories' lessons, each tier only at `use`. An ended run finds nothing, a review or a chore no memory, and the
overseer is refused. The operator finds every memory that keeps its text; the index holds no copy of one. It is the one
`canopy` command the worker definitions allow (§13); a sandboxed worker's policy denies the journal (§24). A steered
worker that searches as another run reaches no more than its bash could read anyway (D076), so the definitions' rules
are defense in depth (T4). Rejected: embeddings, weakest on facts that changed.

### Commands

`canopy memory` lists every tier with its mode, and its verbs make, keep, and forget memories. `forget` and `purge`,
which reach review notes too, delete text, leaving no copy in free pages, so a purged poison or leaked secret is gone.
Every verb that writes refuses inside a tick or a run (T1).

The web UI takes every verb but `purge` through the same functions and guards, as the web channel (§22, T8). A promote
that would replace a lesson in force or publish a private ticket's run's own words is never one click. Forget shows on
a ticket's notes even with proposals off, so a leaked secret can leave from where the operator sees it (operator's
decision, 2026-10-18). Recorded memory never reads as memory in use, and a worker's text shows as plain text, never
Markdown or a link (D113), every character the bounds refuse named.

### Open

- Whether promoted lessons and the standing-instructions file become one surface the operator edits.
- A chore that drafts proposals from transcripts, only if workers' own proposals prove too few.
- Review notes on the web UI's pages; until then only `canopy memory review-notes` shows them.
