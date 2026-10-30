"""Helpers the tests share: ticks and the journal, scripting the fake agents, and running canopy in this process.

A helper more than one test module uses lives here, or in `web_helpers.py` or `review_helpers.py`, never in a test
module: a test module imports from no other (`test_layers.py`). Fixtures live in the conftest files.
"""

import io
import itertools
import json
import os
import re
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NamedTuple, TypedDict, Unpack, cast
from unittest import mock

from rich.console import Console

from canopy.cli.main import main
from canopy.core import (
    config,
    connector_runs,
    db,
    git_tools,
    observe,
    plans,
    prompts,
    recorded_runs,
    records,
    replies,
    sql,
    workspace,
)
from canopy.core.context import Context
from canopy.core.vocab import ConnectorRunStatus, SourceKind, TickStatus
from canopy.infra import logs, procs, resources
from canopy.loop import connectors, mcp, spawns
from canopy.runs import drafted
from tests.conftest import FAKES_DIR, TRACKER_CMD, TRACKER_SOURCE, CanopyEnv, Journals, git

KEY = "PROJ-1"
#: A plan as a planner writes one, for a test that needs any.
PLAN = "# Plan\n\n## api\n\nAdd the endpoint.\n"
#: The prompt `prompted` gives its plan's planner.
PLAN_PROMPT = "You are planning PROJ-1.\n\nThe operator said: keep it small.\n"
# The branch an `implement` of KEY with slug `work` pushes.
BRANCH = f"agent/{KEY}-work"
# The label the test operator's tickets carry (`user_toml`).
LABEL = "agent-ready-tester"
#: The PR WORKER_DONE reports, as a URL that names no PR, so no source reads it.
WORKER_PR = "https://example.test/pr/1"
WORKER_DONE = json.dumps({"status": "done", "branch": BRANCH, "pr": WORKER_PR, "summary": "did it"})
#: The PR a worker that sends drafts opens (`sends_drafts`).
DRAFTS_PR = "https://github.com/acme/api/pull/7"
#: A PR the tests' `vcs` source reads, open with nothing on it, unless a test's GitHub state says otherwise. A ticket
#: with a unit at it reaches the overseer; one at WORKER_PR is the harness's `wait` instead (DESIGN §39).
READ_PR = "https://github.com/acme/repo/pull/1"
#: Why the harness waits on a candidate with a unit at WORKER_PR.
UNOBSERVED = (
    f"unobserved: {WORKER_PR} is not a PR's URL, so it is not observed; no source reads it, so it waits until the "
    "operator forgets the ticket's work"
)
#: What the harness's `unobserved_pr` item says of KEY's unit in `repo` at WORKER_PR.
UNOBSERVED_ITEM = (
    f"{KEY} in repo names {WORKER_PR} as its PR, which is not a PR's URL, so no source reads it and the ticket waits; "
    f"`canopy forget {KEY}` drops its work, and its next implement starts over"
)
#: The `trust` keys of the private file that hold a worker's drafts for the operator to approve:
#: `scenario.configures("private", trust=APPROVE)`.
APPROVE = {"review_replies": "approve"}
#: The tests' `tracker` source, as the user file names it (`tests.conftest.TRACKER_TOML`).
TRACKER = {"kind": "tracker", "cmd": TRACKER_CMD}
#: The `connect` keys of a source that posts to the tracker, for drafts on a ticket.
#: The private file's sources replace the user file's whole, so they name the tests' tracker source again.
TRACKER_POSTS = {"sources": {TRACKER_SOURCE: {**TRACKER, "post_cmd": "canopy-post-github"}}}
# What a blocked worker asks (`blocked_result`).
QUESTION = "Should the button be red or blue?"
# The last line an overseer prints when it has finished its tick.
TICK_DONE = "CANOPY_TICK_DONE"
# Above Linux's largest pid_max, so never a live process.
DEAD_PID = 4_194_305
# A value for every placeholder the worker prompts take.
PROMPT_VALUES = {
    "KEY": "PROJ-1",
    "SLOT": "/pool/1/repo",
    "BRANCH": "agent/PROJ-1-work",
    "BASE": "main",
    "STACKING": "This ticket is not stacked on another ticket's branch.",
    "TRACKER_PROVIDER": "jira",
    "NEEDS_HUMAN_LABEL": "needs-human",
    "TIMEOUT_MINUTES": "45",
    "ATTEMPT": "1",
    "MAX_ATTEMPTS": "2",
    "PR_URL": "https://example.test/pr/1",
    "REPOSITORIES": "This run works in one repository:\n- `repo` at `/pool/1/repo`: branch `agent/PROJ-1-work`",
    "PRS": '{"repo":"<url or null>"}',
    "PR_TITLES": '{"repo":"<its title or null>"}',
    "CONTEXT": None,
    "AUTHORIZED_REPLIERS": "`alice`",
    "LABELS": "`agent-ready-alice`",
    "REQUEST": "10234",
    "MAP": "/ws/MAP.md",
    "WORKER_COMMENT": "starts with `CANOPY:` outside any quote",
    "MARK_COMMENTS": "In every comment and reply you post, start it with `CANOPY:` and a space.",
    "OPEN_PR": "Open each PR through the GitHub MCP.",
    "TRUSTED_REVIEWERS": "`octocat`",
    "OPERATOR_MESSAGES": None,
    "PREVIOUS_RUNS": None,
    "REVIEW_FINDINGS": None,
    "REVIEW_ANSWERS": "",
    "CHECKLIST": "",
    "PLAN": None,
    "REASONS": "- `review`: review comments to address.",
    "FOLLOW_UPS": prompts.follow_ups(5, ["repo"], needs_human="needs-human", labels=["agent-ready-alice"]),
    # How comments reach GitHub under `trust.review_replies = "post"`, the text the prompts held before (DESIGN §29).
    **replies.posted_values("In every comment and reply you post, start it with `CANOPY:` and a space.", "needs-human"),
}
#: A private ticket's worker prompts take the same, but for how they file follow-ups (DESIGN §18, §22).
PRIVATE_PROMPT_VALUES = {
    **PROMPT_VALUES,
    "FOLLOW_UPS": prompts.follow_ups(
        5,
        ["repo"],
        needs_human="needs-human",
        labels=["agent-ready-alice"],
        private=True,
    ),
}


# Ticks and the journal


def present[T](value: T | None) -> T:
    """`value`, failing the test if it is None: what a lookup returns when the test knows the row is there."""
    assert value is not None
    return value


@contextmanager
def in_tick(conn: sqlite3.Connection, *, dry_run: bool = False, ends_ok: bool = False) -> Iterator[int]:
    """Start a tick and act inside it, as the overseer does: CANOPY_TICK_ID names it until the block ends.

    With `ends_ok`, the tick ends ok as the block does, as one whose overseer finished; without it, it is still running.
    """
    tick_id = db.start_tick(conn, dry_run=dry_run)
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": str(tick_id)}):
        yield tick_id
        if ends_ok:
            db.finish_tick(conn, tick_id, TickStatus.OK, "test")


def sources(**more: Mapping[str, object]) -> dict[str, object]:
    """The `connect` keys of the tests' `tracker` source and the sources `more` names, for the private file.

    Its `connect.sources` replaces the user file's whole, so a test's sources there name the tracker source again:
    config requires one (DESIGN §30).

    Returns:
        `{"sources": ...}`, for `configures("private", connect=...)`.
    """
    return {"sources": {TRACKER_SOURCE: TRACKER, **more}}


def tracker_holds(conn: sqlite3.Connection, *keys: str) -> None:
    """The tests' tracker holds `keys`, KEY if none, and the sources read them now, as a tick's do (DESIGN §6).

    Config requires a `tracker` source (DESIGN §30), and a dispatch rests on its fresh read of the ticket and, the
    `vcs` source running beside it, of the repositories' branches (§35, §39). The tests' workspaces run the fake
    connector as theirs, `connector --labeled`, which holds every ticket it is asked open and labeled. Each key is
    touched into the journal first, as the query's record would, so the source is asked for it. The `vcs` source reads
    too unless a run of it read whole within `connect.max_age_minutes`, so a test that scripts GitHub to hang or fail
    from a run on reads it once before it does. A test that configures a tracker of its own reads nothing here: its
    world is what it scripts.
    """
    root = Path.cwd()
    cfg = config.load(root)
    source = cfg.connect.tracker()
    if "--labeled" not in config.notify_words(source.cmd):
        return
    ctx = Context(config=cfg, conn=conn, runner=procs.SubprocessRunner(), ws=workspace.load(root))
    with db.transaction(conn):
        for key in keys or (KEY,):
            db.touch_ticket(conn, key, ctx.repo)
    log = logs.for_tick(None)
    # The fakes first on PATH, as `fakes_on_path` puts them, for a test that runs no fake itself.
    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(FAKES_DIR), os.environ.get("PATH", "")])}):
        observe.observe(conn, cfg, ctx.runner, source, connectors.tracker_request(ctx), log=log)
        if not _vcs_read_lately(conn, cfg.connect.max_age_minutes):
            vcs, request = cfg.connect.vcs(), connectors.vcs_request(ctx)
            observed = observe.observe(conn, cfg, ctx.runner, vcs, request, log=log)
            name = config.DEFAULT_SOURCE
            connector_runs.record(conn, None, name=name, source=vcs, request=request, observed=observed)


def _vcs_read_lately(conn: sqlite3.Connection, minutes: int) -> bool:
    since = db.format_time(datetime.now(UTC) - timedelta(minutes=minutes))
    query = records.select(records.ConnectorRun).where(
        "kind = ? AND status = ? AND ended_at >= ?",
        SourceKind.VCS,
        ConnectorRunStatus.OK,
        since,
    )
    return bool(query.all(conn))


def tick_starts(runner: procs.Runner | None = None, *, tick_id: int | None = None) -> None:
    """Start the runs a tick recorded, as the tick does once its overseer's run has ended (DESIGN §40).

    The tick is `tick_id`, or the one `in_tick` holds open if None. Only the overseer's runs: the harness's own
    dispatches are the tick's to make. `runner` starts them, a real one if None.
    """
    if tick_id is None:
        tick_id = int(os.environ["CANOPY_TICK_ID"])
    with mcp.opened(runner or procs.SubprocessRunner(), Path.cwd()) as ctx:
        for recorded in recorded_runs.of_tick(ctx.conn, tick_id):
            spawns.start(ctx, recorded)


@contextmanager
def in_run(run_id: int | str) -> Iterator[None]:
    """Act inside run `run_id`, as its agent does: CANOPY_RUN_ID names it until the block ends."""
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": str(run_id)}):
        yield


def seen(conn: sqlite3.Connection, env: CanopyEnv, *keys: str) -> None:
    """Record `keys`, KEY if none, as tickets an earlier tick saw: canopy knows them, and the state block shows them."""
    with db.transaction(conn):
        for key in keys or (KEY,):
            db.touch_ticket(conn, key, str(env.root))


@contextmanager
def granted_meanwhile(
    conn: sqlite3.Connection,
    owner: object,
    reads: str,
    insert: str,
    *params: object,
) -> Iterator[list[str]]:
    """Patch `owner.reads`, a read of a grant's limit on `conn`, to try `insert`, another grant, just before it reads.

    The other grant's connection waits for no lock, so it is `locked` out when the read is inside the write transaction
    of the grant under test, as it must be (#341), and `committed` between that grant and its limit when it is not.
    Yields what each try did.
    """
    [(path,)] = conn.execute("SELECT file FROM pragma_database_list WHERE name = 'main'").fetchall()
    real = getattr(owner, reads)
    tried: list[str] = []

    def meanwhile(*args: object, **kwargs: object) -> object:
        other = sqlite3.connect(path, autocommit=True, timeout=0)
        try:
            other.execute(insert, params)
            tried.append("committed")
        except sqlite3.OperationalError as e:
            tried.append("locked" if "locked" in str(e) else str(e))
        finally:
            other.close()
        return real(*args, **kwargs)

    with mock.patch.object(owner, reads, autospec=True, side_effect=meanwhile):
        yield tried


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str]]:
    """Each decision the tick recorded, as (action, rationale)."""
    return [(d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]


def context(env: CanopyEnv, runner: procs.Runner | None = None) -> Context:
    """The context `canopy` builds in `env`'s workspace, over its journal, unmigrated."""
    cfg = config.load(env.root, env.user_file)
    ws = workspace.load(env.root)
    workspace.ensure_state_dir(ws.state_dir)
    logs.configure(ws.state_dir)
    conn = env.journal(migrate=False)
    return Context(config=cfg, conn=conn, runner=runner or procs.SubprocessRunner(), ws=ws)


def operator(*args: str) -> int:
    """Run one of the operator's commands, from the operator's shell: outside any tick or run."""
    with mock.patch.dict(os.environ):
        os.environ.pop("CANOPY_TICK_ID", None)
        return main(list(args))


def running_run(ctx: Context, key: str, *, private: bool = True) -> int:
    """Record a run of `key` that is still running, in a tick of its own, and return its id."""
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    run_id = db.insert_run(
        ctx.conn,
        tick_id=tick_id,
        key=key,
        kind="implement",
        branch=f"agent/{key}-work",
        slots=[],
        runs_dir=ctx.state_dir / "runs",
        private=private,
    )
    db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "test")
    return run_id


def live_run(env: CanopyEnv, ctx: Context, key: str) -> int:
    """Record a running run of `key` whose own process is alive: this one, holding no lifelock.

    Returns:
        The run's id.
    """
    env.journal()  # migrated, as the loop would, so the run can be recorded before it starts
    run_id = running_run(ctx, key)
    assert db.claim_run(ctx.conn, "runs", run_id, os.getpid())
    return run_id


def minute(stamp: str) -> str:
    """`stamp`, a time the journal wrote, as the overseer's state block shows it: to the minute, its seconds dropped."""
    return f"{db.parse_time(stamp):%Y-%m-%dT%H:%M}Z"


def earlier(now: datetime, days: float, hours: float = 0) -> str:
    """The time `days` and `hours` before `now`, as the journal writes it."""
    return db.format_time(now - timedelta(days=days, hours=hours))


@contextmanager
def in_zone(zone: str) -> Iterator[None]:
    """This machine's local time is `zone`, an IANA name, while the block runs, and UTC again after it."""
    try:
        with mock.patch.dict(os.environ, {"TZ": zone}):
            time.tzset()
            yield
    finally:
        time.tzset()


def only_tick(conn: sqlite3.Connection) -> records.Tick:
    """The one tick in the journal."""
    [tick] = records.fetch_all(conn, records.Tick, sql.frag("SELECT * FROM ticks"))
    return tick


def last_tick(conn: sqlite3.Connection) -> records.Tick:
    """The tick started last."""
    return present(db.last_tick(conn))


def last_run(conn: sqlite3.Connection) -> sqlite3.Row:
    """The run recorded last."""
    return present(conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone())


type ToolRow = tuple[str, int, int, int]


def tools_of(conn: sqlite3.Connection, table: db.RunTable | Literal["ticks"], run_id: int) -> list[ToolRow]:
    """A run's tool rollup, as (tool, calls, errors, result characters), the most characters first."""
    return [(t.tool, t.calls, t.errors, t.result_chars) for t in db.run_tools(conn, table, run_id)]


def tools_printed(agent_log: Path, agent: str) -> list[ToolRow]:
    """The rollup of what the fake `agent` (`canopy-worker`, ...) ran: each command a `bash` call returning its stdout.

    Its one run in `agent_log`; empty when it ran no command.
    """
    [run] = [r for r in agent_runs(agent_log) if agent in cast("list[str]", r["argv"])]
    ran = cast("list[dict[str, str]]", run["commands"])
    return [("bash", len(ran), 0, sum(len(c["stdout"]) for c in ran))] if ran else []


def slot_of(conn: sqlite3.Connection, run_id: int) -> records.RunSlot:
    """The one slot a run in one repository leased."""
    [row] = db.run_slots(conn, run_id)
    return row


def unit_of(conn: sqlite3.Connection, key: str) -> records.TicketUnit:
    """The one unit of a ticket in one repository."""
    [row] = db.units(conn, key)
    return row


def plan_file(env: CanopyEnv, run_id: int, key: str = KEY) -> Path:
    """Where the plan run `run_id` of `key` wrote its plan, in the workspace's state directory."""
    return env.state_dir / "plans" / key / f"{run_id}.md"


def plan_run(conn: sqlite3.Connection, state_dir: Path, key: str = KEY) -> int:
    """A finished run of `key` for a plan to belong to. Its kind is a placeholder: no guard reads it here."""
    db.touch_ticket(conn, key, "/ws")
    tick_id = db.start_tick(conn, dry_run=False)
    return db.insert_run(conn, tick_id=tick_id, key=key, kind="implement", branch="", slots=[], runs_dir=state_dir)


def proposed(conn: sqlite3.Connection, state_dir: Path, text: str = PLAN, key: str = KEY) -> int:
    """Write and record a plan for `key`, as `_run` does once a plan run ends `done`. Returns its run's id."""
    run_id = plan_run(conn, state_dir, key)
    plans.record(conn, key, run_id, plans.write(state_dir, key, run_id, text))
    return run_id


def plan_prompt(conn: sqlite3.Connection, run_id: int) -> Path:
    """Where a plan run's prompt is: beside its log, as dispatch writes it."""
    return Path(present(db.get_run(conn, run_id))["log_path"]).with_suffix(".prompt")


def prompted(conn: sqlite3.Connection, state_dir: Path, prompt: str = PLAN_PROMPT, key: str = KEY) -> int:
    """Write and record a plan for `key`, its planner's prompt beside its run's log. Returns its run's id."""
    run_id = proposed(conn, state_dir, key=key)
    plan_prompt(conn, run_id).write_text(prompt)
    return run_id


def prompt_of(env: CanopyEnv, run_id: int) -> str:
    """The prompt the run's worker was given."""
    return (env.state_dir / "runs" / f"{run_id}.prompt").read_text()


def wait_for_run(conn: sqlite3.Connection, run_id: int, timeout: float = 30) -> sqlite3.Row:
    """Wait for a detached run to close its row."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = present(db.get_run(conn, run_id))
        if row["status"] != "running":
            return row
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} still running after {timeout}s")


def lifelock_left(row: sqlite3.Row | records.Row, timeout: float = 30) -> bool:
    """Whether the lifelock file of a closed run is still there once its process has exited.

    The process closes its row, then removes the file, then exits, so the file is looked for only after the exit.
    """
    deadline = time.monotonic() + timeout
    values = records.columns(row)
    while procs.alive(int(values["pid"])) and time.monotonic() < deadline:
        time.sleep(0.05)
    return procs.lifelock(Path(values["log_path"])).exists()


def pool(treehouse_state: Path) -> list[dict[str, object]]:
    """Every slot the fake treehouse holds: the pool it uses without TREEHOUSE_ROOT, then each repository's."""
    state = json.loads(treehouse_state.read_text())
    slots: list[dict[str, object]] = [
        *state.get("slots", []),
        *(s for p in state.get("pools", {}).values() for s in p.get("slots", [])),
    ]
    return slots


def listed(state: Path, *lines: str, variants: Mapping[str, Sequence[str]] | None = None) -> None:
    """Have the fake `opencode models`, whose state file is `state`, print `lines`, and with `--verbose` `variants`."""
    state.write_text(json.dumps({"models": list(lines), "variants": dict(variants or {})}))


def pool_statuses(treehouse_state: Path) -> list[str]:
    """The status of every slot the fake treehouse holds, in `pool`'s order."""
    return [str(s["status"]) for s in pool(treehouse_state)]


# Calling the overseer's tools, and dispatching, in this process


class Said(NamedTuple):
    """What a tool call came back with: its text, and whether it is a tool error."""

    text: str
    error: bool


class Called(NamedTuple):
    """A call an agent makes of one of canopy's tools (DESIGN §27), through the server its inline config names."""

    #: The tool, as the runtime names it: `canopy_decide`, `canopy_chore_history`, `canopy_git_diff`.
    name: str
    #: Its arguments, the fields of its request.
    arguments: Mapping[str, object]

    def __str__(self) -> str:
        """The call as a story tells it: the tool, then its arguments as JSON."""
        return f"{self.name} {json.dumps(self.arguments, default=str)}"


def calls(name: str, /, **arguments: object) -> Called:
    """The call an agent makes of canopy's tool `name`, as the runtime names it, with `arguments`."""
    return Called(name, arguments)


def overseer_calls(move: Called, *, runner: procs.Runner | None = None) -> Said:
    """Make the overseer's call `move` of one of its tools here, in this process, as `canopy _mcp` answers it.

    The server answers it as it would the overseer's: its arguments validated, the workspace the test is in opened
    afresh, and the tick CANOPY_TICK_ID names checked. `runner` runs what the call runs, such as the runtime asked for
    its models, the real one if None.

    Returns:
        What the call came back with: its text, and whether it is a tool error.
    """
    name = move.name.removeprefix(f"{mcp.SERVER}_")
    assert name in {t.name for t in mcp.TOOLS}, f"{move.name} is not one of the overseer's tools"
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": move.arguments}}
    found = runner or procs.SubprocessRunner()
    response = mcp.answer(json.dumps(request, default=str).encode(), lambda: mcp.opened(found, Path.cwd()))
    assert response is not None, move
    result = response.get("result")
    assert isinstance(result, dict), response
    [content] = cast("list[dict[str, str]]", result["content"])
    return Said(content["text"], bool(result["isError"]))


class Dispatched(NamedTuple):
    """What the overseer's `dispatch` tool did: what it said, and the decisions of the tick it ran in."""

    #: What the call came back with.
    said: Said
    #: The tick's decisions, as (action, rationale).
    decisions: list[tuple[str, str]]


def dispatch_in_tick(conn: sqlite3.Connection, move: Called, *, runner: procs.Runner | None = None) -> Dispatched:
    """In a tick of its own, make the overseer's dispatch `move` and start what it recorded; the run does not run.

    `move` is a `dispatches(...)` from `scenario_helpers.py`, or any call of `canopy_dispatch`.
    """
    runner = runner or InlineRunner()
    key = str(move.arguments["key"])
    tracker_holds(conn, key)
    with in_tick(conn) as tick_id:
        said = overseer_calls(move, runner=runner)
        tick_starts(runner, tick_id=tick_id)
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        return Dispatched(said, decisions(conn, tick_id))


def dispatch_and_run(conn: sqlite3.Connection, move: Called, *, runner: procs.Runner | None = None) -> sqlite3.Row:
    """Dispatch as `dispatch_in_tick` does, then do the run in this process, as the detached one would.

    Returns:
        The run, closed.
    """
    runner = runner or InlineRunner()
    tracker_holds(conn, str(move.arguments["key"]))
    with in_tick(conn) as tick_id:
        said = overseer_calls(move, runner=runner)
        assert not said.error, (said.text, decisions(conn, tick_id))
        tick_starts(runner, tick_id=tick_id)
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        run_id = int(last_run(conn)["id"])
        assert main(["_run", str(run_id)], runner=runner) == 0
    return present(db.get_run(conn, run_id))


def dispatch_refused(conn: sqlite3.Connection, move: Called) -> list[tuple[str, str]]:
    """Dispatch as `dispatch_in_tick` does, expecting a refusal, at the call or as the tick starts the run (DESIGN §40).

    Returns:
        The tick's decisions, as (action, rationale).
    """
    said, made = dispatch_in_tick(conn, move)
    assert said.error or any(action.startswith("refused:") for action, _ in made), made
    return made


@dataclass
class InlineRunner:
    """Runs processes for real, but `spawn` starts nothing and returns this process's pid.

    A test then runs `canopy _run <id>` in-process with `main`, which claims the run with that same pid. `timeout_agent`
    makes the worker's run come back timed out, having printed `timeout_stdout`.
    """

    spawned: list[tuple[str, ...]] = field(default_factory=list)
    spawn_error: procs.ProcError | None = None
    timeout_agent: bool = False
    timeout_stdout: str = "fake agent: starting\n"

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,
        on_line: Callable[[str], None] | None = None,
        stdout_to_file: bool = False,
    ) -> procs.Result:
        if self.timeout_agent and "agent" in args[:3]:
            # As the real runner does, each line goes to `on_line` as it is printed.
            if on_line is not None:
                for line in self.timeout_stdout.splitlines(keepends=True):
                    on_line(line)
            return procs.Result(tuple(args), -9, self.timeout_stdout, "", timed_out=True)
        return procs.SubprocessRunner().run(
            args,
            cwd=cwd,
            env=env,
            stdin=stdin,
            timeout=timeout,
            on_start=on_start,
            on_line=on_line,
            stdout_to_file=stdout_to_file,
        )

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002  (starts nothing)
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawned.append(tuple(args))
        return os.getpid()


def inline_context(env: CanopyEnv, runner: InlineRunner | None = None) -> Context:
    """The workspace's context as its config now stands, migrated, whose runner starts no detached process."""
    found = context(env, runner or InlineRunner())
    db.migrate(found.conn, resources.migrations_dir())
    return found


# Scripting the fake agents (tests/fakes/agent)
#
# A `*_does` helper scripts what an agent does from start to end: its commands, none if not given, then its result
# line. A `*_reports` helper sets the result line, and commands only if given, so it can sit inside a block that set
# them. `Behavior` covers the rest; `scripted` is the one they all go through.


def canopy(*args: str) -> list[str]:
    """The command an agent runs to call `canopy` with `args`."""
    return ["canopy", *args]


def decides(key: str, action: str = "wait", rationale: str = "nothing to do yet") -> Called:
    """The overseer decides `action` for `key`, a wait by default, with `rationale`."""
    return calls("canopy_decide", decisions=[{"key": key, "action": action, "rationale": rationale}])


def raises(key: str | None, reason: str, detail: str | None = None, **more: object) -> Called:
    """The overseer raises `reason` about `key` on the attention list, with `detail`, `<key> detail` by default.

    `more` names the item's other fields: `pr` for a PR with no ticket, with `key` None, and `repo` or `item`.
    """
    shown = detail if detail is not None else f"{key} detail"
    return calls("canopy_attention", **({"key": key} if key is not None else {}), reason=reason, detail=shown, **more)


def ticket_sets(*keys: str, **fields: object) -> Called:
    """The overseer sets `fields` on each of `keys`, as the `ticket-set` tool names them: `phase`, `cursors`, `repo`."""
    return calls("canopy_ticket-set", tickets=[{"key": key, **fields} for key in keys])


def chore_runs(name: str, context: str | None = None) -> Called:
    """The overseer starts a run of chore `name`, with `context` for it if given."""
    return calls("canopy_chore-run", name=name, **({"context": context} if context is not None else {}))


def chore_waits(name: str, rationale: str = "not now") -> Called:
    """The overseer records that chore `name`, due, should not run now, and why."""
    return calls("canopy_chore-wait", name=name, rationale=rationale)


#: The overseer's tools whose call names a ticket the state block lists to it: a dispatch, a decision, an attention
#: item, and a ticket's settings.
_LISTED = ("canopy_dispatch", "canopy_decide", "canopy_attention", "canopy_ticket-set")
#: A ticket's key, as the tests name them.
_TICKET_KEY = re.compile(r"[A-Z][A-Z0-9]*-[0-9]+")


def named_tickets(moves: Iterable[list[str] | Called]) -> list[str]:
    """The ticket each move names that the overseer must be listed to make it, in order: the tracker holds each."""
    found: list[str] = []
    for move in moves:
        if not isinstance(move, Called) or move.name not in _LISTED:
            continue
        nested = move.arguments.get("decisions", move.arguments.get("tickets"))
        items = cast("list[Mapping[str, object]]", nested) if isinstance(nested, list) else [move.arguments]
        found += [key for item in items if isinstance(key := item.get("key"), str) and _TICKET_KEY.fullmatch(key)]
    return found


def holds_listed(moves: Iterable[list[str] | Called]) -> None:
    """The tests' tracker holds each ticket `moves` name that the journal does not know yet (`tracker_holds`).

    Outside a workspace, or with no such ticket, it does nothing.
    """
    found = workspace.load(Path.cwd()) if (Path.cwd() / config.WORKSPACE_FILE_NAME).exists() else None
    if found is None or not (keys := named_tickets(moves)):
        return
    with closing(db.connect(found.state_dir / db.DB_FILE_NAME)) as conn:
        db.migrate(conn, resources.migrations_dir())
        if unknown := [key for key in dict.fromkeys(keys) if db.get_ticket(conn, key) is None]:
            tracker_holds(conn, *unknown)


class Behavior(TypedDict, total=False):
    """What a fake agent does besides run its commands and print its result line, as tests/fakes/agent reads it."""

    says: str  # a line it says before the commands run
    exit_code: int
    sleep: float  # seconds it waits before the result line, to run into a timeout
    session: str  # the `sessionID` on each event, with `--format json`
    step_cost: str  # each model call's cost, verbatim JSON, so a test can make it invalid
    errors: str  # a JSON list, each the `error` of an `error` event it prints at the end, with `--format json`


# The fake's name for each of Behavior's keys, after its FAKE_<ROLE>_ prefix.
BEHAVIOR_SETTINGS = {
    "says": "SAYS",
    "exit_code": "EXIT",
    "sleep": "SLEEP",
    "session": "SESSION",
    "step_cost": "STEP_COST",
    "errors": "ERRORS",
}


@dataclass
class Script(AbstractContextManager[None]):
    """What the fake agent in one role does, as tests/fakes/agent reads it: until a block on it ends, the fake does it.

    A script is data as well as a block, so a scenario can hand it to one ticket's runs (FAKE_<ROLE>_FOR in the fake),
    and it can be entered again, by one block after another.
    """

    #: The role, as the fake names it: WORKER, OVERSEER, ...
    role: str
    #: What it does, each setting named as the fake names it without the FAKE_<ROLE>_ prefix: COMMANDS, RESULT, EXIT.
    settings: Mapping[str, str]
    #: How a run of another ticket plays it, given that ticket's key, when that differs: `pushes` pushes the ticket's
    #: own branch. None for a script every ticket's run plays the same.
    per_ticket: Callable[[str], "Script"] | None = field(default=None, compare=False, repr=False)
    #: The blocks open on it, innermost last.
    _open: list[ExitStack] = field(default_factory=list, init=False, compare=False, repr=False)

    def for_ticket(self, key: str) -> "Script":
        """The script as a run of `key` plays it.

        Returns:
            The script, made for `key` if it is made for a ticket at all.
        """
        return self if self.per_ticket is None else self.per_ticket(key)

    def __enter__(self) -> None:
        """Have the fake in its role read the script's settings, until the block ends."""
        stack = ExitStack()
        env = {f"FAKE_{self.role}_{name}": value for name, value in self.settings.items()}
        stack.enter_context(mock.patch.dict(os.environ, env))
        self._open.append(stack)

    def __exit__(self, *exc: object) -> None:
        """Put the environment back as the block found it."""
        self._open.pop().close()


@contextmanager
def overseer_does(
    *moves: Called | list[str],
    result: str = TICK_DONE,
    **behavior: Unpack[Behavior],
) -> Iterator[None]:
    """Until the block ends, the fake overseer makes each move and prints `result`.

    A move is a call of one of canopy's tools, `calls(...)` or a helper that makes one, such as `decides`; or a command
    it runs through its shell, `canopy(...)`, where a test plays one the overseer has no shell for. It makes the calls
    first, in order, then runs the commands. `result` by default ends its tick. A ticket the calls name that the
    journal does not know yet, the tests' tracker holds and reads first (`holds_listed`), so the overseer is listed it.
    """
    holds_listed(moves)
    commands = [move for move in moves if not isinstance(move, Called)]
    tools = [[move.name, move.arguments] for move in moves if isinstance(move, Called)]
    settings = {"COMMANDS": json.dumps(commands), "RESULT": result, "TOOLS": json.dumps(tools, default=str)}
    with scripted("OVERSEER", settings, behavior):
        yield


@contextmanager
def overseer_records(*items: tuple[str, str], waiting: Iterable[str] = ()) -> Iterator[None]:
    """Until the block ends, the fake overseer records each (key, reason) as needing attention and ends the tick.

    Each key in `waiting` it decides to wait on instead, as it must for a ticket in the journal it records nothing for.
    """
    with overseer_does(*itertools.starmap(raises, items), *waits(*waiting)):
        yield


def waits(*keys: str, rationale: str = "nothing to do yet") -> list[Called]:
    """The calls an overseer makes to wait on each of `keys`, as it must on a ticket it has nothing to do for."""
    return [decides(key, "wait", rationale) for key in keys]


def with_events(env: CanopyEnv, agent: str) -> None:
    """Have the command that runs `agent` (`canopy-overseer`, ...) ask for OpenCode's JSON events, as defaults do."""
    env.write_user(env.user_file.read_text().replace(f"--agent {agent} ", f"--agent {agent} --format json ", 1))


def with_rebase(env: CanopyEnv) -> None:
    """Let workers rebase and push with a lease, never merging a base in (`[trust] rebase`)."""
    env.append_user("\n[trust]\nrebase = true\n")


def personas_dir(env: CanopyEnv) -> Path:
    """The operator's personas directory (DESIGN §31), made, and set as `paths.personas` in the user file.

    Returns:
        The directory, where a test writes the operator's persona files.
    """
    path = env.user_file.parent / "personas"
    path.mkdir(parents=True, exist_ok=True)
    env.configure(env.user_file, {"paths": {"personas": str(path)}})
    return path


def checklists_dir(env: CanopyEnv) -> Path:
    """The operator's checklists directory (DESIGN §42), made, and set as `paths.checklists` in the user file.

    Returns:
        The directory, where a test writes a repository's list, `<repo>.md`.
    """
    path = env.user_file.parent / "checklists"
    path.mkdir(parents=True, exist_ok=True)
    env.configure(env.user_file, {"paths": {"checklists": str(path)}})
    return path


def approve_policy(env: CanopyEnv) -> None:
    """Have the workspace's policy ask for a plan the operator approves before any `implement` (DESIGN §25)."""
    env.append_shared('\n[policy]\nplan = "approve"\n')


def with_memory(canopy_env: CanopyEnv, ticket_notes: str = "off", proposals: str = "off") -> None:
    """Set agent memory's tiers (DESIGN §28) in the workspace's private file, which holds nothing else in the tests."""
    canopy_env.write_private(f'[memory]\nticket_notes = "{ticket_notes}"\nproposals = "{proposals}"\n')


def approving(canopy_env: CanopyEnv, extra: str = "") -> None:
    """Set `trust.review_replies = "approve"` (DESIGN §29) in the private file, with `extra` after it."""
    canopy_env.write_private(f'[trust]\nreview_replies = "approve"\n{extra}')


def posting(canopy_env: CanopyEnv) -> None:
    """Set `trust.review_replies = "post"` in the private file: workers post their own comments, marked, as before."""
    canopy_env.write_private('[trust]\nreview_replies = "post"\n')


def all_drafts(conn: sqlite3.Connection) -> list[records.Draft]:
    """Every draft in the journal, in the order they were written."""
    return records.fetch_all(conn, records.Draft, sql.frag("SELECT * FROM drafts ORDER BY id"))


def comment(n: int, thread: str = "PRRT_1", author: str = "alice", body: str = "Rename this.") -> dict[str, Any]:
    """A review comment line, as the reader prints it without `kind` and `pr`."""
    where = {"id": thread, "path": "src/app.py", "line": 12, "side": "right", "outdated": False, "resolved": False}
    return {"item": "comment", "id": n, "author": author, "bot": False, "time": "2026-10-18T10:00:00Z", "body": body,
            "url": f"{DRAFTS_PR}#discussion_r{n}", "review": 101, "thread": where}  # fmt: skip


def github_has(state: Path, *reviews: dict[str, Any], **more: object) -> None:
    """Make the fake GitHub hold `DRAFTS_PR` with `reviews`, and the other state keys given."""
    state.write_text(json.dumps({"prs": {DRAFTS_PR: {"reviews": list(reviews)}}, **more}))


def thread(n: int, did: str = "changed", text: str = "Renamed.") -> dict[str, object]:
    """A worker's draft replying on the thread of review comment `n` of `DRAFTS_PR`."""
    return {"on": "thread", "pr": DRAFTS_PR, "comment": n, "did": did, "text": text}


def tick_reads(ctx: Context) -> int:
    """Run the connectors as a tick's reconcile does, in a tick of their own, and check the drafts they read.

    Returns:
        The tick's id.
    """
    log = logs.for_tick(None)
    with in_tick(ctx.conn) as tick_id:
        drafted.reconcile(ctx, connectors.run(ctx, tick_id, log, dry_run=False).read, log)
    return tick_id


def reads(state: Path, program: str = "connect") -> list[dict[str, Any]]:
    """What the fake GitHub's `program` was asked, each run in order."""
    log = state.parent / "github.jsonl"
    lines: list[str] = log.read_text().splitlines() if log.exists() else []
    return [json.loads(line)["request"] for line in lines if json.loads(line)["program"] == program]


def memories(conn: sqlite3.Connection) -> list[records.Memory]:
    """Every memory in the journal, in the order they were written."""
    return records.fetch_all(conn, records.Memory, sql.frag("SELECT * FROM memories ORDER BY id"))


def run_with(conn: sqlite3.Connection, move: Called, **fields: object) -> sqlite3.Row:
    """Dispatch and run the dispatch `move`, its worker committing, pushing, and sending `fields`."""
    branch = f"agent/{move.arguments['key']}-work"
    line = worker_result(**fields).replace(BRANCH, branch)
    with worker_does(*commit_and_push(branch), result=line):
        return dispatch_and_run(conn, move, runner=InlineRunner())


def worker_result(**memory: object) -> str:
    """A worker's result line: done on KEY's `work` branch in `repo`, carrying the memory fields given."""
    return json.dumps({"status": "done", "branch": BRANCH, "prs": {"repo": None}, "summary": "did it", **memory})


def worker_does(
    *commands: list[str],
    result: str = WORKER_DONE,
    tools: Sequence[Called] = (),
    **behavior: Unpack[Behavior],
) -> Script:
    """Until the block ends, the fake worker makes the calls `tools` names, runs `commands`, and then prints `result`.

    Returns:
        The worker's script, a block.
    """
    settings = {"COMMANDS": json.dumps(commands), "RESULT": result}
    if tools:
        settings["TOOLS"] = json.dumps([[call.name, call.arguments] for call in tools])
    return scripted("WORKER", settings, behavior)


@contextmanager
def private_worker_does(
    *commands: list[str],
    result: dict[str, object],
    tools: Sequence[Called] = (),
    **behavior: Unpack[Behavior],
) -> Iterator[None]:
    """Until the block ends, the fake private worker makes the calls `tools` names, runs `commands`, prints `result`."""
    with scripted("WORKER_PRIVATE", {**reported(result, commands, tools), "COMMANDS": json.dumps(commands)}, behavior):
        yield


@contextmanager
def chore_reports(
    report: object,
    *commands: list[str],
    tools: Sequence[Called] = (),
    **behavior: Unpack[Behavior],
) -> Iterator[None]:
    """Until the block ends, the fake chore prints `report`, verbatim if it is a string.

    It prints it after making the calls `tools` names and running `commands`, if given.
    """
    with scripted("CHORE", reported(report, commands, tools), behavior):
        yield


def reported(report: object, commands: Sequence[list[str]], tools: Sequence[Called] = ()) -> dict[str, str]:
    """A `*_reports` helper's settings.

    `report` as the result line, verbatim if a string, and `commands` and the calls `tools` names, if any.
    """
    settings = {"RESULT": report if isinstance(report, str) else json.dumps(report)}
    if commands:
        settings["COMMANDS"] = json.dumps(commands)
    if tools:
        settings["TOOLS"] = json.dumps([[call.name, call.arguments] for call in tools])
    return settings


@contextmanager
def planner_does(
    *commands: list[str],
    plan: str | None,
    result: Mapping[str, object] | None = None,
    tools: Sequence[Called] = (),
) -> Iterator[None]:
    """Until the block ends, the fake planner makes the calls `tools` names, writes `plan`, and reports.

    It writes `plan` to its desk's plan file and runs `commands` before it reports. It writes as the planner's edit
    tool would, before `commands`; with `plan` None it writes no file. `result`, its result line, defaults to a `done`
    one (DESIGN §25).
    """
    script = "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])"
    write = [["python3", "-c", script, plans.WRITTEN, plan]] if plan is not None else []
    line = json.dumps(result if result is not None else {"status": "done", "summary": "planned it"})
    with scripted("PLANNER", reported(line, [*write, *commands], tools)):
        yield


def scripted(role: str, settings: Mapping[str, str], behavior: Behavior | None = None) -> Script:
    """Until the block ends, the fake agent in `role` (OVERSEER, WORKER, ...) reads `settings` and `behavior`.

    `settings` are named as the fake names them without the prefix (COMMANDS, RESULT); what neither gives, the fake does
    as it would have. The helpers above are this for one role; use it directly for a role none of them script.

    Returns:
        The script, a block.
    """
    named = {BEHAVIOR_SETTINGS[name]: str(value) for name, value in (behavior or {}).items()}
    return Script(role, {**settings, **named})


def blocked_result() -> dict[str, object]:
    """A worker's result: blocked on KEY's `work` branch in `repo`, with no PR, asking QUESTION."""
    return {
        "status": "blocked",
        "branch": BRANCH,
        "prs": {"repo": None},
        "summary": "half done",
        "question": QUESTION,
    }


def commit_and_push(branch: str, message: str = "PROJ-1: the change") -> list[list[str]]:
    """The commands a worker runs to commit and push `branch`."""
    return [
        ["git", "commit", "--quiet", "--allow-empty", "-m", message],
        ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"],
    ]


def trailers_on(origin: Path, branch: str, base: str = "main") -> list[list[str]]:
    """The trailers of each commit `branch` holds and `base` does not in the repository `origin`, newest first."""
    listed = git("log", "--format=%H %(trailers:only,unfold,separator=%x1f)", branch, f"^{base}", "--", cwd=origin)
    found = [line.partition(" ")[2] for line in listed.splitlines()]
    return [line.split("\x1f") if line else [] for line in found]


def agent_runs(agent_log: Path) -> list[dict[str, Any]]:
    """Each fake agent run, in order, as the fake logged it; none if no agent ran."""
    if not agent_log.exists():
        return []
    return [json.loads(line) for line in agent_log.read_text().splitlines()]


def ran_on(agent_log: Path, agent: str = "canopy-worker") -> str | None:
    """The model the definition of the latest run of `agent` names, as it loaded it; None when it names none.

    A variant it names follows the model's id after an `@`, as config spells it.
    """
    run = [r for r in agent_runs(agent_log) if f"--agent {agent}" in " ".join(r["argv"])][-1]
    text = (Path(run["env"]["OPENCODE_CONFIG_DIR"]) / "agents" / f"{agent}.md").read_text()
    found = [line for line in text.splitlines() if line.startswith("model: ")]
    variant = [line for line in text.splitlines() if line.startswith("variant: ")]
    if not found:
        return None
    model = json.loads(found[0].removeprefix("model: "))
    return f"{model}@{json.loads(variant[0].removeprefix('variant: '))}" if variant else model


def told(run: Mapping[str, Any]) -> str:
    """What fake agent run `run`, as the fake logged it, was told: its definition's body, then its message.

    The tests' templates pass the prompt last, and the snapshot as OpenCode's config directory, whose definition of the
    agent holds the prompt's fixed instructions as its body (DESIGN §13).
    """
    argv = run["argv"]
    agent = argv[argv.index("--agent") + 1]
    definition = Path(run["env"]["OPENCODE_CONFIG_DIR"]) / "agents" / f"{agent}.md"
    body = definition.read_text().rpartition("\n---\n")[2].lstrip("\n")
    return f"{body}\n{argv[-1]}"


def has_deadline(run: Mapping[str, Any], minutes: int, *, before: float, after: float) -> bool:
    """Whether agent run `run`, as the fake agent logged it, had a deadline `minutes` after its start.

    The start is between `before` and `after`; the deadline is the moment the clock canopy kills it by fires, in
    `CANOPY_DEADLINE` (DESIGN §33).
    """
    deadline = int(run["env"][procs.DEADLINE_ENV])
    return int(before) + minutes * 60 <= deadline <= after + minutes * 60


def titled_overseer(env: CanopyEnv) -> None:
    """Have the test config's overseer template pass `--title={title}`, as the default templates do."""
    template = "agent run --agent canopy-overseer {prompt}"
    text = env.user_file.read_text()
    assert template in text
    env.write_user(text.replace(template, template.replace(" {prompt}", " --title={title} {prompt}")))


def titled_workers(env: CanopyEnv) -> None:
    """Have the test config's worker template pass `--title={title}`, as the default templates do.

    So the fake worker knows the ticket each run is of (FAKE_WORKER_FOR in the fake).
    """
    template = "agent run --agent canopy-worker {prompt}"
    text = env.user_file.read_text()
    assert template in text
    env.write_user(text.replace(template, template.replace(" {prompt}", " --title={title} {prompt}")))


def overseer_titles(agent_log: Path) -> list[str]:
    """The session title each fake overseer run was given, in order, under `titled_overseer`."""
    return [
        str(run["argv"][3]).removeprefix("--title=")
        for run in agent_runs(agent_log)
        if run["argv"][:3] == ["run", "--agent", "canopy-overseer"]
    ]


def commands_run(agent_log: Path) -> list[list[dict[str, Any]]]:
    """The commands each fake agent run ran, in order: each one's argv, exit code, stdout, and stderr."""
    return [run["commands"] for run in agent_runs(agent_log)]


def state_block(agent_log: Path) -> dict[str, Any]:
    """The state block the last agent to run, an overseer, was given in its prompt: on stdin, or its last argument."""
    *_, overseer = agent_runs(agent_log)
    return json_block(overseer["stdin"] or overseer["argv"][-1])


def json_block(text: str) -> dict[str, Any]:
    """The first fenced JSON block in `text`, parsed."""
    block: dict[str, Any] = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    return block


# The overseer's tools over MCP (DESIGN §27)

#: How a test starts `canopy _mcp`, as the runtime starts it for the overseer: this interpreter's canopy, here.
MCP_SERVER = (sys.executable, "-m", "canopy", "_mcp")
#: What a client says first, and the notification it sends once the server has answered.
MCP_OPENING: tuple[Mapping[str, object], ...] = (
    {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "tests", "version": "0"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
)
#: A `tools/list` request, for `mcp_session`.
LIST_TOOLS: Mapping[str, object] = {"method": "tools/list"}


def logged(text: str) -> git_tools.Commits:
    """The commits the text of a call to the git tool `log` holds: its JSON, after the note before it."""
    return git_tools.Commits.model_validate_json(text.removeprefix(f"{git_tools.DATA_NOTE}\n\n"))


def tool_call(name: str, /, **arguments: object) -> dict[str, object]:
    """A `tools/call` request of tool `name` with `arguments`, for `mcp_session`."""
    return {"method": "tools/call", "params": {"name": name, "arguments": arguments}}


@dataclass(frozen=True)
class Served:
    """What `canopy _mcp` answered in one session, and how it ended."""

    #: Each response, by the id of the request it answers: `initialize` is 0, the session's requests 1 on.
    responses: Mapping[object, Mapping[str, Any]]
    #: What the server wrote to stderr.
    stderr: str
    #: Its exit code, once its stdin closed.
    returncode: int

    def said(self, request_id: int = 1) -> Said:
        """What tool call `request_id` came back with; fails the test if it was answered with a protocol error."""
        response = self.responses[request_id]
        assert "result" in response, response
        [content] = response["result"]["content"]
        return Said(content["text"], response["result"]["isError"])

    def structured(self, request_id: int = 1) -> Mapping[str, Any] | None:
        """What tool call `request_id` came back with as structured content; None when it came back with none."""
        return self.responses[request_id]["result"].get("structuredContent")

    def listed(self, request_id: int = 1) -> list[str]:
        """The name of each tool `tools/list` request `request_id` was answered with."""
        return [t["name"] for t in self.responses[request_id]["result"]["tools"]]


def mcp_session(
    *requests: Mapping[str, object],
    raw: Sequence[str] = (),
    chore: bool = False,
    reports: bool = False,
    status: bool = False,
    git: Sequence[str] = (),
) -> Served:
    """Talk to `canopy _mcp` as the runtime does, here, in this environment.

    It talks as the runtime does for the overseer, with `chore` for a chore's run, `reports` for the server of canopy's
    reports, `status` for a worker's, planner's, or reviewer's card, or with `git`, each `NAME=PATH`, for a review's or
    a plan's: open the session, send each of `requests` numbered from 1, then each line of `raw` as it is, and close
    the server's stdin.

    The server answers one message at a time, and the session waits for it to exit, which it must on its own.
    """
    numbered = [{"jsonrpc": "2.0", "id": n, **request} for n, request in enumerate(requests, 1)]
    lines = [*(json.dumps(m) for m in (*MCP_OPENING, *numbered)), *raw]
    checkouts = [arg for checkout in git for arg in ("--git", checkout)]
    flags = [*(["--chore"] if chore else []), *(["--reports"] if reports else []), *(["--status"] if status else [])]
    server = (*MCP_SERVER, *flags, *checkouts)
    result = procs.SubprocessRunner().run(server, stdin="".join(f"{line}\n" for line in lines), timeout=60)
    assert not result.timed_out, f"canopy _mcp did not exit when its stdin closed: {result.stderr}"
    answers = [json.loads(line) for line in result.stdout.splitlines()]
    return Served({a["id"]: a for a in answers}, result.stderr, result.returncode)


def mcp_lines(*moves: Called) -> list[str]:
    """What a client sends `canopy _mcp` to make each of the overseer's `moves`: the opening, then each call from id 1.

    A test pipes them, a line each, to a server it starts itself, such as one inside a sandbox, and reads the answers
    with `answered_lines`.
    """
    numbered = [
        {**tool_call(move.name.removeprefix(f"{mcp.SERVER}_"), **move.arguments), "jsonrpc": "2.0", "id": n}
        for n, move in enumerate(moves, 1)
    ]
    return [json.dumps(message, default=str) for message in (*MCP_OPENING, *numbered)]


def answered_lines(stdout: str) -> list[Said]:
    """What each call `mcp_lines` sent came back with, in order, read from what the server printed."""
    answers = {a["id"]: a for a in map(json.loads, stdout.splitlines()) if isinstance(a.get("id"), int) and a["id"]}
    return [Served(answers, "", 0).said(n) for n in sorted(answers)]


def inline_servers(run: Mapping[str, Any]) -> dict[str, list[str]]:
    """The servers of canopy's that a fake agent run's inline config (FAKE_AGENT_LOG's `env`) gave it, with commands."""
    inline: dict[str, Any] = json.loads(run["env"].get("OPENCODE_CONFIG_CONTENT", "{}")).get("mcp", {})
    return {name: entry["command"] for name, entry in inline.items()}


def ancestors(pid: int) -> list[int]:
    """Each process `pid` descends from, its parent first, as /proc says now."""
    found: list[int] = []
    while pid > 1:
        # The parent is the field after the state, which follows the parenthesized command name.
        pid = int(Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[1])
        found.append(pid)
    return found


# Notifications


def messages(out: Path) -> list[str]:
    """Each message a `sink_script` or `notified` command was sent, in order; none if it was never run."""
    return out.read_text().split("--\n")[:-1] if out.exists() else []


# Chores


def chore_decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str | None, str, str]]:
    """Each decision the tick recorded, as (chore, action, rationale)."""
    return [(d.chore, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]


def chore_toml(name: str = "build-health", *, every: int = 120, extra: str = "") -> str:
    """A `[chores.<name>]` table for the user file, its command the fake agent."""
    return (
        f"\n[chores.{name}]\nprompt = {json.dumps(str(Path.home() / 'chores' / f'{name}.md'))}\n"
        f"cmd = 'agent run --agent canopy-chore {{prompt}}'\nevery_minutes = {every}\n{extra}"
    )


# The loop's clock and terminal


@dataclass
class FakeTime:
    """A monotonic clock that only `sleep` moves. `on_sleep` runs after each sleep, to act during the wait."""

    now: float = 0.0
    slept: list[float] = field(default_factory=list)
    woke: list[float] = field(default_factory=list)  # the clock after each sleep
    on_sleep: Callable[[], None] | None = None

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        self.woke.append(self.now)
        if self.on_sleep is not None:
            self.on_sleep()


@dataclass
class FakeKeys:
    """What the operator types: `pressed()` returns, and empties, what `type` queued, as `keys.listen`'s function."""

    queued: list[str] = field(default_factory=list)
    reads: int = 0

    def type(self, text: str) -> None:
        self.queued.append(text)

    def pressed(self) -> str:
        self.reads += 1
        text = "".join(self.queued)
        self.queued.clear()
        return text


def console(width: int = 200) -> tuple[Console, io.StringIO]:
    """A console that draws as on a terminal `width` columns wide, without colors, and what it printed."""
    out = io.StringIO()
    return Console(file=out, width=width, highlight=False, force_terminal=True, color_system=None), out


def log_file() -> tuple[Console, io.StringIO]:
    """A console writing to a file, as the daemon's does, which the loop writes logfmt lines to, and what it printed."""
    out = io.StringIO()
    return Console(file=out, width=200, highlight=False), out


# Migrations


def journal_at(journals: Journals, tmp_path: Path, version: int) -> sqlite3.Connection:
    """A journal migrated through `version`, as an older canopy left it, for a test of what later migrations do."""
    return journals.open_through(tmp_path / "canopy.db", shipped_through(tmp_path / "migrations", version))


def old_ticket(conn: sqlite3.Connection, key: str) -> None:
    """Record ticket `key` in a journal `journal_at` opened, with only the columns its first migration made."""
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES (?, '/r', ?, ?)",
        (key, db.now(), db.now()),
    )


def shipped_through(dest: Path, version: int) -> Path:
    """Copy the shipped migrations through `version` into `dest`, the directory an older canopy shipped."""
    dest.mkdir(parents=True, exist_ok=True)
    for m in db.discover(resources.migrations_dir())[:version]:
        (dest / m.path.name).write_text(m.path.read_text())
    return dest


def versions_after(version: int) -> list[int]:
    """The shipped migrations after `version`: what upgrading a journal at `version` applies."""
    return [m.version for m in db.discover(resources.migrations_dir()) if m.version > version]


def ended_tick(conn: sqlite3.Connection, ended: str | None, status: str = "ok") -> int:
    """A tick that ended at `ended` with `status`, or one still running, for what garbage collection keeps of it."""
    cursor = conn.execute(
        "INSERT INTO ticks (started_at, ended_at, status) VALUES (?, ?, ?)",
        (ended or db.now(), ended, status),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def run_with_files(conn: sqlite3.Connection, env: CanopyEnv, tick_id: int, ended: str | None) -> Path:
    """A worker run of `tick_id` that ended at `ended`, or is running, with its log and prompt written: 110 bytes."""
    db.touch_ticket(conn, KEY, str(env.root))
    cursor = conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, log_path) "
        "VALUES (?, ?, 'implement', 'agent/x', ?, ?, ?, '')",
        (tick_id, KEY, ended or db.now(), ended, "done" if ended else "running"),
    )
    log = env.state_dir / "runs" / f"{cursor.lastrowid}.log"
    conn.execute("UPDATE runs SET log_path = ? WHERE id = ?", (str(log), cursor.lastrowid))
    write_file(log, 100)
    write_file(log.with_suffix(".prompt"), 10)
    return log


def write_file(path: Path, size: int, *, hours_old: float = 0) -> Path:
    """Write `size` bytes to `path`, its parents made, its modification time `hours_old` hours ago."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if hours_old:
        moment = time.time() - hours_old * 3600
        os.utime(path, (moment, moment))
    return path
