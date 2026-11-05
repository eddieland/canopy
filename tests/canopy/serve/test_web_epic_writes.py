"""The operator's word on an epic's plan through the web UI (DESIGN §43, TRUST_MODEL T1).

Approving and asking for changes write through the functions `canopy plan epic:N --approve` and `canopy reply epic:N`
call, with channel `web`, and their guards refuse them as they refuse the CLI's. An approval names the file's hash as
the page read it, so a file changed since is refused rather than approved unseen.
"""

from pathlib import Path

from canopy.core import epics
from canopy.core.vocab import PlanStatus
from canopy.serve.backend import Backend
from canopy.serve.mock import epics as mock_epics
from tests.canopy.helpers import in_run, present
from tests.canopy.web_helpers import refused, replan_epic, signed_in_to, start_epic_run

APPROVED, PROPOSED, PLANNING = mock_epics.APPROVED, mock_epics.PROPOSED, mock_epics.PLANNING
#: A reply's form, with the submission id it drew.
REPLY = {"body": "Say how the copy is cleared when the app is offline at sign-out.", "submission": "form-0001"}


def test_the_mock_epics_plan_is_approved_from_the_web_and_its_breakdown_is_the_boards(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    read = c.get(f"/api/epics/{PROPOSED}/plans").json()["plans"][-1]
    route = f"/api/epics/{PROPOSED}/plan/approval"
    # A write needs the session's token, as every write does.
    assert c.post(route, json={"read_sha256": read["sha256"]}).status_code == 403

    approved = c.post(route, json={"read_sha256": read["sha256"]}, headers=headers)
    # Its first approved plan: nothing to compare it with.
    assert approved.json() == {"plan": read["plan"]["id"], "run_id": read["plan"]["run_id"], "change": None}
    found = c.get(f"/api/epics/{PROPOSED}").json()
    assert (found["epic"]["standing"], found["plan"]["status"], found["plan"]["approved_channel"]) == (
        "approved",
        "approved",
        "web",
    )
    assert (found["outline"]["source"], [e["id"] for e in found["outline"]["entries"]]) == (
        "approved",
        ["B1", "B2", "B3"],
    )
    # Approved once: approving it again finds no plan waiting.
    again = c.post(route, json={"read_sha256": read["sha256"]}, headers=headers)
    assert refused(again) == f"no_plan: no plan of epic:{PROPOSED} waits on you; reply to it to ask for one"


def test_a_re_approval_says_the_ids_it_added_removed_and_changed(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    with backend.open() as ctx:
        old = present(epics.current_plan(ctx.conn, APPROVED))
        text = epics.plan_path(ctx.state_dir, APPROVED, old.run_id).read_text()
        start, end = text.index("### B2."), text.index("### B3.")
        # B2 dropped, R1 reworded, and a requirement it never had: nothing else waited on B2.
        new = (text[:start] + text[end:]).replace("- **R1.** ", "- **R1.** Reworded: ")
        new = new.replace("## Contracts", "- **R4.** A fourth requirement.\n\n## Contracts")
        replan_epic(ctx, APPROVED, new)
    read = c.get(f"/api/epics/{APPROVED}/plans").json()["plans"][-1]
    approved = c.post(f"/api/epics/{APPROVED}/plan/approval", json={"read_sha256": read["sha256"]}, headers=headers)
    assert approved.json()["change"] == {"added": ["R4"], "removed": ["B2"], "changed": ["R1"]}


def test_a_plan_file_changed_since_the_page_read_it_is_refused_not_approved_unseen(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    read = c.get(f"/api/epics/{PROPOSED}/plans").json()["plans"][-1]
    path = Path(read["path"])
    path.write_text(f"{path.read_text()}\nAn edit the page never saw.\n")
    said = refused(
        c.post(f"/api/epics/{PROPOSED}/plan/approval", json={"read_sha256": read["sha256"]}, headers=headers),
    )
    assert said == f"stale: epic:{PROPOSED}'s plan file changed since you read it; read it again to approve it"
    with backend.open() as ctx:
        assert present(epics.current_plan(ctx.conn, PROPOSED)).status is PlanStatus.PROPOSED


def test_a_plan_whose_ids_will_not_read_or_reuse_a_dropped_one_is_refused_naming_its_guard(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    path = Path(c.get(f"/api/epics/{PROPOSED}/plans").json()["plans"][-1]["path"])
    path.write_text(path.read_text().replace("- **R2.**", "- **R1.**"))
    sha256 = c.get(f"/api/epics/{PROPOSED}/plans").json()["plans"][-1]["sha256"]
    said = refused(c.post(f"/api/epics/{PROPOSED}/plan/approval", json={"read_sha256": sha256}, headers=headers))
    assert said == f"bad_outline: epic:{PROPOSED}'s plan cannot be read: R1 appears twice"

    # Epic 1's next plan drops B4, and the one after brings it back.
    with backend.open() as ctx:
        old = present(epics.current_plan(ctx.conn, APPROVED))
        text = epics.plan_path(ctx.state_dir, APPROVED, old.run_id).read_text()
        replan_epic(ctx, APPROVED, text[: text.index("### B4.")] + text[text.index("## Decisions") :])
    route = f"/api/epics/{APPROVED}/plan/approval"
    sha256 = c.get(f"/api/epics/{APPROVED}/plans").json()["plans"][-1]["sha256"]
    assert c.post(route, json={"read_sha256": sha256}, headers=headers).json()["change"]["removed"] == ["B4"]
    with backend.open() as ctx:
        replan_epic(ctx, APPROVED, text)
    sha256 = c.get(f"/api/epics/{APPROVED}/plans").json()["plans"][-1]["sha256"]
    assert refused(c.post(route, json={"read_sha256": sha256}, headers=headers)).startswith(
        "reused_id: the plan uses B4, which an earlier approved plan dropped",
    )


def test_an_approval_is_refused_while_a_plan_run_works_and_with_no_plan(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    body = {"read_sha256": "0" * 64}
    assert refused(c.post(f"/api/epics/{PLANNING}/plan/approval", json=body, headers=headers)).startswith("planning:")
    assert (
        refused(c.post("/api/epics/99/plan/approval", json=body, headers=headers))
        == "unknown_epic: canopy has no epic:99"
    )
    assert c.post(f"/api/epics/{PROPOSED}/plan/approval", json={"read_sha256": "x"}, headers=headers).status_code == 422


def test_asking_for_changes_is_a_reply_and_says_what_starts_the_next_plan_run(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    route = f"/api/epics/{PROPOSED}/replies"
    first = c.post(route, json=REPLY, headers=headers).json()
    # Two plan runs of at most three: the next tick starts the third, which reads the reply.
    assert {k: v for k, v in first.items() if k != "message_id"} == {
        "new": True,
        "running_run": None,
        "plan_runs": 2,
        "max_plan_attempts": 3,
    }
    # A retry records nothing new.
    assert c.post(route, json=REPLY, headers=headers).json() == {**first, "new": False}
    # The plan's page says so, until a run takes it.
    assert c.get(f"/api/epics/{PROPOSED}/plans").json()["changes_asked"] is not None
    with backend.open() as ctx:
        [_, reply] = epics.messages_of(ctx.conn, PROPOSED)
        assert (reply.id, reply.channel, reply.body) == (first["message_id"], "web", REPLY["body"])
        # The plan still waits: an approval before the next run starts is the operator's later word.
        assert present(epics.current_plan(ctx.conn, PROPOSED)).status is PlanStatus.PROPOSED
        run_id = start_epic_run(ctx, PROPOSED)
    working = c.post(route, json={**REPLY, "submission": "form-0002"}, headers=headers).json()
    assert (working["running_run"], working["plan_runs"]) == (run_id, 3)
    assert c.get(f"/api/epics/{PROPOSED}/plans").json()["changes_asked"] is None
    assert refused(c.post(route, json={**REPLY, "body": " "}, headers=headers)) == "bad_body: the reply is empty"
    assert refused(c.post("/api/epics/99/replies", json=REPLY, headers=headers)) == "unknown: canopy has no epic:99"


def test_both_writes_are_refused_inside_a_run(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    sha256 = c.get(f"/api/epics/{PROPOSED}/plans").json()["plans"][-1]["sha256"]
    with in_run(7):
        approval = c.post(f"/api/epics/{PROPOSED}/plan/approval", json={"read_sha256": sha256}, headers=headers)
        assert refused(approval).startswith("inside_run")
        assert refused(c.post(f"/api/epics/{PROPOSED}/replies", json=REPLY, headers=headers)).startswith("inside_run")
    with backend.open() as ctx:
        assert present(epics.current_plan(ctx.conn, PROPOSED)).status is PlanStatus.PROPOSED
        assert len(epics.messages_of(ctx.conn, PROPOSED)) == 1
