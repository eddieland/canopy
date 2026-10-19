# Agent memory

Part of the canopy design, normative like all of it: what workers record of what they learn, who reads it, and who
decides. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [The overseer's
tools](OVERSEER_TOOLS.md). Next: [Review replies](REVIEW_REPLIES.md).

## 28. Agent memory

§7, §8, §12, §14, and §22 describe canopy with memory off; this section says what memory changes in each. Off by
default, and with it off nothing a run, a tick, or the overseer reads changes.

Agents gain from short, verified lessons, not raw history; they skip memory tools, so what must be seen is pushed into
the prompt; and memory is poisoned when an agent that read untrusted text writes a store a broader context reads. So
memory comes in two tiers, split by who can make text reach another ticket:

- **Ticket notes**: keyed entries a ticket's runs write, read only by that ticket's later runs, as data. Their reach is
  their ticket's, as the reports in `{{PREVIOUS_RUNS}}` are.
- **Workspace lessons**: workers only propose them, and a proposal reaches no prompt. The operator promotes one into a
  lesson, in their own words if they like, or rejects it, and may promote a ticket's note the same way; a lesson is
  the operator's text, beside the standing instructions, and only the operator retires it.

The overseer writes no memory and reads none, since it reads every ticket's text (T1), and its cached prefix (§6)
stays as it is. Reviews, chores, and splits get neither tier: a reviewer stays independent of the author's beliefs.

### Configuration

`memory.ticket_notes` and `memory.proposals`, each `off`, `record`, or `use`, are private (§12, TRUST_MODEL T7), since
they change what agents may write into later prompts; one key a tier, since the tiers carry different risk. `record`
asks workers to write and serves nothing, so the operator can judge a tier before any of it reaches a prompt; `use`
writes and serves, including what was recorded, with nothing approved again. Turning a key down deletes nothing. A run
keeps the modes its prompt was rendered under (§8, step 3), and its result is read under them. With both off, every
shipped prompt is the same bytes as before memory existed, and what a worker sends of memory is stored nowhere.

### The contract

`{{MEMORY_CONTRACT}}` follows the result line of every `implement` and `resume` prompt and asks for each field only
while its tier allows it: `notes` while ticket notes are not off, and `drop_notes` at `use`; `proposals` while
proposals are not off; `memory_used` and `memory_wrong` while either tier is at `use`. Every field is optional. Once a
key is not off, a prompt override without the placeholders its mode needs is `bad_prompt`, as for the notice. A note
holds only what is true of its ticket alone, under a key that starts with its kind, so a later run that learns more
supersedes it; the harness checks the bounds, not this shape.

At `use`, `{{TICKET_MEMORY}}` sits beside `{{PREVIOUS_RUNS}}` in the `implement` and `resume` prompts, framed as it is:
data to check against the branch and PR, kept off the tracker, the PRs, and commit messages, each note with the head
it was written against. It is capped; what the cap leaves out stays in the journal.

### Writing

`_run` writes a run's memory in the transaction that closes it (§8, step 7), only from a valid result line, and only
for the run's own ticket as its journal row names it, never the result, so no run writes another ticket's notes.
Memory's fields are never stored with the result, so `purge` can reach them.

- Nothing is edited in place: a note under a key in force supersedes it. Notes from runs that ended `failed` or
  `blocked` are kept: a dead end is what a retry most needs.
- `memory_wrong` retires a note; on a lesson it only records the report, since a lesson is the operator's word.
  `memory_used` renews what it cites, and `drop_notes` retires a note. Only memories rendered into the run's own prompt
  count, so a worker cannot renew or retire what it never saw.
- What a run had refused is recorded in the harness's words, never the text.

### Bounds

Enforced in code at write, for notes and proposals, and for a lesson's text at promotion. Each entry is refused alone,
never cut or cleaned, so one bad entry costs only itself.

- A key is a slug, as a branch's is (§8). Each text, and how many of each a run may write, is bounded, so one run
  cannot fill the queue.
- A text is one line of plain text. Every control, format, surrogate, private-use, unassigned, and line or paragraph
  separator character is refused: each can hide text from the operator that a model still reads.
- A text that looks like a secret, a known credential's shape or a long random-looking word, is refused. Hexadecimal
  words are never taken for one, since notes name commits.
- A text that repeats a note of its ticket in force, a pending proposal, or a lesson is refused.

### Retention

- A ticket's notes are invalidated when it is marked done and on `canopy forget`, as `{{PREVIOUS_RUNS}}` is. `canopy
  stop` keeps them: a stopped ticket may be started again.
- A pending proposal nobody reviews expires 14 days after it was written (§6, step 3), in every mode.
- §26's pass deletes the text of notes and proposals no longer in force after `retention.memory_days`, keeping the row.
  A lesson, and each version an edit replaced, keeps its text until the operator forgets it.

### Proposals and lessons

- A pending proposal is rendered into no prompt. Past a cap on those pending a new one is refused, so a flood cannot
  push older ones out.
- `canopy memory promote` makes a pending proposal, or a ticket's note, a lesson in the operator's name, in their words
  if given, under the same bounds, for one repository or every one; it supersedes a lesson in force under its key.
  `reject` ends a proposal. Both work at `record`, so lessons can be built up before any is served. Promoting a private
  ticket's run's own words warns that they may hold what the operator kept off the tracker.
- `canopy memory edit` writes a lesson anew in the operator's name: the old words stay as its history, served to no run
  and found by none, and the new version is due for review afresh with reports of it wrong cleared. `history` lists a
  memory's versions. Rejected: an edit in place, which would leave a run's citations naming words it never read.
- At `use`, `{{WORKSPACE_LESSONS}}` is in every worker prompt that carries `{{STANDING_INSTRUCTIONS}}`, every kind but
  a split's (§8), framed as the operator's words that the prompt's obligations come before. It is capped, serving
  those last vouched for first; a lesson naming a repository renders only in runs that lease it. A plan hears lessons
  but carries no contract, so it cites none.
- A lesson comes up for review 90 days after it was promoted or last used: the operator renews it, graduates it into a
  repository's AGENTS.md or a skill through a PR they merge, or forgets it.

### Attention items

The harness raises three (§14), the operator's alone, none while `memory.proposals` is off: `memory_proposal`, for a
done ticket whose runs' proposals wait, so lessons are judged once a merge checked the work; and at `use` only,
`lesson_review` for the lessons due and `lesson_wrong` for those a run reported wrong.

### Search

`canopy memory search WORDS` finds memories by their words, past what the digests' caps leave out; a query is never
read as query syntax. It adds to what is pushed into the prompt and replaces none of it.

- In a worker's run it finds only what that run's prompt could be served, each tier only while it was at `use` for the
  run: its ticket's notes, in force or replaced, and the lessons for the repositories it leased; never another ticket's
  notes, an invalidated note, or a pending proposal. An ended run finds nothing, a review or a chore no memory, and the
  overseer is refused. What it finds is framed as the digests are, and is not cited in `memory_used` or `memory_wrong`.
- In the operator's shell and the web UI it finds every memory that keeps its text. The index holds no copy of a text,
  so `forget` and `purge` leave nothing in it.
- It is the one `canopy` command the worker definitions allow (§13); a sandboxed worker's policy denies the journal
  (§24). T1 is unchanged: a steered worker that searches as another run or as the operator reaches no more than its
  bash could read from the journal anyway (D076); the definitions' rules are defense in depth (T4).

Rejected: embeddings, a runtime dependency and weakest on facts that changed; and search, or a memory tool, in place
of the digests, since agents skip tools they are not made to use.

### Commands

`canopy memory` lists ticket notes, the proposals waiting, and the lessons, after every tier's mode in words, with the
digest a run would get. `promote`, `reject`, `renew`, `edit`, and `history` make and keep lessons; `forget` deletes one
memory's text and `purge` many, keeping the rows and leaving no copy in free pages, so a purged poison or a leaked
secret is gone. Every one that writes refuses inside a tick or a run, as `notice` does (TRUST_MODEL T1).

The web UI takes every verb but `purge`, a verb over many memories, through the same functions and guards, logged
with channel `web` (§22). A promote that would replace a lesson in force, or publish a private ticket's run's own
words, is never one click, and a forget carries the memory's ref typed out. Forget shows on a ticket's notes even with `memory.proposals`
off, so a leaked secret can leave from where the operator sees it (operator's decision, 2026-10-18).

### Showing memory

The operator must never take recorded memory for memory in use, or the reverse: each tier's mode is said in words,
never by color alone, and the two modes never share a label. Wherever memory shows, what reads each tier, and what a
run wrote, read, relied on, and reported wrong, are said; how it looks is `ui/DESIGN.md`'s. What a worker wrote is
shown as plain text, never Markdown or a link (D113), since a link in a note would read as canopy's, and every
character the bounds refuse is shown by its code point.

### Trust model changes

Approved by the operator (2026-10-17, and in merging the PRs that added the web UI's verbs and `edit`):

- T1: a ticket's notes reach only its own later runs, as data, but outlive the tracker comment that steered them, until
  the ticket ends or `forget`. Lessons are operator text: `promote` and `edit` refuse in any run, with D076's residual.
- T7: `memory.*` is private. T8: the web channel's verbs go through the CLI's functions; a stolen session could make a
  lesson that reaches every worker at `use`, as a notice could, until the operator forgets it.

### Open

- Agent-written workspace facts with code citations the harness checks at read. A citation proves the code exists, not
  that the advice about it is true, so it is a staleness control, not an integrity one.
- Whether promoted lessons and the standing-instructions file become one surface the operator edits.
- Whether a ticket reopened from `recently_done` gets its notes back.
- A chore that drafts proposals from transcripts, only if workers' own proposals prove too few.
