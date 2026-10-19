"""Helpers the tests share: ticks and the journal, scripting the fake agents, and running canopy in this process.

A helper more than one test module uses lives here, or in `web_helpers.py` or `review_helpers.py`, never in a test
module: a test module imports from no other (`test_layers.py`). Fixtures live in the conftest files.
"""

import io
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NamedTuple, TypedDict, Unpack, cast
from unittest import mock

from rich.console import Console

from canopy.cli.main import main
from canopy.core import config, db, plans, records, replies, workspace
from canopy.core.context import Context
from canopy.core.vocab import TickStatus
from canopy.infra import logs, procs, resources
from tests.conftest import CanopyEnv, Journals

KEY = "PROJ-1"
# The branch an `implement` of KEY with slug `work` pushes.
BRANCH = f"agent/{KEY}-work"
# The label the test operator's tickets carry (`user_toml`), and the arguments of an `implement` dispatch of one.
LABEL = "agent-ready-tester"
IMPLEMENT = ("--label", LABEL, "--kind", "implement")
# An `implement` on the branch WORKER_DONE names.
WORK = (*IMPLEMENT, "--slug", "work")
WORKER_DONE = json.dumps({"status": "done", "branch": BRANCH, "pr": "https://example.test/pr/1", "summary": "did it"})
# The PR `run_drafting`'s worker opens.
DRAFTS_PR = "https://github.com/acme/api/pull/7"
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
    "CONTEXT": "None.",
    "AUTHORIZED_REPLIERS": "`alice`",
    "LABELS": "`agent-ready-alice`",
    "REQUEST": "10234",
    "MAP": "/ws/MAP.md",
    "WORKER_COMMENT": "starts with `CANOPY:` outside any quote",
    "MARK_COMMENTS": "In every comment and reply you post, start it with `CANOPY:` and a space.",
    "OPEN_PR": "Open each PR through the GitHub MCP.",
    "TRUSTED_REVIEWERS": "`octocat`",
    "OPERATOR_MESSAGES": "No messages from the operator.",
    "PREVIOUS_RUNS": "None: no earlier run of this ticket has ended.",
    "REVIEW_FINDINGS": "None.",
    "PLAN": "None.",
    "REASONS": "- `review`: review comments to address.",
    # How comments reach GitHub under `trust.review_replies = "post"`, the text the prompts held before (DESIGN §29).
    **replies.posted_values("In every comment and reply you post, start it with `CANOPY:` and a space.", "needs-human"),
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
    conn: sqlite3.Connection, owner: object, reads: str, insert: str, *params: object
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


def earlier(now: datetime, days: float, hours: float = 0) -> str:
    """The time `days` and `hours` before `now`, as the journal writes it."""
    return db.format_time(now - timedelta(days=days, hours=hours))


def only_tick(conn: sqlite3.Connection) -> records.Tick:
    """The one tick in the journal."""
    [tick] = records.fetch_all(conn, records.Tick, "SELECT * FROM ticks")
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


def slot_of(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    """The one slot a run in one repository leased."""
    [row] = db.run_slots(conn, run_id)
    return row


def unit_of(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    """The one unit of a ticket in one repository."""
    [row] = db.units(conn, key)
    return row


def plan_file(env: CanopyEnv, run_id: int, key: str = KEY) -> Path:
    """Where the plan run `run_id` of `key` wrote its plan, in the workspace's state directory."""
    return env.state_dir / "plans" / key / f"{run_id}.md"


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


def pool_statuses(treehouse_state: Path) -> list[str]:
    """The status of every slot the fake treehouse holds, in `pool`'s order."""
    return [str(s["status"]) for s in pool(treehouse_state)]


# Dispatching in this process


class Dispatched(NamedTuple):
    """What `canopy dispatch` did: its exit code, and the decisions of the tick it ran in, as (action, rationale)."""

    code: int
    decisions: list[tuple[str, str]]


def dispatch_in_tick(
    conn: sqlite3.Connection, *args: str, key: str = KEY, runner: procs.Runner | None = None
) -> Dispatched:
    """In a tick of its own, run `canopy dispatch` of `key` in `repo` with `args`; the run it starts does not run."""
    with in_tick(conn) as tick_id:
        code = main(["dispatch", key, "--repo", "repo", *args], runner=runner or InlineRunner())
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        return Dispatched(code, decisions(conn, tick_id))


def dispatch_and_run(
    conn: sqlite3.Connection, *args: str, key: str = KEY, runner: procs.Runner | None = None
) -> sqlite3.Row:
    """Dispatch as `dispatch_in_tick` does, then do the run in this process, as the detached one would.

    Returns:
        The run, closed.
    """
    runner = runner or InlineRunner()
    with in_tick(conn) as tick_id:
        assert main(["dispatch", key, "--repo", "repo", *args], runner=runner) == 0, decisions(conn, tick_id)
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        run_id = int(last_run(conn)["id"])
        assert main(["_run", str(run_id)], runner=runner) == 0
    return present(db.get_run(conn, run_id))


def dispatch_refused(conn: sqlite3.Connection, *args: str, key: str = KEY) -> list[tuple[str, str]]:
    """Dispatch as `dispatch_in_tick` does, expecting a refusal.

    Returns:
        The tick's decisions, as (action, rationale).
    """
    code, made = dispatch_in_tick(conn, *args, key=key)
    assert code == 1, made
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
    ) -> procs.Result:
        if self.timeout_agent and "agent" in args[:3]:
            # As the real runner does, each line goes to `on_line` as it is printed.
            if on_line is not None:
                for line in self.timeout_stdout.splitlines(keepends=True):
                    on_line(line)
            return procs.Result(tuple(args), -9, self.timeout_stdout, "", timed_out=True)
        return procs.SubprocessRunner().run(
            args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start, on_line=on_line
        )

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002  (starts nothing)
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawned.append(tuple(args))
        return os.getpid()


# Scripting the fake agents (tests/fakes/agent)
#
# A `*_does` helper scripts what an agent does from start to end: its commands, none if not given, then its result
# line. A `*_reports` helper sets the result line, and commands only if given, so it can sit inside a block that set
# them. `Behavior` covers the rest; `scripted` is the one they all go through.


def canopy(*args: str) -> list[str]:
    """The command an agent runs to call `canopy` with `args`."""
    return ["canopy", *args]


class Behavior(TypedDict, total=False):
    """What a fake agent does besides run its commands and print its result line, as tests/fakes/agent reads it."""

    says: str  # a line it says before the commands run
    exit_code: int
    sleep: float  # seconds it waits before the result line, to run into a timeout
    session: str  # the `sessionID` on each event, with `--format json`
    step_cost: str  # each model call's cost, verbatim JSON, so a test can make it invalid


# The fake's name for each of Behavior's keys, after its FAKE_<ROLE>_ prefix.
BEHAVIOR_SETTINGS = {
    "says": "SAYS",
    "exit_code": "EXIT",
    "sleep": "SLEEP",
    "session": "SESSION",
    "step_cost": "STEP_COST",
}


@dataclass(frozen=True)
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
    *commands: list[str], result: str = TICK_DONE, queried: str | None = None, **behavior: Unpack[Behavior]
) -> Iterator[None]:
    """Until the block ends, the fake overseer runs `commands` and then prints `result`, by default ending its tick.

    `queried`, if given, is what it records when the tracker query is due; see FAKE_AGENT_QUERIED in the fake.
    """
    settings = {"COMMANDS": json.dumps(commands), "RESULT": result}
    if queried is not None:
        settings["QUERIED"] = queried
    with scripted("OVERSEER", settings, behavior):
        yield


@contextmanager
def overseer_records(*items: tuple[str, str], waiting: Iterable[str] = ()) -> Iterator[None]:
    """Until the block ends, the fake overseer records each (key, reason) as needing attention and ends the tick.

    Each key in `waiting` it decides to wait on instead, as it must for a ticket in the journal it records nothing for.
    """
    recorded = [canopy("attention", key, reason, "--detail", f"{key} detail") for key, reason in items]
    with overseer_does(*recorded, *waits(*waiting)):
        yield


def waits(*keys: str, rationale: str = "nothing to do yet") -> list[list[str]]:
    """The commands an overseer runs to wait on each of `keys`, as it must on a ticket it has nothing to do for."""
    return [canopy("decide", key, "wait", "--rationale", rationale) for key in keys]


def with_events(env: CanopyEnv, agent: str) -> None:
    """Have the command that runs `agent` (`canopy-overseer`, ...) ask for OpenCode's JSON events, as defaults do."""
    env.write_user(env.user_file.read_text().replace(f"--agent {agent} ", f"--agent {agent} --format json ", 1))


def with_rebase(env: CanopyEnv) -> None:
    """Let workers rebase and push with a lease, never merging a base in (`[trust] rebase`)."""
    env.append_user("\n[trust]\nrebase = true\n")


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
    return records.fetch_all(conn, records.Draft, "SELECT * FROM drafts ORDER BY id")


def run_drafting(conn: sqlite3.Connection, entries: object, *args: str, pr: str = DRAFTS_PR) -> sqlite3.Row:
    """Run KEY's next run, an `implement` on its `work` branch unless `args` says otherwise, its worker opening `pr` in
    `repo` and sending `entries` as its drafts."""
    return run_with(conn, *(args or WORK), prs={"repo": pr}, drafts=entries)


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


def reads(state: Path, program: str = "connect") -> list[dict[str, Any]]:
    """What the fake GitHub's `program` was asked, each run in order."""
    log = state.parent / "github.jsonl"
    lines: list[str] = log.read_text().splitlines() if log.exists() else []
    return [json.loads(line)["request"] for line in lines if json.loads(line)["program"] == program]


def memories(conn: sqlite3.Connection) -> list[records.Memory]:
    """Every memory in the journal, in the order they were written."""
    return records.fetch_all(conn, records.Memory, "SELECT * FROM memories ORDER BY id")


def run_with(conn: sqlite3.Connection, *args: str, key: str = KEY, **fields: object) -> sqlite3.Row:
    """Dispatch and run `key`'s next run with `args`, its worker committing, pushing, and sending `fields`."""
    branch = f"agent/{key}-work"
    line = worker_result(**fields).replace(BRANCH, branch)
    with worker_does(*commit_and_push(branch), result=line):
        return dispatch_and_run(conn, *args, key=key, runner=InlineRunner())


def worker_result(**memory: object) -> str:
    """A worker's result line: done on KEY's `work` branch in `repo`, carrying the memory fields given."""
    return json.dumps({"status": "done", "branch": BRANCH, "prs": {"repo": None}, "summary": "did it", **memory})


def worker_does(*commands: list[str], result: str = WORKER_DONE, **behavior: Unpack[Behavior]) -> Script:
    """Until the block ends, the fake worker runs `commands` and then prints `result`.

    Returns:
        The worker's script, a block.
    """
    return scripted("WORKER", {"COMMANDS": json.dumps(commands), "RESULT": result}, behavior)


@contextmanager
def private_worker_does(*commands: list[str], result: dict[str, object]) -> Iterator[None]:
    """Until the block ends, the fake private worker runs `commands` and then prints `result`."""
    with scripted("WORKER_PRIVATE", {"COMMANDS": json.dumps(commands), "RESULT": json.dumps(result)}):
        yield


@contextmanager
def splitter_reports(report: object, *commands: list[str]) -> Iterator[None]:
    """Until the block ends, the fake splitter prints `report`, verbatim if it is a string, after running `commands` if
    given."""
    with scripted("SPLITTER", reported(report, commands)):
        yield


@contextmanager
def chore_reports(report: object, *commands: list[str], **behavior: Unpack[Behavior]) -> Iterator[None]:
    """Until the block ends, the fake chore prints `report`, verbatim if it is a string, after running `commands` if
    given."""
    with scripted("CHORE", reported(report, commands), behavior):
        yield


def reported(report: object, commands: Sequence[list[str]]) -> dict[str, str]:
    """A `*_reports` helper's settings: `report` as the result line, verbatim if a string, and `commands` if any."""
    settings = {"RESULT": report if isinstance(report, str) else json.dumps(report)}
    if commands:
        settings["COMMANDS"] = json.dumps(commands)
    return settings


@contextmanager
def planner_does(*commands: list[str], plan: str | None, result: Mapping[str, object] | None = None) -> Iterator[None]:
    """Until the block ends, the fake planner writes `plan` to its desk's plan file, runs `commands`, and reports.

    It writes as the planner's edit tool would, before `commands`; with `plan` None it writes no file. `result`, its
    result line, defaults to a `done` one (DESIGN §25).
    """
    script = "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])"
    write = [["python3", "-c", script, plans.WRITTEN, plan]] if plan is not None else []
    line = json.dumps(result if result is not None else {"status": "done", "summary": "planned it"})
    with scripted("PLANNER", {"COMMANDS": json.dumps([*write, *commands]), "RESULT": line}):
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


def agent_runs(agent_log: Path) -> list[dict[str, Any]]:
    """Each fake agent run, in order, as the fake logged it; none if no agent ran."""
    if not agent_log.exists():
        return []
    return [json.loads(line) for line in agent_log.read_text().splitlines()]


def titled_overseer(env: CanopyEnv) -> None:
    """Have the test config's overseer template pass `--title={title}`, as the default templates do."""
    template = "agent run --agent canopy-overseer {prompt}"
    text = env.user_file.read_text()
    assert template in text
    env.write_user(text.replace(template, template.replace(" {prompt}", " --title={title} {prompt}")))


def titled_workers(env: CanopyEnv) -> None:
    """Have the test config's worker template pass `--title={title}`, as the default templates do, so the fake worker
    knows the ticket each run is of (FAKE_WORKER_FOR in the fake)."""
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
    """The state block the last agent to run, an overseer, was given in its prompt."""
    *_, overseer = agent_runs(agent_log)
    return json_block(overseer["argv"][-1])


def json_block(text: str) -> dict[str, Any]:
    """The first fenced JSON block in `text`, parsed."""
    block: dict[str, Any] = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    return block


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


def console() -> tuple[Console, io.StringIO]:
    """A wide, plain console, and what it printed."""
    out = io.StringIO()
    return Console(file=out, width=200, highlight=False), out


# Migrations


def journal_at(journals: Journals, tmp_path: Path, version: int) -> sqlite3.Connection:
    """A journal migrated through `version`, as an older canopy left it, for a test of what later migrations do."""
    return journals.open_through(tmp_path / "canopy.db", shipped_through(tmp_path / "migrations", version))


def shipped_through(dest: Path, version: int) -> Path:
    """Copy the shipped migrations through `version` into `dest`, the directory an older canopy shipped."""
    dest.mkdir(parents=True, exist_ok=True)
    for m in db.discover(resources.migrations_dir())[:version]:
        (dest / m.path.name).write_text(m.path.read_text())
    return dest


def versions_after(version: int) -> list[int]:
    """The shipped migrations after `version`: what upgrading a journal at `version` applies."""
    return [m.version for m in db.discover(resources.migrations_dir()) if m.version > version]
