"""A ticket's plans through the web channel and `canopy show` (DESIGN §25, ROADMAP M44).

The web UI's plan route runs `canopy plan`'s code with its refusals, a save writes the plan's file as the operator's
own editor would and refuses one the file changed under, and comments are threads on passages, the ticket's. `canopy
show` prints the newest plan as its file stands, and `--plans` every plan and the open comments.
"""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from canopy.core import db, plans
from canopy.core.context import Context
from canopy.core.vocab import PlanStatus, RunStatus
from tests.canopy.helpers import (
    KEY,
    LABEL,
    dispatch_and_run,
    dispatch_in_tick,
    operator,
    planner_does,
    prompt_of,
)
from tests.canopy.web_helpers import refused, signed_in_client
from tests.conftest import CanopyEnv, GitPool

TEXT = "# Plan for PROJ-1\n\n## repo\n\nAdd the button to `ui/form.tsx`, red.\n"
PLAN = ("--label", LABEL, "--kind", "plan")


def proposed(ctx: Context, text: str = TEXT) -> int:
    """Write and record a plan for KEY as a plan run that ended `done` would; returns the plan's id."""
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    run_id = db.insert_run(
        ctx.conn,
        tick_id=tick_id,
        key=KEY,
        kind="plan",
        branch="",
        slots=[],
        runs_dir=ctx.state_dir,
        works_units=False,
    )
    ctx.conn.execute("UPDATE runs SET status = 'done', ended_at = started_at WHERE id = ?", (run_id,))
    ctx.conn.commit()
    return plans.record(ctx.conn, KEY, run_id, plans.write(ctx.state_dir, KEY, run_id, text)).id


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_a_tickets_plans_are_read_as_their_files_stand(ctx: Context) -> None:
    c, _ = signed_in_client(ctx)
    assert c.get(f"/api/tickets/{KEY}/plans").status_code == 404
    plan_id = proposed(ctx)
    found = c.get(f"/api/tickets/{KEY}/plans").json()
    assert (found["needed"], found["setting"], found["policy"], found["planning"]) == (False, None, "off", None)
    newest = found["newest"]
    assert (newest["text"], newest["problem"], newest["sha256"]) == (TEXT, None, sha(TEXT))
    assert (newest["edited"], newest["changed_since_approval"]) == (False, False)
    assert newest["plan"]["id"] == plan_id
    assert newest["plan"]["status"] == "proposed"
    assert [p["id"] for p in found["plans"]] == [plan_id]
    assert found["threads"] == []

    # The operator's own edit shows, and a file that is gone is said to be, never an empty plan.
    path = Path(newest["path"])
    path.write_text(TEXT + "\nBlue.\n")
    assert c.get(f"/api/tickets/{KEY}/plans").json()["newest"]["edited"] is True
    path.unlink()
    gone = c.get(f"/api/tickets/{KEY}/plans/{plan_id}").json()
    assert (gone["text"], gone["problem"]) == (None, "missing")
    assert c.get(f"/api/tickets/{KEY}/plans/99").status_code == 404


def test_the_plan_route_approves_asks_and_skips_as_canopy_plan_does(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    plan_id = proposed(ctx)
    approved = c.post(f"/api/tickets/{KEY}/plan", json={"action": "approve"}, headers=headers)
    assert approved.json() == {"action": "approve", "plan": plan_id, "superseded": None, "already": False}
    plan = plans.current(ctx.conn, KEY)
    assert plan is not None
    assert (plan.status, plan.approved_channel) == (PlanStatus.APPROVED, "web")
    assert refused(c.post(f"/api/tickets/{KEY}/plan", json={"action": "approve"}, headers=headers)).startswith(
        "bad_plan: plan 1 of PROJ-1 is approved, and its file has not changed since"
    )

    asked = c.post(f"/api/tickets/{KEY}/plan", json={"action": "request"}, headers=headers)
    assert asked.json() == {"action": "request", "plan": None, "superseded": plan_id, "already": False}
    found = c.get(f"/api/tickets/{KEY}/plans").json()
    assert (found["needed"], found["setting"], found["newest"]["plan"]["status"]) == (True, "plan", "superseded")
    skipped = c.post(f"/api/tickets/{KEY}/plan", json={"action": "skip"}, headers=headers)
    assert skipped.json() == {"action": "skip", "plan": None, "superseded": None, "already": False}
    assert c.post(f"/api/tickets/{KEY}/plan", json={"action": "merge"}, headers=headers).status_code == 422
    # A write needs the session's token, as every write does.
    assert c.post(f"/api/tickets/{KEY}/plan", json={"action": "skip"}).status_code == 403


def test_an_edit_saved_from_the_web_is_the_file_approve_takes(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    plan_id = proposed(ctx)
    edited = TEXT + "\n## Out of scope\n\nThe API.\n"
    saved = c.put(
        f"/api/tickets/{KEY}/plans/{plan_id}/file", json={"markdown": edited, "read_sha256": sha(TEXT)}, headers=headers
    )
    assert saved.json() == {"sha256": sha(edited), "size": len(edited.encode())}
    path = plans.path_for(ctx.state_dir, KEY, 1)
    assert path.read_text() == edited
    assert path.stat().st_mode & 0o777 == 0o600
    # Nothing but the plan is left in the ticket's directory.
    assert [p.name for p in path.parent.iterdir()] == [path.name]

    # One the file changed under is refused, and the file is left as it is.
    stale = c.put(
        f"/api/tickets/{KEY}/plans/{plan_id}/file",
        json={"markdown": "# Mine\n", "read_sha256": sha(TEXT)},
        headers=headers,
    )
    assert refused(stale) == (
        f"bad_plan: plan {plan_id}'s file {path} changed since it was read; read it again before saving"
    )
    assert path.read_text() == edited

    assert c.post(f"/api/tickets/{KEY}/plan", json={"action": "approve"}, headers=headers).status_code == 200
    approved = plans.current(ctx.conn, KEY)
    assert approved is not None
    assert plans.approved_text(ctx.state_dir, approved) == edited

    # Saving over an approved plan needs approving it again.
    again = edited + "\nOne more test.\n"
    body = {"markdown": again, "read_sha256": sha(edited)}
    assert c.put(f"/api/tickets/{KEY}/plans/{plan_id}/file", json=body, headers=headers).status_code == 200
    assert c.get(f"/api/tickets/{KEY}/plans").json()["newest"]["changed_since_approval"] is True
    assert plans.approved_text(ctx.state_dir, approved) is None


def test_a_save_is_refused_for_anything_but_the_current_plan_or_a_plan(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    first = proposed(ctx)
    second = proposed(ctx, "# Second\n")
    body = {"markdown": "# Mine\n", "read_sha256": sha(TEXT)}
    assert refused(c.put(f"/api/tickets/{KEY}/plans/{first}/file", json=body, headers=headers)) == (
        f"bad_plan: plan {first} is not {KEY}'s current plan, so it is not edited"
    )
    empty = {"markdown": "  \n", "read_sha256": sha("# Second\n")}
    assert refused(c.put(f"/api/tickets/{KEY}/plans/{second}/file", json=empty, headers=headers)).startswith(
        "bad_plan: a plan is 1 to 100,000 characters"
    )
    # A link in the plan's place is not saved over.
    path = plans.path_for(ctx.state_dir, KEY, 2)
    real = ctx.state_dir / "elsewhere.md"
    real.write_text("# Second\n")
    path.unlink()
    path.symlink_to(real)
    linked = {"markdown": "# Mine\n", "read_sha256": sha("# Second\n")}
    assert "is not a regular file" in refused(
        c.put(f"/api/tickets/{KEY}/plans/{second}/file", json=linked, headers=headers)
    )
    assert real.read_text() == "# Second\n"


def test_comments_are_threads_on_passages_the_tickets_own(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    proposed(ctx)
    base = f"/api/tickets/{KEY}/plan-threads"
    comment = {"quote": "Add the button", "prefix": "## repo ", "suffix": " to ui/form.tsx", "body": " Why red? "}
    made = c.post(base, json=comment, headers=headers).json()
    thread = made["id"]
    assert (made["quote"], made["body"], made["resolved"], made["replies"]) == ("Add the button", "Why red?", False, [])

    replied = c.post(f"{base}/{thread}/replies", json={"body": "It matches the brand."}, headers=headers).json()
    [first] = replied["replies"]
    assert first["body"] == "It matches the brand."
    edited = c.patch(f"{base}/{thread}", json={"body": "Why red, not blue?"}, headers=headers).json()
    assert edited["body"] == "Why red, not blue?"
    edited = c.patch(f"{base}/{thread}", json={"body": "Brand red.", "reply": first["id"]}, headers=headers).json()
    assert edited["replies"][0]["body"] == "Brand red."
    moved = {"anchor": {"quote": "Add the blue button", "prefix": "## repo ", "suffix": ""}}
    assert c.patch(f"{base}/{thread}", json=moved, headers=headers).json()["quote"] == "Add the blue button"
    blank = {"anchor": {"quote": "   ", "prefix": "", "suffix": ""}}
    assert refused(c.patch(f"{base}/{thread}", json=blank, headers=headers)).startswith("bad_anchor")
    assert c.patch(f"{base}/{thread}", json={"resolved": True}, headers=headers).json()["resolved"] is True
    assert c.patch(f"{base}/{thread}", json={"resolved": False}, headers=headers).json()["resolved"] is False
    [listed] = c.get(f"/api/tickets/{KEY}/plans").json()["threads"]
    assert listed["id"] == thread

    assert refused(c.post(base, json={**comment, "body": "  "}, headers=headers)) == "bad_body: the comment is empty"
    assert refused(c.post(base, json={**comment, "quote": "   "}, headers=headers)).startswith("bad_anchor")
    assert c.post(base, json={**comment, "prefix": "x" * 33}, headers=headers).status_code == 422
    assert refused(c.patch(f"{base}/{thread}", json={"reply": first["id"]}, headers=headers)).startswith("bad_body")
    assert refused(c.patch(f"{base}/99", json={"resolved": True}, headers=headers)) == (
        f"unknown: {KEY} has no plan comment 99"
    )
    # Another ticket's thread is not this one's to change.
    db.touch_ticket(ctx.conn, "PROJ-2", ctx.repo)
    ctx.conn.commit()
    assert refused(c.delete(f"/api/tickets/PROJ-2/plan-threads/{thread}", headers=headers)).startswith("unknown")
    assert c.delete(f"{base}/{thread}", headers=headers).json() == {"id": thread}
    assert c.get(f"/api/tickets/{KEY}/plans").json()["threads"] == []


def test_comments_asked_for_from_the_web_reach_the_next_plans_prompt(
    canopy_env: CanopyEnv, git_pool: GitPool, ctx: Context, conn: sqlite3.Connection
) -> None:
    with planner_does(plan=TEXT):
        dispatch_and_run(conn, *PLAN)
    c, headers = signed_in_client(ctx)
    # Ask for changes is a reply: the open comments, each with its passage, as the editor composes them.
    request = 'Change the plan where I commented. Each comment quotes the passage it is on.\n\n1. On "red":\n   Blue.'
    reply = c.post(f"/api/tickets/{KEY}/replies", json={"body": request, "submission": "abcdefgh"}, headers=headers)
    assert reply.status_code == 200
    with planner_does(plan="# Plan, blue\n"):
        second = dispatch_and_run(conn, *PLAN)
    assert second["status"] == RunStatus.DONE
    prompt = prompt_of(canopy_env, int(second["id"]))
    assert '1. On "red":' in prompt
    assert "   Blue." in prompt


def test_the_plan_verbs_refuse_while_a_plan_run_is_running_from_the_web(
    canopy_env: CanopyEnv, git_pool: GitPool, ctx: Context, conn: sqlite3.Connection
) -> None:
    with planner_does(plan=TEXT):
        dispatch_and_run(conn, *PLAN)
    assert dispatch_in_tick(conn, *PLAN).code == 0
    c, headers = signed_in_client(ctx)
    assert c.get(f"/api/tickets/{KEY}/plans").json()["planning"] == 2
    body = {"markdown": "# Mine\n", "read_sha256": sha(TEXT)}
    assert refused(c.put(f"/api/tickets/{KEY}/plans/1/file", json=body, headers=headers)).startswith(
        "bad_plan: plan run 2 for PROJ-1 is running"
    )
    assert refused(c.post(f"/api/tickets/{KEY}/plan", json={"action": "approve"}, headers=headers)).startswith(
        "bad_plan: plan run 2"
    )


def test_canopy_show_prints_the_newest_plan_and_plans_every_one(
    ctx: Context, canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    proposed(ctx)
    capsys.readouterr()
    assert operator("show", KEY) == 0
    out = capsys.readouterr().out
    assert "Plan: not needed, by policy.plan off" in out
    assert "  plan:1  proposed, written" in out
    assert "    Add the button to `ui/form.tsx`, red." in out
    assert f"Approve it with `canopy plan {KEY} --approve`, or ask for changes with `canopy reply {KEY}`." in out

    c, headers = signed_in_client(ctx)
    comment = {"quote": "Add the button", "prefix": "", "suffix": "", "body": "Why red?"}
    assert c.post(f"/api/tickets/{KEY}/plan-threads", json=comment, headers=headers).status_code == 200
    proposed(ctx, "# Second\n\nBlue.\n")
    assert operator("plan", KEY, "--approve") == 0
    plans.path_for(ctx.state_dir, KEY, 2).write_text("# Second\n\nGreen.\n")
    capsys.readouterr()
    assert operator("show", KEY) == 0
    out = capsys.readouterr().out
    assert "  plan:2  approved, written" in out
    assert "edited since the planner wrote it; changed since it was approved" in out
    assert "    Green." in out
    assert "1 earlier plans: canopy show PROJ-1 --plans" in out
    assert "red." not in out

    assert operator("show", KEY, "--plans") == 0
    out = capsys.readouterr().out
    assert out.index("plan:1  superseded") < out.index("plan:2  approved")
    assert "comment 1, " in out
    assert 'on "Add the button":\n    Why red?' in out
    assert operator("show", "run:1", "--plans") == 2


def test_canopy_show_says_when_a_plan_is_needed_and_none_is_written(
    ctx: Context, canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    ctx.conn.commit()
    assert operator("plan", KEY) == 0
    capsys.readouterr()
    assert operator("show", KEY) == 0
    out = capsys.readouterr().out
    assert "Plan: needed, by your word, `plan`\n  none yet: the next tick dispatches a planner" in out
