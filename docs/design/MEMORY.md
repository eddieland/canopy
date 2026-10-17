# Agent memory

Part of the canopy design, normative like all of it: what workers record of what they learn, who reads it, and who
decides. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [The overseer's
tools](OVERSEER_TOOLS.md).

## 28. Agent memory (M50)

Designed, and built in stages (ROADMAP M50). §7, §8, §11, §12, §14, and §22 describe canopy with memory off; this
section says what memory changes in each, and the TRUST_MODEL changes it needs are at its end. Off by default, and
with it off nothing a run, a tick, or the overseer reads changes.

Asked for by the operator (2026-10-16): workers record what they learn, for later runs on the same ticket and, through
the operator, for the whole workspace. The operator waived stage 0's baseline (2026-10-17) and asked for stages 1 and 2
to be built together, each tier still off until they turn it on.

### Why

- `{{PREVIOUS_RUNS}}` (§8) is ticket memory already, but it forgets by position (the latest three runs), it is
  narrative, and a wrong conclusion stays until it scrolls out. A note is keyed: a later run replaces it, drops it, or
  says it was wrong, and it lasts as long as the ticket's work does.
- Workspace-wide, only the operator writes text every run reads: the standing instructions (§12) and the notice (§8).
  A lesson a worker learned on one ticket that every worker should know reaches them only if the operator copies it
  there by hand.
- Research into shipping products and papers (2026-10-16): coding agents gain from short, distilled, verified lessons
  and lose from raw history or memory that does not fit the task; agents often skip memory tools, so what must be seen
  is pushed into the prompt, not fetched; and every memory-poisoning incident shipped so far (ChatGPT, Gemini,
  Windsurf, Claude Code) had an agent that read untrusted text write a store that later reached a broader context.

### Two tiers

Split by who can make text reach another ticket.

- **Ticket notes**: keyed entries a ticket's runs write, read only by that ticket's later runs, as data. Their reach is
  their own ticket's, the same as the reports in `{{PREVIOUS_RUNS}}`.
- **Workspace lessons**: workers only *propose* them. A proposal reaches no prompt; it waits for the operator, who
  promotes it into a lesson, edits it as they promote it, or rejects it. A promoted lesson is the operator's text,
  beside the standing instructions, and only the operator retires it.

The overseer writes no memory and reads none. It reads every ticket's text every tick, and T1 refuses it the notice
for that reason: making it a curator of what every worker reads would hand it the notice under another name. No stage
adds anything to the state block or `prompts/overseer.md`, so the overseer's cached prefix (§6) and every operator's
system prompt stay as they are.

Reviews, chores, and splits get neither tier. A reviewer stays independent of the author's beliefs, a chore is not a
ticket's run, and a split reads and writes the ticket and builds nothing.

### Configuration

Private keys, in the user file or the private file (§12, M49), never the workspace file:

```toml
[memory]
ticket_notes = "off"   # off | record | use
proposals = "off"      # off | record | use
```

- Each tier has its own key, since they carry different risk. `off`, the default, is canopy without it. `record`
  writes and serves nothing: workers are asked to write, and no agent reads what they wrote. `use` writes and serves.
- Private, not shared: `use` changes what agents may write into later prompts, and `record` fills what `use` would
  serve (TRUST_MODEL T7). A workspace file that sets either is a config error, as for every private key.
- Turning a key down stops what its mode added: `use` to `record` stops rendering, `record` to `off` stops writes too.
  Nothing is deleted by it: retention keeps running, so what a trial wrote ages out on its own, and
  `canopy memory purge --all` removes it at once.
- Turning `record` to `use` serves what was recorded, with nothing approved again: the operator reads it first, and
  `forget` or `purge` removes what should not be served. `use` with no spell at `record` is allowed, but each stage of
  M50 runs its tier at `record`, and passes a check there, before its check at `use`.
- The prompt is rendered at dispatch (§8), so a run keeps the modes its prompt was rendered under, whatever the config
  says by the time it ends: its result is read under the modes the journal recorded for it (below), never the config's.

### Off

With both keys off:

- `{{TICKET_MEMORY}}`, `{{WORKSPACE_LESSONS}}`, and `{{MEMORY_CONTRACT}}` render as the empty string, not `None.`.
  Each sits at the end of a line in the shipped prompts and its value starts with the blank line before its heading,
  so every prompt is the same bytes as before memory existed, and no worker is told to write anything.
- A prompt override without the placeholders still serves. Once a key is not off, an override without the placeholders
  its mode needs is `bad_prompt` (Prompt overrides, below), as for the standing instructions and the notice.
- `WorkerResult` ignores unknown fields, and memory's fields are parsed apart from it (Writing, below), so `notes` or
  `proposals` a worker sends anyway are stored nowhere: not in `memories`, and not in `result_json`, in any mode.
- The state block and `prompts/overseer.md` are unchanged.
- `canopy memory` is in `COMMANDS`, imported only when it runs, and its listing commands say memory is off. `forget`
  and `purge` still work, since they only remove. The web UI shows no memory page and no readout. No memory attention
  item arises.
- The one footprint is empty tables: migrations are not conditional, and a second database file would cost a second
  schema lifecycle and the foreign keys to `runs` and `tickets`. A run dispatched with both off has no `run_memory`
  row, so the journal holds nothing of memory at all.

### Recording

At `record`, workers write and no agent reads, so the operator can fill a tier and judge what it holds before any of it
reaches a prompt.

- `{{MEMORY_CONTRACT}}` asks for each result field only while the tier that owns it allows it, so tiers at different
  modes need no rule of their own: `notes` while ticket notes are not off, and `drop_notes` only while they are at
  `use`; `proposals` while proposals are not off; `memory_used` and `memory_wrong` while either tier is at `use`,
  citing only ids a tier at `use` rendered. A worker shown no memory has no key to drop and no id to cite.
- `{{TICKET_MEMORY}}` and `{{WORKSPACE_LESSONS}}` render as the empty string at `record`, as when off, so no worker is
  told a memory exists.
- Everything on the write side runs as at `use`: the bounds, superseding by key, retention, proposals, and promotion.
  A worker writing a key it never saw supersedes the note under it; the old row stays, `superseded`. The digest `use`
  would render is built the same way and shown to the operator, never to an agent, so what turning a tier on would
  serve is seen before it is served.
- What a worker sends that its run's modes did not ask for changes nothing: `memory_used`, `memory_wrong`, and
  `drop_notes` from a run rendered with no tier at `use`, `proposals` from a run rendered with proposals off.
- At `record`, what a worker writes reaches only the operator, as its report does, so T1 changes only with a tier's
  `use`.

### The journal

Migration 0037 adds three tables, built whole in stage 1, so stage 2 adds no migration. Each status and mode column is
constrained with `CHECK (column IN (...))`, their vocabularies are `StrEnum`s in `core/vocab.py`, and their row types
are in `core/records.py`.

- `memories`: one row per note, proposal, or lesson.
  - `scope`: `ticket` (a note), `proposal`, or `lesson`. `author`: `worker` for a note or a proposal, `operator` for a
    lesson, and the table holds the two together.
  - `ticket_key`: a note's ticket, a proposal's source ticket, and NULL for a lesson. `repo`: the repository a
    proposal or lesson names, NULL for one about every repository, and always NULL for a note.
  - `key` and `body`. The key is lowercase words joined by hyphens, at most 40 characters, as a slug is (§8). `body`
    is NULL once the row is forgotten or purged, leaving a tombstone that keeps its provenance.
  - `status`: `active` (a note or lesson in force), `pending` (a proposal waiting on the operator), `superseded`, or
    `invalid`, with `why`, the harness's words for the change (`superseded by note 41`, `dropped by run 52`,
    `wrong, says run 53`, `ticket done`, `forgotten`, `promoted to lesson 7`, `rejected`, `expired`, `purged`).
  - The run and tick that wrote it (NULL for a lesson), and `head`: the commit the run's branch was at when its worker
    ended, as `repo@sha` per repository for a joint run, NULL when no git ran after it.
  - `supersedes`: the row this one replaced under its key. `promoted_from`: a lesson's proposal.
  - `created_at`, `approved_at` (a lesson's promotion), `last_used_at` and `use_count` (from `memory_used`),
    `review_at` (a lesson's next review), `invalidated_at`, and `wrong_at` and `wrong_run_id` (a lesson's latest
    `memory_wrong`, cleared by a renewal).
  - One active row per scope, ticket, and key: a partial unique index over `(scope, ifnull(ticket_key, ''), key)`
    where `status = 'active'`.
- `run_memory`: one row per run of a kind a tier reaches (`implement`, `fix-ci`, `resume`, and `plan`) dispatched
  while either tier was not off, in the transaction that inserts the run: the mode of each tier its prompt was
  rendered under (`ticket_notes`, `proposals`; `off` for a tier that does not reach its kind, such as ticket notes in
  a plan), and the entries `_run` refused from its result, as JSON (Bounds, below). A run with no row was rendered
  with both off. A run that read nothing because its tier was recording is told apart from one whose digest was
  empty, whatever the config says later.
- `memory_reads`: one row per run and memory rendered into its prompt. Only these ids count in that run's
  `memory_used` and `memory_wrong`, and only the keys of these notes in its `drop_notes`.

`runs.result_json` never holds memory's fields: the notes, proposals, and citations live in these tables alone, so
`purge` reaches every copy the journal has. The run's log keeps the worker's whole output, its result line included,
as it keeps every transcript; that file is M47's (§26).

The migration's hash joins `SHIPPED`, and a row for each table joins `SEED`, in `tests/canopy/test_db.py`.

### Writing

A worker's result gains five fields, beside the contract's own (§8):

```json
{"notes":[{"key":"ci-flake","text":"..."}],"drop_notes":["old-key"],
 "proposals":[{"key":"bazel-cache","text":"...","repo":"api"}],"memory_used":[12],"memory_wrong":[9]}
```

`_run` parses them from the same last line as the result (`core/memory.py`'s own model, which ignores every other
field), only when that line is a valid result, so a run that left no result writes nothing. It writes them in the
transaction that closes the run (§8 step 7), for the run's own ticket, read from its journal row, never from the result,
so no run writes another ticket's notes. What it writes depends on the modes in the run's `run_memory` row; a run with
none writes nothing. In order:

1. `memory_wrong`, while either tier was at `use`: of the ids rendered into the run's prompt, a note is invalidated
   (`wrong, says run N`); a lesson is not, since it is the operator's word, but gets `wrong_at` and the run, which
   raises `lesson_wrong` (below). Any other id is ignored.
2. `memory_used`, likewise: each rendered id not reported wrong gets its `last_used_at` and one more `use_count`, and a
   lesson's `review_at` is pushed out to 90 days from now if it was sooner.
3. `drop_notes`, while ticket notes were at `use`: each active note under a key rendered into the prompt is
   invalidated (`dropped by run N`).
4. `notes`, while ticket notes were not off: at most 5 a run, each `{key, text}`, text at most 400 characters. A note
   under an active key supersedes it; nothing is edited in place. A body equal, once normalized (casefolded, its
   whitespace collapsed), to an active note of the same ticket is refused as a repeat.
5. `proposals`, while proposals were not off: at most 3 a run, so one run cannot fill the queue, each
   `{key, text, repo?}`, text at most 600 characters, stored `pending` (Proposals and lessons, below). `repo`, if
   given, must be a repository the run worked in. A body equal, once normalized, to a pending proposal or an active
   lesson is refused.

Notes from runs that ended `failed` or `blocked` are kept: a dead end is what a retry most needs.

### Bounds

In code, at write, for a note and a proposal alike, and for a lesson's text at promotion:

- A key that is not a slug, a text that is blank or over its limit, and an entry past the run's count are refused.
- Control, format, and separator characters are refused, not stripped: every character of Unicode's categories `Cc`,
  `Cf`, `Cs`, `Co`, `Cn`, `Zl`, and `Zp`. That takes in zero-width and bidi characters and Unicode's tag characters,
  each a way to hide text from the operator that a model still reads. A note is one line of plain text.
- A note that looks like a secret is refused: a known token's shape (a private key's header, an AWS key id, a GitHub,
  GitLab, Slack, or OpenAI-style token, a JWT, `password=`, `api_key=`, `secret=`, or `token=` and a value, a
  `Bearer` header), or a word of at least 20 characters that mixes upper and lower case and digits with a Shannon
  entropy of at least 4.2 bits a character. Hexadecimal words, such as commit ids, are not scanned for entropy: notes
  name commits.

A refused entry is logged and recorded in its run's `run_memory.refused` with the field, the key if it had a valid one,
and the reason in the harness's words, never the text. The run's page and `canopy memory list --run` show them.

### Ticket notes, at `use`

`{{TICKET_MEMORY}}` is in the `implement`, `fix-ci`, and `resume` prompts, public and private, beside
`{{PREVIOUS_RUNS}}` (`{{CONVERSATION}}` in a private prompt), and framed as it is: data to check against the branch
and PR, kept off the tracker, the PRs, and commit messages. Under its own heading, each active note of the ticket in
key order, with its id and key, the run that wrote it (its kind and how it ended), how many of the ticket's runs have
started since, and the head it was written against, then its text as a quote. Its last line asks for `drop_notes`,
`memory_used`, and `memory_wrong` by those ids.

The section is capped at 3 KiB of UTF-8. Past the cap, the least recently used notes (by `last_used_at`, or when they
were written if never used) are left out of the prompt, not the journal, and the section says how many. With no
active note it says there are none, rather than rendering empty: the worker was told memory exists, so it is told this
ticket has none yet. The ids rendered go to `memory_reads`.

At `record` the digest is built the same way for the operator's view, labelled `would be served at use`, and nothing is
recorded in `memory_reads`.

### Retention

- A ticket's active notes are invalidated when it is marked done (`ticket done`) and on `canopy forget` (`forgotten
  work`), matching `{{PREVIOUS_RUNS}}`' "since any forget". `canopy stop` keeps them: a stopped ticket may be started
  again.
- A pending proposal is invalidated 14 days after it is written if nobody reviews it (`expired`), by the tick's
  reconcile (§6 step 3), in every mode, off included.
- M47's pass (§26) deletes invalidated and superseded rows after `retention.memory_days`, 30 by default, leaving a
  tombstone without the body, and never a lesson's own row. Until M47 is built nothing is deleted, and `forget` and
  `purge` are the operator's ways to remove a body.

### Proposals and lessons

- A pending proposal is rendered into no prompt, at any mode. At most 20 are pending per workspace: past it, a new one
  is refused (`queue full`), so a flood cannot push older ones out.
- When a pending proposal's source ticket is marked done, the harness raises `memory_proposal` about that ticket
  (§14), naming its pending proposals, every tick while any is pending, so the operator reviews lessons whose work a
  merge has checked. The item names them by id; their text is on the memory page and in `canopy memory proposals`.
- `canopy memory promote ID [--text TEXT]` copies a pending proposal into a new `lesson` row the operator authored,
  `approved_at` now and `review_at` 90 days on, with the proposal's key and repository; `--text` replaces its text,
  under the same bounds. A lesson already active under the key is superseded by it. The proposal becomes `superseded`,
  `promoted to lesson N`. `canopy memory reject ID` makes it `invalid`, `rejected`. At `record` both work as at `use`,
  so the operator can build the lessons up before any is served; `promote` then says the lesson is recorded, not
  served.
- At `use`, `{{WORKSPACE_LESSONS}}` is in every worker prompt that carries `{{STANDING_INSTRUCTIONS}}` (every kind but
  a split, §8), under its own heading beside them, framed as the operator's words that the prompt's obligations come
  before. Capped at 2 KiB of UTF-8, in key order; past the cap the rest are left out and counted. A lesson naming a
  repository renders only in runs that lease it. Plans hear lessons but carry no memory contract, so they cite none.
- A lesson in `memory_used` has its `review_at` pushed out to 90 days on. At the review date the harness raises
  `lesson_review`, one item naming every lesson due: the operator renews it (`canopy memory renew ID`), graduates it
  into the repository's AGENTS.md or a skill through a ticket and a PR they merge, then forgets it, or forgets it. A
  lesson never lapses on its own: it is the operator's word.
- `memory_wrong` on a lesson raises `lesson_wrong`, one item naming every lesson a run has reported wrong since its
  last renewal, with the run. Only the operator retires a lesson; `renew` clears the report.
- At `record` no `lesson_review` or `lesson_wrong` is raised, since no run can use a lesson. Once the key is `use`,
  every lesson approved more than 90 days before is due at the first tick, the review the operator wants before an old
  lesson is served anyway, as one item naming them all, so the switch raises no burst.
- `memory_proposal`, `lesson_review`, and `lesson_wrong` are harness reasons (`attention.HARNESS_REASONS`), raised only
  while `memory.proposals` is not off. They are the operator's alone: the overseer's view of the attention list
  (§6 step 4) leaves them out, so the state block stays as it is and no tick spends a decision on them.

### The contract

`{{MEMORY_CONTRACT}}` follows the result line in `implement`, `fix-ci`, and `resume` prompts, public and private,
since the literal JSON line cannot carry fields that come and go with the config. It names each field its run may send
(Recording, above) with its bounds, says they go in the same one JSON object, and says what each is for:

- a note: what this ticket's next run would otherwise have to find again, such as a cause found, a dead end, or a
  command that works here; never ticket, PR, or log text copied in, and never a secret;
- a proposal: a lesson every later run in the workspace should know, which the operator reads and may promote;
- `memory_used` and `memory_wrong`: the ids of what was shown above that the run relied on, or found wrong.

Every field is optional, and the contract says an empty list is better than a note that would not help.

### Prompt overrides

An override written before memory existed serves while both keys are off. Once a key is not off, a prompt for a kind
the key reaches must carry what its mode needs, or the dispatch is `bad_prompt`:

- `{{MEMORY_CONTRACT}}`, in an `implement`, `fix-ci`, or `resume` prompt, while either key is not off;
- `{{TICKET_MEMORY}}` too, in the same kinds, while ticket notes are at `use`;
- `{{WORKSPACE_LESSONS}}`, in every prompt that carries `{{STANDING_INSTRUCTIONS}}`, while proposals are at `use`.

### Commands

`cli/memory.py`, its command `canopy memory`:

- `canopy memory list [REF] [--all] [--run ID] [--digest]`: each tier's mode in words first, then the ticket notes of
  REF, or of every ticket: id, key, status, the run that wrote it, when, and its use (`read by no run`, or its use
  count and last use), then its text. `--all` includes superseded and invalid rows, `--run` the rows a run wrote and
  the entries it had refused, and `--digest` the digest REF's next run would get, under `would be served at use` while
  recording.
- `canopy memory proposals`: the mode in words, then each pending proposal with its provenance: ticket, private or
  not, run, kind, outcome, and whether its PR merged as far as the journal knows (the ticket marked done), its text,
  and a warning on one from a private ticket, whose text may hold what the operator kept off the tracker.
- `canopy memory lessons [--repo NAME] [--digest]`: the mode, each active lesson with its review date, its use, and
  any `memory_wrong` report, and with `--digest`, what a run in NAME would be served.
- `canopy memory promote ID [--text TEXT]`, `reject ID`, `renew ID`: as above. They refuse as `off` while
  `memory.proposals` is off.
- `canopy memory forget ID`: deletes one row's body, a note's, a proposal's, or a lesson's, leaving its tombstone.
- `canopy memory purge --ticket REF | --run ID | --all`: deletes the bodies of every note and proposal of the ticket's
  runs, of the run, or, with `--all`, of every row, lessons included.
- `forget` and `purge` run with `PRAGMA secure_delete` on and then `PRAGMA wal_checkpoint(TRUNCATE)`, so a purged
  poison or a leaked secret does not survive in free pages or the write-ahead log; a checkpoint a reader holds back is
  reported, and the next one completes it.
- Every command that writes refuses as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set, as `notice` does
  (TRUST_MODEL T1).
- `canopy status` prints a `memory:` line while a tier is not off, each tier's mode in words, after the notice.

The listing commands print what a worker wrote as plain text with every refused character of Bounds made visible
(`<U+200B>`), whatever was written to the journal by hand past the bounds.

### Showing memory

Flagged wherever memory shows, so the operator never takes recorded memory for memory in use, or the reverse. In words,
never by color alone, and the two modes never share a label. With both tiers off none of it shows.

- The web UI's header carries a memory readout beside the latest tick while a tier is not off: `memory: recording`
  while no tier is at `use`, `memory: in use` once one is, with each tier's mode on hover and to a screen reader
  (`ticket notes: recording, lessons: off`), linking to the memory page.
- The memory page heads each tier with a band saying what reads it. For ticket notes, `Recording only. Workers write
  these notes; no run reads them.` or `In use. A ticket's later runs read its notes.`; for lessons, `Recording only.
  Workers propose lessons and you may promote them; no run reads them.` or `In use. Every worker reads the lessons you
  promoted.` A recorded entry's row says `read by no run`; a used one, its use count and last use. Under each band,
  the digest the next run would get, labelled `would be served at use` while recording. Then the pending proposals with
  their provenance, and the lessons.
- A ticket's page has a Memory panel with the same band, its notes, and its digest. A run's page lists the notes it
  wrote and the ones it read: `none, recording only` for a run rendered at `record`, `none` for one whose digest was
  empty, and the entries it had refused.
- What a worker wrote is shown as plain text, never Markdown or a link, unlike other journal text (D113): a link in a
  note would be a worker's link the operator reads as canopy's. Zero-width, bidi, and control characters are made
  visible, in the CLI and the web UI alike.
- The web UI reads memory and writes none: promoting, rejecting, renewing, forgetting, and purging are the CLI's, in
  the operator's shell, until a milestone puts them behind the web channel's token (T8).
- The band's and the readout's look are `ui/DESIGN.md`'s, recorded in the PR that builds them. If M41's allowlist ever
  names these keys, it takes a tier down only (`use` to `record`, `record` to `off`), never up.

### Where the code goes

- `core/memory.py`: the modes, the result's memory fields and their bounds, writing a run's memory in the transaction
  that closes it, the digests, `{{MEMORY_CONTRACT}}`, and what a run's prompt was rendered under. Core, since
  dispatch and `_run` write it and the web UI and the CLI read it, and features never import each other (§5).
- `memory/`, a features package: the operator's verbs (`forget`, `purge`, `promote`, `reject`, `renew`), the tick's
  reconcile step (expiring proposals), and the attention items the harness raises.
- `cli/memory.py`, the web UI's memory routes and models in `serve/`, and the memory page and readout in `ui/`.

Deleting the feature deletes those, its reconcile step, its attention items, and its prompt part (§5).

### Rejected

- The overseer as curator: it reads every ticket's untrusted text every tick (above).
- A memory tool the worker calls to read: agents skip tools they are not made to use, so what a run must see is
  rendered into its prompt. Stage 3's search, if it comes, is for what the caps left out.
- Embeddings: a runtime dependency, and weakest on facts that changed, which is canopy's usual case.
- A second database file: a second schema lifecycle, and no foreign keys to `runs` and `tickets`.
- Notes in `result_json`: `purge` could not reach them without rewriting every run's result.

### Trust model changes

Proposed, for the operator's approval note in the PRs that build each tier's `use`:

- T1, ticket notes: a worker may write notes its own ticket's later runs read as data, the same exposure as its reports
  in `{{PREVIOUS_RUNS}}`, with one new property: a note outlives the tracker comment that steered it, bounded by the
  ticket's life and by `forget`. Only the run's own ticket, read from its row, is written; only ids rendered into a
  run's prompt are renewed or retired by it; and the bounds keep hidden text and secrets out.
- T1, lessons: workspace memory is operator text. Agents only propose it, a proposal reaches no prompt, and `promote`
  refuses in any run, like `notice`. The residual is D076's: until workers are sandboxed (M26), a steered worker's bash
  runs as the operator and could insert a `lesson` row, as it could a `notices` row.
- T7: `memory.*` is private.

### Open

- Agent-written workspace facts with code citations the harness checks at read (GitHub Copilot's shape). A citation
  proves the code exists, not that the advice about it is true, so it is a staleness control, not an integrity one.
  Worth a TRUST_MODEL change only if stage 2 shows the operator promoting many cited, mechanical proposals unchanged.
- Whether promoted lessons and the standing-instructions file become one surface the operator edits.
- Whether a ticket reopened from `recently_done` gets its notes back.
- A chore that drafts proposals from transcripts, only if workers' own proposals prove too few.
- Whether the web UI should promote and reject, behind the web channel's token.
