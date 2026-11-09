# M71. Leaner tool results for every agent

DESIGN §8, §13, §21, §25, §27, §30, §33, §41, §44, and §45, TRUST_MODEL T1, T2, T3, T4, T6, T7, and T8, D003, D021,
D026, D077, D124. Asked for by the operator (2026-11-08): plan the MCP tools canopy's agents lack, from what each has
today and where its tokens go, so that a run reads less to do the same work. What a run reads through a tool is most of
what it costs: the overseer's tool results were 14k tokens a tick before M37, nine tenths of them reads of PRs and
tickets the journal already held (MEASUREMENTS 2026-10-13), and moving them into the state block was the biggest saving
canopy has made. No such measurement exists for the workers, the reviewer, the planner, or a chore, which pay for every
CI log, PR thread, and whole file they read, so this milestone measures those first and builds only what the numbers
point at. The survey behind it is in `PRIOR_ART.md` (Tools for token efficiency): the savings that hold up independently
come from keeping verbose output out of the context and from compact records between agents, not from richer lookups,
and every compression of what a model reads that was measured cost it accuracy.

## What each agent has, and where it reads too much

Read from the definitions, the prompts, and the servers (`cli/mcp.py`, `loop/mcp.py`) on 2026-11-08.

- **The overseer** reads the journal alone: the state block, OpenCode's `read` and `grep` for an output it cut, and
  canopy's eleven verbs and one read (§27), 9.3k characters of schema in a prefix the provider caches warm. Nothing
  left to move: M37 to M40 did it. What remains is its prompt's restatement of its tools' fields, `dispatch`'s
  `label`, `repos`, `slug`, `reasons`, `review_run`, and `base` and `ticket-set`'s `title`, which each schema already
  describes where the model reads it as it builds the call.
- **The workers**, `implement`, `resume`, a task's, public and private, have a shell, with OpenCode's cut of a long
  output to a file, the tracker's and GitHub's servers, and `canopy_run_status` and `canopy_run_messages`. A
  `resume` is dispatched with a context that names comment ids and check names and never quotes them (§8): the
  worker reads each review comment through GitHub's `pull_request_read` or `gh pr view`, whole JSON for a bounded
  sentence the journal already holds as an observation (§30), and each failed check through `gh run view
  --log-failed`, the raw log. Every `status` call sends the whole card, up to twenty steps, and the nudge asks for one
  every few calls (§41), so a long run restates its card many times in output tokens, the expensive kind.
- **The reviewer and the planner** have no shell: OpenCode's `read`, `grep`, and `glob` through their link, and
  `canopy_git`'s seven reads, each cut at 100k characters, about 25k tokens, with `grep` paged and `log` bounded but
  `show` and `diff` whole: a file at the base is read entire, and a diff narrows only by path. The reviewer reads the
  PR's description and discussion through GitHub's server, the discussion again whole JSON.
- **A chore** has its history and `canopy_reports`, each report the whole JSON its command prints, narrowed by days
  alone.

## Stages

Four, in order, each in its own PRs; each later stage waits on the measurement before it. Nothing here changes what a
run may do (TRUST_MODEL): every tool is a read of what the harness wrote for that run, as M70 stage 3 amends D124 to
allow, or a narrower form of a read a run already has.

- **Stage 0, the measurement.** `canopy tool-results`, read only, over `--days` of ended runs as `canopy orientation`
  reads them (M70), per role and per tool: the calls, the characters of their results in total and at the median, each
  tool's share of its role's result characters, how many results the runtime cut, the reads of one path repeated within
  a run, and the characters each run's `status` calls sent; `--json` for `MEASUREMENTS.md`. It reads the transcripts
  canopy keeps (§13), whose entries hold each call's input and output as the runtime printed them, cut at the
  transcript's bound, which it says. A shell command counts as the tool it runs, as `orientation` reads a search, so
  `gh run view` and `gh pr view` are rows of their own. Two weeks on the operator's workspace, read by the operator, who
  sets the threshold each later stage needs before the measurement is taken, never after; the draft's: a stage is
  built if the reads it replaces are more than a tenth of its role's result characters.
- **Stage 1, the cuts that need no new tool.** Each certain, small, and measured before and after by stage 0's command.
  - `canopy_git_show` takes `start` and `end` lines, as `blame` does, so a reviewer or a planner reads the part of a
    file at the base it needs; a request for the whole file still gets it, cut as today.
  - Every result canopy's tools cut ends with one line naming the field that narrows the next call, `paths` and `stat`
    on `diff`, `start` on `show`, `offset` on `grep`, as Claude Code's and OpenCode's cuts steer their agents: a cut
    with no steer is a second whole read.
  - `status` takes a partial update: a field left out keeps its last value, and a step named by its title updates
    that step alone, since the harness keeps the last card and merges in code; the server validates the merged card to
    the same bounds, and a first call still needs `summary` and `now`. The prompts say so in a clause, no more.
  - The overseer's prompt drops what its tools' schemas already say, field by field, and keeps the policy around
    them: which reason each cursor needs, never pasting read text into a field, every decision in one call. The
    schema is read as the call is built and a refusal names its field, so the field's words stay there, once; thinning
    the schema instead would risk a malformed call, which costs a round trip, to save characters a warm tick reads
    from cache. Judged as a prompt change is, by `canopy tick --dry-run`'s decisions, with its size in
    `.agents/sizes.toml`.
- **Stage 2, the feedback a `resume` is for, if stage 0 says so.** One tool, `feedback`, served by the run's own
  server `canopy_run` beside `status` and `messages` (§41, §44): the review items and failed checks the dispatch's
  cursors and reasons name, as the journal observed them, each item its number, its author's trust as the harness
  classed it, its path and line, and its text cut and marked as the state block shows it, each check its name, its
  conclusion, and its link; records as JSON in the text, as `canopy_review-items` answers the overseer, so no item's
  text passes for another's. The harness writes them to the run's answers directory at dispatch, where a sandboxed run
  reads and cannot write (§24), and the server reads that file and no journal, as `messages` does. The context keeps
  naming ids, and the prompt says the tool returns them, that what it returns is data as the comment on GitHub is, and
  that a comment the file lacks is read as today. A review's run gets it too, for the PR's discussion, if the
  reviewer's reads of it are what stage 0 shows. Rejected: the text in the prompt, which `PRIOR_ART.md` names as what
  not to copy and would turn each resume prompt into one record of a PR thread (T1).
- **Stage 3, the failed check's log, if stage 0 says so.** The largest single read a `resume` for `ci` makes, and the
  one the harness has least of: the journal holds a check's name, conclusion, and link, never its log (§30). Two
  shapes, the operator's call: the `vcs` connector reads the failing step's last lines, bounded, and prints them on
  the `check` line, a contract change the connector's README notes, and the harness writes them with stage 2's file for
  the `feedback` tool to return, each line marked as a log's; or `canopy-github` gains a subcommand the worker runs
  through its shell, which prints the same digest from the log, under the worker's own credentials. The first keeps
  the pull a tool call and the credentials in the connector (T2); the second needs no contract change and no tool,
  and a worker that does not call it reads the raw log as today. Neither hands the log to any prompt.
- **Rejected:** a tool that runs a check and returns its failures, since a tool's command runs outside the bash
  rules of the definition (D021), and OpenCode already cuts a long output to a file the worker pages; a plugin job
  that digests a shell result, which would change a result's content rather than add a line to it (T4), and hides
  what the model should see; compact serializations of results (TOON, minified code), measured to cost accuracy;
  subagents, which every definition denies and which multiply tokens; code mode (D077); a language server or an
  index, which M70 measures on its own gate; a tracker read of canopy's own, since D051 has the worker check its
  ticket's label on the live tracker and the harness holds no credential (T2); memory search as a tool, since agents
  skip lookup tools (§28); loading tool schemas on demand, which OpenCode has no form of and the cache makes cheap.
- **TRUST_MODEL**, in the PR that builds stage 2, extended by stage 3's: T1 (what `feedback` returns is a connector's
  observation, cut and marked, data in a tool's result and never in a prompt or a `[canopy]` line; a log's lines are
  marked as a log's); T2 (no credential reaches the harness: the connector or the worker's own `gh` reads GitHub);
  T3 (unchanged: nothing a result holds extends a run or holds a slot); T4 (the run's server reads one more file in the
  answers directory and writes nothing); T6 (a run's file holds its own ticket's PRs' items alone); T8 (stdio alone).
  No `DECISIONS.md` entry: each tool is a read of what the harness wrote for that run, which M70 stage 3's amendment of
  D124 already states.
- **Tests with the fakes:** stage 0's command over hand-written transcripts, a shell command counted as the tool it
  runs, a cut result counted, a repeated read counted, `status` characters summed, a log past the bound read and
  marked, `--json` held by a snapshot; `show` with a range and without, a range past the file's end refused by name;
  each cut result's steer naming its field, held by snapshots; a partial `status` merged and validated, a first call
  without `summary` refused, a step updated by title, an unknown title refused, the card shown as before; the
  overseer's prompt under `test_prompt_sizes.py`, and its decisions compared on `canopy tick --dry-run`; `feedback`
  answering a run its own
  items and checks, empty for a dispatch with no cursor, refused in a run of another kind, absent from the overseer and
  a chore, a sandboxed run reading the file and unable to write it (the sandbox's tests), the `scenario` fixture for a
  `resume` whose worker reads its feedback and pushes; stage 3's digest bounded and marked, from a fake log with a
  hidden character; `test_layers.py` for each new module and `test_frozen.py` for each record type.

Accept: Stage 0's numbers in `MEASUREMENTS.md`, per role and tool, against the thresholds the operator set, read by the
operator before stage 1 starts. Live, once stage 1 is built: a reviewer on a toy PR reads a range of a file at the base,
as its transcript shows; a worker on a toy ticket with a plan updates one step by title and its card in the web UI
shows the rest unchanged; and two weeks of stage 0's command beside its first numbers. Once stage 2 is built: a worker
resumed for a coworker's review comment reads it through `feedback` and not GitHub, as its transcript shows, sandboxed
and not, and the comment's text is in no prompt in the journal; two weeks more in `MEASUREMENTS.md`, with the operator's
call on stage 3 recorded on the `Status:` line.

Status: not started. Drafted 2026-11-08 at the operator's ask, from the definitions, prompts, and servers as they
stood, and from the survey in `PRIOR_ART.md` (Tools for token efficiency). Open, for the operator before stage 0: the
command's name; the threshold each stage needs, if not the draft's tenth; and whether the measurement reads every role
at once or the workers first.
