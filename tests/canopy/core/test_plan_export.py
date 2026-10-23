"""Plans exported into a directory of the operator's (DESIGN §25): every plan, as its file stands, under its row."""

import json
import os
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import conversation, db, feedback_items, feedback_plans, plan_export, plans, records, run_models
from canopy.core.context import DISPATCH_LOCK
from canopy.core.vocab import ModelsRead, PlanStatus
from canopy.runtime.report import ModelUse
from tests.canopy.helpers import KEY, PLAN, PLAN_PROMPT, operator, plan_prompt, plan_run, prompted, proposed
from tests.conftest import CanopyEnv


@pytest.fixture
def state_dir(canopy_env: CanopyEnv) -> Path:
    return canopy_env.state_dir


def front_matter(path: Path) -> tuple[dict[str, object], str]:
    """An exported file's front matter, each value read as JSON, and the text below it."""
    _, head, text = path.read_text().split("---\n", 2)
    keys = dict(line.split(": ", 1) for line in head.splitlines())
    return {k: json.loads(v) for k, v in keys.items()}, text.removeprefix("\n")


def file_of(dest: Path, key: str, run_id: int) -> Path:
    """The one file exported for the plan of run `run_id`, whatever its status and title name it."""
    [path] = (dest / key).glob(f"{run_id}-*.md")
    return path


def feedback_plan(conn: sqlite3.Connection, state_dir: Path, text: str) -> int:
    """Write and record a feedback plan for `KEY`, covering no items. Returns its run's id."""
    run_id = plan_run(conn, state_dir)
    written = plans.write(state_dir, KEY, run_id, text)
    snapshot = feedback_items.Snapshot(heads={}, checks={}, given=())
    feedback_plans.record(conn, KEY, run_id, written, [], snapshot=snapshot)
    return run_id


def test_every_plan_is_exported_with_its_row(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    first = proposed(conn, state_dir)
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    second = proposed(conn, state_dir, f"# Plan: {KEY} Export reports as CSV\n")
    other = proposed(conn, state_dir, "# Other's\n", key="PROJ-2")
    feedback = feedback_plan(conn, state_dir, f"# Feedback plan: {KEY} Export reports as CSV\n")
    dest = tmp_path / "archive"

    exported = plan_export.export(conn, state_dir, dest)

    # Each named for its run, its status, and its title, less the planner's `Plan: KEY`; PLAN's title is that alone.
    assert exported == plan_export.Exported(
        written=[
            f"{KEY}/{first}-SUPERSEDED.md",
            f"{KEY}/{second}-PROPOSED-export-reports-as-csv.md",
            f"{KEY}/{feedback}-PROPOSED-feedback-export-reports-as-csv.md",
            f"PROJ-2/{other}-PROPOSED-other-s.md",
        ],
        unchanged=0,
        skipped=[],
    )
    meta, text = front_matter(dest / KEY / f"{first}-SUPERSEDED.md")
    [row, _] = plans.history(conn, KEY)
    assert text == PLAN
    assert meta == {
        "kind": "plan",
        "id": row.id,
        "ticket_key": KEY,
        "run_id": first,
        "created_at": row.created_at,
        "status": "superseded",
        "sha256": row.sha256,
        "size": row.size,
        "approved_sha256": row.sha256,
        "approved_at": row.approved_at,
        "approved_channel": "cli",
    }
    meta, text = front_matter(file_of(dest, KEY, feedback))
    assert (meta["kind"], meta["status"], text) == (
        "feedback plan",
        "proposed",
        f"# Feedback plan: {KEY} Export reports as CSV\n",
    )
    # Operator-only, as the plans it copies.
    assert dest.stat().st_mode & 0o777 == 0o700
    assert (dest / KEY).stat().st_mode & 0o777 == 0o700
    assert file_of(dest, KEY, first).stat().st_mode & 0o777 == 0o600
    assert len(list((dest / KEY).iterdir())) == 3


def test_an_export_rewrites_only_what_changed(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    first = proposed(conn, state_dir)
    second = proposed(conn, state_dir, key="PROJ-2")
    dest = tmp_path / "archive"
    plan_export.export(conn, state_dir, dest)

    assert plan_export.export(conn, state_dir, dest) == plan_export.Exported(written=[], unchanged=2, skipped=[])

    # The operator edits a plan's title, then approves it: each moves it to a new name, and only its earlier one goes.
    plans.path_for(state_dir, KEY, first).write_text("# Edited\n")
    exported = plan_export.export(conn, state_dir, dest)
    assert (exported.written, exported.removed) == (
        [f"{KEY}/{first}-PROPOSED-edited.md"],
        [f"{KEY}/{first}-PROPOSED.md"],
    )
    plans.approve(conn, state_dir, KEY, channel="web", dispatch_lock=state_dir / DISPATCH_LOCK)
    exported = plan_export.export(conn, state_dir, dest)
    assert (exported.written, exported.removed, exported.unchanged) == (
        [f"{KEY}/{first}-APPROVED-edited.md"],
        [f"{KEY}/{first}-PROPOSED-edited.md"],
        1,
    )
    assert [p.name for p in (dest / KEY).iterdir()] == [f"{first}-APPROVED-edited.md"]
    meta, text = front_matter(dest / KEY / f"{first}-APPROVED-edited.md")
    assert (meta["status"], meta["approved_channel"], text) == ("approved", "web", "# Edited\n")
    assert front_matter(dest / "PROJ-2" / f"{second}-PROPOSED.md")[0]["status"] == "proposed"


def test_a_plan_names_its_planners_persona_and_models(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    db.touch_ticket(conn, KEY, "/ws")
    tick_id = db.start_tick(conn, dry_run=False)
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key=KEY,
        kind="plan",
        branch="",
        slots=[],
        runs_dir=state_dir,
        persona="skeptic",
        persona_digest="0" * 64,
        persona_text="Doubt everything.\n",
        model="anthropic/claude-x@high",
    )
    plans.record(conn, KEY, run_id, plans.write(state_dir, KEY, run_id, PLAN))
    # A run from before canopy recorded its persona or chose its model has neither in its front matter.
    older = proposed(conn, state_dir, key="PROJ-2")
    dest = tmp_path / "archive"

    plan_export.export(conn, state_dir, dest)

    meta, text = front_matter(file_of(dest, KEY, run_id))
    assert (meta["persona"], meta["model"], text) == ("skeptic", "anthropic/claude-x@high", PLAN)
    # Until its session is read, nothing says which models wrote it.
    assert "models" not in meta
    assert {"persona", "model", "models"}.isdisjoint(front_matter(file_of(dest, "PROJ-2", older))[0])

    # The read lands after the plan was archived, so the next export rewrites it, the most costly model first.
    due = run_models.Due("runs", run_id, "ses_1", attempts=0)
    used = [ModelUse("anthropic/claude-y", 1, 0.1), ModelUse("anthropic/claude-x@high", 3, 0.5)]
    run_models.record(conn, due, ModelsRead.FOUND, used)

    assert plan_export.export(conn, state_dir, dest).written == [f"{KEY}/{file_of(dest, KEY, run_id).name}"]
    meta, _ = front_matter(file_of(dest, KEY, run_id))
    assert meta["models"] == ["anthropic/claude-x@high", "anthropic/claude-y"]


def test_only_a_plans_own_earlier_names_are_removed(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    run_id = proposed(conn, state_dir)
    dest = tmp_path / "archive"
    (dest / KEY).mkdir(parents=True)
    # As exports before names carried a status, before it was capitalized, and before it was in capitals, wrote it,
    # and as an export cut short by a failed removal left one.
    (dest / KEY / f"{run_id}.md").write_text("old\n")
    (dest / KEY / f"{run_id}-approved.md").write_text("old\n")
    (dest / KEY / f"{run_id}-Approved-old-title.md").write_text("old\n")
    (dest / KEY / f"{run_id}-APPROVED-old-title.md").write_text("old\n")
    # Not names an export gives this plan: another run's, and the operator's own.
    kept = [
        f"{run_id}0-proposed.md",
        f"{run_id}-notes.md",
        f"{run_id}-PROPOSED.txt",
        f"{run_id}-ApProVed.md",
        "README.md",
    ]
    for name in kept:
        (dest / KEY / name).write_text("theirs\n")

    exported = plan_export.export(conn, state_dir, dest)

    assert exported.written == [f"{KEY}/{run_id}-PROPOSED.md"]
    assert sorted(exported.removed) == [
        f"{KEY}/{run_id}-APPROVED-old-title.md",
        f"{KEY}/{run_id}-Approved-old-title.md",
        f"{KEY}/{run_id}-approved.md",
        f"{KEY}/{run_id}.md",
    ]
    assert sorted(p.name for p in (dest / KEY).iterdir()) == sorted([*kept, f"{run_id}-PROPOSED.md"])


def test_a_name_that_is_the_plans_own_file_is_not_removed(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    run_id = prompted(conn, state_dir)
    dest = tmp_path / "archive"
    plan_export.export(conn, state_dir, dest)
    # As a filesystem that ignores case shows the plan's file, and its prompt, under the names an export gave before.
    (dest / KEY / f"{run_id}-proposed.md").hardlink_to(dest / KEY / f"{run_id}-PROPOSED.md")
    (dest / KEY / f"{run_id}-prompt.md").hardlink_to(dest / KEY / f"{run_id}-PROMPT.md")
    # Another name for the same file that differs by more than case is not one an earlier export left.
    (dest / KEY / f"{run_id}-Approved.md").hardlink_to(dest / KEY / f"{run_id}-PROPOSED.md")

    exported = plan_export.export(conn, state_dir, dest)

    # Said to be gone, as such a filesystem would have it, but not removed, which would remove the file itself.
    assert (exported.written, exported.unchanged) == ([], 1)
    assert exported.removed == [f"{KEY}/{run_id}-proposed.md", f"{KEY}/{run_id}-prompt.md"]
    assert (dest / KEY / f"{run_id}-proposed.md").exists()
    assert front_matter(dest / KEY / f"{run_id}-PROPOSED.md")[1] == PLAN


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        (f"# Plan: {KEY} Export reports as CSV", "-export-reports-as-csv"),
        (f"# Plan: {KEY.lower()}: Export reports, as CSV #", "-export-reports-as-csv"),
        ("# Café crème: ../../etc/passwd", "-cafe-creme-etc-passwd"),
        ("# Plan", ""),
        ("# Plan the migration", "-plan-the-migration"),
        (f"# Plan: {KEY}2 Next", f"-{KEY.lower()}2-next"),
        (f"# Plan: {KEY}", ""),
        # A title on the line under a heading of the key alone, as a planner may write the outline.
        (f"# Plan: {KEY}\n\nExport reports as CSV", "-export-reports-as-csv"),
        (f"# Feedback plan: {KEY} -\n**Export reports**", "-export-reports"),
        ("# Plan\n\nAdd the endpoint.", ""),
        ("# 日本語", ""),
        ("## Goal", ""),
        ("# " + "word " * 30, "-" + "-".join(["word"] * 12)),
    ],
)
def test_a_name_carries_a_slug_of_the_title(heading: str, slug: str) -> None:
    plan = records.Plan(
        id=1,
        ticket_key=KEY,
        run_id=7,
        created_at="2026-10-21T00:00:00Z",
        status=PlanStatus.PROPOSED,
        sha256="ab",
        size=3,
        approved_sha256=None,
        approved_at=None,
        approved_channel=None,
        approved_reason=None,
        effort=None,
    )
    assert plan_export.name("plan", plan, f"{heading}\n\n## Goal\n") == f"7-PROPOSED{slug}.md"


def test_a_plan_with_no_title_of_its_own_takes_its_tickets(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    untitled = proposed(conn, state_dir, f"# Plan: {KEY}\n\n## Goal\n")
    titled = proposed(conn, state_dir, "# Its own\n", key="PROJ-2")
    db.set_ticket(conn, KEY, "/ws", title="Export reports\nas CSV")
    db.set_ticket(conn, "PROJ-2", "/ws", title="Not this one")
    dest = tmp_path / "archive"

    exported = plan_export.export(conn, state_dir, dest)

    assert exported.written == [
        f"{KEY}/{untitled}-PROPOSED-export-reports-as-csv.md",
        f"PROJ-2/{titled}-PROPOSED-its-own.md",
    ]
    # The ticket retitled moves the plan named for it, and leaves the one with its own title.
    db.set_ticket(conn, KEY, "/ws", title="Export as JSON")
    db.set_ticket(conn, "PROJ-2", "/ws", title="Nor this one")
    exported = plan_export.export(conn, state_dir, dest)
    assert (exported.written, exported.removed) == (
        [f"{KEY}/{untitled}-PROPOSED-export-as-json.md"],
        [f"{KEY}/{untitled}-PROPOSED-export-reports-as-csv.md"],
    )


def test_each_plan_has_its_prompt_beside_it(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    first = prompted(conn, state_dir)
    feedback = feedback_plan(conn, state_dir, "# Feedback plan\n")
    plan_prompt(conn, feedback).write_text("Plan the feedback.\n")
    # A plan from before prompts were kept has none to export.
    bare = proposed(conn, state_dir, key="PROJ-2")
    dest = tmp_path / "archive"

    exported = plan_export.export(conn, state_dir, dest)

    assert exported.written == [
        f"{KEY}/{first}-PROPOSED.md",
        f"{KEY}/{first}-PROMPT.md",
        f"{KEY}/{feedback}-PROPOSED-feedback.md",
        f"{KEY}/{feedback}-PROMPT.md",
        f"PROJ-2/{bare}-PROPOSED.md",
    ]
    # Its bytes as the run was given them, operator-only as the plans are.
    assert (dest / KEY / f"{first}-PROMPT.md").read_text() == PLAN_PROMPT
    assert (dest / KEY / f"{first}-PROMPT.md").stat().st_mode & 0o777 == 0o600
    assert (dest / KEY / f"{feedback}-PROMPT.md").read_text() == "Plan the feedback.\n"
    # A prompt never changes, so neither does its name when its plan's status does.
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    assert plan_export.export(conn, state_dir, dest).written == [f"{KEY}/{first}-APPROVED.md"]
    assert plan_export.is_prompt(f"{first}-PROMPT.md")
    assert plan_export.is_prompt(f"{first}-prompt.md")
    assert not plan_export.is_prompt(f"{first}-APPROVED-improve-the-PROMPT.md")


def test_a_prompt_exported_in_lowercase_is_renamed(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    run_id = prompted(conn, state_dir)
    dest = tmp_path / "archive"
    plan_export.export(conn, state_dir, dest)
    # As an export before prompts' names were in capitals wrote it.
    (dest / KEY / f"{run_id}-PROMPT.md").rename(dest / KEY / f"{run_id}-prompt.md")

    exported = plan_export.export(conn, state_dir, dest)

    assert (exported.written, exported.removed) == ([f"{KEY}/{run_id}-PROMPT.md"], [f"{KEY}/{run_id}-prompt.md"])
    assert sorted(p.name for p in (dest / KEY).iterdir()) == [f"{run_id}-PROMPT.md", f"{run_id}-PROPOSED.md"]
    # Back beside its new name, as an older canopy might write it, it goes even where the plan is as it stands.
    (dest / KEY / f"{run_id}-prompt.md").write_text(PLAN_PROMPT)
    exported = plan_export.export(conn, state_dir, dest)
    assert (exported.written, exported.removed) == ([], [f"{KEY}/{run_id}-prompt.md"])


def test_an_earlier_name_that_cannot_be_statted_is_left(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    run_id = proposed(conn, state_dir)
    dest = tmp_path / "archive"
    (dest / KEY).mkdir(parents=True)
    (dest / KEY / f"{run_id}-Proposed.md").write_text("old\n")
    real_stat = os.stat

    def stat(path: str, **kwargs: object) -> os.stat_result:
        if path == f"{run_id}-Proposed.md":
            raise PermissionError(path)
        return real_stat(path, **kwargs)  # pyrefly: ignore[bad-argument-type]

    with mock.patch.object(os, "stat", side_effect=stat):
        exported = plan_export.export(conn, state_dir, dest)

    assert (exported.written, exported.removed) == ([f"{KEY}/{run_id}-PROPOSED.md"], [])
    assert (dest / KEY / f"{run_id}-Proposed.md").read_text() == "old\n"


def test_prompts_off_exports_plans_alone(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    run_id = prompted(conn, state_dir)
    dest = tmp_path / "archive"

    exported = plan_export.export(conn, state_dir, dest, prompts=False)

    assert exported.written == [f"{KEY}/{run_id}-PROPOSED.md"]
    # Turned on again, the prompt goes in beside the plan, which is as it stands.
    exported = plan_export.export(conn, state_dir, dest)
    assert (exported.written, exported.unchanged) == ([f"{KEY}/{run_id}-PROMPT.md"], 1)


def test_a_prompt_outside_the_state_directory_or_through_a_link_is_not_exported(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    linked = proposed(conn, state_dir)
    outside = proposed(conn, state_dir, key="PROJ-2")
    secret = tmp_path / "secret.txt"
    secret.write_text("not a prompt\n")
    plan_prompt(conn, linked).symlink_to(secret)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    conn.execute("UPDATE runs SET log_path = ? WHERE id = ?", (str(elsewhere / f"{outside}.log"), outside))
    (elsewhere / f"{outside}.prompt").write_text("not canopy's\n")
    dest = tmp_path / "archive"

    exported = plan_export.export(conn, state_dir, dest)

    assert exported.written == [f"{KEY}/{linked}-PROPOSED.md", f"PROJ-2/{outside}-PROPOSED.md"]


def said(
    conn: sqlite3.Connection,
    key: str = KEY,
    *,
    body: str = "Done.",
    source: str = "worker",
    kind: str = "report",
    channel: str = "run",
    run_id: int | None = None,
    answers: int | None = None,
    comment: db.Comment | None = None,
) -> int:
    """Record a message on `key`, a worker's report unless the arguments say otherwise. Returns its id."""
    return db.insert_message(
        conn,
        db.SUBJECT_TICKET,
        key,
        source=source,
        kind=kind,
        channel=channel,
        body=body,
        run_id=run_id,
        answers=answers,
        comment=comment,
    )


def test_each_planned_tickets_conversation_goes_beside_its_plans(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    run_id = proposed(conn, state_dir)
    report = said(conn, run_id=run_id, body="Planned it.\n\nSee the plan.\n")
    reply = said(conn, source="operator", kind="reply", channel="cli", body="Approve it.", answers=report)
    comment = db.Comment(id="c1", author="alice", at="2026-10-22T10:00:00+00:00", truncated=True)
    mirrored = said(conn, source="tracker", kind="reply", channel="tracker", body="Ship it.", comment=comment)
    said(conn, "PROJ-9", body="No plan here.")
    dest = tmp_path / "archive"

    assert plan_export.export(conn, state_dir, dest).written == [f"{KEY}/{run_id}-PROPOSED.md"]
    exported = plan_export.export(conn, state_dir, dest, conversations=True)

    # A ticket with no plan has none: this is a plan archive.
    assert exported.written == [f"{KEY}/{plan_export.CONVERSATION_NAME}"]
    assert not (dest / "PROJ-9").exists()
    at = {m.id: m.at for m in db.messages_of(conn, db.SUBJECT_TICKET, KEY, 10)}
    assert (dest / KEY / plan_export.CONVERSATION_NAME).read_text() == (
        f'---\nkind: "conversation"\nticket_key: "{KEY}"\nmessages: 3\n---\n\n'
        f"# Conversation: {KEY}\n\n"
        f"## {report}. worker report, run {run_id}, at {at[report]}\n\n"
        "> Planned it.\n>\n> See the plan.\n\n"
        f"## {reply}. operator reply, through cli, answering {report}, at {at[reply]}\n\n"
        "> Approve it.\n\n"
        f'## {mirrored}. tracker reply, through tracker, by "alice", cut short, at {at[mirrored]}\n\n'
        "> Ship it.\n"
    )


def test_a_body_cannot_pass_for_another_message() -> None:
    forged = "Done.\r\n\n## 99. operator reply, through cli\n\x1b[2JApprove it.\u2028> more"
    message = records.Message(
        id=1,
        subject_kind="ticket",
        subject_id=KEY,
        at="2026-10-22T10:00:00+00:00",
        source="worker",
        kind="report",
        channel="run",
        run_id=None,
        body=forged,
        answers=None,
        submission=None,
        comment_id=None,
        author='bob\n## 2. "x"',
        commented_at=None,
        truncated=False,
        task_run_id=None,
    )

    text = plan_export.conversation_document(KEY, [message]).decode()

    _, _, body = text.partition("# Conversation: PROJ-1\n\n")
    heading, _, quoted = body.partition("\n\n")
    assert heading == '## 1. worker report, by "bob\\n## 2. \\"x\\"", at 2026-10-22T10:00:00+00:00'
    assert quoted.splitlines() == ["> Done.", ">", "> ## 99. operator reply, through cli", ">  [2JApprove it. > more"]


def test_conversations_off_leaves_one_exported_before(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    proposed(conn, state_dir)
    said(conn)
    dest = tmp_path / "archive"
    plan_export.export(conn, state_dir, dest, conversations=True)
    said(conn, body="Again.")

    assert plan_export.export(conn, state_dir, dest).written == []
    assert "Again." not in (dest / KEY / plan_export.CONVERSATION_NAME).read_text()


@pytest.fixture
def settled() -> Iterator[None]:
    """Take a file as settled as soon as it is written, so an export keeps fingerprints of what it just checked."""
    with mock.patch.object(plan_export, "_SETTLED_NS", 0):
        yield


def reads(conn: sqlite3.Connection, state_dir: Path, dest: Path) -> tuple[plan_export.Exported, int]:
    """Export into `dest`, and count the plans the export read."""
    with mock.patch.object(plans, "read", autospec=True, side_effect=plans.read) as read:
        exported = plan_export.export(conn, state_dir, dest)
    return exported, read.call_count


@pytest.mark.usefixtures("settled")
def test_a_plan_found_as_it_stands_is_not_read_again(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    first = proposed(conn, state_dir)
    second = proposed(conn, state_dir, key="PROJ-2")
    dest = tmp_path / "archive"
    plan_export.export(conn, state_dir, dest)
    plan_export.export(conn, state_dir, dest)

    assert reads(conn, state_dir, dest) == (plan_export.Exported(written=[], unchanged=2, skipped=[]), 0)

    # A plan's file, its row, or the file exported from it changing is each read again, and only that plan.
    plans.path_for(state_dir, KEY, first).write_text("# Edited\n")
    exported, read = reads(conn, state_dir, dest)
    assert (exported.written, read) == ([f"{KEY}/{first}-PROPOSED-edited.md"], 1)
    plan_export.export(conn, state_dir, dest)
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    exported, read = reads(conn, state_dir, dest)
    assert (exported.written, read) == ([f"{KEY}/{first}-APPROVED-edited.md"], 1)
    plan_export.export(conn, state_dir, dest)
    (dest / "PROJ-2" / f"{second}-PROPOSED.md").write_text("The operator's edit.\n")
    exported, read = reads(conn, state_dir, dest)
    assert (exported.written, read) == ([f"PROJ-2/{second}-PROPOSED.md"], 1)
    assert front_matter(dest / "PROJ-2" / f"{second}-PROPOSED.md")[1] == PLAN
    # A copy of the plan under another of its names is read, and removed.
    (dest / "PROJ-2" / f"{second}.md").write_text("A stray copy.\n")
    exported, read = reads(conn, state_dir, dest)
    assert (exported.removed, read) == ([f"PROJ-2/{second}.md"], 1)

    # So is a plan whose prompt's export changed, and its prompt written again.
    plan_prompt(conn, first).write_text(PLAN_PROMPT)
    plan_export.export(conn, state_dir, dest)
    plan_export.export(conn, state_dir, dest)
    assert reads(conn, state_dir, dest)[1] == 0
    (dest / KEY / f"{first}-PROMPT.md").write_text("The operator's edit.\n")
    exported, read = reads(conn, state_dir, dest)
    assert (exported.written, read) == ([f"{KEY}/{first}-PROMPT.md"], 1)
    assert (dest / KEY / f"{first}-PROMPT.md").read_text() == PLAN_PROMPT

    # Fingerprints that cannot be read are none: every plan is read again.
    [kept] = (state_dir / plan_export.SEEN_DIR).iterdir()
    kept.write_text("{")
    assert reads(conn, state_dir, dest) == (plan_export.Exported(written=[], unchanged=2, skipped=[]), 2)


@pytest.mark.usefixtures("settled")
def test_a_conversation_is_read_again_only_when_it_or_its_export_changed(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    proposed(conn, state_dir)
    said(conn)
    dest = tmp_path / "archive"
    exported = dest / KEY / plan_export.CONVERSATION_NAME

    def export() -> tuple[plan_export.Exported, int]:
        document = plan_export.conversation_document
        with mock.patch.object(plan_export, "conversation_document", autospec=True, side_effect=document) as read:
            done = plan_export.export(conn, state_dir, dest, conversations=True)
        return done, read.call_count

    export()
    export()
    assert export() == (plan_export.Exported(written=[], unchanged=2, skipped=[]), 0)

    said(conn, body="Again.")
    assert export() == (plan_export.Exported(written=[f"{KEY}/CONVERSATION.md"], unchanged=1, skipped=[]), 1)
    assert exported.read_text().endswith("> Again.\n")
    export()
    assert export()[1] == 0

    exported.write_text("The operator's edit.\n")
    assert export() == (plan_export.Exported(written=[f"{KEY}/CONVERSATION.md"], unchanged=1, skipped=[]), 1)
    assert exported.read_text().endswith("> Again.\n")


def test_a_file_changed_just_now_is_read_again(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    # It could change again within the same tick of the filesystem's clock, leaving its stat as it was. An hour stands
    # for "just now", so a slow machine cannot settle the files between the exports.
    proposed(conn, state_dir)
    dest = tmp_path / "archive"
    with mock.patch.object(plan_export, "_SETTLED_NS", 3600 * 10**9):
        plan_export.export(conn, state_dir, dest)
        plan_export.export(conn, state_dir, dest)

        assert reads(conn, state_dir, dest)[1] == 1
    assert not (state_dir / plan_export.SEEN_DIR).exists()


def test_a_limit_leaves_the_rest_for_the_next_export(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    first = proposed(conn, state_dir)
    second = proposed(conn, state_dir, "# Second\n")
    other = proposed(conn, state_dir, key="PROJ-2")
    dest = tmp_path / "archive"

    assert plan_export.export(conn, state_dir, dest, limit=2) == plan_export.Exported(
        written=[f"{KEY}/{first}-SUPERSEDED.md", f"{KEY}/{second}-PROPOSED-second.md"],
        unchanged=0,
        skipped=[],
        left=1,
    )
    assert plan_export.export(conn, state_dir, dest, limit=2) == plan_export.Exported(
        written=[f"PROJ-2/{other}-PROPOSED.md"],
        unchanged=2,
        skipped=[],
    )


def test_a_limit_counts_a_conversation_as_a_file(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    run_id = proposed(conn, state_dir)
    said(conn)
    dest = tmp_path / "archive"

    assert plan_export.export(conn, state_dir, dest, limit=1, conversations=True) == plan_export.Exported(
        written=[f"{KEY}/{run_id}-PROPOSED.md"],
        unchanged=0,
        skipped=[],
        left=1,
    )
    assert plan_export.export(conn, state_dir, dest, limit=1, conversations=True) == plan_export.Exported(
        written=[f"{KEY}/CONVERSATION.md"],
        unchanged=1,
        skipped=[],
    )


def test_a_plan_whose_file_is_gone_is_skipped_and_nothing_exported_is_removed(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    run_id = proposed(conn, state_dir)
    dest = tmp_path / "archive"
    plan_export.export(conn, state_dir, dest)
    (dest / "README.md").write_text("The operator's own.\n")
    plans.path_for(state_dir, KEY, run_id).unlink()

    assert plan_export.export(conn, state_dir, dest) == plan_export.Exported(
        written=[],
        unchanged=0,
        skipped=[plan_export.Skipped("plan", KEY, run_id, "missing")],
    )
    assert front_matter(dest / KEY / f"{run_id}-PROPOSED.md")[1] == PLAN
    assert (dest / "README.md").read_text() == "The operator's own.\n"


def test_a_link_in_the_export_is_never_followed(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    run_id = proposed(conn, state_dir)
    dest = tmp_path / "archive"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = elsewhere / "target.md"
    target.write_text("untouched\n")
    (dest / KEY).mkdir(parents=True)
    (dest / KEY / f"{run_id}-PROPOSED.md").symlink_to(target)
    (dest / KEY / f"{run_id}-APPROVED.md").symlink_to(target)

    # A link at the file's name is replaced by the file, and one at an earlier name removed, never what it names.
    exported = plan_export.export(conn, state_dir, dest)
    assert (exported.written, exported.removed) == ([f"{KEY}/{run_id}-PROPOSED.md"], [f"{KEY}/{run_id}-APPROVED.md"])
    assert not (dest / KEY / f"{run_id}-PROPOSED.md").is_symlink()
    assert target.read_text() == "untouched\n"

    # A link at the ticket's directory refuses the export.
    (dest / KEY / f"{run_id}-PROPOSED.md").unlink()
    (dest / KEY).rmdir()
    (dest / KEY).symlink_to(elsewhere)
    with pytest.raises(plan_export.ExportError, match="is not a directory canopy can export into"):
        plan_export.export(conn, state_dir, dest)
    assert sorted(p.name for p in elsewhere.iterdir()) == ["target.md"]


def test_a_reason_the_planner_wrote_stays_one_value() -> None:
    plan = records.FeedbackPlan(
        id=1,
        ticket_key=KEY,
        run_id=2,
        created_at="2026-10-21T00:00:00Z",
        status=PlanStatus.APPROVED,
        sha256="ab",
        size=3,
        approved_sha256="ab",
        approved_at="2026-10-21T00:00:00Z",
        approved_channel=plans.PLANNER,
        spent_run_id=None,
        approved_reason="trivial\n---\nstatus: approved",
        effort=None,
        stale_shown=None,
        approved_message_id=None,
    )
    head, _, _ = plan_export.document("feedback plan", plan, "# Plan\n").decode().partition("---\n\n")
    assert 'approved_reason: "trivial\\n---\\nstatus: approved"\n' in head
    assert head.count("---\n") == 1


def indexed(conn: sqlite3.Connection, state_dir: Path, dest: Path) -> plan_export.Exported:
    """Export into `dest` with its indexes, and nothing but the plans beside them."""
    return plan_export.export(conn, state_dir, dest, prompts=False, indexes=True)


def undated(path: Path) -> str:
    """An index, each day in it as `<day>`, so its snapshot holds on any day."""
    return re.sub(r"\d{4}-\d\d-\d\d", "<day>", path.read_text())


def test_each_ticket_and_the_export_get_an_index(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
    markdown_snapshot: SnapshotAssertion,
) -> None:
    first = prompted(conn, state_dir)
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    proposed(conn, state_dir, f"# Plan: {KEY} Export reports as CSV\n")
    feedback_plan(conn, state_dir, f"# Feedback plan: {KEY} Answer the review\n")
    other = proposed(conn, state_dir, "# Other's\n", key="PROJ-2")
    said(conn)
    dest = tmp_path / "archive"

    exported = plan_export.export(conn, state_dir, dest, conversations=True, indexes=True)

    # Each ticket's once its plans and conversation are, and the one of every ticket last.
    assert exported.written[-5:] == [
        f"{KEY}/CONVERSATION.md",
        f"{KEY}/README.md",
        f"PROJ-2/{other}-PROPOSED-other-s.md",
        "PROJ-2/README.md",
        "README.md",
    ]
    assert undated(dest / KEY / "README.md") == markdown_snapshot
    assert undated(dest / "README.md") == markdown_snapshot
    assert (dest / KEY / f"{first}-PROMPT.md").exists()
    assert (dest / "README.md").stat().st_mode & 0o777 == 0o600

    # An index is the same bytes for the same plans, so it is written again only when one of them changed.
    again = plan_export.export(conn, state_dir, dest, conversations=True, indexes=True)
    assert again.written == []
    plans.approve(conn, state_dir, "PROJ-2", channel="web", dispatch_lock=state_dir / DISPATCH_LOCK)
    exported = plan_export.export(conn, state_dir, dest, conversations=True, indexes=True)
    assert exported.written == [f"PROJ-2/{other}-APPROVED-other-s.md", "PROJ-2/README.md", "README.md"]


def test_a_title_shows_in_an_index_as_text_alone(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    run_id = proposed(conn, state_dir, f"# Plan: {KEY} [Click](https://example.com) <img src=x> | &amp; *now*\n")
    dest = tmp_path / "archive"

    indexed(conn, state_dir, dest)

    # Never inside a link's text, where a renderer that reads escapes loosely could still find a link of its own.
    title = r"\[Click\]\(https://example.com\) \<img src=x\> \| \&amp; \*now\*"
    exported = f"{run_id}-PROPOSED-click-https-example-com-img-src-x-amp-now.md"
    assert f"| [{run_id}]({exported}) | {title} |" in (dest / KEY / "README.md").read_text()
    assert f"| [{KEY}]({KEY}/) | 1 | [{run_id}]({KEY}/{exported}) | {title} |" in (dest / "README.md").read_text()


def test_a_long_title_is_cut_short_in_an_index(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    proposed(conn, state_dir, f"# Plan: {KEY} {'word ' * 40}\n")
    dest = tmp_path / "archive"

    indexed(conn, state_dir, dest)

    assert f" | {('word ' * 20).strip()}... | " in (dest / KEY / "README.md").read_text()


def test_only_an_index_canopy_wrote_is_rewritten(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    proposed(conn, state_dir)
    other = proposed(conn, state_dir, key="PROJ-2")
    dest = tmp_path / "archive"
    (dest / KEY).mkdir(parents=True)
    (dest / "README.md").write_text("The operator's own.\n")
    # A link at the name is the operator's too, and never followed.
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("Not the export's.\n")
    (dest / KEY / "README.md").symlink_to(elsewhere)

    exported = indexed(conn, state_dir, dest)

    assert "PROJ-2/README.md" in exported.written
    assert {"README.md", f"{KEY}/README.md"}.isdisjoint(exported.written)
    assert (dest / "README.md").read_text() == "The operator's own.\n"
    assert (dest / KEY / "README.md").is_symlink()
    assert elsewhere.read_text() == "Not the export's.\n"

    # One canopy wrote is rewritten when its plans change; one whose first line the operator removed is theirs.
    canopy_wrote = (dest / "PROJ-2" / "README.md").read_text()
    assert canopy_wrote.startswith(plan_export.INDEX_MARK)
    (dest / "PROJ-2" / "README.md").write_text(canopy_wrote.removeprefix(plan_export.INDEX_MARK))
    plans.approve(conn, state_dir, "PROJ-2", channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    assert indexed(conn, state_dir, dest).written == [f"PROJ-2/{other}-APPROVED.md"]
    assert "proposed" in (dest / "PROJ-2" / "README.md").read_text()
    (dest / "PROJ-2" / "README.md").write_text(plan_export.INDEX_MARK + "An index of an earlier canopy.\n")
    assert indexed(conn, state_dir, dest).written == ["PROJ-2/README.md"]
    assert f"[{other}]({other}-APPROVED.md)" in (dest / "PROJ-2" / "README.md").read_text()


def test_an_index_says_a_plan_left_as_last_exported_is_not_as_it_stands(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    run_id = proposed(conn, state_dir)
    dest = tmp_path / "archive"
    indexed(conn, state_dir, dest)
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    plans.path_for(state_dir, KEY, run_id).unlink()

    indexed(conn, state_dir, dest)

    # Its row is approved, but the file linked is the one exported while it was proposed.
    line = f"| [{run_id}]({run_id}-PROPOSED.md) (not exported as it stands) |  | plan | approved |"
    assert line in (dest / KEY / "README.md").read_text()


@pytest.mark.usefixtures("settled")
def test_an_index_lists_a_plan_it_does_not_read(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    run_id = proposed(conn, state_dir, f"# Plan: {KEY} Export reports as CSV\n")
    dest = tmp_path / "archive"
    indexed(conn, state_dir, dest)
    indexed(conn, state_dir, dest)
    before = (dest / KEY / "README.md").read_bytes()

    with (
        mock.patch.object(plans, "read", autospec=True, side_effect=plans.read) as read,
        mock.patch.object(plan_export, "_read_head", autospec=True, side_effect=plan_export._read_head) as head,  # noqa: SLF001
    ):
        assert indexed(conn, state_dir, dest).written == []
    assert (read.call_count, head.call_count) == (0, 0)

    # Its row changing changes its index, from the title kept for it, still without reading it again for that.
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    exported = indexed(conn, state_dir, dest)
    assert exported.written == [f"{KEY}/{run_id}-APPROVED-export-reports-as-csv.md", f"{KEY}/README.md", "README.md"]
    after = (dest / KEY / "README.md").read_text()
    assert after != before.decode()
    assert f"| [{run_id}]({run_id}-APPROVED-export-reports-as-csv.md) | Export reports as CSV |" in after


def test_canopy_archive_exports_and_says_what_it_did(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = prompted(conn, state_dir)
    gone = proposed(conn, state_dir, key="PROJ-2")
    plans.path_for(state_dir, "PROJ-2", gone).unlink()
    dest = tmp_path / "archive"

    assert operator("archive", str(dest)) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"wrote {KEY}/{run_id}-PROPOSED.md",
        f"wrote {KEY}/{run_id}-PROMPT.md",
        f"wrote {KEY}/README.md",
        "wrote PROJ-2/README.md",
        "wrote README.md",
        f"skipped PROJ-2's plan of run {gone}: its file is missing",
        f"Exported 1 plan, 1 prompt and 3 READMEs to {dest}; 0 unchanged, 1 skipped.",
    ]
    assert front_matter(dest / KEY / f"{run_id}-PROPOSED.md")[1] == PLAN
    # A plan with no file is listed all the same, with nothing to link.
    assert f"| {gone} (not exported) |  | plan | proposed |" in (dest / "PROJ-2" / "README.md").read_text()


def test_canopy_archive_exports_conversations_when_asked(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = proposed(conn, state_dir)
    said(conn)
    dest = tmp_path / "archive"

    assert operator("archive", str(dest), "--conversations") == 0
    assert capsys.readouterr().out.splitlines() == [
        f"wrote {KEY}/{run_id}-PROPOSED.md",
        f"wrote {KEY}/CONVERSATION.md",
        f"wrote {KEY}/README.md",
        "wrote README.md",
        f"Exported 1 plan, 0 prompts, 1 conversation and 2 READMEs to {dest}; 0 unchanged, 0 skipped.",
    ]


@pytest.mark.parametrize("env", [conversation.TICK_ID_ENV, conversation.RUN_ID_ENV])
def test_an_agent_cannot_export_plans(
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    env: str,
) -> None:
    with mock.patch.dict(os.environ, {env: "3"}):
        assert main(["archive", str(tmp_path / "archive")]) == 1
    assert "archive refused (inside_run)" in capsys.readouterr().err
    assert not (tmp_path / "archive").exists()
