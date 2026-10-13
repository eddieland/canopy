"""The web UI's transcripts (DESIGN §13, §22): a run's page, and a run's or tick's session read back from the
events its log holds. Reads only; every text in them is agent output."""

import json
from pathlib import Path

import pytest

from canopy.core import transcript
from canopy.serve import mock
from canopy.serve.backend import Backend
from tests.canopy.test_serve import client


@pytest.fixture
def backend(tmp_path: Path) -> Backend:
    return mock.seed(tmp_path / "mock")


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
    for path in ("/api/runs/99", "/api/runs/99/transcript"):
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
    }


def test_a_running_runs_log_holds_no_events_until_it_ends(backend: Backend) -> None:
    found = client(None, backend).get("/api/runs/41/transcript").json()
    assert (found["status"], found["session_id"], found["entries"]) == ("read", "ses_mock41", [])


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
    assert c.get("/api/runs/39/transcript").json() == {
        "status": "no_session",
        "session_id": None,
        "entries": [],
        "truncated": False,
        "unreadable": 0,
    }
    assert c.get("/api/runs/40/transcript").json()["status"] == "no_log"
    # A link in a log's place is not followed: a worker cannot point it at a file of the operator's.
    log.symlink_to(log.parent / "41.log")
    assert c.get("/api/runs/40/transcript").json()["status"] == "no_log"


def test_a_transcript_past_its_bounds_says_it_was_cut(backend: Backend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcript, "MAX_ENTRIES", 3)
    found = client(None, backend).get("/api/runs/39/transcript").json()
    assert (len(found["entries"]), found["truncated"]) == (3, True)


def test_a_ticks_transcript_is_its_overseers_session(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/ticks/2/transcript").json()
    assert (found["status"], found["session_id"]) == ("read", "ses_tick2")
    # With `--thinking`, its reasoning; and each model call's tokens by kind as well as together.
    first = found["entries"][0]
    assert (first["kind"], first["reasoning"]) == ("text", True)
    step = found["entries"][-1]
    assert step["split"] == {"input": 2325, "output": 930, "reasoning": 310, "cache_read": 6463, "cache_write": 512}
    assert step["tokens"] == sum(step["split"].values())
    commands = [json.loads(e["input"])["command"] for e in found["entries"] if e["kind"] == "tool"]
    assert commands == ["canopy state", "canopy decide ABC-101 wait 'run 41 is implementing it.'"]
    # Tick 1 kept no output; no such tick is a 404.
    assert c.get("/api/ticks/1/transcript").json()["status"] == "no_log"
    missing = c.get("/api/ticks/99/transcript")
    assert (missing.status_code, missing.json()["detail"]) == (404, "no tick 99")
