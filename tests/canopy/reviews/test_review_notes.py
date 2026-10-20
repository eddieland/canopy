"""Review notes (DESIGN §28): what a review of a ticket's PR leaves for its later reviews, and no worker reads."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import memory, review_notes
from canopy.core.vocab import MemoryMode, MemoryStatus, ReviewRunStatus
from canopy.loop import gc
from tests.canopy.helpers import context, in_run, present, with_memory
from tests.canopy.review_helpers import CLEAN, FINDINGS, PR, head, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, pushes, reviews

if TYPE_CHECKING:
    from tests.conftest import CanopyEnv, GitPool

KEY = "PROJ-1"
NOTE = "The retry limit holds: attempts reset only on success. Evidence: src/retry.py:40. Next: skip it."
CONTRACT = '`"review_notes":[{"key":"<key>","text":"<note>"}]`'
HEADING = "## Notes from earlier reviews"


def noting(*notes: object, drop: list[str] | None = None, report: Mapping[str, object] = CLEAN) -> dict[str, object]:
    """A reviewer's report, `CLEAN` by default, carrying `notes` and the keys it drops."""
    sent: dict[str, object] = {**report, "review_notes": list(notes)}
    if drop is not None:
        sent["drop_review_notes"] = drop
    return sent


def note(key: str = "checked-retry-limit", text: str = NOTE) -> dict[str, object]:
    """One review note."""
    return {"key": key, "text": text}


def all_notes(conn: sqlite3.Connection) -> list[tuple[str, str, str | None, MemoryStatus]]:
    """Every review note in the journal, as (ticket, key, text, status), the oldest first."""
    found = sorted(review_notes.notes(conn, every=True), key=lambda n: n.id)
    return [(n.ticket_key, n.key, n.body, n.status) for n in found]


def second_commit(scenario: Scenario, git_pool: GitPool) -> str:
    """The author pushes once, so its PR has a commit no review has read yet.

    Returns:
        The commit the worker pushed.
    """
    scenario.run(worker=pushes(pr=PR))
    return present(git_pool.remote_head(f"agent/{KEY}-work"))


@pytest.fixture
def recording(reviewing: CanopyEnv, scenario: Scenario) -> CanopyEnv:
    """Reviews on for the loop's own PRs, with review notes at `record`."""
    scenario.configures("private", memory={"review_notes": "record"})
    return reviewing


@pytest.fixture
def using(reviewing: CanopyEnv, scenario: Scenario) -> CanopyEnv:
    """Reviews on for the loop's own PRs, with review notes at `use`."""
    scenario.configures("private", memory={"review_notes": "use"})
    return reviewing


def test_with_review_notes_off_a_note_a_reviewer_sends_is_stored_nowhere(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    reviewed = scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note())))
    assert reviewed.status == ReviewRunStatus.DONE
    assert all_notes(scenario.conn) == []
    assert review_notes.review_memory(scenario.conn, reviewed.id) is None
    assert CONTRACT not in reviewed.prompt
    assert "review_notes" not in str(reviewed.row.result_json)


def test_at_record_a_note_is_stored_for_the_ticket_and_reaches_no_review(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    first = scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note())))
    assert CONTRACT in first.prompt
    assert '"drop_review_notes"' not in first.prompt
    [written] = review_notes.notes(scenario.conn)
    assert (written.ticket_key, written.key, written.body) == (KEY, "checked-retry-limit", NOTE)
    assert (written.review_run_id, written.sha) == (first.id, first.row.sha)
    assert "review_notes" not in str(first.row.result_json)
    second = scenario.review(reviews(second_commit(scenario, git_pool), ticket=KEY), reviewer=reviewer_reports(CLEAN))
    assert CONTRACT in second.prompt
    assert NOTE not in second.prompt
    assert HEADING not in second.prompt
    rendered = present(review_notes.review_memory(scenario.conn, second.id))
    assert rendered.review_notes == MemoryMode.RECORD
    assert review_notes.read_by(scenario.conn, second.id) == []


def test_at_use_a_later_review_reads_its_tickets_notes_and_drops_what_no_longer_holds(
    using: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    gone = "The cache key ignores the region. Evidence: src/cache.py:12. Next: check it again."
    first = scenario.review(
        reviews(head(git_pool), ticket=KEY),
        reviewer=reviewer_reports(noting(note(), note("risk-cache-key", gone), report=FINDINGS)),
    )
    assert HEADING in first.prompt
    assert "None: no earlier review of this ticket's PR left a note." in first.prompt
    sha = second_commit(scenario, git_pool)
    second = scenario.review(
        reviews(sha, ticket=KEY), reviewer=reviewer_reports(noting(drop=["risk-cache-key", "never-shown"]))
    )
    section = second.prompt.split(f"{HEADING}\n\n", 1)[1].split("## What to do", 1)[0]
    kept, dropped = sorted(review_notes.notes(scenario.conn, every=True), key=lambda n: n.key)
    assert f"Review note {kept.id}, `checked-retry-limit`, from review {first.id} of `{first.row.sha[:12]}`" in section
    assert f"> {NOTE}" in section
    assert "No worker reads these notes, and they do not narrow this review" in section
    assert '"drop_review_notes"' in second.prompt
    assert [n.id for n in review_notes.read_by(scenario.conn, second.id)] == sorted([kept.id, dropped.id])
    assert (kept.status, dropped.status) == (MemoryStatus.ACTIVE, MemoryStatus.INVALID)
    assert dropped.why == f"dropped by review {second.id}"


def test_a_note_under_a_key_supersedes_the_one_before_it(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note())))
    revised = "The retry limit holds at three. Evidence: tests/test_retry.py:8. Next: skip it."
    later = scenario.review(
        reviews(second_commit(scenario, git_pool), ticket=KEY),
        reviewer=reviewer_reports(noting(note(text=revised))),
    )
    old, new = sorted(review_notes.notes(scenario.conn, every=True), key=lambda n: n.id)
    assert (old.status, old.why) == (MemoryStatus.SUPERSEDED, f"superseded by review note {new.id}")
    assert (new.body, new.supersedes, new.review_run_id) == (revised, old.id, later.id)


def test_entries_past_the_bounds_are_refused_alone_and_recorded(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    sent = [
        note(),
        note("checked-token", "The token is ghp_" + "a" * 36 + ". Evidence: none. Next: none."),
        note("Not A Key"),
        "a note",
        *(note(f"checked-{i}", f"Note {i}. Evidence: a.py:{i}. Next: none.") for i in range(4)),
    ]
    reviewed = scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(*sent)))
    # Five entries are read, the bad ones among them: one bad entry costs only itself, and the rest past five.
    assert [k for _, k, _, _ in all_notes(scenario.conn)] == ["checked-retry-limit", "checked-0"]
    refused = review_notes.review_memory(scenario.conn, reviewed.id)
    assert refused is not None
    assert [(r.field, r.key) for r in memory.refused_of(refused)] == [
        ("review_notes", "checked-token"),
        ("review_notes", None),
        ("review_notes", None),
        ("review_notes", "checked-1"),
        ("review_notes", "checked-2"),
        ("review_notes", "checked-3"),
    ]


def test_a_review_of_a_pr_with_no_ticket_gets_no_notes(using: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    reviewed = scenario.review(reviews(head(git_pool), f"{PR}0"), reviewer=reviewer_reports(noting(note())))
    assert reviewed.status == ReviewRunStatus.DONE
    assert CONTRACT not in reviewed.prompt
    assert HEADING not in reviewed.prompt
    assert review_notes.review_memory(scenario.conn, reviewed.id) is None
    assert all_notes(scenario.conn) == []


def test_no_worker_reads_a_review_note(using: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("private", memory={"ticket_notes": "use", "review_notes": "use"})
    scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note())))
    worked = scenario.run(worker=pushes())
    assert NOTE not in worked.prompt
    assert HEADING not in worked.prompt
    assert CONTRACT not in worked.prompt


def test_an_override_without_the_placeholders_serves_until_the_tier_records(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}} at {{SHA}} in {{CHECKOUT}}.\n")
    reviewed = scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(CLEAN))
    assert reviewed.status == ReviewRunStatus.DONE
    scenario.configures("private", memory={"review_notes": "record"})
    [(action, rationale)] = scenario.refuses(reviews(second_commit(scenario, git_pool), ticket=KEY))[-1:]
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{REVIEW_MEMORY_CONTRACT}}" in rationale


@pytest.mark.parametrize("how", ["done", "forget"])
def test_done_and_forget_invalidate_a_tickets_review_notes(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool, how: str
) -> None:
    scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note())))
    if how == "done":
        scenario.overseer("ticket", "set", KEY, "--done")
        why = "ticket done"
    else:
        scenario.operator("forget", KEY)
        why = "forgotten work"
    [ended] = review_notes.notes(scenario.conn, every=True)
    assert (ended.status, ended.why, ended.body) == (MemoryStatus.INVALID, why, NOTE)


def test_a_review_still_running_when_its_ticket_is_done_writes_no_notes(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    held = scenario.starts_review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note())))
    scenario.overseer("ticket", "set", KEY, "--done")
    assert held.finishes().status == ReviewRunStatus.DONE
    assert all_notes(scenario.conn) == []


def test_memory_review_notes_says_the_mode_first_and_lists_what_reviewers_wrote(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    reviewed = scenario.review(
        reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note(), note("Bad")))
    )
    [written] = review_notes.notes(scenario.conn)
    out = scenario.operator("memory", "review-notes").out
    assert "review notes: Recording only. Reviewers write these notes; no review reads them.\n" in out
    assert f"\n{KEY}:\n  {written.id}  `checked-retry-limit`  active; by review {reviewed.id} of " in out
    assert NOTE in out
    out = scenario.operator("memory", "review-notes", "--review", str(reviewed.id)).out
    assert f"Review {reviewed.id} (of {KEY} at `{reviewed.row.sha[:12]}`), rendered with review notes recording." in out
    assert "Read: none, recording only" in out
    assert "Refused:\n  review_notes: its key is not lowercase words joined by hyphens" in out
    out = scenario.operator("memory", "review-notes", KEY, "--digest").out
    assert f"{KEY}'s review notes, would be served at use:\n\n{HEADING}\n\n" in out
    assert f"Review note {written.id}, `checked-retry-limit`, from review {reviewed.id}" in out


def test_forget_and_purge_reach_review_notes_and_leave_no_text_in_the_journal_file(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    leaked = "The staging password is hunter2-but-longer. Evidence: none. Next: none."
    first = scenario.review(
        reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note(), note("checked-staging", leaked)))
    )
    by_key = {n.key: n for n in review_notes.notes(scenario.conn)}
    out = scenario.operator("memory", "forget", "--review-note", str(by_key["checked-staging"].id)).out
    assert f"Review note {by_key['checked-staging'].id} (`checked-staging` of {KEY}) is forgotten" in out
    for path in (recording.state_dir / name for name in ("canopy.db", "canopy.db-wal")):
        if path.exists():
            assert leaked.encode() not in path.read_bytes(), path
    assert "Purged 1 memory of review" in scenario.operator("memory", "purge", "--review", str(first.id)).out
    assert [(body, status) for _, _, body, status in all_notes(scenario.conn)] == [
        (None, MemoryStatus.INVALID),
        (None, MemoryStatus.INVALID),
    ]


@pytest.mark.parametrize("args", [["forget", "--review-note", "1"], ["purge", "--review", "1"]])
def test_forget_and_purge_of_review_notes_refuse_inside_a_run(canopy_env: CanopyEnv, args: list[str]) -> None:
    with_memory(canopy_env, review_notes="record")
    with in_run(7):
        assert main(["memory", *args]) == 1


def test_purge_of_a_ticket_reaches_its_review_notes(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note())))
    scenario.operator("memory", "purge", "--ticket", KEY)
    assert all_notes(scenario.conn) == [(KEY, "checked-retry-limit", None, MemoryStatus.INVALID)]


def test_gc_counts_the_text_of_review_notes_no_longer_in_force(
    recording: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.review(reviews(head(git_pool), ticket=KEY), reviewer=reviewer_reports(noting(note())))
    scenario.overseer("ticket", "set", KEY, "--done")
    [kind] = [k for k in gc.measure(context(recording), datetime.now(UTC)).kinds if k.name == "memory text"]
    assert (kind.count, kind.size) == (1, len(NOTE.encode()))
