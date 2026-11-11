# M70. A code outline for agents

DESIGN §5, §8, §12, §13, §18, §21, §24, §25, §27, §28, §30, and §36, TRUST_MODEL T1, T3, T4, T6, T7, and T8, D026, D041,
D124. Asked for by the operator (2026-10-31): an agent starts each run knowing nothing of the repository but its working
directory, and spends the first stretch of every run finding its way with grep and reads, in the Bazel monorepo (R10)
above all, where a ticket names a behavior and the code that holds it is many directories away. The workspace map
(`MAP.md`, §18) says what each repository owns and is in every prompt already; nothing says what is inside one. Today
the only index on offer is a third-party MCP server in the operator's own OpenCode config (`docs/CODEBASE_MEMORY.md`):
per slot, so a pool of four builds four and a later run finds the last branch's; blind through the reviewer's and the
planner's links and a joint run's desk; a reach over every project indexed on the machine; untested under the sandbox;
and never tried on a running loop. And agents skip lookup tools (§28): what an agent must see goes in its prompt.
aider's repo map is the nearest evidence that a ranked, bounded outline in the prompt helps, and it is weak evidence
here: aider's model had no tools, and canopy's agents orient by grep today, as Claude Code and OpenCode do with no
outline at all. So the milestone measures first and builds the cheapest thing that moves the number, and canopy adds
what a laptop tool need not: an index keyed by what git holds, never by a path, built once by the harness for every
agent that reads code, with the same bytes however the run is wrapped.

So canopy renders each run an outline of the code its work is about, as data, in the prompt, from the repository's
tree alone first and from a symbol index only if the tree is not enough, and offers lookups last. Four stages, in order,
each in its own PRs; each later stage waits on the measurement before it. It is an outline throughout, in config,
prompts, and code: "map" is the workspace's (§18).

- **Stage 0, the gate.** From the transcripts canopy keeps (M27), two weeks of worker, planner, reviewer, and task runs
  in `MEASUREMENTS.md`, per role and per repository: per run, the tool calls, the grep and glob calls among them, and
  the spend before the first read of the file the run first edited (a review's or a plan's, before its first read of a
  file its diff or ticket names), and the share of the run's tool calls that is. Taken by a script in the PR, read by
  the operator. Stage 1 starts only if, in the monorepo, the median worker run spends more than a quarter of its tool
  calls, or more than three grep or glob calls, before that first read; the operator may set another threshold on the
  `Status:` line before the measurement is taken, never after. Below it, the milestone is deferred with the numbers.
- **Stage 1, the tree.** `index.outline`, private, `off` by default, so every prompt is the bytes it is today, `tree`,
  or, once stage 2 is built, `symbols`; `index.outline_chars`, the outline's bound; `index.exclude`, globs of tracked
  files no outline needs, compared as `high_impact_paths` are (§21). At `tree`, step 3 of a dispatch (§8), and a
  review's, a plan's, and a task's start, render each of the run's repositories a directory tree of the tree the harness
  chose for it, from `git ls-tree -r` and nothing else: no parser, no index. Directories the work is about are opened
  to their files, the rest collapsed to a name and a file count, outermost first, until the bound is reached, and the
  outline says how many files it left out. The work's directories are found by words: for `implement` and a plan, the
  words of the ticket as the connector last observed it (§30, `observed_tickets`, its title and body), split as aider
  splits a message and again on camelCase and snake_case, used to rank and never rendered; for `resume` and a feedback
  plan, the branch's diff; for a review, the PR's diff; for a task (§36), its own text; matched against path components.
  A ticket with no observation, or whose words match no path, gets the tree opened by size alone. A joint run's worker
  (§18) gets one tree per repository. Framed as data, quoted line by line as ticket notes are (§28); a path is bounded,
  and one holding a character that can hide text is dropped, never rendered. Then two weeks at `tree` in
  `MEASUREMENTS.md`, stage 0's numbers again beside its. If the monorepo's median is under the gate's threshold, the
  milestone is done here, and stages 2 and 3 are deferred with the numbers.
- **Stage 2, the symbols, if stage 1 says so.** Three parts, each its own PR or more.
  - *The indexer.* A workspace member, `packages/canopy-index`, `canopy-index` (D041): it reads files on stdin, each
    with its path, parses each with tree-sitter and a tags query, and prints one JSON record per file of its
    definitions (name, kind, line, enclosing scopes) and the distinct names it references, each with a count, and per
    file it cannot parse the reason. The grammars are pinned wheels, one per language, Python and TypeScript/JavaScript
    first and the monorepo's languages with them, named by the operator with each grammar's query coverage: of the
    wheels checked (2026-11-05), Python, TypeScript, Java, and Go ship their own `tags.scm`, and Kotlin, Bash, and
    Starlark ship none, so canopy vendors a query for a language whose wheel lacks one, as aider does, and the query's
    hash joins the cache key. A file of no shipped language, or past a size bound, yields its path alone. It imports
    nothing of canopy, runs no code of the repository, opens no file and no socket, and parses a file broken mid-edit as
    far as the tree goes. The harness runs it through `infra/procs.py` with a time limit, a memory limit, and an output
    bound, in batches each under its own limit, so a slow tree is indexed over several syncs rather than never, and
    under the sandbox wrapper with a role of its own, `index`, that reads and writes nothing but its pipes, where the
    operator has the sandbox (§24); validates its output with pydantic (D026); and never imports tree-sitter;
    `test_layers.py` holds that. It indexes from git's objects, never a working tree: `git ls-tree -r` of the tree it
    chose, and `git cat-file --batch` for the blobs it needs, so a slot's state, a run's edits, the pool's layout, and
    the tree's own `.gitattributes` change nothing, and the harness reads nothing a sandboxed run can write (§24). A
    submodule is another repository, listed by its path and not indexed.
  - *The cache.* Per blob, `.canopy/index.db` beside the journal, queried through `core/sql.py` as the journal is:
    definitions with their lines, and references as distinct names with counts, never lines, since the ranking consumes
    counts and a lookup needs only definitions. A blob's records depend on its bytes, its path's language, the query's
    hash, and the indexer's version alone, so those are the key, slots, branches, and pools that share a blob share its
    records, a tree is indexed by listing it and parsing only the blobs the cache lacks, and a new release of the
    indexer, a grammar, or a query parses afresh. `canopy workspace sync` indexes each pool's base, so a run pays for
    its own commits alone; `canopy index` shows coverage per repository and builds the cache by hand; `canopy gc`
    drops blobs no pool's base and no open run's tree holds, and records of an older indexer.
  - *The outline at `symbols`.* The tree's seeds, and the identifiers among the same words matched against definition
    names, pick the candidate files: the seeds, and two hops through the name tables from them, capped at a few
    thousand files, never the tree. A name defined in more than N files, or referenced from more than M, is left out of
    the hops: `get`, `run`, and `Builder` make dense cliques whose edges aider's weights lower but never remove. Over
    the candidates alone, a definition-to-reference graph with aider's weights (a mentioned name, a long compound name,
    a private name, a name defined in many files, the work's own files) and personalized PageRank in stdlib, since the
    graph is of files, so a dispatch costs a few queries of the cache, never a graph of the monorepo. Each entry is a
    definition inside its enclosing scopes, grouped by file, within the bound, the tree's collapsed directories after
    them; an identifier is bounded and filtered as a path is. A repository the indexer has not finished gets the tree.
    The outline is rendered once, in the prompt, so a run's prompt stays the bytes the journal can show. Then two weeks
    at `symbols` in `MEASUREMENTS.md`, beside stage 1's numbers and the outline's own: its size, how often the file a
    run first edited was in it, and how often it was cut. An outline rarely holding the run's first file is reranked or
    its bound raised.
- **Stage 3, the lookups, if stage 2 says so.** `canopy _mcp --index`, named `canopy_index`, offered to the workers,
  the planner, the reviewer, and a task's agent, over stdio alone (D124): `symbols PATH` and `definition NAME`, each
  over the index of the run's own repositories, written by the harness to the run's answers directory (§41), which a
  sandboxed run reads and nothing in it writes, never over a path the agent names, never indexing on demand; output
  bounded, records as structured content and as JSON in the text, as `canopy_git`'s `log` and `grep` are (§27). No
  `references` tool: `git grep` answers that already, through `canopy_git` for the reviewer and the planner and the
  shell for a worker, and the index's by-name match would add nothing. Each definition allows the two by exact name
  after its deny of `canopy_*`; the overseer and the chores never see them. The shadowing check (§13) refuses a
  repository config that names a server `canopy_index`, as it refuses `canopy`, since a worker starts where that config
  loads. D124 rejected tools for workers; §41's `status` has since given them one, and this stage amends the entry to
  say what a worker's tool may be: a read of what the harness wrote for that run, never a write. The tools stay if
  transcripts show them called where the outline ran out; the operator's call is recorded on the `Status:` line.
- **Rejected:** a third-party index server (above, and `docs/CODEBASE_MEMORY.md`); a language server for the reviewer
  and the planner (several run the project's own build to answer, and a review executes nothing of the PR, §21; the
  workers have OpenCode's own); embeddings or a semantic index (the core never calls a model; weakest on what changed,
  §28); an FTS5 index (`git grep` over a known tree already is one, M31, M50); `tree-sitter-language-pack` (it
  downloads parser libraries from a remote manifest at run time and loads them as native code; a pinned wheel per
  language is reviewed in `uv.lock`); parsing inside the harness's process (generated C over text from a PR; a crash
  costs the outline, not the tick); an index per slot or per path (stale once the slot is reset; the blob is the key git
  already keeps); indexing the working tree (reads what a run writes, §24; keyed by mtime, which a checkout resets);
  `git archive` as the indexer's source (the tree's `.gitattributes` can leave files out or rewrite them); references
  stored with lines (tens of millions of rows for the monorepo, for a ranking that reads counts); a graph of the whole
  tree per dispatch (minutes on a large repository, as aider shows); the symbols before the tree is measured (the
  graph is the expensive half, and the tree may be enough); lookups without the outline (agents skip tools, §28); an
  outline rebuilt as the run goes (its prompt is one record, §8); the name "map" (the workspace's, §18).
- **TRUST_MODEL**, in the PR that builds stage 1, extended by stage 2's: T1 (paths, names, and scopes are the
  repository's text, data in the prompt and never an instruction, each bounded, hidden characters dropped; a review's
  outline is of the PR's own tree; a ticket's text picks what the outline ranks first and is rendered nowhere); T3
  (the indexer's time, memory, and output limits, a size bound per file, batches, and an outline that degrades to the
  tree, so no repository's size holds a run); T4 (the indexer parses the blobs of a PR's or a branch's tree, which a
  contributor wrote, under those limits; it reads stdin alone, runs nothing of the repository, opens no socket, runs
  under the sandbox where the operator has one, and reads git's objects on the host, never a working tree a sandboxed
  run writes; without the sandbox, a parser bug in a pinned grammar is the residual, as a plugin's is today); T6 (a
  run's outline and index are of its own repositories' trees, never a path an agent names, so a steered agent reaches
  no other project); T7 (three more private keys, listed with the others; the shadowing check reaches `canopy_index`);
  T8 (stdio alone). `DECISIONS.md` gains one entry in stage 2, since a parser of untrusted input is shaped around:
  tree-sitter parses code, each grammar a pinned wheel never fetched at run time, only in `canopy-index`, from stdin;
  and stage 3 amends D124. The design gains a section on the outline, a line in §8 step 3, in §12 for the keys with
  `examples/config.toml`, in §13 and §27 for the server, in §24 for the role, and in §5 for the program.
- **Tests with the fakes:** the tree rendered from a hand-written repository, held by `markdown_snapshot`, the
  ticket's words opening their directory, a task's the same, a ticket with no observation opened by size, the bound
  kept with the count of files left out, a joint run's tree per repository, a review's of the PR's tree, a hidden
  character in a path dropped, `off` leaving each prompt byte-identical; the indexer's own, in `tests/canopy_index/`, a
  sample per shipped language, a vendored query's language, a file broken mid-edit, one of no shipped language, one
  past the size bound, one with a hidden character in a name, an input past the output bound, a batch under its own
  limit; the cache, a blob parsed once across two trees and two slots, the same bytes at paths of two languages parsed
  twice, a tree indexed by its missing blobs alone, an older indexer's or query's records parsed afresh, `gc` dropping
  what no base holds; the outline at `symbols`, the ticket's named definition's file ranked first, a high-degree name
  left out of the hops, the candidate cap held, an indexer that times out or crashes leaving the tree and the run
  going; the `scenario` fixture for a worker whose prompt holds the outline and a sandboxed worker's the same, and the
  sandbox's own tests for the `index` role; stage 3's tools answering inside the run's repositories, refusing a path
  outside them, bounded, absent from the overseer and a chore, and a repository config naming `canopy_index` refused;
  `test_layers.py` for the member and its imports, `test_frozen.py` for the record types, `test_prompt_sizes.py` for
  the prompts' sentence on the outline, and `core/test_db.py` if the cache's schema is a migration of its own.

Accept: Stage 0's numbers in `MEASUREMENTS.md`, against the gate's threshold, read by the operator, before stage 1
starts. Live, once stage 1 is built: a worker on a toy ticket whose words name a directory of the monorepo and not its
file has that directory open in its tree, as its prompt in the journal shows, and its transcript's first read or edit is
under it; a sandboxed worker the same, byte for byte; a task's agent the same from the task's text; a joint run's worker
a tree per repository; and two weeks at `tree` in `MEASUREMENTS.md` beside stage 0's, with the operator's call on stage
2 recorded on the `Status:` line. Once stage 2 is built: a worker on a toy ticket that names a behavior in the code's
own words and not its file has that file's definitions in its outline, and its first read or edit is of that file; a
reviewer's outline holds the PR's touched definitions and their callers; the monorepo's base indexed by `canopy
workspace sync` over its batches, or its outline the tree with the log line saying so; and two weeks at `symbols` as
stage 2 says, with the operator's call on stage 3 recorded on the `Status:` line.

Status: in progress. Drafted 2026-11-05 at the operator's ask; the operator chose a parser library over ctags the
same day, and the same day, on their adversarial review of the draft, made stage 0 a gate with a threshold, put the tree
before the symbols, bounded the cache and the ranking, and renamed the map to the outline, since "map" is the
workspace's. Stage 0's measurement built 2026-11-06 against the fakes, as a command rather than a loose script, as
`canopy cards` and `canopy latency` are: `canopy orientation`, read only, over `--days` (14 by default) of ended runs
by when they started (`core/orientation.py`), per role and repository, gives the medians of the tool calls, the
searches among them, the share, and the spend before each run's anchor, and says whether each repository's worker runs
pass the gate; `--json` for `MEASUREMENTS.md`. Each implementation reads what a call did to files from its own tools
(`touched`), so a search is a `grep` or `glob` call or a shell command that starts one. Chosen conservatively, for the
operator to change: a plan run's anchor is the first read of a file its plan names, not one its ticket names, since a
ticket names a behavior and seldom a file; a feedback plan's run has none; a run whose log was cut at the transcript's
bound is read and not anchored; an epic's planner runs are not measured, as the gate reads worker runs and an epic is
planned once; a joint run is its own repository row (`api+web`); and the spend before an anchor is of the model calls
that ended before it, unknown once one could not be priced. Open, for the operator before
stage 1: the gate's threshold, if not the draft's; the monorepo's languages, with each grammar's query coverage, which
decides whether canopy vendors queries; and whether stage 1 renders the outline for every role at once or the workers
first. The gate's threshold, set by the operator before the measurement, is the draft's: more than a quarter of the tool
calls, or more than three searches, before the first read of the file the run edits. Measured 2026-11-10 (MEASUREMENTS
"2026-11-10: M70 stage 0, what runs do before the file they work on"): the monorepo's worker runs meet the gate, their
median share before the anchor 0.429 with a median of no searches, on the 65 of 561 runs anchored, the `implement` runs
alone at 0.244, under a quarter, and the `resume` runs at 0.50. Open for the operator: stage 1's start, the gate being
met; the monorepo's languages, with each grammar's query coverage; and whether stage 1 renders the outline for every
role at once or the workers first. That measurement's searches leave out a shell search an agent made under the name
`bash`, which OpenCode 2's reader took for no shell until 2026-11-11 (M71), so they are a floor; the gate was met on the
share alone, and stands. Settled 2026-11-11, at the operator's ask to resolve what was open, for the operator to change.
Stage 1 starts: the threshold was set before the measurement and is not moved after it, and the monorepo's worker runs
are over it. What the numbers leave weak is recorded, not weighed against the gate: 65 of 561 runs were anchored, the
`implement` runs alone are at 0.244, and a `resume` run's calls before its anchor may be reads of the PR's feedback
rather than a search for the file, which this measurement does not tell apart. So stage 1's two weeks at `tree` are read
per kind beside stage 0's, `implement` and `resume` each, as well as against the gate's one median. The workers get the
outline first, `implement` and `resume`, a joint run's among them, in stage 1's first PR, with the keys, the renderer,
and TRUST_MODEL: the gate reads worker runs, and so does the measurement that ends the stage, so its two weeks start
once the workers have it. The planner's, the reviewer's, and a task's follow in PRs of their own, within stage 1 and
not waiting on those two weeks, so Accept stands as written. They come second on the numbers: the monorepo's plan runs
are under the threshold at 0.154, a review's at 0.288 is over it but its diff names its files already, and task runs
were not measured. The monorepo's languages are not settled here and hold nothing: stage 1 parses nothing, and no doc
in this repository names them. They are named if the operator calls stage 2, from a count of the monorepo's tracked
files by extension, taken then; a language whose wheel ships no tags query gets a vendored one, as stage 2 says.
Stage 1 begun 2026-11-11, at the operator's ask, for the
workers, against the fakes: the three keys, the tree in an `implement`'s and a `resume`'s prompt, a joint run's per
repository, DESIGN §46, and TRUST_MODEL T1, T3, T6, and T7. Chosen conservatively, for the operator to change. The tree
is read in the leased slot at dispatch, before `_run` fetches, so it is as the lease last fetched it, and the outline
names the ref: an `implement`'s base, a `resume`'s branch. A `resume` whose branch changed nothing yet is opened by the
ticket's words. Beyond aider's split, the commonest words of English prose rank nothing and a plain plural is its
singular, since a ticket is prose where aider's message named identifiers. An opened directory names at most 40 of its
own files, the ones the work is about first. `index.outline_chars` is 6,000 by default and bounds the trees, the
section's own sentence apart. A prompt override without `{{OUTLINE}}` gets no outline and is not refused, as it must
carry nothing to do its work. A privately started ticket has no observation, so its tree is opened by size. Next: the
planner's, the reviewer's, and a task's, then Accept's live checks and the two weeks at `tree`.
