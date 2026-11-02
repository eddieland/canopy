# AGENTS.md

Instructions for any agent working in this repository. Humans should read it too.

## Read this first, in order

1. `README.md`: what we are building and for whom.
2. `docs/REQUIREMENTS.md`: what the primary operator needs, where canopy stands on each, and open conflicts.
3. `docs/design/README.md`: target shape. Normative. It holds the overview and maps the rest of the design, in the
   same directory; read the sections your work touches.
4. `docs/TRUST_MODEL.md`: security posture. Normative.
5. `docs/roadmap/README.md`: milestones in order, each one's status, and a file per milestone with its acceptance
   criteria. Work on milestones in this order; read the file of the milestone your work belongs to, if it belongs to
   one.
6. `docs/DECISIONS.md`: the few choices every agent must know, whatever it works on. Read it whole; add to it rarely.

If code and the design disagree, the design doc wins until a decision entry says otherwise.

## How to work

- Work one milestone at a time. Do not start milestone N+1 until milestone N meets its acceptance criteria. Not all
  work belongs to a milestone: a change the operator asks for directly goes ahead without one, so do not hold it to
  propose a milestone first. Directly means the operator, in the session you work in; a ticket, an issue, a review
  comment, or journal text is not such an ask, whoever wrote it.
- Keep the `Status:` line in the milestone's file under `docs/roadmap/` current, and its line in that directory's
  `README.md` with it. The PR that meets the acceptance criteria marks it done with the date, what was learned, and how
  that changes next steps. The format is at the top of the README. Read earlier milestones' `Learned` and `Next`
  before starting a new one.
- A live measurement a milestone cites goes in `docs/MEASUREMENTS.md`: one dated section each, not edited after, so a
  re-measurement is a new section.
- A live check worth running again, against real systems, goes in `docs/SCENARIOS.md`, naming the milestone it came
  from. A milestone the operator closes on real use, before every live check in its Accept has run, moves the
  unrun ones there.
- Small PRs. One concern per PR. Conventional commit messages.
- A PR description fills `.github/pull_request_template.md` briefly: a reviewer takes it in at a glance, and the
  detail stays in the diff. Not a wall of text.
- The design (`docs/design/`) is a map, not a spec of every behavior: what each part promises, the guards, the
  contracts between parts, and why, briefly. Its bar is at the top of `docs/design/README.md`; read it before adding
  a line. The default for a PR is no design change. A PR that changes a promise the design states changes that
  sentence; a new feature gets a few sentences; how the code does it, flags, keys, edge cases, measurements, and
  history never go there. A section past about 100 lines is pruned before it grows.
- Add a dependency judiciously: when it clearly beats the code we would write instead, and its PR says why. It gets a
  `docs/DECISIONS.md` entry only when it passes that file's bar: code across canopy is shaped around it, it handles
  untrusted input, or it would otherwise be proposed again. Most need none. A dev-only tool (a linter, a checker, a
  test plugin) gets a comment where it is configured saying what it is for.
- Most PRs add no decision entry. `docs/DECISIONS.md` holds only what every future agent must know, whatever part of
  the code it works on: a constraint that spans the codebase, a rule the trust boundary relies on, or a direction the
  operator settled. The test: could an agent working on an unrelated part of canopy break it, or reopen it, without
  knowing? If not, it is not a decision entry. Why a feature behaves as it does, and what was rejected for it, goes in
  the design next to the behavior; why a line of code is so goes in a comment there; the story of a change goes in its
  PR; progress goes on the milestone's lines in `docs/roadmap/`. A new feature, command, config key, default, or
  dependency is not a decision by itself. When in doubt, leave it out.
- An entry that passes is short: a title that states the decision and two to four one-line bullets. The bar and the
  format are at the top of `docs/DECISIONS.md`.
- `docs/TRUST_MODEL.md`, `.agents/prompts/overseer.md`, and everything under `.agents/agents/` define what the loop is
  allowed to do. A PR that changes them says in its summary what the change lets the loop do; the operator approves it
  by merging the PR, and no separate approval note is asked for.
- An issue you file carries labels from each group, before anything else about it is worked out:
  - **Type**, one: `bug`, `enhancement`, `documentation`, `measure` (a measurement for `docs/MEASUREMENTS.md`), or
    `milestone` (tracks a ROADMAP milestone; the roadmap is the record, the issue holds the discussion).
  - **Priority**, one: `P0` next up (misleads the operator, wastes runs, or blocks other work), `P1` high, `P2`
    medium, `P3` low or waiting on something else, `P4` parked on purpose, such as a deferred milestone. Keep P0 and
    P1 short enough to mean something; when a tier crowds, move something down. An issue marked `needs-live-check`
    takes none.
  - **Area**, one or more: `area: ui`, `loop`, `runs`, `reviews`, `workspaces`, `trust`, `prompts`, `memory`.
  - **Status**, only when it applies: `needs-decision` when the operator must settle something first, `blocked`
    when it waits on another issue, which its body or a comment names, and `needs-live-check` when it is built and
    waits only on the operator's live check in real use.

  Other labels are canopy's own: the queue label and `needs-human`, which the loop reads and writes, and `agent` on
  its PRs. Never set those by hand to file an issue.
- When unsure, prefer the smaller change and leave a note in the PR. Do not invent requirements.

## Toolchain

- Python 3.12+. Package layout `src/canopy/`, in layered subpackages (DESIGN §5, D041). CLI entry point `canopy`.
- `uv` for everything: `uv sync`, `uv run`, `uv tool install`.
- `ruff` for formatting and linting. `pyrefly` in strict mode for type checking. `pytest` for tests, in strict mode,
  where a warning fails the test that raised it.
- `rumdl` lints and formats Markdown with every default rule. `editorconfig-checker` (`ec`) holds every file that is
  not Python or Markdown to `.editorconfig`. `shellcheck` lints shell scripts, `actionlint` the GitHub workflows, and
  `zizmor` their security: every action is pinned to a commit, and a finding it allows is ignored inline with a reason.
  All are dev dependencies, so `uv sync` installs them and `make lint` runs them. `make lint` also type-checks the
  agent plugin's JSDoc with `tsc`, from npm packages in `tests/plugins`, so it needs Node 22.12+ and npm, as `ui/` does.
- ruff selects every stable rule, and preview rules named one by one, the pydoclint ones among them (D018): a public
  module, class, or function has a Google docstring, with Returns, Yields, and Raises sections that match its body.
  Every docstring, a test's included, opens with a one-line summary ending in a period, and a blank line before
  anything more. A function whose parameters its signature does not explain should have an Args section; it is not
  required, and older code without one needs no bulk fix: add it to a function a PR is already changing. Opt out with
  a commented `ignore` entry or a `noqa` with a code; never narrow `select`.
- `make all` runs fmt, lint (including type checks), and tests; `make check` is the same without fmt, and never
  rewrites files. CI runs `make check`, as two jobs side by side (`lint test` and `ui-check`), and is the backstop
  for the whole suite. An agent does not run `make all` or `make check` before pushing unless the operator asks.
  Every formatter and linter is cheap, so it runs them all; the tests it runs are the ones its change reaches.
  - Always `make fmt` and `make lint`: every formatter, then every linter and the type checker, over the whole
    repository, in seconds. A change under `ui/` also runs `npm --prefix ui run lint` and `typecheck`.
  - Optionally `make hooks`, once per clone: prek's git hooks (`prek.toml`) then run the same formatters and linters
    on each commit's files, and `ui/`'s lint and type check on a push. They stop a commit that fails one; they do not
    replace the step above. A Claude Code cloud session installs them when it starts (`.claude/settings.json`).
  - Tests: `uv run pytest -q <test modules>` for the package you changed, which sits parallel to it under `tests/`
    (add `-n auto` for a directory). Add the whole-canopy tests your change can trip: `tests/canopy/test_layers.py`
    for a new import, module, or test helper, `test_frozen.py` for a dataclass, `test_prompt_sizes.py` for a prompt,
    `core/test_db.py` and `core/test_records.py` for a migration or row type. A change to a shared fixture or helper
    in `tests/` runs the modules that use it. Under `ui/`, the unit tests and specs `ui/AGENTS.md` names.
  - Bringing the base branch in, by a merge or a rebase: the tests of the files whose conflicts you resolved by hand,
    and `core/test_db.py` and `core/test_records.py` for a migration you renumbered. A merge git made alone runs no
    tests: CI runs the suite on the result. Never a whole directory, nor again the tests the branch ran before.

  CI skips every check on a pull request that changes only docs, and the Python tests on one that changes only `ui/`
  and docs, so there the checks you run are the only ones.
- `make install-check` installs canopy with `uv tool install` into an empty HOME and runs a dry tick against the
  fakes (D046). CI runs it too; run it when you change packaging, bundled files, or the install steps.
- A pull request's CI is the run GitHub starts for it. Never start CI by hand on a branch with an open pull request
  (`workflow_dispatch`, from the Actions page or the API): the manual run shares the pull request's concurrency group
  and cancels its run, and a required check left cancelled keeps the pull request from merging though the manual run
  passed. A run GitHub has not started yet is waited for, not replaced; a job that failed is re-run in its own run.
- Stdlib first: `sqlite3`, `tomllib`, `subprocess`, `fcntl`, `json`, `logging`. Add a third-party dependency only when
  stdlib makes the code materially worse, and say why in its PR. Adopted so far: `click` for every command line, the
  workspace members' too, never argparse (D025), `pydantic` for validating config and anything parsed from another
  program's output (D026), `hypothesis` for property tests of input validators (dev only), `pytest-xdist` to run the
  tests in parallel (dev only), `rich` for terminal output (D043), `fastapi` and `uvicorn` for the web UI's server
  (D074, only in `canopy.serve`), `tomlkit` for its edits to the private config (D129, only in `canopy.serve`), and
  `httpx2` for its test client (D079) and, only in the workspace member `canopy-http`, for every HTTP request the
  programs canopy ships make (D130), `syrupy` for snapshot tests (dev only), `jsonschema` to hold an MCP tool's
  result to its output schema (dev only), and `opentelemetry-sdk` for traces (D132, only in `canopy.infra`).
- The web UI lives in `ui/` (D079) and has its own rules: read `ui/AGENTS.md` before touching it. It needs Node 22.12+
  and npm; `make check` runs its checks, and `make ui-e2e` its Playwright tests.
- Nothing tracker- or VCS-API-specific is ever imported by the harness, `src/canopy`. No Jira client, no GitHub
  client: canopy's own GitHub programs, `packages/canopy-github` (D003), and its Jira connector, `packages/canopy-jira`,
  are separate programs it runs as commands.
  The harness reaches those systems only through the agent runtime's MCP servers and the commands its config names,
  and knows nothing about Jira or GitHub beyond strings in config and prompts.

## Formatting

**Maximum line length is 120 characters. For every file type, not just Python.**

- This covers Python, Markdown, TOML, YAML, SQL, shell, prompts, and anything else in the repo.
- `.editorconfig` is the source of truth for whitespace: `max_line_length = 120`, UTF-8, LF line endings, final
  newline, 4-space indent (2 for TOML, YAML, JSON, SQL; tabs in `Makefile`). Configure your editor to honor it.
- `ruff` enforces 120 for Python (`[tool.ruff] line-length = 120`), `rumdl` for Markdown (`[tool.rumdl] line-length`),
  and `ec` for every other file, from `.editorconfig`. Keep the three in sync.
- Do not introduce any other line-length target (80, 88, 100). Do not reflow existing text just to fill 120 columns;
  wrap new or edited prose at 120.
- The only exceptions are lines that cannot be broken: long URLs, Markdown tables and code blocks, a worker prompt's
  one-line JSON result, and generated files such as `uv.lock`.

## Code conventions

- Fully typed. `pyrefly` strict clean, the test fakes included.
- A parameter takes the most general type its body needs; a return keeps the concrete type it builds. `Iterable` for one
  pass; `Collection` for `len`, `in`, or more than one pass; `Sequence` for indexing, slicing, `reversed`, or an order
  the output keeps; `Mapping` for a dict only read. A `set` or `frozenset` tested with `in` becomes
  `collections.abc.Set`, imported as `AbstractSet`, not `Collection`: a `Collection[str]` would also take a bare `str`,
  where `in` is a substring test. A parameter stays concrete when the function mutates, stores, or returns it, or hands
  it to `json.dumps` or `isinstance`; a click command's parameters stay the tuple click passes. No linter checks this,
  so review does.
- A frozen dataclass holds no mutable collection type: a field is typed `Sequence`, `Collection`, `Mapping`, or
  `Set` (as `AbstractSet` where imported so) by what its readers need, as a parameter is, so the type checker refuses
  a change through it. A class that keeps state it changes is not frozen. `tests/canopy/test_frozen.py` fails on a
  `list`, `dict`, or `set` field.
- Deterministic core. The Python code never calls an LLM. It runs agent processes and reads their output.
- Everything canopy knows of the agent runtime, OpenCode, lives in its implementations, `src/canopy/runtime/opencode/`
  (OpenCode 1, the default) and `src/canopy/runtime/opencode2/` (OpenCode 2, when `runtime.version` is 2) (D009): its
  command line and variables, the events it prints, the format of canopy's agent definitions, and its config files.
  Code elsewhere calls the `runtime` package's surface, which names no runtime and takes the version from config; only
  `runtime/implementation.py` imports the implementations. `tests/canopy/test_layers.py` fails on a string outside
  them that names OpenCode, or an import past it.
- Every external process (`treehouse`, `git`, the agent runtime, `notify`) goes through `src/canopy/infra/procs.py`.
  Nothing else calls `subprocess`. This is the seam tests use. ruff's banned-api rule (`TID251`) fails the lint if
  anything else imports it.
- Every command line is click, never argparse: canopy's CLI and every program it ships, the workspace members' too
  (D025); ruff's banned-api rule fails the lint on an argparse import in `src/canopy`. Options or setup two programs
  share, such as reading an operator-only secret file, go in a common workspace member, never copied into each.
- Modules are small and named for what they own, in the package for their layer (DESIGN §5): `core/db.py`,
  `infra/lock.py`, `runs/dispatch.py`, `loop/attention.py`, `cli/main.py`. Imports go down the layers, never between
  features, and only `cli/` imports click, besides the two programs canopy ships in its own package, the desktop sink
  and `python -m canopy.serve`; `tests/canopy/test_layers.py` fails otherwise. A new package gets a layer there and a
  line in DESIGN §5. A separate program (a notification sink) is a uv workspace member, not a package.
- No global mutable state. Pass a `Context` (config, db connection, paths).
- Config is not downgrade-compatible. An unknown key stays an error, so an older release rejects a key a newer one
  added; that is expected, since a release already out cannot be fixed. A review finding about it needs no code.
- Every module is in newspaper order, so it reads top-down from what to how: the docstring, then the public names
  other modules use, most important first, then the private helper functions, each below the first function that
  calls it. What Python needs at import time comes first regardless: constants, type aliases, and anything used as a
  base class, decorator, or default value. `runs/dispatch.py` and `notify/deliver.py` are examples. A module still out
  of order is never a reason to hold a change, and needs no bulk fix: write new modules in order, and reorder an old
  one when a PR is already changing it, if that is cheap.
- A comment that says what a name is, for a module's constant or type alias, a class attribute, a field of a
  dataclass, pydantic model, or `NamedTuple`, or an enum member, is a Sphinx doc comment: lines starting `#:`
  directly above the name, so editors and doc tools attach it to the name. A note on why the code is so stays a plain
  `#`. A class's docstring says what the class is; what one field holds goes on that field, not in the docstring.
  `runs/dispatch.py` is an example. Older modules still spell these with `#`, and need no bulk fix: write new ones
  with `#:`, and convert a module's when a PR is already changing it, if that is cheap.
- SQLite: WAL mode, `PRAGMA foreign_keys=ON`, numbered migrations in `migrations/NNNN_name.sql` applied in order at
  startup, recorded in a `schema_migrations` table. Never edit a shipped migration; add a new one. The series was
  squashed into `0001_init.sql` once, for v0.1 (D068); that is not a precedent for editing one.
  A new migration gets a companion, `tests/canopy/core/migrations/NNNN.sql` for the same version, opening with the
  migration's sha256 and holding a row for each table it creates; `tests/canopy/core/test_db.py` fails on an edited
  migration, and applies every migration to a journal with data in it and fails on any row lost. Two PRs that take the
  same version conflict on the companion: the one merged second renumbers its migration and companion both.
- Every query on the journal is built with `core/sql.py` (D125), or started by `records.select`, and run through
  `sql.execute`, `sql.execute_many`, `records.fetch_all`/`fetch_one`, a query's `all`/`one`, or a write's `run`: clause
  text is literal SQL, each value a `?`, a piece built elsewhere a `{}`, and a table or column chosen at run time a
  `Literal` or `sql.name`, and a value that differs per row of `sql.execute_many` a `sql.ROW`. Never an f-string, `%`,
  or `+` into SQL.
- A query that returns a table's whole rows reads them as that table's row type in `core/records/`, not as
  `sqlite3.Row`: `records.select(records.Run).where(...).all(conn)`, which names the table and its columns from the row
  type, or `records.fetch_all`/`fetch_one` for a statement built elsewhere. New code reads a query of some columns, or
  of a join, as a `records.View` defined beside it, not as `sqlite3.Row`; older code converts when a PR is already
  changing it. Every table has a row type, and a new table gets its row type in the PR that adds it, in its
  domain's module of `core/records/`.
  `tests/canopy/core/test_records.py` holds each row type to its table, so a migration that adds a column to a typed
  table adds the field too. A status, kind, or phase column is a field of its `core/vocab.py` enum, so the row carries
  the member and refuses a value the vocabulary does not hold. A helper that reads the same columns from several tables,
  some still untyped, reads them through `records.columns`.
- A write starts from its table's row type too: `records.insert`, `insert_rows`, `insert_from`, `update`, or `delete`,
  ended by its `run(conn)`, `returned(conn)` for the rows it wrote read back as the row type, or `Insert.many` for many
  rows. Each column it names must be a field, and each value one the field reads back, a vocabulary's member included,
  checked as the statement is built. A table chosen at run time is `records.of_table(name)` of a `Literal`. ruff's
  banned-api rule fails the lint on `sql`'s own write builders anywhere else.
- A run's and a tick's status, a run's kind, and a ticket's phase are closed vocabularies in `core/vocab.py`, each a
  `StrEnum`. New code writes and compares them through its members, not bare strings, and converts a value read from the
  journal where it branches on it. A branch over one is a `match` ending in `case _: assert_never(...)`, so a new value
  fails the type check until every branch handles it. click matches an enum choice by its name, so a `click.Choice` over
  one takes its values. A table made from M36 on constrains each `status`, `kind`, and `phase` column with
  `CHECK (column IN (...))`; `tests/canopy/core/test_db.py` fails on one that does not.
- Hard guards live in code, judgment lives in prompts. Capacity limits, attempt limits, cooldowns, "never merge", and
  "one worker per ticket" are enforced by the harness regardless of what the overseer asks for.
- Log with `logging`, JSON lines to `.canopy/canopy.log` in the workspace. Every tick has an id that appears in every
  log line it produces.

## Testing

- Unit tests fake external processes through `canopy.infra.procs`, never by patching `subprocess` in scattered places.
- Patch with `unittest.mock`, as context managers, never pytest's `monkeypatch`. Import the namespace,
  `from unittest import mock`, and spell it out: `mock.patch.dict(os.environ, {...})` for environment variables (pop
  a variable inside the block to unset it), `mock.patch.object(module, "NAME", value)` for an attribute, and
  `contextlib.chdir` for the working directory. ruff fails the lint on `pytest.MonkeyPatch` and on
  `from unittest.mock import ...`.
- A mock is specced: `mock.patch.object(module, "fn", autospec=True)`, with `side_effect` or `return_value` for what
  it does, or `mock.create_autospec(...)`, so a call the real thing would refuse fails the test. Never a bare
  `Mock()` or `MagicMock()`; ruff fails the lint on them. Patching a plain value (a limit, a constant) needs no spec.
- A patch lasts as long as its `with` block. A fixture that patches yields inside the block. A helper that sets up
  state for the code after it is a context manager (`with in_tick(conn) as tick_id:`, `with worker_does(...):`), and
  a helper that needs a patch only while it runs opens and closes its own. `hermetic_agent_env` restores the whole
  environment after every test, as a backstop, not a license to set `os.environ` directly.
- `tests/fakes/treehouse` is an executable fake that speaks the same CLI (`status --json`, `get --lease --json`,
  `return`) and keeps its state in a temp file. It is put on `PATH` by fixtures.
- The fake agent command is `tests/fakes/agent`, a script that prints a configurable final JSON line. Tests configure
  it through an env var.
- Fixtures live in `tests/conftest.py`: `fakes_on_path`, `treehouse_state` (the fake pool's state file), `agent_log`
  (what each fake agent run saw), and `canopy_env` (a workspace of one repository, `repo`, and a user config in a temp
  directory, with HOME pointed there; commands that name a repository pass `--repo repo`; `append_user` and
  `append_shared` add to its config files). Each fake's docstring lists the env vars and state keys it reads. The fake
  agent can call canopy's tools through the server its inline config names (`FAKE_AGENT_TOOLS`), which is how a test
  plays an overseer calling `canopy_decide`, and run commands (`FAKE_AGENT_COMMANDS`). Beside them are the plain
  helpers every test may need: `git`, and `executable` for a script a test puts on a path.
- What two test modules share lives in one place, never in a test module: `tests/canopy/conftest.py` for fixtures
  (`conn`, the workspace's journal; `ctx`; the web UI's mock `backend`; `ws`; `notified` and `sink_script`, notification
  commands that record what they are sent), `tests/canopy/helpers.py` for helpers (`in_tick`, with `ends_ok=True` for a
  tick that ends as the block does; `in_run`; `decisions`, `last_tick`, `dispatch_and_run`, `messages`; `present`, for a
  row the test knows is there; the overseer's moves, each a call of one of its tools, `decides`, `waits`, `raises`,
  `ticket_sets`, or any `calls(...)`, which `overseer_calls` makes in this process; and scripting the fake agents:
  `overseer_does(decides(KEY))`, `worker_does(sleep=60)`, `chore_reports`), and `web_helpers.py`, `review_helpers.py`,
  and `scenario_helpers.py` beside it. A test module imports from no other; `tests/canopy/test_layers.py` fails
  otherwise. Look there before writing a helper, and move one there once a second module needs it. A test that plays
  an overseer, a worker, or another agent scripts it through those helpers, not by patching its `FAKE_*` variables
  itself; `test_procs.py`, which tests the runner rather than a role, sets them directly.
- A test that tells a ticket's story, ticks and runs and the operator's commands in turn, tells it through the
  `scenario` fixture (`scenario_helpers.py`): `scenario.tick(dispatches(kind=RunKind.RESUME, ...), worker=pushes())`
  checks the tick's exit and waits for the runs it started, and `scenario.run(...)` runs one without the overseer. The
  workers of a tick that dispatches several tickets each play their script as made for their own ticket, so `pushes()`
  pushes that ticket's branch, and `workers={"PROJ-2": fails()}` gives one ticket a script of its own. The
  overseer is played whole: `scenario.tick(queried=["PROJ-9"], code=1)` is a tick that leaves a duty undone, and
  `result=` and `exit_code=` one it fails. A run comes back as a `Ran`, with its `reasons`, its worker's `prompt`, and,
  from `scenario.run`, what its `canopy _run` printed (`.printed`), the run log among it; `runner=` gives that run a
  runner of its own, one that times its worker out. `scenario.refuses(...)` is a dispatch canopy turns down, as the
  decisions it made instead, and `scenario.time_passes(minutes=31)` moves the journal's times into the past, never an
  `UPDATE` of one table's times.
  A review is the overseer's move as a dispatch is: `scenario.review(reviews(sha, ticket=KEY), reviewer=...)` starts one
  in a tick of its own and does it in this process, giving back a `Reviewed`, and `scenario.refuses(reviews(...))` is
  one canopy turns down.
  The config is set the same way: `scenario.configures(policy={"max_resume_attempts": 2})` merges keys into the user
  file, or into the `"workspace"` or `"private"` file named first, never TOML appended to whatever table is last.
  A run the story goes on around is held at work, `scenario.starts(...)` or `scenario.tick(..., hold=True)`, whatever
  role its agent plays, and a review the same way, `scenario.starts_review(reviews(...))`, until the test says it
  `finishes()` or `dies()`, rather than an agent left to sleep or a row with a made-up pid.
  The operator is played whole too: `scenario.operator("grant", KEY, "fix-ci", code=1)` is a command canopy refuses,
  and it and a tick give back what canopy printed (`.out`, `.err`; a tick's `.printed`), and a refusal what it said,
  read from the move rather than from `capsys`. So is one of the overseer's calls outside a tick it runs:
  `scenario.overseer(ticket_sets(KEY, phase="approved"), error=True)`, in a tick of its own, or in one shared with
  the others inside `with scenario.ticking():`, giving back what it came back with (`.text`, `.error`). A key the
  story drops is set to None,
  `configures(notify={"sinks": {"slack": None}})`, and a worker that sends drafts `sends_drafts([...])`.
  A story in the workspace of two repositories, `api` and `web`, is told the same way through `ws_scenario`, whose
  pools are seeded: each dispatch names its repositories, `dispatches(repo=("api", "web"))`, and a joint run's worker
  `pushes(repos=("api", "web"))` in each.
  A scenario keeps the story as it played, and a failed test's report prints it, a numbered step for each move; a step
  the scenario cannot record stays out of it, so prefer a verb where one fits. A step the verbs do not cover is written
  with the helpers above, in the same test; a verb two tests need goes there.
- A test opens a journal through `canopy_env.journal()`, or the `journals` fixture for one outside a workspace, never
  `db.connect` directly: those close it when the test ends. A connection, file, or pipe left open raises a
  ResourceWarning, which fails the test like any other warning.
- Every test directory has an `__init__.py`, `tests/` included (D019). ruff's `INP001` fails the lint on one that does
  not. The root one matters most: without it, `tests/canopy/` is imported as a package named `canopy` and shadows
  `src/canopy`.
- A test module sits parallel to the package it tests: `tests/canopy/runs/` holds the tests of `canopy.runs`, and
  `tests/canopy_sandbox/` those of the workspace member `canopy_sandbox`. A feature's tests go with the package that
  owns it, even when they drive it through the CLI; only tests of canopy as a whole (its layers, its models, its
  property tests, the OpenCode canary) sit in `tests/canopy/` itself. `tests/canopy/test_layers.py` fails on a test
  module anywhere else.
- One end-to-end test runs `canopy tick --dry-run` against the fakes and asserts on the `decisions` and `ticks`
  tables.
- What canopy renders whole, such as the overseer's state block, is held by a snapshot test: a journal written by hand,
  the output compared with syrupy's `snapshot` fixture, or `markdown_snapshot` for a file a person can read whole,
  recorded in the test's `__snapshots__/` directory.
  `make snapshots` records the ones that differ, and the diff is reviewed with the change. A snapshot holds canopy's
  output, never a model's.
- A test waits on a condition, never on time: a loop with a deadline that polls for what it needs, `expect.poll` or
  `toPass` in Playwright, fake timers in Vitest; never a fixed sleep or `waitForTimeout`. A position on the page is
  compared within a pixel, never to a fraction of one. When a test is suspected of being flaky, run it many times over:
  `make burn-in` (and `make ui-e2e-burn-in` for a Playwright spec) runs the tests a branch changed, or every test with
  `ALL=1`, and the Flaky tests workflow does the same on CI's runners, on demand. Neither runs unasked. A PR that fixes
  a flaky test says it passed the burn-in: one green run cannot tell a fix from a failure made rarer.
- Prompts are not unit-tested. `canopy tick --dry-run` writes the overseer's plan to the `decisions` table; that table
  is the evaluation corpus for prompt changes. Do not add prompt "tests" that assert on model output.
  Their sizes are recorded in `.agents/sizes.toml`. The number is a record, not a limit: grow or shrink a prompt as
  the work needs and update its number in the same PR, so the diff shows by how much.
  `tests/canopy/test_prompt_sizes.py` names the line to update, and `make prompt-sizes` prints the sizes with
  estimated tokens.

## Do not build (unless a ROADMAP milestone says so)

- Web UI pages or features that neither a milestone lists nor the operator asked for. `canopy status` and a markdown
  file stay the CLI's surface.
- Webhooks, network listeners, or background services. The loop is `canopy loop`, which runs one tick after another,
  in the foreground or detached by `canopy daemon`; nothing installs it with the OS or restarts it (D042). A milestone
  that adds a listener follows TRUST_MODEL T8 (D055).
- A tracker adapter interface. The tracker is a prompt and config concern.
- A runtime plugin interface. The agent runtime is a command template in config.
- Sandboxing beyond what ROADMAP M26 lists. It plugs into the command template; see DESIGN §24.
- A bot identity. MVP runs as the operator.
- Anything that approves or merges PRs, or transitions tickets to Done.
- Retry logic inside the worker. A worker may push again for a fix it finds (D116), but never polls CI or retries a
  rejected push.
- Multi-machine coordination.

## Definition of done for a PR

- The checks and tests the change reaches pass (Toolchain), and CI passes.
- New behavior has a test using the fakes.
- Docs updated: the design only where it states a promise this changes, within its bar, `README.md` if the install
  path or daily surface changed (and the install path is still five steps), the web UI's guide (`ui/src/guide/`) where
  a page of it describes what changed, in the guide's own voice (`ui/AGENTS.md`), and `DECISIONS.md` only if the
  change passes its bar.
- No new capability lets the loop do something `TRUST_MODEL.md` says it must not.
