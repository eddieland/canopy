"""The operator's desk (DESIGN §18): a ticket's branch checked out in a slot per repository, for their own edits."""

import json
import os
from pathlib import Path
from unittest import mock

from canopy.cli.main import main
from canopy.core import pools, treehouse
from canopy.core.pools import ReturnOutcome
from canopy.runs import checkouts
from tests.canopy.conftest import Ws
from tests.canopy.helpers import BRANCH, KEY, pool_statuses, tracker_holds, waits
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import git


def implemented(scenario: Scenario) -> None:
    """A joint implement of KEY over both repositories pushed its branch to each origin: the desk starts there."""
    run = scenario.run(dispatches(repo=("api", "web")), worker=pushes(repos=("api", "web")))
    assert run.status == "done", run.printed.out


def holders(treehouse_state: Path) -> list[str]:
    state = json.loads(treehouse_state.read_text())
    return [s.get("lease_holder", "") for pool in state["pools"].values() for s in pool["slots"]]


def test_a_desk_links_a_slot_per_unit_on_the_ticket_s_branch(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    implemented(ws_scenario)
    opened = ws_scenario.operator("desk", KEY)
    desk = ws.root / checkouts.DIR / KEY
    found = checkouts.find(ws.root, KEY)
    assert found is not None
    assert (found.path, found.branch, sorted(found.slots)) == (desk, BRANCH, ["api", "web"])
    assert f"{KEY}'s desk is open.\n" in opened.out
    assert f"Open it in VS Code: code {desk / f'{KEY}.code-workspace'}\n" in opened.out
    assert f"Close it when you are done: canopy desk {KEY} --close\n" in opened.out
    # A link per repository to its slot, which is on the branch as a local branch tracking origin's.
    for name, slot in found.slots.items():
        assert (desk / name).is_symlink()
        assert (desk / name).resolve() == slot.resolve()
        assert git("symbolic-ref", "--short", "HEAD", cwd=slot) == BRANCH
        assert git("rev-parse", "--abbrev-ref", f"{BRANCH}@{{upstream}}", cwd=slot) == f"origin/{BRANCH}"
        assert git("rev-parse", "HEAD", cwd=slot) == ws.remote_head(name, BRANCH)
    workspace = json.loads((desk / f"{KEY}.code-workspace").read_text())
    assert workspace == {"folders": [{"name": n, "path": str(s)} for n, s in found.slots.items()]}
    assert pool_statuses(treehouse_state) == ["leased", "leased"]
    assert holders(treehouse_state) == [f"operator:{KEY}", f"operator:{KEY}"]

    # Opening it again changes nothing, and the slots say what holds them and what frees them.
    again = ws_scenario.operator("desk", KEY)
    assert f"{KEY}'s desk is already open.\n" in again.out
    assert holders(treehouse_state) == [f"operator:{KEY}", f"operator:{KEY}"]
    listed = ws_scenario.operator("workspace", "slots", "api")
    assert f"      held by your desk for {KEY}, on its branch; `canopy desk {KEY} --close` returns it\n" in listed.out
    refused = ws_scenario.operator("workspace", "release", "api", "1", code=1)
    assert f"is held by your desk for {KEY}; `canopy desk {KEY} --close` returns it" in refused.err

    # A tick's reconcile returns stale canopy leases, and leaves the operator's.
    ws_scenario.tick(*waits(KEY))
    assert holders(treehouse_state) == [f"operator:{KEY}", f"operator:{KEY}"]


def test_a_desk_for_one_repository_and_what_is_refused(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    tracker_holds(ws_scenario.conn, "PROJ-2")
    no_branch = ws_scenario.operator("desk", "PROJ-2", code=1)
    assert "PROJ-2 has no branch in the journal yet" in no_branch.err
    implemented(ws_scenario)
    not_mapped = ws_scenario.operator("desk", KEY, "--repo", "docs", code=1)
    assert "the map lists no repository docs" in not_mapped.err
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "7"}):
        assert main(["desk", KEY]) == 1
    assert checkouts.find(ws.root, KEY) is None
    assert pool_statuses(treehouse_state) == ["available", "available"]

    one = ws_scenario.operator("desk", KEY, "--repo", "web")
    found = checkouts.find(ws.root, KEY)
    assert found is not None
    assert list(found.slots) == ["web"]
    assert f"  web: {found.slots['web']} on {BRANCH}\n" in one.out
    assert sorted(holders(treehouse_state)) == ["", f"operator:{KEY}"]
    # Dropping a unit the desk already has is not how a desk shrinks: close it first.
    assert ws_scenario.operator("desk", KEY, "--close", "--repo", "web", code=2).err


def test_close_returns_the_slots_unless_work_would_be_lost(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    implemented(ws_scenario)
    ws_scenario.operator("desk", KEY)
    found = checkouts.find(ws.root, KEY)
    assert found is not None
    api, web = found.slots["api"], found.slots["web"]

    (api / "notes.txt").write_text("a tweak\n")
    kept = ws_scenario.operator("desk", KEY, "--close", code=1)
    assert f"{KEY}'s desk has work origin lacks: api has 1 uncommitted change." in kept.err
    assert pool_statuses(treehouse_state) == ["leased", "leased"]
    git("add", "notes.txt", cwd=api)
    git("commit", "--quiet", "-m", f"{KEY}: a tweak", cwd=api)
    git("commit", "--quiet", "--allow-empty", "-m", f"{KEY}: another", cwd=web)
    (web / "more.txt").write_text("more\n")
    kept = ws_scenario.operator("desk", KEY, "--close", code=1)
    assert "api has 1 commit origin lacks; web has 1 uncommitted change and 1 commit origin lacks." in kept.err

    # Pushed, the desk closes: the slots go back, the local branch with them, and the directory is gone.
    (web / "more.txt").unlink()
    for slot in (api, web):
        git("push", "--quiet", "origin", BRANCH, cwd=slot)
    closed = ws_scenario.operator("desk", KEY, "--close")
    assert f"{KEY}'s desk is closed; its slots are returned: api, web.\n" in closed.out
    assert not (ws.root / checkouts.DIR / KEY).exists()
    assert pool_statuses(treehouse_state) == ["available", "available"]
    for name, slot in (("api", api), ("web", web)):
        assert git("branch", "--list", BRANCH, cwd=slot) == ""
        assert git("log", "-1", "--format=%s", f"origin/{BRANCH}", cwd=slot).startswith(KEY)
        assert ws.remote_head(name, BRANCH) == git("rev-parse", f"origin/{BRANCH}", cwd=slot)
    assert f"{KEY} has no desk open.\n" in ws_scenario.operator("desk", KEY, "--close").out

    # --discard loses what a slot holds, as the operator asks.
    ws_scenario.operator("desk", KEY)
    found = checkouts.find(ws.root, KEY)
    assert found is not None
    (found.slots["api"] / "scratch.txt").write_text("scratch\n")
    assert ws_scenario.operator("desk", KEY, "--close", "--discard").out.startswith(f"{KEY}'s desk is closed")
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_close_that_fails_partway_is_finished_by_the_next(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    implemented(ws_scenario)
    ws_scenario.operator("desk", KEY)
    found = checkouts.find(ws.root, KEY)
    assert found is not None

    # web's pool fails to take its slot back: api's is returned and dropped from the desk, web's stays.
    def fails_web(self: treehouse.TreehousePool, path: Path, *, lease_id: str, lease_holder: str) -> ReturnOutcome:
        if path == found.slots["web"]:
            raise pools.PoolError("the pool's state file is locked")
        return treehouse.return_slot(self.runner, path, lease_id=lease_id, lease_holder=lease_holder, pool=self.where)

    with mock.patch.object(treehouse.TreehousePool, "return_slot", autospec=True, side_effect=fails_web):
        kept = ws_scenario.operator("desk", KEY, "--close", code=1)
    assert f"{KEY}'s desk is kept: web: the pool's state file is locked" in kept.err
    assert sorted(holders(treehouse_state)) == ["", f"operator:{KEY}"]
    left = checkouts.find(ws.root, KEY)
    assert left is not None
    assert list(left.slots) == ["web"]
    assert not (left.path / "api").exists()
    assert json.loads(left.workspace_file.read_text())["folders"] == [{"name": "web", "path": str(left.slots["web"])}]

    # A slot the desk no longer holds, freed by hand, is dropped without a look at its work; the rest closes.
    git("commit", "--quiet", "--allow-empty", "-m", f"{KEY}: unpushed", cwd=found.slots["web"])
    ws_scenario.operator("workspace", "release", "web", "1", code=1)
    assert ws_scenario.operator("desk", KEY, "--close", code=1).err  # web's commit is still the desk's to push
    state = json.loads(treehouse_state.read_text())
    [web_slot] = state["pools"][str(ws.clone("web"))]["slots"]
    web_slot.update(lease_holder="canopy:PROJ-9")
    treehouse_state.write_text(json.dumps(state))
    closed = ws_scenario.operator("desk", KEY, "--close")
    assert f"{KEY}'s desk is closed" in closed.out
    assert not (ws.root / checkouts.DIR / KEY).exists()
    assert holders(treehouse_state) == ["", "canopy:PROJ-9"]
