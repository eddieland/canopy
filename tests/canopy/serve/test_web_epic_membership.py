"""A member ticket's epic on its pages (DESIGN §43): its membership, and the epic plan each of its plans follows.

A ticket's detail names the epic it is a member of and the entries it fulfils, as its planner meets them, an entry a
later approval dropped set apart; a ticket of no epic has none. Each of its plans names the approved epic plan its
planner read, by the hash it was approved by, and when a newer one has been approved since.
"""

from datetime import datetime

from canopy.core import db, epics
from canopy.serve.backend import Backend
from canopy.serve.mock import epics as mock_epics
from tests.canopy.helpers import present
from tests.canopy.web_helpers import replan_epic, signed_in_to

APPROVED, HELD = mock_epics.APPROVED, mock_epics.HELD


def test_a_member_names_its_epic_and_entries_and_its_plan_the_epic_plan_it_follows(backend: Backend) -> None:
    c, _ = signed_in_to(backend)
    with backend.open() as ctx:
        # Its planner read the epic's first approved plan; the operator approved a second since.
        followed, newer = epics.plans_of(ctx.conn, APPROVED)
    membership = c.get("/api/tickets/ABC-103").json()["membership"]
    assert {k: membership[k] for k in ("epic_id", "entries", "dropped")} == {
        "epic_id": APPROVED,
        "entries": ["B1"],
        "dropped": [],
    }
    plans = c.get("/api/tickets/ABC-103/plans").json()
    epic_plan = {
        "epic_id": APPROVED,
        "plan_id": followed.id,
        "sha256": followed.approved_sha256,
        "approved_at": followed.approved_at,
        "newer_approved_at": newer.approved_at,
    }
    assert _timed(plans["newest"]["plan"]["epic_plan"]) == epic_plan
    assert [_timed(p["epic_plan"]) for p in plans["plans"]] == [epic_plan]
    # With a branch, it is only told of the change: nothing holds its work.
    assert plans["newest"]["epic_changed"] == []


def test_a_held_members_plan_names_the_ids_that_hold_its_implement_until_approved_again(backend: Backend) -> None:
    """The plan page and the epic's board read the dispatch guard's own test, so neither says more than it refuses."""
    c, headers = signed_in_to(backend)
    plans = c.get(f"/api/tickets/{HELD}/plans").json()
    assert (plans["newest"]["plan"]["status"], plans["newest"]["epic_changed"]) == ("approved", ["C1"])
    members = {m["key"]: m for m in c.get(f"/api/epics/{APPROVED}").json()["members"]}
    assert members[HELD]["epic_changed"] == ["C1"]
    [item] = [i for i in c.get("/api/attention").json() if i["reason"] == "epic_changed"]
    assert item["ticket_key"] == HELD
    assert item["detail"].startswith(f"epic:{APPROVED}'s plan changed C1 since you approved plan ")

    # Approving it again, as its file stands, is the operator's word that it still fits.
    approval = c.post(f"/api/tickets/{HELD}/plan", json={"action": "approve"}, headers=headers)
    assert approval.status_code == 200, approval.text
    assert c.get(f"/api/tickets/{HELD}/plans").json()["newest"]["epic_changed"] == []
    members = {m["key"]: m for m in c.get(f"/api/epics/{APPROVED}").json()["members"]}
    assert members[HELD]["epic_changed"] == []


def test_a_member_of_no_entry_names_its_epic_alone(backend: Backend) -> None:
    c, _ = signed_in_to(backend)
    membership = c.get("/api/tickets/ABC-100").json()["membership"]
    assert (membership["epic_id"], membership["entries"], membership["dropped"]) == (APPROVED, [], [])


def test_a_ticket_of_no_epic_and_its_plans_name_none(backend: Backend) -> None:
    c, _ = signed_in_to(backend)
    assert c.get("/api/tickets/ABC-105").json()["membership"] is None
    plans = c.get("/api/tickets/ABC-105/plans").json()
    assert [p["epic_plan"] for p in plans["plans"]] == [None, None]


def test_a_plan_written_against_an_older_epic_plan_says_a_newer_one_was_approved(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    with backend.open() as ctx:
        followed = epics.plans_of(ctx.conn, APPROVED)[0]
        old = present(epics.approved_plan(ctx.conn, APPROVED))
        text = epics.plan_path(ctx.state_dir, APPROVED, old.run_id).read_text()
        # The next plan drops B2, which nothing else waited on: ABC-104 was registered against it.
        replan_epic(ctx, APPROVED, text[: text.index("### B2.")] + text[text.index("### B3.") :])
    sha256 = c.get(f"/api/epics/{APPROVED}/plans").json()["plans"][-1]["sha256"]
    approval = c.post(f"/api/epics/{APPROVED}/plan/approval", json={"read_sha256": sha256}, headers=headers)
    assert approval.status_code == 200, approval.text
    with backend.open() as ctx:
        newer = present(epics.approved_plan(ctx.conn, APPROVED))
    assert newer.id != old.id

    # ABC-103's plan still names the plan its planner read, and says a newer one was approved since.
    epic_plan = _timed(c.get("/api/tickets/ABC-103/plans").json()["newest"]["plan"]["epic_plan"])
    assert (epic_plan["plan_id"], epic_plan["sha256"]) == (followed.id, followed.approved_sha256)
    assert (epic_plan["approved_at"], epic_plan["newer_approved_at"]) == (followed.approved_at, newer.approved_at)
    # B1 is still the newer plan's; B2 is not, so ABC-104 is a member of the entries left, none.
    assert c.get("/api/tickets/ABC-103").json()["membership"]["entries"] == ["B1"]
    membership = c.get("/api/tickets/ABC-104").json()["membership"]
    assert (membership["entries"], membership["dropped"]) == ([], ["B2"])


def _timed(epic_plan: dict[str, object]) -> dict[str, object]:
    """Return `epic_plan` as the API sent it, its times in the journal's own format, to compare with its rows."""
    return {
        k: db.format_time(datetime.fromisoformat(v)) if k.endswith("_at") and isinstance(v, str) else v
        for k, v in epic_plan.items()
    }
