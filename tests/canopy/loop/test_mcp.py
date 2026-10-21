"""The overseer's verbs as MCP tools (DESIGN §27): `canopy _mcp`, driven over stdio in a tick, beside its commands."""

import contextlib
import io
import json
import os
import sqlite3
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest

from canopy.chores import history
from canopy.cli import mcp as mcp_cli
from canopy.cli.main import main
from canopy.core import chore_runs, db, git_tools
from canopy.core.context import Context
from canopy.core.vocab import ChoreRunStatus, TickStatus
from canopy.infra import procs
from canopy.loop import mcp
from canopy.runs import policy
from tests.canopy.helpers import (
    LABEL,
    LIST_TOOLS,
    MCP_OPENING,
    InlineRunner,
    ancestors,
    chore_reports,
    chore_toml,
    in_run,
    in_tick,
    mcp_session,
    operator,
    present,
    tool_call,
    worker_does,
)
from tests.canopy.review_helpers import feature_commit
from tests.conftest import CanopyEnv, GitPool, executable, git

#: One of the loop's own PRs, PROJ-1's in `repo`, which reviews are on for.
PR = "https://github.com/acme/api/pull/7"
#: A PR the operator asked canopy to review.
REQUESTED = "https://github.com/acme/api/pull/8"
#: Every tool, by name, as the overseer's definition will allow each one.
TOOL_NAMES = [
    "dispatch",
    "decide",
    "queried",
    "attention",
    "ticket-set",
    "mirror",
    "review-run",
    "review-wait",
    "review-end",
    "chore-run",
    "chore-wait",
]
#: What a chore reports, for a run a tool starts.
CHORE_OK: Mapping[str, object] = {"status": "ok", "summary": "nothing found", "findings": []}


@pytest.fixture
def overseen(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> CanopyEnv:
    """A workspace whose every verb has something to act on: one chore, build-health, and reviews of the loop's PRs."""
    prompt = canopy_env.home / "chores" / "build-health.md"
    prompt.parent.mkdir()
    prompt.write_text("# Build health\n\nLook at the build queue.\n")
    reviewer = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\nreview_cmd = '{reviewer}'\n", 1)
    canopy_env.write_user(user + chore_toml() + "\n[review]\nagent_prs = true\n")
    return canopy_env


@dataclass(frozen=True)
class Verb:
    """One call of a verb, as a tool call and as the command the overseer runs today."""

    tool: str
    arguments: Mapping[str, object]
    command: Sequence[str]
    dry_run: bool = False
    #: Whether the call is made inside a running tick.
    ticking: bool = True


@dataclass(frozen=True)
class Done:
    """What a verb did through one door: what it said, whether it failed, and what the journal then held."""

    said: str
    failed: bool
    journal: Mapping[str, Sequence[Mapping[str, object]]]
    #: The command's exit code; None for the tool.
    code: int | None = None
    #: What the command wrote to stderr.
    stderr: str = ""


#: The tables a verb writes, which a tool and its command must leave alike.
RECORDED = ("decisions", "tickets", "ticket_units", "messages", "review_requests", "chore_runs", "runs", "review_runs")


def by_tool(env: CanopyEnv, verb: Verb) -> Done:
    """Do `verb` through `canopy _mcp`, in a fresh journal."""
    with fresh(env, verb) as conn:
        served = mcp_session(tool_call(verb.tool, **verb.arguments))
        assert (served.stderr, served.returncode) == ("", 0)
        said = served.said()
        return Done(said.text, said.error, recorded(conn))


def by_command(env: CanopyEnv, verb: Verb, capsys: pytest.CaptureFixture[str]) -> Done:
    """Do `verb` through its command, in this process, in a fresh journal."""
    with fresh(env, verb) as conn:
        capsys.readouterr()
        code = main(list(verb.command))
        out, err = capsys.readouterr()
        return Done(out.removesuffix("\n"), code != 0, recorded(conn), code=code, stderr=err)


@contextlib.contextmanager
def fresh(env: CanopyEnv, verb: Verb) -> Iterator[sqlite3.Connection]:
    """A new journal, holding what every verb acts on, and the tick `verb` runs in, if it runs in one."""
    for leftover in env.state_dir.glob(f"{db.DB_FILE_NAME}*"):
        leftover.unlink()
    conn = env.journal()
    db.set_unit(conn, "PROJ-1", str(env.root), "repo", pr_url=PR)
    assert operator("start", REQUESTED, "--review") == 0
    with in_tick(conn, dry_run=verb.dry_run) if verb.ticking else contextlib.nullcontext():
        yield conn
    conn.close()


def recorded(conn: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    """What the journal holds in the tables verbs write, but for when each row was written."""
    return {
        table: [
            {k: v for k, v in dict(row).items() if k != "at" and not k.endswith("_at")}
            for row in conn.execute(f"SELECT * FROM {table}")  # noqa: S608  (each a table named above)
        ]
        for table in RECORDED
    }


RECORDS = [
    pytest.param(
        Verb(
            "dispatch",
            {
                "key": "PROJ-1",
                "kind": "implement",
                "label": LABEL,
                "repos": ["repo"],
                "slug": "add-login",
                "context": "see comment 7",
                "cursors": {"comment": "7"},
            },
            [
                *("dispatch", "PROJ-1", "--kind", "implement", "--label", LABEL, "--repo", "repo", "--slug"),
                *("add-login", "--context", "see comment 7", "--cursor", "comment=7"),
            ],
            dry_run=True,
        ),
        id="dispatch",
    ),
    pytest.param(
        Verb(
            "decide",
            {"key": "PROJ-1", "action": "wait", "rationale": "  checks still running  "},
            ["decide", "PROJ-1", "wait", "--rationale", "  checks still running  "],
        ),
        id="decide",
    ),
    pytest.param(
        Verb(
            "decide",
            {"action": "skip", "rationale": "mcp_unavailable: the tracker"},
            ["decide", "skip", "--rationale", "mcp_unavailable: the tracker"],
        ),
        id="decide-tick-wide",
    ),
    pytest.param(
        Verb("queried", {"keys": ["PROJ-2", "PROJ-3", "PROJ-2"]}, ["queried", "PROJ-2", "PROJ-3", "PROJ-2"]),
        id="queried",
    ),
    pytest.param(
        Verb(
            "attention",
            {"key": "PROJ-1", "reason": "needs_reviewer", "detail": "no one owns it", "repo": "repo"},
            ["attention", "PROJ-1", "needs_reviewer", "--detail", "no one owns it", "--repo", "repo"],
        ),
        id="attention",
    ),
    pytest.param(
        Verb(
            "attention",
            {"reason": "review_limit", "detail": "reviewed often", "pr": PR},
            ["attention", "review_limit", "--detail", "reviewed often", "--pr", PR],
        ),
        id="attention-pr",
    ),
    pytest.param(
        Verb(
            "ticket-set",
            # A tracker's ids sent as numbers are taken as strings, and a null as the field left out.
            {
                "key": "PROJ-1",
                "repo": "repo",
                "phase": "ci_red",
                "cursors": {"comment": 7, "ci": 99},
                "done": None,
                "title": "Fix the\nlogin",
            },
            [
                *("ticket", "set", "PROJ-1", "--repo", "repo", "--phase", "ci_red", "--cursor", "comment=7"),
                *("--cursor", "ci=99", "--title", "Fix the\nlogin"),
            ],
        ),
        id="ticket-set",
    ),
    pytest.param(
        Verb("ticket-set", {"key": "PROJ-1", "done": True}, ["ticket", "set", "PROJ-1", "--done"], dry_run=True),
        id="ticket-set-dry",
    ),
    pytest.param(
        Verb(
            "mirror",
            {"ref": "PROJ-1", "comment": 10, "author": "acct-1", "at": "2026-10-15T10:00:00Z", "body": "Looks good."},
            [
                *("mirror", "PROJ-1", "--comment", "10", "--author", "acct-1", "--at", "2026-10-15T10:00:00Z"),
                *("--body", "Looks good."),
            ],
        ),
        id="mirror",
    ),
    pytest.param(
        Verb(
            "review-run",
            {"pr": PR, "sha": "a" * 40, "ticket": "PROJ-1", "repo": "repo", "context": "the retry loop"},
            [
                *("review", "run", "--pr", PR, "--sha", "a" * 40, "--ticket", "PROJ-1", "--repo", "repo"),
                *("--context", "the retry loop"),
            ],
            dry_run=True,
        ),
        id="review-run",
    ),
    pytest.param(
        Verb(
            "review-wait",
            {"pr": PR, "ticket": "PROJ-1", "rationale": "checks still running"},
            ["review", "wait", "--pr", PR, "--ticket", "PROJ-1", "--rationale", "checks still running"],
        ),
        id="review-wait",
    ),
    pytest.param(
        Verb(
            "review-end",
            {"pr": REQUESTED, "reason": "closed"},
            ["review", "end", "--pr", REQUESTED, "--reason", "closed"],
        ),
        id="review-end",
    ),
    pytest.param(
        Verb(
            "chore-run",
            {"name": "build-health", "context": "job 90"},
            ["chore", "run", "build-health", "--context", "job 90"],
            dry_run=True,
        ),
        id="chore-run",
    ),
    pytest.param(
        Verb(
            "chore-wait",
            {"name": "build-health", "rationale": "the queue is down"},
            ["chore", "wait", "build-health", "--rationale", "the queue is down"],
        ),
        id="chore-wait",
    ),
]


@pytest.mark.parametrize("verb", RECORDS)
def test_each_tool_records_what_its_command_records(
    overseen: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    verb: Verb,
) -> None:
    command = by_command(overseen, verb, capsys)
    assert (command.code, command.stderr) == (0, "")
    tool = by_tool(overseen, verb)
    assert not tool.failed
    assert tool.said == command.said
    assert tool.journal == command.journal
    assert any(command.journal[table] for table in ("decisions", "tickets"))


REFUSALS = [
    pytest.param(
        Verb(
            "decide",
            {"key": "PROJ-1", "action": "wait", "rationale": "r"},
            ["decide", "PROJ-1", "wait", "--rationale", "r"],
            ticking=False,
        ),
        "no tick is running (CANOPY_TICK_ID is not set); the overseer's verbs run only inside one",
        1,
        id="no-tick",
    ),
    pytest.param(
        Verb("decide", {"action": "wait", "rationale": "r"}, ["decide", "wait", "--rationale", "r"]),
        "'wait' needs a ticket key; only a tick-wide 'skip' may omit it",
        2,
        id="decide-without-a-key",
    ),
    pytest.param(
        Verb("decide", {"action": "skip", "rationale": "relabel"}, ["decide", "skip", "--rationale", "relabel"]),
        "a skip about one ticket names its key",
        2,
        id="decide-a-tick-wide-skip-without-its-reason",
    ),
    pytest.param(
        Verb(
            "decide",
            {"key": "PROJ-1", "action": "skip", "rationale": "mcp_unavailable: down"},
            ["decide", "PROJ-1", "skip", "--rationale", "mcp_unavailable: down"],
        ),
        "'mcp_unavailable' skips the whole tick, so it names no key: leave key out",
        2,
        id="decide-a-tick-wide-reason-under-a-key",
    ),
    pytest.param(
        Verb(
            "decide",
            {"key": "PROJ-1", "action": "wait", "rationale": "   "},
            ["decide", "PROJ-1", "wait", "--rationale", "   "],
        ),
        "must not be empty",
        2,
        id="decide-with-no-rationale",
    ),
    pytest.param(
        Verb(
            "queried",
            {"keys": [f"PROJ-{n}" for n in range(1000, 1300)]},
            ["queried", *(f"PROJ-{n}" for n in range(1000, 1300))],
        ),
        "300 keys do not fit in one call: name them in several",
        2,
        id="queried-too-many",
    ),
    pytest.param(
        Verb("queried", {"keys": ["PROJ 1"]}, ["queried", "PROJ 1"]),
        "invalid ticket key 'PROJ 1': must match",
        2,
        id="queried-a-bad-key",
    ),
    pytest.param(
        Verb(
            "attention",
            {"reason": "needs_reviewer", "detail": "d"},
            ["attention", "needs_reviewer", "--detail", "d"],
        ),
        "key or pr is required (KEY, or --pr)",
        2,
        id="attention-about-nothing",
    ),
    pytest.param(
        Verb(
            "attention",
            {"key": "PROJ-1", "reason": "needs_reviewer", "detail": "d", "repo": "nope"},
            ["attention", "PROJ-1", "needs_reviewer", "--detail", "d", "--repo", "nope"],
        ),
        "'nope' is not a repository in this workspace (repo)",
        1,
        id="attention-in-no-repository",
    ),
    pytest.param(
        Verb(
            "ticket-set",
            {"key": "PROJ-1", "cursors": {"review": "2026-10-07T20:58:50Z"}},
            ["ticket", "set", "PROJ-1", "--cursor", "review=2026-10-07T20:58:50Z"],
        ),
        "repo is required (--repo): a review cursor belongs to one unit",
        2,
        id="ticket-set-a-units-cursor",
    ),
    pytest.param(
        Verb(
            "dispatch",
            {"key": "PROJ-1", "kind": "implement", "repos": ["api", "web"], "cursors": {"ci": "99"}},
            ["dispatch", "PROJ-1", "--kind", "implement", "--repo", "api", "--repo", "web", "--cursor", "ci=99"],
        ),
        "cursors: a ci cursor belongs to one unit",
        2,
        id="dispatch-a-units-cursor-in-several",
    ),
    pytest.param(
        Verb(
            "ticket-set",
            {"key": "PROJ-1", "repo": "repo", "cursors": {"review": "yesterday"}},
            ["ticket", "set", "PROJ-1", "--repo", "repo", "--cursor", "review=yesterday"],
        ),
        "a review cursor is the newest handled item's time in UTC, as YYYY-MM-DDTHH:MM:SSZ; got 'yesterday'",
        2,
        id="ticket-set-a-bad-cursor",
    ),
    pytest.param(
        Verb(
            "dispatch",
            {"key": "PROJ-1", "kind": "fix-ci", "label": LABEL, "repos": ["repo"]},
            ["dispatch", "PROJ-1", "--kind", "fix-ci", "--label", LABEL, "--repo", "repo"],
        ),
        "dispatch refused (bad_kind): fix-ci is retired",
        1,
        id="dispatch",
    ),
    pytest.param(
        Verb(
            "dispatch",
            {"key": "PROJ-1", "kind": "implement", "repos": ["repo"]},
            ["dispatch", "PROJ-1", "--kind", "implement", "--repo", "repo"],
            dry_run=True,
        ),
        "dispatch refused (unauthorized)",
        1,
        id="dispatch-without-a-label",
    ),
    pytest.param(
        # A null is the field left out: the guard refuses it, and records it, as it does the command without --repo.
        Verb(
            "dispatch",
            {"key": "PROJ-1", "kind": "implement", "label": LABEL, "repos": None, "reasons": None, "cursors": None},
            ["dispatch", "PROJ-1", "--kind", "implement", "--label", LABEL],
            dry_run=True,
        ),
        "dispatch refused (unknown_repo): --repo is required",
        1,
        id="dispatch-in-no-repository",
    ),
    pytest.param(
        Verb(
            "mirror",
            {"ref": "PROJ-1", "comment": "a b", "author": "acct-1", "at": "2026-10-15T10:00:00Z", "body": "Hi."},
            [
                "mirror",
                "PROJ-1",
                "--comment",
                "a b",
                "--author",
                "acct-1",
                "--at",
                "2026-10-15T10:00:00Z",
                "--body",
                "Hi.",
            ],
        ),
        "mirror refused (bad_comment): 'a b' is not a comment id",
        1,
        id="mirror",
    ),
    pytest.param(
        Verb(
            "review-run",
            {"pr": PR, "sha": "abc", "ticket": "PROJ-1", "repo": "repo"},
            ["review", "run", "--pr", PR, "--sha", "abc", "--ticket", "PROJ-1", "--repo", "repo"],
            dry_run=True,
        ),
        "review refused (bad_pr): --sha must be the full head commit",
        1,
        id="review-run",
    ),
    pytest.param(
        Verb(
            "review-wait",
            {"pr": "http://example.test/pr/1", "rationale": "r"},
            ["review", "wait", "--pr", "http://example.test/pr/1", "--rationale", "r"],
        ),
        "must be a plain https:// URL of at most 300 characters",
        2,
        id="review-wait-a-bad-url",
    ),
    pytest.param(
        Verb("review-end", {"pr": PR, "reason": "merged"}, ["review", "end", "--pr", PR, "--reason", "merged"]),
        f"review end refused (not_requested): {PR} has no open request; the refusal was recorded",
        1,
        id="review-end",
    ),
    pytest.param(
        Verb("chore-run", {"name": "nope"}, ["chore", "run", "nope"]),
        "chore run refused (unknown_chore): no chore named 'nope' is configured for this workspace",
        1,
        id="chore-run",
    ),
    pytest.param(
        Verb("chore-wait", {"name": "nope", "rationale": "r"}, ["chore", "wait", "nope", "--rationale", "r"]),
        "no chore named 'nope' is configured for this workspace",
        1,
        id="chore-wait",
    ),
]


@pytest.mark.parametrize(("verb", "refusal", "code"), REFUSALS)
def test_a_tool_refuses_what_its_command_refuses_and_records_the_same(
    overseen: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    verb: Verb,
    refusal: str,
    code: int,
) -> None:
    command = by_command(overseen, verb, capsys)
    assert command.code == code
    assert refusal in command.stderr
    tool = by_tool(overseen, verb)
    assert tool.failed
    assert refusal in tool.said
    assert tool.journal == command.journal


def test_a_refusal_is_a_tool_error_and_the_server_goes_on(overseen: CanopyEnv) -> None:
    conn = overseen.journal()
    with in_tick(conn) as tick_id:
        served = mcp_session(
            tool_call("decide", action="wait", rationale="r"),
            tool_call("decide", key="PROJ-1", action="wait", rationale="r", colour="blue"),
            tool_call("decide", key="PROJ-1", action="wait", rationale="checks still running"),
            {"method": "tools/call", "params": {"name": "decide_wait", "arguments": {}}},
            {"method": "resources/list"},
            {"method": "ping"},
        )
    assert served.said(1) == ("'wait' needs a ticket key; only a tick-wide 'skip' may omit it", True)
    # An unknown field is refused, not dropped: named, with nothing recorded for the call.
    assert served.said(2) == ("colour: Extra inputs are not permitted", True)
    assert served.said(3) == ("recorded wait for PROJ-1", False)
    assert served.responses[4]["error"] == {"code": -32602, "message": "no tool named 'decide_wait'"}
    assert served.responses[5]["error"]["code"] == -32601
    assert served.responses[6]["result"] == {}
    assert [(d.ticket_key, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)] == [
        ("PROJ-1", "wait", "checks still running"),
    ]


def test_the_server_lists_each_tool_only_inside_a_running_tick_and_never_inside_a_run(overseen: CanopyEnv) -> None:
    conn = overseen.journal()
    decide = tool_call("decide", key="PROJ-1", action="wait", rationale="r")
    outside = mcp_session(LIST_TOOLS, decide, tool_call("ticket-set", key="PROJ-1", title="Login"))
    assert outside.listed() == []
    assert outside.said(2) == (
        "no tick is running (CANOPY_TICK_ID is not set); the overseer's verbs run only inside one",
        True,
    )
    # The command takes `ticket set` outside a tick; the tool takes nothing there.
    assert outside.said(3).error
    with in_tick(conn):
        inside = mcp_session(LIST_TOOLS)
        with in_run(7):
            in_a_run = mcp_session(LIST_TOOLS, decide)
    assert inside.listed() == TOOL_NAMES
    assert not any("_" in name for name in inside.listed())
    assert in_a_run.listed() == []
    assert in_a_run.said(2) == (
        "CANOPY_RUN_ID is set: canopy's tools are the overseer's, and refuse inside a run",
        True,
    )
    ended = present(db.last_tick(conn))
    db.finish_tick(conn, ended.id, TickStatus.OK, "test")
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": str(ended.id)}):
        stale = mcp_session(LIST_TOOLS, decide)
    assert stale.listed() == []
    assert stale.said(2) == (f"CANOPY_TICK_ID={ended.id} does not name a running tick", True)
    assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0


def test_each_tools_input_is_its_schema_and_takes_no_other_field(overseen: CanopyEnv) -> None:
    conn = overseen.journal()
    with in_tick(conn):
        served = mcp_session(LIST_TOOLS)
    schemas = {t["name"]: t["inputSchema"] for t in served.responses[1]["result"]["tools"]}
    schema = schemas["ticket-set"]
    assert (schema["type"], schema["additionalProperties"], schema["required"]) == ("object", False, ["key"])
    # A field named `title` is a field, though a schema's titles are left out.
    assert "title" in schema["properties"]
    assert "$ref" not in json.dumps(served.responses[1])
    assert "split" not in schema["properties"]["phase"]["anyOf"][0]["enum"]
    # A field that defaults to nothing takes a null for it.
    assert {"type": "null"} in schema["properties"]["done"]["anyOf"]
    assert {"type": "null"} in schema["properties"]["cursors"]["anyOf"]
    # What a guard refuses left out is listed as required, though the request takes it, to be refused and recorded.
    assert schemas["dispatch"]["required"] == ["key", "kind", "repos"]
    assert "default" not in schemas["dispatch"]["properties"]["repos"]
    assert schemas["review-run"]["required"] == ["pr", "sha", "repo"]


def test_a_tool_takes_no_text_for_a_flag_or_a_number_and_names_only_the_kinds_it_dispatches(
    overseen: CanopyEnv,
) -> None:
    conn = overseen.journal()
    with in_tick(conn):
        served = mcp_session(
            tool_call("ticket-set", key="PROJ-1", done="yes"),
            tool_call(
                "dispatch",
                key="PROJ-1",
                kind="resume",
                label=LABEL,
                repos=["repo"],
                reasons=["review"],
                review_run=True,
            ),
            tool_call("dispatch", key="PROJ-1", kind="bogus", label=LABEL, repos=["repo"]),
        )
    assert served.said(1) == ("done: Input should be a valid boolean", True)
    assert served.said(2) == ("review_run: Input should be a valid integer", True)
    assert served.said(3) == (f"kind: choose from {', '.join(policy.DISPATCH_KINDS)}", True)
    assert "fix-ci" not in served.said(3).text
    assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
    assert db.get_ticket(conn, "PROJ-1") is None


def test_a_lone_surrogate_a_client_sends_is_answered_and_the_server_goes_on(overseen: CanopyEnv) -> None:
    # JSON takes an escaped lone surrogate, which has no UTF-8: echoed as it came, it would end the server mid-session.
    served = mcp_session(
        raw=[
            json.dumps({"jsonrpc": "2.0", "id": "\ud800", "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "\ud800"}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        ],
    )
    assert served.responses["\ud800"]["result"] == {}
    assert served.responses[1]["error"]["code"] == -32602
    assert served.responses[2]["result"] == {}
    assert (served.stderr, served.returncode) == ("", 0)


def test_the_server_answers_in_the_version_asked_or_its_newest_writes_no_stderr_and_exits_when_stdin_closes(
    overseen: CanopyEnv,
) -> None:
    unknown = {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}
    served = mcp_session(
        {"method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
        raw=["not json", "[]", '{"jsonrpc": "1.0", "id": 9, "method": "ping"}', json.dumps(unknown)],
    )
    assert served.responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert served.responses[0]["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert served.responses[1]["result"]["protocolVersion"] == "2024-11-05"
    assert served.responses[2]["result"]["protocolVersion"] == mcp.PROTOCOL_VERSIONS[0]
    assert served.responses[9]["error"]["code"] == -32600
    assert served.responses[None]["error"]["code"] in (-32700, -32600)
    assert (served.stderr, served.returncode) == ("", 0)


# A chore's run: `canopy _mcp --chore` serves it its own history alone (DESIGN §19, §27).


def two_chore_runs(env: CanopyEnv) -> sqlite3.Connection:
    """The journal, holding two ended runs of build-health, 1 and 2, the second a finding's."""
    conn = env.journal()
    for summary in ("all green", "one flaky test"):
        run_id = chore_runs.insert_chore_run(conn, tick_id=None, chore="build-health", logs_dir=env.state_dir)
        report: dict[str, object] = {"status": "ok", "summary": summary, "findings": []}
        db.finish_run(conn, "chore_runs", run_id, ChoreRunStatus.OK, json.dumps(report))
    return conn


def test_a_chores_run_is_served_its_history_alone(overseen: CanopyEnv) -> None:
    conn = two_chore_runs(overseen)
    for run in ("chore-2", "chore-try:build-health"):
        with in_run(run):
            served = mcp_session(
                LIST_TOOLS,
                tool_call("decide", key="PROJ-1", action="wait", rationale="r"),
                chore=True,
            )
        assert served.listed() == ["history"], run
        # None of the overseer's verbs is served to a chore, whatever it asks.
        assert served.responses[2]["error"] == {"code": -32602, "message": "no tool named 'decide'"}
    schema = served.responses[1]["result"]["tools"][0]["inputSchema"]
    assert (schema["required"], schema["additionalProperties"]) == (["name"], False)
    assert schema["properties"]["limit"]["maximum"] == history.MAX_LIMIT
    # The overseer's server lists nothing inside a chore's run, its history included.
    with in_tick(conn), in_run("chore-2"):
        assert mcp_session(LIST_TOOLS).listed() == []


@pytest.mark.parametrize("run", [None, "7", "review-1", "chore-99", "chore-x"])
def test_nothing_is_served_where_no_chores_run_is(overseen: CanopyEnv, run: str | None) -> None:
    conn = two_chore_runs(overseen)
    read = tool_call("history", name="build-health")
    with in_tick(conn), in_run(run) if run is not None else contextlib.nullcontext():
        served = mcp_session(LIST_TOOLS, read, chore=True)
    assert served.listed() == []
    assert served.said(2) == (
        "chore history refused (not_chore): the history tool serves a chore's own runs alone, and this is none",
        True,
    )


def test_a_chores_history_tool_says_what_its_command_prints(
    overseen: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    two_chore_runs(overseen)
    reads = [
        {"name": "build-health"},
        {"name": "build-health", "limit": 1},
        {"name": "build-health", "before": 2},
        {"name": "build-health", "run": 2},
    ]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {history.WORKSPACE_ENV: str(overseen.root)}
    # From a `cwd` outside the workspace, as a chore's may be: its run names the workspace.
    with in_run("chore-2"), mock.patch.dict(os.environ, env), contextlib.chdir(elsewhere):
        served = mcp_session(*(tool_call("history", **read) for read in reads), chore=True)
        printed: list[str] = []
        for read in reads:
            flags = [f"--{field}={value}" for field, value in read.items() if field != "name"]
            assert main(["chore", "history", str(read["name"]), *flags]) == 0
            printed.append(capsys.readouterr().out)
    for n, out in enumerate(printed, 1):
        said = served.said(n)
        assert not said.error, said.text
        assert f"{said.text}\n" == out
    assert served.said(1).text.startswith(history.DATA_NOTE)
    assert served.said(2).text.endswith("Older runs: before (--before) 2.")
    assert "summary: one flaky test" in served.said(4).text


def test_a_chores_history_tool_refuses_what_its_command_refuses(
    overseen: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    two_chore_runs(overseen)
    refused = [
        ({"name": "queue-age"}, "chore history refused (other_chore): this is a run of chore build-health"),
        ({"name": "build-health", "run": 9}, "chore history refused (unknown): chore build-health has no run 9"),
        ({"name": "build-health", "run": 1, "before": 2}, "run (--run) prints one run and before (--before) pages"),
        ({"name": "build-health", "limit": history.MAX_LIMIT + 1}, "limit: Input should be less than or equal to 50"),
        ({"name": "Build Health"}, "invalid chore name 'Build Health'"),
        ({"name": "build-health", "colour": "blue"}, "colour: Extra inputs are not permitted"),
    ]
    with in_run("chore-2"):
        served = mcp_session(*(tool_call("history", **arguments) for arguments, _ in refused), chore=True)
    for n, (_, refusal) in enumerate(refused, 1):
        said = served.said(n)
        assert said.error
        assert refusal in said.text, said.text
    # The command refuses the first two, a guard's, as the tool does.
    with in_run("chore-2"):
        assert main(["chore", "history", "queue-age"]) == 1
        assert refused[0][1] in capsys.readouterr().err
        assert main(["chore", "history", "build-health", "--run", "1", "--before", "2"]) == 2
        assert "run (--run) prints one run and before (--before) pages" in capsys.readouterr().err


# A review's or a plan's run: `canopy _mcp --git NAME=PATH` serves it read-only git in those checkouts alone (§27).


def test_a_review_or_a_plan_is_served_read_only_git_in_its_checkout_alone(
    overseen: CanopyEnv,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    sha = feature_commit(git_pool, tmp_path)
    seed = tmp_path / "seed"
    with in_tick(overseen.journal()):
        served = mcp_session(
            LIST_TOOLS,
            tool_call("log", range="main..feature"),
            tool_call("diff", base="main", head=sha),
            tool_call("show", rev="feature", path="retry.py"),
            tool_call("merge-base", base="main", head="feature"),
            tool_call("show", rev="feature", path="../seed/retry.py"),
            tool_call("show", rev="--output=x", path="retry.py"),
            tool_call("show", rev="feature", path="retry.py", repo="web"),
            tool_call("decide", key="PROJ-1", action="wait", rationale="r"),
            tool_call("blame", rev="feature", path="retry.py", start=1, end=2),
            tool_call("log", range="feature", search="call()"),
            git=[f"checkout={seed}"],
        )
    # Its own tools, wherever it runs, a running tick included, and none of the overseer's.
    assert served.listed() == ["merge-base", "diff", "log", "show", "blame"]
    schema = served.responses[1]["result"]["tools"][2]["inputSchema"]
    assert (schema["required"], schema["additionalProperties"]) == (["range"], False)
    assert schema["properties"]["limit"]["maximum"] == git_tools.MAX_LIMIT
    log, diff, show, base = (served.said(n) for n in (2, 3, 4, 5))
    assert [said.error for said in (log, diff, show, base)] == [False] * 4
    assert log.text.startswith(git_tools.DATA_NOTE)
    assert f"commit {sha}\n" in log.text
    assert "+while True:\n+    call()" in diff.text
    assert show.text.endswith("while True:\n    call()")
    assert base.text == git("rev-parse", "main", cwd=seed)
    escape, option, other = (served.said(n) for n in (6, 7, 8))
    assert (escape.error, option.error, other.error) == (True, True, True)
    assert "path: a path stays inside the repository: no `..`" in escape.text
    assert "rev: not a revision" in option.text
    assert other.text == "no repository named 'web' here: this run reads checkout"
    assert served.responses[9]["error"] == {"code": -32602, "message": "no tool named 'decide'"}
    blame, searched = served.said(10), served.said(11)
    assert (blame.error, searched.error) == (False, False)
    assert blame.text.endswith(" 2)     call()")
    assert blame.text.count(f"{sha} ") == 2
    assert searched.text.count("\ncommit ") == 1
    assert f"commit {sha}\n" in searched.text
    assert (served.stderr, served.returncode) == ("", 0)


def test_git_reads_no_variable_the_runtime_passes_down(git_pool: GitPool, tmp_path: Path) -> None:
    """A `GIT_*` variable in the agent's environment, which the server inherits, steers none of its git (#1130)."""
    feature_commit(git_pool, tmp_path)
    marker = tmp_path / "ran"
    external = executable(tmp_path / "external", f'#!/bin/sh\necho ran >> "{marker}"\n')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    git("init", "--quiet", cwd=elsewhere)
    inherited = {
        "GIT_DIR": str(elsewhere / ".git"),
        "GIT_EXTERNAL_DIFF": str(external),
        "GIT_CONFIG_PARAMETERS": f"'diff.external={external}'",
    }
    with mock.patch.dict(os.environ, inherited):
        served = mcp_session(tool_call("diff", base="main", head="feature"), git=[f"checkout={tmp_path / 'seed'}"])
    said = served.said()
    assert not said.error, said.text
    assert "+while True:" in said.text
    assert not marker.exists()


def test_the_git_server_takes_absolute_checkouts_and_serves_nothing_else() -> None:
    assert main(["_mcp", "--chore", "--git", "checkout=/repo"]) == 2
    assert main(["_mcp", "--git", "checkout=repo"]) == 2
    assert main(["_mcp", "--git", "Checkout=/repo"]) == 2
    with (
        mock.patch.object(mcp, "run_stdio", autospec=True, return_value=0) as served,
        mock.patch.dict(os.environ, {"GIT_DIR": "/elsewhere"}),
    ):
        assert main(["_mcp", "--git", "api=/a", "--git", "web=/w"], runner=procs.SubprocessRunner(unset=["S"])) == 0
    [((runner,), kwargs)] = served.call_args_list
    assert kwargs == {"checkouts": {"api": Path("/a"), "web": Path("/w")}}
    # Nothing it starts is a run: none is reparented, and none reads the git variables it inherited.
    assert isinstance(runner, procs.SubprocessRunner)
    assert not runner.reparent
    assert {"S", "GIT_DIR"} <= runner.unset


def test_a_run_a_tool_starts_is_not_the_servers_descendant(overseen: CanopyEnv) -> None:
    # The runtime signals every descendant of the server when the overseer's run ends (DESIGN §27, What OpenCode
    # does). The server here is this process, so a run it started would be this process's descendant.
    if not Path("/proc/self/stat").exists():
        pytest.skip("needs /proc")
    conn = overseen.journal()
    lines = [json.dumps(m).encode() for m in MCP_OPENING]
    call = {"jsonrpc": "2.0", "id": 1, **tool_call("chore-run", name="build-health")}
    out = io.StringIO()
    runner = procs.SubprocessRunner(reparent=True)
    with in_tick(conn, ends_ok=True), chore_reports(CHORE_OK, sleep=60):
        mcp.serve([*lines, json.dumps(call).encode()], out.write, lambda: opened(overseen, runner))
    [*_, said] = [json.loads(line) for line in out.getvalue().splitlines()]
    assert said["result"]["isError"] is False, said
    with stopped(conn) as pid:
        assert os.getpid() not in ancestors(pid)


def test_a_run_a_tool_starts_outlives_the_server(overseen: CanopyEnv) -> None:
    conn = overseen.journal()
    with in_tick(conn, ends_ok=True), chore_reports(CHORE_OK, sleep=60):
        served = mcp_session(tool_call("chore-run", name="build-health"))
    assert served.said() == ("started chore build-health: run 1", False)
    # The server has exited, and the run it started goes on: `stopped` finds it running.
    with stopped(conn):
        pass


@pytest.mark.usefixtures("git_pool")
def test_a_worker_a_tool_dispatches_is_recorded_and_not_the_servers_descendant(overseen: CanopyEnv) -> None:
    if not Path("/proc/self/stat").exists():
        pytest.skip("needs /proc")
    conn = overseen.journal()
    lines = [json.dumps(m).encode() for m in MCP_OPENING]
    arguments = {"key": "PROJ-1", "kind": "implement", "label": LABEL, "repos": ["repo"], "cursors": {"comment": 7}}
    call = {"jsonrpc": "2.0", "id": 1, **tool_call("dispatch", **arguments)}
    out = io.StringIO()
    runner = procs.SubprocessRunner(reparent=True)
    with in_tick(conn, ends_ok=True) as tick_id, worker_does(sleep=60):
        mcp.serve([*lines, json.dumps(call).encode()], out.write, lambda: opened(overseen, runner))
    [*_, said] = [json.loads(line) for line in out.getvalue().splitlines()]
    assert said["result"]["isError"] is False, said
    [text] = [c["text"] for c in said["result"]["content"]]
    assert text.startswith("dispatched implement for PROJ-1: run 1: ")
    assert [(d.ticket_key, d.action) for d in db.decisions_for_tick(conn, tick_id)] == [
        ("PROJ-1", "dispatch:implement"),
    ]
    assert present(db.get_ticket(conn, "PROJ-1")).last_comment_id == "7"
    with worked(conn) as pid:
        assert os.getpid() not in ancestors(pid)


def test_canopy_mcp_spawns_through_an_intermediate() -> None:
    with mock.patch.object(mcp, "run_stdio", autospec=True, return_value=0) as served:
        assert main(["_mcp"]) == 0
        assert main(["_mcp"], runner=procs.SubprocessRunner(unset=["SECRET"])) == 0
        inline = InlineRunner()
        assert main(["_mcp"], runner=inline) == 0
    [(default,), _], [(given,), _], [(fake,), _] = served.call_args_list
    assert isinstance(default, procs.SubprocessRunner)
    assert default.reparent
    # The runner `main` is given is kept: what it removes from a child's environment, it still removes.
    assert isinstance(given, procs.SubprocessRunner)
    assert (given.reparent, given.unset) == (True, {"SECRET"})
    assert fake is inline
    assert mcp_cli.cmd_mcp.hidden


@contextlib.contextmanager
def opened(env: CanopyEnv, runner: procs.Runner) -> Iterator[Context]:
    """The workspace as the server opens it for a call, with `runner`."""
    with mcp.opened(runner, Path.cwd()) as ctx:
        assert ctx.ws.root == env.root
        yield ctx


@contextlib.contextmanager
def stopped(conn: sqlite3.Connection) -> Iterator[int]:
    """Chore run 1 while it runs, its agent started, and then its process and its agent stopped. Yields its pid."""
    deadline = time.monotonic() + 30
    run = present(chore_runs.get_chore_run(conn, 1))
    while run.agent_pid is None and time.monotonic() < deadline:
        time.sleep(0.05)
        run = present(chore_runs.get_chore_run(conn, 1))
    pid, agent = present(run.pid), present(run.agent_pid)
    try:
        assert procs.running(Path(run.log_path), pid)
        yield pid
    finally:
        procs.kill_group(agent)
        procs.kill_group(pid)


@contextlib.contextmanager
def worked(conn: sqlite3.Connection) -> Iterator[int]:
    """Run 1 while it runs, its worker started, and then its `_run` and its worker stopped. Yields its `_run`'s pid."""
    deadline = time.monotonic() + 30
    run = present(db.get_run(conn, 1))
    while run["worker_pid"] is None and time.monotonic() < deadline:
        time.sleep(0.05)
        run = present(db.get_run(conn, 1))
    pid, worker = int(run["pid"]), int(present(run["worker_pid"]))
    try:
        assert procs.running(Path(run["log_path"]), pid)
        yield pid
    finally:
        procs.kill_group(worker)
        procs.kill_group(pid)
