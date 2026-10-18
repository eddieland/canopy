# AGENTS.md

Instructions for any agent working in this repository. Humans should read it too.

## Read this first, in order

1. `README.md`: what we are building and for whom.
2. `docs/REQUIREMENTS.md`: what the primary operator needs, where canopy stands on each, and open conflicts.
3. `docs/design/README.md`: target shape. Normative. It holds the overview and maps the rest of the design, in the
   same directory; read the sections your work touches.
4. `docs/TRUST_MODEL.md`: security posture. Normative.
5. `docs/ROADMAP.md`: milestones and acceptance criteria. Work in this order.
6. `docs/DECISIONS.md`: the few choices every agent must know, whatever it works on. Read it whole; add to it rarely.

If code and the design disagree, the design doc wins until a decision entry says otherwise.

## How to work

- Work one milestone at a time. Do not start milestone N+1 until milestone N meets its acceptance criteria.
- Keep the milestone's `Status:` line in `docs/ROADMAP.md` current. The PR that meets the acceptance criteria marks it
  done with the date, what was learned, and how that changes next steps. The format is at the top of that file. Read
  earlier milestones' `Learned` and `Next` before starting a new one.
- A live measurement a milestone cites goes in `docs/MEASUREMENTS.md`: one dated section each, not edited after, so a
  re-measurement is a new section.
- A live check worth running again, against real systems, goes in `docs/SCENARIOS.md`, naming the milestone it came
  from. A milestone the operator closes on real use, before every live check in its Accept has run, moves the
  unrun ones there.
- Small PRs. One concern per PR. Conventional commit messages.
- A behavior change updates the docs that state it, in the same PR: a PR that changes what a tick does and leaves the
  design saying otherwise is incomplete. The design says what canopy does and why, not how the code does it; what
  belongs there, and where the rest goes, is at the top of `docs/design/README.md`. Most PRs add a sentence there, or
  change one, or none.
- Add a dependency judiciously: when it clearly beats the code we would write instead, and its PR says why. It gets a
  `docs/DECISIONS.md` entry only when it passes that file's bar: code across canopy is shaped around it, it handles
  untrusted input, or it would otherwise be proposed again. Most need none. A dev-only tool (a linter, a checker, a
  test plugin) gets a comment where it is configured saying what it is for.
- Most PRs add no decision entry. `docs/DECISIONS.md` holds only what every future agent must know, whatever part of
  the code it works on: a constraint that spans the codebase, a rule the trust boundary relies on, or a direction the
  operator settled. The test: could an agent working on an unrelated part of canopy break it, or reopen it, without
  knowing? If not, it is not a decision entry. Why a feature behaves as it does, and what was rejected for it, goes in
  the design next to the behavior; why a line of code is so goes in a comment there; the story of a change goes in its
  PR; progress goes on the milestone's lines in `docs/ROADMAP.md`. A new feature, command, config key, default, or
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
    P1 short enough to mean something; when a tier crowds, move something down.
  - **Area**, one or more: `area: ui`, `loop`, `runs`, `reviews`, `workspaces`, `trust`, `prompts`, `memory`.
  - **Status**, only when it applies: `needs-decision` when the operator must settle something first, and `blocked`
    when it waits on another issue, which its body or a comment names.

  Other labels are canopy's own: the queue label and `needs-human`, which the loop reads and writes, and `agent` on
  its PRs. Never set those by hand to file an issue.
- When unsure, prefer the smaller change and leave a note in the PR. Do not invent requirements.

## Toolchain

- Python 3.12+. Package layout `src/canopy/`, in layered subpackages (DESIGN §5, D041). CLI entry point `canopy`.
- `uv` for everything: `uv sync`, `uv run`, `uv tool install`.
- `ruff` for formatting and linting. `pyrefly` in strict mode for type checking. `pytest` for tests, in strict mode,
  where a warning fails the test that raised it.
- `rumdl` lints and formats Markdown with every default rule. `editorconfig-checker` (`ec`) holds every file that is
  not Python or Markdown to `.editorconfig`. `shellcheck` lints shell scripts and `actionlint` the GitHub workflows.
  All are dev dependencies, so `uv sync` installs them and `make lint` runs them.
- ruff selects every stable rule, and preview rules named one by one, the pydoclint ones among them (D018): a public
  module, class, or function has a Google docstring, with Returns, Yields, and Raises sections that match its body.
  Opt out with a commented `ignore` entry or a `noqa` with a code; never narrow `select`.
- `make all` runs fmt, lint (including type checks), and tests. It must pass before any PR.
- `make check` is `make all` without fmt: it verifies and never rewrites files. CI runs it, as two jobs side by side
  (`lint test` and `ui-check`), except on a pull request that changes only docs, where every check passes without
  running; run `make all` before pushing one anyway.
- `make install-check` installs canopy with `uv tool install` into an empty HOME and runs a dry tick against the
  fakes (D046). CI runs it too; run it when you change packaging, bundled files, or the install steps.
- Stdlib first: `sqlite3`, `tomllib`, `subprocess`, `fcntl`, `json`, `logging`. Add a third-party dependency only when
  stdlib makes the code materially worse, and say why in its PR. Adopted so far: `click` for the CLI (D025),
  `pydantic` for validating config and anything parsed from another program's output (D026), `hypothesis` for property
  tests of input validators (dev only), `pytest-xdist` to run the tests in parallel (dev only), `rich` for terminal output
  (D043), `fastapi` and `uvicorn` for the web UI's server (D074, only in `canopy.serve`), and `httpx2` for its test
  client (D079, dev only), and `syrupy` for snapshot tests (dev only).
- The web UI lives in `ui/` (D079) and has its own rules: read `ui/AGENTS.md` before touching it. It needs Node 22.12+
  and npm; `make check` runs its checks, and `make ui-e2e` its Playwright tests.
- Nothing tracker- or VCS-API-specific is ever imported by the harness, `src/canopy`. No Jira client, no GitHub
  client: canopy's own GitHub programs, `packages/canopy-github` (D003), are separate programs it runs as commands.
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
- Deterministic core. The Python code never calls an LLM. It runs agent processes and reads their output.
- Every external process (`treehouse`, `git`, the agent runtime, `notify`) goes through `src/canopy/infra/procs.py`.
  Nothing else calls `subprocess`. This is the seam tests use. ruff's banned-api rule (`TID251`) fails the lint if
  anything else imports it.
- Modules are small and named for what they own, in the package for their layer (DESIGN §5): `core/db.py`,
  `infra/lock.py`, `runs/dispatch.py`, `loop/attention.py`, `cli/main.py`. Imports go down the layers, never between
  features, and only `cli/` imports click; `tests/canopy/test_layers.py` fails otherwise. A new package gets a layer
  there and a line in DESIGN §5. A separate program (a notification sink) is a uv workspace member, not a package.
- No global mutable state. Pass a `Context` (config, db connection, paths).
- Config is not downgrade-compatible. An unknown key stays an error, so an older release rejects a key a newer one
  added; that is expected, since a release already out cannot be fixed. A review finding about it needs no code.
- Every module is in newspaper order, so it reads top-down from what to how: the docstring, then the public names
  other modules use, most important first, then the private helper functions, each below the first function that
  calls it. What Python needs at import time comes first regardless: constants, type aliases, and anything used as a
  base class, decorator, or default value. `runs/dispatch.py` and `notify/deliver.py` are examples. A module still out
  of order is never a reason to hold a change, and needs no bulk fix: write new modules in order, and reorder an old
  one when a PR is already changing it, if that is cheap.
- SQLite: WAL mode, `PRAGMA foreign_keys=ON`, numbered migrations in `migrations/NNNN_name.sql` applied in order at
  startup, recorded in a `schema_migrations` table. Never edit a shipped migration; add a new one. The series was
  squashed into `0001_init.sql` once, for v0.1 (D068); that is not a precedent for editing one.
  A new migration gets a companion, `tests/canopy/core/migrations/NNNN.sql` for the same version, opening with the
  migration's sha256 and holding a row for each table it creates; `tests/canopy/core/test_db.py` fails on an edited
  migration, and applies every migration to a journal with data in it and fails on any row lost. Two PRs that take the
  same version conflict on the companion: the one merged second renumbers its migration and companion both.
- A query that returns a table's whole rows reads them as that table's row type in `core/records.py`
  (`records.fetch_all`, `records.fetch_one`), not as `sqlite3.Row`. A new table gets its row type in the PR that adds
  it, and an old one when a PR already changes its queries. `tests/canopy/core/test_records.py` holds each row type to
  its table, so a migration that adds a column to a typed table adds the field too. A status, kind, or phase column is a
  field of its `core/vocab.py` enum, so the row carries the member and refuses a value the vocabulary does not hold. A
  helper that reads the same columns from several tables, some still untyped, reads them through `records.columns`.
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
  agent can run commands (`FAKE_AGENT_COMMANDS`), which is how a test plays an overseer calling `canopy decide`. Beside
  them are the plain helpers every test may need: `git`, and `executable` for a script a test puts on a path.
- What two test modules share lives in one place, never in a test module: `tests/canopy/conftest.py` for fixtures
  (`conn`, the workspace's journal; `ctx`; the web UI's mock `backend`; `ws`; `notified` and `sink_script`, notification
  commands that record what they are sent), `tests/canopy/helpers.py` for helpers (`in_tick`, with `ends_ok=True` for a
  tick that ends as the block does; `in_run`; `decisions`, `last_tick`, `dispatch_and_run`, `messages`; `present`, for a
  row the test knows is there; and scripting the fake agents: `overseer_does(canopy(...))`, `worker_does(sleep=60)`,
  `chore_reports`), and `web_helpers.py`, `review_helpers.py`, and `scenario_helpers.py` beside it. A test module
  imports from no other; `tests/canopy/test_layers.py` fails otherwise. Look there before writing a helper, and move one
  there once a second module needs it. A test that plays an overseer, a worker, or another agent scripts it through
  those helpers, not by patching its `FAKE_*` variables itself; `test_procs.py`, which tests the runner rather than a
  role, sets them directly.
- A test that tells a ticket's story, ticks and runs and the operator's commands in turn, tells it through the
  `scenario` fixture (`scenario_helpers.py`): `scenario.tick(dispatches(kind=RunKind.RESUME, ...), worker=pushes())`
  checks the tick's exit and waits for the runs it started, and `scenario.run(...)` runs one without the overseer. A
  step the verbs do not cover is written with the helpers above, in the same test; a verb two tests need goes there.
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

## Do not build (unless a ROADMAP milestone says so)

- Web UI pages or features no milestone lists. `canopy status` and a markdown file stay the CLI's surface.
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

- `make all` passes.
- New behavior has a test using the fakes.
- Docs updated: the design where it states the behavior, within its bar, `README.md` if the install path or daily surface
  changed (and the install path is still five steps), the web UI's guide (`ui/src/guide/`) where a page of it
  describes what changed, in the guide's own voice (`ui/AGENTS.md`), and `DECISIONS.md` only if the change passes
  its bar.
- No new capability lets the loop do something `TRUST_MODEL.md` says it must not.
