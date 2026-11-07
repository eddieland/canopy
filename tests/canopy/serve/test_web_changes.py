"""What a worker's or a task's run changed, on its page and its ticket's runs list (DESIGN §45).

The rows are recorded as `_run` and `_task` record them when a run ends, and the diffs kept beside the run's log as
`runs.changes` keeps them. A page reads the journal alone, each repository's range and the files git counted; the
run's own diff is sent on its own when the page opens it, read within a review's diff's bounds.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from canopy.core import db, gc_passes, records, review_diff, run_changes
from canopy.core.context import Context
from canopy.core.run_changes import Change
from canopy.core.vocab import RunKind, RunStatus
from tests.canopy.helpers import KEY, present, running_run
from tests.canopy.web_helpers import signed_in_client

#: A run's own change, as `runs.changes` keeps it: the branch's text, a control character in its last line.
CHANGE = """\
diff --git a/src/canopy/order.py b/src/canopy/order.py
index 1111111..2222222 100644
--- a/src/canopy/order.py
+++ b/src/canopy/order.py
@@ -1,2 +1,2 @@ def main() -> None:
 import os
-def _helper(): ...
+def main() -> None:\x07 # moved up
"""
#: The branch against its base, which holds an earlier run's change besides.
BRANCH = CHANGE + CHANGE.replace("order.py", "earlier.py")
START, END, FORK = "a1" * 20, "b2" * 20, "c3" * 20
#: What git counted of `CHANGE`, and of a logo it renamed, binary.
COUNTED = run_changes.counted(
    [
        review_diff.Count("src/canopy/order.py", None, 1, 1),
        review_diff.Count("logo.png", "old-logo.png", None, None),
    ],
)
PR = "https://github.com/acme/api/pull/7"


def test_a_runs_page_carries_its_range_and_files_as_counted_and_no_diff(ctx: Context) -> None:
    run_id = ended_run(ctx)
    keep(ctx, run_id, "api", CHANGE, BRANCH)
    run_changes.record(ctx.conn, run_id, [kept("api")])
    db.set_unit(ctx.conn, KEY, ctx.repo, "api", pr_url=PR)

    c, _ = signed_in_client(ctx)
    shown = c.get(f"/api/runs/{run_id}").json()
    [change] = shown["changes"]
    assert change == {
        "range": {
            "repo": "api",
            "start_sha": START,
            "start_on_base": False,
            "end_sha": END,
            "unpushed_sha": None,
            "files_changed": 2,
            "lines_added": 1,
            "lines_removed": 1,
        },
        "files": [
            {"path": "src/canopy/order.py", "old_path": None, "added": 1, "removed": 1},
            {"path": "logo.png", "old_path": "old-logo.png", "added": None, "removed": None},
        ],
        "diff_kept": True,
        "missing": None,
        "removed_after_days": None,
        "pr_url": PR,
    }
    assert shown["records_changes"] is True
    # The list of runs sends neither the changes nor the ranges: only the run's page, and its ticket's, does.
    assert all(r["changes"] == [] and r["ranges"] == [] for r in c.get("/api/runs").json())


def test_a_runs_own_diff_is_sent_on_its_own_read_as_a_reviews_is(ctx: Context) -> None:
    run_id = ended_run(ctx)
    keep(ctx, run_id, "api", CHANGE, BRANCH)
    run_changes.record(ctx.conn, run_id, [kept("api")])
    c, _ = signed_in_client(ctx)
    assert c.get(f"/api/runs/{run_id}/changes/api").json() == {
        "files": [
            {
                "path": "src/canopy/order.py",
                "old_path": None,
                "binary": False,
                "hunks": [
                    {
                        "header": "def main() -> None:",
                        "lines": [
                            {"kind": "ctx", "old": 1, "new": 1, "text": "import os"},
                            {"kind": "del", "old": 2, "new": None, "text": "def _helper(): ..."},
                            # The branch's text, its control characters made spaces, as a review's diff is.
                            {"kind": "add", "old": None, "new": 2, "text": "def main() -> None:  # moved up"},
                        ],
                    },
                ],
            },
        ],
        "truncated": False,
    }
    # A repository the run recorded no change to has none, nor has a run with no such id.
    assert c.get(f"/api/runs/{run_id}/changes/web").status_code == 404
    assert c.get("/api/runs/999/changes/api").status_code == 404


def test_a_kept_diff_is_read_within_a_reviews_bounds(ctx: Context) -> None:
    run_id = ended_run(ctx)
    keep(ctx, run_id, "api", BRANCH, BRANCH)
    run_changes.record(ctx.conn, run_id, [kept("api")])
    c, _ = signed_in_client(ctx)
    with mock.patch.object(review_diff, "MAX_FILES", 1):
        diff = c.get(f"/api/runs/{run_id}/changes/api").json()
    assert (len(diff["files"]), diff["truncated"]) == (1, True)


def test_an_unpushed_runs_page_names_the_commit_it_left_in_its_slot_not_on_origin(ctx: Context) -> None:
    run_id = ended_run(ctx, RunStatus.UNPUSHED)
    keep(ctx, run_id, "api", CHANGE, CHANGE)
    left = "d4" * 20
    run_changes.record(ctx.conn, run_id, [kept("api", end=START, unpushed=left)])
    c, _ = signed_in_client(ctx)
    [change] = c.get(f"/api/runs/{run_id}").json()["changes"]
    assert (change["range"]["unpushed_sha"], change["range"]["end_sha"], change["diff_kept"]) == (left, START, True)
    assert [f["path"] for f in c.get(f"/api/runs/{run_id}/changes/api").json()["files"]] == ["src/canopy/order.py"]


def test_a_diff_not_kept_says_why_and_one_gone_or_a_link_is_none_never_empty(ctx: Context, tmp_path: Path) -> None:
    """A crashed run's row counted nothing and kept nothing; a kept file since replaced by a link is no diff."""
    crashed = ended_run(ctx, RunStatus.CRASHED)
    run_changes.record(ctx.conn, crashed, run_changes.crashed(["api"]))
    linked = ended_run(ctx)
    log_path = keep(ctx, linked, "api", CHANGE, CHANGE)
    change = run_changes.change_path(log_path, "api")
    change.unlink()
    elsewhere = tmp_path / "elsewhere.diff"
    elsewhere.write_text(CHANGE)
    change.symlink_to(elsewhere)
    run_changes.record(ctx.conn, linked, [kept("api")])

    c, _ = signed_in_client(ctx)
    [nothing] = c.get(f"/api/runs/{crashed}").json()["changes"]
    assert (nothing["range"]["start_sha"], nothing["range"]["files_changed"], nothing["files"]) == (None, None, [])
    assert (nothing["diff_kept"], nothing["missing"]) == (False, run_changes.CRASHED)
    assert c.get(f"/api/runs/{crashed}/changes/api").status_code == 404
    [gone] = c.get(f"/api/runs/{linked}").json()["changes"]
    assert (gone["diff_kept"], gone["missing"], gone["removed_after_days"]) == (False, None, None)
    assert c.get(f"/api/runs/{linked}/changes/api").status_code == 404
    # A run that recorded nothing, as one reconcile closed, has no change to send, and says it records them.
    bare = c.get(f"/api/runs/{ended_run(ctx)}").json()
    assert (bare["changes"], bare["records_changes"]) == ([], True)


def test_only_an_ended_run_of_a_kind_that_records_says_it_does(ctx: Context) -> None:
    running = running_run(ctx, KEY, private=False)
    planned = running_run(ctx, KEY, private=False)
    db.finish_run(ctx.conn, "runs", planned, RunStatus.DONE, None)
    records.update(records.Run).set(kind=RunKind.PLAN).where("id = ?", planned).run(ctx.conn)
    c, _ = signed_in_client(ctx)
    assert c.get(f"/api/runs/{running}").json()["records_changes"] is False
    assert c.get(f"/api/runs/{planned}").json()["records_changes"] is False


def test_a_kept_diff_retention_removed_says_after_how_many_days(ctx: Context) -> None:
    run_id = ended_run(ctx)
    run_changes.record(ctx.conn, run_id, [kept("api")])
    gc_passes.record(
        ctx.conn,
        tick_id=None,
        started_at=datetime.now(UTC),
        run_files_days=30,
        tick_files_days=7,
        run_cutoff=db.format_time(datetime.now(UTC) + timedelta(days=1)),
        tick_cutoff=None,
        removed={},
        failures=0,
        error=None,
    )
    c, _ = signed_in_client(ctx)
    [change] = c.get(f"/api/runs/{run_id}").json()["changes"]
    assert (change["diff_kept"], change["removed_after_days"]) == (False, 30)
    # Its size is the journal's, so it outlives the file.
    assert (change["range"]["files_changed"], len(change["files"])) == (2, 2)


def test_a_joint_runs_page_carries_a_change_per_repository_one_of_them_unpushed(ctx: Context) -> None:
    """A joint run whose push was refused in one repository marks that one's alone as work not on origin."""
    run_id = ended_run(ctx, RunStatus.UNPUSHED)
    keep(ctx, run_id, "api", CHANGE, CHANGE)
    keep(ctx, run_id, "web", BRANCH, BRANCH)
    left = "d4" * 20
    run_changes.record(ctx.conn, run_id, [kept("web", end=START, unpushed=left), kept("api")])
    db.set_unit(ctx.conn, KEY, ctx.repo, "web", pr_url=PR)
    c, _ = signed_in_client(ctx)
    changes = c.get(f"/api/runs/{run_id}").json()["changes"]
    assert [(ch["range"]["repo"], ch["range"]["unpushed_sha"], ch["pr_url"]) for ch in changes] == [
        ("api", None, None),
        ("web", left, PR),
    ]
    assert len(c.get(f"/api/runs/{run_id}/changes/web").json()["files"]) == 2


def test_a_tickets_runs_list_names_each_runs_range_and_size_without_its_files(ctx: Context) -> None:
    recorded = ended_run(ctx)
    run_changes.record(ctx.conn, recorded, [kept("api")])
    bare = ended_run(ctx)
    c, _ = signed_in_client(ctx)
    runs = {r["id"]: r for r in c.get(f"/api/tickets/{KEY}").json()["runs"]}
    assert runs[recorded]["ranges"] == [
        {
            "repo": "api",
            "start_sha": START,
            "start_on_base": False,
            "end_sha": END,
            "unpushed_sha": None,
            "files_changed": 2,
            "lines_added": 1,
            "lines_removed": 1,
        },
    ]
    assert runs[recorded]["changes"] == []
    assert runs[bare]["ranges"] == []


def kept(repo: str, *, end: str = END, unpushed: str | None = None) -> Change:
    """A change of `repo` from `START` to `end`, or left `unpushed`, both of whose diffs were kept, and counted."""
    return Change(
        repo,
        START,
        end=end,
        merge_base=FORK,
        unpushed=unpushed,
        change_kept=True,
        branch_kept=True,
        counted=COUNTED,
    )


def ended_run(ctx: Context, status: RunStatus = RunStatus.DONE) -> int:
    """Record a run of `KEY` that ended as `status`, and return its id."""
    run_id = running_run(ctx, KEY, private=False)
    db.finish_run(ctx.conn, "runs", run_id, status, None)
    return run_id


def keep(ctx: Context, run_id: int, repo: str, change: str, branch: str) -> str:
    """Keep run `run_id`'s two diffs of `repo` beside its log, as `runs.changes` does, and return the log's path."""
    log_path = str(present(db.get_run(ctx.conn, run_id))["log_path"])
    path = run_changes.change_path(log_path, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    review_diff.keep(path, change)
    review_diff.keep(review_diff.run_path_for(log_path, repo), branch)
    return log_path
