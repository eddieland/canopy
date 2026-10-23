"""The mock journal's feedback plans (DESIGN §32): each state a plan has, each on a PR's page of its own."""

from canopy.core import db
from canopy.serve.backend import Backend
from canopy.serve.mock import feedback_plans
from canopy.serve.mock.reviews import PR_88
from tests.canopy.web_helpers import client


def test_each_state_s_pr_shows_its_plan_in_that_state(backend: Backend) -> None:
    """The stale plan is PR 88's; each other state is on a mobile PR of its own, its ticket's one."""
    c = client(None, backend)
    urls = {"stale": PR_88, **{name: s.url for name, s in feedback_plans.STATES.items()}}
    shown = {}
    for name, url in urls.items():
        assert c.get("/api/pull-request", params={"url": url}).status_code == 200
        shown[name] = c.get("/api/pull-request/threads", params={"url": url}).json()["feedback_plan"]
    assert {name: plan["status"] for name, plan in shown.items()} == {
        "stale": "stale",
        "waiting": "waiting",
        "approved": "approved",
        "approved-by-planner": "approved",
        "spent": "spent",
        "no-items": "waiting",
        "missing": "waiting",
        "many-items": "waiting",
    }
    assert len({plan["ticket_key"] for plan in shown.values()}) == len(shown)
    assert shown["waiting"]["changes"] == []
    # The operator left frank's question out, and their approval's message names it so.
    approved = shown["approved"]
    assert [i["left_out"] for i in approved["items"]] == [False, False, True]
    assert (approved["approved_channel"], approved["approved_reason"]) == ("web", None)
    assert approved["approved_message"] is not None
    planner = shown["approved-by-planner"]
    assert (planner["approved_channel"], planner["approved_message"]) == ("planner", None)
    assert planner["approved_reason"]
    assert {i["proposal"] for i in planner["items"]} <= {"decline", "ask", "leave"}
    assert shown["spent"]["spent_run"] == feedback_plans.STATES["spent"].run + 1
    assert (shown["no-items"]["items"], shown["no-items"]["text"]) == ([], feedback_plans.STATES["no-items"].text)
    assert (shown["missing"]["text"], shown["missing"]["problem"]) == (None, "missing")
    many = shown["many-items"]["items"]
    assert len(many) == 10
    assert {i["item"] for i in many} == {"review", "comment"}
    assert feedback_plans.LONG_AUTHOR in {i["author"] for i in many}
    assert any(i["trusted"] for i in many)


def test_the_states_are_older_than_the_spend_page_s_week(backend: Backend) -> None:
    """So the spend page's default week, and the counts of what happened lately, are as they were without them."""
    with backend.open() as ctx:
        for state in feedback_plans.STATES.values():
            row = db.get_run(ctx.conn, state.run)
            assert row is not None
            assert (backend.clock() - db.parse_time(str(row["ended_at"]))).days >= 8
