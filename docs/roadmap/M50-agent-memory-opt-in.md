# M50. Agent memory, opt-in

DESIGN §8 (A fresh session per run, Notices to workers), §12, §26, TRUST_MODEL T1 and T7, D030, D076, D093. Sketch
only; the design comes first, as a new section of the design. Asked for by the operator (2026-10-16): workers record
what they learn, for later runs on the same ticket and, through the operator, for the whole workspace. No
REQUIREMENTS entry yet. Off by default, and with it off nothing a run, a tick, or the overseer reads changes. Writing
and reading are switched apart (the operator, 2026-10-16): a tier can record memories that no agent reads, and the
operator turns reading on once what was recorded has been judged. Four stages, in order, each in its own PRs, a stage
starting only once the one before has passed its last check (stages 1 and 2 have two, at `record` and then at `use`),
each check recorded on the `Status:` line as it passes.

- Why: `{{PREVIOUS_RUNS}}` is ticket memory already, but it forgets by position (the latest three runs), it is
  narrative, and a wrong conclusion stays until it scrolls out. Workspace-wide, only the operator writes text every run
  reads (the standing instructions, the notice). Research into shipping products and papers (2026-10-16): coding
  agents gain from short, distilled, verified lessons and lose from raw history or memory that does not fit the task;
  agents often skip memory tools, so what must be seen is pushed; and every memory-poisoning incident shipped so far
  (ChatGPT, Gemini, Windsurf, Claude Code) had an agent that read untrusted text writing a store that later reached a
  broader context.
- Two tiers, split by who can make text reach another ticket. **Ticket notes**: keyed entries a ticket's runs write,
  read only by that ticket's later runs, as data. **Workspace lessons**: workers only *propose* them; a proposal
  reaches no prompt until the operator promotes it, and a promoted lesson is the operator's text, beside the standing
  instructions. The overseer writes no memory and reads none: it reads every ticket's text every tick, and T1 refuses
  it the notice for that reason, so making it a curator would hand the notice back under another name.
- Opt-in: `[memory]` with `ticket_notes` and `proposals`, each `"off"` (the default), `"record"`, or `"use"`, separate
  because the tiers carry different risk. `record` writes and serves nothing; `use` writes and serves. Private keys
  (M49): the user file or the private file, never the workspace file, since `use` changes what agents may write into
  later prompts, and `record` fills what `use` would serve (T7). With both off:
  - `{{TICKET_MEMORY}}`, `{{WORKSPACE_LESSONS}}`, and `{{MEMORY_CONTRACT}}` (the result fields below, which the
    literal JSON line of each worker prompt cannot carry) render as the empty string, not `None.`, so every prompt is
    the same bytes as before and no worker is told to write anything.
  - An override without the placeholders still serves. Once a key is not off, an override without the placeholders
    its mode needs is `bad_prompt`, as for the standing instructions and the notice.
  - `WorkerResult` already ignores unknown fields; `notes` or `proposals` a worker sends anyway are stored nowhere.
  - The state block and `prompts/overseer.md` are unchanged. No stage adds anything to either, so the overseer's
    cached prefix and every operator's system prompt stay as they are.
  - `canopy memory ...` is in `COMMANDS`, imported only when it runs, and says memory is off. The web UI shows no
    memory page. No memory attention item can arise.
  - The one footprint is an empty `memories` table: migrations are not conditional, and a second database file
    would cost a second schema lifecycle and the foreign keys to `runs` and `tickets`.
  - Turning a key down stops what its mode added: `use` to `record` stops rendering, `record` to `off` stops writes
    too. Retention keeps running, so what a trial wrote ages out on its own; `canopy memory purge --all` removes it at
    once.
- Recording, at `record`: workers write and no agent reads, so the operator can fill a tier and judge what it holds
  before any of it reaches a prompt.
  - `{{MEMORY_CONTRACT}}` asks for each field only while the tier that owns it allows it, so tiers at different modes
    need no rule of their own: `notes` while ticket notes are not off, and `drop_notes` only while they are at `use`;
    `proposals` while proposals are not off; `memory_used` and `memory_wrong` while either tier is at `use`, citing
    only ids a tier at `use` rendered. A worker shown no memory has no key to drop and no id to cite. An override needs
    `{{MEMORY_CONTRACT}}` for a tier at `record`, and that tier's digest placeholder too at `use`.
  - `{{TICKET_MEMORY}}` and `{{WORKSPACE_LESSONS}}` render as the empty string, as when off, so no worker is told a
    memory exists.
  - Everything on the write side runs as at `use`: the bounds, superseding by key (a worker writing a key it never saw
    supersedes the note under it; the old row stays, `superseded`), retention, proposals and promotion. The digest `use`
    would render is built the same way and shown to the operator, never to an agent, so what turning on would serve is
    seen before it is served.
  - The journal keeps, for each worker run, the mode of each tier its prompt was rendered under and the ids rendered
    into it. A run that read nothing because the tier was recording is told apart from one whose digest was empty,
    whatever the config says later.
  - Turning `record` to `use` serves what was recorded, with nothing approved again: the operator reads it first, and
    `forget` or `purge` removes what should not be served. `use` with no spell at `record` is allowed, but each stage
    below runs its tier at `record`, and passes a check there, before its check at `use`.
  - TRUST_MODEL: at `record`, what a worker writes reaches only the operator, as its report does, so T1 changes only
    with a stage's `use` half.
- Flagged wherever memory shows, so the operator never takes recorded memory for memory in use, or the reverse. In
  words, never by color alone, and the two modes never share a label. With both tiers off none of it shows.
  - The web UI's header carries a memory readout beside the latest tick while a tier is not off: `memory: recording`
    while none is used, `memory: in use` once one is, each tier's mode on hover and to a screen reader
    (`ticket notes: recording, lessons: off`), linking to the memory page.
  - The memory page, a web UI page this milestone adds, heads each tier with a band saying what reads it: for ticket
    notes, `Recording only. Workers write these notes; no run reads them.`, or `In use. A ticket's later runs read its
    notes.` A recorded entry's row says `read by no run`; a used one, its use count and last use. The digest the next
    run would get is shown under its band, labelled `would be served at use` while recording.
  - A ticket's page has a Memory panel with the same band. A run's page lists the notes it wrote and the ones it read:
    `none, recording only` for a run rendered at `record`, `none` for one whose digest was empty.
  - `canopy memory list` and `canopy memory proposals` print the tier's mode in words first; `canopy status` prints a
    `memory:` line while a tier is not off.
  - What a worker wrote is shown as plain text, never markdown or a link, with zero-width, bidi, and control
    characters made visible, in the CLI and the web UI alike.
  - The band's and the readout's look are `ui/DESIGN.md`'s, recorded in the PR that builds them. If M41's allowlist
    ever names these keys, it takes a tier down only (`use` to `record`, `record` to `off`), never up.
- Code: a features package, `memory/`, and `cli/memory.py`, with its layer in `tests/canopy/test_layers.py`, and the
  web UI's memory page and readout. Deleting the feature deletes those, its reconcile step, and its prompt part (§5).

**Stage 0, measure.** Nothing is built.

- From the operator's run transcripts, a dated section of `MEASUREMENTS.md`: the share of `fix-ci` and `resume` runs,
  and of second and later `implement` runs, that end `blocked` or `failed` or spend steps finding again what an earlier
  run on the ticket found. That is §8's own condition for revisiting fresh sessions, and the baseline stage 1 is held
  to.
- Check: written down. If such runs are rare, the operator decides whether the rest is still worth building.

**Stage 1, ticket notes.** Behind `memory.ticket_notes`, at `record` first, then at `use`.

- A migration adds `memories`: scope (`ticket`, `proposal`, `lesson`), ticket, optional repository, key, body,
  status (`active`, `pending`, `superseded`, `invalid`) and why, author (`worker`, `operator`), the run and tick that
  wrote it, the branch head it was written against, `supersedes`, `promoted_from`, created, approved, last used, use
  count, review date, and invalidated. One active row per scope, ticket, and key. It adds too what each worker run
  was rendered under: each tier's mode and the ids rendered. Their row types in `core/records.py`, their vocabularies
  (the modes among them) in `core/vocab.py`, `CHECK` constraints, and their hashes and seed rows in
  `tests/canopy/core/test_db.py`. Built whole in this stage, so stage 2 adds no migration.
- A worker's result gains `notes` (`{key, text}`, text at most 400 characters) and `drop_notes` (keys). `_run`
  validates them and writes them for the run's own ticket, read from its journal row, never from the result, so no run
  writes another ticket's notes. A note under an active key supersedes it; nothing is edited in place. A body equal,
  once normalized, to an active one in the same scope is refused. Notes from runs that ended `failed` or `blocked` are
  kept: a dead end is what a retry most needs.
- Bounds in code, at write: control, zero-width, and bidi characters refused, not stripped; a regex and entropy scan
  refuses a note that looks like a secret; at most 5 notes a run.
- At `use`, `{{TICKET_MEMORY}}` in `implement`, `fix-ci`, and `resume` prompts, public and private, beside
  `{{PREVIOUS_RUNS}}` and framed as it is: data to check against the branch and PR, kept off the tracker and PRs. Each
  note in key order, with its id, the run that wrote it (kind and outcome), how many runs ago, and the head it was
  written against. Capped at 3 KiB; past the cap, the least recently used are left out of the prompt, not the journal,
  and the section says how many. Reviews, chores, and splits get none: a reviewer stays independent of the author's
  beliefs.
- At `use`, the result gains `memory_used` and `memory_wrong`, lists of ids. Only ids rendered into that run's prompt
  count, so a worker cannot renew or retire a note it never saw. A used note gets its last use and count; a wrong one is
  invalidated.
- Retention: a ticket's notes are invalidated when it is marked done and on `canopy forget`, matching
  `{{PREVIOUS_RUNS}}`' "since any forget"; `canopy stop` keeps them. M47's pass deletes invalidated rows after
  `retention.memory_days` (30), leaving a tombstone without the body. Where M47 is not built yet, nothing is deleted.
- `canopy memory list [REF]`, `canopy memory forget ID`, and `canopy memory purge --ticket REF | --run ID | --all`:
  forget and purge delete the body with `PRAGMA secure_delete` on, so a purged poison or a leaked secret does not
  survive in free pages. All three that write refuse as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set.
- The surfaces above, for ticket notes: the header's readout, the memory page and its bands, the ticket's Memory panel,
  the run's lists, and the CLI's lines, built with the `record` half, since that is when the operator most needs them.
- TRUST_MODEL T1, with the `use` half: a worker may write notes its own ticket's later runs read as data, the same
  exposure as its reports in `{{PREVIOUS_RUNS}}`, with one new property: a note outlives the tracker comment that
  steered it, bounded by the ticket's life and by `forget`.
- Tests with the fakes: with `memory` unset, every worker prompt kind and the state block match their snapshots before
  this milestone, and a result carrying `notes` stores nothing. At `record`: a note is stored and is in no prompt of any
  kind; each prompt kind differs from its snapshot when off only by the contract, which asks for `notes` alone;
  `memory_used`, `memory_wrong`, and `drop_notes` a worker sends anyway change nothing; the run's mode is journaled with
  no ids; the readout, bands, and run lists say recording, and a recorded note holding markdown, a link, or (written to
  the journal by hand, past the bounds) zero-width and bidi characters shows as plain text with those characters
  visible, in `canopy memory list` and on the memory, ticket, and run pages (Vitest, and Playwright against the mock
  journal). At `use`: a note reaches the same ticket's next run and no other ticket's; a note recorded at `record` is
  served once the key is `use`; a key supersedes; a run cannot write or retire another ticket's note; an id never
  rendered is ignored; a secret-like or bidi body is refused; the digest's cap and its count; done and forget
  invalidate; an override without a placeholder its mode needs is `bad_prompt` only once the key is not off; purge
  leaves no body in the file.
- Check, recording: a week of the operator's loop at `record`, a dated section of `MEASUREMENTS.md`: notes per run,
  bytes per note, the share of runs that wrote none, and the operator's reading of a sample of digests, the share of
  notes that would have helped the run that got them, would have misled it, or held what should not be stored. If
  they would mostly mislead, the contract is reworked and recorded again before `use`.
- Check, in use: a week at `use`, against stage 0's baseline and the recording week: the same share of runs, attempts
  per ticket, and steps per run, with the `memory_used` and `memory_wrong` rates, a dated section of
  `MEASUREMENTS.md`. The recording week is the control for being asked to write: its runs wrote notes and read none,
  so what moves past it is reading's doing. If notes do not move the baseline, the milestone stops here.

**Stage 2, proposals and lessons.** Behind `memory.proposals`, at `record` first, then at `use`, which needs the
operator's approval.

- A worker's result gains `proposals` (`{key, text, repo?}`, text at most 600 characters), stored `pending` under the
  same bounds. **A pending proposal is rendered into no prompt.** At most 20 pending per workspace, refusing new ones
  past it so a flood cannot push older ones out; one is invalidated 14 days after it is written if nobody reviews it.
  When its source ticket is marked done, the harness raises `memory_proposal`, so the operator reviews lessons whose
  work a merge has checked.
- `canopy memory proposals` lists each with its provenance (ticket, private or not, run, kind, outcome, whether its PR
  merged), its text with zero-width, bidi, and control characters made visible, and a warning on one from a private
  ticket. `canopy memory promote ID [--text TEXT]` copies it into a new row the operator authored; `reject ID` ends
  it. Both refuse as `inside_run`. At `record` both work as at `use`, so the operator can build the lessons up before
  any is served; `promote` says the lesson is recorded, not served.
- At `use`, `{{WORKSPACE_LESSONS}}` in every worker prompt that carries `{{STANDING_INSTRUCTIONS}}`, under its own
  heading beside them, framed as the operator's words after the prompt's obligations. Capped at 2 KiB, in key order,
  with the count left out past the cap. A lesson naming a repository renders only in runs that lease it.
- A lesson in `memory_used` has its review date pushed out 90 days. At the review date the harness raises
  `lesson_review`: renew, graduate into the repository's AGENTS.md or a skill through a ticket and a PR the operator
  merges, or drop it. A lesson never lapses on its own: it is the operator's word. `memory_wrong` on a lesson raises
  `lesson_wrong`; only the operator retires it. At `record` no `lesson_review` is raised, since no run can use a
  lesson; once the key is `use`, those approved more than 90 days before come up for review at the first tick, the
  review the operator wants before an old lesson is served anyway, as one `lesson_review` item naming them all, not one
  each, so the switch raises no burst.
- The surfaces above, for proposals and lessons, beside ticket notes'.
- TRUST_MODEL T1: workspace memory is operator text; agents only propose it, and `promote` refuses in any run, like
  `notice`. The residual is D076's: until workers are sandboxed (M26), a steered worker's bash runs as the operator
  and could insert a `lesson` row, as it could a `notices` row.
- Tests with the fakes: with `memory.proposals` off, a result carrying `proposals` stores nothing and no prompt changes;
  at `record`, a proposal is stored, a promoted lesson is in no prompt of any kind, no `lesson_review` is raised, and
  the surfaces say recording; with ticket notes at `use` and proposals at `record`, the contract asks for `memory_used`
  and `memory_wrong` citing notes alone, and a lesson id in them changes nothing; the switch to `use` raises one
  `lesson_review` for every lesson past its date; at `use`, a pending proposal is in no prompt of any kind; promote and
  reject refuse with `CANOPY_RUN_ID` set; the cap refuses the 21st; expiry at 14 days; `memory_proposal` at done; a
  promoted lesson reaches every worker prompt and no review or chore; `lesson_review` at the review date and its push on
  use; a lesson for one repository stays out of another's runs.
- Check, recording: a month of the operator's loop at `record`: proposals a week, the share promoted, edited at
  promotion, rejected, and expired, and the median time to review, a dated section of `MEASUREMENTS.md`.
- Check, in use: two weeks at `use`: the `memory_used` and `memory_wrong` rates on lessons and what each
  `lesson_review` and `lesson_wrong` ended in, a dated section of `MEASUREMENTS.md`.

**Stage 3, search.** Only if stage 1 or 2's check shows digests left out entries often.

- `canopy memory search QUERY` over an FTS5 table ranked with `bm25()`, scoped by `CANOPY_RUN_ID` to the run's ticket
  and the promoted lessons, each only while its tier is at `use`, reaching superseded notes and what the caps left out.
  No embeddings: they would be a runtime dependency, and they are weakest on facts that changed, which is canopy's usual
  case.
- `make install-check` checks that the installed Python's SQLite has FTS5.

Open:

- Agent-written workspace facts with code citations the harness checks at read (GitHub Copilot's shape). A citation
  proves the code exists, not that the advice about it is true ("this test is flaky; skip it" cites a real test), so
  it is a staleness control, not an integrity one, and such facts are the ones grep finds cheaply. Worth a TRUST_MODEL
  change only if stage 2 shows the operator promoting many cited, mechanical proposals almost unchanged.
- Whether promoted lessons and the standing-instructions file become one surface the operator edits.
- Whether a ticket reopened from `recently_done` gets its notes back.
- A chore that drafts proposals from transcripts, as Codex and Gemini CLI do, only if workers' own proposals prove
  too few.

Status: in progress. Designed 2026-10-17 (DESIGN §28). Stage 0 waived by the operator (2026-10-17), who asked for
stages 1 and 2 to be built together, each tier off until they turn it on; their checks, at `record` and then at `use`,
are still the operator's. Built: `[memory]`, migration 0037's tables and their row types, the prompts' placeholders
(every prompt the same bytes with memory off, held by snapshots recorded before them), and `canopy memory` and the
status line saying which tier records. Ticket notes at `record` (stage 1's first half): the contract, `_run` writing a
run's notes under the bounds with what it refused, superseding by key, done and forget invalidating, and
`canopy memory list`, `forget`, and `purge`. Ticket notes at `use` (its second half): each implement, fix-ci, and
resume prompt served its ticket's digest, `memory_used`, `memory_wrong`, and `drop_notes` on what it was shown, an
override without `{{TICKET_MEMORY}}` refused, and TRUST_MODEL T1's ticket notes, approved by the operator (2026-10-17).
Proposals and lessons (stage 2), at `record` and `use`: proposals under the bounds and the queue's 20, their expiry,
`memory_proposal`, `promote`, `reject`, and `renew`, `{{WORKSPACE_LESSONS}}` in every prompt that carries the standing
instructions, review dates, `lesson_review` and `lesson_wrong`, and T1's lessons, approved by the operator (2026-10-17).
The web API's memory routes, read only, and each tier's mode on the loop's state; the web UI's readout, memory page
with each tier's band, a ticket's Memory panel, and a run's lists, every worker's text plain with hidden characters
named. Search (stage 3), built at the operator's word (2026-10-17) before any check had shown the digests leave entries
out: `canopy memory search` over an FTS5 index of every memory (migration 0038) ranked with bm25(), scoped by
`CANOPY_RUN_ID` to the run's ticket's notes, superseded ones included, and its repositories' lessons, each while at
`use` for the run, the digests naming it, `forget` and `purge` clearing the index too, and `make install-check`
checking FTS5. Memory at density (asked for by the operator, 2026-10-17): the lessons digest keeps the lessons last
promoted, renewed, or used rather than the first by key, `lesson_review` and `lesson_wrong` name ten and count the rest,
an index on scope and status (migration 0039), and the memory page lists tickets with notes in force, opening each to
its notes, with every list scrolling in its panel and a memory its digest leaves out saying so. Where memory was used
(asked for by the operator, 2026-10-18): each run's citations journaled per memory (migration 0044), a memory naming
the latest runs that relied on it, and a run's page marking what it relied on and found wrong. Every stage's checks, at
`record` and at `use`, are still the operator's.
