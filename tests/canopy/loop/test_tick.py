"""End to end: `canopy tick --dry-run` against the fake treehouse and a fake overseer that calls canopy's real tools."""

import dataclasses
import errno
import json
import os
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import commit_hooks, config, db, definitions, plans, records
from canopy.core.vocab import Phase, RunKind, TickStatus
from canopy.infra import lock, logs, procs
from canopy.loop import attention, duties, mcp, tick
from tests.canopy.helpers import (
    KEY,
    LABEL,
    agent_runs,
    calls,
    canopy,
    earlier,
    has_deadline,
    in_tick,
    listed,
    minute,
    only_tick,
    overseer_titles,
    present,
    ticket_sets,
    titled_overseer,
    tools_of,
    tools_printed,
    tracker_holds,
    waits,
    with_events,
    worker_ran,
)
from tests.canopy.scenario_helpers import Scenario, sets_phase
from tests.conftest import CanopyEnv, executable


def test_dry_run_tick_records_the_overseer_plan(scenario: Scenario, treehouse_state: Path) -> None:
    env = scenario.env
    before = time.time()
    ticked = scenario.tick(
        calls("canopy_decide", decisions=[{"key": "PROJ-1", "action": "wait", "rationale": "checks pending"}]),
        calls(
            "canopy_ticket-set",
            tickets=[{"key": "PROJ-1", "repo": "repo", "phase": "ci_running", "cursors": {"ci": "1"}}],
        ),
        calls("canopy_dispatch", key="PROJ-2", kind="implement", label=LABEL, repos=["repo"]),
        calls("canopy_attention", key="PROJ-3", reason="needs_author", detail="https://example.test/pr/3"),
        calls("canopy_decide", decisions=[{"key": "PROJ-4;rm", "action": "wait", "rationale": "bad key"}]),
        dry_run=True,
    )
    assert ticked.printed.out.startswith("tick 1: ok: dry run; 4 decisions")
    after = time.time()

    [run] = agent_runs(scenario.agent_log)
    _acted_through_its_tools(run)
    argv = run["argv"]
    assert isinstance(argv, list)
    assert argv[:3] == ["run", "--agent", "canopy-overseer"]
    # The message is the state block alone; the prompt is in the definition, cached across ticks (DESIGN §6).
    prompt = argv[3]
    assert isinstance(prompt, str)
    assert prompt.startswith("## State\n")
    assert "# canopy overseer" not in prompt
    # The state is compact JSON, one line: every step of the tick re-reads it (DESIGN §6 step 4).
    state = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert "\n" not in state
    assert '"tick_id":1,' in state
    assert '"dry_run":true' in state
    assert '"labels":["agent-ready-tester"]' in state
    assert run["cwd"] == str(env.root)
    snapshot = definitions.ensure(env.state_dir, config.load(env.root))
    # Its deadline, the moment its timeout fires, for the clock in the snapshot (DESIGN §33).
    assert has_deadline(run, 15, before=before, after=after)
    # Its tools: canopy's own server, in the inline config of its process alone, and code mode, which hides them, off.
    server = {"type": "local", "command": list(mcp.COMMAND), "cwd": str(env.root), "enabled": True, "timeout": 900_000}
    assert run["env"] == {
        "CANOPY_TICK_ID": "1",
        "CANOPY_DEADLINE": run["env"]["CANOPY_DEADLINE"],
        "OPENCODE_CONFIG_DIR": str(snapshot),
        "OPENCODE_CONFIG_CONTENT": json.dumps({"mcp": {"canopy": server}}),
        "OPENCODE_EXPERIMENTAL_CODE_MODE": "false",
    }
    assert "\n# canopy overseer\n" in (snapshot / "agents" / "canopy-overseer.md").read_text()

    conn = scenario.conn
    assert only_tick(conn).id == ticked.tick.id
    assert (ticked.tick.status, ticked.tick.dry_run) == ("ok", 1)
    assert ticked.tick.ended_at is not None
    assert [(d.ticket_key, d.action) for d in ticked.decisions] == [
        (None, "queried"),
        ("PROJ-1", "wait"),
        ("PROJ-2", "dispatch:implement"),
        ("PROJ-3", "attention:needs_author"),
    ]
    proj1 = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert proj1["phase"] is None
    [unit] = db.units(conn, "PROJ-1")  # a phase about the PR is the unit's
    assert (unit.phase, unit.ci_cursor) == ("ci_running", None)  # a dry run never advances cursors
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0  # nothing was dispatched
    assert ticked.runs == []
    assert [c[0] for c in json.loads(treehouse_state.read_text())["calls"]] == ["status"]

    log_lines = [json.loads(line) for line in (env.state_dir / "canopy.log").read_text().splitlines()]
    tick_lines = [line for line in log_lines if line["msg"] in ("tick started", "running overseer", "tick finished")]
    assert [line["tick_id"] for line in tick_lines] == [1, 1, 1]
    output = env.state_dir / "ticks" / "1.log"
    assert output.read_text().startswith("fake agent: starting")
    assert output.stat().st_mode & 0o077 == 0
    # The state block is kept beside it, as the input of the transcript's first model call (DESIGN §22).
    kept = env.state_dir / "ticks" / "1.prompt"
    assert kept.read_text() == prompt
    assert kept.stat().st_mode & 0o077 == 0
    assert env.state_dir.stat().st_mode & 0o077 == 0


def _acted_through_its_tools(run: Mapping[str, object]) -> None:
    """The overseer `run` ran no command and recorded everything through its tools (DESIGN §27), a refusal included."""
    assert run["commands"] == []
    made = run["tools"]
    assert isinstance(made, list)
    # The tracker source read the query, which canopy recorded, so the overseer records none (DESIGN §39).
    assert [c["name"] for c in made] == [
        f"canopy_{name}" for name in ("decide", "ticket-set", "dispatch", "attention", "decide")
    ]
    # A refusal is a tool error naming the field, and the overseer goes on: nothing recorded it.
    assert [c["error"] for c in made] == [False] * 4 + [True], made
    assert made[-1]["text"].startswith("decisions.0.key: invalid ticket key 'PROJ-4;rm'")


def test_a_tick_records_its_overseers_latest_tool_call_from_the_events_it_prints(scenario: Scenario) -> None:
    """Its decision, the call it made last, is on the tick, read as it printed it (DESIGN §8)."""
    with_events(scenario.env, "canopy-overseer")
    tick_id = scenario.tick(*waits(KEY)).tick.id
    row = present(db.get_tick(scenario.conn, tick_id))
    assert (row.activity_tool, row.activity_at is not None) == ("canopy_decide", True)


@pytest.mark.parametrize(
    ("woken_by", "tickets", "running", "open_items", "title"),
    [
        (None, 0, 0, 0, "tick 7 · by hand · nothing open"),
        ("run", 2, 1, 0, "tick 7 · run ended · 2 tickets, 1 running"),
        ("timer", 1, 0, 1, "tick 7 · timer · 1 ticket, 1 needs you"),
        ("web", 0, 0, 3, "tick 7 · asked · 3 need you"),
    ],
)
def test_the_session_title_says_what_started_the_tick_and_what_it_faces(
    woken_by: tick.WokenBy | None,
    tickets: int,
    running: int,
    open_items: int,
    title: str,
) -> None:
    """So the runtime's session list tells a tick with something before it from one of a quiet stretch (DESIGN §13)."""
    assert tick.session_title(7, woken_by, tickets=tickets, running=running, open_items=open_items) == title


def test_a_tick_run_by_hand_gives_its_overseer_a_session_title(scenario: Scenario) -> None:
    titled_overseer(scenario.env)
    ci_running = sets_phase("PROJ-1", Phase.CI_RUNNING, repo="repo")
    for _ in range(2):
        scenario.tick(ci_running, *waits("PROJ-1", rationale="checks pending"), dry_run=True)
    assert overseer_titles(scenario.agent_log) == ["tick 1 · by hand · 1 ticket", "tick 2 · by hand · 1 ticket"]


def test_overseer_state_names_the_configured_needs_human_label(scenario: Scenario) -> None:
    scenario.configures("workspace", tracker={"needs_human_label": "blocked-on-team"})
    scenario.tick(*waits(KEY), dry_run=True)
    [run] = agent_runs(scenario.agent_log)
    argv = run["argv"]
    assert isinstance(argv, list)
    assert '"needs_human_label":"blocked-on-team"' in str(argv[3])


def test_overseer_state_names_the_comment_marks(scenario: Scenario) -> None:
    # The overseer recognizes workers' comments by these, since workers post as the operator (D069).
    scenario.configures(trust={"comment_suffix": "(canopy)"})
    scenario.tick(*waits(KEY), dry_run=True)
    [run] = agent_runs(scenario.agent_log)
    argv = run["argv"]
    assert isinstance(argv, list)
    assert '"comment_prefix":"CANOPY:"' in str(argv[3])
    assert '"comment_suffix":"(canopy)"' in str(argv[3])


def test_next_tick_sees_the_journal(scenario: Scenario) -> None:
    scenario.tick(sets_phase("PROJ-9", Phase.NEEDS_HUMAN, repo="repo"), *waits("PROJ-9"), dry_run=True)
    scenario.tick(*waits("PROJ-9", rationale="needs a human"), dry_run=True)
    second = agent_runs(scenario.agent_log)[1]["argv"]
    assert isinstance(second, list)
    assert '"key":"PROJ-9"' in second[-1]
    assert '"phase":"needs_human"' in second[-1]
    assert '"tick_id":2' in second[-1]


def test_the_state_block_names_the_tickets_marked_done_lately(scenario: Scenario) -> None:
    # A merged ticket stays open in the tracker until a human closes it, so the query keeps finding it: listed, the
    # overseer leaves it alone instead of reading it and marking it done again every tick (DESIGN §7).
    conn = scenario.conn
    repo = str(scenario.env.root)
    with in_tick(conn) as tick_id:
        # The query found each still open but PROJ-8, which a human has closed since it merged.
        found = [f"PROJ-{n}" for n in range(1, 8)]
        db.record_decision(conn, tick_id, None, duties.QUERIED_ACTION, duties.queried_rationale(found))
        for key in ("PROJ-1", "PROJ-2", "PROJ-3", "PROJ-7", "PROJ-8"):
            db.set_ticket(conn, key, repo, done=True)
            db.record_decision(conn, tick_id, key, "done", "merged")
        db.set_ticket(conn, "PROJ-4", repo, done=True)
        db.set_ticket(conn, "PROJ-5", repo, phase=Phase.CI_RUNNING)
        db.record_decision(conn, tick_id, "PROJ-5", "done", "merged")
        # The tracker reports a closed ticket closed, so once it is reopened the query must find it again.
        db.set_ticket(conn, "PROJ-6", repo, done=True)
        db.record_decision(conn, tick_id, "PROJ-6", "done", db.CLOSED_RATIONALE)
        db.finish_tick(conn, tick_id, TickStatus.OK, "")
    # Forgotten, then marked done again with no decision of its own: the earlier one does not count.
    with db.transaction(conn):
        db.forget_ticket(conn, "PROJ-7", channel="cli", branch=None, prs=[])
    db.set_ticket(conn, "PROJ-7", repo, done=True)
    # Time passes for these two tickets alone, which `time_passes` cannot say.
    long_ago = db.format_time(datetime.now(UTC) - timedelta(days=tick.RECENTLY_DONE_DAYS + 1))
    with db.transaction(conn):
        conn.execute("UPDATE decisions SET created_at = ? WHERE ticket_key = 'PROJ-2'", (long_ago,))
        # Its newest `done` decision is the one that counts.
        conn.execute("UPDATE decisions SET created_at = ? WHERE ticket_key = 'PROJ-3'", (long_ago,))
    with in_tick(conn) as tick_id:
        db.record_decision(conn, tick_id, "PROJ-3", "done", "merged, still open")
        db.finish_tick(conn, tick_id, TickStatus.OK, "")
    scenario.tick(*waits("PROJ-5", rationale="checks pending"), dry_run=True)
    state = scenario.state()
    # Not PROJ-2, done too long ago; not PROJ-4, with no `done` decision; not PROJ-5, which is not marked done; not
    # PROJ-6, closed; not PROJ-7, whose decision came before it was forgotten; not PROJ-8, which the query left out.
    assert state["recently_done"] == ["PROJ-1", "PROJ-3"]
    assert [t["key"] for t in state["tickets"]] == ["PROJ-5"]


def test_the_query_runs_every_tick_by_default(scenario: Scenario) -> None:
    ticks = [scenario.tick(*waits(KEY)), scenario.tick(*waits(KEY))]
    assert [t.tick.query_due for t in ticks] == [True, True]


def test_the_query_runs_again_once_its_spacing_has_passed(scenario: Scenario) -> None:
    scenario.configures(tracker={"query_every_minutes": 30})
    # A ticket to decide, so a tick the query is not due on still runs the overseer (DESIGN §39).
    scenario.seen("PROJ-2")
    ticks = [scenario.tick(*waits("PROJ-2")) for _ in range(2)]
    # The first tick ran it 31 minutes ago; the second, which left it out, does not count.
    scenario.time_passes(minutes=31)
    ticks.append(scenario.tick(*waits("PROJ-2")))
    assert [t.tick.query_due for t in ticks] == [True, False, True]


def test_only_a_live_ok_tick_counts_as_having_run_the_query(scenario: Scenario) -> None:
    scenario.configures(tracker={"query_every_minutes": 30})
    # A ticket to decide, so a tick the query is not due on still runs the overseer (DESIGN §39).
    scenario.seen("PROJ-2")
    ticks = [scenario.tick(*waits("PROJ-2"), dry_run=True), scenario.tick(exit_code=3, code=1)]
    ticks += [scenario.tick(*waits("PROJ-2")) for _ in range(2)]
    assert [t.tick.query_due for t in ticks] == [True, True, True, False]


def test_a_tick_from_before_the_spacing_was_recorded_ran_the_query(scenario: Scenario) -> None:
    scenario.configures(tracker={"query_every_minutes": 30})
    conn = scenario.conn
    with in_tick(conn) as tick_id:
        db.finish_tick(conn, tick_id, TickStatus.OK, "")
    assert conn.execute("SELECT query_due FROM ticks").fetchone()["query_due"] is None
    scenario.seen("PROJ-2")
    assert scenario.tick(*waits("PROJ-2")).tick.query_due is False


@pytest.mark.parametrize(
    "case",
    [
        (3, "CANOPY_TICK_DONE", "overseer exited 3"),
        (0, "I got distracted", "final message has no CANOPY_TICK_DONE line"),
        (0, "", "final message has no CANOPY_TICK_DONE line"),
    ],
)
def test_overseer_failure_closes_the_tick(scenario: Scenario, case: tuple[int, str, str]) -> None:
    exit_code, last_line, summary = case
    failed = scenario.tick(*waits(KEY), result=last_line, exit_code=exit_code, dry_run=True, code=1)
    assert only_tick(scenario.conn).id == failed.tick.id
    assert failed.tick.status == "overseer_failed"
    assert summary in failed.tick.summary


@pytest.mark.parametrize(
    ("final", "status"),
    [
        ("CANOPY_TICK_DONE", "ok"),
        ("CANOPY_TICK_DONE\n\nRecorded 6 decisions and dispatched 2 runs.", "ok"),  # a summary after it (tick 150)
        ("Recorded 6 decisions.\n  `CANOPY_TICK_DONE`  ", "ok"),
        ("tick complete", "overseer_failed"),  # the old done line
        ("I'll print CANOPY_TICK_DONE when finished", "overseer_failed"),  # the token is the whole line or nothing
        ("canopy_tick_done", "overseer_failed"),
    ],
)
def test_the_done_token_is_a_line_anywhere_in_the_final_message(scenario: Scenario, final: str, status: str) -> None:
    with_events(scenario.env, "canopy-overseer")
    ticked = scenario.tick(*waits(KEY), result=final, dry_run=True, code=0 if status == "ok" else 1)
    assert ticked.tick.status == status


def test_the_done_token_in_an_earlier_message_fails_the_tick(scenario: Scenario) -> None:
    """A run that named the token, then stopped before the procedure's end, did not finish it."""
    with_events(scenario.env, "canopy-overseer")
    failed = scenario.tick(
        *waits(KEY),
        result="Now reading the next ticket.",
        says="CANOPY_TICK_DONE",
        dry_run=True,
        code=1,
    )
    assert only_tick(scenario.conn).id == failed.tick.id
    assert (failed.tick.status, failed.tick.summary) == (
        "overseer_failed",
        "overseer's final message has no CANOPY_TICK_DONE line",
    )


@pytest.mark.parametrize(
    ("exit_code", "failure"),
    [(1, "overseer exited 1"), (0, "overseer's final message has no CANOPY_TICK_DONE line")],
)
def test_an_overseer_failure_names_the_error_the_runtime_reported(
    scenario: Scenario,
    exit_code: int,
    failure: str,
) -> None:
    with_events(scenario.env, "canopy-overseer")
    server = {"name": "UnknownError", "data": {"message": "Unexpected server error.", "ref": "err_ccf1"}}
    failed = scenario.tick(
        *waits(KEY),
        result="",
        exit_code=exit_code,
        errors=json.dumps([server]),
        dry_run=True,
        code=1,
    )
    assert (failed.tick.status, failed.tick.summary) == (
        "overseer_failed",
        f"{failure}; the runtime reported UnknownError: Unexpected server error. (err_ccf1)",
    )


@pytest.mark.parametrize(
    ("names", "reported"),
    [("ABC", "A; then B; then C"), ("ABCDE", "A; then 3 more; then E"), ("ABAB", "A; then B")],
)
def test_an_overseer_failure_names_each_distinct_error_the_first_and_last_past_three(
    scenario: Scenario,
    names: str,
    reported: str,
) -> None:
    """The first error may be the cause, and the last ended the run (OpenCode goes on after a context overflow)."""
    with_events(scenario.env, "canopy-overseer")
    errors = json.dumps([{"name": name} for name in names])
    failed = scenario.tick(*waits(KEY), result="", exit_code=1, errors=errors, dry_run=True, code=1)
    assert failed.tick.summary == f"overseer exited 1; the runtime reported {reported}"


def test_an_overseer_that_ends_its_tick_after_an_error_is_ok(scenario: Scenario) -> None:
    """The runtime's error is named only for a tick that failed: a session that recovered from it did its work."""
    with_events(scenario.env, "canopy-overseer")
    ticked = scenario.tick(errors=json.dumps([{"name": "ContextOverflowError"}]), dry_run=True)
    assert ticked.tick.status == "ok"


@pytest.mark.parametrize(("last_line", "status"), [("CANOPY_TICK_DONE", "ok"), ("I got distracted", "overseer_failed")])
def test_an_overseer_printing_json_events_is_read_by_their_text(
    scenario: Scenario,
    last_line: str,
    status: str,
) -> None:
    """With OpenCode's `--format json`, its last line of stdout is an event; the done line is in the events' text."""
    with_events(scenario.env, "canopy-overseer")
    ticked = scenario.tick(*waits(KEY), result=last_line, dry_run=True, code=0 if status == "ok" else 1)
    assert ticked.tick.status == status


@pytest.mark.parametrize("last_line", ["CANOPY_TICK_DONE", "I got distracted"])
def test_a_tick_records_and_prints_what_its_overseer_cost(scenario: Scenario, last_line: str) -> None:
    """With events, the tick keeps the overseer's session and summed cost, whether or not the overseer succeeded."""
    with_events(scenario.env, "canopy-overseer")
    read = ["echo", "read it"]
    code = 0 if last_line == "CANOPY_TICK_DONE" else 1
    ticked = scenario.tick(*waits(KEY), read, result=last_line, session="ses_o1", dry_run=True, code=code)

    conn = scenario.conn
    tick = ticked.tick
    assert only_tick(conn).id == tick.id
    assert (tick.session_id, tick.cost_usd) == ("ses_o1", 0.25)  # two model calls, summed
    tokens = ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_read", "tokens_cache_write")
    assert tuple(getattr(tick, c) for c in tokens) == (2000, 400, 60, 8000, 1000)
    assert tick.tokens_peak_context == 5500
    assert (tick.tokens_first_call, tick.tokens_first_cache_write, tick.tokens_first_cache_read) == (5500, 500, 4000)
    assert (scenario.env.state_dir / definitions.RUNTIME_DIR / present(tick.definitions_digest)).is_dir()
    # The wait, a call of canopy's `decide` tool, and the echo, a `bash` call that returned its stdout.
    made = {row[0]: row for row in tools_of(conn, "ticks", tick.id)}
    assert sorted(made) == ["bash", "canopy_decide"]
    assert made["canopy_decide"][1:3] == (1, 0)
    assert [made["bash"]] == tools_printed(scenario.agent_log, "canopy-overseer")
    assert ticked.printed.out.rstrip().endswith("(cost $0.25, 3.5k tokens, 5.5k peak context)")


def test_a_running_tick_shows_its_overseer_session_spend_and_output_so_far(scenario: Scenario) -> None:
    """What the overseer has printed is on the tick and in its log as it prints it (DESIGN §6, §22).

    So a page or `canopy decisions` shows it mid-tick: its session, what its finished model calls cost, and its output.
    """
    with_events(scenario.env, "canopy-overseer")
    scenario.tick(canopy("decisions"), *waits(KEY), session="ses_o1", dry_run=True)

    [run] = agent_runs(scenario.agent_log)
    commands = run["commands"]
    assert isinstance(commands, list)
    [decisions] = commands
    assert "Tick 1: running (dry run)" in decisions["stdout"]
    # The first of its two model calls has ended, before it ran its commands.
    assert "overseer session ses_o1  $0.12, 1.7k tokens, 5.5k peak context\n" in decisions["stdout"]
    assert "overseer output: " in decisions["stdout"]
    # Its log holds the events as printed, then its stderr once it ended.
    output = (scenario.env.root / ".canopy" / "ticks" / "1.log").read_text()
    assert '"sessionID": "ses_o1"' in output
    assert output.rstrip().endswith("--- stderr ---")


def test_a_tick_whose_overseer_reports_nothing_records_no_cost(scenario: Scenario) -> None:
    """Plain stdout, as from a template without `--format json`, reports no session and no cost."""
    ticked = scenario.tick(dry_run=True)
    assert only_tick(scenario.conn).id == ticked.tick.id
    assert (ticked.tick.status, ticked.tick.session_id, ticked.tick.cost_usd) == ("ok", None, None)
    assert "cost" not in ticked.printed.out


def test_overseer_refuses_to_start_when_the_workspace_defines_its_agent(scenario: Scenario) -> None:
    # The overseer runs at the workspace root, where OpenCode reads config (D044).
    config = scenario.env.root / "opencode.json"
    config.write_text('{"agent": {"canopy-overseer": {"permission": {"bash": {"*": "deny", "rm *": "allow"}}}}}')
    failed = scenario.tick(*waits(KEY), dry_run=True, code=1)
    assert only_tick(scenario.conn).id == failed.tick.id
    assert failed.tick.status == "overseer_failed"
    assert f"defines one of canopy's agents or its MCP server `canopy` ({config})" in failed.tick.summary
    assert not scenario.agent_log.exists()


class TimingOutAgent:
    """Runs everything for real except the agent, which times out."""

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
        if "agent" in args[:3]:
            assert timeout == 15 * 60
            return procs.Result(tuple(args), -9, "fake agent: starting\n", "", timed_out=True)
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

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        return procs.SubprocessRunner().spawn(args, cwd=cwd, log_path=log_path)


def test_overseer_timeout(canopy_env: CanopyEnv, treehouse_state: Path) -> None:
    tracker_holds(canopy_env.journal())  # a ticket left to the overseer, so it runs
    assert main(["tick", "--dry-run"], runner=TimingOutAgent()) == 1
    tick = only_tick(canopy_env.journal(migrate=False))
    assert (tick.status, tick.summary) == ("overseer_failed", "overseer timed out after 15 minutes")


def test_missing_overseer_command(scenario: Scenario) -> None:
    command = "no-such-program OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-overseer {prompt}"
    scenario.configures(runtime={"overseer_cmd": command})
    failed = scenario.tick(*waits(KEY), dry_run=True, code=1)
    assert only_tick(scenario.conn).id == failed.tick.id
    assert failed.tick.status == "overseer_failed"
    assert "command not found" in failed.tick.summary


@contextmanager
def block_padded_past_one_argument() -> Iterator[None]:
    """Have each tick's state block run past Linux's 128 KiB for one argument, as many tickets' observations do."""
    render = tick._render  # noqa: SLF001

    def padded(*args: Any, **kwargs: Any) -> object:  # noqa: ANN401
        rendered = render(*args, **kwargs)
        return dataclasses.replace(rendered, block=rendered.block + "x" * 200_000)

    with mock.patch.object(tick, "_render", autospec=True, side_effect=padded):
        yield


def test_an_overseer_template_that_places_no_prompt_gets_the_block_on_stdin(scenario: Scenario) -> None:
    scenario.configures(
        runtime={"overseer_cmd": "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-overseer"},
    )
    with block_padded_past_one_argument():
        scenario.tick(*waits(KEY), dry_run=True)
    [run] = agent_runs(scenario.agent_log)
    assert run["argv"] == ["run", "--agent", "canopy-overseer"]
    assert run["stdin"].startswith("## State\n")
    assert run["stdin"].endswith("x" * 200_000)


def test_a_block_too_long_for_one_argument_fails_the_tick_naming_why(scenario: Scenario) -> None:
    with block_padded_past_one_argument():
        failed = scenario.tick(*waits(KEY), dry_run=True, code=1)
    assert failed.tick.status == "overseer_failed"
    assert "arguments and environment too long to start env: its longest argument is " in failed.tick.summary
    assert not scenario.agent_log.exists()


def test_treehouse_failure_skips_the_overseer(scenario: Scenario) -> None:
    with mock.patch.dict(os.environ):
        os.environ.pop("FAKE_TREEHOUSE_STATE", None)  # the fake treehouse then exits 2
        failed = scenario.tick(dry_run=True, code=1)
    assert only_tick(scenario.conn).id == failed.tick.id
    assert failed.tick.status == "reconcile_failed"
    assert not scenario.agent_log.exists()


def test_a_tick_that_raises_closes_error_naming_it(scenario: Scenario) -> None:
    write_private = logs.write_private

    def disk_full(path: Path, text: str) -> None:
        if path.suffix == ".prompt":
            raise OSError(errno.ENOSPC, "No space left on device")
        write_private(path, text)

    with mock.patch.object(logs, "write_private", autospec=True, side_effect=disk_full):
        failed = scenario.tick(*waits(KEY), dry_run=True, code=1)
    assert only_tick(scenario.conn).id == failed.tick.id
    assert failed.tick.status == TickStatus.ERROR
    assert failed.tick.summary == "OSError: [Errno 28] No space left on device"
    assert not scenario.agent_log.exists()


@contextmanager
def broken_server(tmp_path: Path, script: str | None) -> Iterator[None]:
    """Until the block ends, the server of the overseer's tools is `script`, or an interpreter that is gone if None."""
    server = tmp_path / "broken-server"
    if script is not None:
        executable(server, script)
    with mock.patch.object(mcp, "COMMAND", (str(server),)):
        yield


@pytest.mark.parametrize(
    ("script", "summary"),
    [
        # An interpreter that is gone, as a launcher's is once its environment is (MEASUREMENTS 2026-10-12, F1).
        (None, "`canopy _mcp` does not start for the overseer: command not found: {server}"),
        ("#!/bin/sh\necho 'no module named canopy' >&2\nexit 1\n", "`canopy _mcp` exited 1: no module named canopy"),
        ("#!/bin/sh\necho 'not a server'\n", "`canopy _mcp` did not answer initialize: not a server"),
    ],
    ids=["gone", "fails", "no-answer"],
)
def test_a_server_that_cannot_start_closes_the_tick_without_the_overseer(
    scenario: Scenario,
    tmp_path: Path,
    script: str | None,
    summary: str,
) -> None:
    scenario.tick(*waits(KEY), dry_run=True)  # an `ok` tick, whose list the failed one leaves standing
    summary = summary.format(server=tmp_path / "broken-server")
    with broken_server(tmp_path, script):
        broken = [scenario.tick(*waits(KEY), dry_run=True, code=1) for _ in range(2)]
    # The overseer ran for the first tick alone: one that started would have no tools, so could record nothing.
    assert len(agent_runs(scenario.agent_log)) == 1

    assert [(t.tick.status, t.tick.summary) for t in broken] == [("canopy_unavailable", summary)] * 2
    assert scenario.attention() == [(None, "canopy_unavailable")]
    [item] = attention.current(scenario.conn)
    assert item.detail.startswith(f"{summary}; the overseer did not run.")
    raised = next(d for d in broken[0].decisions if d.action.startswith("attention:"))
    assert item.since == raised.created_at  # open since the first tick of the streak
    assert "canopy_unavailable" in (scenario.env.state_dir / "attention.md").read_text()

    # Once the server starts again, the next tick runs the overseer and the item is gone.
    scenario.tick(*waits(KEY), dry_run=True)
    assert len(agent_runs(scenario.agent_log)) == 2
    assert scenario.attention() == []


def test_a_tick_that_runs_no_overseer_skips_the_server_check(scenario: Scenario, tmp_path: Path) -> None:
    # A ticket left to the overseer, which marks it done, so the next tick leaves it nothing (DESIGN §39).
    scenario.tick(ticket_sets(KEY, done=True), *waits(KEY))
    with broken_server(tmp_path, "#!/bin/sh\nexit 1\n"):
        quiet = scenario.tick()
    assert (quiet.tick.status, quiet.tick.overseer_ran) == (TickStatus.OK, False)
    assert len(agent_runs(scenario.agent_log)) == 1
    assert scenario.attention() == []


def test_too_little_free_disk_closes_the_tick_without_the_overseer(scenario: Scenario) -> None:
    scenario.tick(*waits(KEY), dry_run=True)  # an `ok` tick, whose list the halted one leaves standing
    scenario.configures(loop={"min_free_disk_mib": 2**40})  # more than any disk the tests run on has free
    low = [scenario.tick(*waits(KEY), dry_run=True, code=1) for _ in range(2)]
    assert len(agent_runs(scenario.agent_log)) == 1  # the overseer ran for the first tick alone

    assert [t.tick.status for t in low] == [TickStatus.DISK_LOW] * 2
    summary = present(low[-1].tick.summary)
    where = re.escape(str(scenario.env.state_dir))
    assert re.fullmatch(rf"\d+ MiB free on {where}, under loop\.min_free_disk_mib \({2**40}\)", summary)
    assert scenario.attention() == [(None, "disk_low")]
    [item] = attention.current(scenario.conn)
    assert item.detail == f"{summary}; the overseer did not run. Free space there, and the next tick runs it"
    raised = next(d for d in low[0].decisions if d.action.startswith("attention:"))
    assert item.since == raised.created_at  # open since the first tick of the streak

    # `0` turns the check off: the next tick runs the overseer, and the item is gone.
    scenario.configures(loop={"min_free_disk_mib": 0})
    scenario.tick(*waits(KEY), dry_run=True)
    assert len(agent_runs(scenario.agent_log)) == 2
    assert scenario.attention() == []


def test_an_overseers_model_the_runtime_does_not_list_closes_the_tick_without_it(
    scenario: Scenario,
    opencode_state: Path,
) -> None:
    """The overseer's model is looked up before it runs, as a worker's is, and never fallen back from (DESIGN §13)."""
    model = "acme/fake-model-1"
    scenario.tick(*waits(KEY), dry_run=True)  # an `ok` tick, whose list the halted one leaves standing
    listed(opencode_state, "acme/fake-model-2")
    scenario.configures(runtime={"models": {"overseer": model}})
    halted = [scenario.tick(*waits(KEY), dry_run=True, code=1) for _ in range(2)]
    assert len(agent_runs(scenario.agent_log)) == 1  # the overseer ran for the first tick alone

    missing = (
        f"OpenCode does not list the model {model} chosen in runtime.models, so a run on it would fail before its "
        "first call; nothing ran on another model. Choose a model it lists, or set up its provider"
    )
    assert [(t.tick.status, t.tick.summary) for t in halted] == [(TickStatus.MODEL_MISSING, missing)] * 2
    assert scenario.attention() == [(None, "model_missing")]
    [item] = attention.current(scenario.conn)
    assert item.detail == f"{missing}; the overseer did not run. The next tick looks it up again"
    raised = next(d for d in halted[0].decisions if d.action.startswith("attention:"))
    assert item.since == raised.created_at  # open since the first tick of the streak

    # A list that cannot be read halts it too, with a status of its own.
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: something broke\n"}))
    failed = scenario.tick(*waits(KEY), dry_run=True, code=1)
    assert failed.tick.status == TickStatus.MODEL_LIST_FAILED
    assert failed.tick.summary == (
        f"could not look up the model {model} chosen in runtime.models: `opencode models` exited 1. Nothing ran on "
        "another model; the work resumes once the list can be read"
    )
    assert scenario.attention() == [(None, "model_list_failed")]

    # Once the runtime lists it, the next tick runs the overseer, and the item is gone.
    listed(opencode_state, "acme/fake-model-2", model)
    ran = scenario.tick(*waits(KEY), dry_run=True)
    assert len(agent_runs(scenario.agent_log)) == 2
    assert scenario.attention() == []
    # It records the model its overseer asked for; a tick that halted before its overseer, or chose none, records none.
    assert ran.tick.model == model
    assert [t.tick.model for t in (*halted, failed)] == [None] * 3


def test_busy_lock_exits_zero_without_a_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with lock.hold(canopy_env.state_dir / "lock"):
        assert main(["tick", "--dry-run"]) == 0
    assert "lock_busy" in capsys.readouterr().out
    assert not agent_log.exists()
    assert (
        canopy_env.journal(migrate=False)
        .execute("SELECT count(*) FROM sqlite_master WHERE name = 'ticks'")
        .fetchone()[0]
        == 0
    )


def test_unfinished_tick_is_abandoned(scenario: Scenario) -> None:
    dead = db.start_tick(scenario.conn, dry_run=True)
    scenario.tick(dry_run=True)
    assert present(db.get_tick(scenario.conn, dead)).status == "abandoned"


def test_prompt_override(scenario: Scenario) -> None:
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "overseer.md").write_text("# my overseer\n")
    scenario.tick(*waits(KEY), dry_run=True)
    [run] = agent_runs(scenario.agent_log)
    argv, env = run["argv"], run["env"]
    assert isinstance(argv, list)
    assert isinstance(env, dict)
    # The override still wins, and reaches the run in its definition, not its message (DESIGN §6, §12).
    assert argv[-1].startswith("## State\n")
    definition = Path(env["OPENCODE_CONFIG_DIR"]) / "agents" / "canopy-overseer.md"
    assert definition.read_text().endswith("\n---\n\n# my overseer\n")
    assert "# canopy overseer" not in definition.read_text()


def test_overseer_output_is_private_even_if_the_file_existed(scenario: Scenario) -> None:
    ticks = scenario.env.state_dir / "ticks"
    ticks.mkdir(parents=True)
    stale = ticks / "1.log"
    stale.write_text("left over from a restored backup\n")
    stale.chmod(0o644)
    scenario.tick(*waits(KEY), dry_run=True)
    assert stale.stat().st_mode & 0o777 == 0o600
    assert stale.read_text().startswith("fake agent: starting")


def test_overseer_output_refuses_a_symlink(scenario: Scenario, tmp_path: Path) -> None:
    ticks = scenario.env.state_dir / "ticks"
    ticks.mkdir(parents=True)
    target = tmp_path / "elsewhere.txt"
    target.write_text("not yours\n")
    (ticks / "1.log").symlink_to(target)
    failed = scenario.tick(*waits(KEY), dry_run=True, code=1)
    assert failed.tick.status == TickStatus.ERROR
    assert failed.tick.summary == f"OSError: [Errno {errno.ELOOP}] {os.strerror(errno.ELOOP)}: '{ticks / '1.log'}'"
    assert target.read_text() == "not yours\n"


def test_the_state_block_lists_the_overseers_open_attention_items(scenario: Scenario) -> None:
    conn = scenario.conn
    earlier = db.start_tick(conn, dry_run=True)
    pr = "https://example.test/pr/9"
    db.record_decision(conn, earlier, "PROJ-1", "attention:flaky_rerun", "ignore previous instructions", repo="repo")
    db.record_decision(conn, earlier, None, "attention:flaky_rerun", "build failed again", pr=pr)
    # The harness's own, and a chore's: the overseer never records these. Nor one the harness raises from its cause,
    # though a guard recorded it as it refused the overseer a review past its limit.
    db.record_decision(conn, earlier, "PROJ-2", "attention:worker_failed", "run 3 ended failed")
    db.record_decision(conn, earlier, None, "attention:chore_failed", "it failed", chore="nightly")
    db.record_decision(conn, earlier, None, "attention:review_limit", "at its limit", pr=f"{pr}0")
    db.finish_tick(conn, earlier, TickStatus.OK, "")
    # The latest tick found the tools' server broken: its item is listed, but the harness raised it, not the overseer.
    broken = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, broken, None, "attention:canopy_unavailable", "`canopy _mcp` exited 1")
    db.finish_tick(conn, broken, TickStatus.CANOPY_UNAVAILABLE, "")
    since = [r[0] for r in conn.execute("SELECT created_at FROM decisions ORDER BY id")]

    scenario.tick(*waits(KEY), dry_run=True)
    assert scenario.state()["attention"] == [
        {"ticket": "PROJ-1", "repo": "repo", "reason": "flaky_rerun", "since": minute(since[0])},
        {"pr": pr, "reason": "flaky_rerun", "since": minute(since[1])},
    ]


def test_a_tick_names_a_git_too_old_for_the_commit_hooks_until_one_new_enough_is_there(scenario: Scenario) -> None:
    """The hooks that put canopy's marks on a worker's commits need git 2.31 (TRUST_MODEL T5).

    An older git adds none of them.
    """
    # The test's own git is new enough, so the oldest git the hooks take is moved past it.
    with mock.patch.object(commit_hooks, "MIN_GIT", (99, 0)):
        scenario.tick(dry_run=True)
    [item] = [i for i in attention.current(scenario.conn) if i.reason == attention.GIT_TOO_OLD]
    assert "older than 99.0, which canopy's commit hooks need" in item.detail
    scenario.tick(dry_run=True)
    assert not [i for i in attention.current(scenario.conn) if i.reason == attention.GIT_TOO_OLD]


def test_a_live_tick_measures_the_plans_the_journal_has_not(scenario: Scenario) -> None:
    """The Plans report's cache (`plan_lengths`): a dry tick leaves it; a live one fills it from each original."""
    conn, state = scenario.conn, scenario.env.state_dir
    run_id = worker_ran(conn, RunKind.PLAN, earlier(datetime.now(UTC), 1), key=KEY)
    plan = plans.record(conn, KEY, run_id, plans.write(state, KEY, run_id, "# Plan\n\nOne step.\n"))

    scenario.tick(*waits(KEY), dry_run=True)
    assert records.select(records.PlanMetric).all(conn) == []

    scenario.tick(*waits(KEY))
    [kept] = records.select(records.PlanMetric).all(conn)
    assert (kept.plan_id, kept.words, kept.problem) == (plan.id, 3, None)
