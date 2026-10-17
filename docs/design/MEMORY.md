# Agent memory

Part of the canopy design, normative like all of it: what workers record of what they learn, who reads it, and who
decides. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [The overseer's
tools](OVERSEER_TOOLS.md).

## 28. Agent memory (M50)

ROADMAP M50. §7, §8, §12, §14, and §22 describe canopy with memory off; this section says what memory changes in each.
Off by default, and with it off nothing a run, a tick, or the overseer reads changes.

`{{PREVIOUS_RUNS}}` (§8) is ticket memory already, but it forgets by position, it is narrative, and a wrong conclusion
stays until it scrolls out; and workspace-wide only the operator writes text every run reads. Coding agents gain from
short, distilled, verified lessons and lose from raw history or memory that does not fit the task; they often skip
memory tools, so what must be seen is pushed into the prompt; and every memory-poisoning incident shipped so far had an
agent that read untrusted text write a store that later reached a broader context. So memory comes in two tiers, split
by who can make text reach another ticket:

- **Ticket notes**: keyed entries a ticket's runs write, read only by that ticket's later runs, as data. Their reach is
  their ticket's, as the reports in `{{PREVIOUS_RUNS}}` are.
- **Workspace lessons**: workers only propose them. A proposal reaches no prompt. The operator promotes one into a
  lesson, in their own words if they like, or rejects it, and may promote a ticket's note the same way; a lesson is
  the operator's text, beside the standing instructions, and only the operator retires it.

The overseer writes no memory and reads none: it reads every ticket's text every tick, and T1 refuses it the notice for
that reason, so a curator role would hand it the notice under another name. Nothing is added to the state block or
`prompts/overseer.md`, so the overseer's cached prefix (§6) stays as it is. Reviews, chores, and splits get neither
tier: a reviewer stays independent of the author's beliefs.

### Configuration

Private keys, in the user file or the private file (§12), never the workspace file:

```toml
[memory]
ticket_notes = "off"   # off | record | use
proposals = "off"      # off | record | use
```

- Each tier has its own key, since they carry different risk. `record` asks workers to write and serves nothing, so
  the operator can judge what a tier holds before any of it reaches a prompt; `use` writes and serves.
- Private, since `use` changes what agents may write into later prompts and `record` fills what `use` would serve
  (TRUST_MODEL T7).
- Turning a key down stops what its mode added and deletes nothing; `canopy memory purge --all` removes what a trial
  wrote. Turning `record` to `use` serves what was recorded with nothing approved again: the operator reads it first.
- A run keeps the modes its prompt was rendered under (§8, step 3), whatever the config says by the time it ends: its
  result is read under the modes the journal recorded for it.

### Off

With both keys off, `{{TICKET_MEMORY}}`, `{{WORKSPACE_LESSONS}}`, and `{{MEMORY_CONTRACT}}` render as the empty string,
placed so that every shipped prompt is the same bytes as before memory existed; an override without them still serves.
Memory's result fields are parsed apart from the result and never stored in `result_json`, so what a worker sends anyway
is stored nowhere. `canopy memory` says memory is off, the web UI shows no memory page or readout, no memory attention
item arises, and no run records a memory row. The one footprint is empty tables and an empty search index: migrations
are not conditional, and a second database file would cost a second schema lifecycle and the foreign keys to `runs` and
`tickets`.

### The contract

`{{MEMORY_CONTRACT}}` follows the result line of every `implement`, `fix-ci`, and `resume` prompt, public and private,
since the literal JSON line cannot carry fields that come and go with the config. It asks for each field only while
the tier that owns it allows it, so tiers at different modes need no rule of their own:

```json
{"notes":[{"key":"ci-flake","text":"..."}],"drop_notes":["old-key"],
 "proposals":[{"key":"bazel-cache","text":"...","repo":"api"}],"memory_used":[12],"memory_wrong":[9]}
```

- `notes` while ticket notes are not off; `drop_notes` only at `use`.
- `proposals` while proposals are not off.
- `memory_used` and `memory_wrong` while either tier is at `use`, citing only ids rendered into that run's prompt. A
  worker shown no memory has no key to drop and no id to cite.

The contract gives each entry a shape, so notes and proposals read the same from run to run, for the next worker and
for the operator who judges them. A note's key starts with its kind (`cause-`, `dead-end-`, `cmd-`, `env-`), so a later
run that learns more about the same thing reuses the key and supersedes the note, rather than writing a second one
beside it. Its text says what holds, the evidence a later run can check it by, and what to do next. The contract asks
for nothing the summary, the branch, or its commits already say, since those reach the next run anyway. A proposal
says what any worker should do, why, and when it applies, and only what the run itself showed and the repository's own
docs do not say. The harness checks none of this shape: a text that departs from it is held to the bounds alone.
Rejected: evidence and next step as fields of their own, each needing bounds, for what one line carries.

Every field is optional. A field the run's modes did not ask for changes nothing. Once a key is not off, a prompt
override without the placeholders its mode needs is `bad_prompt`, as for the standing instructions and the notice:
`{{MEMORY_CONTRACT}}` for a tier at `record`, and that tier's digest placeholder too at `use`.

### Writing

`_run` writes a run's memory in the transaction that closes it (§8, step 7), only from a valid result line, for the
run's own ticket, read from its journal row, never from the result, so no run writes another ticket's notes.

- A note under a key already in force supersedes it; nothing is edited in place, and the old note stays, superseded.
  Notes from runs that ended `failed` or `blocked` are kept: a dead end is what a retry most needs.
- `memory_wrong` retires a note it cites; on a lesson it only records the report, which raises `lesson_wrong`, since a
  lesson is the operator's word. `memory_used` renews what it cites, and pushes a lesson's review date out 90 days.
  `drop_notes` retires a shown note by key. Only memories rendered into the run's own prompt count, so a worker cannot
  renew or retire what it never saw.
- What a run had refused is recorded with it, in the harness's words, never the text, for the operator to read.

### Bounds

In code, at write, for a note and a proposal alike, and for a lesson's text at promotion. Each entry is refused alone,
never cut or cleaned, so one bad entry costs only itself.

- A key is lowercase words joined by hyphens, at most 40 characters, as a branch's slug is (§8). A note is at most 400
  characters and 5 a run; a proposal at most 600 and 3 a run, so one run cannot fill the queue.
- A text is one line of plain text. Every control, format, surrogate, private-use, unassigned, and line or paragraph
  separator character is refused, which takes in zero-width, bidi, and Unicode tag characters: each hides text from
  the operator that a model still reads.
- A text that looks like a secret is refused: a known credential's shape, or a long word of a base64 or URL-safe
  alphabet that mixes upper and lower case and digits, switches between them often, and repeats few characters.
  Hexadecimal words are never taken for one, since notes name commits.
- A text equal, once casefolded and its whitespace collapsed, to a note of the same ticket in force, or to a pending
  proposal or a lesson, is refused as a repeat.

### Ticket notes in prompts

At `use`, `{{TICKET_MEMORY}}` is in the `implement`, `fix-ci`, and `resume` prompts, public and private, beside
`{{PREVIOUS_RUNS}}`, and framed as it is: data to check against the branch and PR, kept off the tracker, the PRs, and
commit messages. Each note shows its id and key, the run that wrote it and how it ended, how many runs ago, and the head
it was written against, so a worker can judge whether it still holds. The section is capped at 3 KiB; past the cap the
least recently used are left out of the prompt, not the journal, and counted. A ticket with no note says so, since the
worker was told memory exists.

### Retention

- A ticket's notes are invalidated when it is marked done and on `canopy forget`, matching `{{PREVIOUS_RUNS}}`' "since
  any forget". `canopy stop` keeps them: a stopped ticket may be started again.
- A pending proposal nobody reviews expires 14 days after it was written, by the tick's reconcile (§6, step 3), in
  every mode.
- M47's pass (§26) deletes the text of notes and proposals no longer in force after `retention.memory_days`, keeping
  the row. A lesson never lapses: it is the operator's word.

### Proposals and lessons

- A pending proposal is rendered into no prompt, at any mode. At most 20 are pending: past it a new one is refused, so
  a flood cannot push older ones out.
- `canopy memory promote ID [--text TEXT] [--repo REPO]` makes a pending proposal a lesson in the operator's name,
  with their text if given, under the same bounds, for `REPO` if given; a lesson in force under its key is superseded.
  `canopy memory reject ID` ends a proposal. Both work at `record` as at `use`, so the operator can build the lessons up
  before any is served.
- `promote` takes a ticket's note too, whatever its status while it keeps its text, since what a ticket taught is
  often clearest once it is done and its notes invalidated. The note stays its ticket's, unchanged; its lesson is for
  every repository unless `--repo` names one, since a note names none. Promoting a note or a proposal from a private
  ticket's run in its own words warns that its text may hold what the operator kept off the tracker.
- At `use`, `{{WORKSPACE_LESSONS}}` is in every worker prompt that carries `{{STANDING_INSTRUCTIONS}}`, every kind but
  a split's (§8), beside them and framed as the operator's words that the prompt's obligations come before. Capped at
  2 KiB: past it the lessons longest since promoted, renewed, or used are left out and counted, and the rest render in
  key order, so with many lessons the ones the operator or a run last vouched for are served, not the first by name. A
  lesson naming a repository renders only in runs that lease it. A plan hears lessons but carries no contract, so it
  cites none.
- A lesson comes up for review 90 days after it was promoted or last used: the operator renews it
  (`canopy memory renew ID`), graduates it into a repository's AGENTS.md or a skill through a ticket and a PR they
  merge, or forgets it.

### Attention items

The harness raises three (§14), the operator's alone: they are harness reasons, so the overseer's view of the list
leaves them out and no tick spends a decision on them. None arises while `memory.proposals` is off.

- `memory_proposal`, about a ticket marked done whose runs' proposals wait, so the operator reviews lessons whose work a
  merge has checked.
- At `use` only, one `lesson_review` naming the lessons due, longest overdue first, and one `lesson_wrong` naming the
  lessons a run reported wrong since their last renewal. No run reads a lesson at `record`, so none is raised there;
  once the key is `use`, every lesson past its date comes up together at the first tick, in one item, the review the
  operator wants before an old lesson is served. An item names ten at most and counts the rest, so hundreds of lessons
  due still make one line.

### Search

The digests are capped, and a note that a later one under its key replaced leaves them, so `canopy memory search WORDS`
finds the rest by their words, best match first: SQLite's full-text index over each memory's key and text, ranked with
bm25(), a word in a key weighing more than one in a text. A query is read as words, never as the index's query syntax,
so nothing a worker types is an error. It adds to what is pushed into the prompt and replaces none of it.

- In a worker's run, which `CANOPY_RUN_ID` names, it finds only what that run's prompt could be served, each tier only
  while the journal says it was at `use` for the run: its ticket's notes in force and those they replaced, and the
  lessons for the repositories it leased. Never another ticket's notes, an invalidated note, or a pending proposal. A
  run that has ended finds nothing, a review or a chore no memory at all, and the overseer is refused, since it reads
  no memory.
- What it finds is framed as the digests frame it, a note as data to check and a lesson as the operator's word, both
  kept off the tracker and the PRs, with every hidden character named. It is not rendered into the prompt, so a run
  cites none of it in `memory_used` or `memory_wrong`.
- A digest names the command where it helps: the ticket's whenever it has notes, the lessons' when its cap left some
  out. A run told nothing of memory is told nothing of search, and with memory off every prompt stays the same bytes.
- In the operator's shell it finds every memory that still has its text, proposals and every ticket's notes included.
- The index holds no copy of a text: `forget` and `purge` leave no word of what they deleted in it. It needs SQLite
  built with FTS5, which every journal's migrations create and `make install-check` checks.
- T1 is unchanged: a run reaches its own ticket's notes and the lessons a run in its repositories is served. A steered
  worker that names another run's id reaches what its bash could read from the journal anyway (T1's residual, D076).

Rejected for search: embeddings, a runtime dependency and weakest on facts that changed, which is canopy's usual case;
and a search as the only way to read memory, since agents skip tools they are not made to use.

### Commands

`canopy memory` lists ticket notes (`list`), the proposals waiting with where each came from (`proposals`), and the
lessons with their review dates and reports (`lessons`), each after every tier's mode in words; `list` and `lessons`
also print the digest a run would get, labelled as served or as what `use` would serve. `promote`, `reject`, and `renew`
make and keep lessons. `search WORDS` finds memories by their words (Search). `forget ID` deletes one memory's text and
`purge` many (a ticket's runs', a run's, or all), leaving the rows; a forgotten lesson is retired. They delete with
`secure_delete` on and checkpoint the write-ahead log after, so a purged poison or a leaked secret does not survive in
free pages. Every one that writes refuses as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set, as `notice`
does (TRUST_MODEL T1). `canopy status` names each tier's mode while one is on.

### Showing memory

Wherever memory shows, the operator must never take recorded memory for memory in use, or the reverse: each tier's
mode is said in words, never by color alone, and the two modes never share a label. The web UI's header names whether
any memory is in use while a tier is on; its memory page, a ticket's page, and a run's page say for each tier what reads
it, what a run wrote and read, and what it would be served. The web UI reads memory and writes none: every write is the
CLI's, in the operator's shell. How it looks is `ui/DESIGN.md`'s.

A busy workspace holds thousands of notes and hundreds of lessons, so the memory page lists the tickets with notes in
force, one row each with its count, and reads a ticket's notes only when the operator opens its row; the lessons come
reported wrong first, then by review date, so what calls for the operator heads the list. Wherever a list shows a
memory in force that its digest's cap leaves out, its row says so, as left out of the prompt at `use` and as what would
be left out while recording.

What a worker wrote is shown as plain text, never Markdown or a link, unlike other journal text (D113): a link in a note
would be a worker's link the operator reads as canopy's. Every character the bounds refuse is shown by its code point,
in the CLI and the web UI alike, whatever was written to the journal by hand.

Rejected:

- A memory tool the worker calls in place of the digests: agents skip tools they are not made to use.
- Embeddings: see Search.
- Notes in `result_json`: `purge` could not reach them without rewriting every run's result.

### Trust model changes

Approved by the operator (2026-10-17), in the PRs that build each tier's `use`:

- T1, ticket notes: a worker may write notes its own ticket's later runs read as data, the same exposure as its reports
  in `{{PREVIOUS_RUNS}}`, with one new property: a note outlives the tracker comment that steered it, bounded by the
  ticket's life and by `forget`.
- T1, lessons: workspace memory is operator text; agents only propose it, and `promote` refuses in any run, like
  `notice`. The residual is D076's: until workers are sandboxed (M26), a steered worker's bash runs as the operator and
  could insert a lesson into the journal, as it could a notice.
- T7: `memory.*` is private.

### Open

- Agent-written workspace facts with code citations the harness checks at read. A citation proves the code exists, not
  that the advice about it is true, so it is a staleness control, not an integrity one.
- Whether promoted lessons and the standing-instructions file become one surface the operator edits.
- Whether a ticket reopened from `recently_done` gets its notes back.
- A chore that drafts proposals from transcripts, only if workers' own proposals prove too few.
- Whether the web UI should promote and reject, behind the web channel's token.
