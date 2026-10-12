# AGENTS.md

Instructions for any agent working in this repository. Humans should read it too.

## Read this first, in order

1. `README.md`: what we are building and for whom.
2. `docs/REQUIREMENTS.md`: what the primary operator needs, where canopy stands on each, and open conflicts.
3. `docs/DESIGN.md`: target shape. Normative.
4. `docs/TRUST_MODEL.md`: security posture. Normative.
5. `docs/ROADMAP.md`: milestones and acceptance criteria. Work in this order.
6. `docs/DECISIONS.md`: the few choices every agent must know, whatever it works on. Read it whole; add to it rarely.

If code and `docs/DESIGN.md` disagree, the design doc wins until a decision entry says otherwise.

## How to work

- Work one milestone at a time. Do not start milestone N+1 until milestone N meets its acceptance criteria.
- Keep the milestone's `Status:` line in `docs/ROADMAP.md` current. The PR that meets the acceptance criteria marks it
  done with the date, what was learned, and how that changes next steps. The format is at the top of that file. Read
  earlier milestones' `Learned` and `Next` before starting a new one.
- A live measurement a milestone cites goes in `docs/MEASUREMENTS.md`: one dated section each, not edited after, so a
  re-measurement is a new section.
- Small PRs. One concern per PR. Conventional commit messages.
- Every behavior change updates the relevant doc in the same PR. A PR that changes the tick algorithm and does not touch
  `docs/DESIGN.md` is incomplete.
- Every new runtime dependency gets a `docs/DECISIONS.md` entry saying why stdlib was insufficient. A dev-only tool (a
  linter, a checker, a test plugin) gets none; a comment where it is configured says what it is for.
- Most PRs add no decision entry. `docs/DECISIONS.md` holds only what every future agent must know, whatever part of
  the code it works on: a constraint that spans the codebase, a rule the trust boundary relies on, a runtime
  dependency, or a direction the operator settled. The test: could an agent working on an unrelated part of canopy
  break it, or reopen it, without knowing? If not, it is not a decision entry. Why a feature behaves as it does, and
  what was rejected for it, goes in `docs/DESIGN.md` next to the behavior; why a line of code is so goes in a comment
  there; the story of a change goes in its PR; progress goes on the milestone's lines in `docs/ROADMAP.md`. A new
  feature, command, config key, or default is not a decision by itself. When in doubt, leave it out.
- An entry that passes is short: a title that states the decision and two to four one-line bullets. The bar and the
  format are at the top of `docs/DECISIONS.md`.
- Changes to `docs/TRUST_MODEL.md`, `prompts/overseer.md`, or anything under `agents/` require an explicit human
  approval note in the PR description. These files define what the loop is allowed to do.
- When unsure, prefer the smaller change and leave a note in the PR. Do not invent requirements.

## Toolchain

- Python 3.12+. Package layout `src/canopy/`, in layered subpackages (DESIGN §5, D041). CLI entry point `canopy`.
- `uv` for everything: `uv sync`, `uv run`, `uv tool install`.
- `ruff` for formatting and linting. `pyrefly` in strict mode for type checking. `pytest` for tests, in strict mode,
  where a warning fails the test that raised it.
- `rumdl` lints and formats Markdown with every default rule. `editorconfig-checker` (`ec`) holds every file that is
  not Python or Markdown to `.editorconfig`. `shellcheck` lints shell scripts and `actionlint` the GitHub workflows.
  All are dev dependencies, so `uv sync` installs them and `make lint` runs them.
- ruff selects every stable rule (D018). Opt out with a commented `ignore` entry or a `noqa` with a code; never narrow
  `select`.
- `make all` runs fmt, lint (including type checks), and tests. It must pass before any PR.
- `make check` is `make all` without fmt: it verifies and never rewrites files. CI runs it.
- `make install-check` installs canopy with `uv tool install` into an empty HOME and runs a dry tick against the
  fakes (D046). CI runs it too; run it when you change packaging, bundled files, or the install steps.
- `make binary` builds `dist/canopy`, the single executable a release ships (D067), and
  `make install-check INSTALL_SOURCE=dist/canopy` checks it. The release workflow runs both on every platform it ships
  for, on a version tag and on pull requests that touch packaging.
- Stdlib first: `sqlite3`, `tomllib`, `subprocess`, `fcntl`, `json`, `logging`. Add a third-party dependency only when
  stdlib makes the code materially worse, and record why. Adopted so far: `click` for the CLI (D025), `pydantic` for
  validating config and anything parsed from another program's output (D026), `hypothesis` for property tests of input
  validators (dev only), `pytest-xdist` to run the tests in parallel (dev only), `rich` for terminal output
  (D043), `fastapi` and `uvicorn` for the web UI's server (D074, only in `canopy.serve`), and `httpx2` for its test
  client (D079, dev only).
- The web UI lives in `ui/` (D079) and has its own rules: read `ui/AGENTS.md` before touching it. It needs Node 22.12+
  and npm; `make check` runs its checks, and `make ui-e2e` its Playwright tests.
- Nothing tracker- or VCS-API-specific is ever imported. No Jira client, no GitHub client. Connectivity to those
  systems is the agent runtime's MCP servers. The harness knows nothing about Jira or GitHub beyond strings in config
  and prompts.

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
- Deterministic core. The Python code never calls an LLM. It runs agent processes and reads their output.
- Every external process (`treehouse`, `git`, the agent runtime, `notify`) goes through `src/canopy/infra/procs.py`.
  Nothing else calls `subprocess`. This is the seam tests use. ruff's banned-api rule (`TID251`) fails the lint if
  anything else imports it.
- Modules are small and named for what they own, in the package for their layer (DESIGN §5): `core/db.py`,
  `infra/lock.py`, `runs/dispatch.py`, `loop/attention.py`, `cli/main.py`. Imports go down the layers, never between
  features, and only `cli/` imports click; `tests/canopy/test_layers.py` fails otherwise. A new package gets a layer
  there and a line in DESIGN §5. A separate program (a notification sink) is a uv workspace member, not a package.
- No global mutable state. Pass a `Context` (config, db connection, paths).
- SQLite: WAL mode, `PRAGMA foreign_keys=ON`, numbered migrations in `migrations/NNNN_name.sql` applied in order at
  startup, recorded in a `schema_migrations` table. Never edit a shipped migration; add a new one. The series was
  squashed into `0001_init.sql` once, for v0.1 (D068); that is not a precedent for editing one.
- Hard guards live in code, judgment lives in prompts. Capacity limits, attempt limits, cooldowns, "never merge", and
  "one worker per ticket" are enforced by the harness regardless of what the overseer asks for.
- Log with `logging`, JSON lines to `.canopy/canopy.log` in the workspace. Every tick has an id that appears in every
  log line it produces.

## Testing

- Unit tests fake external processes through `canopy.infra.procs`, never by monkeypatching `subprocess` in scattered
  places.
- `tests/fakes/treehouse` is an executable fake that speaks the same CLI (`status --json`, `get --lease --json`,
  `return`) and keeps its state in a temp file. It is put on `PATH` by fixtures.
- The fake agent command is `tests/fakes/agent`, a script that prints a configurable final JSON line. Tests configure
  it through an env var.
- Fixtures live in `tests/conftest.py`: `fakes_on_path`, `treehouse_state` (the fake pool's state file), `agent_log`
  (what each fake agent run saw), and `canopy_env` (a workspace of one repository, `repo`, and a user config in a temp
  directory, with HOME pointed there; commands that name a repository pass `--repo repo`). Each fake's docstring lists
  the env vars and state keys it reads. The fake agent can run commands (`FAKE_AGENT_COMMANDS`), which is how a test
  plays an overseer calling `canopy decide`.
- Every test directory has an `__init__.py`, `tests/` included (D019). ruff's `INP001` fails the lint on one that does
  not. The root one matters most: without it, `tests/canopy/` is imported as a package named `canopy` and shadows
  `src/canopy`.
- One end-to-end test runs `canopy tick --dry-run` against the fakes and asserts on the `decisions` and `ticks`
  tables.
- Prompts are not unit-tested. `canopy tick --dry-run` writes the overseer's plan to the `decisions` table; that table
  is the evaluation corpus for prompt changes. Do not add prompt "tests" that assert on model output.

## Do not build (unless a ROADMAP milestone says so)

- A web UI beyond what ROADMAP M20, M23, and M24 list. `canopy status` and a markdown file stay the CLI's surface.
- Webhooks, network listeners, or background daemons. The loop is `canopy loop`, a foreground command that runs one
  tick after another (D042). A milestone that adds a listener follows TRUST_MODEL T8 (D055).
- A tracker adapter interface. The tracker is a prompt and config concern.
- A runtime plugin interface. The agent runtime is a command template in config.
- Sandboxing beyond what ROADMAP M26 lists. It plugs into the command template; see HOST_ISOLATION.
- A bot identity. MVP runs as the operator.
- Anything that approves or merges PRs, or transitions tickets to Done.
- Retry logic inside the worker. Workers push once and exit.
- Multi-machine coordination.

## Definition of done for a PR

- `make all` passes.
- New behavior has a test using the fakes.
- Docs updated: `DESIGN.md` for behavior and why it is that way, `README.md` if the install path or daily surface
  changed (and the install path is still five steps), and `DECISIONS.md` only if the change passes its bar.
- No new capability lets the loop do something `TRUST_MODEL.md` says it must not.
