"""The web UI's epics (DESIGN §43): the list, an epic's page with its breakdown, and its plans.

What `canopy epic list` and `canopy show epic:N` print, the outline read by the CLI's own readers: the approved plan's,
or, while none is approved, the proposed one's, and a plan that will not read served as its problem, never in part.
"""

from canopy.core import conversation, db, epics, records
from canopy.core.vocab import RunStatus
from canopy.serve.backend import Backend
from canopy.serve.mock import epics as mock_epics
from tests.canopy.helpers import present
from tests.canopy.web_helpers import client, replan_epic, start_epic_run

APPROVED, PROPOSED, PLANNING = mock_epics.APPROVED, mock_epics.PROPOSED, mock_epics.PLANNING


def test_the_mock_epics_are_listed_newest_first_each_where_it_stands(backend: Backend) -> None:
    listed = client(None, backend).get("/api/epics").json()
    assert [(e["id"], e["standing"]) for e in listed] == [
        (PLANNING, "planning"),
        (PROPOSED, "proposed"),
        (APPROVED, "approved"),
    ]
    planning, proposed, approved = listed
    assert (planning["repos"], planning["members"], planning["entries"]) == (["api", "web"], 0, None)
    # A proposed plan's breakdown is counted; no member is registered against one.
    assert (proposed["entries"], proposed["entries_with_members"]) == (3, 0)
    assert (approved["repos"], approved["project"], approved["members"]) == (["api", "web", "mobile"], "ABC", 3)
    assert (approved["entries"], approved["entries_with_members"]) == (4, 2)


def test_an_approved_epic_leads_with_its_breakdown_beside_its_members(backend: Backend) -> None:
    found = client(None, backend).get(f"/api/epics/{APPROVED}").json()
    assert (found["bound"], found["max_plan_attempts"]) == (8, 3)
    assert found["plan"]["status"] == "approved"
    outline = found["outline"]
    assert (outline["source"], outline["problem"], outline["plan_id"]) == ("approved", None, found["plan"]["id"])
    assert [r["id"] for r in outline["requirements"]] == ["R1", "R2", "R3"]
    assert [c["id"] for c in outline["contracts"]] == ["C1"]
    entries = {e["id"]: e for e in outline["entries"]}
    assert {i: e["members"] for i, e in entries.items()} == {"B1": ["ABC-103"], "B2": ["ABC-104"], "B3": [], "B4": []}
    assert (entries["B2"]["uses"], entries["B2"]["repos"], entries["B2"]["after"]) == (
        ["C1"],
        ["mobile", "web"],
        ["B1"],
    )
    assert entries["B4"]["trivial"] is not None
    assert all(e["trivial"] is None for i, e in entries.items() if i != "B4")
    members = {m["key"]: m for m in found["members"]}
    assert list(members) == ["ABC-103", "ABC-104", "ABC-100"]
    # One with a PR, one running, one registered against no entry.
    assert (members["ABC-103"]["entries"], members["ABC-103"]["prs"]) == (
        ["B1"],
        ["https://github.com/acme/web/pull/91"],
    )
    assert (members["ABC-104"]["entries"], members["ABC-104"]["latest_run"]["state"]) == (["B2"], "running")
    assert (members["ABC-100"]["entries"], members["ABC-100"]["dropped"]) == ([], [])
    assert members["ABC-103"]["phase"] == "review_pending"
    assert [r["plan_id"] for r in found["runs"]] == [outline["plan_id"]]


def test_a_proposed_epic_shows_its_plan_marked_proposed_and_the_reply_it_answers(backend: Backend) -> None:
    found = client(None, backend).get(f"/api/epics/{PROPOSED}").json()
    assert found["plan"]["status"] == "proposed"
    assert (found["outline"]["source"], [e["id"] for e in found["outline"]["entries"]]) == (
        "proposed",
        ["B1", "B2", "B3"],
    )
    [reply] = found["messages"]
    assert (reply["source"], reply["kind"]) == ("operator", "reply")
    first, second = found["runs"]
    # The reply came between them: the second wrote the plan that waits.
    assert first["ended_at"] < reply["at"] < second["started_at"]
    assert second["plan_id"] == found["plan"]["id"]


def test_a_just_submitted_epic_has_its_plan_run_working_and_no_plan(backend: Backend) -> None:
    found = client(None, backend).get(f"/api/epics/{PLANNING}").json()
    assert (found["plan"], found["outline"], found["members"]) == (None, None, [])
    [run] = found["runs"]
    assert (run["state"], run["ended_at"], run["plan_id"]) == ("running", None, None)


def test_an_epics_plans_are_each_as_its_file_stands(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get(f"/api/epics/{PROPOSED}/plans").json()
    # Its reply was read by the run that wrote the plan that waits: no changes are asked of it.
    assert (found["planning"], found["changes_asked"]) == (None, None)
    assert [p["plan"]["status"] for p in found["plans"]] == ["superseded", "proposed"]
    assert all(p["text"].startswith("# Offline order history") and not p["edited"] for p in found["plans"])
    assert c.get(f"/api/epics/{PLANNING}/plans").json() == {
        "epic_id": PLANNING,
        "planning": 4,
        "plans": [],
        "changes_asked": None,
    }

    # An approved plan's file edited since: canopy still reads the copy the operator approved.
    with backend.open() as ctx:
        plan = present(epics.current_plan(ctx.conn, APPROVED))
        path = epics.plan_path(ctx.state_dir, APPROVED, plan.run_id)
    path.write_text(f"{path.read_text()}\nAn edit after the approval.\n")
    [approved] = c.get(f"/api/epics/{APPROVED}/plans").json()["plans"]
    assert (approved["edited"], approved["changed_since_approval"]) == (True, True)
    assert c.get(f"/api/epics/{APPROVED}").json()["outline"]["problem"] is None


def test_a_plan_whose_ids_repeat_is_served_as_its_problem_never_half_a_map(backend: Backend) -> None:
    c = client(None, backend)
    with backend.open() as ctx:
        plan = present(epics.current_plan(ctx.conn, PROPOSED))
        path = epics.plan_path(ctx.state_dir, PROPOSED, plan.run_id)
    # The operator's edit before approving, which repeats an id.
    path.write_text(path.read_text().replace("- **R2.**", "- **R1.**"))
    outline = c.get(f"/api/epics/{PROPOSED}").json()["outline"]
    assert (outline["source"], outline["problem"]) == ("proposed", "R1 appears twice")
    assert (outline["requirements"], outline["contracts"], outline["entries"]) == ([], [], [])
    listed = next(e for e in c.get("/api/epics").json() if e["id"] == PROPOSED)
    assert listed["entries"] is None

    path.unlink()
    assert c.get(f"/api/epics/{PROPOSED}").json()["outline"]["problem"] == "its file is missing"


def test_an_approved_copy_changed_since_is_its_problem_and_keeps_every_registration(backend: Backend) -> None:
    c = client(None, backend)
    with backend.open() as ctx:
        plan = present(epics.current_plan(ctx.conn, APPROVED))
        copy = epics.approved_path(ctx.state_dir, APPROVED, plan.run_id, present(plan.approved_sha256))
    copy.write_text(copy.read_text().replace("Retire", "Keep"))
    found = c.get(f"/api/epics/{APPROVED}").json()
    assert "is not the plan approved by run 1" in found["outline"]["problem"]
    assert found["outline"]["entries"] == []
    assert {m["key"]: m["entries"] for m in found["members"]} == {"ABC-103": ["B1"], "ABC-104": ["B2"], "ABC-100": []}


def test_a_member_whose_entry_a_later_approval_dropped_comes_back_as_such(backend: Backend) -> None:
    with backend.open() as ctx:
        old = present(epics.current_plan(ctx.conn, APPROVED))
        text = epics.plan_path(ctx.state_dir, APPROVED, old.run_id).read_text()
        # The next plan drops B2, its retries, and B4's wait on it with it.
        start, end = text.index("### B2."), text.index("### B3.")
        replan_epic(ctx, APPROVED, text[:start] + text[end:])
        epics.approve(
            ctx.conn,
            ctx.state_dir,
            APPROVED,
            repos=frozenset(epics.repos_of(ctx.conn, APPROVED)),
            channel="web",
        )
    found = client(None, backend).get(f"/api/epics/{APPROVED}").json()
    members = {m["key"]: (m["entries"], m["dropped"]) for m in found["members"]}
    assert members == {"ABC-103": (["B1"], []), "ABC-104": ([], ["B2"]), "ABC-100": ([], [])}
    assert [e["id"] for e in found["outline"]["entries"]] == ["B1", "B3", "B4"]
    assert (found["epic"]["entries"], found["epic"]["entries_with_members"]) == (3, 1)


def test_an_epic_waits_for_a_run_then_for_a_reply_once_its_run_wrote_no_plan(backend: Backend) -> None:
    c = client(None, backend)
    with backend.open() as ctx:
        epic = epics.submit(
            ctx.conn,
            ctx.workspace,
            "Plan the\x07 move.",
            repos=["web"],
            project=None,
            tracker_epic=None,
            channel="web",
        )
    [listed, *_] = c.get("/api/epics").json()
    assert (listed["id"], listed["standing"], listed["text"]) == (epic.id, "queued", "Plan the  move.")

    with backend.open() as ctx:
        run_id = start_epic_run(ctx, epic.id)
        records.update(records.EpicRun).set(
            status=RunStatus.UNKNOWN,
            ended_at=db.now(),
            result_json='{"harness": "its plan\'s ids cannot be read"}',
        ).where("id = ?", run_id).run(ctx.conn)
    [listed, *_] = c.get("/api/epics").json()
    assert listed["standing"] == "unplanned"
    [run] = c.get(f"/api/epics/{epic.id}").json()["runs"]
    assert (run["state"], run["summary"]) == ("failed", "its plan's ids cannot be read")

    with backend.open() as ctx:
        conversation.reply(ctx.conn, conversation.parse_ref(f"epic:{epic.id}"), "Try again.", channel="web")
    [listed, *_] = c.get("/api/epics").json()
    assert listed["standing"] == "queued"


def test_an_unknown_epic_is_a_404(backend: Backend) -> None:
    c = client(None, backend)
    assert c.get("/api/epics/99").status_code == 404
    assert c.get("/api/epics/99/plans").status_code == 404
