"""The operator's desk on a ticket's page (DESIGN §18): opened and closed as `canopy desk KEY` and `--close` do."""

import os
from pathlib import Path
from unittest import mock

from canopy.runs import checkouts
from canopy.serve import desk_views
from canopy.serve.backend import Backend
from canopy.serve.mock import desks as mock_desks
from tests.canopy.conftest import Ws
from tests.canopy.helpers import KEY, context, pool_statuses
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.canopy.web_helpers import SECRET, client, refused, signed_in, signed_in_client


def test_the_page_opens_a_desk_shows_it_and_closes_it_only_once_its_work_is_on_origin(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    run = ws_scenario.run(dispatches(repo=("api", "web")), worker=pushes(repos=("api", "web")))
    assert run.status == "done", run.printed.out
    c, headers = signed_in_client(context(ws_scenario.env))
    assert c.get(f"/api/tickets/{KEY}").json()["desk"] == {"repos": ["api", "web"], "open": None}

    unmapped = c.post(f"/api/tickets/{KEY}/desk", json={"repos": ["docs"]}, headers=headers)
    assert refused(unmapped) == "unknown_repo: the map lists no repository docs"
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "7"}):
        inside = c.post(f"/api/tickets/{KEY}/desk", json={"repos": []}, headers=headers)
    assert refused(inside).startswith("inside_run: CANOPY_RUN_ID is set")
    assert pool_statuses(treehouse_state) == ["available", "available"]

    opened = c.post(f"/api/tickets/{KEY}/desk", json={"repos": ["web"]}, headers=headers)
    assert opened.status_code == 200, opened.text
    found = checkouts.find(ws.root, KEY)
    assert found is not None
    assert list(found.slots) == ["web"]
    desk = opened.json()["desk"]
    assert opened.json()["already"] is False
    assert desk["path"] == f"{checkouts.DIR}/{KEY}"
    assert desk["workspace_file"] == str(found.workspace_file)
    assert desk["open_command"] == f"code {found.workspace_file}"
    assert desk["slots"] == [{"repo": "web", "path": str(found.slots["web"].relative_to(ws.root))}]
    assert c.get(f"/api/tickets/{KEY}").json()["desk"] == {"repos": ["api", "web"], "open": desk}
    again = c.post(f"/api/tickets/{KEY}/desk", json={"repos": []}, headers=headers)
    assert (again.json()["already"], again.json()["desk"]) == (True, desk)

    # Work origin lacks keeps the desk until the operator discards it, typing the ticket's key.
    (found.slots["web"] / "draft.txt").write_text("mine\n")
    kept = c.post(f"/api/tickets/{KEY}/desk/close", json={}, headers=headers)
    assert refused(kept) == (
        f"unpushed: {KEY}'s desk has work origin lacks: web has 1 uncommitted change. Commit and push it, or discard "
        "it; nothing was returned."
    )
    mistyped = c.post(f"/api/tickets/{KEY}/desk/close", json={"discard": True, "confirm": "PROJ-2"}, headers=headers)
    assert refused(mistyped) == f"not_confirmed: type {KEY} to confirm losing its desk's work"
    assert checkouts.find(ws.root, KEY) is not None
    closed = c.post(f"/api/tickets/{KEY}/desk/close", json={"discard": True, "confirm": KEY}, headers=headers)
    assert closed.json() == {"returned": ["web"]}
    assert checkouts.find(ws.root, KEY) is None
    assert c.get(f"/api/tickets/{KEY}").json()["desk"]["open"] is None
    none = c.post(f"/api/tickets/{KEY}/desk/close", json={}, headers=headers)
    assert none.json() == {"returned": []}


def test_a_ticket_with_no_branch_has_no_desk_to_open(ws_scenario: Scenario) -> None:
    run = ws_scenario.run(dispatches(repo=("api", "web")), worker=pushes(repos=("api", "web")))
    assert run.status == "done", run.printed.out
    c, headers = signed_in_client(context(ws_scenario.env))
    response = c.post("/api/tickets/PROJ-404/desk", json={"repos": []}, headers=headers)
    assert refused(response) == "desk_failed: PROJ-404 has no branch in the journal yet: its first implement names one"


def test_the_editor_link_opens_the_workspace_file_through_wsl_inside_it() -> None:
    file = Path("/home/me/acme/checkouts/ABC-1/ABC-1.code-workspace")
    assert desk_views.editor_url(file, {}) == f"vscode://file{file}"
    assert desk_views.editor_url(file, {desk_views.WSL_DISTRO: "Ubuntu 24.04"}) == (
        f"vscode://vscode-remote/wsl+Ubuntu%2024.04{file}"
    )
    assert desk_views.editor_url(Path("/a b/x.code-workspace"), {}) == "vscode://file/a%20b/x.code-workspace"


def test_the_mock_holds_abc_103_s_desk_on_a_slot_of_web_s_until_it_is_discarded(backend: Backend) -> None:
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)
    desk = c.get(f"/api/tickets/{mock_desks.SEEDED}").json()["desk"]
    assert desk["repos"] == ["web"]
    assert [s["repo"] for s in desk["open"]["slots"]] == ["web"]
    web = next(p for p in c.get("/api/worktrees").json() if p["repo"] == "web")
    held = web["worktrees"][mock_desks.SEEDED_SLOT - 1]
    assert held["note"] == (
        f"held by your desk for {mock_desks.SEEDED}, on its branch; "
        f"`canopy desk {mock_desks.SEEDED} --close` returns it"
    )

    kept = c.post(f"/api/tickets/{mock_desks.SEEDED}/desk/close", json={}, headers=headers)
    assert refused(kept).startswith(
        f"unpushed: {mock_desks.SEEDED}'s desk has work origin lacks: web has 2 uncommitted",
    )
    body = {"discard": True, "confirm": mock_desks.SEEDED}
    closed = c.post(f"/api/tickets/{mock_desks.SEEDED}/desk/close", json=body, headers=headers)
    assert closed.json() == {"returned": ["web"]}
    web = next(p for p in c.get("/api/worktrees").json() if p["repo"] == "web")
    assert web["worktrees"][mock_desks.SEEDED_SLOT - 1]["state"] == "idle"

    # Opened again, on the first idle slot, which holds nothing, so it closes at once; another ticket takes the next.
    reopened = c.post(f"/api/tickets/{mock_desks.SEEDED}/desk", json={"repos": []}, headers=headers)
    assert [s["path"].split("/")[-2] for s in reopened.json()["desk"]["slots"]] == ["4"]
    other = c.post("/api/tickets/ABC-099/desk", json={"repos": []}, headers=headers)
    assert [s["path"].split("/")[-2] for s in other.json()["desk"]["slots"]] == ["6"]
    full = c.post("/api/tickets/ABC-099/desk/close", json={}, headers=headers)
    assert full.json() == {"returned": ["web"]}
    closed = c.post(f"/api/tickets/{mock_desks.SEEDED}/desk/close", json={}, headers=headers)
    assert closed.json() == {"returned": ["web"]}
