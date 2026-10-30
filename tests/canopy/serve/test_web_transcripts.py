"""The web UI's transcripts (DESIGN §13, §22). Reads only; every text in them is agent output.

A run's and a chore run's pages, and a run's, chore run's, or tick's session read back from the events its log holds.
"""

import dataclasses
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from canopy.core import cards, gc_passes, run_models
from canopy.core.run_models import Due
from canopy.core.vocab import ModelsRead
from canopy.runtime import transcript
from canopy.serve.backend import Backend
from tests.canopy.web_helpers import client, signed_in


def test_a_run_page_is_the_run_as_the_runs_list_shows_it(backend: Backend) -> None:
    c = client(None, backend)
    listed = {r["id"]: r for r in c.get("/api/runs").json()}
    for run_id in (39, 41, 43):
        assert c.get(f"/api/runs/{run_id}").json() == listed[run_id]
    run = c.get("/api/runs/43").json()
    # A path inside the workspace is shown from its root: the run's log, and the worktrees a running run holds.
    assert run["log_path"] == ".canopy/runs/43.log"
    assert run["worktrees"] == [".treehouse/mobile-8e41d0c7/1/mobile", ".treehouse/web-3f9c2a1b/2/web"]
    assert c.get("/api/runs/39").json()["worktrees"] == []


def test_no_such_run_is_a_404_and_a_run_id_is_a_positive_integer(backend: Backend) -> None:
    c = client(None, backend)
    for path in ("/api/runs/99", "/api/runs/99/transcript", "/api/runs/99/output"):
        missing = c.get(path)
        assert (missing.status_code, missing.json()["detail"]) == (404, "no run 99")
    assert c.get("/api/runs/0/transcript").status_code == 422
    assert c.get("/api/runs/two").status_code == 422


def test_a_runs_transcript_is_its_sessions_text_tool_calls_and_steps_in_order(backend: Backend) -> None:
    found = client(None, backend).get("/api/runs/39/transcript").json()
    assert (found["status"], found["session_id"], found["truncated"], found["unreadable"]) == (
        "read",
        "ses_mock39",
        False,
        0,
    )
    entries = found["entries"]
    assert [e["kind"] for e in entries[:5]] == ["text", "tool", "tool", "tool", "step"]
    read, missing = entries[2], entries[3]
    assert (read["tool"], read["status"], read["title"]) == ("read", "completed", "src/search/SearchBox.tsx")
    # Its input is indented JSON, and a file's markup is characters for the UI to show as text.
    assert json.loads(read["input"])["filePath"].endswith("/src/search/SearchBox.tsx")
    assert "return <input value={query}" in read["output"]
    assert (missing["status"], missing["title"]) == ("error", None)
    assert missing["output"].startswith("File not found: ")
    bash = next(e for e in entries if e["kind"] == "tool" and e["tool"] == "bash")
    assert (bash["title"], bash["duration_ms"]) == ("Run the search tests", 14_000)
    # Its steps are what the run cost, and its last text is the result line the harness read.
    steps = [e["cost_usd"] for e in entries if e["kind"] == "step"]
    assert round(sum(steps), 2) == client(None, backend).get("/api/runs/39").json()["cost_usd"]
    assert json.loads(entries[-2]["text"])["status"] == "done"


def test_a_runtime_error_ends_a_failed_runs_transcript(backend: Backend) -> None:
    entries = client(None, backend).get("/api/runs/40/transcript").json()["entries"]
    assert entries[-1] == {
        "kind": "error",
        "at": "2026-10-08T10:49:54Z",
        "name": "APIError",
        "message": "Rate limited: retry after 60s",
        "call": 2,
    }


def test_a_running_runs_transcript_is_what_its_worker_printed_so_far(backend: Backend) -> None:
    found = client(None, backend).get("/api/runs/41/transcript").json()
    assert (found["status"], found["session_id"]) == ("read", "ses_mock41")
    assert [e["kind"] for e in found["entries"]] == ["text", "tool", "step", "tool", "step"]
    assert found["entries"][-2]["title"] == "Run the login tests"


def test_a_running_run_shows_its_latest_tool_call(backend: Backend) -> None:
    runs = {r["id"]: r for r in client(None, backend).get("/api/runs").json()}
    assert runs[41]["activity"] == {"tool": "bash", "did": "npm test -- login", "at": "2026-10-08T12:27:00Z"}
    assert runs[39]["activity"] is None  # ended: its result says what it did


def test_a_running_run_shows_its_card_whether_stale_by_its_calls_and_when_it_goes_stale_by_time(
    backend: Backend,
) -> None:
    runs = {r["id"]: r for r in client(None, backend).get("/api/runs").json()}
    fresh, stale = runs[41]["card"], runs[43]["card"]
    assert (fresh["now"], fresh["at"], fresh["calls_since"]) == ("running the login tests", "2026-10-08T12:24:00Z", 3)
    assert fresh["done"] == [{"step": "add the SSO callback", "proof": "tests pass: 12/12"}]
    assert (fresh["stale"], fresh["stale_at"]) == (False, "2026-10-08T12:34:00Z")
    assert (stale["stale"], stale["calls_since"]) == (True, 26)  # past `cards.STALE_CALLS`
    assert runs[39]["card"] is None  # it kept none


def test_only_the_recorded_sessions_events_are_shown(backend: Backend) -> None:
    c = client(None, backend)
    with backend.open() as ctx:
        log = ctx.state_dir / "runs" / "41.log"
    other = {"type": "text", "timestamp": 1, "sessionID": "ses_other", "part": {"type": "text", "text": "not mine"}}
    mine = {**other, "sessionID": "ses_mock41", "part": {"type": "text", "text": "mine"}}
    log.write_text("\n".join(["setup said hello", json.dumps(other), json.dumps(mine), "--- worker stderr ---"]))
    entries = c.get("/api/runs/41/transcript").json()["entries"]
    assert [e["text"] for e in entries] == ["mine"]


def test_a_run_with_no_session_or_no_log_says_so(backend: Backend) -> None:
    c = client(None, backend)
    with backend.open() as ctx:
        ctx.conn.execute("UPDATE runs SET session_id = NULL WHERE id = 39")
        log = ctx.state_dir / "runs" / "40.log"
    log.unlink()
    found = c.get("/api/runs/39/transcript").json()
    # The prompt is canopy's own, kept whether or not the runtime reported a session.
    assert found.pop("prompt")["text"].startswith("# canopy worker: implement\n")
    assert found == {
        "status": "no_session",
        "session_id": None,
        "entries": [],
        "truncated": False,
        "unreadable": 0,
        "removed_after_days": None,
    }
    assert c.get("/api/runs/40/transcript").json()["status"] == "no_log"
    # A link in a log's place is not followed: a worker cannot point it at a file of the operator's.
    log.symlink_to(log.parent / "41.log")
    assert c.get("/api/runs/40/transcript").json()["status"] == "no_log"


def test_each_entry_names_its_model_call_and_the_prompt_is_the_first_calls_input(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/runs/39/transcript").json()
    assert [(e["kind"], e["call"]) for e in found["entries"]] == [
        ("text", 1),
        ("tool", 1),
        ("tool", 1),
        ("tool", 1),
        ("step", 1),
        ("text", 2),
        ("tool", 2),
        ("tool", 2),
        ("step", 2),
        ("tool", 3),
        ("tool", 3),
        ("text", 3),
        ("step", 3),
    ]
    with backend.open() as ctx:
        kept = ctx.state_dir / "runs" / "39.prompt"
    assert found["prompt"] == {"text": kept.read_text(), "truncated": False}
    # A run canopy kept no prompt for has none; a link in a prompt's place is not followed.
    assert c.get("/api/runs/41/transcript").json()["prompt"] is None
    (kept.parent / "41.prompt").symlink_to(kept)
    assert c.get("/api/runs/41/transcript").json()["prompt"] is None
    # A tick's prompt is its state block, and a chore run's is beside its log too.
    assert c.get("/api/ticks/2/transcript").json()["prompt"]["text"].startswith("## State\n")
    assert c.get("/api/chores/deps/runs/2/transcript").json()["prompt"]["text"].startswith("# canopy chore: deps\n")


@pytest.mark.parametrize(
    ("table", "run_id", "log", "path"),
    [
        ("runs", 39, "runs/39.log", "/api/runs/39/transcript"),
        ("ticks", 2, "ticks/2.log", "/api/ticks/2/transcript"),
        ("chore_runs", 2, "chore-runs/deps/2.log", "/api/chores/deps/runs/2/transcript"),
        ("review_runs", 4, "reviews/4.log", "/api/reviews/4/transcript"),
        ("task_runs", 1, "task-runs/1.log", "/api/tasks/1/runs/1/transcript"),
    ],
)
def test_each_model_call_of_a_run_more_than_one_model_served_names_its_model(
    backend: Backend,
    table: run_models.RunTable,
    run_id: int,
    log: str,
    path: str,
) -> None:
    c = client(None, backend)
    session = c.get(path).json()["session_id"]
    finished = {"type": "step_finish", "timestamp": 1, "sessionID": session}
    calls = [
        {**finished, "part": {"type": "step-finish", "messageID": "msg_a"}},
        {**finished, "part": {"type": "step-finish", "messageID": "msg_b"}},
        # A reply the session's record did not name, or one before canopy kept each reply's model.
        {**finished, "part": {"type": "step-finish", "messageID": "msg_c"}},
    ]
    with backend.open() as ctx:
        with (ctx.state_dir / log).open("a") as f:
            f.writelines(f"{json.dumps(call)}\n" for call in calls)
        replies = {"msg_a": "anthropic/claude-opus-4-1", "msg_b": "anthropic/claude-sonnet-4-5"}
        run_models.record(ctx.conn, Due(table, run_id, session, 1), ModelsRead.FOUND, (), replies=replies)
    steps = [e for e in c.get(path).json()["entries"] if e["kind"] == "step"]
    assert [s["model"] for s in steps[-3:]] == ["anthropic/claude-opus-4-1", "anthropic/claude-sonnet-4-5", None]
    # The mock's own calls name no message canopy kept a model for.
    assert {s["model"] for s in steps[:-3]} == {None}


def test_a_transcript_past_its_bounds_says_it_was_cut(backend: Backend) -> None:
    with mock.patch.object(transcript, "MAX_ENTRIES", 3):
        found = client(None, backend).get("/api/runs/39/transcript").json()
    assert (len(found["entries"]), found["truncated"]) == (3, True)


def test_a_ticks_transcript_is_its_overseers_session(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/ticks/2/transcript").json()
    assert (found["status"], found["session_id"]) == ("read", "ses_tick2")
    # Each model call's tokens by kind as well as together.
    step = found["entries"][-1]
    assert step["split"] == {"input": 2325, "output": 930, "reasoning": 310, "cache_read": 6463, "cache_write": 512}
    assert step["tokens"] == sum(step["split"].values())
    tools = [json.loads(e["input"]) for e in found["entries"] if e["kind"] == "tool"]
    assert [t.get("command", t.get("method")) for t in tools] == [
        "canopy state",
        "get_status",
        "canopy dispatch ABC-104 --label canopy --kind implement --repo web",
        "canopy decide ABC-101 wait 'run 41 is implementing it.'",
    ]
    # Tick 1 kept no output; no such tick is a 404.
    assert c.get("/api/ticks/1/transcript").json()["status"] == "no_log"
    missing = c.get("/api/ticks/99/transcript")
    assert (missing.status_code, missing.json()["detail"]) == (404, "no tick 99")


def test_a_ticks_output_is_the_end_of_its_file_as_written_stderr_included(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/ticks/2/output").json()
    with backend.open() as ctx:
        written = (ctx.state_dir / "ticks" / "2.log").read_text()
    assert found == {
        "status": "read",
        "text": written,
        "size": len(written.encode()),
        "truncated": False,
        "removed_after_days": None,
    }
    # What the transcript leaves out: the runtime's own lines on stderr.
    assert "--- stderr ---\nINFO  " in found["text"]
    assert "WARN  " not in json.dumps(c.get("/api/ticks/2/transcript").json())
    # Tick 1 kept no output; no such tick is a 404.
    assert c.get("/api/ticks/1/output").json() == {
        "status": "no_output",
        "text": "",
        "size": 0,
        "truncated": False,
        "removed_after_days": None,
    }
    missing = c.get("/api/ticks/99/output")
    assert (missing.status_code, missing.json()["detail"]) == (404, "no tick 99")
    assert c.get("/api/ticks/0/output").status_code == 422


def test_a_runs_output_is_the_end_of_its_log_as_written_setup_and_stderr_included(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/runs/40/output").json()
    with backend.open() as ctx:
        written = (ctx.state_dir / "runs" / "40.log").read_text()
    assert found == {
        "status": "read",
        "text": written,
        "size": len(written.encode()),
        "truncated": False,
        "removed_after_days": None,
    }
    # What the transcript leaves out: its setup command's output, and the runtime's own lines on stderr.
    assert found["text"].startswith("--- setup web stdout ---\n")
    assert "--- worker stderr ---\nERROR " in found["text"]
    transcript_text = json.dumps(c.get("/api/runs/40/transcript").json())
    assert "Packages: +412" not in transcript_text
    assert "rate limited: retry after" not in transcript_text
    assert c.get("/api/runs/0/output").status_code == 422


def test_a_chore_runs_page_is_its_row_and_the_whole_of_what_it_reported(backend: Backend) -> None:
    c = client(None, backend)
    listed = {r["id"]: r for r in c.get("/api/chores/deps").json()["runs"]}
    page = c.get("/api/chores/deps/runs/2").json()
    assert (page["chore"], page["run"]) == ("deps", listed[2])
    assert (page["summary"], page["note"]) == ("One advisory touches web's lockfile.", None)
    assert [f["id"] for f in page["findings"]] == ["lodash-advisory"]
    assert page["findings"][0]["link"] == "https://github.com/advisories/GHSA-35jh-r3h4-6jhm"

    # The row's summary is cut for a list; the page's is the whole of it, and the harness's note is apart from it.
    summary = "\n".join(f"- repository {i}: {' '.join(['clean'] * 20)}" for i in range(12))
    note = "the chore's last line was not a valid result; its findings are not recorded"
    with backend.open() as ctx:
        ctx.conn.execute(
            "UPDATE chore_runs SET result_json = ? WHERE id = 1",
            (json.dumps({"status": "ok", "summary": summary, "findings": []}),),
        )
        ctx.conn.execute(
            "UPDATE chore_runs SET status = 'unknown', result_json = ? WHERE id = 3",
            (json.dumps({"harness": note}),),
        )
    first = c.get("/api/chores/deps/runs/1").json()
    assert len(first["run"]["summary"]) < len(summary) == len(first["summary"])
    assert (first["note"], first["findings"]) == (None, [])
    unknown = c.get("/api/chores/build-health/runs/3").json()
    assert (unknown["run"]["state"], unknown["summary"], unknown["note"]) == ("failed", None, note)


def test_a_chore_runs_transcript_is_its_sessions_events(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/chores/deps/runs/2/transcript").json()
    assert (found["status"], found["session_id"]) == ("read", "ses_chore2")
    commands = [json.loads(e["input"])["command"] for e in found["entries"] if e["kind"] == "tool"]
    assert commands == ["npm audit --omit=dev", "npm audit --omit=dev"]
    assert "Prototype Pollution" in found["entries"][1]["output"]
    # Its last text is the result line the harness read; a running run's log holds no events yet.
    assert json.loads(found["entries"][-2]["text"])["status"] == "ok"
    assert c.get("/api/chores/build-health/runs/4/transcript").json()["entries"] == []
    assert c.get("/api/chores/deps/runs/1/transcript").json()["status"] == "no_log"


def test_a_chore_run_is_found_only_under_its_own_chore(backend: Backend) -> None:
    c = client(None, backend)
    for path in ("/api/chores/deps/runs/4", "/api/chores/deps/runs/4/transcript", "/api/chores/deps/runs/99"):
        missing = c.get(path)
        assert missing.status_code == 404, path
    assert c.get("/api/chores/deps/runs/4").json()["detail"] == "chore 'deps' has no run 4"
    assert c.get("/api/chores/deps/runs/0").status_code == 422
    bad = c.get("/api/chores/Not_A_Name/runs/2")
    assert (bad.status_code, bad.json()["detail"]["guard"]) == (409, "bad_ref")


def test_a_chore_deleted_from_the_config_keeps_its_runs_pages(backend: Backend) -> None:
    chores = {name: chore for name, chore in backend.config.chores.items() if name != "deps"}
    deleted = dataclasses.replace(backend, config=backend.config.model_copy(update={"chores": chores}))
    c = client(None, deleted)
    # Its chore's page is gone, as `canopy show chore:deps` refuses it; the journal's history of it is not.
    assert c.get("/api/chores/deps").status_code == 404
    assert c.get("/api/chores/deps/runs/2").json()["run"]["id"] == 2
    assert c.get("/api/chores/deps/runs/2/transcript").json()["session_id"] == "ses_chore2"


def test_a_file_retention_removed_says_after_how_many_days(backend: Backend) -> None:
    c = client(None, backend)
    with backend.open() as ctx:
        state = ctx.state_dir
        # A pass whose cutoffs are past every run's and tick's end in the mock, and one before them, which removed none.
        for days, cut in ((40, "2026-09-01T00:00:00.000Z"), (30, "2026-10-20T00:00:00.000Z")):
            gc_passes.record(
                ctx.conn,
                tick_id=None,
                started_at=datetime(2026, 11, 1, tzinfo=UTC),
                run_files_days=days,
                tick_files_days=days // 4,
                run_cutoff=cut,
                tick_cutoff=cut,
                removed={},
                failures=0,
                error=None,
            )
    for path in (state / "runs" / "39.log", state / "runs" / "39.prompt", state / "ticks" / "2.log"):
        path.unlink()

    found = c.get("/api/runs/39/transcript").json()
    assert (found["status"], found["prompt"], found["removed_after_days"]) == ("no_log", None, 30)
    assert c.get("/api/runs/39/output").json()["removed_after_days"] == 30
    # An `ok` tick's files go by `tick_files_days`.
    assert c.get("/api/ticks/2/transcript").json()["removed_after_days"] == 7
    assert c.get("/api/ticks/2/output").json()["removed_after_days"] == 7
    # A file that is there, or gone while no pass reached its row's end, was not removed by retention.
    assert c.get("/api/runs/41/transcript").json()["removed_after_days"] is None
    with backend.open() as ctx:
        ctx.conn.execute("DELETE FROM gc_passes")
    assert c.get("/api/runs/39/transcript").json()["removed_after_days"] is None


def test_a_running_runs_card_asks_its_question_and_the_operator_answers_it_by_letter(backend: Backend) -> None:
    c = client(None, backend)
    question = c.get("/api/runs/41").json()["card"]["question"]
    assert question["options"][1] == "hide the form behind a link"
    assert (question["recommend"], question["asked_at"], question["answer"]) == ("B", "2026-10-08T12:24:00Z", None)
    asked = question["asked_at"]
    headers = signed_in(c)

    refused = c.post("/api/runs/41/answers", json={"letter": "D", "asked_at": asked}, headers=headers)
    assert (refused.status_code, refused.json()["detail"]["guard"]) == (409, "bad_answer")
    moved = c.post("/api/runs/41/answers", json={"letter": "A", "asked_at": "2026-10-08T12:00:00Z"}, headers=headers)
    assert moved.json()["detail"]["guard"] == "moved_on"  # the page showed another question

    answered = c.post("/api/runs/41/answers", json={"letter": "b", "asked_at": asked}, headers=headers).json()
    assert answered == {"letter": "B", "option": "hide the form behind a link", "already": False, "heard": False}
    assert c.get("/api/runs/41").json()["card"]["question"]["answer"] == "B"
    # Once its answers directory is there, as while its agent runs, the answer is written where the agent hears it.
    with backend.open() as ctx:
        answers = cards.answers_dir(ctx.state_dir, "41")
    cards.make_answers(answers)
    again = c.post("/api/runs/41/answers", json={"letter": "B", "asked_at": asked}, headers=headers).json()
    assert (again["already"], again["heard"]) == (True, True)
    assert json.loads((answers / cards.ANSWER_FILE).read_text())["letter"] == "B"
    ended = c.post("/api/runs/39/answers", json={"letter": "A", "asked_at": asked}, headers=headers)
    assert ended.json()["detail"]["guard"] == "ended"
