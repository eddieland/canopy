"""Proposals and lessons (DESIGN §28, ROADMAP M50 stage 2): workers propose, and only the operator makes a lesson."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import db, memory, memory_manage, prompts, records
from canopy.core.config import load
from canopy.core.vocab import MemoryScope, MemoryStatus, ResumeReason, RunKind
from canopy.infra import logs, resources
from canopy.loop import attention
from canopy.memory import attention as memory_attention
from canopy.memory import reconcile as memory_reconcile
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    PROMPT_VALUES,
    context,
    in_run,
    in_tick,
    memories,
    planner_does,
    present,
    with_memory,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes

if TYPE_CHECKING:
    from tests.conftest import CanopyEnv, GitPool

#: The overseer dispatches KEY's implement on its `work` branch.
WORK = dispatches(slug="work")
#: The overseer dispatches a resume of KEY to fix CI.
FIX_CI = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI])
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


def memory_modes(ticket_notes: str = "off", proposals: str = "off") -> dict[str, str]:
    """Agent memory's tiers (DESIGN §28), for the workspace's private file."""
    return {"ticket_notes": ticket_notes, "proposals": proposals}


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
    return memory_manage.promote(conn, cfg, proposed(conn, text, key=key, repo=repo, ticket=ticket)).lesson


def test_with_proposals_off_a_proposal_is_stored_nowhere(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("private", memory=memory_modes(ticket_notes="record"))
    run = scenario.run(WORK, worker=pushes(proposals=[{"key": "api-tests", "text": LESSON}]))
    assert memories(scenario.conn) == []
    assert '`"proposals":' not in run.prompt


def test_at_record_a_proposal_waits_and_a_promoted_lesson_reaches_no_prompt(
    scenario: Scenario, git_pool: GitPool
) -> None:
    conn, canopy_env = scenario.conn, scenario.env
    scenario.configures("private", memory=memory_modes(proposals="record"))
    first = scenario.run(WORK, worker=pushes(proposals=[{"key": "api-tests", "text": LESSON, "repo": "repo"}]))
    [proposal] = memories(conn)
    assert (proposal.scope, proposal.status, proposal.repo, proposal.run_id) == (
        "proposal",
        MemoryStatus.PENDING,
        "repo",
        first.id,
    )
    assert '`"proposals":' in first.prompt
    promoted = scenario.operator("memory", "promote", str(proposal.id))
    assert "It is recorded, not served: memory.proposals is record" in promoted.out
    lesson = memories(conn)[-1]
    assert (lesson.scope, lesson.author, lesson.promoted_from, lesson.body) == (
        "lesson",
        "operator",
        proposal.id,
        LESSON,
    )
    assert memories(conn)[0].status is MemoryStatus.SUPERSEDED
    text = scenario.run(FIX_CI, worker=pushes()).prompt
    assert LESSON not in text
    assert HEADING not in text
    # Long past its review date, it raises nothing while no run can read it.
    conn.execute("UPDATE memories SET review_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (lesson.id,))
    assert memory_attention.items(conn, load(canopy_env.root, canopy_env.user_file)) == []


@pytest.mark.parametrize(("kind", "private"), PROMPTS)
def test_at_use_a_lesson_reaches_every_worker_prompt(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, kind: str, *, private: bool
) -> None:
    with_memory(canopy_env, proposals="use")
    lesson = promoted(conn, canopy_env)
    proposed(conn, "A pending proposal that no prompt carries.", key="pending")
    cfg = load(canopy_env.root, canopy_env.user_file)
    rendered = memory.render(conn, cfg, key=KEY, kind=kind, repos=("repo",))
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
    # Enough lessons of 500 characters that the cap leaves some out, whatever it is.
    count = memory.MAX_LESSONS_DIGEST // 500 + 2
    ids = [promoted(conn, canopy_env, f"lesson {i} " + "z" * 500, key=f"k{i:02}").id for i in range(count)]
    # Promoted, renewed, or used: the review date says which was last. The odd keys were last, then the even ones.
    soon = datetime.now(UTC) + timedelta(days=90)
    order = ids[1::2] + ids[::2]
    conn.executemany(
        "UPDATE memories SET review_at = ? WHERE id = ?",
        [(db.format_time(soon - timedelta(days=n)), i) for n, i in enumerate(order)],
    )
    digest = memory.lessons_digest(conn, None, cite=False)
    assert 0 < len(digest.ids) < count
    assert digest.ids == tuple(sorted(order[: len(digest.ids)]))
    assert digest.left_out == count - len(digest.ids)
    left_out = f"[{digest.left_out} more lessons are left out of this prompt; `{memory.SEARCH_COMMAND}` finds them.]"
    assert left_out in digest.text


def test_with_notes_in_use_and_lessons_recording_a_cited_lesson_changes_nothing(
    scenario: Scenario, git_pool: GitPool
) -> None:
    conn = scenario.conn
    scenario.configures("private", memory=memory_modes(ticket_notes="use", proposals="record"))
    lesson = promoted(conn, scenario.env)
    text = scenario.run(WORK, worker=pushes(memory_used=[lesson.id], memory_wrong=[lesson.id])).prompt
    assert '`"memory_used":[<id>]`' in text
    assert HEADING not in text
    assert memory.get(conn, lesson.id) == lesson


def test_a_plan_hears_lessons_but_what_it_sends_of_memory_changes_nothing(
    scenario: Scenario, git_pool: GitPool
) -> None:
    conn = scenario.conn
    scenario.configures("private", memory=memory_modes(ticket_notes="use", proposals="use"))
    # From another ticket's run: a started ticket is not planned.
    lesson = promoted(conn, scenario.env, ticket="PROJ-2")
    sent = {"memory_used": [lesson.id], "memory_wrong": [lesson.id], "proposals": [{"key": "more", "text": "More."}]}
    planner = planner_does(plan="# Plan\n\nDo it.\n", result={"status": "done", "summary": "planned it", **sent})
    run = scenario.run(dispatches(kind=RunKind.PLAN), worker=planner)
    assert HEADING in run.prompt
    # Its prompt carries no contract, so it cites and proposes nothing (DESIGN §28, Proposals and lessons).
    assert memory.get(conn, lesson.id) == lesson
    assert [m.id for m in memories(conn) if m.status is MemoryStatus.PENDING] == []


def test_a_used_lesson_is_pushed_back_from_review_and_a_wrong_one_raises_lesson_wrong(
    scenario: Scenario, git_pool: GitPool
) -> None:
    conn, canopy_env = scenario.conn, scenario.env
    scenario.configures("private", memory=memory_modes(proposals="use"))
    used = promoted(conn, canopy_env)
    wrong = promoted(conn, canopy_env, "Never run the linter.", key="lint")
    soon = db.format_time(datetime.now(UTC) + timedelta(days=1))
    conn.execute("UPDATE memories SET review_at = ? WHERE scope = 'lesson'", (soon,))
    run = scenario.run(WORK, worker=pushes(memory_used=[used.id, wrong.id], memory_wrong=[wrong.id]))
    after_used, after_wrong = memory.get(conn, used.id), memory.get(conn, wrong.id)
    assert after_used is not None
    assert after_wrong is not None
    assert after_used.review_at is not None
    assert after_used.review_at > db.format_time(datetime.now(UTC) + timedelta(days=89))
    # The operator's word: reported wrong, not retired, and not counted as used.
    assert (after_wrong.status, after_wrong.wrong_run_id, after_wrong.use_count) == (
        MemoryStatus.ACTIVE,
        run.id,
        0,
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    [item] = memory_attention.items(conn, cfg)
    assert (item.ticket_key, item.reason) == (None, "lesson_wrong")
    assert f"lesson {wrong.id} (run {run.id}) wrong" in item.detail
    scenario.operator("memory", "renew", str(wrong.id))
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


@pytest.mark.parametrize("args", [["promote", "1"], ["reject", "1"], ["renew", "1"], ["edit", "1", "--text", "x"]])
def test_promote_reject_renew_and_edit_refuse_inside_a_run(
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
        memory_manage.promote(conn, load(canopy_env.root, canopy_env.user_file), proposal)


def test_promote_takes_the_operators_words_and_supersedes_the_lesson_under_its_key(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, proposals="use")
    first = promoted(conn, canopy_env)
    cfg = load(canopy_env.root, canopy_env.user_file)
    again = memory_manage.promote(conn, cfg, proposed(conn, "Different words."), text="  Use `make test-api`. ")
    assert again.superseded == first.id
    assert (again.lesson.body, again.served) == ("Use `make test-api`.", True)
    old = present(memory.get(conn, first.id))
    assert (old.status, old.why) == (MemoryStatus.SUPERSEDED, f"superseded by lesson {again.lesson.id}")
    with pytest.raises(Exception, match="hides text"):
        memory_manage.promote(conn, cfg, proposed(conn, "Third."), text="bad\u202etext")


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
    again = memory_manage.promote(
        conn, load(canopy_env.root, canopy_env.user_file), noted(conn, "Run `make lint` twice.")
    )
    assert (again.lesson.repo, again.superseded) == (None, lesson.id)


def test_promote_refuses_a_lesson_a_forgotten_note_and_a_repository_not_in_the_map(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="record")
    cfg = load(canopy_env.root, canopy_env.user_file)
    lesson = promoted(conn, canopy_env)
    with pytest.raises(Exception, match=f"no proposal or note has id {lesson.id}"):
        memory_manage.promote(conn, cfg, lesson.id)
    note = noted(conn, "Run `make lint` twice.")
    capsys.readouterr()
    assert main(["memory", "promote", str(note), "--repo", "nowhere"]) == 1
    assert "'nowhere' is not a repository in this workspace (repo)" in capsys.readouterr().err
    memory_manage.forget(conn, note)
    with pytest.raises(Exception, match=f"note {note}'s text is gone: forgotten"):
        memory_manage.promote(conn, cfg, note)
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


def test_edit_writes_a_new_version_and_keeps_the_old_one_as_the_lessons_history(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="use")
    first = promoted(conn, canopy_env)
    # A run reported it wrong: the edit is the operator's answer, so the new version carries no report.
    reporter = present(memory.get(conn, present(first.promoted_from))).run_id
    conn.execute("UPDATE memories SET wrong_at = ?, wrong_run_id = ? WHERE id = ?", (db.now(), reporter, first.id))
    words = "Run the API's tests with `make test-api`, which loads its fixtures."
    assert main(["memory", "edit", str(first.id), "--text", f"  {words} "]) == 0
    lesson = memories(conn)[-1]
    assert capsys.readouterr().out == (
        f"Lesson {first.id} is edited into lesson {lesson.id} (`api-tests`), version 2, due for review at "
        f"{lesson.review_at}. Lesson {first.id} stays in its history.\n"
        "Every run dispatched from now on reads the new version.\n"
    )
    assert (lesson.key, lesson.body, lesson.status, lesson.author) == ("api-tests", words, "active", "operator")
    assert (lesson.supersedes, lesson.promoted_from, lesson.wrong_at, lesson.use_count) == (first.id, first.id, None, 0)
    assert memory.edited(lesson)
    assert not memory.edited(first)
    old = present(memory.get(conn, first.id))
    assert (old.status, old.why, old.body) == (MemoryStatus.SUPERSEDED, f"edited into lesson {lesson.id}", LESSON)
    # Runs are served the new words alone.
    assert memory.lessons_digest(conn, None, cite=True).ids == (lesson.id,)
    # The lesson still names the proposal it was promoted from, past the edit.
    proposal = present(memory.origin(conn, lesson))
    assert (proposal.scope, proposal.id) == (MemoryScope.PROPOSAL, first.promoted_from)
    assert main(["memory", "lessons"]) == 0
    assert f"edited from lesson {first.id} at {lesson.approved_at} from proposal {proposal.id};" in (
        capsys.readouterr().out
    )
    assert main(["memory", "history", str(first.id)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Lesson `api-tests`: 2 versions, newest first.\n")
    assert out.index(f"v2  {lesson.id}  active;") < out.index(f"v1  {first.id}  superseded, edited into lesson")
    assert f"v1  {first.id}  superseded, edited into lesson {lesson.id}; promoted at" in out
    assert out.count("  <-") == 1


def test_edit_moves_a_lesson_between_repositories_and_a_promote_over_it_is_its_next_version(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, proposals="record")
    cfg = load(canopy_env.root, canopy_env.user_file)
    first = promoted(conn, canopy_env)
    narrowed = memory_manage.edit(conn, cfg, first.id, repo="repo", repos=["repo"])
    assert (narrowed.lesson.repo, narrowed.lesson.body, narrowed.version, narrowed.served) == ("repo", LESSON, 2, False)
    widened = memory_manage.edit(conn, cfg, narrowed.lesson.id, every_repo=True)
    assert (widened.lesson.repo, widened.version) == (None, 3)
    again = memory_manage.promote(conn, cfg, proposed(conn, "Different words."))
    assert again.superseded == widened.lesson.id
    assert not memory.edited(again.lesson)
    versions = memory.history(conn, narrowed.lesson.id)
    assert [m.id for m in versions] == [again.lesson.id, widened.lesson.id, narrowed.lesson.id, first.id]
    assert [memory.version(conn, m) for m in versions] == [4, 3, 2, 1]
    # A lesson forgotten ends its history: one promoted under its key after starts another.
    memory_manage.forget(conn, again.lesson.id)
    fresh = memory_manage.promote(conn, cfg, proposed(conn, "Third words.")).lesson
    assert [m.id for m in memory.history(conn, fresh.id)] == [fresh.id]
    assert len(memory.history(conn, first.id)) == 4


@pytest.mark.parametrize(
    ("args", "refusal"),
    [
        (["--text", f" {LESSON}"], "(unchanged): lesson {id} already says that, to every run"),
        (["--every-repo"], "(unchanged): lesson {id} already says that, to every run"),
        (["--repo", "nowhere"], "(unknown_repo): 'nowhere' is not a repository in this workspace (repo)"),
        (["--text", "x" * 601], "(bad_text): the lesson's its text is 601 characters, over 600"),
        (["--text", "bad\u202etext"], "(bad_text): the lesson's its text holds U+202E"),
    ],
)
def test_edit_refuses_what_changes_nothing_or_breaks_the_bounds(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    refusal: str,
) -> None:
    with_memory(canopy_env, proposals="record")
    lesson = promoted(conn, canopy_env)
    capsys.readouterr()
    assert main(["memory", "edit", str(lesson.id), *args]) == 1
    assert f"edit refused {refusal.format(id=lesson.id)}" in capsys.readouterr().err
    assert [m.id for m in memory.history(conn, lesson.id)] == [lesson.id]


def test_edit_takes_only_a_lesson_in_force_and_needs_proposals_on(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="record")
    first = promoted(conn, canopy_env)
    assert main(["memory", "edit", str(first.id)]) == 2
    assert "name what changes: --text, --repo, or --every-repo" in capsys.readouterr().err
    assert main(["memory", "edit", str(first.id), "--repo", "repo", "--every-repo"]) == 2
    capsys.readouterr()
    assert main(["memory", "edit", str(first.id), "--text", "Newer words."]) == 0
    capsys.readouterr()
    # The old version is history now: an edit names the version in force.
    assert main(["memory", "edit", str(first.id), "--text", "Newest words."]) == 1
    assert (
        f"edit refused (unknown): no lesson in force has id {first.id}: superseded, edited into lesson"
        in capsys.readouterr().err
    )
    assert main(["memory", "edit", str(first.promoted_from), "--text", "A proposal."]) == 1
    assert f"no lesson in force has id {first.promoted_from}" in capsys.readouterr().err
    with_memory(canopy_env, ticket_notes="use")
    assert main(["memory", "edit", str(memories(conn)[-1].id), "--text", "Off."]) == 1
    assert "edit refused (off): memory.proposals is off" in capsys.readouterr().err


def test_forgetting_a_lesson_names_the_versions_that_keep_their_text(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, proposals="record")
    cfg = load(canopy_env.root, canopy_env.user_file)
    first = promoted(conn, canopy_env)
    lesson = memory_manage.edit(conn, cfg, first.id, text="Newer words.").lesson
    assert main(["memory", "forget", str(lesson.id)]) == 0
    assert (
        f"Its other versions keep their text ({first.id}): forget each too if the words must go. "
        f"`canopy memory history {lesson.id}` shows them.\n"
    ) in capsys.readouterr().out
    assert main(["memory", "forget", str(first.id)]) == 0
    assert "other versions" not in capsys.readouterr().out
    assert [m.body for m in memory.history(conn, lesson.id)] == [None, None]


def test_a_notes_history_is_each_note_under_its_key(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, ticket_notes="use")
    first = noted(conn, "The lint step fails on a stale cache.", status="superseded")
    with in_tick(conn) as tick_id:
        cur = conn.execute(
            "INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, tick_id, supersedes, "
            "created_at) VALUES ('ticket', ?, 'lint', 'Clearing the cache fixed lint.', 'active', 'worker', "
            "(SELECT run_id FROM memories WHERE id = ?), ?, ?, ?)",
            (KEY, first, tick_id, first, db.now()),
        )
    second = int(cur.lastrowid or 0)
    assert [m.id for m in memory.history(conn, first)] == [second, first]
    assert main(["memory", "history", str(second)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"Note `lint` of {KEY}: 2 versions, newest first.\n")
    assert f"v2  {second}  active; by run" in out
    assert main(["memory", "history", "999"]) == 1
    assert "no memory has id 999" in capsys.readouterr().err


def test_reject_ends_a_proposal(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, proposals="record")
    proposal = proposed(conn)
    assert main(["memory", "reject", str(proposal)]) == 0
    assert (memories(conn)[0].status, memories(conn)[0].why) == (MemoryStatus.INVALID, "rejected")
    assert main(["memory", "promote", str(proposal)]) == 1


def test_proposals_past_the_bounds_are_refused(scenario: Scenario, git_pool: GitPool) -> None:
    conn = scenario.conn
    scenario.configures("private", memory=memory_modes(proposals="record"))
    promoted(conn, scenario.env)
    run = scenario.run(
        WORK,
        worker=pushes(
            proposals=[
                {"key": "elsewhere", "text": "About a repository this run never leased.", "repo": "web"},
                {"key": "repeat", "text": LESSON.lower()},
                {"key": "fine", "text": "Fine."},
                {"key": "fourth", "text": "Past the cap."},
            ]
        ),
    )
    assert [m.key for m in memory.pending_proposals(conn)] == ["fine"]
    rendered = present(memory.run_memory(conn, run.id))
    assert [(r.key, r.why) for r in memory.refused_of(rendered)] == [
        ("elsewhere", "its repository is not one the run worked in"),
        ("repeat", f"it repeats lesson {memories(conn)[1].id}"),
        ("fourth", "past the 3 proposals a run may make"),
    ]


def test_the_queue_refuses_the_twenty_first_pending_proposal(scenario: Scenario, git_pool: GitPool) -> None:
    conn = scenario.conn
    scenario.configures("private", memory=memory_modes(proposals="record"))
    for i in range(memory.MAX_PENDING):
        proposed(conn, f"Proposal {i}.", key=f"p{i}")
    run = scenario.run(WORK, worker=pushes(proposals=[{"key": "one-more", "text": "The twenty-first."}]))
    assert len(memory.pending_proposals(conn)) == memory.MAX_PENDING
    rendered = present(memory.run_memory(conn, run.id))
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


def test_a_done_tickets_pending_proposals_raise_memory_proposal_for_the_operator_alone(scenario: Scenario) -> None:
    conn = scenario.conn
    scenario.configures("private", memory=memory_modes(proposals="record"))
    ids = [proposed(conn, key="api-tests"), proposed(conn, "Another one.", key="other")]
    cfg = load(scenario.env.root, scenario.env.user_file)
    assert memory_attention.items(conn, cfg) == []
    db.set_ticket(conn, KEY, "repo", done=True)
    [item] = memory_attention.items(conn, cfg)
    assert (item.ticket_key, item.reason) == (KEY, "memory_proposal")
    assert item.detail.startswith(f"proposals {ids[0]}, {ids[1]} from {KEY}'s runs wait on you")
    scenario.tick()
    assert scenario.attention() == [(KEY, "memory_proposal")]
    assert "memory_proposal" not in str(scenario.state())
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


def test_the_memory_listings_print_json_for_an_agent_to_read(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, ticket_notes="record", proposals="record")
    note = noted(conn, "Run `make lint`\u200b first.", private=True)
    proposal = proposed(conn, repo="repo")
    lesson = promoted(conn, canopy_env, "Use `make test-api`.", key="test-api")
    assert main(["memory", "list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["modes"] == {"ticket_notes": "record", "proposals": "record"}
    [entry] = listed["notes"]
    assert {k: entry[k] for k in ("id", "ticket", "key", "status", "run_id", "use_count", "text")} == {
        "id": note,
        "ticket": KEY,
        "key": "lint",
        "status": "active",
        "run_id": 1,
        "use_count": 0,
        # A character that hides text is named, as the text listing names it.
        "text": "Run `make lint`<U+200B> first.",
    }
    assert main(["memory", "proposals", "--json"]) == 0
    [waiting] = json.loads(capsys.readouterr().out)["proposals"]
    assert {k: v for k, v in waiting.items() if k != "created_at"} == {
        "id": proposal,
        "key": "api-tests",
        "repo": "repo",
        "ticket": KEY,
        "run_id": 2,
        "run_kind": "implement",
        "run_status": "done",
        "private": False,
        "ticket_done": False,
        "text": LESSON,
    }
    assert main(["memory", "lessons", "--json"]) == 0
    [served] = json.loads(capsys.readouterr().out)["lessons"]
    assert {k: served[k] for k in ("id", "key", "repo", "made", "from", "use_count", "wrong_at", "text")} == {
        "id": lesson.id,
        "key": "test-api",
        "repo": None,
        "made": "promoted",
        "from": {"scope": "proposal", "id": lesson.promoted_from, "ticket": KEY, "run_id": 3},
        "use_count": 0,
        "wrong_at": None,
        "text": "Use `make test-api`.",
    }
    assert served["review_at"] == lesson.review_at


@pytest.mark.parametrize(
    "args",
    [
        ["memory", "list", KEY, "--digest", "--json"],
        ["memory", "list", "--run", "1", "--json"],
        ["memory", "lessons", "--digest", "--json"],
    ],
)
def test_json_is_for_the_listings_not_a_digest_or_a_run(canopy_env: CanopyEnv, args: list[str]) -> None:
    assert main(args) == 2


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
