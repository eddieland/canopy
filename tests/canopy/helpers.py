"""Helpers the tests share: ticks and the journal, scripting the fake agents, and running canopy in this process.

A helper more than one test module uses lives here, or in `web_helpers.py` or `review_helpers.py`, never in a test
module: a test module imports from no other (`test_layers.py`). Fixtures live in the conftest files.
"""

import io
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple
from unittest import mock

from rich.console import Console

from canopy.cli.main import main
from canopy.core import config, db, workspace
from canopy.core.context import Context
from canopy.infra import logs, procs, resources
from tests.conftest import CanopyEnv, Journals

KEY = "PROJ-1"
# The label the test operator's tickets carry (`user_toml`), and the arguments of an `implement` dispatch of one.
LABEL = "agent-ready-tester"
IMPLEMENT = ("--label", LABEL, "--kind", "implement")
# An `implement` on the branch WORKER_DONE names.
WORK = (*IMPLEMENT, "--slug", "work")
WORKER_DONE = json.dumps(
    {"status": "done", "branch": "agent/PROJ-1-work", "pr": "https://example.test/pr/1", "summary": "did it"}
)
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
    "PR_LABEL": "agent",
    "TIMEOUT_MINUTES": "45",
    "ATTEMPT": "1",
    "MAX_ATTEMPTS": "2",
    "PR_URL": "https://example.test/pr/1",
    "REPOSITORIES": "This run works in one repository:\n- `repo` at `/pool/1/repo`: branch `agent/PROJ-1-work`",
    "PRS": '{"repo":"<url or null>"}',
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
    "REVIEW_FINDINGS": "None.",
}


# Ticks and the journal


@contextmanager
def in_tick(conn: sqlite3.Connection, *, dry_run: bool = False) -> Iterator[int]:
    """Start a tick and act inside it, as the overseer does: CANOPY_TICK_ID names it until the block ends."""
    tick_id = db.start_tick(conn, dry_run=dry_run)
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": str(tick_id)}):
        yield tick_id


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
    db.finish_tick(ctx.conn, tick_id, "ok", "test")
    return run_id


def last_run(conn: sqlite3.Connection) -> sqlite3.Row:
    """The run recorded last."""
    row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    return row


def slot_of(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    """The one slot a run in one repository leased."""
    [row] = db.run_slots(conn, run_id)
    return row


def unit_of(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    """The one unit of a ticket in one repository."""
    [row] = db.units(conn, key)
    return row


def prompt_of(env: CanopyEnv, run_id: int) -> str:
    """The prompt the run's worker was given."""
    return (env.state_dir / "runs" / f"{run_id}.prompt").read_text()


def wait_for_run(conn: sqlite3.Connection, run_id: int, timeout: float = 30) -> sqlite3.Row:
    """Wait for a detached run to close its row."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = db.get_run(conn, run_id)
        assert row is not None
        if row["status"] != "running":
            return row
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} still running after {timeout}s")


def lifelock_left(row: sqlite3.Row, timeout: float = 30) -> bool:
    """Whether the lifelock file of a closed run is still there once its process has exited.

    The process closes its row, then removes the file, then exits, so the file is looked for only after the exit.
    """
    deadline = time.monotonic() + timeout
    while procs.alive(int(row["pid"])) and time.monotonic() < deadline:
        time.sleep(0.05)
    return procs.lifelock(Path(row["log_path"])).exists()


def pool(treehouse_state: Path) -> list[dict[str, object]]:
    """Every slot the fake treehouse holds: the pool it uses without TREEHOUSE_ROOT, then each repository's."""
    state = json.loads(treehouse_state.read_text())
    slots: list[dict[str, object]] = [
        *state.get("slots", []),
        *(s for p in state.get("pools", {}).values() for s in p.get("slots", [])),
    ]
    return slots


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
        db.finish_tick(conn, tick_id, "ok", "test")
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
        db.finish_tick(conn, tick_id, "ok", "test")
        run_id = int(last_run(conn)["id"])
        assert main(["_run", str(run_id)], runner=runner) == 0
    run = db.get_run(conn, run_id)
    assert run is not None
    return run


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


def canopy(*args: str) -> list[str]:
    """The command an agent runs to call `canopy` with `args`."""
    return ["canopy", *args]


@contextmanager
def overseer_does(*commands: list[str], result: str = TICK_DONE, queried: str | None = None) -> Iterator[None]:
    """Until the block ends, the fake overseer runs `commands` and then prints `result`, by default ending its tick.

    `queried`, if given, is what it records when the tracker query is due; see FAKE_AGENT_QUERIED in the fake.
    """
    env = {"FAKE_OVERSEER_COMMANDS": json.dumps(commands), "FAKE_OVERSEER_RESULT": result}
    if queried is not None:
        env["FAKE_OVERSEER_QUERIED"] = queried
    with mock.patch.dict(os.environ, env):
        yield


def waits(*keys: str) -> list[list[str]]:
    """The commands an overseer runs to wait on each of `keys`, as it must on a ticket it has nothing to do for."""
    return [canopy("decide", key, "wait", "--rationale", "nothing to do yet") for key in keys]


@contextmanager
def worker_does(*commands: list[str], result: str = WORKER_DONE) -> Iterator[None]:
    """Until the block ends, the fake worker runs `commands` and then prints `result`."""
    with mock.patch.dict(
        os.environ, {"FAKE_WORKER_COMMANDS": json.dumps(list(commands)), "FAKE_WORKER_RESULT": result}
    ):
        yield


@contextmanager
def private_worker_does(*commands: list[str], result: dict[str, object]) -> Iterator[None]:
    """Until the block ends, the fake private worker runs `commands` and then prints `result`."""
    with mock.patch.dict(
        os.environ,
        {"FAKE_WORKER_PRIVATE_COMMANDS": json.dumps(list(commands)), "FAKE_WORKER_PRIVATE_RESULT": json.dumps(result)},
    ):
        yield


def blocked_result() -> dict[str, object]:
    """A worker's result: blocked on KEY's `work` branch in `repo`, with no PR, asking QUESTION."""
    return {
        "status": "blocked",
        "branch": f"agent/{KEY}-work",
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


def agent_runs(agent_log: Path) -> list[dict[str, object]]:
    """Each fake agent run, in order, as the fake logged it; none if no agent ran."""
    if not agent_log.exists():
        return []
    return [json.loads(line) for line in agent_log.read_text().splitlines()]


def state_block(agent_log: Path) -> dict[str, Any]:
    """The state block the last agent to run, an overseer, was given in its prompt."""
    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    return json_block(overseer["argv"][3])


def json_block(text: str) -> dict[str, Any]:
    """The first fenced JSON block in `text`, parsed."""
    block: dict[str, Any] = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    return block


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
