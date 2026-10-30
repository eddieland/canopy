"""A worker's answers to its checklists, checked against the lists it was given (DESIGN §42).

Every item of every list gets a row: the run's answer, or `unanswered`. An answer to an item or a repository the lists
do not hold is dropped and named, and so is one that is no answer; neither costs the run its result. `canopy checklist`
counts them per repository and item, over a hand-written journal.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.cli import checklist
from canopy.cli.main import main
from canopy.core import checklist_answers, checklists
from canopy.core.checklist_answers import Answer
from canopy.core.vocab import ItemAnswer
from tests.canopy.helpers import in_zone, journal_of_answers

if TYPE_CHECKING:
    import pytest
    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv, Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def listed(repo: str, *ids: str) -> checklists.Checklist:
    """A list of `repo`'s, of an item for each of `ids`."""
    text = "\n".join(f"## {i}\nThe rule of {i}.\n" for i in ids)
    return checklists.Checklist(repo, *checklists.parse(repo, text))


API = listed("api", "general-types", "newspaper", "doc-comments")
WEB = listed("web", "no-any")


def test_each_item_is_recorded_as_the_run_answered_it() -> None:
    """A word or an object's `answer`, and `held` with its reason."""
    reported = {
        "api": {
            "general-types": "pass",
            "newspaper": {"answer": "fixed"},
            "doc-comments": {"answer": "held", "reason": "  A field of a NamedTuple, which Sphinx reads anyway.  "},
        },
        "web": {"no-any": "n/a"},
    }
    checked = checklist_answers.check([API, WEB], reported)
    assert checked.answers == (
        Answer("api", "general-types", ItemAnswer.PASSED),
        Answer("api", "newspaper", ItemAnswer.FIXED),
        Answer("api", "doc-comments", ItemAnswer.HELD, "A field of a NamedTuple, which Sphinx reads anyway."),
        Answer("web", "no-any", ItemAnswer.NOT_APPLICABLE),
    )
    assert checked.note() == ""


def test_an_item_left_out_is_unanswered() -> None:
    """A run with no `checklist`, or one that answers only some items, still records every item it was given."""
    assert [a.answer for a in checklist_answers.check([API], None).answers] == [ItemAnswer.UNANSWERED] * 3
    checked = checklist_answers.check([API, WEB], {"api": {"newspaper": "pass"}})
    assert [(a.item, a.answer) for a in checked.answers] == [
        ("general-types", ItemAnswer.UNANSWERED),
        ("newspaper", ItemAnswer.PASSED),
        ("doc-comments", ItemAnswer.UNANSWERED),
        ("no-any", ItemAnswer.UNANSWERED),
    ]
    assert checked.note() == ""


def test_answers_the_lists_do_not_hold_are_dropped_and_named() -> None:
    """An item or a repository the run was not given is dropped, and so is an answer that is none."""
    reported = {
        "api": {
            "general-types": "unanswered",
            "newspaper": {"answer": "held"},
            "doc-comments": "skipped",
            "made-up": "pass",
        },
        "docs": {"spelling": "pass"},
        "web": ["no-any"],
    }
    checked = checklist_answers.check([API, WEB], reported)
    assert {a.answer for a in checked.answers} == {ItemAnswer.UNANSWERED}
    assert checked.note() == (
        "checklist answers dropped: 'docs': no list of the run's; api 'made-up': not an item of its list; "
        "api general-types: `answer` is not fixed, held, n/a, pass; api newspaper: `held` gives no reason; "
        "api doc-comments: `answer` is not fixed, held, n/a, pass; web: not an object of items"
    )
    assert checklist_answers.check([WEB], "all pass").note() == (
        "checklist answers dropped: checklist is not an object of repositories"
    )


def test_a_reason_is_bounded() -> None:
    """A `held` item's reason is the worker's text: kept to `MAX_REASON` characters."""
    reported = {"web": {"no-any": {"answer": "held", "reason": "x" * 5000}}}
    [answer] = checklist_answers.check([WEB], reported).answers
    assert answer.reason == "x" * checklist_answers.MAX_REASON


def test_the_contract_names_each_repository_with_a_list() -> None:
    """Only a run given a list is told its push may be held; the others' prompts are as they were."""
    assert checklist_answers.contract_text([]) == ""
    text = checklist_answers.contract_text([API, WEB])
    assert text.startswith("\n\nThe operator keeps a checklist for `api`, `web`: rules no linter checks.")
    assert '"checklist":{"<repository>":' in text


def test_answers_are_counted_per_repository_and_item_over_the_window(tmp_path: Path, journals: Journals) -> None:
    """Each item in its list's order, by when its runs started: a run before the window counts for nothing."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_answers(conn, NOW)
    found = checklist_answers.counts(conn, NOW, 7)
    assert (found.days, found.repo) == (7, None)
    assert [(c.repo, c.item, c.reminded, *(c.of(a) for a in ItemAnswer)) for c in found.items] == [
        # repo, item, reminded, pass, fixed, held, n/a, unanswered
        ("api", "general-types", 3, 2, 1, 0, 0, 0),
        ("api", "newspaper", 3, 0, 1, 1, 1, 0),
        ("api", "doc-comments", 3, 1, 0, 0, 0, 2),
        ("web", "no-any", 1, 0, 0, 1, 0, 0),
    ]
    assert [(c.item, c.reminded) for c in checklist_answers.counts(conn, NOW, 1).items] == [
        ("general-types", 1),
        ("newspaper", 1),
        ("doc-comments", 1),
        ("no-any", 1),
    ]
    assert [(c.repo, c.item, c.held) for c in checklist_answers.counts(conn, NOW, 7, repo="web").items] == [
        ("web", "no-any", 1),
    ]
    assert checklist_answers.counts(conn, NOW, 7, repo="docs").items == ()


def test_the_counts_are_printed_as_a_table(tmp_path: Path, journals: Journals, snapshot: SnapshotAssertion) -> None:
    """The item ids are the operator's, printed as they are; a held item's reason is its run's, not printed here."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_answers(conn, NOW)
    with in_zone("UTC"):
        assert "\n".join(checklist.render(checklist_answers.counts(conn, NOW, 7))) == snapshot
        assert checklist.render(checklist_answers.counts(conn, NOW, 1, repo="docs")) == [
            "docs's checklist over 1 day, since 2026-10-08 UTC, by repository and item.",
            "",
            "No worker run of the window was given a list.",
        ]


def test_canopy_checklist_counts_the_last_days(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """`--repo` narrows it to one repository's list, `--days` to the last days, and `--json` prints it as data."""
    journal_of_answers(canopy_env.journal(), datetime.now(UTC))
    assert main(["checklist"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[2:4] == [
        "repo  item           reminded  pass  fixed  held  n/a  unanswered",
        "api   general-types         3     2      1     0    0           0",
    ]
    assert main(["checklist", "--repo", "web", "--days", "1", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert (found["days"], found["repo"]) == (1, "web")
    assert found["items"] == [
        {"repo": "web", "item": "no-any", "reminded": 1, "pass": 0, "fixed": 0, "held": 1, "n/a": 0, "unanswered": 0},
    ]
    # A held item's reason is the worker's text: never in the counts.
    assert main(["checklist", "--json"]) == 0
    assert "Its reason." not in capsys.readouterr().out
    assert main(["checklist", "--days", "0"]) == 2
