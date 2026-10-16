"""The web UI's worktrees page (DESIGN §22): each pool's slots from treehouse, with the run or review holding each."""

import dataclasses
import json
import threading
from collections.abc import Sequence
from pathlib import Path

from canopy.core import db, pools, workspace
from canopy.core.context import Context
from canopy.core.vocab import PoolKind
from canopy.serve import mock
from tests.canopy.helpers import running_run
from tests.canopy.web_helpers import client, signed_in_client
from tests.conftest import pool_state

KEY = "PROJ-1"


def slot(name: str, status: str, **more: object) -> dict[str, object]:
    return {"name": name, "path": f"/pool/{name}", "status": status, **more}


def leased(name: str, holder: str, lease_id: str, **more: object) -> dict[str, object]:
    return slot(
        name, "leased", lease_id=lease_id, lease_holder=holder, leased_at="2026-10-08T12:00:00.123456789-07:00", **more
    )


def test_each_slot_shows_what_holds_it_and_what_runs_in_it(ctx: Context, treehouse_state: Path) -> None:
    run_id = running_run(ctx, KEY)
    ctx.conn.execute(
        "INSERT INTO run_slots (run_id, slot_path, lease_id, lease_holder, base_branch) VALUES (?, ?, ?, ?, ?)",
        (run_id, "/pool/1", "lease-run", f"canopy:{KEY}", "main"),
    )
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    review_id = db.insert_review_run(
        ctx.conn, tick_id=tick_id, pr_url="https://example.test/pr/3", sha="abc", ticket=None, repo=None,
        purpose="query", logs_dir=ctx.state_dir / "reviews",
    )  # fmt: skip
    db.set_review_slot(
        ctx.conn,
        review_id,
        slot=Path("/pool/2"),
        lease_id="lease-review",
        lease_holder="canopy:r",
        base_branch="main",
        pool=PoolKind.TREEHOUSE,
    )
    db.finish_tick(ctx.conn, tick_id, "ok", "test")
    slots = [
        leased(
            "1",
            f"canopy:{KEY}",
            "lease-run",
            processes=[{"pid": 7, "name": "opencode\x1b[2J"}],
        ),
        leased("2", "canopy:r", "lease-review"),
        leased("3", "canopy:PROJ-9", "lease-gone"),
        leased("4", "canopy-sync", "lease-sync"),
        slot("5", "in-use", branch="op/try", processes=[{"pid": 9, "name": "zsh"}]),
        slot("6", "available"),
        slot("7", "dirty"),
        slot("8", "damaged"),
    ]
    treehouse_state.write_text(pool_state(ctx.workspace.repos[0].path, slots))
    c, _ = signed_in_client(ctx)

    [pool] = c.get("/api/worktrees").json()
    assert (pool["repo"], pool["size"], pool["error"]) == ("repo", None, None)
    by_name = {w["name"]: w for w in pool["worktrees"]}
    assert {n: w["state"] for n, w in by_name.items()} == {
        "1": "working",
        "2": "working",
        "3": "held",
        "4": "held",
        "5": "held",
        "6": "idle",
        "7": "dirty",
        "8": "broken",
    }
    one = by_name["1"]
    assert (one["run"]["id"], one["run"]["kind"], one["review"]) == (run_id, "implement", None)
    # Detached, as every run's slot is: the branch shown is the run's.
    assert (one["branch"], one["detached"], one["holder"]) == ("agent/PROJ-1-work", True, f"canopy:{KEY}")
    assert one["leased_at"] == "2026-10-08T19:00:00.123456Z"
    assert one["processes"] == [{"pid": 7, "name": "opencode [2J"}]  # control characters dropped
    assert by_name["2"]["review"]["id"] == review_id
    assert by_name["2"]["run"] is None
    assert "reconcile returns it" in by_name["3"]["note"]
    assert "workspace sync" in by_name["4"]["note"]
    assert by_name["5"]["note"] is None
    assert (by_name["6"]["branch"], by_name["6"]["detached"], by_name["6"]["holder"]) == (None, True, None)


def test_a_pool_that_cannot_be_read_says_why_and_the_others_still_show(ctx: Context, treehouse_state: Path) -> None:
    root = ctx.repo_root
    (root / "repos" / "web" / ".git").mkdir(parents=True)
    ws = workspace.Workspace(
        root=root,
        name="ws",
        repos=(workspace.Repo("api", root / "repos" / "api"), workspace.Repo("web", root / "repos" / "web")),
        map_file=root / "canopy-workspace.toml",
    )
    pools = {str(root / "repos" / "web"): {"slots": [slot("1", "available")]}}
    treehouse_state.write_text(json.dumps({"pools": pools}))
    c, _ = signed_in_client(dataclasses.replace(ctx, ws=ws))

    api, web = c.get("/api/worktrees").json()
    assert (api["repo"], api["worktrees"]) == ("api", [])
    assert "no clone" in api["error"]
    assert (web["repo"], web["error"], [w["state"] for w in web["worktrees"]]) == ("web", None, ["idle"])


def test_a_failing_treehouse_is_the_pool_s_error_not_the_page_s(ctx: Context, treehouse_state: Path) -> None:
    treehouse_state.write_text("not json")
    c, _ = signed_in_client(ctx)

    response = c.get("/api/worktrees")
    assert response.status_code == 200
    [pool] = response.json()
    assert pool["worktrees"] == []
    assert "treehouse status exited" in pool["error"]


def test_the_mock_is_a_workspace_with_a_joint_run_and_a_pool_past_its_size(tmp_path: Path) -> None:
    c = client(None, mock.seed(tmp_path / "mock"))

    api, mobile, web = c.get("/api/worktrees").json()
    assert (api["repo"], api["size"], api["worktrees"]) == ("api", 2, [])
    assert "no clone" in api["error"]
    assert (mobile["repo"], mobile["size"], len(mobile["worktrees"])) == ("mobile", 2, 2)
    assert (web["repo"], web["size"], len(web["worktrees"])) == ("web", 4, 5)
    joint = [w for pool in (mobile, web) for w in pool["worktrees"] if w["run"] and w["run"]["id"] == 43]
    assert [w["path"] for w in joint] == [".treehouse/mobile-8e41d0c7/1/mobile", ".treehouse/web-3f9c2a1b/2/web"]
    [running] = [r for r in c.get("/api/runs").json() if r["id"] == 43]
    assert running["worktrees"] == [".treehouse/mobile-8e41d0c7/1/mobile", ".treehouse/web-3f9c2a1b/2/web"]


def test_a_workspace_s_pools_are_read_at_once(tmp_path: Path) -> None:
    backend = mock.seed(tmp_path / "mock")
    # Both cloned pools must be inside treehouse together for either to get past the barrier.
    both = threading.Barrier(2, timeout=5)

    def slots(ctx: Context, repo: str) -> Sequence[pools.Slot]:
        both.wait()
        return backend.slots(ctx, repo)

    c = client(None, dataclasses.replace(backend, slots=slots))
    assert [len(p["worktrees"]) for p in c.get("/api/worktrees").json()] == [0, 2, 5]
