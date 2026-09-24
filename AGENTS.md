# AGENTS.md

Instructions for any agent working in this repository. Humans should read it too.

## Read this first, in order

1. `README.md`: what we are building and for whom.
2. `docs/DESIGN.md`: target shape. Normative.
3. `docs/TRUST_MODEL.md`: security posture. Normative.
4. `docs/ROADMAP.md`: milestones and acceptance criteria. Work in this order.
5. `docs/DECISIONS.md`: why things are the way they are. Append, never rewrite.

If code and `docs/DESIGN.md` disagree, the design doc wins until a decision
entry says otherwise.

## How to work

- Work one milestone at a time. Do not start milestone N+1 until milestone N
  meets its acceptance criteria.
- Keep the milestone's `Status:` line in `docs/ROADMAP.md` current. The PR
  that meets the acceptance criteria marks it done with the date, what was
  learned, and how that changes next steps. The format is at the top of that
  file. Read earlier milestones' `Learned` and `Next` before starting a new one.
- Small PRs. One concern per PR. Conventional commit messages.
- Every behavior change updates the relevant doc in the same PR. A PR that
  changes the tick algorithm and does not touch `docs/DESIGN.md` is incomplete.
- Every new dependency gets a `docs/DECISIONS.md` entry explaining why stdlib
  was insufficient.
- Changes to `docs/TRUST_MODEL.md`, `prompts/overseer.md`, or anything under
  `agents/` require an explicit human approval note in the PR description.
  These files define what the loop is allowed to do.
- When unsure, prefer the smaller change and leave a note in the PR. Do not
  invent requirements.

## Toolchain

- Python 3.12+. Package layout `src/canopy/`. CLI entry point `canopy`.
- `uv` for everything: `uv sync`, `uv run`, `uv tool install`.
- `ruff` for formatting and linting. `pyrefly` in strict mode for type checking. `pytest` for tests.
- ruff selects every stable rule (D018). Opt out with a commented `ignore` entry or a `noqa` with a code; never
  narrow `select`.
- `make all` runs fmt, lint (including type checks), and tests. It must pass before any PR.
- `make check` is `make all` without fmt: it verifies and never rewrites files. CI runs it.
- Stdlib first: `argparse`, `sqlite3`, `tomllib`, `subprocess`, `fcntl`,
  `json`, `logging`. Add a third-party dependency only when stdlib makes the
  code materially worse, and record why.
- Nothing tracker- or VCS-API-specific is ever imported. No Jira client, no
  GitHub client. Connectivity to those systems is the agent runtime's MCP
  servers. The harness knows nothing about Jira or GitHub beyond strings in
  config and prompts.

## Formatting

**Maximum line length is 120 characters. For every file type, not just Python.**

- This covers Python, Markdown, TOML, YAML, SQL, shell, prompts, and anything else in the repo.
- `.editorconfig` is the source of truth for whitespace: `max_line_length = 120`, UTF-8, LF line endings, final
  newline, 4-space indent (2 for TOML, YAML, JSON, SQL; tabs in `Makefile`). Configure your editor to honor it.
- `ruff` enforces 120 for Python (`[tool.ruff] line-length = 120` in `pyproject.toml`). Keep the two in sync.
- Do not introduce any other line-length target (80, 88, 100). Do not reflow existing text just to fill 120 columns;
  wrap new or edited prose at 120.
- The only exceptions are lines that cannot be broken: long URLs, and generated files such as `uv.lock`.

## Code conventions

- Fully typed. `pyrefly` strict clean, the test fakes included.
- Deterministic core. The Python code never calls an LLM. It runs agent
  processes and reads their output.
- Every external process (`treehouse`, `git`, the agent runtime, `notify`)
  goes through `src/canopy/procs.py`. Nothing else calls `subprocess`. This is
  the seam tests use. ruff's banned-api rule (`TID251`) fails the lint if anything else imports it.
- Modules are small and named for what they own: `db.py`, `lock.py`,
  `treehouse.py`, `dispatch.py`, `attention.py`, `config.py`, `cli.py`.
- No global mutable state. Pass a `Context` (config, db connection, paths).
- SQLite: WAL mode, `PRAGMA foreign_keys=ON`, numbered migrations in
  `migrations/NNNN_name.sql` applied in order at startup, recorded in a
  `schema_migrations` table. Never edit a shipped migration; add a new one.
- Hard guards live in code, judgment lives in prompts. Capacity limits, attempt
  limits, cooldowns, "never merge", and "one worker per ticket" are enforced by
  the harness regardless of what the overseer asks for.
- Log with `logging`, JSON lines to `~/.canopy/canopy.log`. Every tick has an
  id that appears in every log line it produces.

## Testing

- Unit tests fake external processes through `procs.py`, never by monkeypatching
  `subprocess` in scattered places.
- `tests/fakes/treehouse` is an executable fake that speaks the same CLI
  (`status --json`, `get --lease --json`, `return`) and keeps its state in a
  temp file. It is put on `PATH` by fixtures.
- The fake agent command is `tests/fakes/agent`, a script that prints a
  configurable final JSON line. Tests configure it through an env var.
- Fixtures live in `tests/conftest.py`: `fakes_on_path`, `treehouse_state` (the fake pool's state file), and
  `agent_log` (what each fake agent run saw). Each fake's docstring lists the env vars and state keys it reads.
- Every test directory has an `__init__.py`, `tests/` included (D019). ruff's `INP001` fails the lint on one that does
  not. The root one matters most: without it, `tests/canopy/` is imported as a package named `canopy` and shadows
  `src/canopy`.
- One end-to-end test runs `canopy tick --dry-run` against the fakes and asserts
  on the `decisions` and `ticks` tables.
- Prompts are not unit-tested. `canopy tick --dry-run` writes the overseer's
  plan to the `decisions` table; that table is the evaluation corpus for prompt
  changes. Do not add prompt "tests" that assert on model output.

## Do not build (unless a ROADMAP milestone says so)

- A web UI. `canopy status` and a markdown file are the UI.
- Webhooks or long-running daemons. The loop is a scheduled `tick`.
- A tracker adapter interface. The tracker is a prompt and config concern.
- A runtime plugin interface. The agent runtime is a command template in config.
- Sandboxing. It plugs into the command template later; see TRUST_MODEL.
- A bot identity. MVP runs as the operator.
- Anything that approves or merges PRs, or transitions tickets to Done.
- Retry logic inside the worker. Workers push once and exit.
- Multi-machine coordination.

## Definition of done for a PR

- `make all` passes.
- New behavior has a test using the fakes.
- Docs updated: `DESIGN.md` for behavior, `DECISIONS.md` for choices,
  `README.md` if the install path or daily surface changed (and the install
  path is still five steps).
- No new capability lets the loop do something `TRUST_MODEL.md` says it must not.
