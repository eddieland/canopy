# M72. Search across every session the runtime keeps

DESIGN §11, §12, §13, §22, §24, §26, and §28, TRUST_MODEL T1, T3, T4, T6, T7, and T8, D009, D026, D053, D125. Asked for
by the operator (2026-11-10): they have many sessions, canopy's and their own, that they want to point to or get back
to later, and finding one is very hard among the sessions canopy makes; they would like a full-text index across all
of them, if that is feasible.

Every tick's overseer run, and every worker, planner, reviewer, chore, and task run, is a session in the runtime's
record: an unsandboxed run's in the operator's own, beside the sessions they ran by hand, and a sandboxed role's in a
record of its own (§24). canopy already reads that record for spend (§13), every session in every directory,
read-only, and keeps each one's cost, tokens, directory, and parent: no title, and nothing of what it said. To find a
session today the operator has a run's session id, on its page and in `canopy status`, and a search over the journal's
text that reads no transcript (§22). A run's log is removed after `retention.run_files_days` (§26), and a session
outside canopy never had one.

## What the runtime keeps of a session

Read 2026-11-10 from the build npm ships, `@opencode/cli-linux-x64` 2.1.4, not run.

- One database holds every project's sessions. A session's row has its title, its directory, its agent, the session
  it ran for, and when it was archived. Its messages are rows of one type each: what it was sent, what the agent wrote,
  its reasoning and its tool calls, each call with its input and what it returned, a compaction's summary, and a shell
  command with its output.
- The runtime's own search is a `LIKE` on a session's title, and its list command shows one project's top-level
  sessions (§13). Nothing searches what a session said, and its database has no full-text index.
- Its list can leave archived sessions out. canopy archives none: it writes nothing to the runtime's data (§26).
- OpenCode 1's tables are still beside OpenCode 2's, with whatever sessions 1 left in them.

So an index is feasible: the text is in one place, which canopy already reads a page at a time from where it stopped,
and SQLite's FTS5, which memory's search needs already (§28) and `make install-check` checks, indexes it. What no
measurement says is what it costs on a real record: how much text there is, how large its index is, and how long a
search takes. So the milestone lists every session, which needs no index, measures the text, and indexes what the
numbers allow.

## Stages

Three, each in its own PRs. Stage 1 waits on no measurement, and may be built beside stage 0; stage 2 waits on stage
0's numbers.

- **Stage 0, the measurement.** `canopy sessions --sizes`, over the runtime's whole record, opened read-only as the
  spend's read opens it (§13), refused inside a tick or a run (T6), with `--json` for `MEASUREMENTS.md`:
  - the sessions, canopy's by kind of run and the rest by directory, as `canopy spend` tells them apart, with the
    subagents', the archived, and those still in OpenCode 1's tables counted apart;
  - the characters of text by part: titles, what a session was sent, what its agent wrote, its reasoning, what its
    tool calls and shell were given, what they returned, and summaries;
  - for each of three cuts, a trial index in a temporary file in the state directory, removed when the command ends:
    its size, with word positions and without, the time to build it, and the time to find the words the command was
    given; and the time to find the same words by a plain scan of the record, with no index, as §22's search scans
    the journal. The cuts are `said` (titles, what a session was sent, what its agent wrote, and summaries), `did`
    (that, and what its tool calls and shell were given: commands, paths, patterns), and `read` (that, its reasoning,
    and what the calls returned).

  The operator sets the thresholds before the measurement is taken, never after; the draft's are a search within a
  quarter of a second, M31's bar, and an index no larger than a quarter of the runtime's own database. Stage 2 takes
  the widest cut that passes both. A cut whose plain scan is within the bar needs no index: stage 2 then searches the
  record in place, as M31 found for the journal.
- **Stage 1, every session listed, and found by its title.**
  - `sessions.search`, private (T7): `off` by default, so nothing more is read or served than today, `titles`, or,
    once stage 2 is built, `text`. And `sessions.exclude`, private: globs of directories whose sessions canopy neither
    lists nor indexes, such as another client's work.
  - At `titles`, the read that records every session's spend (§13) also keeps its title, and when it was archived
    where the record says, under either runtime version: the title bounded, on one line, with control and hidden
    characters dropped. Turning the key on reads the record again from its first session, so the sessions already
    recorded get theirs.
  - The web UI gets a Sessions page: every session the runtime keeps, newest first, a subagent's under the session it
    ran for, an archived one left out until asked for, as the runtime's own list leaves it. It opens on the sessions
    outside canopy, the operator's own, which no page lists today, with canopy's a filter away, so canopy's count
    never buries them. Another workspace's runs are outside, as for spend, told apart by their directory, which
    `sessions.exclude` can leave out. A row has the session's title, where it ran, when, and what it cost. One of
    canopy's names the run, tick, review, chore run, or task run that made it, and opens that page; one outside has
    its id and the command that reopens it in the runtime, with its directory, to copy.
  - The search page gains two panels, as it has one per source: the sessions outside canopy, and canopy's, each the
    newest whose title holds every word.
  - `canopy sessions [WORDS]` lists and finds the same from the shell, with `--json`, and says how far the read has
    come. It refuses inside a tick or a run, and no tool serves it to an agent (T1, T6).
- **Stage 2, what was said, indexed.** At `text`, over the cut stage 0 chose.
  - *The index.* `.canopy/sessions.db`, beside the journal and private as the state directory is (D053), queried
    through `core/sql.py` as the journal is (D125). It is a cache, never the journal: every row comes from the
    runtime's record, so it has no migration, is dropped whole and built again when its shape or the cut changes, and
    is removed when `sessions.search` goes below `text`; `canopy gc --dry-run` reports its size. It holds an index of
    words and no text of its own, as memory's index holds none (§28): a hit's snippet is read from the runtime's
    record when the search is made, for the hits shown alone, so the index is a fraction of the text and shows
    nothing the runtime no longer keeps. A SQLite too old to delete from such an index, before 3.43, gets `titles`
    and a line saying why.
  - *What is indexed.* Of a session outside canopy, all the cut names. Of a session canopy started, its title and
    what its agent wrote, did, and read, as the cut names them, never what it was sent: a run's prompt is the
    journal's text rendered, a tick's state block the same text every tick, and §22's search finds both already. A
    message and a session are each indexed up to a bound, and a hit on one past it says it was cut, so no session a
    run wrote fills the disk (T3).
  - *Keeping it in step.* While `canopy loop` waits between live ticks, as the spend's read does (§13), never in a
    tick, a dry run, or a pause: from where the last read stopped, a session updated since is indexed again whole,
    in place of its rows. The first build goes from the newest session back, so last week's are found before last
    year's, and each step is bounded in time, so the wait still ends when it is due. Each sandbox role's record is
    read with the operator's (§24), and one canopy cannot read is passed over whole. Once a day, with the pass (§26),
    a session the runtime no longer keeps leaves the index. The page and the command say how far the index has read,
    and when.
  - *Searching.* A hit is a session: its title, the snippet of its best message with the query's words marked, and
    how many more of its messages hold them. A session is found when its title and one of its messages hold every
    word between them, each matched as a word, as memory's search matches (§28), never as the index's query syntax,
    so no query is an error. Hits are ranked by how well they match, a word in a title weighing more, then newest
    first, in stage 1's two panels, its page, and its command. A hit on one of canopy's opens its run's page, whose
    transcript finds the same words while the log is kept (§26).
  - *Behind the runtime's surface.* What a session's record holds, how its text is read, and how one is reopened are
    the implementation's (D009): OpenCode 2's. Under the deprecated OpenCode 1, `text` is `titles`, and the page
    says so.
- **Rejected:** the runtime's own search (a title's `LIKE`, and canopy would have to run the operator's runtime to
  ask it); an index of the logs canopy keeps (canopy's runs alone, and only for `retention.run_files_days`, where the
  runtime's record holds every session in one shape); the index in the journal (the journal holds the loop's facts,
  kept forever under migrations; this is a derived copy of another program's text, dropped whole and rebuilt); the
  text kept in the index (a second copy of every session in the state directory, and an index three times its text,
  §22); embeddings or any semantic search (the core never calls a model, §4); search as a tool or a prompt section
  for canopy's agents (a run that reads other sessions reads other tickets' work and the operator's own, T6, and
  agents skip lookup tools, §28); a service of its own to keep the index (D042: the loop's wait reads, as it reads
  spend); and writing to the runtime's record, a title, a tag, or an archive mark, to thin its own list (not
  canopy's to write, §26; the `Status:` line leaves it to the operator).
- **TRUST_MODEL**, in the PR that builds stage 1, extended by stage 2's: T1 (a title and a snippet are whatever an
  agent wrote or a tool read, ticket and PR text among it: data, bounded, hidden characters dropped, rendered as text
  (D113), and put in no prompt; a query is words; no agent canopy runs can search); T3 (each step of the read is
  bounded in time, each message and session in size, and the index's size is reported); T4 (the record is what runs
  write, an unsandboxed run's the operator's own, so it is opened as the spend's read opens it, read-only and as one
  made to harm its reader, each row validated (D026); the loop alone writes the index, in the state directory, which
  a sandboxed worker neither reads nor writes (§24)); T6 (the index is derived from every session's text, a private
  ticket's and the operator's own in other directories among it, and is kept as that text is: operator-only, on the
  machine, sent nowhere; `sessions.exclude` keeps a directory out; an unsandboxed run could already read the record
  itself, the standing residual); T7 (two more private keys, which the workspace file cannot set and the web's config
  writes never name, D128); T8 (the listener serves what it never has: the titles, then the snippets, of sessions
  outside canopy, the operator's work in any directory, and of canopy's runs past their logs' retention; to the
  secret's holder, read-only, bounded, as text, and over plain HTTP on a private address they cross the network as
  transcripts do (D076); a stolen session reads them, the residual, and `off`, the default, serves none). No
  `DECISIONS.md` entry: a feature, two keys, and a cache. The design gains a few sentences in §13 for what the read
  keeps and the index, in §22's Search, with its rejection of FTS5 revised, in §26's table, and in §12 for the keys,
  with `examples/config.toml`; the guide a page for Sessions and a paragraph under Search; `ui/DESIGN.md` the page.
- **Tests with the fakes:** over runtime databases written by hand, as the spend's tests write them. Stage 0's
  command: sessions counted by whose they are and by kind, characters by part, a session canopy cannot read passed
  over and counted, a sandbox role's record read, each trial index measured and its file removed, `--json` held by a
  snapshot. Stage 1: a title kept, bounded, a hidden character dropped; one of canopy's listed with its run, one
  outside with its directory and its command; a subagent's under its parent; an excluded directory's nowhere; the
  two panels and the page through the web's mock `backend`; the command refused inside a run; `off` leaving the
  journal's rows and the API as they are; under each runtime version. Stage 2: a session found by a word of what it
  was sent, of what its agent wrote, and of its title with a message; one of canopy's never by its prompt's words;
  one updated since indexed again; one the runtime dropped gone after the pass; a message past the bound cut and
  marked; a message whose JSON is not what the reader expects passed over; a role's record that cannot be read passed
  over whole; the first build newest first; a step that stops at its time bound and goes on from there; the index
  removed when the key is lowered and built again when raised; a snippet read from the record, and none for a session
  it no longer keeps; a query of the index's syntax searched as words, as memory's test holds its own;
  `test_layers.py` for each new module, `test_frozen.py` for each record type, and `core/test_db.py` and
  `core/test_records.py` for stage 1's migration.

Accept: Stage 0's numbers in `MEASUREMENTS.md`, from the operator's own record, against the thresholds they set, with
their call on the cut recorded on the `Status:` line before stage 2 starts. Live, once stage 1 is built, at `titles`:
the operator finds a session of their own, run by hand in a directory outside the workspace, by a word of its title,
with canopy's sessions in the same record, and reopens it in the runtime with the command canopy gives; a run's
session opens its run's page; a session in an excluded directory is on no page and in no command's output; and at
`off` the API serves no session's title. Once stage 2 is built, at `text`: the operator finds a session of their own
by words only its text holds, and a run by something its agent wrote that no journal row holds, each within the bar
on the real record; a session that ended minutes ago is found after the loop's next wait; one deleted in the runtime
is gone after the next pass; a sandboxed run's session is found as an unsandboxed one's is; each tick still starts
when it is due while the first build runs; and the index's size and a search's time on the real record are in
`MEASUREMENTS.md` beside stage 0's.

Status: in progress. Drafted 2026-11-10 at the operator's ask, from §13's read of the runtime's record and a read of
the build npm ships (`@opencode/cli-linux-x64` 2.1.4), not run. Chosen conservatively, for the operator to change: the
names (`canopy sessions`, `sessions.search`, `sessions.exclude`); `off` by default; one index per workspace, beside
its journal, rather than one per machine; the text of OpenCode 2's sessions alone; and no reader of a session in the
web UI, so a hit outside canopy is reopened in the runtime. Stage 0's command, `canopy sessions --sizes`, built
2026-11-10, reads OpenCode 2's record alone. Its thresholds, set by the operator before the measurement, are the
draft's: a search within 0.25 s, and an index no larger than a quarter of the runtime's own database. Measured
2026-11-10 (MEASUREMENTS "2026-11-10: M72 stage 0, the runtime's record and what indexing it costs"): every cut passes
both, the widest, `read`, with its slowest search at 0.027 s and its largest index 0.6% of the database, where a plain
scan takes about 70 s, so stage 0's rule gives stage 2 `read`. The operator's call on the cut (2026-11-11): `read`, as
the rule gives. Stage 1 begun 2026-11-11: the two keys, the read keeping each title and archive under either runtime
version and starting again from the first session when a key changes, and `canopy sessions [WORDS]`; the web UI's
Sessions page, the search page's two panels, and TRUST_MODEL T8 for them, are next. The reopen command, `opencode
--session ID` in the session's directory, is OpenCode 1's, assumed of 2 and not yet run. Settled 2026-11-11, at the
operator's ask to resolve what was open, for the operator to change. The sessions OpenCode 1 left in its own tables get
no reader: OpenCode 1 is deprecated and kept only until it is dropped (AGENTS.md). Stage 0's command counts them,
unread, and the section does not give the count, so this was settled without it. And canopy's sessions stay in the
runtime's own list: the Sessions page opens on the operator's own, with canopy's a filter away. What would thin the
runtime's list changes what canopy does with the runtime's data and logins (§26, T2, T4): a record of its own for an
unsandboxed run, as a sandboxed role has (§24), or archiving canopy's sessions through the runtime. That is a milestone
of its own, on the roadmap's deferred list with its trigger.
