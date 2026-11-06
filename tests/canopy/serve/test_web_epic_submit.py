"""The operator's epics submitted through the web UI (DESIGN §43, TRUST_MODEL T1).

A submission writes through the function `canopy epic submit` calls, with channel `web`, and its guards refuse it as
they refuse the CLI's: inside a tick or a run, and, in a workspace of several repositories, for naming none. Each
carries the submission id its form drew, so a retry records no second epic.
"""

import pytest

from canopy.core import epics
from canopy.core.context import Context
from canopy.serve.backend import Backend
from tests.canopy.helpers import in_run, in_tick
from tests.canopy.web_helpers import refused, signed_in_client, signed_in_to

GOAL = "Let a user sign in on every app with one account, and sign out of all of them at once."
#: The submission id a form drew when it was rendered.
SUBMISSION = "4b1f0c2e-9a7d-4e55-8c1b-2f3a6d7e8f90"


def test_an_epic_submitted_from_the_web_is_queued_for_its_plan_run_as_the_operators(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    body = {
        "text": f"  {GOAL}  ",
        "repos": ["web", "api", "web"],
        "project": "ABC",
        "tracker_epic": "ABC-90",
        "submission": SUBMISSION,
    }
    before = [e["id"] for e in c.get("/api/epics").json()]
    # A write needs the session's token, as every write does: refused without it, it records nothing.
    assert c.post("/api/epics", json=body).status_code == 403
    assert [e["id"] for e in c.get("/api/epics").json()] == before

    submitted = c.post("/api/epics", json=body, headers=headers).json()
    # Each repository once, in the order named, as the CLI records them.
    assert submitted["repos"] == ["web", "api"]
    epic_id = submitted["id"]
    with backend.open() as ctx:
        found = epics.get(ctx.conn, epic_id)
    assert found is not None
    assert (found.text, found.project, found.tracker_epic, found.channel) == (GOAL, "ABC", "ABC-90", "web")
    # The list has it first, its plan run to come; its page has no plan and no run yet.
    [first, *rest] = c.get("/api/epics").json()
    assert (first["id"], first["standing"], first["repos"]) == (epic_id, "queued", ["web", "api"])
    assert [e["id"] for e in rest] == before
    detail = c.get(f"/api/epics/{epic_id}").json()
    assert (detail["plan"], detail["runs"], detail["outline"]) == (None, [], None)


def test_a_workspace_of_several_repositories_refuses_an_epic_that_names_none(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    before = c.get("/api/epics").json()
    said = refused(c.post("/api/epics", json={"text": GOAL, "repos": [], "submission": SUBMISSION}, headers=headers))
    assert said == "unknown_repo: --repo is required: name each repository its plan reads (api, mobile, web)"
    assert c.get("/api/epics").json() == before


def test_a_workspace_of_one_repository_reads_it_when_none_is_named(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    submitted = c.post("/api/epics", json={"text": GOAL, "repos": [], "submission": SUBMISSION}, headers=headers).json()
    assert submitted == {"id": 1, "repos": ["repo"]}
    [found] = epics.every(ctx.conn)
    assert (found.project, found.tracker_epic, found.channel) == (None, None, "web")


def test_a_retried_submission_records_no_second_epic(ctx: Context) -> None:
    """A retry whose first try was recorded, its answer lost, is answered with that epic, and records nothing new."""
    c, headers = signed_in_client(ctx)
    body: dict[str, object] = {"text": GOAL, "repos": [], "submission": SUBMISSION}
    first = c.post("/api/epics", json=body, headers=headers).json()
    # Answered with the epic recorded, though the retry's text and keys would be refused now: they are not read again.
    retried = c.post("/api/epics", json={**body, "text": " ", "project": "a b"}, headers=headers).json()
    assert retried == first == {"id": 1, "repos": ["repo"]}
    [found] = epics.every(ctx.conn)
    assert (found.text, found.project, found.submission) == (GOAL, None, SUBMISSION)
    # The same goal from a form drawn anew is an epic of its own, as the operator may mean it.
    again = c.post("/api/epics", json={**body, "submission": "another-submission"}, headers=headers).json()
    assert again == {"id": 2, "repos": ["repo"]}
    # A retry is still the operator's word: refused inside a run, as any submission is.
    with in_run(7):
        assert refused(c.post("/api/epics", json=body, headers=headers)).startswith("inside_run")


def test_a_submission_without_its_id_is_not_recorded(ctx: Context) -> None:
    """The form's id is required, and held to the form a reply's is."""
    c, headers = signed_in_client(ctx)
    for submission in (None, "short", "not an id!"):
        body: dict[str, object] = {"text": GOAL, "repos": [], "submission": submission}
        assert c.post("/api/epics", json=body, headers=headers).status_code == 422
    assert epics.every(ctx.conn) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({"text": "   "}, "bad_body: the epic's text is empty"),
        ({"text": "x" * (epics.MAX_TEXT + 1)}, "bad_body"),
        ({"text": GOAL, "repos": ["shop"]}, "unknown_repo: 'shop' is not a repository in this workspace"),
        ({"text": GOAL, "project": "a b"}, "bad_key: 'a b' is not --project"),
        ({"text": GOAL, "tracker_epic": "ABC 90"}, "bad_key: 'ABC 90' is not --tracker-epic"),
    ],
)
def test_a_submission_canopy_cannot_use_is_refused_as_the_cli_refuses_it(
    ctx: Context,
    body: dict[str, str],
    said: str,
) -> None:
    c, headers = signed_in_client(ctx)
    sent: dict[str, object] = {"repos": [], "submission": SUBMISSION, **body}
    assert refused(c.post("/api/epics", json=sent, headers=headers)).startswith(said)
    assert epics.every(ctx.conn) == []


def test_a_submission_is_refused_inside_a_tick_or_a_run(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    body: dict[str, object] = {"text": GOAL, "repos": [], "submission": SUBMISSION}
    with in_run(7):
        assert refused(c.post("/api/epics", json=body, headers=headers)).startswith("inside_run")
    with in_tick(ctx.conn):
        assert refused(c.post("/api/epics", json=body, headers=headers)).startswith("inside_run")
    assert epics.every(ctx.conn) == []
