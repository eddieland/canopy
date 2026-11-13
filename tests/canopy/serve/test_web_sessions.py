"""The runtime's sessions in the web UI (DESIGN §13, ROADMAP M72): the Sessions page's list and the search's panels."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from canopy.core import db, records, runtime_sessions, session_list
from canopy.infra import resources
from canopy.runtime.report import SessionPage, SessionSpend
from canopy.serve.mock import T0
from canopy.serve.mock import sessions as mock_sessions
from tests.canopy.helpers import context
from tests.canopy.web_helpers import client, signed_in_client

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.serve.backend import Backend
    from tests.conftest import CanopyEnv


def titles(found: list[dict[str, Any]]) -> list[object]:
    """Each session's title, with its subagents' under it."""
    return [(s["title"], titles(s["subagents"])) if s["subagents"] else s["title"] for s in found]


def test_the_list_opens_on_the_sessions_outside_canopy_each_with_the_command_that_reopens_it(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/sessions").json()
    assert (found["search"], found["whose"], found["words"], found["more"]) == ("titles", "outside", [], False)
    # Newest first, the deploy question's subagent under it; the archived one and the client's left out.
    assert titles(found["sessions"]) == [
        ("Why does the deploy script hang on staging?", ["Find where deploy.sh waits on the health check"]),
        "Outline the Q4 planning doc",
        "XYZ-12 implement: Rate-limit the export endpoint",
        "Bisect the flaky checkout test",
    ]
    deploy = found["sessions"][0]
    assert (deploy["directory"], deploy["cost_usd"], deploy["made_by"]) == ("/home/op/acme/infra", 0.84, None)
    assert deploy["reopen"] == f"cd /home/op/acme/infra && opencode --session {mock_sessions.DEPLOY}"
    assert deploy["subagents"][0]["parent_id"] == mock_sessions.DEPLOY
    assert found["progress"] == {
        "status": "found",
        "read_at": "2026-10-08T12:08:00Z",
        "error": None,
        "through": "2026-10-08T12:06:00Z",
        "current": True,
    }
    # The archived one when asked for, never the client's.
    archived = c.get("/api/sessions", params={"archived": True}).json()["sessions"]
    assert [(s["title"], s["archived"]) for s in archived if s["archived"]] == [("Try the new router's loaders", True)]
    assert not any(s["directory"] == mock_sessions.EXCLUDED for s in archived)


def test_a_list_narrowed_to_a_directory_holds_its_sessions_alone_and_never_an_excluded_ones(
    backend: Backend,
) -> None:
    c = client(None, backend)
    infra = c.get("/api/sessions", params={"directory": "/home/op/acme/infra"}).json()
    assert (titles(infra["sessions"]), infra["more"]) == (
        [("Why does the deploy script hang on staging?", ["Find where deploy.sh waits on the health check"])],
        False,
    )
    # Exactly that directory, not the one above it; found by words within it too.
    assert c.get("/api/sessions", params={"directory": "/home/op/acme"}).json()["sessions"] == []
    found = c.get("/api/sessions", params={"directory": "/home/op/src/web-experiments", "q": "flaky"}).json()
    assert titles(found["sessions"]) == ["Bisect the flaky checkout test"]
    # The client's directory, which sessions.exclude names, lists nothing, however asked.
    asked: list[dict[str, str | bool]] = [{}, {"archived": True}, {"q": "globex"}, {"whose": "canopy"}]
    for params in asked:
        excluded = c.get("/api/sessions", params={"directory": mock_sessions.EXCLUDED, **params}).json()
        assert excluded["sessions"] == []
    assert c.get("/api/sessions", params={"directory": ""}).status_code == 422


def test_canopys_sessions_each_name_the_run_that_made_them_and_the_page_it_opens(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/sessions", params={"whose": "canopy", "limit": session_list.MAX_LISTED}).json()
    assert not found["more"]
    made = {s["session_id"]: s["made_by"] for s in found["sessions"]}
    assert all(s["reopen"] is None for s in found["sessions"])
    assert made["ses_tick2"] == {
        "kind": "tick",
        "id": 2,
        "ticket_key": None,
        "chore": None,
        "task_id": None,
        "epic_id": None,
    }
    assert (made["ses_mock41"]["kind"], made["ses_mock41"]["id"], made["ses_mock41"]["ticket_key"]) == (
        "run",
        41,
        "ABC-101",
    )
    with backend.open() as ctx:
        chore = records.select(records.ChoreRun).where("session_id IS NOT NULL").all(ctx.conn)[0]
        task = records.select(records.TaskRun).where("session_id IS NOT NULL").all(ctx.conn)[0]
        epic = records.select(records.EpicRun).where("session_id IS NOT NULL").all(ctx.conn)[0]
        review = records.select(records.ReviewRun).where("session_id IS NOT NULL").all(ctx.conn)[0]
    assert (made[chore.session_id]["kind"], made[chore.session_id]["chore"]) == ("chore_run", chore.chore)
    assert (made[task.session_id]["kind"], made[task.session_id]["task_id"]) == ("task_run", task.task_id)
    assert (made[epic.session_id]["kind"], made[epic.session_id]["epic_id"]) == ("epic_run", epic.epic_id)
    assert (made[review.session_id]["kind"], made[review.session_id]["id"]) == ("review", review.id)
    # Run 41's subagent is under its session, named by the run its parent's is.
    [run41] = [s for s in found["sessions"] if s["session_id"] == "ses_mock41"]
    [explore] = run41["subagents"]
    assert (explore["session_id"], explore["made_by"]["id"]) == (mock_sessions.EXPLORE, 41)
    # None of the operator's is among canopy's.
    assert not any(s["session_id"].startswith("ses_op_") for s in found["sessions"])


def test_a_search_finds_the_newest_whose_title_holds_every_word_subagents_among_them(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/sessions", params={"q": "DEPLOY  the"}).json()
    assert found["words"] == ["DEPLOY", "the"]
    # Found flat, newest first, the subagent with the session it ran for named.
    assert [(s["title"], s["parent_id"], s["subagents"]) for s in found["sessions"]] == [
        ("Find where deploy.sh waits on the health check", mock_sessions.DEPLOY, []),
        ("Why does the deploy script hang on staging?", None, []),
    ]
    login = c.get("/api/sessions", params={"q": "login", "whose": "canopy"}).json()["sessions"]
    assert login[0]["title"] == "Explore where the login redirect is decided"
    assert c.get("/api/sessions", params={"q": "login"}).json()["sessions"] == []
    # The client's is found by no word of its title.
    assert c.get("/api/sessions", params={"q": "globex"}).json()["sessions"] == []
    # At most `limit`, saying there are more.
    one = c.get("/api/sessions", params={"q": "the", "limit": 1}).json()
    assert (len(one["sessions"]), one["more"]) == (1, True)


def test_a_query_the_search_would_refuse_is_a_422(backend: Backend) -> None:
    c = client(None, backend)
    assert c.get("/api/sessions", params={"q": "x"}).status_code == 422
    assert c.get("/api/sessions", params={"q": " ".join("abcdefghi")}).status_code == 422
    assert c.get("/api/sessions", params={"whose": "theirs"}).status_code == 422
    assert c.get("/api/sessions", params={"limit": session_list.MAX_LISTED + 1}).status_code == 422


def test_at_off_the_api_serves_no_session_whatever_the_journal_keeps(ctx: Context) -> None:
    """Titles kept before the key was turned off, which the loop's next read drops, are never served meanwhile."""
    kept_titles(ctx)
    c, _ = signed_in_client(ctx)
    found = c.get("/api/sessions").json()
    assert (found["search"], found["sessions"], found["progress"]) == ("off", [], None)
    assert c.get("/api/sessions", params={"q": "notes", "whose": "canopy"}).json()["sessions"] == []


def test_at_titles_a_session_in_the_state_directory_is_canopys_with_no_run(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user("\n[sessions]\nsearch = 'titles'\n")
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    kept_titles(ctx)
    c, _ = signed_in_client(ctx)
    outside = c.get("/api/sessions").json()["sessions"]
    assert [(s["title"], s["made_by"]) for s in outside] == [("My notes", None)]
    canopys = c.get("/api/sessions", params={"whose": "canopy"}).json()["sessions"]
    assert [(s["title"], s["made_by"], s["reopen"]) for s in canopys] == [("A chore's trial", None, None)]


def kept_titles(ctx: Context) -> None:
    """Record two sessions the read kept titles of: the operator's notes, and a chore's trial in the state directory."""
    ms = int(T0.timestamp() * 1000)

    def session(session_id: str, title: str, directory: str) -> SessionSpend:
        return SessionSpend(session_id, None, directory, ms, ms, 0.5, 0, 0, 0, 0, 0, title=title)

    mine = session("ses_mine", "My notes", "/home/me/notes")
    trial = session("ses_trial", "A chore's trial", str((ctx.state_dir / "chores" / "deps").resolve()))
    runtime_sessions.record(
        ctx.conn,
        SessionPage("found", (mine, trial), cursor=(ms, "ses_trial")),
        titles=runtime_sessions.titles_setting([]),
        restarted=True,
    )
