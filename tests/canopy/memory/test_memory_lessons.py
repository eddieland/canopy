"""Proposals and lessons (DESIGN §28, ROADMAP M50 stage 2): workers propose, and only the operator makes a lesson."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import db, memory, prompts, records
from canopy.core.config import load
from canopy.core.vocab import MemoryScope, MemoryStatus, RunKind
from canopy.infra import logs, resources
from canopy.loop import attention
from canopy.memory import attention as memory_attention
from canopy.memory import manage
from canopy.memory import reconcile as memory_reconcile
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    LABEL,
    PROMPT_VALUES,
    WORK,
    context,
    dispatch_and_run,
    in_run,
    in_tick,
    last_run,
    memories,
    overseer_does,
    planner_does,
    present,
    prompt_of,
    run_with,
    state_block,
    with_memory,
)

if TYPE_CHECKING:
    from tests.conftest import CanopyEnv

FIX_CI = ("--label", "agent-ready-tester", "--kind", "resume", "--reason", "ci")
LESSON = "Run the API's tests with `make test-api`; plain `pytest` misses its fixtures."
HEADING = "## Lessons from the operator"
VALUES = {
    **PROMPT_VALUES,
    "AUTHORIZATION": prompts.plan_authorization(KEY, ["agent-ready-alice"], private=False),
    "PLAN_FILE": ".canopy-plan.md",
    "PLAN_OUT": ".canopy-new-plan.md",
    "MAX_PLAN_CHARS": "100,000",
    "CONVERSATION": "No messages yet.",
}
PROMPTS = [(str(k), False) for k in prompts.WORKER] + [(str(k), True) for k in prompts.WORKER_PRIVATE]


def proposed(
    conn: sqlite3.Connection, text: str = LESSON, *, key: str = "api-tests", repo: str | None = None, ticket: str = KEY
) -> int:
    """A pending proposal from a run of `ticket`, written to the journal as `_run` would."""
    with in_tick(conn) as tick_id:
        db.touch_ticket(conn, ticket, "repo")
        run_id = db.insert_run(
            conn, tick_id=tick_id, key=ticket, kind=RunKind.IMPLEMENT, branch=BRANCH, slots=(), runs_dir=Path("/runs")
        )
        cur = conn.execute(
            "INSERT INTO memories (scope, ticket_key, repo, key, body, status, author, run_id, tick_id, created_at) "
            "VALUES ('proposal', ?, ?, ?, ?, 'pending', 'worker', ?, ?, ?)",
            (ticket, repo, key, text, run_id, tick_id, db.now()),
        )
        conn.execute("UPDATE runs SET status = 'done', ended_at = ? WHERE id = ?", (db.now(), run_id))
    return int(cur.lastrowid or 0)


def noted(conn: sqlite3.Connection, text: str = LESSON, *, status: str = "active", private: bool = False) -> int:
    """A ticket note of KEY's, `lint`, from an ended run, written to the journal as `_run` would."""
    with in_tick(conn) as tick_id:
        db.touch_ticket(conn, KEY, "repo")
        run_id = db.insert_run(
            conn, tick_id=tick_id, key=KEY, kind=RunKind.IMPLEMENT, branch=BRANCH, slots=(), runs_dir=Path("/runs")
        )
        cur = conn.execute(
            "INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, tick_id, created_at) "
            "VALUES ('ticket', ?, 'lint', ?, ?, 'worker', ?, ?, ?)",
            (KEY, text, status, run_id, tick_id, db.now()),
        )
        conn.execute(
            "UPDATE runs SET status = 'done', ended_at = ?, private = ? WHERE id = ?", (db.now(), private, run_id)
        )
    return int(cur.lastrowid or 0)


def promoted(
    conn: sqlite3.Connection,
    canopy_env: CanopyEnv,
    text: str = LESSON,
    *,
    key: str = "api-tests",
    repo: str | None = None,
    ticket: str = KEY,
) -> records.Memory:
    """Promote a fresh proposal of `text`, from a run of `ticket`, as the operator does."""
    cfg = load(canopy_env.root, canopy_env.user_file)
    return manage.promote(conn, cfg, proposed(conn, text, key=key, repo=repo, ticket=ticket)).lesson


@pytest.mark.usefixtures("git_pool")
def test_with_proposals_off_a_proposal_is_stored_nowhere(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run = run_with(conn, *WORK, proposals=[{"key": "api-tests", "text": LESSON}])
    assert memories(conn) == []
    assert '`"proposals":' not in prompt_of(canopy_env, int(run["id"]))


@pytest.mark.usefixtures("git_pool")
def test_at_record_a_proposal_waits_and_a_promoted_lesson_reaches_no_prompt(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="record")
    first = run_with(conn, *WORK, proposals=[{"key": "api-tests", "text": LESSON, "repo": "repo"}])
    [proposal] = memories(conn)
    assert (proposal.scope, proposal.status, proposal.repo, proposal.run_id) == (
        "proposal",
        MemoryStatus.PENDING,
        "repo",
        first["id"],
    )
    assert '`"proposals":' in prompt_of(canopy_env, int(first["id"]))
    capsys.readouterr()
    assert main(["memory", "promote", str(proposal.id)]) == 0
    assert "It is recorded, not served: memory.proposals is record" in capsys.readouterr().out
    lesson = memories(conn)[-1]
    assert (lesson.scope, lesson.author, lesson.promoted_from, lesson.body) == (
        "lesson",
        "operator",
        proposal.id,
        LESSON,
    )
    assert memories(conn)[0].status is MemoryStatus.SUPERSEDED
    run_with(conn, *FIX_CI)
    text = prompt_of(canopy_env, int(last_run(conn)["id"]))
    assert LESSON not in text
    assert HEADING not in text
    # Long past its review date, it raises nothing while no run can read it.
    conn.execute("UPDATE memories SET review_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (lesson.id,))
    assert memory_attention.items(conn, load(canopy_env.root, canopy_env.user_file)) == []


@pytest.mark.parametrize(("kind", "private"), PROMPTS)
def test_at_use_a_lesson_reaches_every_worker_prompt_but_a_splits(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, kind: str, *, private: bool
) -> None:
    with_memory(canopy_env, proposals="use")
    lesson = promoted(conn, canopy_env)
    proposed(conn, "A pending proposal that no prompt carries.", key="pending")
    cfg = load(canopy_env.root, canopy_env.user_file)
    rendered = memory.render(conn, cfg, key=KEY, kind=kind, repos=("repo",))
    if kind == RunKind.SPLIT:
        assert rendered is None
        return
    assert rendered is not None
    assert rendered.ids == (lesson.id,)
    text = prompts.render_worker(cfg, kind, {**VALUES, **rendered.values}, private=private, required=rendered.required)
    assert f"\n\n{HEADING}\n\nLessons the operator promoted" in text
    assert f"Lesson {lesson.id}, `api-tests`:\n> {LESSON}" in text
    assert "A pending proposal that no prompt carries." not in text
    cites = kind in memory.NOTE_KINDS
    assert ("`memory_used`" in text) is cites


def test_the_reviewers_prompt_has_no_place_for_lessons() -> None:
    assert "{{WORKSPACE_LESSONS}}" not in (resources.prompts_dir() / prompts.REVIEWER).read_text()


def test_a_lesson_for_one_repository_stays_out_of_anothers_runs(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, proposals="use")
    every = promoted(conn, canopy_env, "Commit messages name the ticket.", key="ticket-key")
    api = promoted(conn, canopy_env, LESSON, repo="api")
    assert memory.lessons_digest(conn, ("api",), cite=True).ids == (api.id, every.id)
    assert memory.lessons_digest(conn, ("web",), cite=True).ids == (every.id,)


def test_the_lessons_digest_keeps_those_last_vouched_for_in_key_order(
    conn: sqlite3.Connection, canopy_env: CanopyEnv
) -> None:
    with_memory(canopy_env, proposals="use")
    ids = [promoted(conn, canopy_env, f"lesson {i} " + "z" * 500, key=f"k{i}").id for i in range(6)]
    # Promoted, renewed, or used: the review date says which was last. k1 was last, then k3, k5, and so on down.
    soon = datetime.now(UTC) + timedelta(days=90)
    order = [ids[1], ids[3], ids[5], ids[0], ids[2], ids[4]]
    conn.executemany(
        "UPDATE memories SET review_at = ? WHERE id = ?",
        [(db.format_time(soon - timedelta(days=n)), i) for n, i in enumerate(order)],
    )
    digest = memory.lessons_digest(conn, None, cite=False)
    assert 0 < len(digest.ids) < 6
    assert digest.ids == tuple(sorted(order[: len(digest.ids)]))
    assert digest.left_out == 6 - len(digest.ids)
    left_out = f"[{digest.left_out} more lessons are left out of this prompt; `{memory.SEARCH_COMMAND}` finds them.]"
    assert left_out in digest.text


@pytest.mark.usefixtures("git_pool")
def test_with_notes_in_use_and_lessons_recording_a_cited_lesson_changes_nothing(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, ticket_notes="use", proposals="record")
    lesson = promoted(conn, canopy_env)
    run = run_with(conn, *WORK, memory_used=[lesson.id], memory_wrong=[lesson.id])
    text = prompt_of(canopy_env, int(run["id"]))
    assert '`"memory_used":[<id>]`' in text
    assert HEADING not in text
    assert memory.get(conn, lesson.id) == lesson


@pytest.mark.usefixtures("git_pool")
def test_a_plan_hears_lessons_but_what_it_sends_of_memory_changes_nothing(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, ticket_notes="use", proposals="use")
    # From another ticket's run: a started ticket is not planned.
    lesson = promoted(conn, canopy_env, ticket="PROJ-2")
    sent = {"memory_used": [lesson.id], "memory_wrong": [lesson.id], "proposals": [{"key": "more", "text": "More."}]}
    with planner_does(plan="# Plan\n\nDo it.\n", result={"status": "done", "summary": "planned it", **sent}):
        run = dispatch_and_run(conn, "--label", LABEL, "--kind", "plan")
    assert HEADING in prompt_of(canopy_env, int(run["id"]))
    # Its prompt carries no contract, so it cites and proposes nothing (DESIGN §28, Proposals and lessons).
    assert memory.get(conn, lesson.id) == lesson
    assert [m.id for m in memories(conn) if m.status is MemoryStatus.PENDING] == []


@pytest.mark.usefixtures("git_pool")
def test_a_used_lesson_is_pushed_back_from_review_and_a_wrong_one_raises_lesson_wrong(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="use")
    used = promoted(conn, canopy_env)
    wrong = promoted(conn, canopy_env, "Never run the linter.", key="lint")
    soon = db.format_time(datetime.now(UTC) + timedelta(days=1))
    conn.execute("UPDATE memories SET review_at = ? WHERE scope = 'lesson'", (soon,))
    run = run_with(conn, *WORK, memory_used=[used.id, wrong.id], memory_wrong=[wrong.id])
    after_used, after_wrong = memory.get(conn, used.id), memory.get(conn, wrong.id)
    assert after_used is not None
    assert after_wrong is not None
    assert after_used.review_at is not None
    assert after_used.review_at > db.format_time(datetime.now(UTC) + timedelta(days=89))
    # The operator's word: reported wrong, not retired, and not counted as used.
    assert (after_wrong.status, after_wrong.wrong_run_id, after_wrong.use_count) == (
        MemoryStatus.ACTIVE,
        run["id"],
        0,
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    [item] = memory_attention.items(conn, cfg)
    assert (item.ticket_key, item.reason) == (None, "lesson_wrong")
    assert f"lesson {wrong.id} (run {run['id']}) wrong" in item.detail
    assert main(["memory", "renew", str(wrong.id)]) == 0
    assert memory_attention.items(conn, cfg) == []


def test_review_dates_raise_one_lesson_review_once_lessons_are_in_use(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, proposals="record")
    old = [promoted(conn, canopy_env, f"Old lesson {i}.", key=f"old-{i}").id for i in range(3)]
    fresh = promoted(conn, canopy_env, "A fresh lesson.", key="fresh")
    long_ago = db.format_time(datetime.now(UTC) - timedelta(days=200))
    conn.executemany(
        "UPDATE memories SET approved_at = ?, review_at = ? WHERE id = ?",
        [(long_ago, db.format_time(datetime.now(UTC) - timedelta(days=110)), i) for i in old],
    )
    assert memory_attention.items(conn, load(canopy_env.root, canopy_env.user_file)) == []
    with_memory(canopy_env, proposals="use")
    [item] = memory_attention.items(conn, load(canopy_env.root, canopy_env.user_file))
    assert item.reason == "lesson_review"
    assert f"lessons {', '.join(map(str, old))} are due for review" in item.detail
    assert str(fresh.id) not in item.detail.split(" are due")[0]


@pytest.mark.parametrize("args", [["promote", "1"], ["reject", "1"], ["renew", "1"]])
def test_promote_reject_and_renew_refuse_inside_a_run(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, args: list[str]
) -> None:
    with_memory(canopy_env, proposals="use")
    proposed(conn)
    with in_run(7):
        assert main(["memory", *args]) == 1
    assert memories(conn)[0].status is MemoryStatus.PENDING


def test_promote_refuses_while_proposals_are_off(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    proposal = proposed(conn)
    with pytest.raises(Exception, match=r"memory\.proposals is off"):
        manage.promote(conn, load(canopy_env.root, canopy_env.user_file), proposal)


def test_promote_takes_the_operators_words_and_supersedes_the_lesson_under_its_key(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, proposals="use")
    first = promoted(conn, canopy_env)
    cfg = load(canopy_env.root, canopy_env.user_file)
    again = manage.promote(conn, cfg, proposed(conn, "Different words."), text="  Use `make test-api`. ")
    assert again.superseded == first.id
    assert (again.lesson.body, again.served) == ("Use `make test-api`.", True)
    old = present(memory.get(conn, first.id))
    assert (old.status, old.why) == (MemoryStatus.SUPERSEDED, f"superseded by lesson {again.lesson.id}")
    with pytest.raises(Exception, match="hides text"):
        manage.promote(conn, cfg, proposed(conn, "Third."), text="bad\u202etext")


def test_promote_makes_a_note_a_lesson_and_leaves_the_note_its_tickets(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="record")
    # Its ticket marked done invalidated it, and what it taught may still be worth keeping.
    note = noted(conn, status="invalid")
    assert main(["memory", "promote", str(note), "--repo", "repo"]) == 0
    lesson = memories(conn)[-1]
    assert capsys.readouterr().out.startswith(
        f"Note {note} is lesson {lesson.id} (`lint`) for repo, due for review at {lesson.review_at}.\n"
    )
    assert (lesson.scope, lesson.author, lesson.promoted_from, lesson.repo, lesson.ticket_key, lesson.body) == (
        "lesson",
        "operator",
        note,
        "repo",
        None,
        LESSON,
    )
    assert (memories(conn)[0].status, memories(conn)[0].why) == (MemoryStatus.INVALID, None)
    assert main(["memory", "lessons"]) == 0
    assert f"from note {note} of {KEY};" in capsys.readouterr().out
    # Without --repo, a note's lesson is every repository's.
    again = manage.promote(conn, load(canopy_env.root, canopy_env.user_file), noted(conn, "Run `make lint` twice."))
    assert (again.lesson.repo, again.superseded) == (None, lesson.id)


def test_promote_refuses_a_lesson_a_forgotten_note_and_a_repository_not_in_the_map(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="record")
    cfg = load(canopy_env.root, canopy_env.user_file)
    lesson = promoted(conn, canopy_env)
    with pytest.raises(Exception, match=f"no proposal or note has id {lesson.id}"):
        manage.promote(conn, cfg, lesson.id)
    note = noted(conn, "Run `make lint` twice.")
    capsys.readouterr()
    assert main(["memory", "promote", str(note), "--repo", "nowhere"]) == 1
    assert "'nowhere' is not a repository in this workspace (repo)" in capsys.readouterr().err
    manage.forget(conn, note)
    with pytest.raises(Exception, match=f"note {note}'s text is gone: forgotten"):
        manage.promote(conn, cfg, note)
    assert [m.scope for m in memories(conn)].count(MemoryScope.LESSON) == 1


def test_promoting_a_private_tickets_note_in_its_own_words_warns(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="use")
    note = noted(conn, private=True)
    assert main(["memory", "promote", str(note)]) == 0
    out = capsys.readouterr().out
    assert "Warning: its text is from a private ticket's run" in out
    assert "Every run dispatched from now on reads it." in out
    assert main(["memory", "promote", str(note), "--text", "Run `make lint` twice."]) == 0
    assert "Warning" not in capsys.readouterr().out


def test_reject_ends_a_proposal(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, proposals="record")
    proposal = proposed(conn)
    assert main(["memory", "reject", str(proposal)]) == 0
    assert (memories(conn)[0].status, memories(conn)[0].why) == (MemoryStatus.INVALID, "rejected")
    assert main(["memory", "promote", str(proposal)]) == 1


@pytest.mark.usefixtures("git_pool")
def test_proposals_past_the_bounds_are_refused(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, proposals="record")
    promoted(conn, canopy_env)
    run = run_with(
        conn,
        *WORK,
        proposals=[
            {"key": "elsewhere", "text": "About a repository this run never leased.", "repo": "web"},
            {"key": "repeat", "text": LESSON.lower()},
            {"key": "fine", "text": "Fine."},
            {"key": "fourth", "text": "Past the cap."},
        ],
    )
    assert [m.key for m in memory.pending_proposals(conn)] == ["fine"]
    rendered = present(memory.run_memory(conn, int(run["id"])))
    assert [(r.key, r.why) for r in memory.refused_of(rendered)] == [
        ("elsewhere", "its repository is not one the run worked in"),
        ("repeat", f"it repeats lesson {memories(conn)[1].id}"),
        ("fourth", "past the 3 proposals a run may make"),
    ]


@pytest.mark.usefixtures("git_pool")
def test_the_queue_refuses_the_twenty_first_pending_proposal(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, proposals="record")
    for i in range(memory.MAX_PENDING):
        proposed(conn, f"Proposal {i}.", key=f"p{i}")
    run = run_with(conn, *WORK, proposals=[{"key": "one-more", "text": "The twenty-first."}])
    assert len(memory.pending_proposals(conn)) == memory.MAX_PENDING
    rendered = present(memory.run_memory(conn, int(run["id"])))
    assert [r.why for r in memory.refused_of(rendered)] == ["20 proposals already wait on the operator"]


def test_a_proposal_nobody_reviews_expires_after_fourteen_days(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    old, new = proposed(conn, key="old"), proposed(conn, "A newer one.", key="new")
    conn.execute(
        "UPDATE memories SET created_at = ? WHERE id = ?",
        (db.format_time(datetime.now(UTC) - timedelta(days=15)), old),
    )
    ctx = context(canopy_env)
    with in_tick(conn) as tick_id:
        assert memory_reconcile.run(ctx, logs.for_tick(tick_id)) == 1
    by_id = {m.id: m for m in memories(conn)}
    assert (by_id[old].status, by_id[old].why) == (MemoryStatus.INVALID, "expired")
    assert by_id[new].status is MemoryStatus.PENDING


@pytest.mark.usefixtures("treehouse_state")
def test_a_done_tickets_pending_proposals_raise_memory_proposal_for_the_operator_alone(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, agent_log: Path
) -> None:
    with_memory(canopy_env, proposals="record")
    ids = [proposed(conn, key="api-tests"), proposed(conn, "Another one.", key="other")]
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert memory_attention.items(conn, cfg) == []
    db.set_ticket(conn, KEY, "repo", done=True)
    [item] = memory_attention.items(conn, cfg)
    assert (item.ticket_key, item.reason) == (KEY, "memory_proposal")
    assert item.detail.startswith(f"proposals {ids[0]}, {ids[1]} from {KEY}'s runs wait on you")
    with overseer_does():
        assert main(["tick"]) == 0
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [(KEY, "memory_proposal")]
    assert "memory_proposal" not in str(state_block(agent_log))
    assert attention.for_overseer(conn) == []


def test_memory_proposals_lists_each_with_its_provenance_and_warns_of_a_private_ticket(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="record")
    proposal = proposed(conn, "Use `make test-api`\u200b.", repo="repo")
    conn.execute("UPDATE runs SET private = 1, status = 'done'")
    assert main(["memory", "proposals"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("ticket notes: Off.")
    assert "lessons: Recording only. Workers propose lessons and you may promote them; no run reads them.\n" in out
    assert (
        f"  {proposal}  `api-tests` for repo; from {KEY}, private, run 1 (implement, done), its ticket not yet done"
        in out
    )
    assert "Use `make test-api`<U+200B>." in out
    assert "Warning: from a private ticket's run" in out


def test_with_proposals_at_use_the_cli_says_lessons_are_served(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="use")
    lesson = promoted(conn, canopy_env)
    assert main(["memory", "lessons", "--digest"]) == 0
    out = capsys.readouterr().out
    assert "The lessons, served to every run:" in out
    assert f"Lesson {lesson.id}, `api-tests`:\n> {LESSON}" in out


def test_many_lessons_due_raise_one_short_item_naming_the_longest_overdue(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, proposals="use")
    ids = [promoted(conn, canopy_env, f"Lesson number {i}.", key=f"lesson-{i}").id for i in range(25)]
    # The later a lesson was promoted here, the longer it has been due.
    now = datetime.now(UTC)
    conn.executemany(
        "UPDATE memories SET review_at = ? WHERE id = ?",
        [(db.format_time(now - timedelta(days=n + 1)), i) for n, i in enumerate(ids)],
    )
    [item] = memory_attention.items(conn, load(canopy_env.root, canopy_env.user_file))
    named = ", ".join(map(str, ids[::-1][: memory_attention.MAX_NAMED]))
    assert item.detail.startswith(f"lessons {named}, and 15 more are due for review")
