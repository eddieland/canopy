"""Plans on disk and in the journal (DESIGN §25, ROADMAP M44).

Each plan is a file of its own, written once and never replaced, read bounded and without following a link, and approved
as its file stands, by its hash.
"""

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from canopy.core import conversation, db, plans
from canopy.core.context import DISPATCH_LOCK
from canopy.core.conversation import Refused
from canopy.core.vocab import PlanStatus
from tests.canopy.helpers import KEY, PLAN, plan_run, present, proposed
from tests.conftest import CanopyEnv


@pytest.fixture
def state_dir(canopy_env: CanopyEnv) -> Path:
    return canopy_env.state_dir


def test_a_plan_is_written_operator_only_and_recorded_with_its_hash(conn: sqlite3.Connection, state_dir: Path) -> None:
    run_id = plan_run(conn, state_dir)
    written = plans.write(state_dir, KEY, run_id, PLAN)
    path = state_dir / "plans" / KEY / f"{run_id}.md"
    assert plans.path_for(state_dir, KEY, run_id) == path
    assert path.read_text() == PLAN
    assert written == plans.Written(sha256=hashlib.sha256(PLAN.encode()).hexdigest(), size=len(PLAN.encode()))
    assert path.stat().st_mode & 0o777 == 0o600
    assert (state_dir / "plans").stat().st_mode & 0o777 == 0o700
    assert path.parent.stat().st_mode & 0o777 == 0o700
    # Nothing but the plan and its original, the same bytes kept as written, is left in the ticket's directory.
    original = path.with_name(f"{run_id}.original.md")
    assert sorted(p.name for p in path.parent.iterdir()) == sorted([path.name, original.name])
    assert original.read_text() == PLAN
    assert original.stat().st_mode & 0o777 == 0o600

    plan = plans.record(conn, KEY, run_id, written)
    assert (plan.status, plan.sha256, plan.size, plan.approved_at) == (PlanStatus.PROPOSED, written.sha256, 34, None)
    assert plans.current(conn, KEY) == plan
    assert plans.read(path) == plans.Reading(PLAN, written.sha256, written.size, None)


def test_a_name_already_taken_is_never_overwritten(conn: sqlite3.Connection, state_dir: Path) -> None:
    run_id = proposed(conn, state_dir)
    path = plans.path_for(state_dir, KEY, run_id)
    with pytest.raises(plans.PlanFileError, match=f"a plan named {run_id}.md is already there"):
        plans.write(state_dir, KEY, run_id, "# Another\n")
    assert path.read_text() == PLAN

    # Nor is a link at the name followed.
    other = plan_run(conn, state_dir)
    target = state_dir / "elsewhere.md"
    plans.path_for(state_dir, KEY, other).symlink_to(target)
    with pytest.raises(plans.PlanFileError, match="already there"):
        plans.write(state_dir, KEY, other, "# Another\n")
    assert not target.exists()
    assert sorted(p.name for p in path.parent.iterdir()) == sorted([path.name, f"{run_id}.original.md", f"{other}.md"])


@pytest.mark.parametrize("which", ["plans", "ticket"])
def test_a_symlinked_or_shared_directory_refuses_the_write(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
    which: str,
) -> None:
    run_id = plan_run(conn, state_dir)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    link = state_dir / "plans" if which == "plans" else state_dir / "plans" / KEY
    link.parent.mkdir(mode=0o700, exist_ok=True)
    link.symlink_to(elsewhere)
    with pytest.raises(plans.PlanFileError, match="is not a directory canopy made"):
        plans.write(state_dir, KEY, run_id, PLAN)
    assert list(elsewhere.iterdir()) == []

    link.unlink()
    link.mkdir(mode=0o700)
    link.chmod(0o750)
    with pytest.raises(plans.PlanFileError, match="is not private to you"):
        plans.write(state_dir, KEY, run_id, PLAN)
    assert list(link.iterdir()) == []


@pytest.mark.parametrize("key", ["../PROJ-1", "PROJ/1", ".", ""])
def test_a_path_is_built_only_from_a_ticket_key(state_dir: Path, key: str) -> None:
    with pytest.raises(ValueError, match="is not a ticket key"):
        plans.path_for(state_dir, key, 1)


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b"\xff\xfe not UTF-8", "not UTF-8"),
        (b" \n\t\n", "empty"),
        (("x" * (plans.MAX_CHARS + 1)).encode(), "over the bound"),
        # Over the bound in bytes too, so the read is cut inside a character.
        (("\N{GRINNING FACE}" * (plans.MAX_CHARS + 1)).encode(), "over the bound"),
    ],
)
def test_a_file_that_is_no_plan_reads_as_why_with_the_whole_files_hash(
    tmp_path: Path,
    content: bytes,
    problem: plans.Problem,
) -> None:
    path = tmp_path / "1.md"
    path.write_bytes(content)
    assert plans.read(path) == plans.Reading(None, hashlib.sha256(content).hexdigest(), len(content), problem)


def test_a_plan_at_the_bound_is_one(tmp_path: Path) -> None:
    path = tmp_path / "1.md"
    # Four bytes a character, the most UTF-8 takes.
    text = "\N{GRINNING FACE}" * plans.MAX_CHARS
    path.write_text(text)
    assert plans.read(path).text == text


def test_a_missing_linked_or_irregular_file_is_never_read_as_a_plan(tmp_path: Path) -> None:
    path = tmp_path / "1.md"
    assert plans.read(path) == plans.Reading(None, None, None, "missing")
    real = tmp_path / "real.md"
    real.write_text(PLAN)
    path.symlink_to(real)
    assert plans.read(path) == plans.Reading(None, None, None, "not a regular file")
    path.unlink()
    os.mkfifo(path)
    assert plans.read(path).problem == "not a regular file"
    path.unlink()
    path.mkdir()
    assert plans.read(path).problem == "not a regular file"


def test_a_new_plan_supersedes_the_current_one_and_history_keeps_both(
    conn: sqlite3.Connection,
    state_dir: Path,
) -> None:
    first = proposed(conn, state_dir)
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    second = proposed(conn, state_dir, "# Second\n")
    found = plans.history(conn, KEY)
    assert [(p.run_id, p.status) for p in found] == [(first, PlanStatus.SUPERSEDED), (second, PlanStatus.PROPOSED)]
    assert plans.current(conn, KEY) == found[1]
    # The superseded plan keeps its file and its approval.
    assert plans.path_for(state_dir, KEY, first).read_text() == PLAN
    assert found[0].approved_channel == "cli"
    # Another ticket's plans are its own.
    proposed(conn, state_dir, key="PROJ-2")
    assert plans.current(conn, KEY) == found[1]


def test_a_ticket_has_at_most_one_current_plan(conn: sqlite3.Connection, state_dir: Path) -> None:
    proposed(conn, state_dir)
    run_id = plan_run(conn, state_dir)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(
            "INSERT INTO plans (ticket_key, run_id, created_at, sha256, size) VALUES (?, ?, 'x', 'h', 1)",
            (KEY, run_id),
        )


def test_approval_takes_the_file_as_the_operator_left_it(conn: sqlite3.Connection, state_dir: Path) -> None:
    run_id = proposed(conn, state_dir)
    path = plans.path_for(state_dir, KEY, run_id)
    edited = PLAN + "\n## Out of scope\n\nThe UI.\n"
    path.write_text(edited)

    plan = plans.approve(conn, state_dir, KEY, channel="web", dispatch_lock=state_dir / DISPATCH_LOCK)
    assert plan.status is PlanStatus.APPROVED
    assert (plan.approved_sha256, plan.approved_channel) == (hashlib.sha256(edited.encode()).hexdigest(), "web")
    # What the planner wrote is kept beside it, so the edit shows.
    assert plan.sha256 == hashlib.sha256(PLAN.encode()).hexdigest()
    assert plans.approved_text(state_dir, plan) == edited


def test_an_edit_after_approval_needs_approving_again(conn: sqlite3.Connection, state_dir: Path) -> None:
    run_id = proposed(conn, state_dir)
    plan = plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    with pytest.raises(Refused, match="bad_plan: plan 1 of PROJ-1 is approved, and its file has not changed since"):
        plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)

    path = plans.path_for(state_dir, KEY, run_id)
    path.write_text("# Changed\n")
    assert plans.approved_text(state_dir, plan) is None
    again = plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    assert plans.approved_text(state_dir, again) == "# Changed\n"

    path.unlink()
    assert plans.approved_text(state_dir, again) is None
    with pytest.raises(Refused, match=f"bad_plan: plan 1's file {path} is missing, so it cannot be approved"):
        plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)


def test_an_approval_with_a_note_writes_it_on_the_ticket_for_the_implement(
    conn: sqlite3.Connection,
    state_dir: Path,
) -> None:
    proposed(conn, state_dir)
    lock = state_dir / DISPATCH_LOCK
    for note, why in (
        ("  ", "the note is empty"),
        ("x" * (plans.MAX_NOTE + 1), "the note is 3801 characters; the most is 3800"),
    ):
        with pytest.raises(Refused, match=f"bad_body: {why}"):
            plans.approve(conn, state_dir, KEY, channel="web", dispatch_lock=lock, note=note)
    # A refused note approves nothing and says nothing.
    assert present(plans.current(conn, KEY)).status is PlanStatus.PROPOSED
    assert conversation.operator_messages_after(conn, KEY, 0) == []

    plan = plans.approve(conn, state_dir, KEY, channel="web", dispatch_lock=lock, note=" Keep the old flag. \n")
    assert plan.status is PlanStatus.APPROVED
    [said] = conversation.operator_messages_after(conn, KEY, 0)
    assert said.body == (
        f"Plan {plan.id} is approved. Follow it with these notes, which come first where the two differ:\n\n"
        "Keep the old flag."
    )
    assert said.channel == "web"
    # The verb's instruction: it answers no question, and, after the approval, asks for no changes.
    assert not conversation.answers_questions(said)
    assert plans.changes_asked(conn, present(db.get_ticket(conn, KEY))) is None

    # Approved again after an edit, with a note of its own.
    plans.path_for(state_dir, KEY, plan.run_id).write_text("# Changed\n")
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=lock, note="Keep the old flag.")
    assert len(conversation.operator_messages_after(conn, KEY, 0)) == 2


def test_approval_refuses_no_plan_and_a_file_that_is_no_longer_one(conn: sqlite3.Connection, state_dir: Path) -> None:
    with pytest.raises(Refused, match="bad_plan: PROJ-1 has no plan waiting to be approved"):
        plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    run_id = proposed(conn, state_dir)
    plans.path_for(state_dir, KEY, run_id).write_text("x" * (plans.MAX_CHARS + 1))
    with pytest.raises(Refused, match="is over the bound, so it cannot be approved"):
        plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    current = present(plans.current(conn, KEY))
    assert current.status is PlanStatus.PROPOSED
    # A proposed plan is never text a worker gets.
    assert plans.approved_text(state_dir, current) is None


def test_superseding_leaves_the_ticket_with_no_current_plan(conn: sqlite3.Connection, state_dir: Path) -> None:
    with db.transaction(conn):
        assert plans.supersede(conn, KEY) is None
    proposed(conn, state_dir)
    with db.transaction(conn):
        assert plans.supersede(conn, KEY) == 1
    assert plans.current(conn, KEY) is None


def test_forgetting_a_ticket_supersedes_its_plan_and_keeps_the_file(conn: sqlite3.Connection, state_dir: Path) -> None:
    run_id = proposed(conn, state_dir)
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    with db.transaction(conn):
        db.forget_ticket(conn, KEY, channel="cli", branch=None, prs=[])
    assert plans.current(conn, KEY) is None
    assert [p.status for p in plans.history(conn, KEY)] == [PlanStatus.SUPERSEDED]
    assert plans.path_for(state_dir, KEY, run_id).read_text() == PLAN
