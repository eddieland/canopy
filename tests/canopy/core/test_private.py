"""Private tickets (DESIGN §22, ROADMAP M18): `canopy start`, `stop`, `reply`, and `show`, the private worker, and the
journal's conversation, against the fake treehouse, a fake overseer, and a fake worker."""

import contextlib
import io
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, conversation, db, definitions, outbox
from canopy.core.vocab import RunStatus, StartStatus
from canopy.infra import procs, resources
from canopy.loop import attention, repeat
from canopy.serve import views
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    QUESTION,
    FakeTime,
    InlineRunner,
    agent_runs,
    blocked_result,
    canopy,
    commit_and_push,
    console,
    context,
    dispatch_in_tick,
    in_tick,
    journal_at,
    last_run,
    operator,
    overseer_does,
    pool,
    present,
    private_worker_does,
    state_block,
    versions_after,
    wait_for_run,
    waits,
    worker_does,
)
from tests.conftest import CanopyEnv, GitPool, Journals


def test_a_started_ticket_is_worked_privately_from_question_to_reply(  # noqa: PLR0915  (M18's acceptance, one story)
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # ROADMAP M18's acceptance, the harness's half.
    assert operator("start", KEY) == 0
    assert "is started, privately" in capsys.readouterr().out

    # Dispatched with no label: the start record authorizes it, and the harness picks the private worker.
    with private_worker_does(*commit_and_push(BRANCH), result=blocked_result()):
        runner = InlineRunner()
        assert dispatch_in_tick(conn, "--kind", "implement", runner=runner).code == 0
        run = last_run(conn)
        assert run["private"] == 1
        assert "private: started by the operator" in capsys.readouterr().out
        assert main(["_run", str(run["id"])], runner=runner) == 0
    [worker] = agent_runs(agent_log)
    argv = worker["argv"]
    assert isinstance(argv, list)
    assert "canopy-worker-private" in argv
    assert "# canopy private worker: implement" in str(argv[-1])
    run = last_run(conn)
    assert run["status"] == "blocked"
    [report, question] = db.messages_of(conn, conversation.TICKET, KEY, 10)
    assert (report["kind"], report["body"], report["run_id"]) == ("report", "half done", run["id"])
    assert (question["kind"], question["body"]) == ("question", QUESTION)

    # The question is on the attention list, raised by the harness, and in `canopy show`.
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "waiting on the operator")):
        assert main(["tick"]) == 0
        ctx = context(canopy_env)
        [item] = [i for i in attention.listed(ctx) if i.reason == "awaiting_reply"]
        assert item.ticket_key == KEY
        # That tick read the question: the web UI marks only what came after it as waiting for a tick.
        assert db.acknowledged_message_id(conn) == question["id"]
        assert QUESTION in item.detail
        capsys.readouterr()
        assert operator("show", KEY) == 0
        shown = capsys.readouterr().out
        assert QUESTION in shown
        assert f"Message {question['id']} waits on your answer" in shown
        assert operator("status") == 0
        assert f"awaiting your reply to message {question['id']}" in capsys.readouterr().out

        # `canopy reply` during the loop's wait ends it, and the next tick resumes the ticket with the reply.
        reply = "Blue, to match the header."
        time = FakeTime()
        with (
            private_worker_does(result={**blocked_result(), "status": "done", "question": None}),
            contextlib.ExitStack() as after_reply,
        ):

            def reply_once() -> None:
                # The overseer's next tick dispatches the resume, so its new commands outlast this call.
                if not db.latest_message_id(conn, source="operator"):
                    assert operator("reply", KEY, reply) == 0
                    newest = db.latest_message_id(conn, source="operator")
                    after_reply.enter_context(
                        overseer_does(
                            canopy(
                                "dispatch",
                                KEY,
                                "--repo",
                                "repo",
                                "--kind",
                                "resume",
                                "--reason",
                                "reply",
                                "--cursor",
                                f"message={newest}",
                                "--context",
                                f"Operator reply: message {newest}",
                            ),
                        )
                    )

            time.on_sleep = reply_once
            term, _ = console()
            statuses = repeat.run(
                ctx,
                dry_run=False,
                interval_minutes=15,
                max_ticks=2,
                console=term,
                stop=repeat.Stop(),
                sleep=time.sleep,
                clock=time.clock,
            )
            assert statuses == {"ok": 2}
            # Woken at once, but no sooner than a minute after the first tick began, not after 15 minutes.
            assert sum(time.slept) == pytest.approx(60)  # loop.min_gap_minutes, by default
            resumed = wait_for_run(conn, int(last_run(conn)["id"]))
            assert (resumed["kind"], resumed["private"], resumed["status"]) == ("resume", 1, "done")
            prompt = (canopy_env.state_dir / "runs" / f"{resumed['id']}.prompt").read_text()
            assert reply in prompt
            assert "the operator's reply to message" in prompt
            ticket = present(db.get_ticket(conn, KEY))
            assert ticket.last_message_id == db.latest_message_id(conn, source="operator")
            # The reply answered the question: the next tick raises no `awaiting_reply`, and acknowledges the reply.
            assert conversation.awaiting(conn) == []
            acknowledged = present(db.acknowledged_message_id(conn))
            assert acknowledged >= db.latest_message_id(conn, source="operator")


def test_references_name_their_kind_and_a_kind_refuses_verbs_it_does_not_take() -> None:
    assert conversation.parse_ref("PROJ-12") == conversation.Ref("ticket", "PROJ-12")
    assert conversation.parse_ref("run:7") == conversation.Ref("run", "7")
    assert conversation.parse_ref("chore:build-health") == conversation.Ref("chore", "build-health")
    assert conversation.parse_ref("api#42").kind == "pr"
    assert conversation.parse_ref("https://github.com/o/r/pull/42").kind == "pr"
    for bad in ("run:x", "run:0", "chore:Bad", "a b", "PROJ/1", "#4", "https://github.com/o/r/issues/4", ""):
        with pytest.raises(conversation.Refused, match="bad_ref"):
            conversation.parse_ref(bad)
    conversation.check_verb(conversation.parse_ref("run:7"), "show")
    with pytest.raises(conversation.Refused, match=r"unsupported.*takes only reply, dismiss, show"):
        conversation.check_verb(conversation.parse_ref("chore:build-health"), "start")
    # A PR takes `start` and `stop` for a review request, `grant`, and `show`; working one waits on M14.
    conversation.check_verb(conversation.parse_ref("api#42"), "show")
    with pytest.raises(conversation.Refused, match=r"unsupported.*M14"):
        conversation.check_verb(conversation.parse_ref("api#42"), "reply")


@pytest.mark.parametrize("variable", ["CANOPY_TICK_ID", "CANOPY_RUN_ID"])
@pytest.mark.parametrize("verb", [["start", KEY], ["stop", KEY], ["reply", KEY, "yes"], ["forget", KEY]])
def test_the_operators_commands_refuse_inside_canopys_runs(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    verb: list[str],
) -> None:
    with mock.patch.dict(os.environ, {variable: "1"}):
        assert main(verb) == 1
        assert f"refused (inside_run): {variable} is set" in capsys.readouterr().err
        assert db.starts(conn) == []


def test_start_refuses_without_tracker_tools_for_a_private_worker(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.write_shared('[tracker]\nprovider = "linear"\nquery = "assigned to me"\n')
    assert main(["start", KEY]) == 1
    assert "start refused (no_read_tools)" in capsys.readouterr().err
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace(
            "[tracker]\n", '[tracker]\nmcp_server = "linear"\nread_tools = ["get_issue"]\n'
        )
    )
    assert main(["start", KEY]) == 0


def test_reply_refuses_an_unknown_ticket_stop_a_public_one_and_reply_is_bounded_and_idempotent(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["reply", KEY, "hello"]) == 1
    assert "reply refused (unknown)" in capsys.readouterr().err
    assert main(["stop", KEY]) == 1
    assert "stop refused (not_started)" in capsys.readouterr().err
    assert main(["start", KEY]) == 0
    assert main(["reply", KEY, "x" * (conversation.MAX_OPERATOR + 1)]) == 1
    assert "reply refused (bad_body)" in capsys.readouterr().err
    assert main(["reply", KEY, "  go ahead  "]) == 0
    # The same reply again, after an uncertain result, is the same submission.
    assert main(["reply", KEY, "go ahead"]) == 0
    assert "nothing new recorded" in capsys.readouterr().out
    [message] = db.messages_of(conn, conversation.TICKET, KEY, 10)
    assert (message["source"], message["kind"], message["channel"], message["body"]) == (
        "operator",
        "reply",
        "cli",
        "go ahead",
    )


def test_a_reply_answers_the_latest_question(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    assert main(["start", KEY]) == 0
    question = db.insert_message(conn, "ticket", KEY, source="worker", kind="question", channel="run", body="A or B?")
    with mock.patch.object(sys, "stdin", io.StringIO("B\n")):
        assert main(["reply", KEY]) == 0
    reply = present(db.get_message(conn, question + 1))
    assert (reply["body"], reply["answers"]) == ("B", question)
    assert conversation.latest_question(conn, KEY) is None


def test_a_stopped_ticket_is_dispatched_by_nothing_until_started_again(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert operator("start", KEY) == 0
    assert operator("stop", KEY) == 0
    # Not even with a queue label: a stopped ticket stays private.
    runner = InlineRunner()
    assert dispatch_in_tick(conn, "--label", "agent-ready-tester", "--kind", "implement", runner=runner).code == 1
    assert "dispatch refused (stopped)" in capsys.readouterr().err
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    record = present(conversation.start_of(conn, KEY))
    assert record.status == StartStatus.STOPPED
    assert operator("start", KEY) == 0
    assert dispatch_in_tick(conn, "--kind", "implement", runner=runner).code == 0


def test_a_private_ticket_is_never_split(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert operator("start", KEY) == 0
    runner = InlineRunner()
    assert dispatch_in_tick(conn, "--kind", "split", "--request", "c-1", runner=runner).code == 1
    assert "dispatch refused (private)" in capsys.readouterr().err


def test_a_stop_that_commits_before_the_runs_insert_wins(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert operator("start", KEY) == 0
    real = conversation.prompt_conversation

    def stop_meanwhile(c: sqlite3.Connection, key: str) -> str:
        # The operator stops the ticket after the dispatch planned the run and before it inserts it.
        conversation.stop(canopy_env.journal(), conversation.Ref("ticket", key), channel="cli")
        return real(c, key)

    with mock.patch.object(conversation, "prompt_conversation", autospec=True, side_effect=stop_meanwhile):
        assert dispatch_in_tick(conn, "--kind", "implement", runner=InlineRunner()).code == 1
        assert "dispatch refused (stopped)" in capsys.readouterr().err
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert {s["status"] for s in pool(treehouse_state)} == {"available"}


def test_run_reads_the_start_record_again_before_the_worker_starts(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    assert operator("start", KEY) == 0
    runner = InlineRunner()
    assert dispatch_in_tick(conn, "--kind", "implement", runner=runner).code == 0
    assert operator("stop", KEY) == 0
    run = last_run(conn)
    assert main(["_run", str(run["id"])], runner=runner) == 0
    run = last_run(conn)
    assert run["status"] == "stopped"
    assert "stopped the ticket before its worker started" in run["result_json"]
    assert not agent_log.exists()
    assert {s["status"] for s in pool(treehouse_state)} == {"available"}
    # `stopped` raises no attention item.
    assert attention.from_runs(conn) == []


def test_a_public_run_does_not_start_once_the_ticket_is_started_privately(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    runner = InlineRunner()
    assert dispatch_in_tick(conn, "--label", "agent-ready-tester", "--kind", "implement", runner=runner).code == 0
    assert operator("start", KEY) == 0
    run = last_run(conn)
    assert run["private"] == 0
    assert main(["_run", str(run["id"])], runner=runner) == 0
    assert last_run(conn)["status"] == "stopped"
    assert not agent_log.exists()


def private_by_default(canopy_env: CanopyEnv) -> None:
    """Set `tracker.private` in the user file: a labeled ticket's first dispatch starts it privately."""
    canopy_env.write_user(canopy_env.user_file.read_text().replace("[tracker]\n", "[tracker]\nprivate = true\n"))


def test_with_tracker_private_a_labeled_tickets_first_dispatch_starts_it_privately(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_by_default(canopy_env)
    runner = InlineRunner()
    # The label still authorizes the first dispatch: without one there is nothing to start.
    assert dispatch_in_tick(conn, "--kind", "implement", runner=runner).code == 1
    assert "dispatch refused (unauthorized)" in capsys.readouterr().err
    assert db.starts(conn) == []

    with private_worker_does(*commit_and_push(BRANCH), result=blocked_result()):
        assert dispatch_in_tick(conn, "--label", "agent-ready-tester", "--kind", "implement", runner=runner).code == 0
        assert "label agent-ready-tester; starts it privately (tracker.private)" in capsys.readouterr().out
        run = last_run(conn)
        assert run["private"] == 1
        record = present(conversation.start_of(conn, KEY))
        assert (record.status, record.channel) == (StartStatus.STARTED, conversation.LABEL)
        assert main(["_run", str(run["id"])], runner=runner) == 0
    [worker] = agent_runs(agent_log)
    argv = worker["argv"]
    assert isinstance(argv, list)
    assert "canopy-worker-private" in argv
    assert last_run(conn)["status"] == "blocked"

    # From now on it is an ordinary private ticket: no label needed, and `canopy stop` stops it.
    assert operator("show", KEY) == 0
    assert "by its first dispatch, on its queue label" in capsys.readouterr().out
    assert operator("reply", KEY, "Blue.") == 0
    with private_worker_does(result={**blocked_result(), "status": "done", "question": None}):
        assert dispatch_in_tick(conn, "--kind", "resume", "--reason", "reply", runner=runner).code == 0
    assert last_run(conn)["private"] == 1
    assert operator("stop", KEY) == 0
    stopped = dispatch_in_tick(
        conn, "--label", "agent-ready-tester", "--kind", "resume", "--reason", "reply", runner=runner
    )
    assert stopped.code == 1
    assert "dispatch refused (stopped)" in capsys.readouterr().err


def test_tracker_private_leaves_a_ticket_already_worked_in_public_public(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    runner = InlineRunner()
    assert dispatch_in_tick(conn, "--label", "agent-ready-tester", "--kind", "implement", runner=runner).code == 0
    private_by_default(canopy_env)
    # Its conversation is already on the tracker, so it stays there.
    conn.execute("UPDATE runs SET status = 'failed', ended_at = started_at")
    assert dispatch_in_tick(conn, "--label", "agent-ready-tester", "--kind", "implement", runner=runner).code == 0
    assert last_run(conn)["private"] == 0
    assert db.starts(conn) == []


def test_tracker_private_in_a_dry_run_writes_no_start_record(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    private_by_default(canopy_env)
    with in_tick(conn, dry_run=True):
        assert main(["dispatch", KEY, "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]) == 0
    assert db.starts(conn) == []
    [decision] = conn.execute("SELECT rationale FROM decisions").fetchall()
    assert "starts it privately (tracker.private)" in decision["rationale"]


def test_tracker_private_refuses_without_tracker_tools_for_a_private_worker(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.write_shared('[tracker]\nprovider = "linear"\nquery = "assigned to me"\n')
    private_by_default(canopy_env)
    assert (
        dispatch_in_tick(conn, "--label", "agent-ready-tester", "--kind", "implement", runner=InlineRunner()).code == 1
    )
    assert "dispatch refused (no_read_tools)" in capsys.readouterr().err
    assert db.starts(conn) == []


def test_stop_now_ends_the_running_run_and_returns_its_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert operator("start", KEY) == 0
    assert dispatch_in_tick(conn, "--kind", "implement", runner=InlineRunner()).code == 0
    run = last_run(conn)
    # Stand-ins for `_run` and its worker, each leading its own process group as the real ones do.
    # Each has a log, and so a lifelock, of its own.
    state = canopy_env.state_dir
    run_pid = procs.SubprocessRunner().spawn(["sleep", "60"], cwd=canopy_env.repo, log_path=state / "run.log")
    worker_pid = procs.SubprocessRunner().spawn(["sleep", "60"], cwd=canopy_env.repo, log_path=state / "worker.log")
    conn.execute("UPDATE runs SET pid = ?, worker_pid = ? WHERE id = ?", (run_pid, worker_pid, run["id"]))
    assert {s["status"] for s in pool(treehouse_state)} == {"available", "leased"}

    assert operator("stop", KEY) == 0
    assert "will finish; --now ends it" in capsys.readouterr().out
    assert last_run(conn)["status"] == "running"
    assert operator("stop", KEY, "--now") == 0
    assert "was ended and its slots returned" in capsys.readouterr().out

    run = last_run(conn)
    assert run["status"] == "stopped"
    assert not procs.alive(run_pid)
    assert not procs.alive(worker_pid)
    assert {s["status"] for s in pool(treehouse_state)} == {"available"}
    assert attention.from_runs(conn) == []
    [report] = db.run_messages(conn, int(run["id"]))
    assert "canopy stop --now" in report["body"]


def test_a_private_run_refuses_a_worktree_config_that_names_the_trackers_tools(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    for slot in git_pool.slots:
        (slot / "opencode.json").write_text('{"permission": {"atlassian_addOrEditJiraIssueComment": "allow"}}')
    assert operator("start", KEY) == 0
    runner = InlineRunner()
    assert dispatch_in_tick(conn, "--kind", "implement", runner=runner).code == 0
    assert main(["_run", str(last_run(conn)["id"])], runner=runner) == 0
    run = last_run(conn)
    assert run["status"] == "crashed"
    assert "names tools of the tracker's MCP server 'atlassian'" in run["result_json"]
    assert not agent_log.exists()


def test_the_private_worker_definition_allows_only_the_trackers_read_tools(canopy_env: CanopyEnv) -> None:
    cfg = config.load(canopy_env.root)
    text = (definitions.ensure(canopy_env.state_dir, cfg) / "agents" / "canopy-worker-private.md").read_text()
    rules = [line.strip() for line in text.splitlines() if line.startswith('  "atlassian_')]
    tools = present(cfg.tracker.tools())
    # The wildcard deny comes first: the last matching rule wins (D021).
    assert rules == ['"atlassian_*": deny', *(f'"atlassian_{t}": allow' for t in tools.allowed)]
    writes = ("addOrEditJiraIssueComment", "editJiraIssue", "createJiraIssue", "transitionJiraIssue", "executeWrite")
    assert not set(writes) & set(tools.allowed)
    for cli in ("gh", "acli", "jira"):
        assert f'    "{cli} *": deny\n' in text
    # As shipped, it names no server: the snapshot without config is the bundled file.
    bundled = (resources.agents_dir() / "canopy-worker-private.md").read_text()
    assert '"atlassian_' not in bundled
    with pytest.raises(definitions.DefinitionsError):
        definitions.render_private(bundled.replace("# canopy: tracker tools", "# gone"), tools)


def test_github_defaults_keep_the_pr_tools_and_no_issue_writes() -> None:
    tools = config.DEFAULT_TRACKER_TOOLS["github"]
    assert tools.server == "github"
    assert "create_pull_request" in tools.allowed
    for write in ("issue_write", "add_issue_comment", "sub_issue_write", "merge_pull_request", "actions_run_trigger"):
        assert write not in tools.allowed


def test_the_migration_gives_runs_from_before_it_a_conversation(tmp_path: Path, journals: Journals) -> None:
    conn = journal_at(journals, tmp_path, 2)
    conn.execute("INSERT INTO ticks (id, started_at) VALUES (1, 'x')")
    db.touch_ticket(conn, "OLD-1", "/r")
    results = [
        ("done", json.dumps({"summary": "did it", "prs": {"api": "https://e.test/pr/1", "web": None}}), "2026-01-02"),
        ("blocked", json.dumps({"summary": "", "question": "Which one?"}), "2026-01-01"),
        ("crashed", "not json", "2026-01-03"),
        ("running", None, None),
    ]
    for status, result, ended in results:
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, log_path, status, result_json) "
            "VALUES (1, 'OLD-1', 'implement', 'b', 'x', ?, 'l', ?, ?)",
            (ended, status, result),
        )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(2)
    found = [(m["run_id"], m["kind"], m["body"], m["source"]) for m in db.messages_of(conn, "ticket", "OLD-1", 10)]
    assert found == [
        (2, "report", "ended blocked", "worker"),
        (2, "question", "Which one?", "worker"),
        (1, "report", "did it\nhttps://e.test/pr/1", "worker"),
        (3, "report", "ended crashed", "worker"),
    ]


def test_run_messages_and_the_run_ended_event_carry_the_message() -> None:
    result = json.dumps({"summary": " did it ", "prs": {"api": "https://e.test/pr/1"}, "question": "Q?"})
    assert conversation.run_messages(RunStatus.DONE, result) == [("report", "did it\nhttps://e.test/pr/1")]
    assert conversation.run_messages(RunStatus.BLOCKED, result)[1] == ("question", "Q?")
    assert conversation.run_messages(RunStatus.CRASHED, json.dumps({"harness": "gone"})) == [("report", "gone")]


def test_run_ended_names_the_message_the_run_recorded(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    canopy_env.append_user('\n[notify.sinks.log]\ncmd = "true"\nevents = ["runs"]\n')
    cfg = config.load(canopy_env.root)
    tick_id = db.start_tick(conn, dry_run=False)
    db.touch_ticket(conn, KEY, "/r")
    run_id = db.insert_run(
        conn, tick_id=tick_id, key=KEY, kind="implement", branch=BRANCH, slots=[], runs_dir=canopy_env.state_dir
    )
    run = present(db.get_run(conn, run_id))
    result = json.dumps({"summary": "s", "question": "Q?"})
    assert conversation.close_run(conn, cfg, run, RunStatus.BLOCKED, result)
    event = conn.execute("SELECT fields FROM notify_events WHERE kind = 'run.ended'").fetchone()
    question = db.messages_of(conn, "ticket", KEY, 10)[-1]
    assert json.loads(event[0])["message"] == question["id"]
    assert outbox.run_ended(cfg, run, RunStatus.DONE, "{}")(None) is not None


def test_the_state_block_marks_a_private_ticket_with_its_new_operator_messages(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    agent_log: Path,
    treehouse_state: Path,
) -> None:
    assert main(["start", KEY]) == 0
    db.touch_ticket(conn, "PROJ-2", str(canopy_env.root))
    question = db.insert_message(conn, "ticket", KEY, source="worker", kind="question", channel="run", body="A or B?")
    assert main(["reply", KEY, "B"]) == 0
    with overseer_does(*waits(KEY, "PROJ-2", rationale="next tick")):
        assert main(["tick", "--dry-run"]) == 0
        state = state_block(agent_log)
        tickets = {t["key"]: t for t in state["tickets"]}
        assert "private" not in tickets["PROJ-2"]
        private = tickets[KEY]["private"]
        assert private["message_cursor"] is None
        assert [(m["id"], m["body"], m["answers"]) for m in private["new_operator_messages"]] == [
            (question + 1, "B", question)
        ]
        assert private["awaiting_reply"] is None
        # A handled message moves the cursor past it.
        assert main(["ticket", "set", KEY, "--repo", "repo", "--cursor", f"message={question + 1}"]) == 0
        ticket = present(db.get_ticket(conn, KEY))
        assert conversation.state_section(conn, ticket) == {
            **private,
            "message_cursor": question + 1,
            "new_operator_messages": [],
        }


def test_a_stopped_ticket_is_named_in_the_state_block_by_key_alone(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    agent_log: Path,
    treehouse_state: Path,
) -> None:
    # Listed with the other tickets, it would be owed a decision every tick it stays stopped.
    assert main(["start", KEY]) == 0
    assert main(["stop", KEY]) == 0
    db.touch_ticket(conn, "PROJ-2", str(canopy_env.root))
    with overseer_does(canopy("decide", "PROJ-2", "wait", "--rationale", "next tick")):
        assert main(["tick", "--dry-run"]) == 0
        stopped = state_block(agent_log)
        assert stopped["stopped"] == [KEY]
        assert [t["key"] for t in stopped["tickets"]] == ["PROJ-2"]
    # Started again, it is a private ticket like any other.
    assert main(["start", KEY]) == 0
    with overseer_does(*waits(KEY, "PROJ-2", rationale="next tick")):
        assert main(["tick", "--dry-run"]) == 0
        started = state_block(agent_log)
        assert started["stopped"] == []
        assert {t["key"]: "private" in t for t in started["tickets"]} == {KEY: True, "PROJ-2": False}


def test_a_message_cursor_is_a_message_id(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ticket", "set", KEY, "--repo", "repo", "--cursor", "message=c-1"]) == 2
    assert "a message cursor is a message id" in capsys.readouterr().err


def test_a_ticket_a_tick_decided_about_without_recording_a_phase_is_seen(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The overseer records a decision for every ticket it looks at, but not always the ticket's own phase.
    def phase_line() -> str:
        assert operator("status") == 0
        [line] = [line for line in capsys.readouterr().out.splitlines() if line.startswith(f"  {KEY}  started")]
        return line.split("  phase ", 1)[1]

    def summary() -> tuple[str | None, str | None]:
        found = views.summary(conn, db.recent_tickets(conn, 1, key=KEY)[0])
        return found.phase, found.last_decision

    def in_a_tick(*args: str) -> None:
        with in_tick(conn, ends_ok=True):
            assert main(list(args)) == 0

    assert operator("start", KEY) == 0
    assert phase_line() == "not seen by a tick yet"
    assert summary() == (None, None)

    in_a_tick("decide", KEY, "wait", "--rationale", "blocked_by: PROJ-2")
    assert phase_line() == "not recorded, last decision wait"
    assert summary() == (None, "wait")
    assert operator("show", KEY) == 0
    assert "phase not recorded, last decision wait;" in capsys.readouterr().out

    in_a_tick("ticket", "set", KEY, "--phase", "blocked")
    assert phase_line() == "blocked"
    assert summary() == ("blocked", "wait")

    # Forgetting clears the phase and starts the loop's view over: the decisions before it no longer count.
    assert operator("forget", KEY) == 0
    assert phase_line() == "not seen by a tick yet"
    assert summary() == (None, None)


def test_show_a_run_and_a_chore(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with worker_does(*commit_and_push(BRANCH)):
        runner = InlineRunner()
        assert dispatch_in_tick(conn, "--label", "agent-ready-tester", "--kind", "implement", runner=runner).code == 0
        assert main(["_run", "1"], runner=runner) == 0
        capsys.readouterr()
        assert main(["show", "run:1"]) == 0
        shown = capsys.readouterr().out
        assert f"run:1: implement of {KEY}, done" in shown
        assert "https://example.test/pr/1" in shown
        assert "report" in shown
        assert main(["show", "run:99"]) == 1
        assert main(["show", "chore:nightly"]) == 1
        assert "no chore 'nightly'" in capsys.readouterr().err
        # A public ticket's show says so, and has the run's report.
        assert main(["show", KEY]) == 0
        assert "public: its queue label authorizes it" in capsys.readouterr().out


def test_show_drops_control_characters(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["start", KEY]) == 0
    db.insert_message(
        conn, "ticket", KEY, source="worker", kind="question", channel="run", body="red\x1b[2Jor\rblue?\nsecond line"
    )
    capsys.readouterr()
    assert main(["show", KEY]) == 0
    shown = capsys.readouterr().out
    assert "\x1b" not in shown
    assert "\r" not in shown
    assert "    red [2Jor blue?\n    second line" in shown


def test_the_snapshot_follows_the_tracker_tools(canopy_env: CanopyEnv) -> None:
    cfg = config.load(canopy_env.root)
    first = definitions.ensure(canopy_env.state_dir, cfg)
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[tracker]\n", '[tracker]\nread_tools = ["getJiraIssue"]\n')
    )
    second = definitions.ensure(canopy_env.state_dir, config.load(canopy_env.root))
    assert first != second
    assert '"atlassian_getJiraIssue": allow' in (second / "agents" / "canopy-worker-private.md").read_text()


def test_config_refuses_a_tool_name_that_could_reach_the_definition_as_more_than_a_name(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[tracker]\n", '[tracker]\nread_tools = ["a\\": allow"]\n')
    )
    with pytest.raises(config.ConfigError, match="read_tools"):
        config.load(canopy_env.root)
    canopy_env.append_shared('mcp_server = "github"\n')
    with pytest.raises(config.ConfigError, match="is private"):
        config.load(canopy_env.root)
