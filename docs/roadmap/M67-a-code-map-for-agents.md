# M67. A code map for agents

DESIGN §5, §8, §13, §18, §21, §24, §25, §27, and §28, TRUST_MODEL T1, T3, T4, T6, T7, and T8, D026, D041, D124. Asked
for by the operator (2026-10-31): an agent starts each run knowing nothing of the repository but its working directory,
and spends the first stretch of every run finding its way with grep and reads, in the Bazel monorepo (R10) above all,
where a ticket names a behavior and the code that holds it is many directories away. Today the only index on offer is a
third-party MCP server in the operator's own OpenCode config (`docs/CODEBASE_MEMORY.md`): per slot, so a pool of four
builds four and a later run finds the last branch's; blind through the reviewer's and the planner's links and a joint
run's desk; a reach over every project indexed on the machine; untested under the sandbox; and never tried on a running
loop. And agents skip lookup tools (§28): what an agent must see goes in its prompt. aider's repo map is the evidence
that a ranked, bounded map in the prompt works; canopy adds what a laptop tool need not: an index keyed by what git
holds, never by a path, built once by the harness for every agent that reads code, with the same bytes however the run
is wrapped.

So canopy indexes each repository's code itself, deterministically, from git's objects, and renders each run a map of
the code its work is about, as data, in the prompt, and only then offers lookups. Three stages, in order, each in its
own PRs; stage 2 waits on stage 1's numbers.

- **Stage 0, the baseline.** From the transcripts canopy keeps (M27), two weeks of worker, planner, and reviewer runs in
  `MEASUREMENTS.md`: per run, the tool calls before the first edit, the files read, and of those the share the run's
  diff never touched, with the run's spend; per repository too, since the monorepo is the case that matters. Taken by a
  script in the PR, read by the operator, so stage 1 has a number to beat.
- **Stage 1, the map.** A workspace member, `packages/canopy-index`, `canopy-index` (D041): it reads a tar of files on
  stdin, parses each with tree-sitter and its grammar's own `tags.scm`, and prints one JSON record per file of its
  definitions (name, kind, line, enclosing scopes) and references (name, line), and per file it cannot parse the reason.
  The grammars are pinned wheels, one per language, Python and TypeScript/JavaScript first and the monorepo's languages
  with them, named by the operator; a file of no shipped language yields its path alone. It imports nothing of canopy,
  runs no code of the repository, opens no file and no socket, and parses a file broken mid-edit as far as the tree
  goes. The harness runs it through `infra/procs.py` with a time limit and an output bound, validates its output with
  pydantic (D026), and never imports tree-sitter; `test_layers.py` holds that. It indexes from git's objects, never a
  working tree: `git archive` of the tree it chose, so a slot's state, a run's edits, and the pool's layout change
  nothing, and the harness reads nothing a sandboxed run can write (§24). The cache is per blob, `.canopy/index.db`
  beside the journal, queried through `core/sql.py` as the journal is: a blob's records depend on its bytes and its
  path's language alone, so slots, branches, and pools that share a blob share its records, and a tree is indexed by
  listing it and parsing only the blobs the cache lacks. `canopy workspace sync` indexes each pool's base, so a run pays
  for its own commits alone; `canopy index` shows coverage per repository and builds the cache by hand; `canopy gc`
  drops blobs no pool's base and no open run's tree holds. `index.map`, private, `off` by default, so every prompt is
  the bytes it is today, or `on`; `index.map_chars`, the map's bound; `index.exclude`, globs of tracked files no map
  needs, compared as `high_impact_paths` are (§21). At `on`, step 3 of a dispatch (§8), and a review's, a plan's, and a
  task's start, render the run's map from the tree of each of its repositories: the files its work is about first, a
  ticket's named files and identifiers for `implement` and a plan, the branch's diff for `resume` and a feedback plan,
  the PR's diff for a review; then the files that define what those reference and reference what those define, ranked
  by a definition-to-reference graph with aider's weights (a mentioned name, a long compound name, a private name, a
  name defined in many files, the task's own files) and personalized PageRank in stdlib, since the graph is of files;
  each entry a definition inside its enclosing scopes, grouped by file, cut at the bound with the files past it listed
  by path. The map is rendered once, in the prompt, so a run's prompt stays the bytes the journal can show, and a joint
  run's worker (§18) gets one per repository. Framed as data, quoted line by line as ticket notes are (§28); an
  identifier is bounded, and one holding a character that can hide text is dropped, never rendered. A repository the
  indexer cannot finish within its limit gets its file list and a log line, never a failed run (T3).
- **Stage 2, the lookups, if stage 1 says so.** `canopy _mcp --index`, named `canopy_index`, offered to the workers, the
  planner, and the reviewer, over stdio alone (D124): `symbols PATH`, `definition NAME`, and `references NAME`, each
  over the index of the run's own repositories, written by the harness to the run's answers directory (§41), which a
  sandboxed run reads and nothing in it writes, never over a path the agent names, never indexing on demand; output
  bounded, records as structured content and as JSON in the text, as `canopy_git`'s `log` and `grep` are (§27). Each
  definition allows them by exact name after its deny of `canopy_*`; the overseer and the chores never see them. The
  tools say what the index is: references match by name, not by type, so `save` in one class matches `save` in
  another. Whether the tools stay is stage 3's call.
- **Stage 3, the measurement.** Two weeks at `on` in `MEASUREMENTS.md`, stage 0's numbers again beside its, per role
  and repository, and the map's own: its size, how often the file a run first edited was in it, and how often it was
  cut. A map rarely holding the run's first file is reranked or its bound raised; the tools stay if transcripts show
  them called where the map ran out. The operator's call on each is recorded on the `Status:` line.
- **Rejected:** a third-party index server (above, and `docs/CODEBASE_MEMORY.md`); a language server for the reviewer
  and the planner (several run the project's own build to answer, and a review executes nothing of the PR, §21; the
  workers have OpenCode's own); embeddings or a semantic index (the core never calls a model; weakest on what changed,
  §28); an FTS5 index (`git grep` over a known tree already is one, M31, M50); `tree-sitter-language-pack` (it
  downloads parser libraries from a remote manifest at run time and loads them as native code; a pinned wheel per
  language is reviewed in `uv.lock`); parsing inside the harness's process (generated C over text from a PR; a crash
  costs the map, not the tick); an index per slot or per path (stale once the slot is reset; the blob is the key git
  already keeps); indexing the working tree (reads what a run writes, §24; keyed by mtime, which a checkout resets);
  lookups without the map (agents skip tools, §28); a map rebuilt as the run goes (its prompt is one record, §8).
- **TRUST_MODEL**, in the PR that builds stage 1: T1 (names and scopes are the repository's text, data in the prompt
  and never an instruction, each bounded, hidden characters dropped; a review's map is of the PR's own tree); T3 (the
  indexer's time limit and output bound, and a map that degrades to a file list, so no repository's size holds a run);
  T4 (the indexer reads stdin alone, runs nothing of the repository, opens no socket, and runs on the host over git's
  objects, never a working tree a sandboxed run writes); T6 (a run's map and index are of its own repositories' trees,
  never a path an agent names, so a steered agent reaches no other project); T7 (three more private keys, listed with
  the others); T8 (stdio alone). `DECISIONS.md` gains one entry, since a parser of untrusted input is shaped around:
  tree-sitter parses code, each grammar a pinned wheel never fetched at run time, only in `canopy-index`, from stdin.
  The design gains a section on the map, a line in §8 step 3, in §13 and §27 for the server, and in §5 for the program.
- **Tests with the fakes:** the indexer's own, in `tests/canopy_index/`, a sample per shipped language, a file broken
  mid-edit, one of no shipped language, one with a hidden character in a name, an archive past the output bound; the
  cache, a blob parsed once across two trees and two slots, a tree indexed by its missing blobs alone, `gc` dropping
  what no base holds; a map rendered from a hand-written repository, held by `markdown_snapshot`, the ticket's named
  file ranked first, the bound kept with the cut files listed, a joint run's map per repository, a review's of the PR's
  tree, `off` leaving each prompt byte-identical, an indexer that times out or crashes leaving the file list and the
  run going; the `scenario` fixture for a worker whose prompt holds the map and a sandboxed worker's the same; stage
  2's tools answering inside the run's repositories, refusing a path outside them, bounded, and absent from the overseer
  and a chore; `test_layers.py` for the member and its imports, `test_frozen.py` for the record types,
  `test_prompt_sizes.py` for the prompts' sentence on the map, and `core/test_db.py` if the cache's schema is a
  migration of its own.

Accept: Stage 0's numbers in `MEASUREMENTS.md`, read by the operator, before stage 1 starts. Live, once stage 1 is
built: a worker on a toy ticket that names a behavior and not its file, in the monorepo, has that file's definitions in
its map, as its prompt in the journal shows, and its transcript's first read or edit is of that file; a sandboxed worker
the same, byte for byte; a reviewer's map holds the PR's touched definitions and their callers; a joint run's worker a
map per repository; the monorepo's base indexed by `canopy workspace sync` within the indexer's limit, or its map the
file list with the log line saying so; and two weeks at `on` in `MEASUREMENTS.md` as stage 3 says, with the operator's
call on stage 2's tools recorded on the `Status:` line.

Status: not started. Drafted 2026-11-05 at the operator's ask; the operator chose a parser library over ctags the same
day. Open, for the operator before stage 1: the monorepo's languages, so the grammars it ships are named; and whether
stage 1 renders the map for every role at once or the workers first.
